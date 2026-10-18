"""Reads that grow with history are bounded by time or key (#795).

A realm-robustness review found reads of overseer_death and overseer_guild_ask
that scanned whole tables or every row a key ever had, and so grew every day:
the guild page's newest death per ghost read the whole death table (EXPLAIN:
type ALL over the outer query), the Chronicle and the recap read every death
the family ever had, the activity breakpoint counted them, and the v2
Chronicle's join by guild had no key at all (EXPLAIN ANALYZE: a backward walk
of the primary key over every row). And a slow model call held one of the
twelve threads every realm read runs on.

Two halves here:

- THE INVENTORY. Every SELECT the shipped code makes on either table, found by
  reading the source (so a new read is checked the day it is written), must
  carry a bound the table's keys serve. A death read needs a key that leads an
  index (character_name, zone, driver or killer_type) AND a time bound, or be
  one row by a key. overseer_death has no key on created_at alone yet
  (mod-overseer#908 adds one with the next worldserver roll), so a time bound
  alone still walks the table. An ask read may use its created_at key, the
  live states, one id, or one guild's newest LIMIT rows.
- THE BEHAVIOUR of each read this ticket bounded, and that model calls run on
  threads of their own.
"""

import ast
import asyncio
import concurrent.futures
import datetime
import pathlib
import re
import sys
import threading
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import achievements  # noqa: E402
import jev  # noqa: E402
import jev_activity  # noqa: E402
import llmpool  # noqa: E402
import map_server  # noqa: E402
import realmread  # noqa: E402
import recap  # noqa: E402
import vision  # noqa: E402
from apiv2 import chronicle, guild  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
TABLES = ("overseer_death", "overseer_guild_ask")


# ---- the inventory ----------------------------------------------------------


def _flat(node):
    """The text of a string expression, with `{x}` for each part that is not
    text (an f-string field, a str() of a constant); None when no part is."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) else "{x}" for v in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _flat(node.left), _flat(node.right)
        if left is None and right is None:
            return None
        return (left if left is not None else "{x}") + (
            right if right is not None else "{x}"
        )
    return None


def _statements(path: pathlib.Path):
    """(line, text) of each whole string expression in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)):
            continue
        up = parent.get(node)
        if isinstance(up, ast.JoinedStr):
            continue
        if isinstance(up, ast.BinOp) and isinstance(up.op, ast.Add):
            continue  # a piece of a longer concatenation, read whole above
        text = _flat(node)
        if text:
            yield node.lineno, " ".join(text.split())


def inventory() -> list:
    """(where, table, clause) for every read of the two tables."""
    files = sorted(HERE.glob("*.py")) + sorted((HERE / "apiv2").glob("*.py"))
    out = []
    for path in files:
        for line, text in _statements(path):
            if not text.lstrip("( ").upper().startswith("SELECT"):
                continue
            for table in TABLES:
                for m in re.finditer(r"\bFROM %s\b" % table, text):
                    rest = text[m.start() :]
                    stop = re.search(r"\bFROM\b|\bUNION\b", rest[4:])
                    clause = rest if stop is None else rest[: stop.start() + 4]
                    where = "%s:%d" % (path.relative_to(HERE), line)
                    out.append((where, table, clause))
    return out


_COL = r"\b(?:\w+\.)?"
_TIME = re.compile(_COL + r"created_at\s*(?:>=?|BETWEEN)|\{spans\}")
_DEATH_KEY = re.compile(
    _COL + r"(?:character_name|zone|driver|killer_type)\s*(?:IN\s*\(|=\s*%s)"
)
_ONE_ROW = re.compile(_COL + r"character_name\s*=\s*%s.*\bLIMIT 1\b")
_BY_ID = re.compile(_COL + r"id\s*=\s*%s")
_LIVE = "state IN ('open', 'filled')"
_ONE_GUILD = re.compile(_COL + r"guild\s*=\s*%s.*\bLIMIT\b")


def bounded(table: str, clause: str) -> bool:
    if _BY_ID.search(clause):
        return True
    if table == "overseer_death":
        if _ONE_ROW.search(clause):
            return True
        return bool(_DEATH_KEY.search(clause) and _TIME.search(clause))
    return bool(_TIME.search(clause) or _LIVE in clause or _ONE_GUILD.search(clause))


class EveryReadIsBounded(unittest.TestCase):
    def test_the_inventory_finds_the_reads(self):
        """A scanner that found nothing would pass everything."""
        found = inventory()
        files = {where.split(":")[0] for where, _, _ in found}
        for name in (
            "bridge.py",
            "map_server.py",
            "guildsocial.py",
            "guildrun.py",
            "apiv2/guild.py",
            "apiv2/chronicle.py",
            "apiv2/achievements.py",
        ):
            self.assertIn(name, files)
        self.assertGreaterEqual(len([f for f in found if f[1] == "overseer_death"]), 17)
        self.assertGreaterEqual(
            len([f for f in found if f[1] == "overseer_guild_ask"]), 10
        )

    def test_every_death_and_ask_read_is_bounded_by_time_or_key(self):
        loose = [
            "%s %s" % (where, clause)
            for where, table, clause in inventory()
            if not bounded(table, clause)
        ]
        self.assertEqual(loose, [], "\n".join(loose))

    def test_the_rule_catches_the_reads_this_ticket_bounded(self):
        """The shapes that grew, as they were, are refused."""
        for table, clause in (
            ("overseer_death", "FROM overseer_death WHERE id IN ( SELECT MAX(id) "),
            (
                "overseer_death",
                "FROM overseer_death WHERE character_name IN ({holes}) "
                "GROUP BY character_name)",
            ),
            (
                "overseer_death",
                "FROM overseer_death WHERE character_name IN (%s)",
            ),
            (
                "overseer_death",
                "FROM overseer_death d JOIN guild_member gm ON gm.guid = "
                "d.character_guid WHERE gm.guildid IN ({holes}) AND "
                "d.created_at >= NOW() - INTERVAL %s DAY",
            ),
            ("overseer_guild_ask", "FROM overseer_guild_ask WHERE kind = 'quest'"),
        ):
            self.assertFalse(bounded(table, clause), clause)


# ---- the reads ----------------------------------------------------------------


class Cursor:
    """Answers a statement by the first table it reads; records them all."""

    def __init__(self, tables):
        self.tables, self.calls, self._rows = tables, [], []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        self._rows = next(
            (rows for name, rows in self.tables.items() if "FROM " + name in sql), []
        )

    def fetchall(self):
        return list(self._rows)


class Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


START = datetime.datetime(2026, 10, 17, 20, 0, 0)
FAMILY = ["Grug", "Ugga"]


def _run(rid, started, state="active", map_id=36, ended=None):
    return {
        "id": rid,
        "leader_name": "Grug",
        "map_id": map_id,
        "state": state,
        "started_at": started,
        "last_progress_at": started,
        "ended_at": ended,
        "ended_reason": "",
        "outcome": "",
    }


def _death_reads(cur):
    return [(sql, params) for sql, params in cur.calls if "overseer_death" in sql]


class TheRecap(unittest.TestCase):
    def _fetch(self, runs):
        cur = Cursor({"overseer_dungeon_run": runs})
        with mock.patch.object(map_server, "_connect", return_value=Conn(cur)):
            map_server._fetch_recap(None, FAMILY)
        return cur

    def test_the_death_read_starts_at_the_open_run_it_draws(self):
        old = START - datetime.timedelta(days=3)
        cur = self._fetch([_run(2, START), _run(1, old, state="ended", ended=old)])
        ((sql, params),) = _death_reads(cur)
        self.assertIn("created_at >= %s", sql)
        self.assertEqual(params, (*FAMILY, START))

    def test_with_no_run_open_no_death_is_read(self):
        old = START - datetime.timedelta(days=3)
        cur = self._fetch([_run(1, old, state="ended", ended=old)])
        self.assertEqual(_death_reads(cur), [])

    def test_deaths_since_is_the_newest_open_run(self):
        later = START + datetime.timedelta(hours=1)
        self.assertEqual(recap.deaths_since([_run(1, START), _run(2, later)]), later)
        self.assertIsNone(recap.deaths_since([]))


class TheChronicleCards(unittest.TestCase):
    def _fetch(self, runs):
        cur = Cursor({"overseer_dungeon_run": runs})
        with mock.patch.object(map_server, "_connect", return_value=Conn(cur)):
            map_server._fetch_achievements(FAMILY)
        return cur

    def test_the_death_read_starts_at_the_oldest_run_on_the_runs_maps(self):
        old = START - datetime.timedelta(days=9)
        cur = self._fetch(
            [_run(2, START, map_id=43), _run(1, old, state="ended", ended=old)]
        )
        ((sql, params),) = _death_reads(cur)
        self.assertIn("created_at >= %s", sql)
        self.assertIn("map IN (%s, %s)", sql)
        self.assertEqual(params, (*FAMILY, old, 36, 43))

    def test_with_no_run_no_death_is_read(self):
        self.assertEqual(_death_reads(self._fetch([])), [])

    def test_a_death_outside_every_run_could_never_count(self):
        """death_scope only drops what in_run would drop anyway."""
        now = START + datetime.timedelta(hours=2)
        runs = [_run(1, START, map_id=36)]
        since, maps = achievements.death_scope(runs)
        before = START - datetime.timedelta(seconds=1)
        self.assertFalse(achievements.in_run(runs[0], before, 36, now))
        self.assertLess(before, since)
        self.assertFalse(achievements.in_run(runs[0], START, 43, now))
        self.assertNotIn(43, maps)


class TheGuildPage(unittest.TestCase):
    def test_each_ghost_reads_its_one_newest_death(self):
        rd = realmread.Memory(
            {
                guild._DEATH_TOTAL_SQL: [{"n": 2, "who": 2}],
                guild._KILLERS_SQL: [],
                guild._LAST_DEATHS: [
                    {
                        "name": "Bonk",
                        "killer": "Kobold",
                        "map": 0,
                        "zone": 12,
                        "at": 100,
                    },
                ],
            }
        )
        out = guild._deaths(rd, ["Grug", "Bonk", "Zug"], ["Bonk", "Zug"], {}, {})
        sql, params = rd.asked[-1]
        self.assertEqual(params, ("Bonk", "Zug"))
        self.assertEqual(sql.count("LIMIT 1)"), 2)
        self.assertEqual(sql.count(" UNION ALL "), 1)
        self.assertNotIn("MAX(id)", sql)
        self.assertEqual([g["killer"] for g in out["ghosts"]], ["Kobold", None])


class TheV2Chronicle(unittest.TestCase):
    def test_deaths_are_read_by_member_name_and_keep_their_guild(self):
        rd = realmread.Memory(
            {
                chronicle._MEMBERS_SQL: [
                    {"name": "Crag", "guild_id": 23},
                    {"name": "Brug", "guild_id": 24},
                ],
                chronicle._DEATHS_SQL: [
                    {"name": "Crag", "map": 36, "killer": "Sneed", "at": 7200},
                    {"name": "Stranger", "map": 36, "killer": "Sneed", "at": 7200},
                ],
            }
        )
        rows = chronicle._deaths(rd, [23, 24], "%s, %s", "0, 1, 530, 571")
        sql, params = rd.asked[-1]
        self.assertIn("character_name IN (%s, %s)", sql)
        self.assertNotIn("guild_member", sql)
        self.assertEqual(params, ("Brug", "Crag", chronicle.DAYS, chronicle.MAX_ROWS))
        self.assertEqual([(r["name"], r["guild_id"]) for r in rows], [("Crag", 23)])

    def test_a_guild_with_no_members_reads_no_deaths(self):
        rd = realmread.Memory({chronicle._MEMBERS_SQL: []})
        self.assertEqual(chronicle._deaths(rd, [23], "%s", "0"), [])
        self.assertEqual(len(rd.asked), 1)


class TheActivityMark(unittest.TestCase):
    def test_a_new_death_is_a_breakpoint_even_as_an_old_one_ages_out(self):
        """The mark is the newest death's id in the window. A windowed COUNT
        would read 1 before and 1 after, and miss the death."""
        before = jev_activity.Marks(None, (), 100, False, False)
        now = jev_activity.Marks(None, (), 105, False, False)
        self.assertEqual(jev_activity.stopped_at(before, now), jev_activity.AFTER_DEATH)
        aged = jev_activity.Marks(None, (), 0, False, False)
        self.assertEqual(jev_activity.stopped_at(before, aged), "")

    def test_the_read_is_the_newest_id_in_the_window(self):
        from test_guildsocial_bridge import bridge

        sql = dict(bridge._ACTIVITY_READS)["deaths"]
        self.assertIn("MAX(id) AS n", sql)
        self.assertIn(
            "created_at > NOW() - INTERVAL %d HOUR" % jev_activity.DEATH_MARK_HOURS,
            sql,
        )
        self.assertEqual(bridge._activity_shape("deaths", [{"n": None}]), 0)
        self.assertEqual(bridge._activity_shape("deaths", [{"n": 41}]), 41)


# ---- the model threads --------------------------------------------------------


def _held_default(test):
    """Run `test(loop)` with the default executor one thread wide."""

    async def go():
        loop = asyncio.get_running_loop()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(pool)
        try:
            return await test(loop)
        finally:
            pool.shutdown(wait=False)

    return asyncio.run(go())


class ModelCallsHaveTheirOwnThreads(unittest.TestCase):
    def test_a_read_does_not_wait_on_a_thread_a_slow_jev_call_holds(self):
        gate = threading.Event()
        seen = []

        async def test(loop):
            started = asyncio.Event()

            def slow(url, body, headers, timeout):
                seen.append(threading.current_thread().name)
                loop.call_soon_threadsafe(started.set)
                gate.wait(10)
                return 500, b""

            client = jev.Client("k", transport=slow, timeout=10)
            asking = asyncio.ensure_future(
                client.ask("x", "s", {"route": jev.choice("?", {"a": "a", "b": "b"})})
            )
            await asyncio.wait_for(started.wait(), 3)
            try:
                read = await asyncio.wait_for(asyncio.to_thread(lambda: "row"), 3)
            finally:
                gate.set()
                await asking
            return read

        self.assertEqual(_held_default(test), "row")
        self.assertTrue(seen[0].startswith(llmpool.PREFIX), seen)

    def test_a_vision_look_runs_on_the_model_threads(self):
        seen = []

        def transport(url, body, timeout):
            seen.append(threading.current_thread().name)
            return 404, b""

        look = asyncio.run(
            vision.Seer(
                frame_url="http://map.example/api/frame",
                vision_url="http://gateway.example/api/chat",
                transport=transport,
            ).look("Grug")
        )
        self.assertEqual(look.status, vision.NO_FRAME)
        self.assertTrue(seen and seen[0].startswith(llmpool.PREFIX), seen)

    def test_a_model_call_runs_while_every_default_thread_is_held(self):
        gate = threading.Event()

        async def test(loop):
            held = loop.run_in_executor(None, gate.wait, 10)
            try:
                return await asyncio.wait_for(
                    llmpool.call(lambda: threading.current_thread().name), 3
                )
            finally:
                gate.set()
                await held

        self.assertTrue(_held_default(test).startswith(llmpool.PREFIX))

    def test_the_bridge_asks_its_model_on_the_model_threads(self):
        source = (HERE / "bridge.py").read_text(encoding="utf-8")
        self.assertFalse("to_thread(_ask_llm" in source)
        self.assertEqual(source.count("llmpool.call(_ask_llm, prompt)"), 3)

    def test_the_image_ships_the_module(self):
        docker = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(" llmpool.py ", docker)


if __name__ == "__main__":
    unittest.main()

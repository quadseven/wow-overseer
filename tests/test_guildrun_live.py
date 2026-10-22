"""The guild coordinator live proof: the bridge forms a group, writes the
finder-run row with both judgments, the worldserver answers, the outcome is
recorded, and the Guild tab renders the run.

This drives the bridge's half of slice 1 end to end: _start_guild_run writes
the overseer_guild_run row, the two Jev judgments and the kind='guild'
finder-run command row; _follow_guild_runs reads the command's answer back and
records the run's outcome; guildrun.page shapes the Guild tab payload. The
worldserver half (mod-overseer's finder-run verb) is not in this repo, so this
test seals the Python seam: the row the bridge writes is exactly the row the
module is documented to handle (guildcorps.MODULE_GUILD_VERBS carries finder-run).
"""

import asyncio
import dataclasses
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import guildrun  # noqa: E402
import jev  # noqa: E402
import json  # noqa: E402
from test_jev_items import FakeJev  # noqa: E402


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()
bridge._COMPLETED_PASSES.add("guild_jobs")

WARRIOR, PALADIN, PRIEST, ROGUE, MAGE, WARLOCK = 1, 2, 5, 4, 8, 9
PROTECTION_TALENT = "12301"
HOLY_TALENT = "14913"


def row(name, level, class_id, **kw):
    out = {
        "name": name,
        "level": level,
        "class_id": class_id,
        "map_id": 0,
        "race": 2,
        "in_combat": 0,
        "health": 300,
        "group_leader": 0,
        "guild_name": "Cave",
        "talent_spells": None,
        "target_tree": "",
    }
    out.update(kw)
    return out


def cave_band():
    return [
        guildrun.member_from_row(
            row(
                "Tanky",
                20,
                WARRIOR,
                talent_spells=PROTECTION_TALENT,
                worn_slots=6,
                has_weapon=1,
                has_shield=1,
            )
        ),
        guildrun.member_from_row(row("Furio", 19, WARRIOR, talent_spells="61216")),
        guildrun.member_from_row(
            row(
                "Healy",
                19,
                PRIEST,
                talent_spells=HOLY_TALENT,
                worn_slots=6,
                has_weapon=1,
            )
        ),
        guildrun.member_from_row(
            row("Pally", 19, PALADIN, talent_spells="20473", worn_slots=6, has_weapon=1)
        ),
        guildrun.member_from_row(row("Stabby", 19, ROGUE, worn_slots=6, has_weapon=1)),
        guildrun.member_from_row(row("Zappy", 18, MAGE, worn_slots=6, has_weapon=1)),
        guildrun.member_from_row(row("Locky", 17, WARLOCK, worn_slots=6, has_weapon=1)),
    ]


DOORS = guildrun.doors({389: 8, 36: 10, 43: 10, 33: 14})


def decide_with(fake):
    pool = guildrun.Pool("Cave", tuple(cave_band()))
    plan = guildrun.plan_for(pool, DOORS, guildrun.rates([]))
    client = jev.Client("k", transport=fake)
    return asyncio.run(guildrun.decide(client, plan, environ={}))


class _Cursor:
    """A fake DB cursor that records writes and answers configured reads."""

    def __init__(self, reads=None):
        self.reads = list(reads or [])
        self.writes = []
        self.lastrowid = 0
        self.rows = []
        self._row_index = 0

    def execute(self, sql, args=()):
        self.writes.append((sql.strip(), tuple(args)))
        if sql.lstrip().upper().startswith("SELECT"):
            self.rows = self.reads.pop(0) if self.reads else []
            self._row_index = 0
        else:
            self.lastrowid += 1
            self.rows = []

    def fetchall(self):
        return self.rows

    def fetchone(self):
        if self.rows:
            row = self.rows[self._row_index]
            self._row_index += 1
            return row
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_connect(cursor):
    """Return a connection that always hands out the same cursor, so writes
    from the two separate _connect calls in _start_guild_run accumulate."""

    def connect():
        return _Connection(cursor)

    return connect


class TheStartWritesTheRunAndTheCommand(unittest.TestCase):
    """_start_guild_run writes the run row, both judgments and the command."""

    def test_start_writes_the_finder_run_command_and_both_judgments(self):
        fake = FakeJev(
            picks={"dungeon": "ragefire", "composition": "a"}, confidence=0.9
        )
        decision = decide_with(fake)

        writes = []
        judgment_writes = []

        class Cursor(_Cursor):
            def execute(self, sql, args=()):
                super().execute(sql, args)
                if "INSERT INTO overseer_guild_run" in sql:
                    writes.append(("run", args))
                elif "INSERT INTO overseer_command" in sql:
                    writes.append(("command", args))

        cursor = Cursor()

        def record_judgment(judgment):
            judgment_writes.append(dataclasses.asdict(judgment))

        orig_connect = bridge._connect
        bridge._connect = lambda: _Connection(cursor)
        try:
            with mock.patch.object(bridge, "_insert_jev_judgment", record_judgment):
                run_id = bridge._start_guild_run(decision)
        finally:
            bridge._connect = orig_connect

        self.assertIsInstance(run_id, int)
        self.assertGreater(run_id, 0)
        command_writes = [a for kind, a in writes if kind == "command"]
        self.assertEqual(len(command_writes), 1)
        target, command, source = command_writes[0]
        self.assertEqual(target, "Tanky")
        self.assertEqual(source, "overseer:guildrun")
        self.assertTrue(command.startswith("finder-run ragefire "))
        self.assertIn("Healy", command)
        self.assertIn("Stabby", command)
        self.assertIn("Zappy", command)
        self.assertNotIn("Tanky", command)

        self.assertEqual(len(judgment_writes), 2)
        kinds = {j["kind"] for j in judgment_writes}
        self.assertEqual(kinds, {guildrun.KIND_COMPOSITION, guildrun.KIND_DUNGEON})
        for j in judgment_writes:
            self.assertEqual(j["item_guid"], run_id)
            self.assertEqual(j["status"], "answered")
            self.assertIsNotNone(j["jev"])
            self.assertIsNotNone(j["confidence"])
            self.assertTrue(j["facts"])


class TheFollowRecordsTheOutcome(unittest.TestCase):
    """_follow_guild_runs reads the command's answer and records the outcome."""

    def test_follow_records_a_cleared_run_with_deaths_bosses_and_loot(self):
        fake = FakeJev(
            picks={"dungeon": "ragefire", "composition": "a"}, confidence=0.9
        )
        decision = decide_with(fake)

        writes = []
        judgment_writes = []

        class Cursor(_Cursor):
            def execute(self, sql, args=()):
                super().execute(sql, args)
                if "INSERT INTO overseer_guild_run" in sql:
                    writes.append(("run", args))
                elif "INSERT INTO overseer_command" in sql:
                    writes.append(("command", args))

        def record_judgment(judgment):
            judgment_writes.append(dataclasses.asdict(judgment))

        cursor = Cursor()
        with mock.patch.object(bridge, "_insert_jev_judgment", record_judgment):
            with mock.patch.object(bridge, "_connect", _fake_connect(cursor)):
                run_id = bridge._start_guild_run(decision)

        # The worldserver answers the finder-run command: the run cleared.
        result = {
            "outcome": "cleared",
            "why": "the finder says the dungeon is finished",
            "deaths": 2,
            "seconds_inside": 1500,
            "bosses_done": 4,
            "bosses_total": 4,
            "loot_items": 17,
        }
        # One joined row: the run row plus its command's status/detail/result.
        joined_row = {
            "id": run_id,
            "state": "queued",
            "keyword": "ragefire",
            "tank": "Tanky",
            "members": guildrun.members_text(decision.chosen),
            "last_room": "",
            "status": "applied",
            "detail": "",
            "result": json.dumps(result),
            "stale": 0,
        }

        follow_writes = []

        class FollowCursor(_Cursor):
            def __init__(self):
                super().__init__(reads=[[joined_row]])

            def execute(self, sql, args=()):
                super().execute(sql, args)
                if "UPDATE overseer_guild_run SET state = 'ended'" in sql:
                    follow_writes.append(("end", args))

        with mock.patch.object(bridge, "_connect", _fake_connect(FollowCursor())):
            changed = bridge._follow_guild_runs()

        self.assertEqual(changed, 1)
        self.assertEqual(len(follow_writes), 1)
        end_args = follow_writes[0][1]
        self.assertEqual(end_args[0], "cleared")
        self.assertEqual(end_args[1], "the finder says the dungeon is finished")
        self.assertEqual(end_args[2], 2)
        self.assertEqual(end_args[3], 1500)
        self.assertEqual(end_args[4], 4)
        self.assertEqual(end_args[5], 4)
        self.assertEqual(end_args[6], 17)


class ThePageRendersTheRun(unittest.TestCase):
    """guildrun.page shapes the Guild tab payload from a recorded run."""

    def test_page_shows_the_group_the_dungeon_the_choice_and_the_outcome(self):
        rows = [
            {
                "id": 2,
                "guild": "Cave",
                "band": "15-19",
                "composition": "spec-tank/spec-healer",
                "keyword": "ragefire",
                "members": "Tanky:tank:warrior:20,Healy:healer:priest:19,"
                "Stabby:damage:rogue:19,Zappy:damage:mage:18,"
                "Locky:damage:warlock:17",
                "state": "inside",
                "dungeon_by": "jev",
                "dungeon_jev": "ragefire",
                "dungeon_confidence": 0.81,
                "composition_by": "jev",
                "composition_jev": "a",
                "composition_confidence": 0.9,
                "prior_rate": None,
                "prior_runs": 0,
                "seconds_inside": 600,
            },
            {
                "id": 1,
                "guild": "Cave",
                "band": "15-19",
                "composition": "spec-tank/spec-healer",
                "keyword": "ragefire",
                "members": "",
                "state": "ended",
                "outcome": "cleared",
                "why": "the finder says the dungeon is finished",
                "dungeon_by": "jev",
                "dungeon_jev": "ragefire",
                "dungeon_confidence": 0.81,
                "composition_by": "jev",
                "composition_jev": "a",
                "composition_confidence": 0.9,
                "prior_rate": None,
                "prior_runs": 0,
                "deaths": 2,
                "seconds_inside": 1500,
                "bosses_done": 4,
                "bosses_total": 4,
                "loot_items": 17,
            },
        ]
        page = guildrun.page(rows)
        self.assertEqual(page["head"], "1 group out, 1 back")
        self.assertEqual(len(page["active"]), 1)
        self.assertEqual(len(page["recent"]), 1)
        active = page["active"][0]
        self.assertEqual(active["title"], "Cave - Ragefire Chasm")
        self.assertIn("Jev chose Ragefire Chasm, 81% sure", active["lines"][0])
        self.assertIn("Jev chose lineup a, 90% sure", active["lines"][1])
        recent = page["recent"][0]
        self.assertEqual(recent["tone"], "good")
        self.assertIn("2 deaths", recent["lines"][2])
        self.assertIn("4 of 4 bosses", recent["lines"][2])
        self.assertIn("17 items looted", recent["lines"][2])


if __name__ == "__main__":
    unittest.main()

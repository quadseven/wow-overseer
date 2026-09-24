"""A per-family dungeon campaign queue: run A N times, then B M times (#209).

The operator's order this exists for: "Horde family (Zug's): Ragefire Chasm 50
times, then Wailing Caverns 50 times". Every test here runs on fake rows; none
touches a database.
"""

import ast
import asyncio
import pathlib
import types
import unittest

from test_decree_order import FakeConn, FakeCursor  # sets up the pymysql stub

import campaignqueue  # noqa: E402
import core  # noqa: E402
import council  # noqa: E402
import crossing  # noqa: E402
import decree  # noqa: E402
import jobs  # noqa: E402
import map_server  # noqa: E402
import raidrun  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")

ORDER = "Ragefire Chasm 50 times, then Wailing Caverns 50 times"

# The Horde five as wow-dev's roster had them on 2026-09-22: levels 16 to 20,
# on Kalimdor (map 1), Zug leading. Races: 2 orc, 6 tauren, 8 troll.
HORDE = (
    ("Zug", 20, 2),
    ("Oz", 19, 8),
    ("Uzza", 17, 8),
    ("Zork", 16, 6),
    ("Zrog", 17, 2),
)
ALLIANCE = (
    ("Grug", 60, 1),
    ("Ugga", 60, 1),
    ("Og", 60, 1),
    ("Bork", 60, 7),
    ("Grog", 60, 3),
)


def level_rows(family=HORDE, map_id=1):
    return [
        {"name": n, "level": lvl, "race": race, "map_id": map_id, "lead": int(i == 0)}
        for i, (n, lvl, race) in enumerate(family)
    ]


def roster_rows():
    """Both families, enabled, questing, with the columns the Decree reads."""
    rows = []
    for fam, members, map_id in (("Grug", ALLIANCE, 0), ("Zug", HORDE, 1)):
        for i, (name, lvl, race) in enumerate(members):
            rows.append(
                {
                    "name": name,
                    "enabled": 1,
                    "lead": int(i == 0),
                    "family": fam,
                    "job": "quest",
                    "drive_quest": 0,
                    "travel_npc": "",
                    "learn_skill": 0,
                    "dungeon_runs_wanted": 25,
                    "dungeon_runs_done": 0,
                    "level": lvl,
                    "race": race,
                    "map_id": map_id,
                }
            )
    return rows


# --- reading the operator's order ---------------------------------------------


class TheOperatorsOrderIsRead(unittest.TestCase):
    def test_the_horde_order_becomes_two_entries(self):
        entries, refusal = campaignqueue.parse_entries(ORDER)
        self.assertEqual("", refusal)
        self.assertEqual(
            (
                campaignqueue.Entry("ragefire", 50),
                campaignqueue.Entry("wailing", 50),
            ),
            entries,
        )

    def test_the_short_form_reads_the_same(self):
        entries, _ = campaignqueue.parse_entries("ragefire 50, wailing x50")
        self.assertEqual(["ragefire", "wailing"], [e.keyword for e in entries])

    def test_a_part_with_no_number_is_refused(self):
        entries, refusal = campaignqueue.parse_entries("ragefire, then wailing 50")
        self.assertEqual((), entries)
        self.assertIn("exactly one number", refusal)

    def test_an_unknown_dungeon_is_refused_naming_the_doors(self):
        entries, refusal = campaignqueue.parse_entries("onyxia 5")
        self.assertEqual((), entries)
        self.assertIn("not a dungeon the overseer has a door for", refusal)
        self.assertIn("ragefire", refusal)

    def test_a_long_run_of_digits_is_read_in_linear_time(self):
        """CodeQL flagged the first reader as polynomial on repeated digits."""
        _, refusal = campaignqueue.parse_entries("ragefire " + "9" * 390)
        self.assertIn("exactly one number", refusal)
        _, refusal = campaignqueue.parse_entries("9" * 5000)
        self.assertIn("at most 400", refusal)

    def test_a_count_past_the_column_is_refused(self):
        _, refusal = campaignqueue.parse_entries("ragefire 70000")
        self.assertIn("65535", refusal)

    def test_the_discord_form_is_a_queue_directive(self):
        said = core.parse_directive("queue Zug: " + ORDER, "7", {"7"}, dedicated=True)
        self.assertEqual(
            [core.QueueDirective(family="Zug", text=ORDER, source="discord:7")], said
        )

    def test_clear_is_read_as_clear(self):
        self.assertTrue(campaignqueue.parse_order("queue Zug: clear").clear)
        self.assertFalse(campaignqueue.parse_order("queue Zug: ragefire 5").clear)

    def test_a_sentence_that_mentions_a_dungeon_is_not_an_order(self):
        self.assertIsNone(campaignqueue.parse_order("they loved ragefire 50 times"))


# --- which doors a family may be queued through -------------------------------


class EveryEntryIsCheckedBeforeAnythingIsWritten(unittest.TestCase):
    def refused(self, text, family=HORDE, map_id=1):
        entries, refusal = campaignqueue.parse_entries(text)
        self.assertEqual("", refusal)
        plan = campaignqueue.plan("Zug", entries, level_rows(family, map_id))
        self.assertEqual((), plan.entries, "a refused queue carried entries")
        return plan.refusal

    def test_the_horde_order_is_accepted(self):
        entries, _ = campaignqueue.parse_entries(ORDER)
        plan = campaignqueue.plan("Zug", entries, level_rows())
        self.assertEqual("", plan.refusal)
        self.assertEqual(entries, plan.entries)
        self.assertIn("Ragefire Chasm 50, then Wailing Caverns 50", plan.says)

    def test_an_unknown_keyword_is_refused(self):
        plan = campaignqueue.plan(
            "Zug", (campaignqueue.Entry("maraudon", 5),), level_rows()
        )
        self.assertIn("no dungeon portal answers", plan.refusal)
        self.assertEqual((), plan.entries)

    def test_the_other_factions_capital_is_refused(self):
        self.assertIn("other faction's capital", self.refused("stockades 5"))

    def test_ragefire_is_refused_to_the_alliance(self):
        self.assertIn(
            "other faction's capital", self.refused("ragefire 5", ALLIANCE, 1)
        )

    def test_another_continent_is_refused(self):
        self.assertIn("Eastern Kingdoms", self.refused("deadmines 5"))

    def test_a_withheld_door_is_refused(self):
        self.assertIn("withheld", self.refused("stratholme live 5"))

    def test_a_door_above_the_weakest_member_is_refused(self):
        self.assertIn("Zork is level 16", self.refused("scholomance 5"))

    def test_one_bad_entry_refuses_the_whole_queue(self):
        self.assertIn("The Stockade", self.refused("ragefire 50, stockades 5"))


class TheBoxDoorsAreKnown(unittest.TestCase):
    """quadseven/mod-overseer#577 added ten box-trigger doors, Ragefire first."""

    def test_every_new_keyword_is_a_portal_and_has_a_map(self):
        import dungeonpath

        for keyword, map_id in (
            ("ragefire", 389),
            ("maraudon-orange", 349),
            ("maraudon-purple", 349),
            ("scholomance", 289),
            ("dire-maul-east-east", 429),
            ("dire-maul-north", 429),
        ):
            self.assertIn(keyword, jobs.PORTAL_KEYWORDS)
            self.assertEqual(map_id, dungeonpath.PORTAL_MAPS[keyword])
            self.assertEqual(map_id, council.DUNGEON_KEYWORDS[keyword][0])

    def test_the_dungeon_job_fits_the_column(self):
        # overseer_roster.job is VARCHAR(32) on the live schema.
        for keyword in jobs.PORTAL_KEYWORDS:
            self.assertLessEqual(len(jobs.dungeon_job(keyword)), 32, keyword)


# --- advancing ------------------------------------------------------------------


def _q(qid, keyword, runs, status, position):
    return {
        "id": qid,
        "family": "Zug",
        "position": position,
        "keyword": keyword,
        "runs_wanted": runs,
        "status": status,
    }


class OnePassDecides(unittest.TestCase):
    def test_a_queued_head_is_started_with_a_fresh_count(self):
        move = campaignqueue.step(
            [_q(1, "ragefire", 50, "queued", 0)],
            {"job": "quest", "dungeon_runs_done": 9},
        )
        self.assertEqual(
            (1, "ragefire", 50, True),
            (move.start, move.keyword, move.wanted, move.reset),
        )

    def test_an_active_head_short_of_its_count_holds(self):
        move = campaignqueue.step(
            [_q(1, "ragefire", 50, "active", 0)],
            {"job": "dungeon:ragefire", "dungeon_runs_done": 12},
        )
        self.assertFalse(move.writes)

    def test_an_unreadable_count_writes_nothing(self):
        move = campaignqueue.step([_q(1, "ragefire", 50, "active", 0)], None)
        self.assertFalse(move.writes)


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _load(names, namespace):
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace


class FakeWorld:
    """The queue table and the roster, as the bridge's adapters see them."""

    def __init__(self, queue):
        self.queue = [dict(r) for r in queue]
        self.roster = [
            {
                "name": r["name"],
                "enabled": 1,
                "lead": r["lead"],
                "family": r["family"],
                "job": "quest",
                "dungeon_runs_done": 0,
                "dungeon_runs_wanted": 25,
            }
            for r in roster_rows()
        ]
        self.withhold = False
        self.jobs = []

    def row(self, name):
        return next(r for r in self.roster if r["name"] == name)

    def family(self, key):
        return [r for r in self.roster if r["family"] == key]

    # the adapters
    def fetch_queue(self):
        return [dict(r) for r in self.queue if r["status"] in campaignqueue.PENDING]

    def fetch_roster(self):
        return [dict(r) for r in self.roster]

    def mark(self, sql, qid):
        for r in self.queue:
            if r["id"] == qid:
                if "'active'" in sql.split("WHERE")[0] and r["status"] == "queued":
                    r["status"] = "active"
                elif "'done'" in sql.split("WHERE")[0] and r["status"] == "active":
                    r["status"] = "done"
        return 1

    def drive(self, keyword, wanted, names=None, source="", withheld=None):
        if self.withhold:
            if withheld is not None:
                withheld.append("bags are near full")
            return 0, 0
        for name in names:
            self.row(name).update(
                job=jobs.dungeon_job(keyword), dungeon_runs_wanted=wanted
            )
            self.jobs.append((name, jobs.dungeon_job(keyword), source))
        return len(names), len(names)

    def drive_raid(self, keyword, family, names, source="", withheld=None):
        self.raid_orders = getattr(self, "raid_orders", []) + [(keyword, family)]
        for name in names:
            self.row(name).update(job=jobs.raid_job(keyword))
            self.jobs.append((name, jobs.raid_job(keyword), source))
        return len(names)

    def insert_job(self, name, mode, source):
        self.row(name)["job"] = mode
        self.jobs.append((name, mode, source))

    def reset(self, names):
        for name in names:
            self.row(name)["dungeon_runs_done"] = 0
        return len(names)


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = info


def _queue_pass(world, holds=None):
    """One queue pass against `world`; the lines it logged. `holds` maps a
    family key to the Jev interlude holding its job (#216)."""
    holds = holds or {}
    log = _Log()
    ns = _load(
        ["_campaign_queue_once", "_apply_queue_move"],
        {
            "asyncio": asyncio,
            "campaignqueue": campaignqueue,
            "jobs": jobs,
            "log": log,
            "_fetch_queue_rows": world.fetch_queue,
            "_fetch_queue_roster": world.fetch_roster,
            # No build report: the module refuses every crossing, as before
            # mod-overseer#671, and the pass says nothing about it.
            "_fetch_module_crossing": lambda: "",
            "crossing": crossing,
            "_mark_queue": world.mark,
            "_drive_dungeon": world.drive,
            "_drive_raid": world.drive_raid,
            "raidrun": raidrun,
            "_insert_job": world.insert_job,
            "_reset_campaign_done": world.reset,
        },
    )

    async def owns_travel(pending, fams):
        return None

    async def no_plan(pending, fams):
        return False

    async def no_town(fams):
        return None

    me = types.SimpleNamespace(
        _activity_holds=lambda key=None: holds.get(key, ""),
        _campaign_owns_travel=owns_travel,
        _leave_town_when_done=no_town,
        _plan_campaigns=no_plan,
    )
    asyncio.run(ns["_campaign_queue_once"](me))
    return log.lines


class TheQueueAdvancesByItself(unittest.TestCase):
    """The acceptance criterion: two entries advance when the first cap is
    reached, and the family returns to questing when the list is empty."""

    def setUp(self):
        self.world = FakeWorld(
            [_q(1, "ragefire", 50, "queued", 0), _q(2, "wailing", 50, "queued", 1)]
        )

    def zug(self):
        return self.world.row("Zug")

    def test_the_whole_campaign(self):
        w = self.world
        _queue_pass(w)
        self.assertEqual("dungeon:ragefire", self.zug()["job"])
        self.assertEqual({"dungeon:ragefire"}, {r["job"] for r in w.family("Zug")})
        self.assertEqual(50, self.zug()["dungeon_runs_wanted"])
        self.assertEqual("active", w.queue[0]["status"])

        # Twelve runs in: nothing to do.
        self.zug()["dungeon_runs_done"] = 12
        before = len(w.jobs)
        _queue_pass(w)
        self.assertEqual(before, len(w.jobs))

        # The vendor pass evacuates a full-bagged party with job=quest. The
        # queue owns the job and puts it back, without resetting the count.
        for r in w.family("Zug"):
            r["job"] = "quest"
        _queue_pass(w)
        self.assertEqual("dungeon:ragefire", self.zug()["job"])
        self.assertEqual(12, self.zug()["dungeon_runs_done"])

        # Fifty: on to Wailing Caverns, the count back to 0.
        self.zug()["dungeon_runs_done"] = 50
        _queue_pass(w)
        self.assertEqual(["done", "active"], [r["status"] for r in w.queue])
        self.assertEqual({"dungeon:wailing"}, {r["job"] for r in w.family("Zug")})
        self.assertEqual(0, self.zug()["dungeon_runs_done"])

        # Fifty again: the queue is empty and the family goes back to quest.
        self.zug()["dungeon_runs_done"] = 50
        _queue_pass(w)
        self.assertEqual(["done", "done"], [r["status"] for r in w.queue])
        self.assertEqual({"quest"}, {r["job"] for r in w.family("Zug")})

        # And nothing after that.
        before = len(w.jobs)
        _queue_pass(w)
        self.assertEqual(before, len(w.jobs))

    def test_the_other_family_is_never_written(self):
        w = self.world
        _queue_pass(w)
        self.zug()["dungeon_runs_done"] = 50
        _queue_pass(w)
        self.assertFalse([j for j in w.jobs if j[0] in {n for n, _, _ in ALLIANCE}])

    def test_every_job_row_names_the_queue(self):
        _queue_pass(self.world)
        self.assertEqual({campaignqueue.SOURCE}, {s for _, _, s in self.world.jobs})

    def test_a_start_withheld_on_full_bags_stays_queued(self):
        self.world.withhold = True
        self.world.row("Zug")["dungeon_runs_done"] = 9
        _queue_pass(self.world)
        self.assertEqual("queued", self.world.queue[0]["status"])
        self.assertEqual(9, self.zug()["dungeon_runs_done"], "the count was reset")

    def test_a_withheld_start_logs_the_withhold_and_its_reason(self):
        """#217: the pass said "starting Ragefire Chasm, 50 runs" every
        minute while the bag check held the start back."""
        self.world.withhold = True
        lines = _queue_pass(self.world)
        self.assertIn("queue: Zug's family: withheld: bags are near full", lines)
        self.assertFalse([ln for ln in lines if "starting" in ln], lines)

    def test_a_start_that_landed_still_says_starting(self):
        lines = _queue_pass(self.world)
        self.assertEqual(
            ["queue: Zug's family: starting Ragefire Chasm, 50 runs"],
            [ln for ln in lines if ln.startswith("queue: Zug")],
        )


def _drive_with_full_bags(withheld):
    """bridge._drive_dungeon, run for real with every bag near full."""
    ns = _load(
        ["_withheld", "_drive_dungeon"],
        {
            "jobs": jobs,
            "log": _Log(),
            "_fetch_free_slots": lambda names: {n: 0 for n in names},
            "bag_pressure": types.SimpleNamespace(
                family_town_run_needed=lambda slots: True
            ),
            "_insert_job": lambda *a: (_ for _ in ()).throw(
                AssertionError("a job was written past full bags")
            ),
            "_hand_to_town": lambda keyword, mode, names: 0,
            "_keep_in_town": lambda names: 0,
        },
    )
    return ns["_drive_dungeon"]("ragefire", 50, ["Zug"], "s", withheld=withheld)


class TheDriveSaysWhyItWithheld(unittest.TestCase):
    def test_full_bags_are_the_reason_given(self):
        withheld = []
        self.assertEqual((0, 0), _drive_with_full_bags(withheld))
        self.assertEqual(1, len(withheld), withheld)
        self.assertIn("bags are near full", withheld[0])

    def test_an_unknown_keyword_is_the_reason_given(self):
        withheld = []
        ns = _load(["_withheld", "_drive_dungeon"], {"jobs": jobs, "log": _Log()})
        self.assertEqual(
            (0, 0), ns["_drive_dungeon"]("maraudon", 5, ["Zug"], withheld=withheld)
        )
        self.assertEqual(["no dungeon portal answers to maraudon"], withheld)


class NothingElseStompsTheQueue(unittest.TestCase):
    """The goal loop's dungeon lease and the automatic job passes re-assert on
    their own clocks; while a queue has entries they stand down."""

    def test_the_council_goal_lease_asks_first(self):
        body = ast.get_source_segment(BRIDGE, _function("_goal_drive_dungeon"))
        self.assertLess(body.index("_queue_owns_job"), body.index("_drive_dungeon,"))

    def test_an_automatic_job_order_asks_first(self):
        body = ast.get_source_segment(BRIDGE, _function("_set_job"))
        self.assertLess(
            body.index("await self._queue_holds_job(d)"),
            body.index("names = await asyncio.to_thread(_fetch_enabled_names)"),
        )

    def test_only_an_automatic_source_stands_down(self):
        owns = []
        ns = _load(
            ["_queue_holds_job"],
            {
                # The annotation on `d` is evaluated at def time before 3.14.
                "core": core,
                "asyncio": asyncio,
                "log": _Log(),
                "_queue_owns_job": lambda: owns.append(1) or True,
            },
        )

        def ask(source):
            d = core.JobDirective(mode="quest", source=source)
            me = types.SimpleNamespace(_activity_holds=lambda key=None: "")
            return asyncio.run(ns["_queue_holds_job"](me, d))

        self.assertTrue(ask("overseer:craft_rhythm"))
        self.assertFalse(ask("discord:7"))
        self.assertEqual(1, len(owns), "a person's order asked the queue at all")

    def test_the_queue_owns_the_job_only_for_its_own_family(self):
        rows = [_q(1, "ragefire", 50, "active", 0)]
        ns = _load(
            ["_queue_owns_job"],
            {
                "campaignqueue": campaignqueue,
                "log": _Log(),
                "bonds": types.SimpleNamespace(head_of_family=lambda: "Grug"),
                "_fetch_queue_rows": lambda: rows,
            },
        )
        ns["_cohort_of"] = lambda name: "Grug"
        self.assertFalse(ns["_queue_owns_job"]())
        ns["_cohort_of"] = lambda name: "Zug"
        self.assertTrue(ns["_queue_owns_job"]())

    def test_the_loop_runs_and_the_store_is_created_in_both_starts(self):
        self.assertEqual(2, BRIDGE.count("self._campaign_queue_loop,"))
        self.assertEqual(
            2, BRIDGE.count("await asyncio.to_thread(_ensure_queue_store)")
        )


class TheDiscordOrder(unittest.TestCase):
    """bridge._set_queue: validated whole, written only when every entry passes."""

    def run_order(self, family, text):
        world = FakeWorld([])
        written, sent, passes = [], [], []

        class Channel:
            async def send(self, line):
                sent.append(line)

        async def queue_once():
            passes.append(1)

        ns = _load(
            ["_set_queue"],
            {
                "asyncio": asyncio,
                "campaignqueue": campaignqueue,
                "core": core,
                "log": _Log(),
                "_fetch_queue_roster": world.fetch_roster,
                "_fetch_queue_rows": world.fetch_queue,
                "_queue_level_rows": lambda fam: [
                    dict(r, lead=int(r["name"] == fam["leader"]["name"]))
                    for r in roster_rows()
                    if r["name"] in fam["names"]
                ],
                "_write_queue": lambda plan, source: (
                    written.append((plan, source)) or 2
                ),
            },
        )
        me = types.SimpleNamespace(_campaign_queue_once=queue_once)
        asyncio.run(
            ns["_set_queue"](
                me, core.QueueDirective(family, text, "discord:7"), Channel()
            )
        )
        return written, sent, passes

    def test_the_horde_order_is_written_and_started(self):
        written, sent, passes = self.run_order("Zug", ORDER)
        self.assertEqual(1, len(written))
        self.assertEqual("Zug", written[0][0].family)
        self.assertEqual("discord:7", written[0][1])
        self.assertIn("Ragefire Chasm 50, then Wailing Caverns 50", sent[0])
        self.assertEqual([1], passes)

    def test_a_refused_entry_writes_nothing(self):
        written, sent, passes = self.run_order("Zug", "ragefire 50, stockades 5")
        self.assertEqual([], written)
        self.assertIn("other faction's capital", sent[0])
        self.assertEqual([], passes)

    def test_an_unnamed_family_is_asked_for(self):
        written, sent, _ = self.run_order("", ORDER)
        self.assertEqual([], written)
        self.assertIn("Name the family", sent[0])


# --- the Decree control -------------------------------------------------------


class TheDecreeQueueCard(unittest.TestCase):
    def test_the_horde_order_is_planned(self):
        order = decree.plan_order(
            {"section": decree.QUEUE, "family": "Zug", "entries": ORDER}, roster_rows()
        )
        self.assertEqual("", order.refusal)
        self.assertEqual("Zug", order.queue.family)
        self.assertEqual(
            ["ragefire", "wailing"], [e.keyword for e in order.queue.entries]
        )
        self.assertEqual(2, order.asked)
        self.assertEqual((), order.rows)
        self.assertEqual((), order.updates)

    def test_a_refused_entry_plans_no_write(self):
        order = decree.plan_order(
            {"section": decree.QUEUE, "family": "Zug", "entries": "stockades 5"},
            roster_rows(),
        )
        self.assertIn("other faction's capital", order.refusal)
        self.assertIsNone(order.queue)

    def test_two_families_need_one_named(self):
        order = decree.plan_order(
            {"section": decree.QUEUE, "entries": ORDER}, roster_rows()
        )
        self.assertEqual(decree.ORDER_REFUSALS["family"], order.refusal)

    def test_clear_is_one_write(self):
        order = decree.plan_order(
            {"section": decree.QUEUE, "family": "Zug", "clear": True}, roster_rows()
        )
        self.assertTrue(order.queue.clear)
        self.assertEqual(1, order.asked)

    def test_the_write_replaces_the_familys_queue(self):
        order = decree.plan_order(
            {"section": decree.QUEUE, "family": "Zug", "entries": ORDER}, roster_rows()
        )
        cursor = FakeCursor()
        from unittest import mock

        with mock.patch.object(map_server, "_connect", return_value=FakeConn(cursor)):
            changed = map_server._apply_order(order)
        self.assertEqual(3, changed)
        self.assertIn(
            "UPDATE overseer_dungeon_queue SET status = 'cancelled'", cursor.calls[0][0]
        )
        self.assertEqual(("Zug",), cursor.calls[0][1])
        self.assertEqual(
            [
                ("Zug", 0, "ragefire", 50, map_server.WEB_SOURCE),
                ("Zug", 1, "wailing", 50, map_server.WEB_SOURCE),
            ],
            [params for _, params in cursor.calls[1:]],
        )

    def test_the_console_shows_each_familys_queue(self):
        queue = [_q(1, "ragefire", 50, "active", 0), _q(2, "wailing", 50, "queued", 1)]
        rows = roster_rows()
        next(r for r in rows if r["name"] == "Zug")["dungeon_runs_done"] = 12
        console = decree.build_console(rows, [], queue_rows=queue)
        lines = {f["key"]: f["queue"]["line"] for f in console["families"]}
        self.assertEqual(
            "Zug's family: Queue: Ragefire Chasm 12 of 50, then Wailing Caverns 50.",
            lines["Zug"],
        )
        self.assertEqual("Grug's family: nothing is queued.", lines["Grug"])
        self.assertEqual(decree.QUEUE, console["queue"]["section"])


# --- the site -----------------------------------------------------------------


class TheSiteShowsTheQueue(unittest.TestCase):
    def test_progress_reads_as_the_issue_asks(self):
        rows = [_q(1, "ragefire", 50, "active", 0), _q(2, "wailing", 50, "queued", 1)]
        self.assertEqual(
            "Ragefire Chasm 12 of 50, then Wailing Caverns 50",
            campaignqueue.progress_line(rows, 12),
        )

    def test_views_read_each_family_off_its_own_leader(self):
        rows = roster_rows()
        next(r for r in rows if r["name"] == "Zug")["dungeon_runs_done"] = 7
        views = campaignqueue.views([_q(1, "ragefire", 50, "active", 0)], rows)
        self.assertEqual("Queue: Ragefire Chasm 7 of 50.", views["Zug"]["line"])
        self.assertEqual("", views["Grug"]["line"])

    def test_the_dungeons_page_and_the_banner_carry_it(self):
        self.assertIn('path["queue"] = fetched.get("queue_views", {})', SERVER)
        self.assertIn('payload["queue"] = queue or campaignqueue.view', SERVER)
        self.assertIn("f.queue && f.queue.line", PAGE)
        self.assertIn("p.queue && p.queue.line", PAGE)

    def test_the_decree_card_is_on_the_page(self):
        for node in ("dcrqueuetext", "dcrqueuesend", "dcrqueueclear", "dcrqueuefam"):
            self.assertIn('id="%s"' % node, PAGE)
        self.assertIn("section: p.queue.section, entries: dcrQueueText.value", PAGE)


if __name__ == "__main__":
    unittest.main()

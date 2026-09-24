"""An ordered raid: the keyword, the queue order, the seats and the job.

What these pin, because "a raid can be queued" is not it:

  1. ONLY AN ORDER. `moltencore` is a queue keyword and never a portal
     keyword, so the council and the campaign planner, which choose among
     portal keywords, can never propose a raid.
  2. THE SEATS ARE THE LINEUP. The rows the bridge writes are raidlineup's own
     groups, converted once from the page's 1-8 to the core's 0-7.
  3. SEATS BEFORE THE JOB, AND NO JOB WITHOUT SEATS. A family parked on a raid
     job the module cannot form stands every other drive down for nothing.
"""

import ast
import contextlib
import pathlib
import types
import unittest

from test_decree_order import FakeConn, FakeCursor  # noqa: F401  (pymysql stub)

import campaignqueue  # noqa: E402
import jobs  # noqa: E402
import raidlineup  # noqa: E402
import raidrun  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

ALLIANCE = [
    {"name": n, "level": 60, "race": 1, "map_id": 0}
    for n in ("Grug", "Ugga", "Og", "Bork", "Grog")
]


class TheKeywordIsAnOrderAndNeverAPlan(unittest.TestCase):
    def test_the_raid_job_is_the_modules_vocabulary(self):
        self.assertEqual("raid:moltencore", jobs.raid_job("moltencore"))
        self.assertIsNone(jobs.raid_job("onyxia"))
        self.assertEqual("raid:moltencore", jobs.job_for("moltencore"))
        self.assertEqual("dungeon:ragefire", jobs.job_for("ragefire"))
        self.assertTrue(jobs.is_raid_job("raid:moltencore"))
        self.assertFalse(jobs.is_raid_job("raid prep"))

    def test_the_job_fits_the_column(self):
        # overseer_roster.job is VARCHAR(32) since mod-overseer's job_width.
        for keyword in jobs.RAID_KEYWORDS:
            self.assertLessEqual(len(jobs.raid_job(keyword)), 32)

    def test_a_raid_is_not_a_portal_the_planners_can_choose(self):
        self.assertFalse(jobs.RAID_KEYWORDS & jobs.PORTAL_KEYWORDS)
        self.assertIsNone(jobs.dungeon_job("moltencore"))

    def test_every_raid_keyword_has_a_name_to_be_said_by(self):
        self.assertEqual(set(jobs.RAID_KEYWORDS), set(raidrun.PLACES))
        self.assertEqual(set(jobs.RAID_KEYWORDS), set(raidrun.NAMES.values()))

    def test_describe_says_it_does_not_clear(self):
        said = jobs.describe("raid:moltencore")
        self.assertIn("does not clear", said)
        self.assertNotIn("NOT BUILT YET", said)


class TheQueueReadsARaidOrder(unittest.TestCase):
    def test_every_name_for_it_is_read(self):
        for text in ("moltencore 1", "molten core 1", "the molten core 1", "mc 1"):
            entries, refusal = campaignqueue.parse_entries(text)
            self.assertEqual("", refusal, text)
            self.assertEqual((campaignqueue.Entry("moltencore", 1),), entries, text)

    def test_the_alliance_family_at_sixty_is_accepted(self):
        entries, _ = campaignqueue.parse_entries("moltencore 1")
        plan = campaignqueue.plan("Grug", entries, ALLIANCE)
        self.assertEqual("", plan.refusal)
        self.assertIn("Molten Core 1", plan.says)

    def test_a_member_below_fifty_refuses_the_whole_order(self):
        """Zug's family: the head is level 28, so Bonkers waits."""
        rows = ALLIANCE[:4] + [{"name": "Zug", "level": 28, "race": 2, "map_id": 1}]
        entries, _ = campaignqueue.parse_entries("moltencore 1")
        plan = campaignqueue.plan("Zug", entries, rows)
        self.assertIn("Zug is below level 50", plan.refusal)
        self.assertEqual((), plan.entries)

    def test_more_than_one_night_is_refused(self):
        entries, _ = campaignqueue.parse_entries("moltencore 3")
        plan = campaignqueue.plan("Grug", entries, ALLIANCE)
        self.assertIn("a raid order is one night", plan.refusal)

    def test_a_queued_raid_starts_with_its_raid_job(self):
        rows = [
            {
                "id": 7,
                "keyword": "moltencore",
                "runs_wanted": 1,
                "status": "queued",
                "position": 0,
            }
        ]
        move = campaignqueue.step(rows, {"job": "quest", "dungeon_runs_done": 0})
        self.assertEqual(7, move.start)
        self.assertEqual("moltencore", move.keyword)
        self.assertIn("Molten Core", move.why)

    def test_an_active_raid_whose_job_was_knocked_off_is_reasserted(self):
        rows = [
            {
                "id": 7,
                "keyword": "moltencore",
                "runs_wanted": 1,
                "status": "active",
                "position": 0,
            }
        ]
        move = campaignqueue.step(rows, {"job": "quest", "dungeon_runs_done": 0})
        self.assertEqual("moltencore", move.keyword)
        self.assertIn("re-asserting raid:moltencore", move.why)
        held = campaignqueue.step(
            rows, {"job": "raid:moltencore", "dungeon_runs_done": 0}
        )
        self.assertFalse(held.writes, held.why)


class TheSeatsAreTheLineup(unittest.TestCase):
    def test_groups_one_to_eight_become_subgroups_zero_to_seven(self):
        members = (
            [
                {
                    "name": "T%d" % i,
                    "level": 60,
                    "class_id": raidlineup.WARRIOR,
                    "race": 1,
                }
                for i in range(8)
            ]
            + [
                {
                    "name": "H%d" % i,
                    "level": 60,
                    "class_id": raidlineup.PRIEST,
                    "race": 1,
                }
                for i in range(8)
            ]
            + [
                {"name": "D%d" % i, "level": 60, "class_id": raidlineup.MAGE, "race": 1}
                for i in range(24)
            ]
        )
        lineup = raidlineup.build_lineup(members, guaranteed=["T0"])
        seats = raidrun.seat_rows("Grug", "moltencore", lineup)
        self.assertEqual(40, len(seats))
        self.assertEqual({0, 1, 2, 3, 4, 5, 6, 7}, {s[3] for s in seats})
        first = [g for g in lineup["groups"] if g["number"] == 1][0]
        for member in first["members"]:
            self.assertIn(
                ("Grug", "moltencore", member["name"], 0, member["role"]), seats
            )


def _function(name):
    tree = ast.parse(BRIDGE)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("no %s in bridge.py" % name)


def _load_drive_raid(events, members, missing_table=False):
    """bridge._drive_raid, run for real against fakes that record order."""
    source = "\n\n".join(
        ast.get_source_segment(BRIDGE, _function(name))
        for name in ("_withheld", "_drive_raid")
    )

    class MissingTable(Exception):
        pass

    class Cursor:
        def execute(self, sql, args=()):
            if "overseer_raid_seat" in sql:
                if missing_table:
                    raise MissingTable(1146, "Table doesn't exist")
                events.append(("seat", sql.split()[0], args))
            else:
                events.append(("read", args))

        def executemany(self, sql, rows):
            if missing_table:
                raise MissingTable(1146, "Table doesn't exist")
            events.append(("seat", sql.split()[0], list(rows)))

        def fetchall(self):
            return list(members)

    class Conn:
        def cursor(self):
            return contextlib.nullcontext(Cursor())

    class Log:
        def info(self, *a, **k):
            pass

        warning = exception = info

    namespace = {
        "jobs": jobs,
        "raidrun": raidrun,
        "raidlineup": raidlineup,
        "campaignqueue": campaignqueue,
        "log": Log(),
        "_insert_job": lambda name, mode, by: events.append(("job", name, mode)),
        "_connect": lambda: contextlib.nullcontext(Conn()),
        "pymysql": types.SimpleNamespace(
            err=types.SimpleNamespace(MySQLError=MissingTable)
        ),
    }
    exec(compile(source, str(BRIDGE), "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace["_drive_raid"]


GUILD = [
    {"name": n, "level": 60, "class_id": c, "race": 1}
    for n, c in (
        [("Grug", raidlineup.WARRIOR)]
        + [("W%d" % i, raidlineup.WARRIOR) for i in range(8)]
        + [("P%d" % i, raidlineup.PRIEST) for i in range(9)]
        + [("M%d" % i, raidlineup.MAGE) for i in range(30)]
    )
]


class TheBridgeWritesSeatsThenTheJob(unittest.TestCase):
    def test_seats_are_replaced_before_any_job_is_written(self):
        events = []
        drive = _load_drive_raid(events, GUILD)
        withheld = []
        written = drive("moltencore", "Grug", ["Grug"], "overseer:queue", withheld)
        self.assertEqual(1, written)
        self.assertEqual([], withheld)
        kinds = [e[0] for e in events]
        self.assertEqual("read", kinds[0])
        self.assertEqual(("seat", "DELETE", ("Grug", "moltencore")), events[1])
        inserts = [e for e in events if e[0] == "seat" and e[1] == "INSERT"]
        self.assertEqual(1, len(inserts), "the forty seats are one statement")
        self.assertEqual(40, len(inserts[0][2]))
        self.assertEqual(("job", "Grug", "raid:moltencore"), events[-1])
        self.assertLess(kinds.index("seat"), kinds.index("job"))

    def test_no_seat_table_means_no_job(self):
        events = []
        drive = _load_drive_raid(events, GUILD, missing_table=True)
        withheld = []
        self.assertEqual(0, drive("moltencore", "Grug", ["Grug"], "q", withheld))
        self.assertFalse([e for e in events if e[0] == "job"])
        self.assertIn("not deployed", withheld[0])

    def test_an_unknown_raid_writes_nothing(self):
        events = []
        drive = _load_drive_raid(events, GUILD)
        self.assertEqual(0, drive("onyxia", "Grug", ["Grug"], "q", []))
        self.assertEqual([], events)

    def test_the_queue_routes_a_raid_entry_to_the_raid_writer(self):
        """_apply_queue_move sends `moltencore` to _drive_raid with the
        family's key, and never to the dungeon writer."""
        calls = []
        source = ast.get_source_segment(BRIDGE, _function("_apply_queue_move"))
        namespace = {
            "raidrun": raidrun,
            "jobs": jobs,
            "campaignqueue": campaignqueue,
            "log": types.SimpleNamespace(exception=lambda *a, **k: None),
            "_mark_queue": lambda sql, qid: calls.append(("mark", qid)),
            "_reset_campaign_done": lambda names: calls.append(("reset",)),
            "_insert_job": lambda *a: calls.append(("job",) + a),
            "_drive_dungeon": lambda *a, **k: calls.append(("dungeon",)) or (0, 0),
            "_drive_raid": lambda keyword, family, names, source, withheld=None: (
                calls.append(("raid", keyword, family, tuple(names))) or len(names)
            ),
        }
        exec(compile(source, str(BRIDGE), "exec"), namespace)  # noqa: S102 - bridge.py's own source
        move = campaignqueue.Move(
            start=7,
            keyword="moltencore",
            wanted=1,
            reset=True,
            why="starting Molten Core, 1 runs",
        )
        said = namespace["_apply_queue_move"](move, ["Grug", "Ugga"], "Grug")
        self.assertEqual(("raid", "moltencore", "Grug", ("Grug", "Ugga")), calls[0])
        self.assertNotIn(("dungeon",), calls)
        self.assertIn(("mark", 7), calls)
        self.assertEqual(move.why, said)


class NothingAutomaticWritesARaid(unittest.TestCase):
    def test_the_planner_and_council_modules_never_name_the_raid(self):
        for module in ("campaignplan.py", "council.py", "jev_activity.py"):
            text = (HERE / module).read_text(encoding="utf-8")
            self.assertNotIn("moltencore", text, module)
            self.assertNotIn("raid_job", text, module)


if __name__ == "__main__":
    unittest.main()

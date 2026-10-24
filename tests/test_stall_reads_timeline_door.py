"""The stall reads find each run's door on a ledger without `portal_keyword`.

On the dev realm 2026-10-23 the Alliance family (41 to 47) went from Uldaman
to the Scarlet Cathedral to the Scarlet Armory and back for days. Uldaman and
the Cathedral stalled every time ("dungeon clear switched itself off ... with
nothing left it could reach"), yet nothing ever read either as stuck, because
the ledger the running worldserver writes has no `portal_keyword` column yet:
every pass logged "the run ledger by door cannot be read on this realm", the
stall reads came back empty, the stall breaker never fired, and the pace
ladder kept stepping back to the Cathedral.

The run timeline (overseer_dungeon_run_event) names each run's portal on every
row, so the door is read from there when the column is missing. The fixtures
are the family's last two Cathedral runs, 832870 and 834142, and a cleared
Armory run, as the timeline holds them.
"""

import ast
import pathlib
import types
import unittest

import campaignplan
import dungeonstall

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

STALL = (
    "dungeon clear switched itself off; no reason given; it refused 'dc skip' "
    "1 inside map 189 with nothing left it could reach"
)
TIMELINE_LEDGER = [
    {
        "id": 819733,
        "map_id": 189,
        "portal_keyword": "scarlet-armory",
        "outcome": "complete",
    },
    {
        "id": 832870,
        "map_id": 189,
        "portal_keyword": "scarlet-cathedral",
        "outcome": "stalled",
    },
    {
        "id": 834142,
        "map_id": 189,
        "portal_keyword": "scarlet-cathedral",
        "outcome": "stalled",
    },
]
EVENTS = [
    {"run_id": 832870, "kind": "stalled", "detail": STALL},
    {"run_id": 834142, "kind": "stalled", "detail": STALL},
]


class _MySQLError(Exception):
    pass


class _NoPortalColumnCursor:
    """A realm whose overseer_dungeon_run has no `portal_keyword` column."""

    def __init__(self):
        self.rows = []
        self.asked = []

    def execute(self, sql, args=()):
        self.asked.append(sql)
        if "FROM overseer_dungeon_run_event" in sql and "e.portal" not in sql:
            self.rows = EVENTS
        elif "e.portal" in sql:
            self.rows = TIMELINE_LEDGER
        elif "portal_keyword" in sql:
            raise _MySQLError(1054, "Unknown column 'portal_keyword' in 'field list'")
        else:
            self.rows = []

    def fetchall(self):
        return list(self.rows)


class _EmptyDoorColumnCursor(_NoPortalColumnCursor):
    """A realm with the column, empty on every run that did not complete."""

    def execute(self, sql, args=()):
        self.asked.append(sql)
        if "FROM overseer_dungeon_run_event" in sql and "e.portal" not in sql:
            self.rows = EVENTS
        elif "e.portal" in sql:
            self.rows = TIMELINE_LEDGER
        elif "portal_keyword" in sql:
            self.rows = [
                dict(
                    r,
                    portal_keyword=r["portal_keyword"]
                    if r["outcome"] == "complete"
                    else "",
                )
                for r in TIMELINE_LEDGER
            ]
        else:
            self.rows = []


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a):
        self.lines.append(msg % a if a else msg)


def _functions(*names):
    found = {
        node.name: node
        for node in ast.walk(ast.parse(BRIDGE))
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    return ast.Module(body=[found[n] for n in names], type_ignores=[])


def _stuck_doors(cur):
    log = _Log()
    ns = {
        "dungeonstall": dungeonstall,
        "log": log,
        "pymysql": types.SimpleNamespace(
            err=types.SimpleNamespace(MySQLError=_MySQLError)
        ),
    }
    exec(compile(_functions("_planner_rows", "_stuck_doors"), "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
    return ns["_stuck_doors"](cur, ["Grug", "Bork", "Grog", "Og", "Ugga"]), log


class TheDoorComesFromTheTimeline(unittest.TestCase):
    def test_two_cathedral_stalls_are_stuck_without_the_column(self):
        cur = _NoPortalColumnCursor()
        stuck, _log = _stuck_doors(cur)
        self.assertEqual({"scarlet-cathedral"}, set(stuck))
        self.assertIn("Cathedral", stuck["scarlet-cathedral"].why)

    def test_the_cleared_armory_is_not_stuck(self):
        stuck, _log = _stuck_doors(_NoPortalColumnCursor())
        self.assertNotIn("scarlet-armory", stuck)

    def test_the_timeline_is_asked_first(self):
        cur = _NoPortalColumnCursor()
        _stuck_doors(cur)
        self.assertEqual(
            dungeonstall.RUNS_SQL_TIMELINE.format(holes=dungeonstall.holes(5)),
            cur.asked[0],
        )

    def test_an_empty_column_after_the_roll_does_not_hide_the_door(self):
        # #1375: the worldserver writes `portal_keyword` only on a run that
        # completes, so a stalled run's column is empty after the roll.
        cur = _EmptyDoorColumnCursor()
        stuck, _log = _stuck_doors(cur)
        self.assertEqual({"scarlet-cathedral"}, set(stuck))

    def test_the_timeline_read_never_names_the_missing_column_as_a_field(self):
        sql = dungeonstall.RUNS_SQL_TIMELINE
        self.assertIn("overseer_dungeon_run_event", sql)
        self.assertNotIn("r.portal_keyword", sql)
        self.assertIn("AS portal_keyword", sql)
        self.assertIn("e.run_id = r.id", sql)

    def test_a_shared_map_wing_counts_as_itself(self):
        row = dict(TIMELINE_LEDGER[1])
        self.assertEqual("scarlet-cathedral", dungeonstall.door_of(row))
        row["portal_keyword"] = None
        # A run with no timeline row still counts toward its map's front door,
        # as it did before.
        self.assertEqual("scarlet", dungeonstall.door_of(row))


class ThePlannerLedgerToo(unittest.TestCase):
    def test_the_planner_reads_the_timeline_before_counting_by_map(self):
        body = BRIDGE[BRIDGE.index("def _planner_facts(") :]
        body = body[: body.index("\ndef ")]
        self.assertLess(
            body.index("campaignplan.RUNS_SQL_TIMELINE"),
            body.index("campaignplan.RUNS_SQL_OLD"),
        )

    def test_the_planner_counts_the_cathedral_as_the_cathedral(self):
        rows = [dict(r, leader_name="Grug") for r in TIMELINE_LEDGER]
        done, failed = campaignplan.ledger(rows, ["Grug"])
        self.assertEqual(2, failed.get("scarlet-cathedral"))
        self.assertEqual(1, done.get("scarlet-armory"))
        self.assertNotIn("scarlet", failed)


if __name__ == "__main__":
    unittest.main()

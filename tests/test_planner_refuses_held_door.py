"""The planner refuses every door the stall breaker left in its window (#1078).

On 2026-11-07 the stall breaker left Sunken Temple for Zug's family at
07:21:12 (overseer_dungeon_pace row 138, decision `stall_out`): the head had
gone two hours with no quest, level, gear or boss progress (dungeonstall
`silent_run`). Sixty-one seconds later the planner chose Sunken Temple again
("the queue is empty") and the family ran it 26 more times with no clear. The
planner's refusal read only the two-stall kind (`stuck_doors`), and a silent
head's leave has no two stalled runs behind it, so nothing barred the door.

The fixture is that pace row as the realm holds it, with an empty run ledger:
nothing but the leave says the door is held.
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

# 48 hours less the 61 seconds since the leave, as TIMESTAMPDIFF reads it.
HELD = [{"door": "sunken-temple", "left_s": 48 * 3600 - 61}]

# Zug's family, at the levels Sunken Temple is offered to.
FAMILY = (
    {"name": "Zug", "level": 50, "race": 2, "map_id": 0, "lead": 1},
    {"name": "Oz", "level": 50, "race": 8, "map_id": 0, "lead": 0},
    {"name": "Uzza", "level": 49, "race": 2, "map_id": 0, "lead": 0},
    {"name": "Zrog", "level": 50, "race": 2, "map_id": 0, "lead": 0},
    {"name": "Zork", "level": 50, "race": 8, "map_id": 0, "lead": 0},
)


class _MySQLError(Exception):
    pass


class _Cursor:
    """A realm whose run ledger is empty and whose pace table holds the leave."""

    def __init__(self, held=HELD, pace_missing=False):
        self.held = held
        self.pace_missing = pace_missing
        self.rows = []
        self.asked = []

    def execute(self, sql, args=()):
        self.asked.append((sql, args))
        if "overseer_dungeon_pace" in sql:
            if self.pace_missing:
                raise _MySQLError(1146, "Table 'overseer_dungeon_pace' doesn't exist")
            self.rows = list(self.held)
        else:
            self.rows = []

    def fetchall(self):
        return list(self.rows)


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


def _stall_barred(cur):
    ns = {
        "dungeonstall": dungeonstall,
        "log": _Log(),
        "pymysql": types.SimpleNamespace(
            err=types.SimpleNamespace(MySQLError=_MySQLError)
        ),
    }
    exec(  # noqa: S102 - bridge.py's own source
        compile(
            _functions("_planner_rows", "_stuck_doors", "_stall_barred"),
            "bridge.py",
            "exec",
        ),
        ns,
    )
    return ns["_stall_barred"](cur, "Zug", [m["name"] for m in FAMILY])


def _facts(stalled):
    return campaignplan.Facts(
        family="Zug", level_rows=FAMILY, done={}, failed={}, stalled=stalled
    )


class ThePlannerRefusesAHeldDoor(unittest.TestCase):
    def test_sunken_temple_is_offered_without_the_leave(self):
        offered = {o.keyword for o in campaignplan.options(_facts({}))}
        self.assertIn("sunken-temple", offered)

    def test_a_silent_heads_leave_bars_the_door(self):
        stalled = _stall_barred(_Cursor())
        self.assertIn("sunken-temple", stalled)
        offered = {o.keyword for o in campaignplan.options(_facts(stalled))}
        self.assertNotIn("sunken-temple", offered)
        kind, why = campaignplan.refusal_kinds(_facts(stalled))["sunken-temple"]
        self.assertEqual(campaignplan.REFUSED_STALLED, kind)
        self.assertIn("stall breaker left it", why)
        self.assertIn("48.0 more hour", why)

    def test_the_read_is_the_familys_leaves_in_the_window(self):
        cur = _Cursor()
        _stall_barred(cur)
        sql, args = next(a for a in cur.asked if "overseer_dungeon_pace" in a[0])
        self.assertEqual(
            (
                dungeonstall.WINDOW_HOURS,
                "Zug",
                dungeonstall.DECISION,
                dungeonstall.WINDOW_HOURS,
            ),
            args,
        )
        self.assertIn("family = %s", sql)
        self.assertIn("decision = %s", sql)

    def test_an_unreadable_pace_table_bars_nothing_more(self):
        self.assertEqual({}, _stall_barred(_Cursor(pace_missing=True)))

    def test_the_newest_leave_of_a_door_says_the_hold(self):
        rows = [
            {"door": "sunken-temple", "left_s": 3600},
            {"door": "sunken-temple", "left_s": 7200},
            {"door": "not-a-door", "left_s": 7200},
        ]
        barred = dungeonstall.held_barred(rows)
        self.assertEqual({"sunken-temple"}, set(barred))
        self.assertIn("1.0 more hour", barred["sunken-temple"])


if __name__ == "__main__":
    unittest.main()

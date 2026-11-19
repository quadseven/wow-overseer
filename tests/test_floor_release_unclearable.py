"""A member no vendor can clear does not hold its family at the bag floor (#1261).

Pinned: a member whose stacks are all kept is released with one log line, a
vendor visit the module reports as NOTHING CHANGED is counted, and after
bag_pressure.VENDOR_VISIT_LIMIT of them the member is released too.
"""

import ast
import contextlib
import pathlib
import unittest

import bag_pressure

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
WANT = ("_at_floor", "_note_vendor_visits", "_floor_release")


class Log:
    def __init__(self):
        self.lines = []

    def warning(self, fmt, *a):
        self.lines.append(fmt % a)

    def exception(self, *a):
        self.lines.append("exception")


def load(rows_by_call):
    log = Log()

    class Cur:
        def execute(self, sql, args):
            pass

        def fetchall(self):
            return rows_by_call.pop(0) if rows_by_call else []

    class Conn:
        def cursor(self):
            return contextlib.nullcontext(Cur())

    ns = {
        "bag_pressure": bag_pressure,
        "log": log,
        "_connect": lambda: contextlib.nullcontext(Conn()),
        "_VENDOR_SELLABLE": {},
        "_VISITS_UNCHANGED": {},
        "_VISIT_SEEN": {},
        "_FLOOR_RELEASED_SAID": set(),
        "_FLOOR_KEPT": {},
        "_VISITS_SQL": "%s",
    }
    funcs = [
        n
        for n in ast.walk(ast.parse(BRIDGE))
        if isinstance(n, ast.FunctionDef) and n.name in WANT
    ]
    exec(compile(ast.Module(body=funcs, type_ignores=[]), "bridge.py", "exec"), ns)
    return ns, log


class UnclearableMember(unittest.TestCase):
    def test_all_kept_member_is_released_and_logged_once(self):
        ns, log = load([])
        ns["_VENDOR_SELLABLE"]["Ot"] = 0
        ns["_FLOOR_KEPT"]["Ot"] = 111
        free = {"Ot": 0, "Tug": 12}
        self.assertEqual({"Tug": 12}, ns["_floor_release"](["Ot", "Tug"], free))
        ns["_floor_release"](["Ot", "Tug"], free)
        self.assertEqual(1, len(log.lines))
        self.assertIn("Ot released", log.lines[0])
        self.assertIn("111 stack(s) kept", log.lines[0])

    def test_member_with_something_to_sell_stays_held(self):
        ns, _ = load([])
        ns["_VENDOR_SELLABLE"]["Ot"] = 4
        free = {"Ot": 0}
        self.assertEqual(free, ns["_floor_release"](["Ot"], free))

    def test_unread_member_stays_held(self):
        ns, _ = load([])
        free = {"Zrog": 0}
        self.assertEqual(free, ns["_floor_release"](["Zrog"], free))


class NothingChangedVisits(unittest.TestCase):
    def visit(self, stamp):
        return [{"name": "Zrog", "last_seen": stamp}]

    def test_each_new_visit_counts_once(self):
        ns, _ = load([self.visit(1), self.visit(1), self.visit(2)])
        for _ in range(3):
            ns["_note_vendor_visits"](["Zrog"])
        self.assertEqual(2, ns["_VISITS_UNCHANGED"]["Zrog"])

    def test_repeats_are_bounded_per_member(self):
        stamps = [self.visit(i) for i in range(bag_pressure.VENDOR_VISIT_LIMIT)]
        ns, log = load(stamps)
        free = {"Zrog": 0}
        for _ in range(bag_pressure.VENDOR_VISIT_LIMIT - 1):
            self.assertEqual(free, ns["_floor_release"](["Zrog"], free))
        self.assertEqual({}, ns["_floor_release"](["Zrog"], free))
        self.assertIn("vendor visits changed nothing", log.lines[0])

    def test_vendor_cannot_clear_pure(self):
        self.assertEqual("", bag_pressure.vendor_cannot_clear("A", {}, {}))
        self.assertTrue(bag_pressure.vendor_cannot_clear("A", {"A": 0}, {}))
        self.assertTrue(bag_pressure.vendor_cannot_clear("A", {"A": 3}, {"A": 3}))


if __name__ == "__main__":
    unittest.main()

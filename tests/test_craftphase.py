"""The craft window (#2369): the planner, the switch, the skip predicate, the
read, and the seams that honour an open window."""

import ast
import json
import os
import pathlib
import types
import unittest
from unittest import mock

import campaignqueue as cq
import craftphase as cp
import familyseat as fs

FAMILY = "Grug"
NOW = 1_000_000.0
HOME = cp.Facts(roster=frozenset({"Grug", "Og"}))


def fresh():
    return cp.State(FAMILY, cp.SCHEDULE[FAMILY])


class PlannerTest(unittest.TestCase):
    def test_a_family_never_run_opens_one_bounded_window(self):
        got = cp.plan(fresh(), HOME, NOW)
        self.assertTrue(cp.is_open(got.state, NOW))
        self.assertEqual(NOW + cp.MAX_WINDOW_SECONDS, got.state.ends)
        self.assertEqual(
            {
                "family": FAMILY,
                "phase": "craft",
                "start": NOW,
                "end": NOW + cp.MAX_WINDOW_SECONDS,
                "reason": cp.REASON_OPENED,
            },
            got.row,
        )

    def test_the_window_ends_itself_at_the_maximum_length(self):
        opened = cp.plan(fresh(), HOME, NOW).state
        mid = cp.plan(opened, HOME, NOW + cp.MAX_WINDOW_SECONDS - 1)
        self.assertIsNone(mid.row)
        self.assertTrue(cp.is_open(mid.state, NOW + 1))
        end = NOW + cp.MAX_WINDOW_SECONDS
        done = cp.plan(opened, HOME, end + 500)
        self.assertFalse(cp.is_open(done.state, end + 500))
        self.assertEqual(cp.REASON_LENGTH, done.row["reason"])
        self.assertEqual(end, done.row["end"])

    def test_a_stale_state_is_closed_by_the_clock_alone(self):
        opened = cp.plan(fresh(), HOME, NOW).state
        self.assertFalse(cp.is_open(opened, NOW + cp.MAX_WINDOW_SECONDS))

    def test_the_cooldown_holds_the_next_window(self):
        opened = cp.plan(fresh(), HOME, NOW).state
        end = NOW + cp.MAX_WINDOW_SECONDS
        closed = cp.plan(opened, HOME, end).state
        self.assertIsNone(cp.plan(closed, HOME, end + cp.COOLDOWN_SECONDS - 1).row)
        again = cp.plan(closed, HOME, end + cp.COOLDOWN_SECONDS)
        self.assertTrue(cp.is_open(again.state, end + cp.COOLDOWN_SECONDS))

    def test_no_window_opens_while_the_family_is_in_a_run(self):
        busy = cp.Facts(roster=HOME.roster, in_run=True)
        self.assertIsNone(cp.plan(fresh(), busy, NOW).row)

    def test_no_window_opens_for_a_crafter_off_the_roster(self):
        away = cp.Facts(roster=frozenset({"Og"}))
        self.assertIsNone(cp.plan(fresh(), away, NOW).row)

    def test_a_crafter_who_leaves_the_roster_ends_the_window(self):
        opened = cp.plan(fresh(), HOME, NOW).state
        got = cp.plan(opened, cp.Facts(roster=frozenset()), NOW + 60)
        self.assertEqual(cp.REASON_GONE, got.row["reason"])
        self.assertFalse(cp.is_open(got.state, NOW + 60))

    def test_the_log_is_bounded(self):
        state, now = fresh(), NOW
        for _ in range(cp.LOG_KEEP * 2):
            state = cp.plan(state, HOME, now).state
            now += cp.MAX_WINDOW_SECONDS
            state = cp.plan(state, HOME, now).state
            now += cp.COOLDOWN_SECONDS
        self.assertEqual(cp.LOG_KEEP, len(state.log))


class SwitchTest(unittest.TestCase):
    def test_off_unless_explicitly_on(self):
        self.assertFalse(cp.enabled({}))
        self.assertFalse(cp.enabled({"CRAFT_PHASE": ""}))
        self.assertFalse(cp.enabled({"CRAFT_PHASE": "off"}))
        self.assertFalse(cp.enabled({"CRAFT_PHASE": "maybe"}))
        self.assertTrue(cp.enabled({"CRAFT_PHASE": "on"}))


class SkipTest(unittest.TestCase):
    def test_protected_names_only_inside_an_open_window(self):
        opened = cp.plan(fresh(), HOME, NOW).state
        self.assertEqual({"Grug"}, cp.protected([opened], NOW + 5))
        self.assertEqual(frozenset(), cp.protected([opened], opened.ends))
        self.assertEqual(frozenset(), cp.protected([fresh()], NOW))

    def test_barred_when_the_family_holds_the_crafter(self):
        self.assertTrue(cp.barred({"Grug"}, ["Og", "Grug"]))
        self.assertFalse(cp.barred({"Grug"}, ["Og", "Zug"]))
        self.assertFalse(cp.barred(set(), ["Grug"]))


class ReadTest(unittest.TestCase):
    def test_the_memo_round_trips_and_pages_the_phase_and_log(self):
        opened = cp.plan(fresh(), HOME, NOW)
        value = json.dumps(cp.encode(opened.state))
        rows = [{"subject": FAMILY, "value": value, "since": NOW}]
        got = cp.page(rows, NOW + 10)
        self.assertEqual(1, len(got))
        self.assertEqual("craft", got[0]["phase"])
        self.assertEqual(opened.row, got[0]["log"][-1])
        later = cp.page(rows, opened.state.ends + 1)
        self.assertEqual("idle", later[0]["phase"])
        self.assertIsNone(later[0]["ends"])
        self.assertEqual(1, len(later[0]["log"]))

    def test_unreadable_rows_are_skipped(self):
        rows = [
            {"subject": FAMILY, "value": "{nope"},
            {"subject": "Other", "value": "{}"},
        ]
        self.assertEqual([], cp.page(rows, NOW))


class TheDungeonSeams(unittest.TestCase):
    ROSTER = [
        {"name": "Grug", "family": "Grug", "job": "quest"},
        {"name": "Ugga", "family": "Grug", "job": "quest"},
        {"name": "Og", "family": "Grug", "job": "craft"},
    ]

    def test_a_crafter_in_an_open_window_is_not_lent_to_a_guild_run(self):
        self.assertEqual({"Ugga", "Og"}, fs.lendable(self.ROSTER, set()))
        got = fs.lendable(self.ROSTER, set(), crafting={"Og"})
        self.assertEqual({"Ugga"}, got)

    def test_the_crafter_is_lent_again_once_the_window_ends(self):
        opened = cp.plan(cp.State("Grug", "Og"), HOME, NOW).state
        during = cp.protected([opened], NOW + 1)
        after = cp.protected([opened], opened.ends)
        self.assertNotIn("Og", fs.lendable(self.ROSTER, set(), crafting=during))
        self.assertIn("Og", fs.lendable(self.ROSTER, set(), crafting=after))

    def test_a_family_with_its_crafter_in_a_window_is_withheld_then_admitted(self):
        names = ("Grug", "Og")
        shut = cq.decide_admission(
            names,
            "rfc",
            cq.Facts(free_slots={"Grug": 30, "Og": 30}, craft_window=True),
            1.0,
        )
        self.assertEqual(cq.GATE_CRAFT, shut.gate)
        free = cq.decide_admission(
            names, "rfc", cq.Facts(free_slots={"Grug": 30, "Og": 30}), 1.0
        )
        self.assertIsInstance(free, cq.Admit)


BRIDGE = pathlib.Path(__file__).resolve().parent.parent / "bridge.py"


def _bridge_function(name):
    for node in ast.walk(ast.parse(BRIDGE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s not found in bridge.py" % name)


class Broken(Exception):
    pass


class TheBridgeHelpers(unittest.TestCase):
    def helpers(self, memo_read, now=NOW):
        self.lines = []
        ns = {
            "craftphase": cp,
            "pymysql": types.SimpleNamespace(
                err=types.SimpleNamespace(MySQLError=Broken)
            ),
            "log": types.SimpleNamespace(
                exception=lambda msg, *a: self.lines.append(msg),
                info=lambda msg, *a: self.lines.append(msg % a if a else msg),
            ),
            "time": types.SimpleNamespace(time=lambda: now),
            "_memo_read": memo_read,
            "_fetch_queue_roster": lambda: [
                {"name": "Grug", "family": "Grug"},
                {"name": "Og", "family": "Grug"},
            ],
            "_LIVE_RUN_LEADERS_SQL": "x",
            "_connect": lambda: self.fail("no connection expected"),
            "_guild_run_members_out": lambda: set(),
            "_memo_upsert": lambda *a: None,
        }
        names = (
            "_craft_window_states",
            "_craft_window_tick",
            "_craft_window_names",
            "_craft_window_open_for",
            "_craft_window_withholds",
        )
        module = ast.Module(body=[_bridge_function(n) for n in names], type_ignores=[])
        exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        return ns

    def test_a_failed_state_read_protects_nobody_and_does_not_raise(self):
        def memo_read(kind):
            raise Broken("down")

        ns = self.helpers(memo_read)
        self.assertEqual([], ns["_craft_window_states"](NOW))
        with mock.patch.dict(os.environ, {"CRAFT_PHASE": "on"}):
            self.assertEqual(frozenset(), ns["_craft_window_names"]())
            self.assertFalse(ns["_craft_window_open_for"](["Grug", "Og"]))
            self.assertIsNone(ns["_craft_window_withholds"](["Grug"], "rfc"))
        self.assertTrue(self.lines)

    def test_the_withhold_helper_feeds_the_gate_while_the_window_stands(self):
        opened = cp.plan(fresh(), HOME, NOW).state
        memo = {"Grug": (cp.encode(opened), NOW)}
        ns = self.helpers(lambda kind: memo)
        # The live-run read is a connection; give the tick one that reads none.
        ns["_connect"] = _NoRuns
        with mock.patch.dict(os.environ, {"CRAFT_PHASE": "on"}):
            reason = ns["_craft_window_withholds"](["Grug", "Og"], "rfc")
            self.assertIn("craft window", reason)
            self.assertIsNone(ns["_craft_window_withholds"](["Zug"], "rfc"))
        with mock.patch.dict(os.environ, {"CRAFT_PHASE": "off"}):
            self.assertIsNone(ns["_craft_window_withholds"](["Grug", "Og"], "rfc"))


class TheAdmissionChain(unittest.TestCase):
    def test_the_craft_gate_names_itself_and_lifts_with_the_window(self):
        names = ("Grug", "Og")
        slots = {"Grug": 30, "Og": 30}
        shut = cq.decide_admission(
            names, "rfc", cq.Facts(free_slots=slots, craft_window=True), 1.0
        )
        self.assertIsInstance(shut, cq.Withhold)
        self.assertEqual(cq.GATE_CRAFT, shut.gate)
        self.assertIn("craft window", shut.reason)
        self.assertIsInstance(
            cq.decide_admission(names, "rfc", cq.Facts(free_slots=slots), 1.0),
            cq.Admit,
        )

    def test_the_bridge_chain_stops_at_the_craft_withhold(self):
        body = BRIDGE.read_text(encoding="utf-8")
        seen = []
        ns = {"_craft_window_withholds": lambda n, k: seen.append((n, k)) or "held"}
        gate = ast.Module(body=[_bridge_function("_gear_gate")], type_ignores=[])
        exec(compile(gate, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        ns["_town_errand_withholds"] = lambda n, k: None
        self.assertEqual("held", ns["_gear_gate"](["Grug"], "rfc"))
        self.assertEqual([(["Grug"], "rfc")], seen)
        self.assertIn("craft_window=_craft_window_open_for(names)", body)


class _NoRuns:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, sql):
        pass

    def fetchall(self):
        return []


if __name__ == "__main__":
    unittest.main()

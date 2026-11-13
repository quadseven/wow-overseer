"""The craft window (#2369): the planner, the switch, the skip predicate, the
read, and the seams that honour an open window."""

import json
import unittest

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


if __name__ == "__main__":
    unittest.main()

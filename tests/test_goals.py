"""Goal supervisor tests: parsing, reconcile decisions, fake-store lifecycle.

No MySQL and no Discord anywhere - the store is a dict a tiny fake mutates
by applying the typed actions reconcile returns, which is exactly the seam
bridge.py implements against the real store (infra#2601).
"""
import unittest

import goals
from goals import (
    CancelGoal,
    Goal,
    MarkComplete,
    MilestoneThought,
    RecordProgress,
    Report,
    StrategyCommand,
    parse_goal,
    reconcile,
)


class ParseLevelTest(unittest.TestCase):
    def test_reach_level(self):
        self.assertEqual(parse_goal("reach level 5 before you continue"), Goal("level", 5))

    def test_hit_level(self):
        self.assertEqual(parse_goal("hit level 10"), Goal("level", 10))

    def test_get_to_level(self):
        self.assertEqual(parse_goal("get to level 12"), Goal("level", 12))

    def test_get_to_bare_number(self):
        self.assertEqual(parse_goal("get to 8"), Goal("level", 8))

    def test_level_to(self):
        self.assertEqual(parse_goal("level to 6"), Goal("level", 6))

    def test_level_up_to(self):
        self.assertEqual(parse_goal("level up to 20"), Goal("level", 20))

    def test_case_insensitive(self):
        self.assertEqual(parse_goal("Reach Level 5"), Goal("level", 5))

    def test_level_above_cap_is_not_a_goal(self):
        self.assertIsNone(parse_goal("reach level 999"))

    def test_level_one_is_not_a_goal(self):
        # Every character is already level 1; a target of 1 is noise.
        self.assertIsNone(parse_goal("reach level 1"))


class ParseSkillTest(unittest.TestCase):
    def test_every_profession_parses_to_its_verified_id(self):
        # The ids below were verified live against character_skills on
        # 2026-08-21; this pins the dict against silent edits.
        expected = {
            "first aid": 129, "blacksmithing": 164, "leatherworking": 165,
            "alchemy": 171, "herbalism": 182, "cooking": 185, "mining": 186,
            "tailoring": 197, "engineering": 202, "enchanting": 333,
            "fishing": 356, "skinning": 393,
        }
        self.assertEqual(goals.SKILL_IDS, expected)
        for name in expected:
            parsed = parse_goal(f"get {name} to 75")
            self.assertEqual(parsed, Goal("skill", 75, name), name)

    def test_two_word_profession_with_extra_spaces(self):
        self.assertEqual(parse_goal("get first  aid to 150"), Goal("skill", 150, "first aid"))

    def test_skill_up_to(self):
        self.assertEqual(parse_goal("push mining up to 75"), Goal("skill", 75, "mining"))

    def test_level_your_profession_is_a_skill_goal_not_a_level_goal(self):
        self.assertEqual(parse_goal("level your cooking to 150"), Goal("skill", 150, "cooking"))

    def test_skill_above_cap_is_not_a_goal(self):
        self.assertIsNone(parse_goal("get mining to 451"))

    def test_unknown_profession_is_not_a_goal(self):
        self.assertIsNone(parse_goal("get jewelcrafting to 75"))


class ParseCancelTest(unittest.TestCase):
    def test_forget_your_goal(self):
        self.assertEqual(parse_goal("forget your goal"), CancelGoal())

    def test_cancel_the_goal(self):
        self.assertEqual(parse_goal("cancel the goal"), CancelGoal())

    def test_abandon_goals_plural(self):
        self.assertEqual(parse_goal("abandon your goals"), CancelGoal())

    def test_cancel_far_from_goal_does_not_bind(self):
        # 'drop' and 'goal' in different sentences: the bounded gap in the
        # cancel pattern must not join them across the period.
        self.assertIsNone(parse_goal("drop that quest. a goal is a promise"))


class ParseNonGoalTest(unittest.TestCase):
    def test_plain_orders_are_not_goals(self):
        for text in ("follow", "go kill boars until you feel stronger",
                     "stats", "sell your junk and repair"):
            self.assertIsNone(parse_goal(text), text)


def make_row(**over):
    row = {
        "id": 7,
        "character_name": "Grug",
        "kind": "level",
        "skill_name": None,
        "target": 5,
        "status": "active",
        "channel_id": "123",
        "last_report": None,
    }
    row.update(over)
    return row


class ReconcileTest(unittest.TestCase):
    def test_completed_goal_stays_silent_over_many_cycles(self):
        row = make_row(status="completed", last_report="5")
        for _ in range(5):
            self.assertEqual(reconcile(row, 6), [])

    def test_cancelled_goal_stays_silent_over_many_cycles(self):
        row = make_row(status="cancelled", last_report="3")
        for _ in range(5):
            self.assertEqual(reconcile(row, 4), [])

    def test_unobservable_character_yields_no_actions(self):
        self.assertEqual(reconcile(make_row(), None), [])

    def test_first_sighting_issues_strategy_and_records(self):
        actions = reconcile(make_row(), 1)
        self.assertEqual(actions, [
            StrategyCommand("Grug", "co +grind"),
            RecordProgress(7, 1),
        ])

    def test_steady_state_is_read_only(self):
        # Pinned: an unchanged observation produces NOTHING - no strategy
        # re-issue, no writes, no chatter.
        row = make_row(last_report="3")
        for _ in range(5):
            self.assertEqual(reconcile(row, 3), [])

    def test_level_gain_reports_milestone_without_reissuing_strategy(self):
        actions = reconcile(make_row(last_report="2"), 3)
        self.assertNotIn(StrategyCommand("Grug", "co +grind"), actions)
        kinds = [type(a) for a in actions]
        self.assertEqual(kinds, [MilestoneThought, Report, RecordProgress])
        self.assertIn("level 3", actions[1].text)
        self.assertEqual(actions[2], RecordProgress(7, 3))

    def test_completion_at_target_marks_complete_and_reports(self):
        actions = reconcile(make_row(last_report="4"), 5)
        kinds = [type(a) for a in actions]
        # MarkComplete last on purpose: a failed Discord send must retry
        # the announcement next cycle, not complete silently.
        self.assertEqual(kinds, [MilestoneThought, Report, MarkComplete])
        self.assertIn("Goal complete", actions[1].text)
        self.assertIn("level 5", actions[1].text)
        self.assertEqual(actions[2], MarkComplete(7))

    def test_completion_beyond_target_also_completes(self):
        actions = reconcile(make_row(last_report="4"), 6)
        self.assertIn(MarkComplete(7), actions)

    def test_regression_records_quietly(self):
        # A rolled-back store after a worldserver restore: no milestone,
        # no strategy, just resync the recorded progress.
        actions = reconcile(make_row(last_report="4"), 3)
        self.assertEqual(actions, [RecordProgress(7, 3)])

    def test_corrupt_last_report_treated_as_first_sighting(self):
        actions = reconcile(make_row(last_report="not-a-number"), 2)
        self.assertEqual(actions[0], StrategyCommand("Grug", "co +grind"))


class ReconcileSkillTest(unittest.TestCase):
    def _row(self, **over):
        return make_row(kind="skill", skill_name="mining", target=75, **over)

    def test_small_gain_records_without_milestone(self):
        actions = reconcile(self._row(last_report="30"), 33)
        self.assertEqual(actions, [RecordProgress(7, 33)])

    def test_crossing_a_step_boundary_reports(self):
        actions = reconcile(self._row(last_report="48"), 51)
        kinds = [type(a) for a in actions]
        self.assertEqual(kinds, [MilestoneThought, Report, RecordProgress])
        self.assertIn("mining 51", actions[1].text)

    def test_completion_at_skill_target(self):
        actions = reconcile(self._row(last_report="74"), 75)
        self.assertEqual(type(actions[-1]), MarkComplete)
        self.assertIn("mining 75", actions[1].text)


class FakeStore:
    """Applies reconcile actions the way bridge.py applies them to MySQL."""

    def __init__(self, row):
        self.rows = {row["id"]: dict(row)}
        self.commands = []
        self.thoughts = []
        self.reports = []

    def active_rows(self):
        # A fresh dict per row, like a fresh cursor fetch: nothing survives
        # outside the persisted columns.
        return [dict(r) for r in self.rows.values() if r["status"] == "active"]

    def apply(self, action):
        if isinstance(action, StrategyCommand):
            self.commands.append(action.command)
        elif isinstance(action, MilestoneThought):
            self.thoughts.append(action.text)
        elif isinstance(action, Report):
            self.reports.append(action.text)
        elif isinstance(action, RecordProgress):
            self.rows[action.goal_id]["last_report"] = str(action.value)
        elif isinstance(action, MarkComplete):
            self.rows[action.goal_id]["status"] = "completed"

    def cycle(self, observed):
        for row in self.active_rows():
            for action in reconcile(row, observed):
                self.apply(action)


class LifecycleTest(unittest.TestCase):
    def test_level_goal_end_to_end(self):
        store = FakeStore(make_row())
        for observed in (1, 1, 2, 2, 3, 4, 5, 5, 6):
            store.cycle(observed)
        # Strategy exactly once, at first sighting.
        self.assertEqual(store.commands, ["co +grind"])
        # A milestone per level gained, then completion; nothing after.
        self.assertEqual(len(store.reports), 4)
        self.assertIn("level 2", store.reports[0])
        self.assertIn("Goal complete", store.reports[-1])
        self.assertEqual(store.rows[7]["status"], "completed")
        # Post-completion cycles were absorbed silently (absence pinned).
        self.assertEqual(len(store.thoughts), len(store.reports))

    def test_restart_mid_goal_changes_nothing(self):
        store = FakeStore(make_row())
        store.cycle(1)
        store.cycle(2)
        # 'Restart': a second supervisor built ONLY from the persisted rows.
        reborn = FakeStore(store.rows[7])
        reborn.cycle(2)
        self.assertEqual(reborn.commands, [])  # no strategy re-issue
        self.assertEqual(reborn.reports, [])
        reborn.cycle(3)
        self.assertEqual(len(reborn.reports), 1)
        self.assertIn("level 3", reborn.reports[0])

    def test_cancelled_goal_issues_nothing_over_many_cycles(self):
        store = FakeStore(make_row(last_report="2"))
        store.rows[7]["status"] = "cancelled"
        for observed in (3, 4, 5, 6, 7):
            store.cycle(observed)
        self.assertEqual(store.commands, [])
        self.assertEqual(store.reports, [])
        self.assertEqual(store.thoughts, [])


class TextTest(unittest.TestCase):
    def test_ack_names_the_goal(self):
        text = goals.ack_text("Grug", Goal("level", 5))
        self.assertIn("Grug", text)
        self.assertIn("level 5", text)

    def test_skill_ack_names_the_profession(self):
        text = goals.ack_text("Grug", Goal("skill", 300, "blacksmithing"))
        self.assertIn("blacksmithing 300", text)

    def test_cancel_text_counts(self):
        self.assertIn("no active goal", goals.cancel_text("Grug", 0))
        self.assertIn("1 goal cancelled", goals.cancel_text("Grug", 1))
        self.assertIn("2 goals cancelled", goals.cancel_text("Grug", 2))


if __name__ == "__main__":
    unittest.main()

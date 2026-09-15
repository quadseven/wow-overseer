"""Goal supervisor tests: parsing, reconcile decisions, fake-store lifecycle.

No MySQL and no Discord anywhere - the store is a dict a tiny fake mutates
by applying the typed actions reconcile returns, which is exactly the seam
bridge.py implements against the real store (infra#2601).
"""
import ast
import pathlib
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
            # Added for the family's trade plan (infra#2757), and with a
            # DIFFERENT provenance that the module says out loud: nobody on
            # this realm holds either, so there was no live row to check them
            # against. They come from the core's own enum at the pinned SHA -
            # SharedDefines.h:3218 and :3235 in
            # mod-playerbots/azerothcore-wotlk@efe123fa - which also matches
            # every one of the twelve above, which is how the two sources were
            # checked against each other rather than assumed to agree.
            "jewelcrafting": 755, "inscription": 773,
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
        """Was 'jewelcrafting', which stopped being unknown when the family's
        trade plan needed it (infra#2757). Archaeology is a Cataclysm
        profession and does not exist on a 3.3.5a realm at all, so it is the
        stable version of the same assertion."""
        self.assertIsNone(parse_goal("get archaeology to 75"))


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
            StrategyCommand("Grug", "nc +grind"),
            RecordProgress(7, 1),
        ])

    def test_a_stalled_goal_records_the_stall_and_stays_quiet(self):
        """No progress is usually just a slow grind, so it must not chatter -
        but it must be counted, because it is also what a lost strategy looks
        like."""
        row = make_row(last_report="3")
        self.assertEqual(reconcile(row, 3),
                         [RecordProgress(7, 3, stalls=1)])

    def test_a_goal_stalled_long_enough_is_put_back_on_task(self):
        """PlayerbotAI::ResetStrategies runs on login and rebuilds strategies
        from defaults, and the autonomous ones are gated behind IsRandomBot(),
        false for named characters. The roster loop relogs anyone who drops, so
        a long goal will meet this. Issued once and never again, the goal goes
        inert while its row still reads 'active'."""
        row = make_row(last_report="3/%d" % (goals.REASSERT_AFTER_CYCLES - 1))
        actions = reconcile(row, 3)
        self.assertEqual(actions[0], StrategyCommand("Grug", "nc +grind"))
        self.assertEqual(actions[1], RecordProgress(7, 3, stalls=0))

    def test_the_stall_counter_resets_when_progress_resumes(self):
        row = make_row(last_report="3/%d" % (goals.REASSERT_AFTER_CYCLES - 1))
        recorded = [a for a in reconcile(row, 4)
                    if isinstance(a, goals.RecordProgress)]
        self.assertEqual(recorded, [RecordProgress(7, 4)])
        self.assertEqual(recorded[0].stalls, 0)

    def test_a_row_written_before_stalls_existed_still_reads(self):
        """Rows in the live table hold a bare integer."""
        self.assertEqual(goals._read_report({"last_report": "12"}), (12, 0))
        self.assertEqual(goals._read_report({"last_report": "12/3"}), (12, 3))
        self.assertEqual(goals._read_report({"last_report": ""}), (None, 0))

    def test_level_gain_reports_milestone_without_reissuing_strategy(self):
        actions = reconcile(make_row(last_report="2"), 3)
        self.assertNotIn(StrategyCommand("Grug", "nc +grind"), actions)
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
        self.assertEqual(actions[0], StrategyCommand("Grug", "nc +grind"))


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
        self.assertEqual(store.commands, ["nc +grind"])
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


class StrategyChannelTest(unittest.TestCase):
    """The bug this class exists for shipped, delivered cleanly, and did
    nothing for weeks.

    goals.py sent 'co +grind'. mod-playerbots registers grind on the NON-combat
    engine (AiFactory::AddDefaultNonCombatStrategies calls
    `nonCombatEngine->addStrategy("grind")`), so the combat channel adds it to
    an engine that does not move the character. Every layer reported success:
    the command row reached status 'delivered', the goal row stayed 'active',
    and the bot never took a step.

    Measured live, one character, 90 seconds each:

        Ugga before        -8950,-132
        after 'co +grind'  -8950,-132
        after 'nc +grind'  -8990,-103
    """

    def test_the_strategy_goes_down_the_non_combat_channel(self):
        # kind='skill' USED TO BE IN THIS LIST, and taking it out is the point
        # of infra#3731 rather than a narrowing of the test - a skill goal no
        # longer gets a combat strategy at all, on either channel. The refusal
        # is asserted by SkillGoalIssuesNoCombatStrategyTest below.
        for kind, skill in (("level", None), ("dungeon", "scarlet-library")):
            with self.subTest(kind=kind):
                cmd = goals.strategy_for(make_row(kind=kind, skill_name=skill))
                self.assertTrue(
                    cmd.startswith("nc "),
                    "grind lives on the non-combat engine; %r reaches an engine "
                    "that cannot move the character" % cmd,
                )

    def test_the_command_is_one_the_bot_grammar_accepts(self):
        """'nc' and 'co' are the two strategy verbs. Anything else is parsed as
        some other command entirely and silently does something unrelated."""
        cmd = goals.strategy_for(make_row())
        verb, _, rest = cmd.partition(" ")
        self.assertIn(verb, ("nc", "co"))
        self.assertTrue(rest.startswith(("+", "-", "~", "!", "?")),
                        "strategy changes are sign-prefixed: %r" % cmd)


class LifeStrategyTest(unittest.TestCase):
    """They stopped working and nothing said so.

    `grind` means "kill what is in front of you". It worked at level 1 in a
    starting zone and stopped at level 7, because nothing moves these
    characters to level-appropriate content - RandomPlayerbotMgr's teleporting
    only applies to bots in its own pool, and named characters are not in it.

    Measured live, same spot, 150 seconds, one on each strategy:

        Grog  'new rpg'  -8800 -> -8924   travelled 124 yards
        Ugga  'grind'    -8800 -> -8797   moved 3
    """

    def test_the_life_strategy_is_not_the_grind_strategy(self):
        self.assertNotEqual(goals.LIFE_STRATEGY, goals.strategy_for(make_row()))

    def test_it_goes_down_the_non_combat_channel_too(self):
        """Same trap as the goal strategy: the combat channel reaches an engine
        that cannot move the character."""
        self.assertTrue(goals.LIFE_STRATEGY.startswith("nc "))

    def test_it_adds_a_strategy_rather_than_replacing_the_set(self):
        """A bare or '!' prefixed command resets strategies, which would strip
        whatever the goal supervisor had just asked for."""
        _, _, rest = goals.LIFE_STRATEGY.partition(" ")
        self.assertTrue(rest.startswith("+"), goals.LIFE_STRATEGY)


class DuplicateGoalTest(unittest.TestCase):
    """The council meets hourly and keeps reaching the same conclusion while
    the work is still in progress. Replacing the goal each time wiped
    last_report - restarting the progress record and the stall counter that
    re-issues a lost strategy - so the supervisor never got far enough to
    re-assert anything."""

    def test_an_identical_goal_in_progress_is_recognised(self):
        active = [{"kind": "level", "target": 7}]
        self.assertTrue(goals.already_working("level", 7, active))

    def test_a_different_target_is_a_different_goal(self):
        active = [{"kind": "level", "target": 7}]
        self.assertFalse(goals.already_working("level", 9, active))

    def test_a_different_kind_is_a_different_goal(self):
        active = [{"kind": "skill", "target": 7}]
        self.assertFalse(goals.already_working("level", 7, active))

    def test_no_active_goal_means_nothing_to_duplicate(self):
        self.assertFalse(goals.already_working("level", 7, []))

    def test_a_target_stored_as_text_still_matches(self):
        """MySQL hands back what the column type gives; the rule must not
        depend on which."""
        self.assertTrue(goals.already_working("level", 7, [{"kind": "level", "target": "7"}]))


class PartyThatTravelsTest(unittest.TestCase):
    """One character travels and the rest follow.

    `follow` was inert for all five: it resolves through a formation value set
    to `chaos`, and ChaosFormation::GetLocation() opens with GetMaster(), which
    is null for a party of masterless bots. They had followed nobody, ever.

    Even repaired it loses - `follow` runs at relevance 1.0 while `new rpg`'s
    actions run 3.0 to 11.0. Taking the wander OFF the followers is what makes
    following possible. Measured live: a 937-yard spread became four of them
    standing within three yards.
    """

    def test_the_leader_travels(self):
        self.assertIn(goals.LIFE_STRATEGY, goals.life_strategies(leads=True))

    def test_a_travelling_leader_is_not_also_put_on_a_task(self):
        """infra#3423. The leader branch is the ONLY one that ever granted a
        diverter, so it is the only one this parameter changes. A character
        part-way through an errand already has a job, and mod-overseer has
        stood down everything that would pull it off that job for the trip -
        granting the task strategy on top makes the two writers take turns.

        Pinned here, beside the cases that walk the un-travelled path, so the
        cluster covers both sides of the branch rather than only the resting
        default. The full invariant, read against the module's own
        ESCORT_DIVERT_STRATEGIES rather than a name copied into this repo,
        lives in test_escort_owns_the_strategy.py.
        """
        task = goals.strategy_for({"kind": "level"})
        self.assertIn(task, goals.life_strategies(leads=True))
        self.assertNotIn(task, goals.life_strategies(leads=True, travelling=True))

    def test_a_travelling_follower_never_had_the_task_strategy_anyway(self):
        """The follower branches grant `new rpg`, `follow` and `flee`, none of
        which an escort stands down, so `travelling` is a no-op for them. Worth
        pinning rather than assuming: it is why the fix touches one branch, and
        a reader checking the follower case would otherwise see nothing change
        and suspect the parameter was not wired up."""
        for aimed in (True, False):
            with self.subTest(aimed=aimed):
                self.assertEqual(
                    goals.life_strategies(leads=False, aimed=aimed),
                    goals.life_strategies(leads=False, aimed=aimed, travelling=True),
                )

    def test_a_follower_does_not(self):
        """The whole fix. A follower given the wander strategy outranks its own
        follow every tick and drifts off alone."""
        self.assertNotIn(goals.LIFE_STRATEGY, goals.life_strategies(leads=False))
        self.assertIn("nc -new rpg", goals.life_strategies(leads=False))

    def test_a_follower_is_told_to_follow(self):
        self.assertTrue(any("+follow" in c for c in goals.life_strategies(leads=False)))

    def test_the_wander_is_dropped_before_the_follow_is_asked_for(self):
        """Otherwise there is a tick where both are set and the follower is
        gone again."""
        cmds = goals.life_strategies(leads=False)
        self.assertLess(cmds.index("nc -new rpg"),
                        next(i for i, c in enumerate(cmds) if "+follow" in c))

    def test_fleeing_is_a_combat_strategy(self):
        """FleeStrategy's triggers are panic and critical health - combat
        states. On the non-combat engine it reaches something that never sees
        them, which is the `co +grind` mistake with the channels swapped."""
        self.assertTrue(goals.FLEE_STRATEGY.startswith("co "), goals.FLEE_STRATEGY)

    def test_everyone_gets_self_preservation(self):
        """AiFactory adds `flee` for nobody, random bot or not. Without it they
        fight to zero every time."""
        for leads in (True, False):
            # Travelling too: an errand takes the TASK away, never the
            # self-preservation. A traveller that stopped fleeing would be the
            # withhold-everything mistake, and it would be invisible here if
            # this loop only ever walked the resting default.
            for travelling in (True, False):
                with self.subTest(leads=leads, travelling=travelling):
                    self.assertIn(
                        goals.FLEE_STRATEGY,
                        goals.life_strategies(leads=leads, travelling=travelling),
                    )

    def test_every_command_reaches_an_engine_that_can_act(self):
        """The `co +grind` lesson: a command on the wrong channel is delivered
        cleanly and does nothing."""
        for leads in (True, False):
            for travelling in (True, False):
                for cmd in goals.life_strategies(leads=leads, travelling=travelling):
                    verb, _, rest = cmd.partition(" ")
                    self.assertIn(verb, ("nc", "co"), cmd)
                    self.assertTrue(rest.startswith(("+", "-")), cmd)


class StrategiesReturnWithTheCharacter(unittest.TestCase):
    """`new rpg` is never a default for a named character - it exists only
    because the life loop grants it, and ResetStrategies takes it away on
    every login. Noticing the return is what closes a ten-minute hole."""

    def test_a_character_back_under_the_ai_is_reported(self):
        self.assertEqual(
            frozenset({"Grug"}),
            goals.returned_to_ai(frozenset({"Bork"}), frozenset({"Bork", "Grug"})))

    def test_nobody_new_means_nobody_is_re_issued(self):
        """These commands reach the game as whispers. Re-issuing to characters
        that never lost anything is visible noise in Evan's chat."""
        both = frozenset({"Bork", "Grug"})
        self.assertEqual(frozenset(), goals.returned_to_ai(both, both))

    def test_the_first_look_fires_for_nobody(self):
        """At startup every character looks like a return. The protect cycle
        already covers startup; firing here too would re-issue to all five on
        every restart of the bridge."""
        self.assertEqual(
            frozenset(),
            goals.returned_to_ai(None, frozenset({"Grug", "Bork", "Og"})))

    def test_a_character_taken_BY_a_person_is_not_a_return(self):
        """Losing AI control is the start of the problem, not the end of it -
        the re-issue belongs on the way back, when a strategy can actually be
        accepted. Commanding an AI-less character only fills the table with
        errors."""
        self.assertEqual(
            frozenset(),
            goals.returned_to_ai(frozenset({"Grug", "Bork"}), frozenset({"Bork"})))

    def test_a_full_round_trip_fires_exactly_once(self):
        """Human takes Grug, human gives him back. One re-issue, on the way
        back, and nothing on the tick after."""
        seen = frozenset({"Grug", "Bork"})
        taken = frozenset({"Bork"})
        self.assertEqual(frozenset(), goals.returned_to_ai(seen, taken))
        given_back = frozenset({"Grug", "Bork"})
        self.assertEqual(frozenset({"Grug"}), goals.returned_to_ai(taken, given_back))
        self.assertEqual(frozenset(), goals.returned_to_ai(given_back, given_back))

    def test_the_leader_coming_back_gets_what_drives_him(self):
        """The whole point: a leader who relogged must get `new rpg` back, or
        four followers stand still around him."""
        self.assertIn("nc +new rpg", goals.life_strategies(leads=True))


class TheReturnLoopIsActuallyWired(unittest.TestCase):
    """goals.returned_to_ai can be perfect and never called.

    bridge.py cannot be imported here - it needs pymysql, discord and a live
    MySQL - so this walks its AST. An AST walk and not a grep on purpose: a
    call written in a comment satisfies a grep, and a comment gives nobody
    their strategy back.
    """

    @classmethod
    def setUpClass(cls):
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        cls.tree = ast.parse(src)
        cls.fn = next(
            (n for n in ast.walk(cls.tree)
             if isinstance(n, ast.AsyncFunctionDef) and n.name == "_restore_lost_lives"),
            None)

    def _calls(self):
        out = set()
        for node in ast.walk(self.fn):
            if isinstance(node, ast.Attribute):
                out.add(node.attr)
            elif isinstance(node, ast.Name):
                out.add(node.id)
        return out

    def test_the_loop_exists(self):
        self.assertIsNotNone(self.fn, "no _restore_lost_lives in bridge.py")

    def test_it_is_started_and_held(self):
        """asyncio keeps only a weak reference to a running task, so a loop
        created and not held can be collected mid-flight - and it stops with
        no error and nothing in the log."""
        hook = next(n for n in ast.walk(self.tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "setup_hook")
        started = {n.attr for n in ast.walk(hook) if isinstance(n, ast.Attribute)}
        self.assertIn("_restore_lost_lives", started)

    def test_it_asks_who_came_back_rather_than_re_issuing_to_everyone(self):
        """These commands reach the game as whispers; blanket re-issues are
        visible noise in Evan's chat."""
        self.assertIn("returned_to_ai", self._calls())

    def test_it_actually_hands_the_life_back(self):
        self.assertIn("_give_them_a_life", self._calls())

    def test_it_rechecks_far_more_often_than_the_protect_sweep(self):
        """The whole point is closing a 600-second hole. A recheck on the same
        cadence would close nothing."""
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        body = src[src.index("async def _restore_lost_lives"):]
        body = body[:body.index("async def _protect_characters")]
        self.assertIn("LIFE_RECHECK_SECONDS", body)
        default = body.split('LIFE_RECHECK_SECONDS", "')[1].split('"')[0]
        self.assertLessEqual(float(default), 60.0)
        self.assertGreaterEqual(float(default), 5.0)


def _skill_row(**over):
    row = make_row(kind="skill", skill_name="tailoring", target=225)
    row.update(over)
    return row


class SkillGoalIssuesNoCombatStrategyTest(unittest.TestCase):
    """The defect, and the only test that would have caught it (infra#3731).

    `strategy_for` answered every kind with `nc +grind` - "kill what is in
    front of you" - skill goals included, and its own docstring said so as a
    deliberate scope decision. The result was the owner's own sentence: "why
    are they fighting in tanaris instead of working on their professions like i
    told you to?". The family's most recent deaths are to Wastewander Assassins
    and Wastewander Shadow Mages, in Tanaris, which is that instruction carried
    out exactly.

    HOW EACH OF THESE FAILS. Route kind='skill' back through the level branch
    and the first test stops raising; delete the guard in `strategy_for` and the
    second one returns a string instead; emit a StrategyCommand anywhere in the
    skill branch and the third one sees it.
    """

    def test_asking_for_a_combat_strategy_for_a_skill_goal_raises(self):
        with self.assertRaises(ValueError):
            goals.strategy_for(_skill_row())

    def test_it_still_answers_every_other_kind(self):
        """The guard must be narrow. `life_strategies` asks this function for
        the leader's task strategy on every protect sweep, and a guard that
        caught more than skill goals would take four followers' leader off his
        only reason to move."""
        for kind in ("level", "quest", "dungeon"):
            with self.subTest(kind=kind):
                self.assertEqual("nc +grind",
                                 goals.strategy_for(make_row(kind=kind)))

    def test_a_skill_goal_drives_a_profession_and_never_a_strategy(self):
        actions = reconcile(_skill_row(), 40)
        self.assertTrue(
            any(isinstance(a, goals.DriveSkill) for a in actions),
            "a skill goal must produce a profession drive: %r" % (actions,),
        )
        self.assertFalse(
            any(isinstance(a, StrategyCommand) for a in actions),
            "a skill goal must never produce a combat strategy: %r" % (actions,),
        )

    def test_the_drive_carries_the_facts_the_planner_needs(self):
        drive = next(a for a in reconcile(_skill_row(), 40)
                     if isinstance(a, goals.DriveSkill))
        self.assertEqual(drive.skill_name, "tailoring")
        self.assertEqual(drive.skill_id, goals.SKILL_IDS["tailoring"])
        self.assertEqual(drive.observed, 40)
        self.assertEqual(drive.target, 225)
        self.assertEqual(drive.beneficiary, "Grug")

    def test_a_skill_with_no_id_commands_nobody(self):
        """Unreachable on the live path - `_observe_goal` returns None for a
        name SKILL_IDS does not carry, so reconcile never gets here - but the
        honest answer is still to record and command nobody. Falling through to
        a strategy is the whole defect."""
        actions = reconcile(_skill_row(skill_name="basket weaving"), 3)
        self.assertEqual(actions, [RecordProgress(7, 3)])


class SkillDriveCadenceTest(unittest.TestCase):
    """When the profession drive is re-issued, and when the goal speaks.

    ONE COUNTER SERVES BOTH, and it is never reset by its own re-assert - that
    is the difference from the level branch, where zeroing on re-issue is
    correct because pacing the re-issue is the counter's only job. Here it must
    also be able to REACH SKILL_BARREN_CYCLES, and a counter its own re-assert
    zeroes every fifth cycle can never reach thirty.
    """

    def _drives(self, actions):
        return [a for a in actions if isinstance(a, goals.DriveSkill)]

    def _recorded(self, actions):
        return next(a for a in actions if isinstance(a, RecordProgress))

    def test_first_sighting_drives_and_speaks(self):
        drives = self._drives(reconcile(_skill_row(), 40))
        self.assertEqual(len(drives), 1)
        self.assertTrue(drives[0].speak,
                        "the goal must say what it is going to do when it is set")

    def test_progress_neither_drives_nor_speaks(self):
        """Steady state is read-only - that is this module's whole contract.
        A drive on a cycle that made progress would insert a family-wide job
        fan-out for a family already doing the right thing."""
        actions = reconcile(_skill_row(last_report="40/3"), 41)
        self.assertEqual(self._drives(actions), [])
        self.assertEqual(self._recorded(actions).stalls, 0)

    def test_a_short_stall_counts_and_stays_quiet(self):
        for stalls in range(1, goals.REASSERT_AFTER_CYCLES - 1):
            with self.subTest(stalls=stalls):
                actions = reconcile(_skill_row(last_report="40/%d" % stalls), 40)
                self.assertEqual(self._drives(actions), [])
                self.assertEqual(self._recorded(actions).stalls, stalls + 1)

    def test_a_run_of_stalled_cycles_re_drives(self):
        row = _skill_row(last_report="40/%d" % (goals.REASSERT_AFTER_CYCLES - 1))
        actions = reconcile(row, 40)
        self.assertEqual(len(self._drives(actions)), 1)
        self.assertFalse(self._drives(actions)[0].speak,
                         "a routine re-assert is a log line, not a Discord line")

    def test_the_re_assert_does_not_reset_the_counter(self):
        """The bug this guards: zero the counter on re-drive and the barren
        verdict below becomes unreachable, so a goal that never moves reports
        healthy for ever - the exact shape of the defect this change fixes."""
        row = _skill_row(last_report="40/%d" % (goals.REASSERT_AFTER_CYCLES - 1))
        self.assertEqual(self._recorded(reconcile(row, 40)).stalls,
                         goals.REASSERT_AFTER_CYCLES)

    def test_a_barren_goal_speaks(self):
        row = _skill_row(last_report="40/%d" % (goals.SKILL_BARREN_CYCLES - 1))
        drives = self._drives(reconcile(row, 40))
        self.assertEqual(len(drives), 1)
        self.assertTrue(drives[0].speak)
        self.assertEqual(drives[0].stalls, goals.SKILL_BARREN_CYCLES)

    def test_it_does_not_speak_every_cycle_once_barren(self):
        """A blocked goal is blocked on every cycle by definition. Narrating it
        once a minute buries the channel and teaches the operator to stop
        reading it."""
        row = _skill_row(last_report="40/%d" % goals.SKILL_BARREN_CYCLES)
        drives = self._drives(reconcile(row, 40))
        self.assertEqual(drives, [], "no drive is due on this cycle")

    def test_a_falling_reading_clears_the_counter(self):
        """A skill value cannot fall in the engine, so a fall means the read
        changed underneath us. Holding a counter high on a reading nobody
        trusts is the wrong direction to be wrong in."""
        row = _skill_row(last_report="40/7")
        self.assertEqual(self._recorded(reconcile(row, 38)).stalls, 0)

    def test_completion_outranks_every_cadence(self):
        actions = reconcile(_skill_row(target=50, last_report="49/99"), 50)
        self.assertEqual(self._drives(actions), [])
        self.assertEqual(type(actions[-1]), MarkComplete)


class SkillBarrenArithmeticTest(unittest.TestCase):
    """The barren threshold is a number of CYCLES, and the cycle length lives
    in bridge.py. These two constants have to be read together or the threshold
    means nothing.
    """

    # The worldserver's PlayerSaveInterval on this realm, in seconds. With
    # PlayerSave.AdditionalSaves = 0 this is the full staleness of
    # `character_skills`, and 30-50 crafts of drift at the family's rate.
    SAVE_INTERVAL_SECONDS = 900.0

    def _goal_interval(self) -> float:
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        return float(src.split('GOAL_INTERVAL_SECONDS", "')[1].split('"')[0])

    def test_barren_is_a_whole_number_of_re_assert_periods(self):
        """Every cycle that speaks must also be a cycle that re-drives, so the
        sentence a person reads is attached to a fresh decision. Break the
        divisibility and a barren goal speaks on a cycle with no plan behind
        it."""
        self.assertEqual(
            goals.SKILL_BARREN_CYCLES % goals.REASSERT_AFTER_CYCLES, 0)

    def test_barren_outlasts_two_save_intervals(self):
        """Fifteen cycles can pass with real progress the table has not
        admitted yet. A threshold below that accuses a working drive of doing
        nothing on the strength of the save clock alone."""
        window = goals.SKILL_BARREN_CYCLES * self._goal_interval()
        self.assertGreaterEqual(
            window, 2 * self.SAVE_INTERVAL_SECONDS,
            "SKILL_BARREN_CYCLES x GOAL_INTERVAL is %.0fs, inside two save "
            "intervals - a stale read alone could trigger it" % window,
        )


class TheSkillDriveIsActuallyWired(unittest.TestCase):
    """goals.DriveSkill can be perfect and never applied.

    This repo's dominant failure is a correct mechanism with no caller, so the
    action being emitted is not the deliverable - the bridge acting on it is.
    bridge.py cannot be imported here (pymysql, discord, a live MySQL), so this
    walks its AST. An AST walk and not a grep on purpose: a name written in a
    comment satisfies a grep, and a comment writes no job order.
    """

    @classmethod
    def setUpClass(cls):
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        cls.tree = ast.parse(src)

    def _fn(self, name):
        return next(
            (n for n in ast.walk(self.tree)
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
             and n.name == name),
            None)

    def _names(self, fn):
        out = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute):
                out.add(node.attr)
            elif isinstance(node, ast.Name):
                out.add(node.id)
        return out

    def test_bridge_imports_the_planner(self):
        imported = {n.name for node in ast.walk(self.tree)
                    if isinstance(node, ast.Import) for n in node.names}
        self.assertIn("skillgoal", imported)

    def test_the_action_is_dispatched(self):
        fn = self._fn("_apply_goal_action")
        self.assertIsNotNone(fn, "no _apply_goal_action in bridge.py")
        names = self._names(fn)
        self.assertIn("DriveSkill", names)
        self.assertIn("_drive_skill", names)

    def test_the_handler_asks_the_planner_rather_than_deciding(self):
        fn = self._fn("_drive_skill")
        self.assertIsNotNone(fn, "no _drive_skill in bridge.py")
        names = self._names(fn)
        # The two live facts the plan cannot see for itself...
        self.assertIn("_fetch_skill_cap", names)
        self.assertIn("standing_mode", names)
        # ...the decision itself...
        self.assertIn("skillgoal", names)
        self.assertIn("plan", names)
        # ...and the ONE sanctioned writer for the job column.
        self.assertIn("_set_job", names)

    def test_every_action_reconcile_can_emit_has_a_handler(self):
        """THE GUARD THE DISPATCH TABLE EXISTS FOR, and the one the old
        `elif isinstance` chain could not offer.

        An action kind that fell off the end of that chain did nothing at all,
        silently, for ever - a decision made and dropped on the floor. goals.py
        has grown roughly one action per epic, so "somebody added a kind and
        nobody taught the bridge to apply it" is not hypothetical; it is how
        DriveSkill itself could have shipped inert.

        HOW THIS FAILS: add an action dataclass to goals.py, return it from any
        reconcile branch, and forget the table entry. Nothing else in the suite
        would notice.
        """
        goals_src = (pathlib.Path(__file__).resolve().parent.parent / "goals.py").read_text()
        goals_tree = ast.parse(goals_src)
        declared = {n.name for n in ast.walk(goals_tree)
                    if isinstance(n, ast.ClassDef)}

        emitted = set()
        for fn in ast.walk(goals_tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            if fn.name != "reconcile" and not fn.name.startswith("_reconcile_"):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in declared:
                        emitted.add(node.func.id)
        self.assertTrue(emitted, "found no actions at all - the walk is broken")

        fn = self._fn("_apply_goal_action")
        handled = {n.attr for n in ast.walk(fn)
                   if isinstance(n, ast.Attribute)
                   and isinstance(n.value, ast.Name) and n.value.id == "goals"}
        missing = sorted(emitted - handled)
        self.assertEqual(
            missing, [],
            "goals.reconcile emits %s and _apply_goal_action applies none of "
            "them - the decision is made and then dropped" % missing,
        )

    def test_an_unknown_action_is_not_silently_dropped(self):
        """The table's other half. A `.get` that returned None and fell through
        would be the same silence in a tidier shape."""
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        body = src[src.index("async def _apply_goal_action"):]
        body = body[:body.index("async def _goal_strategy")]
        self.assertIn("log.warning", body)

    def test_the_handler_never_writes_a_command_row_itself(self):
        """`_insert_command` here would be a second writer racing `_set_job`'s
        guard, and `_write_trade_errand` would make this the second writer for
        travel_npc - the mistake that pinned the family in a Gadgetzan shop for
        half an hour (infra#3703, infra#3708, infra#3728)."""
        names = self._names(self._fn("_drive_skill"))
        for forbidden in ("_insert_command", "_write_trade_errand"):
            self.assertNotIn(forbidden, names)


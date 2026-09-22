"""The council's quest decision has to survive into something that moves.

WHAT THESE ARE ABOUT. Watched live in party chat: Ugga said she needed one
more Large Candle for Kobold Candles, three of them said they would help, Ugga
said "then it is settled" - and all five stood still. 0.0 yards in 45 seconds,
none in combat, 11 yards from the kobolds that drop the item. The overseer log
said `council: plan 'quest' is not a goal the supervisor drives`.

Every test below pins one of the links in the chain that was broken, and the
ones that would fail SILENTLY on the live database are called out by name.
"""

import ast
import pathlib
import unittest

import council
import goals
import questbook


# --- the schema migration, which is the one that can be silently dead -----


LEGACY_KIND = "enum('level','skill')"
# Fully migrated as of the 'dungeon' kind (infra dungeon-decision gap):
# goals.goal_migrations reads GOAL_KINDS itself now rather than naming one
# value, so "migrated" means every kind the module currently writes, and
# this constant has to keep up with GOAL_KINDS or these tests would be
# pinning a shape the module no longer considers settled.
MIGRATED_KIND = "enum(%s)" % ",".join("'%s'" % k for k in goals.GOAL_KINDS)


class TheEnumMigration(unittest.TestCase):
    """CREATE TABLE IF NOT EXISTS will NOT add a value to an existing ENUM.

    This is the failure that passes every test and does nothing in production:
    the test database is always fresh, so its CREATE produces the final shape
    and the migration is never exercised, while the live overseer_goal - made
    months ago with ENUM('level','skill') - rejects the INSERT outright. The
    tests here run against the LEGACY shape on purpose.
    """

    def test_a_legacy_table_is_told_to_gain_quest(self):
        statements = goals.goal_migrations(LEGACY_KIND, has_quest_id=True)
        self.assertEqual(1, len(statements), statements)
        self.assertIn("MODIFY kind", statements[0])
        self.assertIn("'quest'", statements[0])

    def test_the_migration_keeps_every_kind_that_already_existed(self):
        """A MODIFY that dropped a value would silently orphan live rows.

        MySQL does not refuse it; it truncates. Every active level and skill
        goal in the table would become '' on the next write touching them.
        """
        statement = goals.goal_migrations(LEGACY_KIND, has_quest_id=True)[0]
        for kind in ("level", "skill", "quest"):
            self.assertIn("'%s'" % kind, statement, kind)

    def test_a_legacy_table_also_needs_the_quest_id_column(self):
        statements = goals.goal_migrations(LEGACY_KIND, has_quest_id=False)
        self.assertEqual(2, len(statements), statements)
        self.assertTrue(any("quest_id" in s and "ADD COLUMN" in s for s in statements))

    def test_it_is_idempotent_against_an_already_migrated_table(self):
        """Running twice must be a no-op, not an error and not a re-ALTER.

        The bridge runs this on EVERY start. An ALTER takes a metadata lock on
        a table the supervisor is reading once a minute, so re-running one
        unconditionally is a real cost, not just untidiness.
        """
        self.assertEqual([], goals.goal_migrations(MIGRATED_KIND, has_quest_id=True))

    def test_it_is_idempotent_against_a_fresh_database(self):
        """A fresh CREATE already produces the final shape.

        The migration must not fail on a database where the ENUM already has
        the value - which is every test database, and every new deployment.
        """
        self.assertEqual(
            [], goals.goal_migrations(goals.KIND_COLUMN.lower(), has_quest_id=True)
        )

    def test_applying_the_migration_reaches_a_settled_shape(self):
        """Simulate the ALTERs, then ask again: the answer must be nothing."""
        kind, has_quest_id = LEGACY_KIND, False
        for statement in goals.goal_migrations(kind, has_quest_id):
            if "MODIFY kind" in statement:
                kind = MIGRATED_KIND
            if "ADD COLUMN quest_id" in statement:
                has_quest_id = True
        self.assertEqual([], goals.goal_migrations(kind, has_quest_id))

    def test_an_absent_table_is_left_to_create_table(self):
        """No `kind` column means no table; an ALTER would just fail."""
        self.assertEqual([], goals.goal_migrations("", has_quest_id=False))

    def test_the_column_definition_matches_the_kinds_the_module_writes(self):
        """The enum and the code writing into it must not drift apart."""
        for kind in goals.GOAL_KINDS:
            self.assertIn("'%s'" % kind, goals.KIND_COLUMN)


# --- the quest id, threaded from the council to the goal ------------------


def _member(name, level, **kw):
    return council.Member(name=name, level=level, class_name="warrior", **kw)


class TheQuestIdSurvivesTheCouncil(unittest.TestCase):
    """`target` on a quest proposal is objectives REMAINING - it names no quest.

    So a quest goal handler could not get an id out of a plan at all, which is
    why the id is threaded rather than re-derived at persist time.
    """

    def test_a_quest_proposal_carries_the_id(self):
        me = _member(
            "Ugga", 10, quest="I need 1 more Large Candle.", quest_left=1, quest_id=3861
        )
        proposal = council.assess(me, public_levels={"Ugga": 10, "Grug": 10})
        self.assertEqual("quest", proposal.kind)
        self.assertEqual(3861, proposal.quest_id)

    def test_the_target_is_still_objectives_remaining(self):
        """Pinned because it is exactly why the id had to be added."""
        me = _member("Ugga", 10, quest="one more candle", quest_left=1, quest_id=3861)
        self.assertEqual(1, council.assess(me, public_levels={"Ugga": 10}).target)

    def test_the_id_reaches_the_agreed_plan(self):
        members = [
            _member(
                "Ugga",
                10,
                quest="I need 1 more Large Candle.",
                quest_left=1,
                quest_id=3861,
            ),
            _member("Grug", 10),
            _member("Bork", 10),
        ]
        held = council.hold(members, history=[])
        self.assertIsNotNone(held.plan)
        self.assertEqual("quest", held.plan.kind)
        self.assertEqual(3861, held.plan.quest_id)
        self.assertEqual("Ugga", held.plan.beneficiary)

    def test_two_different_quests_one_objective_from_done_do_not_merge(self):
        """(kind, self, target) is identical for both; only the id differs.

        Merging them would have the family agree to help with a quest nobody
        at the table ever named - the winner would carry one member's sentence
        and the other member's id, or worse, whichever sorted first.
        """
        proposals = [
            council.Proposal("Ugga", "quest", "Ugga", 1, 60, "candles", quest_id=3861),
            council.Proposal("Grug", "quest", "Grug", 1, 60, "kobolds", quest_id=176),
        ]
        merged = council._merge(proposals)
        self.assertEqual(2, len(merged), merged)


# --- choosing WHICH quest, via questbook ----------------------------------


def _quest(qid, **kw):
    return questbook.Quest(id=qid, title="quest %d" % qid, **kw)


class ChoosingTheQuestToDrive(unittest.TestCase):
    """questbook already knows who is behind and in what order they can catch
    up; drive_target filters that, it never re-ranks it."""

    def setUp(self):
        self.catalog = {
            35: _quest(35),
            37: _quest(37, prev_quest_id=35),
            176: _quest(176),
            3861: _quest(3861),
        }
        self.members = [
            questbook.Member(
                name="Grug",
                class_id=1,
                race_id=1,
                level=12,
                rewarded=frozenset({35, 37, 176, 3861}),
            ),
            questbook.Member(
                name="Bork",
                class_id=4,
                race_id=3,
                level=12,
                rewarded=frozenset({35, 37, 176, 3861}),
            ),
            questbook.Member(
                name="Ugga", class_id=5, race_id=1, level=10, held=frozenset({35})
            ),
        ]
        self.ledger = questbook.build(self.members, self.catalog)

    def test_the_council_s_own_quest_wins_when_the_traveller_holds_it(self):
        """The council already deliberated; second-guessing a decision the
        traveller can carry out would make the scene a decoration."""
        self.assertEqual(
            3861,
            questbook.drive_target(
                self.ledger,
                held_by_traveller={3861, 176},
                wanted=3861,
                beneficiary="Ugga",
            ),
        )

    def test_a_quest_the_traveller_does_not_hold_is_never_chosen(self):
        """NewRpgDoQuestAction dispatches only on a quest the bot HOLDS;
        anything else falls through to ChangeToIdle() on the next tick. Aiming
        at an unheld quest is the "delivered, nothing happened" failure."""
        chosen = questbook.drive_target(
            self.ledger, held_by_traveller=frozenset(), wanted=3861, beneficiary="Ugga"
        )
        self.assertEqual(0, chosen)

    def test_it_falls_back_to_the_catch_up_plan_in_the_plan_s_own_order(self):
        """35 before 37: 37 has 35 as its prerequisite, so a chooser that took
        the highest-numbered or first-listed quest would aim at a quest Ugga
        cannot possibly progress."""
        order = [q.id for q in self.ledger.plans["Ugga"]]
        self.assertLess(order.index(35), order.index(37), order)
        chosen = questbook.drive_target(
            self.ledger, held_by_traveller={35, 37}, wanted=0, beneficiary="Ugga"
        )
        self.assertEqual(35, chosen)

    def test_it_skips_plan_entries_the_traveller_cannot_drive(self):
        chosen = questbook.drive_target(
            self.ledger, held_by_traveller={37}, wanted=0, beneficiary="Ugga"
        )
        self.assertEqual(37, chosen)

    def test_with_no_beneficiary_it_helps_whoever_is_furthest_behind(self):
        self.assertEqual("Ugga", self.ledger.furthest_behind)
        self.assertEqual(
            35,
            questbook.drive_target(self.ledger, held_by_traveller={35, 37}),
        )

    def test_nothing_driveable_is_zero_and_not_a_guess(self):
        """0 says "the traveller is not carrying the work the family should do",
        whose answer is quest sharing - not a different aim."""
        self.assertEqual(
            0,
            questbook.drive_target(
                self.ledger, held_by_traveller={999}, wanted=3861, beneficiary="Ugga"
            ),
        )


# --- supervising a quest goal ---------------------------------------------


def _row(**kw):
    row = dict(
        id=7,
        character_name="Ugga",
        kind="quest",
        target=goals.QUEST_TARGET,
        quest_id=3861,
        status="active",
        last_report=None,
    )
    row.update(kw)
    return row


class SupervisingAQuestGoal(unittest.TestCase):
    def test_progress_counts_down_and_is_observed_as_a_rising_number(self):
        self.assertEqual(-3, goals.observed_from_left(3))
        self.assertEqual(0, goals.observed_from_left(0))
        self.assertIsNone(goals.observed_from_left(None))

    def test_first_sighting_aims_the_party_rather_than_grinding(self):
        """The whole ticket. `nc +grind` means "kill what is in front of you"
        and never travels; it is what has been overriding quest intent."""
        actions = goals.reconcile(_row(), goals.observed_from_left(1))
        aims = [a for a in actions if isinstance(a, goals.DriveQuest)]
        self.assertEqual(1, len(aims))
        self.assertEqual(3861, aims[0].quest_id)
        self.assertEqual("Ugga", aims[0].beneficiary)
        self.assertFalse([a for a in actions if isinstance(a, goals.StrategyCommand)])

    def test_a_quest_goal_never_issues_a_strategy_command(self):
        for left, report in ((3, None), (3, "-3/0"), (3, "-3/4"), (2, "-3/0")):
            actions = goals.reconcile(
                _row(last_report=report), goals.observed_from_left(left)
            )
            self.assertFalse(
                [a for a in actions if isinstance(a, goals.StrategyCommand)],
                (left, report, actions),
            )

    def test_the_aim_is_renewed_on_a_clock_even_while_progress_is_good(self):
        """RPG_DO_QUEST self-expires after 30 minutes and the bot then re-rolls
        a RANDOM quest from its log. A stall-triggered re-assert would never
        fire in exactly the case where everything looks healthiest."""
        cycles = goals.REASSERT_AFTER_CYCLES
        row = _row(last_report="-5/%d" % (cycles - 1))
        actions = goals.reconcile(row, goals.observed_from_left(4))
        self.assertTrue([a for a in actions if isinstance(a, goals.DriveQuest)])
        recorded = [a for a in actions if isinstance(a, goals.RecordProgress)][0]
        self.assertEqual(0, recorded.stalls, "the lease counter did not reset")

    def test_a_quiet_cycle_only_advances_the_lease_counter(self):
        actions = goals.reconcile(_row(last_report="-3/0"), goals.observed_from_left(3))
        self.assertEqual(1, len(actions), actions)
        self.assertEqual(1, actions[0].stalls)

    def test_every_objective_closed_is_reported(self):
        actions = goals.reconcile(_row(last_report="-3/0"), goals.observed_from_left(2))
        texts = [a.text for a in actions if isinstance(a, goals.Report)]
        self.assertEqual(1, len(texts))
        self.assertIn("2 objectives left", texts[0])

    def test_the_last_objective_reads_as_one_not_two(self):
        actions = goals.reconcile(_row(last_report="-2/0"), goals.observed_from_left(1))
        text = [a.text for a in actions if isinstance(a, goals.Report)][0]
        self.assertIn("1 objective left", text)

    def test_zero_left_completes_the_goal(self):
        actions = goals.reconcile(_row(last_report="-1/0"), goals.observed_from_left(0))
        self.assertTrue([a for a in actions if isinstance(a, goals.MarkComplete)])

    def test_completion_claims_objectives_done_and_not_the_quest_finished(self):
        """The turn-in is a separate act. Claiming the quest complete here
        would be the overseer over-claiming, which is the one thing it must
        never do."""
        text = goals.completion_text(_row(), 0)
        self.assertIn("hand it in", text)
        self.assertNotIn("reached", text)

    def test_an_unobservable_quest_says_nothing(self):
        """None is "the character is not holding it" - a real state while the
        family's quest logs still differ - and must not read as zero left."""
        self.assertEqual([], goals.reconcile(_row(), None))

    def test_a_goal_with_no_quest_id_does_not_aim_at_quest_zero(self):
        actions = goals.reconcile(_row(quest_id=0), goals.observed_from_left(2))
        self.assertFalse([a for a in actions if isinstance(a, goals.DriveQuest)])

    def test_completed_goals_stay_silent(self):
        self.assertEqual([], goals.reconcile(_row(status="completed"), -1))


class TellingTwoQuestGoalsApart(unittest.TestCase):
    def test_quest_goals_are_identified_by_id_and_not_by_target(self):
        """Every quest goal has target 0. Comparing targets would report
        "already working" for ANY quest the moment one was active, and the
        council's next decision would be swallowed in silence."""
        active = [{"kind": "quest", "target": 0, "quest_id": 3861}]
        self.assertTrue(goals.already_working("quest", 0, active, quest_id=3861))
        self.assertFalse(goals.already_working("quest", 0, active, quest_id=176))

    def test_level_goals_are_unaffected(self):
        active = [{"kind": "level", "target": 20}]
        self.assertTrue(goals.already_working("level", 20, active))
        self.assertFalse(goals.already_working("level", 21, active))


class TheWorkQuestVerb(unittest.TestCase):
    def test_it_parses_into_a_quest_goal(self):
        parsed = goals.parse_goal("Grug, work quest 3861 for Ugga")
        self.assertEqual("quest", parsed.kind)
        self.assertEqual(3861, parsed.quest_id)
        self.assertEqual(goals.QUEST_TARGET, parsed.target)

    def test_it_does_not_fire_on_a_word_that_merely_contains_it(self):
        self.assertIsNone(goals.parse_goal("homework quest 12"))

    def test_level_and_skill_orders_still_parse_as_they_did(self):
        self.assertEqual("level", goals.parse_goal("get to level 20").kind)
        self.assertEqual("skill", goals.parse_goal("cooking to 150").kind)

    def test_it_describes_itself_by_id(self):
        parsed = goals.parse_goal("work quest 3861")
        self.assertEqual("quest 3861", goals.describe(parsed))


# --- the constraint this must not break -----------------------------------


class PartyCohesionIsUntouched(unittest.TestCase):
    """A quest goal changes WHERE the traveller goes, never WHO travels.

    Followers given `new rpg` scattered the family over 937 yards; taking it
    off brought them within 3. The cost of getting this wrong is the healer
    600 yards away while the tank dies.
    """

    def test_followers_still_lose_the_wander_strategy(self):
        commands = goals.life_strategies(leads=False)
        self.assertIn("nc -new rpg", commands)
        self.assertIn("nc +follow", commands)
        self.assertNotIn(goals.LIFE_STRATEGY, commands)

    def test_the_drop_comes_before_the_follow(self):
        """No tick where both are set, or the follower drifts off again."""
        commands = goals.life_strategies(leads=False)
        self.assertLess(commands.index("nc -new rpg"), commands.index("nc +follow"))

    def test_only_the_leader_travels(self):
        self.assertIn(goals.LIFE_STRATEGY, goals.life_strategies(leads=True))

    # --- the aim has to carry the strategy that reads it (infra#2801) --------
    #
    # Found by the WoW session probing the live family in-game, which is the
    # only way this was ever going to surface: drive_quest=60 was set on Ugga,
    # Og and Grog, and NONE of the three had `new rpg`. rpgInfo is consumed
    # only by NewRpgDoQuestAction, reachable only through the `do quest status`
    # trigger node, registered only in NewRpgStrategy::InitTriggers. No
    # strategy, no trigger, nothing reads the aim - so the column was populated
    # and inert, which is this epic's signature failure.
    #
    # It was hidden because the dev-world proof used RANDOM bots, and
    # AiFactory.cpp gives random bots `new rpg` when enableNewRpgStrategy is
    # on. The family has it deliberately stripped, so dev validated the
    # mechanism on subjects carrying a prerequisite the family lacks.

    def test_an_aimed_follower_gets_the_strategy_that_reads_the_aim(self):
        commands = goals.life_strategies(leads=False, aimed=True)
        self.assertIn(goals.LIFE_STRATEGY, commands)
        self.assertNotIn(
            "nc -new rpg", commands, "stripping it is what made the aim unreadable"
        )

    def test_an_unaimed_follower_still_loses_it(self):
        """The 937-yard scatter is what happens to a follower carrying `new
        rpg` with NOWHERE to be. Aimed is the whole difference: dev measured a
        253-yard spread with three bots aimed at one quest."""
        commands = goals.life_strategies(leads=False, aimed=False)
        self.assertIn("nc -new rpg", commands)
        self.assertNotIn(goals.LIFE_STRATEGY, commands)

    def test_an_aimed_follower_keeps_following(self):
        """`follow` runs at 1.0 and every rpg action at 3.0-11.0, so it cannot
        pull them off the quest - it is the fallback for when the rpg action
        idles, which is what stops a finished traveller standing in a field."""
        self.assertIn("nc +follow", goals.life_strategies(leads=False, aimed=True))

    def test_the_default_is_the_safe_one(self):
        """A caller that has not been taught about aims must not accidentally
        hand out the wander strategy."""
        self.assertEqual(
            goals.life_strategies(leads=False),
            goals.life_strategies(leads=False, aimed=False),
        )

    def test_the_supervisor_passes_the_aim_through(self):
        """The rule is worthless if bridge never tells it who is aimed - the
        far side of the boundary, which is where this epic keeps breaking."""
        code = _function_code("_give_them_a_life")
        self.assertIn("aimed", code, "life_strategies has to be called with the aim")

    def test_the_drive_quest_action_names_no_traveller(self):
        """It carries a beneficiary, who is who the work is FOR - not who gets
        sent. A name chosen in goals.py would be a second opinion about
        leadership that could disagree with overseer_roster.lead."""
        fields = goals.DriveQuest.__dataclass_fields__
        self.assertEqual({"quest_id", "beneficiary"}, set(fields))


# --- the bridge seam, which the suite cannot import -----------------------


BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _bridge_source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _function(name: str):
    tree = ast.parse(_bridge_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _function_code(name: str) -> str:
    """The function's CODE, with its docstring and comments removed.

    `ast.dump` of a function includes its docstring as a string constant, so a
    test asserting a SQL fragment "is in" the dump can pass on a prose mention
    of it long after the code stopped doing it. That happened here: the
    leader-only aim assertion went on passing off the docstring after
    infra#2801 changed the query. Strip both, then assert.
    """
    node = _function(name)
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(ast.dump(stmt) for stmt in body)


class TheBridgeStopsThrowingQuestPlansAway(unittest.TestCase):
    """bridge.py imports discord and is not importable here by design, so this
    is structural - it reads the source rather than running it."""

    def test_both_gates_read_one_list_of_driven_kinds(self):
        """They were two identical ("level",) literals and 'quest' has to
        reach BOTH: persisting without _already_agreed means the council
        re-stages the same scene every hour against a goal it did persist."""
        source = _bridge_source()
        self.assertNotIn('not in ("level",)', source)
        for name in ("_already_agreed", "_persist_council_plan"):
            names = [n.id for n in ast.walk(_function(name)) if isinstance(n, ast.Name)]
            self.assertIn("DRIVEN_KINDS", names, name)

    def test_quest_is_a_driven_kind(self):
        """'dungeon' joined this set too (infra dungeon-decision gap, see
        tests/test_dungeon_goal.py) - this test only pins that 'quest' is
        still one of them, not that it is the only one."""
        tree = ast.parse(_bridge_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "DRIVEN_KINDS" for t in node.targets
            ):
                kinds = {e.value for e in node.value.elts}
                self.assertIn("quest", kinds)
                self.assertIn("level", kinds)
                return
        raise AssertionError("DRIVEN_KINDS not found in bridge.py")

    def test_the_migration_decision_is_delegated_to_the_pure_module(self):
        """So it is testable against a legacy table, which no fresh test
        database can ever be."""
        source = ast.dump(_function("_ensure_goal_store"))
        self.assertIn("goal_migrations", source)

    def test_the_aim_is_written_to_every_holder_of_the_quest(self):
        """infra#2801: the family quests together, so the aim is not the
        leader's alone.

        Asserted against the SQL text specifically rather than an ast.dump of
        the whole function - the previous version of this test checked a dump
        that includes docstrings, so it went on passing off a prose mention of
        `lead` = 1 after the code had stopped doing it. A test that can pass on
        its own comment is not a test.
        """
        code = _function_code("_aim_traveller")
        self.assertIn("drive_quest", code)
        self.assertIn("name IN", code, "the aim must target holders by name")
        self.assertNotIn(
            "`lead` = 1", code, "a leader-only aim is unreadable for a follower"
        )

    def test_a_non_holder_is_cleared_rather_than_left_aimed(self):
        """Aiming a character at a quest it does not hold idles it on the next
        tick, and an unaimed follower with `new rpg` free-roams - so the aim has
        to be exactly the holder set, both directions."""
        code = _function_code("_aim_traveller")
        self.assertIn("drive_quest = 0", code)
        self.assertIn("NOT IN", code)

    def test_the_aim_survives_a_column_that_has_not_shipped_yet(self):
        """overseer_roster's columns arrive with the worldserver image, and
        the bridge is a separate deployment with its own restarts. An
        unguarded write would take the whole supervision cycle with it."""
        handler = [
            h
            for n in ast.walk(_function("_aim_traveller"))
            if isinstance(n, ast.Try)
            for h in n.handlers
        ]
        self.assertEqual(1, len(handler))
        numbers = [n.value for n in ast.walk(handler[0]) if isinstance(n, ast.Constant)]
        self.assertIn(1054, numbers, "no ER_BAD_FIELD_ERROR guard")
        self.assertTrue(
            any(isinstance(n, ast.Raise) for n in ast.walk(handler[0])),
            "any other OperationalError must still escape",
        )

    def test_the_quest_choice_goes_through_questbook(self):
        """Rather than a second, quieter answer to a question questbook has
        already answered properly."""
        source = ast.dump(_function("_choose_drive_quest"))
        self.assertIn("drive_target", source)

    def test_the_one_quest_query_is_derived_from_the_shared_one(self):
        """A hand-copied second copy of that twenty-column join would drift,
        and it would drift silently."""
        self.assertIn("_QUEST_ONE_SQL = _QUEST_SQL.replace(", _bridge_source())


class AnsweringAPleaActuallyAimsTheFamily(unittest.TestCase):
    """infra#2801: "Bork help Ugga" was a sentence with no mechanism.

    Observed in Evan's Discord at 14:35, 15:06 and 16:05 on 2026-08-24: Ugga
    says she needs one more Large Candle, all four agree to help her, and
    nothing happens. Hours apart, three times, verbatim. Meanwhile she sat at
    7 of 8 candles for quest 60 the whole time.

    The muster wrote a regroup command and a memory and stopped there, so the
    family said yes and then carried on with whatever they were already doing.
    Answering a plea has to point them at the thing that was asked for.
    """

    def test_the_muster_path_aims_the_family(self):
        code = _bridge_source()
        self.assertIn("_aim_after_muster", code, "the muster path has to reach an aim")
        self.assertIn(
            "_aim_for_plea", code, "and that aim has to be the plea-derived one"
        )

    def test_the_aim_is_chosen_from_what_the_caller_actually_needs(self):
        code = _function_code("_aim_for_plea")
        self.assertIn(
            "caller", code, "the quest has to come from the character who asked"
        )

    def test_only_a_quest_the_helpers_also_hold_is_chosen(self):
        """Aiming a helper at a quest it does not hold idles it on the next
        tick - the silent no-op this epic keeps producing. Quest sharing is
        what usually makes a shared candidate exist."""
        # the candidate search moved into _pick_plea_quest when _aim_for_plea
        # was split for the complexity cap; the property is unchanged.
        code = _function_code("_pick_plea_quest")
        self.assertIn("_holders_of", code)

    def test_an_unanswerable_plea_aims_nobody(self):
        """If nothing shared can be found, the family must not be aimed at a
        quest they cannot act on. Saying nothing beats a false promise."""
        # _function_code returns an ast dump, so match the AST form rather
        # than the source text.
        code = _function_code("_aim_for_plea")
        self.assertIn(
            "Return(value=Constant(value=0))",
            code,
            "there has to be a path that aims nobody",
        )
        self.assertGreaterEqual(
            code.count("Return(value=Constant(value=0))"),
            2,
            "no caller, no incomplete quest, and no shared candidate are all "
            "reasons to aim nobody rather than aim badly",
        )

    def test_the_quest_the_caller_named_beats_the_most_popular_one(self):
        """Ugga holds six incomplete quests. The most widely held is Bounty on
        Murlocs; the one she asked about is Kobold Candles. Picking by
        popularity would send the family to kill murlocs while she stood there
        still wanting a candle - help she did not ask for is not help."""
        chooser = _function_code("_pick_plea_quest")
        self.assertIn("about", chooser, "the plea text has to reach the choice")
        self.assertIn("_quest_titles", chooser, "matching by name needs titles")
        # A named match returns immediately; the popularity fallback can only
        # be reached by falling past it.
        self.assertIn("Return(value=Tuple", chooser)
        self.assertIn(
            "Constant(value=True)",
            chooser,
            "a named match must short-circuit the popularity path",
        )
        self.assertIn(
            "about",
            _function_code("_aim_for_plea"),
            "the plea text has to be threaded through",
        )


class AnyoneCanAskForHelp(unittest.TestCase):
    """The plea path must never know a character's name.

    Ugga is the case that exposed the bug - she asked three times in two hours
    and nothing happened - but she is an EXAMPLE, not a special case. Bork asks
    constantly and Grog turns up for him every time; whoever calls, the same
    machinery has to answer. A name in this code would work perfectly for the
    character it named and silently fail every other one, which is the kind of
    bug that hides for months because the demo always passes.
    """

    FAMILY = ("Ugga", "Grug", "Grog", "Bork", "Og")

    def _code_of(self, fn: str) -> str:
        return _function_code(fn)

    def test_no_character_name_appears_in_the_plea_aim_code(self):
        for fn in (
            "_aim_for_plea",
            "_pick_plea_quest",
            "_holders_of",
            "_quest_titles",
            "_aim_traveller",
        ):
            code = self._code_of(fn)
            found = [n for n in self.FAMILY if n in code]
            self.assertEqual(
                [],
                found,
                "%s hard-codes %s; the caller must come from the plea" % (fn, found),
            )

    def test_the_caller_is_taken_from_the_plea_itself(self):
        code = _bridge_source()
        self.assertIn("plea.caller", code, "whoever spoke is who gets helped")

    def test_the_family_roster_comes_from_configuration_not_source(self):
        """_protected_guids reads OVERSEER_NOTABLE_NAMES, so adding a sixth
        character is a config change and not a code change."""
        code = _function_code("_protected_guids")
        self.assertIn("OVERSEER_NOTABLE_NAMES", code)
        found = [n for n in self.FAMILY if n in code]
        self.assertEqual([], found, "the roster is configured, not compiled in")


class TheLeaderIsNotAGateOnHelpingSomebodyElse(unittest.TestCase):
    """infra#2801, the half that was still missing after the aim was widened.

    mod-overseer was changed to aim every holder of a quest rather than the
    party leader alone, but the choice feeding it still intersected with what
    the LEADER held - so the widened aim was never handed a quest it could
    not already drive. The two halves have to agree or the C++ change is
    inert, which is this project's most repeated failure.

    The numbers below are the live world at 2026-08-24 23:07, read off
    character_queststatus: Ugga, Og and Grog all held quest 60; Grug, the
    leader, held five quests and none of them was 60.
    """

    HELD = {
        "Grug": frozenset({26, 62, 176, 239, 5261}),  # the leader: NOT 60
        "Ugga": frozenset({60, 84, 176, 239}),
        "Og": frozenset({60, 176, 239}),
        "Grog": frozenset({60, 84}),
        "Bork": frozenset({84, 176}),
    }

    def test_a_quest_the_leader_does_not_hold_is_still_driveable(self):
        """The exact live wedge: three of them are carrying quest 60 and the
        one who is not happens to be the leader."""
        self.assertIn(
            60,
            questbook.aimable(self.HELD, "Ugga", "Grug"),
            "quest 60 was held by Ugga, Og and Grog - it was always driveable",
        )

    def test_the_beneficiary_still_has_to_hold_it(self):
        """Not a relaxation of both halves. A quest Ugga does not hold cannot
        be observed for progress, so it must never be chosen for her."""
        self.assertNotIn(
            5261,
            questbook.aimable(self.HELD, "Ugga", "Grug"),
            "only Grug holds 5261; aiming it at Ugga could never be observed",
        )

    def test_with_no_beneficiary_the_leader_is_the_fallback(self):
        """A council that named nobody still has to be able to travel."""
        self.assertEqual(self.HELD["Grug"], questbook.aimable(self.HELD, "", "Grug"))

    def test_the_old_intersection_would_have_chosen_nothing(self):
        """Pins the bug itself, so a future refactor that reinstates the
        intersection fails here rather than going quiet in production for
        another three hours."""
        old = self.HELD["Grug"] & self.HELD["Ugga"]
        self.assertEqual(frozenset({176, 239}), old)
        self.assertNotIn(60, old, "this is why chosen=0 every hour")

    def test_drive_target_picks_it_once_the_candidates_are_right(self):
        """End of the chain: the widened set has to survive drive_target and
        come out as a real quest id, not just be a bigger set."""
        # furthest_behind is a derived property, not a field; the
        # beneficiary is passed explicitly so it is never consulted.
        ledger = questbook.Ledger(plans={"Ugga": ()}, behind={"Ugga": ()})
        chosen = questbook.drive_target(
            ledger,
            held_by_traveller=questbook.aimable(self.HELD, "Ugga", "Grug"),
            wanted=60,
            beneficiary="Ugga",
        )
        self.assertEqual(60, chosen, "the council named 60 and Ugga holds it")


class TheChoiceFeedingTheAimDoesNotGateOnTheLeader(unittest.TestCase):
    """A source-level guard on bridge, which the tests cannot import."""

    def test_the_chooser_uses_the_shared_rule(self):
        code = _function_code("_choose_drive_quest")
        self.assertIn(
            "aimable", code, "the candidate set has to come from questbook.aimable"
        )

    def test_the_chooser_no_longer_intersects_with_the_leader(self):
        """The literal `&` against the leader's holdings is the bug."""
        code = _function_code("_choose_drive_quest")
        self.assertNotIn(
            "BitAnd",
            code,
            "intersecting the candidates with anything is what "
            "emptied the set; aimable owns this rule now",
        )


if __name__ == "__main__":
    unittest.main()

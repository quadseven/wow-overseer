"""The council's dungeon decision has to survive into something that moves.

Mirrors tests/test_quest_goal.py's shape and reasoning almost exactly - a
dungeon goal is the same class of problem a quest goal was (infra#2597's
"council decided, and the family stood still"), fixed the same way: a
migration to admit the kind, a lease-renewed drive action rather than a
one-shot strategy, and a bridge that persists and executes it.
"""

import ast
import pathlib
import unittest

import council
import goals

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _m(name, level, **over):
    return council.Member(
        name=name,
        level=level,
        class_name=over.pop("class_name", "Warrior"),
        gold=over.pop("gold", 999999),
        trades=over.pop("trades", 5),
    )


def _bridge_source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _function(name: str):
    tree = ast.parse(_bridge_source())
    for node in ast.walk(tree):
        # AsyncFunctionDef too: _apply_goal_action and its siblings are
        # `async def` methods on the Discord client class.
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _function_code(name: str) -> str:
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


# --- the schema migration ---------------------------------------------------


LEGACY_KIND = "enum('level','skill','quest')"


class TheEnumMigrationGeneralizedForDungeon(unittest.TestCase):
    """goal_migrations was rewritten to read GOAL_KINDS instead of naming
    'quest' - these pin that it still does its one job for the new kind."""

    def test_a_table_that_predates_dungeon_is_told_to_gain_it(self):
        statements = goals.goal_migrations(LEGACY_KIND, has_quest_id=True)
        self.assertEqual(1, len(statements), statements)
        self.assertIn("MODIFY kind", statements[0])
        self.assertIn("'dungeon'", statements[0])

    def test_every_earlier_kind_survives_the_modify(self):
        statement = goals.goal_migrations(LEGACY_KIND, has_quest_id=True)[0]
        for kind in ("level", "skill", "quest", "dungeon"):
            self.assertIn("'%s'" % kind, statement, kind)

    def test_idempotent_against_a_table_that_already_has_it(self):
        self.assertEqual(
            [], goals.goal_migrations(goals.KIND_COLUMN.lower(), has_quest_id=True)
        )

    def test_dungeon_is_in_the_one_list_of_kinds(self):
        self.assertIn("dungeon", goals.GOAL_KINDS)
        self.assertIn("'dungeon'", goals.KIND_COLUMN)


# --- telling two dungeon goals apart -----------------------------------------


class TellingTwoDungeonGoalsApart(unittest.TestCase):
    """Every dungeon goal shares the same target (DUNGEON_RUNS_WANTED), so
    the keyword is the identity - the same shape as a quest's id."""

    def test_the_keyword_is_the_identity_not_the_target(self):
        active = [{"kind": "dungeon", "target": 25, "skill_name": "scarlet-library"}]
        self.assertTrue(
            goals.already_working("dungeon", 25, active, keyword="scarlet-library")
        )
        self.assertFalse(
            goals.already_working("dungeon", 25, active, keyword="scarlet-armory")
        )

    def test_the_bare_dungeon_job_is_its_own_identity(self):
        active = [{"kind": "dungeon", "target": 25, "skill_name": ""}]
        self.assertTrue(goals.already_working("dungeon", 25, active, keyword=""))
        self.assertFalse(
            goals.already_working("dungeon", 25, active, keyword="scarlet")
        )

    def test_other_kinds_are_unaffected(self):
        active = [{"kind": "level", "target": 20}]
        self.assertTrue(goals.already_working("level", 20, active))


# --- supervising a dungeon goal ----------------------------------------------


def _row(**kw):
    row = dict(
        id=9,
        character_name="Bork",
        kind="dungeon",
        target=council.DUNGEON_RUNS_WANTED,
        skill_name="scarlet-cathedral",
        status="active",
        last_report=None,
    )
    row.update(kw)
    return row


class SupervisingADungeonGoal(unittest.TestCase):
    def test_first_sighting_drives_the_family_rather_than_grinding(self):
        actions = goals.reconcile(_row(), 0)
        drives = [a for a in actions if isinstance(a, goals.DriveDungeon)]
        self.assertEqual(1, len(drives))
        self.assertEqual("scarlet-cathedral", drives[0].keyword)
        self.assertEqual(25, drives[0].wanted)
        self.assertEqual("Bork", drives[0].beneficiary)
        self.assertFalse([a for a in actions if isinstance(a, goals.StrategyCommand)])

    def test_a_dungeon_goal_never_issues_a_strategy_command(self):
        for done, report in ((3, None), (3, "3/0"), (3, "3/4"), (2, "3/0")):
            actions = goals.reconcile(_row(last_report=report), done)
            self.assertFalse(
                [a for a in actions if isinstance(a, goals.StrategyCommand)],
                (done, report, actions),
            )

    def test_the_job_is_renewed_on_a_clock_even_while_progress_is_good(self):
        """A relog or a bag-pressure evacuation can knock the job off the
        roster without the campaign having failed - re-assert on a cadence,
        the same argument _reconcile_quest already made for its aim."""
        cycles = goals.REASSERT_AFTER_CYCLES
        row = _row(last_report="5/%d" % (cycles - 1))
        actions = goals.reconcile(row, 6)
        self.assertTrue([a for a in actions if isinstance(a, goals.DriveDungeon)])
        recorded = [a for a in actions if isinstance(a, goals.RecordProgress)][0]
        self.assertEqual(0, recorded.stalls, "the lease counter did not reset")

    def test_a_quiet_cycle_only_advances_the_lease_counter(self):
        actions = goals.reconcile(_row(last_report="5/0"), 5)
        self.assertEqual(1, len(actions), actions)
        self.assertEqual(1, actions[0].stalls)

    def test_a_completed_run_is_reported(self):
        actions = goals.reconcile(_row(last_report="5/0"), 6)
        texts = [a.text for a in actions if isinstance(a, goals.Report)]
        self.assertEqual(1, len(texts))
        self.assertIn("6 of 25", texts[0])

    def test_reaching_the_wanted_count_completes_the_goal(self):
        actions = goals.reconcile(_row(last_report="24/0"), 25)
        self.assertTrue([a for a in actions if isinstance(a, goals.MarkComplete)])

    def test_completion_names_the_campaign_not_one_character(self):
        text = goals.completion_text(_row(), 25)
        self.assertIn("family finished its campaign", text)

    def test_completed_goals_stay_silent(self):
        self.assertEqual([], goals.reconcile(_row(status="completed"), 25))

    def test_an_unobservable_dungeon_says_nothing(self):
        self.assertEqual([], goals.reconcile(_row(), None))

    def test_a_bare_dungeon_goal_drives_the_default_job(self):
        actions = goals.reconcile(_row(skill_name=""), 0)
        drives = [a for a in actions if isinstance(a, goals.DriveDungeon)]
        self.assertEqual("", drives[0].keyword)


# --- the council's plan reaching the goal store ------------------------------


class TheKeywordSurvivesTheCouncil(unittest.TestCase):
    def test_a_dungeon_proposal_carries_the_keyword(self):
        members = [_m(n, 41) for n in ("Grug", "Ugga", "Grog", "Bork", "Og")]
        rows = [
            {"name": n, "level": 41} for n in ("Grug", "Ugga", "Grog", "Bork", "Og")
        ]
        proposal = council._dungeon_proposal(members, rows, [])
        self.assertIsNotNone(proposal)
        self.assertEqual("scarlet-cathedral", proposal.keyword)

    def test_the_keyword_reaches_the_agreed_plan(self):
        members = [_m(n, 41) for n in ("Grug", "Ugga", "Grog", "Bork", "Og")]
        rows = [
            {"name": n, "level": 41} for n in ("Grug", "Ugga", "Grog", "Bork", "Og")
        ]
        held = council.hold(members, history=[], level_rows=rows, cards=[])
        self.assertIsNotNone(held.plan)
        self.assertEqual("dungeon", held.plan.kind)
        self.assertEqual("scarlet-cathedral", held.plan.keyword)


# --- bridge.py wiring (AST-only: bridge.py needs discord/pymysql) -----------


class TheBridgeCanActuallyDriveADungeonGoal(unittest.TestCase):
    def test_dungeon_is_a_driven_kind(self):
        tree = ast.parse(_bridge_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "DRIVEN_KINDS" for t in node.targets
            ):
                kinds = {e.value for e in node.value.elts}
                self.assertEqual({"level", "quest", "dungeon"}, kinds)
                return
        raise AssertionError("DRIVEN_KINDS not found in bridge.py")

    def test_the_keyword_is_persisted_as_skill_name(self):
        """There is no dedicated column for it - see _persist_council_plan's
        own comment on why skill_name is where it lives."""
        code = _function_code("_persist_council_plan")
        self.assertIn("skill_name", code)
        self.assertIn("keyword", code)

    def test_apply_goal_action_knows_drivedungeon(self):
        code = _function_code("_apply_goal_action")
        self.assertIn("DriveDungeon", code)

    def test_the_drive_is_gated_on_bag_pressure(self):
        """mod-overseer's own bag-pressure evacuation (#423/#424/#430) will
        fail a run for a family that cannot loot - the execution pass must
        check before sending them in, not after."""
        code = _function_code("_drive_dungeon")
        self.assertIn("family_town_run_needed", code)
        self.assertIn("_fetch_free_slots", code)

    def test_the_drive_writes_the_whole_enabled_family(self):
        """A dungeon run needs everybody in the instance, unlike a quest aim
        which names one traveller - _fetch_enabled_names is the same set
        _set_job's own job-schedule fan-out uses."""
        code = _function_code("_drive_dungeon")
        self.assertIn("_fetch_enabled_names", code)
        self.assertIn("dungeon_runs_wanted", code)


# --- an unknown keyword never reaches the roster (#86) ----------------------


MODULE = (
    pathlib.Path(__file__).resolve().parents[1] / "mod-overseer/src/mod_overseer.cpp"
)


def _load_drive_dungeon(inserted: list, updated: list, warnings: list):
    """bridge._drive_dungeon, executed for real against fakes.

    bridge.py itself cannot be imported here (discord/pymysql), so the one
    function is compiled out of its source and run with every name it reaches
    for supplied by the test. That makes this a behaviour test: it counts the
    writes that would have landed, rather than reading the code as text.
    """
    import contextlib
    import types

    import jobs

    node = _function("_drive_dungeon")
    source = ast.get_source_segment(_bridge_source(), node)

    class Cursor:
        rowcount = 1

        def execute(self, sql, args):
            updated.append(args)

    class Conn:
        def cursor(self):
            return contextlib.nullcontext(Cursor())

    class Log:
        def info(self, *a, **k):
            pass

        def warning(self, msg, *args):
            warnings.append(msg % args)

        def exception(self, *a, **k):
            pass

    namespace = {
        "jobs": jobs,
        "log": Log(),
        "_fetch_enabled_names": lambda: ["Grug", "Ugga", "Og"],
        "_fetch_free_slots": lambda names: {n: 40 for n in names},
        "bag_pressure": types.SimpleNamespace(
            family_town_run_needed=lambda slots: False
        ),
        "_insert_job": lambda name, mode, by: inserted.append((name, mode)),
        "_connect": lambda: contextlib.nullcontext(Conn()),
        "pymysql": types.SimpleNamespace(
            err=types.SimpleNamespace(MySQLError=Exception)
        ),
    }
    exec(compile(source, str(BRIDGE), "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace["_drive_dungeon"]


class AnUnknownKeywordNeverReachesTheRoster(unittest.TestCase):
    def _drive(self, keyword):
        inserted, updated, warnings = [], [], []
        result = _load_drive_dungeon(inserted, updated, warnings)(keyword, 25)
        return result, inserted, updated, warnings

    def test_an_unknown_keyword_writes_nothing_at_all(self):
        result, inserted, updated, _ = self._drive("ragefire")
        self.assertEqual((0, 0), result)
        self.assertEqual([], inserted, "a job was written for an unknown keyword")
        self.assertEqual(
            [], updated, "a campaign row was written for an unknown keyword"
        )

    def test_the_refusal_names_the_keyword_and_the_valid_ones(self):
        _, _, _, warnings = self._drive("ragefire")
        self.assertEqual(1, len(warnings), warnings)
        self.assertIn("dungeon:ragefire", warnings[0])
        for keyword in ("deadmines", "scarlet-cathedral", "stockades"):
            self.assertIn(keyword, warnings[0])

    def test_a_known_keyword_still_sends_the_whole_family(self):
        result, inserted, updated, warnings = self._drive("scarlet-cathedral")
        self.assertEqual((3, 3), result)
        self.assertEqual(
            [
                ("Grug", "dungeon:scarlet-cathedral"),
                ("Ugga", "dungeon:scarlet-cathedral"),
                ("Og", "dungeon:scarlet-cathedral"),
            ],
            inserted,
        )
        self.assertEqual(3, len(updated))
        self.assertEqual([], warnings)

    def test_the_bare_dungeon_job_is_still_accepted(self):
        result, inserted, _, _ = self._drive("")
        self.assertEqual((3, 3), result)
        self.assertEqual({"dungeon"}, {mode for _, mode in inserted})


class TheKeywordVocabularyIsTheCoordinators(unittest.TestCase):
    def test_portal_keywords_match_mod_overseers_portal_table(self):
        import re

        import jobs

        text = MODULE.read_text(encoding="utf-8")
        start = text.index("DungeonPortals()\n")
        body = text[start : text.index("};", start)]
        in_cpp = set(re.findall(r'^\s*\{"([a-z-]+)",', body, re.M))
        self.assertTrue(in_cpp, "no portal rows parsed from mod_overseer.cpp")
        self.assertEqual(in_cpp, set(jobs.PORTAL_KEYWORDS))

    def test_every_chat_dungeon_is_a_portal_keyword(self):
        import jobs

        self.assertLessEqual(set(jobs.DUNGEONS.values()), jobs.PORTAL_KEYWORDS)

    def test_dungeon_job(self):
        import jobs

        self.assertEqual("dungeon", jobs.dungeon_job(""))
        self.assertEqual("dungeon:scarlet", jobs.dungeon_job("scarlet"))
        self.assertIsNone(jobs.dungeon_job("ragefire"))
        self.assertIsNone(jobs.dungeon_job("Deadmines"))


if __name__ == "__main__":
    unittest.main()

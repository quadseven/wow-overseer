"""While a character is on an errand, the module owns its task, not this loop.

infra#3423. The life loop writes a full strategy set per character on the
roster cadence and has no idea an errand is in flight, so it grants the party
leader `nc +grind` mid-escort - a strategy mod-overseer has deliberately stood
down for the trip. The module catches it and takes it straight back off:

    'Og' had grind put back on its non-combat engine while it was travelling
    to 'at:1:-705,-2045,66.45' - taken off again. Something is granting
    strategies to a character that is mid-escort

Twice in three hours on the live realm, once on a dungeon staging errand and
once on a follower's `repair` errand.

READ THE SCOPE HONESTLY, because the first write-up of this ticket did not.
The damage is BOUNDED: the module re-asserts the stand-down on every travel
poll rather than once at the start, so a second writer costs a few seconds of
the wrong strategy rather than the errand. This was initially reported as the
cause of a dungeon campaign stuck at 0 of 100, and it is not. The module runs
that exact experiment on its own correction ladder and prints the answer:

    Correction 1 of 3: re-asserting the escort's own strategy set - nothing
    had come back on, so this is not what is holding it

The runs were failing because the leader was pinned by the module's footing
check on broken terrain, and because a run opens with no distance gate at all
(quadseven/mod-overseer#305). The collision below is real, observed, and worth
closing on its own merits. It is not why the campaign was stuck.

WHY THIS IS A CONTRACT TEST OVER THE C++ AND NOT A LIST OF NAMES. The set of
strategies an escort stands down lives in mod_overseer.cpp, in another
repository, on its own release cadence. A copy of it here would drift, and it
would drift silently - the symptom is a character that walks slightly worse,
which looks like pathfinding. So the divert list is READ from the vendored
module source and the assertion is made against whatever it says today. If the
module ever adds a diverter that this loop grants, this test fails at the
submodule pin bump rather than at 2am on the realm.

infra#2929 moved mod-overseer to its own repository and kept a submodule at
the same path precisely so this suite's C++-as-text contract tests keep reading
real content; check.python-units.yml carries `submodules: true` for this
directory alone. tests/test_travel_npc.py established the pattern.
"""

import ast
import pathlib
import re
import unittest

import goals

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _divert_strategies() -> frozenset:
    """The names an escort stands down, read out of the module source.

    Parsed rather than copied. The initializer is a plain brace list of string
    literals, so the strings between the braces ARE the set.
    """
    src = MODULE.read_text(encoding="utf-8")
    start = src.index("ESCORT_DIVERT_STRATEGIES[] = {")
    end = src.index("};", start)
    return frozenset(re.findall(r'"([^"]+)"', src[start:end]))


def _granted(commands) -> frozenset:
    """The strategy NAMES a command list turns ON.

    A command is `<engine> <sign><name>`, as in `nc +grind` or `co +flee`.
    Only `+` counts: `nc -new rpg` takes a strategy off, and taking one off is
    what the module itself does, never a collision.

    EXACT NAMES, NEVER SUBSTRINGS, and the divert list is why. It contains
    `rpg`, and LIFE_STRATEGY is `new rpg` - a different strategy that the
    module deliberately leaves on, because it is how the errand travels at
    all. A substring test would report the fix as broken and, worse, invite
    somebody to "fix" it by taking the traveller's legs away, which is
    infra#3409 exactly.
    """
    names = set()
    for command in commands:
        _, _, rest = command.partition(" ")
        if rest.startswith("+"):
            names.add(rest[1:])
    return frozenset(names)


class TheDivertListIsReadNotRemembered(unittest.TestCase):
    def test_the_module_source_is_actually_vendored(self):
        """A missing submodule would make every assertion below vacuous."""
        self.assertTrue(
            MODULE.exists(),
            "mod-overseer is not checked out at %s - run "
            "`git submodule update --init` from the repository root. CI does "
            "this for exactly this directory (check.python-units.yml)" % MODULE,
        )

    def test_the_list_parses_to_something_recognisable(self):
        """If the parse silently returned nothing, everything passes and
        nothing is checked. Pin the shape and the one name this bug is about."""
        divert = _divert_strategies()
        self.assertIn("grind", divert)
        self.assertIn("gather", divert)
        self.assertGreaterEqual(len(divert), 8, divert)

    def test_new_rpg_is_not_a_diverter(self):
        """The module leaves it on deliberately - it is how an escort moves.
        If this ever flips, withholding it becomes correct and the whole shape
        of life_strategies has to be revisited rather than quietly patched."""
        self.assertNotIn("new rpg", _divert_strategies())


class ATravellerIsGrantedNoDiverter(unittest.TestCase):
    """The invariant, across every branch of life_strategies."""

    def test_no_branch_grants_a_diverter_while_travelling(self):
        divert = _divert_strategies()
        for leads in (True, False):
            for aimed in (True, False):
                with self.subTest(leads=leads, aimed=aimed):
                    granted = _granted(
                        goals.life_strategies(leads=leads, aimed=aimed, travelling=True)
                    )
                    self.assertEqual(
                        frozenset(),
                        granted & divert,
                        "the module stands these down for the trip and this "
                        "loop hands them straight back",
                    )

    def test_the_leader_is_covered_and_not_only_the_followers(self):
        """The leader is the character this was measured on, and he is the
        ONLY one the old code granted a diverter to - the follower branches
        never did. A fix that covered followers alone would test green and
        change nothing on the realm."""
        self.assertIn(
            "grind",
            _granted(goals.life_strategies(leads=True, aimed=True)),
            "the leader branch is supposed to grant the task strategy when "
            "there is no errand - if it no longer does, this test is watching "
            "the wrong thing",
        )
        self.assertNotIn(
            "grind",
            _granted(goals.life_strategies(leads=True, aimed=True, travelling=True)),
        )


class TheTravellerKeepsItsLegsAndItsLife(unittest.TestCase):
    """Withholding the whole set would be a worse bug than the one fixed.

    The module restores ONLY what it stood down, and it never stands down -
    and never grants - `new rpg`, `follow` or `flee`. Those exist solely
    because this loop grants them, and ResetStrategies takes them away on
    every relog. A character that relogged mid-errand under a
    withhold-everything scheme would come back with no strategy at all and
    nobody to give it one.
    """

    def test_the_travelling_leader_still_gets_the_life_strategy(self):
        commands = goals.life_strategies(leads=True, travelling=True)
        self.assertIn(goals.LIFE_STRATEGY, commands)

    def test_the_travelling_leader_still_gets_flee(self):
        commands = goals.life_strategies(leads=True, travelling=True)
        self.assertIn(goals.FLEE_STRATEGY, commands)

    def test_a_travelling_follower_still_follows(self):
        commands = goals.life_strategies(leads=False, aimed=True, travelling=True)
        self.assertIn("nc +follow", commands)
        self.assertIn(goals.LIFE_STRATEGY, commands)

    def test_the_task_strategy_is_the_only_thing_withheld(self):
        """Exactly one command comes off the leader's set, and it is the one
        the module names. Asserted as a set difference so an accidental extra
        removal cannot hide behind a passing membership check."""
        before = goals.life_strategies(leads=True)
        during = goals.life_strategies(leads=True, travelling=True)
        self.assertEqual(
            [goals.strategy_for({"kind": "level"})],
            [c for c in before if c not in during],
        )
        self.assertEqual([], [c for c in during if c not in before])


class TheDefaultIsTheOldBehaviour(unittest.TestCase):
    def test_not_passing_travelling_changes_nothing(self):
        """Every existing caller and test omits it. A default that withheld
        the task strategy would stop the family levelling at all."""
        for leads in (True, False):
            for aimed in (True, False):
                with self.subTest(leads=leads, aimed=aimed):
                    self.assertEqual(
                        goals.life_strategies(leads=leads, aimed=aimed),
                        goals.life_strategies(
                            leads=leads, aimed=aimed, travelling=False
                        ),
                    )


# --- the bridge seam, which the suite cannot import -----------------------


def _function(name: str):
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _function_code(name: str) -> str:
    """The function's CODE, docstring stripped, in the pattern
    test_quest_goal.py established - so an assertion cannot pass off a prose
    mention in a docstring long after the code stopped doing it."""
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


class TheSupervisorAsksTheQuestionAndPassesTheAnswer(unittest.TestCase):
    """The rule is worthless if bridge never tells it who is walking - the far
    side of the boundary, which is where this epic keeps breaking."""

    def test_the_life_pass_reads_who_is_travelling(self):
        self.assertIn("_travelling_names", _function_code("_give_them_a_life"))

    def test_the_life_pass_passes_it_through(self):
        code = _function_code("_give_them_a_life")
        self.assertIn(
            "travelling", code, "life_strategies has to be called with the errand"
        )

    def test_it_is_decided_per_character_and_not_a_literal(self):
        """Checking the name alone let a mutant through on the sibling
        assertion in test_protect.py - `travelling=False` would satisfy a
        substring check and restore the bug in full."""
        call = next(
            n
            for n in ast.walk(_function("_give_them_a_life"))
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "life_strategies"
        )
        travelling = next(k.value for k in call.keywords if k.arg == "travelling")
        self.assertIsInstance(
            travelling,
            ast.Compare,
            "travelling= is a constant, so every character is treated the same",
        )

    def test_it_is_asked_once_for_the_whole_pass(self):
        """Asking per character would let the set change underneath one sweep,
        which is the reason `head` and `aimed` are hoisted too."""
        loop = next(
            n
            for n in ast.walk(_function("_give_them_a_life"))
            if isinstance(n, ast.For)
        )
        called_in_loop = {
            n.func.id
            for n in ast.walk(loop)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertNotIn("_travelling_names", called_in_loop)

    def test_an_empty_errand_does_not_count(self):
        """The column is empty far more often than it is set. Treating '' as
        an errand would withhold the task strategy from the whole family
        permanently, which is the family standing still - the exact cost
        _give_them_a_life exists to prevent."""
        self.assertRegex(_function_code("_travelling_names"), r"travel_npc\s*<>\s*''")

    def test_a_missing_column_degrades_to_the_old_behaviour(self):
        """The bridge deploys separately from the worldserver that applies the
        module's SQL, so the column can legitimately be absent. Granting the
        task strategy as before is the safe direction, and the warning is what
        stops it being silent."""
        self.assertIn("1054", _function_code("_travelling_names"))
        # Structural rather than a text match: the docstring says "return an
        # empty set" in prose, and _function_code strips the docstring for
        # exactly that reason, so the dumped tree spells the call rather than
        # the source. Assert the shape instead.
        returns_empty_set = any(
            isinstance(n, ast.Return)
            and isinstance(n.value, ast.Call)
            and getattr(n.value.func, "id", None) == "set"
            and not n.value.args
            for n in ast.walk(_function("_travelling_names"))
        )
        self.assertTrue(
            returns_empty_set,
            "a missing column has to degrade to granting the task strategy, "
            "not to an exception that kills the whole life pass",
        )


class NoProductionCallerCanForgetTheErrand(unittest.TestCase):
    """`travelling` defaults to False, and the default is the SAFE one.

    That default is deliberate and has to stay. The alternative reading of
    "safe" - withholding the task strategy unless told otherwise - would stop
    the whole family levelling the moment a caller forgot the argument, which
    is a far larger failure than the bounded collision this fixes. It also
    matches how `aimed` is treated one line up: test_quest_goal.py pins that
    default as a safety property for the same reason.

    But a default that is safe is not the same as a default nobody should
    land on by accident, and that is the real exposure a reviewer named on
    this change: a future caller that omits the argument silently gets the
    pre-fix behaviour. Adding the argument to a few sibling test cases does
    not close that, because the caller at risk is one nobody has written yet.
    Guarding EVERY call site does.
    """

    def _life_strategies_calls(self):
        """Every call of life_strategies in the shipped modules.

        Test modules are deliberately not scanned: they call it with two
        arguments on purpose, to pin what the resting default does.
        """
        package = pathlib.Path(__file__).resolve().parents[1]
        for path in sorted(package.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(
                    node.func, "id", None
                )
                if name == "life_strategies":
                    yield path.name, node.lineno, {k.arg for k in node.keywords}

    def test_there_is_at_least_one_call_to_guard(self):
        """If the scan silently found nothing, the guard below passes while
        watching an empty set - the same vacuum the vendored-source check
        above exists to prevent."""
        self.assertTrue(list(self._life_strategies_calls()))

    def test_every_production_call_passes_the_errand(self):
        for module, lineno, kwargs in self._life_strategies_calls():
            with self.subTest(module=module, lineno=lineno):
                self.assertIn(
                    "travelling",
                    kwargs,
                    "%s:%d calls life_strategies without `travelling`, so a "
                    "character mid-errand is handed the task strategy again - "
                    "the bug infra#3423 fixed, restored silently" % (module, lineno),
                )


if __name__ == "__main__":
    unittest.main()

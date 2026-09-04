"""A character with no group and no aim must not be able to go looking for a
fight, no matter why it ended up somewhere dangerous.

infra#2925/#2891. Watched live: the family wiped as a group in Burning
Steppes (level 45-55) against a named elite. Minutes later, with no group, no
quest, and no travel aim pointing him anywhere, Grug revived and walked alone
into a `??`-conned dragonkin and died again. His combat engine still carried
`pull`, `tank` and `tank assist` - correct for a protection warrior WHILE
GROUPED AND TANKING CONTENT THE GROUP CHOSE, and clearly wrong once neither
was true any more.

The C++ here is compiled only on a push to `main`, never on a PR, so these are
contract tests over the source text, in the pattern test_schema_degrade.py
established.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"


def _source() -> str:
    return MODULE.read_text(encoding="utf-8")


def _function(signature: str) -> str:
    """The whole of a member function, braces balanced."""
    src = _source()
    start = src.index(signature)
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("%s has no closing brace" % signature)


def _code(text: str) -> str:
    """The same text with // comments stripped."""
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _guard() -> str:
    return _function("void DriveEngagementSafety()")


class TheGateReadsTheSameAimsAsTheOtherDrives(unittest.TestCase):
    """A late-added column must degrade this drive the same way it degrades
    DriveQuests and DriveTravel (infra#2846) - never take the whole guard off
    the air."""

    def test_it_uses_the_same_guarded_quest_loader(self):
        # `LoadQuestAims(` rather than `LoadQuestAims()`: the loader takes an out-parameter since mod-overseer#192, which keeps the last good aim across a transient read failure.
        # What this pins is that the gate reads through the SHARED loader
        # rather than issuing its own query, and that is unchanged.
        self.assertIn("LoadQuestAims(", _code(_guard()))

    def test_it_uses_the_same_guarded_travel_loader(self):
        # The travel column's reader lives on the TravelAimBook now
        # (`TravelAimBook::Load()`, mod_overseer.cpp), and DriveEngagementSafety
        # reads it through the same `_travelAims.Load()` that DriveQuests and
        # DriveTravel use. A free LoadTravelAims() no longer exists.
        self.assertIn("_travelAims.Load()", _code(_guard()))

    def test_it_does_not_select_either_aim_column_itself(self):
        code = _code(_guard())
        self.assertNotIn("drive_quest", code)
        self.assertNotIn("travel_npc", code)

    def test_the_roster_query_is_guarded_like_every_other_roster_wide_drive(self):
        code = _code(_guard())
        self.assertIn("if (!result)", code)
        self.assertIn("return;", code)


class OnlyUnaccompaniedAndUnaimedIsGated(unittest.TestCase):
    """Do not weaken pull/tank for a character that IS grouped and tanking on
    purpose - the gate is about alone and aimless, not about tanking."""

    def test_aimed_characters_are_skipped(self):
        code = _code(_guard())
        self.assertIn("if (aimed || accompanied)", code)
        self.assertIn("continue;", code)

    def test_accompanied_means_a_live_groupmate_not_a_bare_group_pointer(self):
        """KeepRosterGrouped keeps the family in one party long after a wipe
        scatters who is actually online - a Group* alone would not have
        caught Grug's death."""
        code = _code(_guard())
        self.assertIn("GetFirstMember()", code)
        self.assertIn("IsInWorld()", code)
        self.assertIn("member != bot", code)


class OnlyInitiationStrategiesAreStripped(unittest.TestCase):
    """tank/tank assist must survive this guard - stripping them would gate a
    REACTION (holding aggro once drawn in), not an initiation."""

    def test_the_gated_list_is_exactly_pull_aoe_grind(self):
        code = _code(_guard())
        self.assertIn('{"pull", "aoe", "grind"}', code)

    def test_tank_strategies_are_never_named_for_stripping(self):
        code = _code(_guard())
        self.assertNotIn('"tank"', code)
        self.assertNotIn('"tank assist"', code)

    def test_the_strip_uses_the_minus_sign_on_the_combat_engine(self):
        code = _code(_guard())
        self.assertIn("BOT_STATE_COMBAT", code)
        self.assertIn("change += '-';", code)

    def test_only_strategies_actually_present_are_included(self):
        """Built from StrategyPresent, the same reader ResolveStrategyChecks
        already uses - not an unconditional strip every poll."""
        code = _code(_guard())
        self.assertIn("StrategyPresent(botAI, StrategyItem{strategy, true})", code)


class TheBackstopIsAdditiveNotReliedOn(unittest.TestCase):
    """`co +flee` was applied to Grog and he still died - it must not be the
    only mitigation, and the guard must say so."""

    def test_flee_is_only_added_not_relied_on_as_the_fix(self):
        code = _code(_guard())
        self.assertIn('"+flee"', code)

    def test_the_backstop_only_fires_once_already_unaccompanied_and_unaimed(self):
        """The victim/level check must be reachable only after the
        aimed-or-accompanied early return, not as an independent path."""
        guard = _guard()
        gate = guard.index("if (aimed || accompanied)")
        backstop = guard.index("GetVictim()")
        self.assertLess(gate, backstop)

    def test_the_backstop_does_not_touch_a_bot_that_is_not_in_combat(self):
        code = _code(_guard())
        self.assertIn("if (!bot->IsInCombat())", code)

    def test_flee_effectiveness_is_not_overclaimed(self):
        src = _source()
        start = src.index("void DriveEngagementSafety()")
        # search the preceding block comment too, not just the function body
        comment_start = src.rindex("// ----", 0, start)
        self.assertIn("Grog", src[comment_start:start])


class TheConColorThresholdIsTheGamesOwnSignal(unittest.TestCase):
    """Point 1 of the brief: use the level-differential signal the client
    already computes for `??`, not an invented number."""

    def test_the_threshold_constant_exists(self):
        self.assertIn("constexpr uint32 CON_COLOR_UNKNOWN_LEVEL_DIFF", _source())

    def test_the_guard_uses_the_named_constant_not_a_bare_literal(self):
        code = _code(_guard())
        self.assertIn("CON_COLOR_UNKNOWN_LEVEL_DIFF", code)
        self.assertNotRegex(code, r"victimLevel\s*[<>=]+\s*botLevel\s*\+\s*\d")


class ThePollIsRegisteredAndSeparateFromTheTravellerArchitecture(unittest.TestCase):
    """This is a target-selection/engagement guard, orthogonal to who
    travels - it must not touch TravelHoldsTheWheel, DriveQuests' or
    DriveTravel's own bodies, or rpgInfo/master state."""

    def test_a_dedicated_timer_is_declared(self):
        self.assertIn("uint32 _engagementTimer = 0;", _source())

    def test_a_dedicated_poll_interval_is_declared(self):
        self.assertIn("constexpr uint32 ENGAGEMENT_POLL_MS", _source())

    def test_onupdate_calls_the_drive_on_its_own_timer(self):
        code = _code(_source())
        self.assertIn("_engagementTimer >= ENGAGEMENT_POLL_MS", code)
        self.assertIn("DriveEngagementSafety();", code)

    def test_the_guard_never_calls_the_travel_arbitration(self):
        code = _code(_guard())
        self.assertNotIn("TravelHoldsTheWheel", code)

    def test_the_guard_never_touches_rpginfo_or_master(self):
        code = _code(_guard())
        self.assertNotIn("rpgInfo", code)
        self.assertNotIn("SetMaster", code)

    def test_drivequests_and_drivetravel_bodies_are_unchanged_by_this_addition(self):
        """This is a text-shape check, not a full regression suite: the two
        functions this PR must not touch still open with the same guarded
        roster/aim reads test_schema_degrade.py already pins down."""
        quests = _code(_function("void DriveQuests()"))
        self.assertIn("TravelHoldsTheWheel(", quests)
        self.assertNotIn("DriveEngagementSafety", quests)
        travel = _code(_function("void DriveTravel()"))
        self.assertNotIn("DriveEngagementSafety", travel)


class TheGuardFailsClosedAndCheap(unittest.TestCase):
    """The worldserver segfaulted twice today (infra#2891). Nothing new here
    may be able to throw, block, or add a query per bot on a hot path."""

    def test_steerableai_is_used_not_a_bare_lookup(self):
        code = _code(_guard())
        self.assertIn("SteerableAI(bot)", code)
        self.assertIn("if (!botAI)", code)

    def test_no_query_runs_per_character(self):
        """Exactly the roster-list SELECT, once for the whole sweep - the
        aim loaders are each one query too, also once per sweep."""
        code = _code(_guard())
        self.assertEqual(1, code.count("CharacterDatabase.Query"))


if __name__ == "__main__":
    unittest.main()

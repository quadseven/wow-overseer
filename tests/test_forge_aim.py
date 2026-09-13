"""The forge walk: standing a smelter inside a Forge's spell focus.

infra#3748, part of infra#3731. infra#3738 found that Engineering stops dead at
skill 31 because 12 of its 18 brackets consume a smelted bar and nothing in this
system smelts. infra#3747 proved why, against the running worldserver's own
`Spell.dbc`: every smelt spell carries `RequiresSpellFocus = 3`, which
`SpellFocusObject.dbc` resolves to Forge, and `DriveCraft` casts in place. This
suite covers the walk that closes it.

WHAT THIS PINS THAT A LIVE DRY RUN CANNOT. The failures here are all silent
ones, which is the whole reason the gap survived three issues:

  * `DriveCraft` does not tell SPELL_FAILED_REQUIRES_SPELL_FOCUS from a
    cooldown. It logs a bare numeric `SpellCastResult` at INFO and retries every
    twenty seconds, for ever, and does not clear the errand. So a forge walk
    that lands a character just outside the focus produces a log that reads like
    a transient and a character that never crafts. Nothing on the C++ side will
    ever say "you are two yards short".
  * `overseer_roster.travel_npc` is VARCHAR(32) and MySQL TRUNCATES rather than
    refuses outside strict mode, so an over-long aim is not a failed aim - it is
    a different, plausible-looking coordinate nobody surveyed.
  * A background pass that latches `travel_npc` pins the family in one place for
    as long as it runs (infra#3703, infra#3708, infra#3728, four release fixes
    in one night).

THE REALM IS NOT IN THE STATE THESE TESTS DESCRIBE, deliberately. infra#3747
measured the family 9.02 to 11.65 yards from the Gadgetzan forge and concluded a
dry run there proved nothing either way, because 9 against a radius of 10 is a
coin flip. Measured again 2026-09-13 22:21 against a 25-second-old snapshot, the
family is SPLIT and nobody is near any forge at all: Grug and Ugga 178 yards from
the Gadgetzan forge (entry 141838), Bork, Og and Grog 1,435 to 1,659 yards from
theirs (entry 175851). Both of those are states a rule could pass by accident, so
the fixtures below are built from the spawn table rather than from either.

THE RADIUS FIXTURES ARE MEASURED, NOT INVENTED. Counted live against
`acore_world.gameobject_template` on 2026-09-13:

    type = 8 AND Data0 = 3 (Forge)   149 templates
      Data1 = 10 : 136      Data1 = 8 : 4       Data1 = 12 : 3
      Data1 = 15 : 2        Data1 = 30 : 2      Data1 = 4 : 1    Data1 = 5 : 1
    type = 8 AND Data0 = 1 (Anvil)   296 templates, Data1 = 10 for 289 of them

which is the counter-example to infra#3617's reading of `Data1` as the focus id:
anvils and forges BOTH mostly say 10, and the 10 is ten yards.
"""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
DECISIONS = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/overseer_decisions.cpp"
BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import craft  # noqa: E402
import goals  # noqa: E402
import travel  # noqa: E402

# The Gadgetzan forge, entry 141838 on map 1, as `_FORGE_SQL` would return it.
GADGETZAN = {"map_id": 1, "x": -7199.0, "y": -3766.2, "z": 8.7, "radius": 10}


class TheAimItself(unittest.TestCase):
    def test_a_forge_on_the_same_map_becomes_a_ground_aim(self):
        forge = travel.forge_aim(dict(GADGETZAN), 1)
        self.assertEqual(forge.aim, "at:1:-7199.0,-3766.2,8.7")
        self.assertEqual(forge.radius, 10)
        self.assertFalse(forge.refused)

    def test_the_aim_fits_the_column_it_has_to_live_in(self):
        """VARCHAR(32), and MySQL truncates rather than refuses. A truncated
        aim resolves to a coordinate nobody surveyed, which this project has
        already paid for in dead characters (infra#3704)."""
        forge = travel.forge_aim(dict(GADGETZAN), 1)
        self.assertLessEqual(len(forge.aim), travel.COLUMN_WIDTH)
        self.assertTrue(travel.is_ground_aim(forge.aim))

    def test_an_aim_too_long_for_the_column_is_refused_not_truncated(self):
        far = {"map_id": 530, "x": -39091.75, "y": -115489.5,
               "z": -14995.7, "radius": 10}
        forge = travel.forge_aim(far, 530)
        self.assertFalse(forge.aim)
        self.assertIn("truncate", forge.refused)

    def test_a_forge_on_another_map_is_not_a_longer_walk(self):
        """MoveFarTo paths through PathGenerator and there is no navmesh across
        an ocean, so a cross-map spawn is not a worse candidate, it is not a
        candidate."""
        forge = travel.forge_aim(dict(GADGETZAN), 0)
        self.assertFalse(forge.aim)
        self.assertIn("no navmesh", forge.refused)

    def test_no_snapshot_row_is_told_apart_from_no_forge(self):
        """Different things for a person to do about them: a forge on another
        continent is a travel problem, a family nobody can see is a snapshot
        problem."""
        self.assertIn("overseer_snapshot", travel.forge_aim(None, None).refused)
        self.assertIn("travels to a map", travel.forge_aim(None, 1).refused)

    def test_a_forge_narrower_than_the_arrival_tolerance_is_refused(self):
        """THE REFUSAL THAT IS NOT IN `vault_aim`, and the reason this is not
        just a copy of it. A Guild Vault is judged by its own five-yard interact
        gate; a smelt is judged by the FORGE's radius, and this world has forge
        templates at 4 and 5 yards. Arriving within TRAVEL_ARRIVED_POSITION_YARDS
        of a four-yard forge is a character standing outside the focus, and the
        refusal that follows is one DriveCraft logs as a bare number."""
        for radius in (0, 4, 5):
            with self.subTest(radius=radius):
                narrow = dict(GADGETZAN, radius=radius)
                forge = travel.forge_aim(narrow, 1)
                self.assertFalse(forge.aim)
                self.assertIn("focus", forge.refused)

    def test_a_forge_wider_than_the_tolerance_is_accepted(self):
        for radius in (8, 10, 12, 15, 30):
            with self.subTest(radius=radius):
                forge = travel.forge_aim(dict(GADGETZAN, radius=radius), 1)
                self.assertTrue(forge.aim)
                self.assertEqual(forge.radius, radius)

    def test_no_refusal_is_ever_a_bare_no(self):
        for spawn, standing in ((None, None), (None, 1),
                                (dict(GADGETZAN), 0),
                                (dict(GADGETZAN, radius=4), 1)):
            with self.subTest(spawn=spawn, standing=standing):
                refused = travel.forge_aim(spawn, standing).refused
                self.assertTrue(refused)
                self.assertGreater(len(refused.split()), 8)


class AlreadyStandingInIt(unittest.TestCase):
    """`within_focus` - judged against the forge's own radius, never a constant
    of ours, because that radius IS the rule CheckCast applies."""

    def test_inside_the_radius_needs_no_walk(self):
        self.assertTrue(travel.within_focus(dict(GADGETZAN, d2=81.0)))   # 9y

    def test_outside_the_radius_does(self):
        self.assertFalse(travel.within_focus(dict(GADGETZAN, d2=136.0)))  # 11.6y

    def test_the_boundary_counts_as_inside(self):
        self.assertTrue(travel.within_focus(dict(GADGETZAN, d2=100.0)))   # 10y

    def test_a_narrow_forge_is_judged_narrowly(self):
        """8 yards is inside a 10-yard focus and outside a 4-yard one, which is
        exactly why a single constant would be wrong in both directions."""
        near = dict(GADGETZAN, d2=64.0)                       # 8 yards
        self.assertTrue(travel.within_focus(near))
        self.assertFalse(travel.within_focus(dict(near, radius=4)))

    def test_a_row_that_cannot_answer_fails_towards_walking(self):
        """Not knowing whether they are close enough costs a walk; guessing
        that they are costs every cast, for ever, invisibly."""
        self.assertFalse(travel.within_focus(None))
        self.assertFalse(travel.within_focus(dict(GADGETZAN)))          # no d2
        self.assertFalse(travel.within_focus({"d2": 1.0}))              # no radius


class TheFactsAboutTheGame(unittest.TestCase):
    def test_the_focus_object_type_and_id_are_the_measured_ones(self):
        self.assertEqual(travel.SPELL_FOCUS_GO_TYPE, 8)   # GAMEOBJECT_TYPE_SPELL_FOCUS
        self.assertEqual(travel.FORGE_FOCUS_ID, 3)        # SpellFocusObject.dbc

    def test_the_module_records_that_data1_is_the_radius(self):
        """infra#3617 read `Data1` as the focus id and parked the whole
        forge/anvil question on the strength of it. The counts that tell the two
        columns apart live in the module so the misreading is not repeated."""
        import inspect
        source = inspect.getsource(travel)
        self.assertIn("3617", source)
        self.assertIn("Data0", source)
        self.assertIn("radius", source)


class TheArrivalToleranceIsMirroredFromTheModule(unittest.TestCase):
    """A CONTRACT TEST OVER THE PINNED C++, in the pattern test_travel_npc.py
    established for `travel.ROLES` against `TravelRoles()`.

    This one is not vocabulary, it is a NUMBER, and it is load-bearing in a way
    a keyword is not: `ARRIVED_POSITION_YARDS` is what decides which forges are
    candidates at all. If mod-overseer ever loosens its arrival tolerance past a
    forge's focus radius, the walk silently stops being enough - every smelt
    starts failing as a bare `SpellCastResult` that reads like a cooldown - and
    nothing else in either codebase would notice. CI notices here.
    """

    @classmethod
    def setUpClass(cls):
        if not MODULE.exists():
            raise unittest.SkipTest(
                "mod-overseer submodule is not initialised; run "
                "`git submodule update --init` (CI does)")
        cls.module = MODULE.read_text(encoding="utf-8", errors="replace")
        cls.decisions = DECISIONS.read_text(encoding="utf-8", errors="replace")

    def test_it_equals_the_constant_the_travel_drive_actually_uses(self):
        found = re.search(
            r"constexpr\s+float\s+TRAVEL_ARRIVED_POSITION_YARDS\s*=\s*"
            r"([0-9.]+)f\s*;", self.module)
        self.assertIsNotNone(
            found, "TRAVEL_ARRIVED_POSITION_YARDS is gone from mod_overseer.cpp")
        self.assertEqual(float(found.group(1)),
                         float(travel.ARRIVED_POSITION_YARDS))

    def test_a_ground_aim_is_the_tolerance_this_constant_names(self):
        """The module picks between two tolerances on whether the aim resolved
        a creature. An `at:` aim resolves `outEntry = 0`, so it takes the
        position one - which is the one mirrored above."""
        self.assertIn(
            "entry ? TRAVEL_ARRIVED_YARDS : TRAVEL_ARRIVED_POSITION_YARDS",
            self.module)
        self.assertIn("outEntry = 0;  // deliberately: the walk is the whole errand",
                      self.module)

    def test_the_column_width_agrees_with_the_module(self):
        found = re.search(
            r"constexpr\s+std::size_t\s+TRAVEL_AIM_COLUMN_CHARS\s*=\s*(\d+)\s*;",
            self.module)
        self.assertIsNotNone(found)
        self.assertEqual(int(found.group(1)), travel.COLUMN_WIDTH)

    def test_the_module_hands_a_ground_aim_back_by_itself(self):
        """WHY THIS PASS NEEDS NO RELEASE OF ITS OWN. `TravelAimBook::Release`
        skips its column write only when the book never claimed the aim AND
        `LearnSkillPending` or `IsMaintenanceErrand` holds. `CounterRoleForAim`
        answers `None` for an `at:` aim - its own enum comment says so in as
        many words - so neither holds and the column is cleared on arrival.
        That is the terminal path `_guild_bank_once` already relies on, and it
        is why adding a forge keyword to `_release_trade_errand`'s
        `ECONOMY_ERRANDS` guard would be wrong rather than merely unnecessary."""
        self.assertIn("bool IsMaintenanceErrand(std::string const& aim)",
                      self.decisions)
        self.assertIn("return CounterRoleForAim(aim) != CounterRole::None;",
                      self.decisions)
        self.assertIn("None,      // not a counter: a trainer, an innkeeper, an `at:`, a portal",
                      (ROOT / "docker/azerothcore-playerbots/mod-overseer/src"
                       / "overseer_decisions.h").read_text(
                          encoding="utf-8", errors="replace"))

    def test_only_the_leader_can_be_aimed(self):
        """Grog is the family's engineer and the character the bars are FOR, and
        aiming him would move nobody: mod-overseer grants `new rpg` to the
        leader alone and answers `RefuseInFormation` for a follower. The
        followers arrive by following, which is why this pass aims one
        character, like both bank passes before it."""
        self.assertIn("AimedMover::RefuseInFormation", self.module)

    def test_drive_craft_still_cannot_say_why_a_focused_cast_failed(self):
        """The reason the Python side has to make the failure legible. Pinned so
        that when the mod-overseer issue is fixed, this test is what tells
        somebody the log line here can be retired."""
        drive = self.module[self.module.index("void DriveCraft()"):]
        drive = drive[:drive.index("DiscoverFlightPointOnArrival")]
        self.assertIn("static_cast<uint32>(result)", drive)
        self.assertNotIn("SPELL_FAILED_REQUIRES_SPELL_FOCUS", drive.split(
            "SpellCastResult const result")[-1])


class TheCallerIsWiredAndCannotLatchTheColumn(unittest.TestCase):
    """A CONTRACT TEST OVER bridge.py's SOURCE, the pattern test_craft_rhythm.py
    uses for its own caller and for the same reason: a pure decision no live
    control flow reaches is a thing this repository has shipped before."""

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8", errors="replace")
        start = cls.source.index("async def _forge_once(self)")
        cls.body = cls.source[start:cls.source.index(
            "async def _forge_loop(self)")]
        # THE CODE, WITHOUT THE DOCSTRING. The ordering assertions below are
        # about which statement runs first, and that docstring names several of
        # these functions while explaining why - so searching the whole body
        # would find the prose and answer a question nobody asked.
        opened = cls.body.index('"""')
        cls.code = cls.body[cls.body.index('"""', opened + 3) + 3:]

    def test_the_loop_runs_under_the_gateway_and_headless_alike(self):
        """Two lists, and a loop registered in only one of them is a feature
        that silently does not exist in dev."""
        self.assertEqual(self.source.count("self._forge_loop,"), 2)

    def test_it_writes_nothing_unless_somebody_needs_a_forge(self):
        """THE SAFETY PROPERTY, not an optimisation. The demand read is the
        first statement in the function and it returns before anything else is
        read or written, so on every pass where no miner is smelting this
        competes for `travel_npc` not at all."""
        first = self.code.index("_forge_errands")
        self.assertLess(first, self.code.index("_write_trade_errand"))
        self.assertLess(first, self.code.index("_head_now"))
        self.assertIn("if not smelters:\n            return", self.code)

    def test_the_demand_read_is_gated_on_the_craft_permission(self):
        """`job='craft'` is DriveCraft's own permission. Walking somebody to a
        forge while the family is out gathering stands the quest drive down
        (`TravelHoldsTheWheel`) for a cast that cannot happen anyway."""
        reader = self.source[self.source.index("def _forge_errands()"):]
        reader = reader[:reader.index("def _current_travel_npc")]
        self.assertIn("job = %s", reader)
        self.assertIn("craft.MODE", reader)
        self.assertIn("craft.focus_for(", reader)

    def test_the_demand_read_asks_for_a_FORGE_and_not_for_any_focus(self):
        """infra#3760 put a SECOND focus id into `craft.RECIPES`: the eleven
        Anvil-gated Engineering brackets now declare `focus=1`, because they
        always needed one and the old test could not see it. An anvil and a
        forge are different objects in different places, so a demand read that
        asked "does this recipe need SOME focus" would walk Grog to a forge for
        Handful of Copper Bolts - a journey that moves the whole family and
        ends in exactly the silent SPELL_FAILED_REQUIRES_SPELL_FOCUS it was
        supposed to cure. A truthiness test on `focus_for` is that bug, and it
        is a one-character edit away, so it is pinned rather than reasoned
        about."""
        reader = self.source[self.source.index("def _forge_errands()"):]
        reader = reader[:reader.index("def _current_travel_npc")]
        self.assertIn("== travel.FORGE_FOCUS_ID", reader)
        # And the mapping the comparison relies on really does name the forge.
        self.assertEqual(craft.FOCUS_AIMS[travel.FORGE_FOCUS_ID], "forge")
        # Anvil-gated Engineering recipes exist in the table and must not match.
        anvil = [r.spell_id for r in
                 craft.RECIPES[goals.SKILL_IDS["engineering"]]
                 if r.focus == 1]
        self.assertTrue(anvil, "infra#3760's anvil entries have gone missing")
        for spell in anvil:
            with self.subTest(spell=spell):
                self.assertNotEqual(craft.focus_for(spell),
                                    travel.FORGE_FOCUS_ID)

    def test_it_goes_through_the_one_sanctioned_writer(self):
        """`_write_trade_errand` is the only thing in this process that writes
        `travel_npc`, and its guard is what keeps an economy aim from blanking
        an outstanding learn errand (mod-overseer#438)."""
        self.assertIn("_write_trade_errand", self.code)
        self.assertNotIn("UPDATE overseer_roster", self.code)
        self.assertNotIn("travel_npc =", self.code)

    def test_a_ground_aim_already_takes_the_guarded_branch(self):
        """So no change to `_retaskable_from` was needed, and none was made:
        infra#3702 taught it that an `at:` aim is an economy errand when the
        vault pass shipped. Pinned because deleting that branch would silently
        turn this pass into one that zeroes learn errands."""
        guard = self.source[self.source.index("def _retaskable_from("):]
        guard = guard[:guard.index("def _write_trade_errand(")]
        self.assertIn("if travel.is_ground_aim(aim):", guard)
        self.assertIn('return ("", aim)', guard)

    def test_it_skips_the_walk_when_the_smelter_is_already_in_the_focus(self):
        """Writing an aim for a walk of nought yards claims the column from
        whatever else could use it, and stands the quest drive down for a
        journey that is already over."""
        self.assertIn("travel.within_focus(spawn)", self.code)
        self.assertLess(self.code.index("travel.within_focus(spawn)"),
                        self.code.index("_write_trade_errand"))

    def test_every_way_out_says_which_characters_it_is_costing(self):
        """DriveCraft cannot say why a focused cast failed, so this is the only
        place a person can find out. Each of the three exits names the smelters
        it is leaving stuck."""
        for exit_line in ("forge: %s hold a focus-gated craft errand",
                          "forge: leader=%s could not be aimed at the forge",
                          "forge: leader=%s aimed at %s"):
            with self.subTest(exit=exit_line):
                self.assertIn(exit_line, self.code)
        self.assertGreaterEqual(self.code.count('", ".join(sorted(smelters))'), 3)

    def test_it_does_not_interrupt_a_dungeon_run(self):
        self.assertIn("self._mid_run(names)", self.code)

    def test_the_cadence_is_configurable_like_every_other_pass(self):
        loop = self.source[self.source.index("async def _forge_loop"):]
        loop = loop[:loop.index("async def _settle_town_errand")]
        self.assertIn('os.environ.get("CRAFT_FORGE_CYCLE_SECONDS"', loop)

    def test_it_claims_the_last_stagger_slot(self):
        """The rhythm decides whether the family crafts, `_assign_crafts` writes
        the recipe that follows, and only then is there a smelt errand to see.
        Arriving first would read a stale `craft_spell` - and would put this
        pass into the same instant as every other writer of the column."""
        loop = self.source[self.source.index("async def _forge_loop"):]
        loop = loop[:loop.index("async def _settle_town_errand")]
        mine = re.search(r"asyncio\.sleep\(min\(cycle,\s*([0-9.]+)\)\)", loop)
        self.assertIsNotNone(mine)
        rhythm = self.source[self.source.index("async def _craft_rhythm_loop"):]
        theirs = re.search(r"asyncio\.sleep\(min\(cycle,\s*([0-9.]+)\)\)", rhythm)
        self.assertGreater(float(mine.group(1)), float(theirs.group(1)))


class TheFocusVocabularyCannotDriftFromTheWalk(unittest.TestCase):
    """`craft.FOCUS_AIMS` claims a walk exists for every id in it. These are
    what stop that being a claim."""

    def test_the_forge_is_the_only_focus_anything_walks_to(self):
        self.assertEqual(set(craft.FOCUS_AIMS), {travel.FORGE_FOCUS_ID})

    def test_the_named_pass_exists_and_uses_the_named_aim(self):
        source = BRIDGE.read_text(encoding="utf-8", errors="replace")
        self.assertIn("async def _forge_once(self)", source)
        self.assertIn("travel.forge_aim(", source)
        self.assertIn("travel.SPELL_FOCUS_GO_TYPE", source)
        self.assertIn("travel.FORGE_FOCUS_ID", source)

    def test_the_query_filters_on_data0_and_the_radius(self):
        """Data0 is the focus id and Data1 is the radius. A query built on
        infra#3617's reading would return every focus object whose radius
        happens to be ten - forges, anvils and looms alike."""
        source = BRIDGE.read_text(encoding="utf-8", errors="replace")
        sql = source[source.index("_FORGE_SQL = ("):]
        sql = sql[:sql.index("def _nearest_forge")]
        self.assertIn("gt.type = %s AND gt.Data0 = %s AND gt.Data1 > %s", sql)
        self.assertIn("gt.Data1 AS radius", sql)
        self.assertIn("g.map = s.map_id", sql)          # the same-map rule
        self.assertIn("ORDER BY d2 LIMIT 1", sql)


if __name__ == "__main__":
    unittest.main()

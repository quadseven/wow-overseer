"""craft_rhythm - the gather/craft alternation, its data, and its refusals.

Three halves, and the second and third are the ones that matter.

THE FIXTURES ARE MEASURED, NOT INVENTED, the same discipline
test_craft_supply.py's own docstring states. The live family on 2026-09-13
19:15, read straight off `overseer_roster`, `character_skills` and
`item_instance` while all five sat on job='craft' producing nothing:

    Bork  Leatherworking 1, Skinning 12   craft_spell 2881   0x Ruined Leather Scraps
    Grog  Engineering 1, Mining 1         craft_spell 3918   0x Rough Stone
    Grug  Blacksmithing 1, Mining 8       craft_spell 2660   0x Rough Stone
    Og    Tailoring 50, Enchanting 1      craft_spell 2963   1x Linen Cloth
    Ugga  Alchemy 14, Herbalism 132       craft_spell 2330   0x Peacebloom, 7x Silverleaf

`TheLiveFamilyIsTheOneThatWasStuck` pins that whole state end to end, including
that `craft.craft_errand` independently derives each of those five craft_spell
values from the skills alone.

THE STATES THE REALM IS NOT IN ARE TESTED HARDEST, deliberately. A dry run
against this realm as it stands proves almost nothing: every member is at zero
casts, so a rule that fired on any shortfall whatsoever would pass. So the
classes below spend most of their length on states no snapshot contains - a
fully stocked family, a family in the dead band, a family mid-dungeon, a
roster whose rows disagree, and a member nothing can ever supply - because
those are the ones where a wrong rule hides.

THE LAST CLASS IS A CONTRACT TEST OVER bridge.py's SOURCE TEXT, in the pattern
test_trainjob.py established. It exists because this module's correctness is
only half the change: a pure decision that no live control flow reaches is the
failure this repository has shipped before, and `test_the_only_write_is_a_job
_mode` is what keeps the caller from growing a second one.
"""

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import craft  # noqa: E402
import craft_rhythm  # noqa: E402
import craft_supply  # noqa: E402
import jobs  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

# The live family, exactly as measured. Skills first, holdings second.
LIVE_SKILLS = {
    "Bork": {
        "leatherworking": 1,
        "skinning": 12,
        "first aid": 1,
        "cooking": 1,
        "fishing": 1,
    },
    "Grog": {"mining": 1, "engineering": 1, "first aid": 1, "cooking": 1, "fishing": 1},
    "Grug": {
        "blacksmithing": 1,
        "mining": 8,
        "first aid": 1,
        "cooking": 1,
        "fishing": 1,
    },
    "Og": {
        "tailoring": 50,
        "enchanting": 1,
        "first aid": 1,
        "cooking": 1,
        "fishing": 1,
    },
    "Ugga": {
        "alchemy": 14,
        "herbalism": 132,
        "first aid": 1,
        "cooking": 1,
        "fishing": 1,
    },
}
# OG'S ENTRY IS 8776 AND IT USED TO BE 2963, AND THAT CHANGE IS THE WHOLE
# POINT OF THE BRACKET SWEEP (part of infra#3731). The 2026-09-13 roster really
# did hold 2963 for him - this table is a faithful snapshot - but 2963 is Bolt
# of Linen Cloth, whose TrivialSkillLineRankHigh is 50, and Og's Tailoring is
# exactly 50. He was casting a recipe that cannot roll a skill-up, for ever,
# and the proof is in his own bags: 151 Bolt of Linen Cloth on 2026-09-13,
# 151 casts that produced an item and not one point. With the edge corrected
# he derives Linen Belt (8776) instead, whose reagent is those 151 bolts.
#
# So the old value is not the baseline this test should defend - it is the bug
# it should have caught. Kept here as the DERIVED answer, with the historical
# column value recorded in the sentence above rather than in the assertion.
LIVE_SPELLS = {"Bork": 2881, "Grog": 3918, "Grug": 2660, "Og": 8776, "Ugga": 2330}
LIVE_HELD = {
    "Bork": {2934: 0},
    "Grog": {2835: 0},
    "Grug": {2835: 0},
    "Og": {2589: 1},
    "Ugga": {2447: 0, 765: 7},
}


def _stand(name, spell, held):
    return craft_rhythm.stand(name, spell, held)


def _family(verdicts):
    """A family of stands at chosen cast counts, via a one-reagent recipe.

    Uses Rough Sharpening Stone (2660, 1x Rough Stone) so a cast count and a
    held count are the same number and the test reads as the state it means.
    """
    return [_stand(name, 2660, {2835: casts}) for name, casts in verdicts.items()]


class TheGatheredTableIsAProjectionOfTheRecipeNotes(unittest.TestCase):
    """The reagent map already existed twice (craft_supply.REAGENT and
    REAGENTS) and a third copy would be a third thing to keep in step. Those
    two hold the BOUGHT half only; this holds the GATHERED half, and these
    tests are what make the three a partition rather than three opinions."""

    def test_every_spell_is_a_real_crafting_recipe(self):
        known = {r.spell_id for recipes in craft.RECIPES.values() for r in recipes}
        for spell in sorted(craft_rhythm.GATHERED):
            with self.subTest(spell=spell):
                self.assertIn(spell, known)

    def test_every_reagent_is_the_one_the_recipe_note_names(self):
        """THE ANTI-DRIFT PIN. The note is the human-readable source of truth
        and it was verified against the worldserver's own Spell.dbc; this table
        is a machine-readable projection of it. Requiring the exact
        "<per_cast>x <label>" string in the note means a quantity changed in
        one place and not the other fails on the pull request, and an entry
        invented here for a reagent the recipe does not use cannot be added."""
        notes = {
            r.spell_id: r.note for recipes in craft.RECIPES.values() for r in recipes
        }
        for spell, reagents in sorted(craft_rhythm.GATHERED.items()):
            for reagent in reagents:
                with self.subTest(spell=spell, reagent=reagent.label):
                    self.assertIn(
                        "%dx %s" % (reagent.per_cast, reagent.label), notes[spell]
                    )

    def test_no_reagent_is_also_a_bought_one(self):
        """A gathered reagent must never be in craft_supply, and a bought one
        must never be here. craft_supply's own docstring gives the cost of the
        first direction: `reagent_errand` would log "no reachable vendor stocks
        it" on every poll for ever. The cost of the second is this module
        sending the family roaming for something a vendor sells unlimited."""
        bought = {entry for entry, _l, _p in craft_supply.REAGENT.values()}
        for reagents in craft_supply.REAGENTS.values():
            bought.update(entry for entry, _l, _p, _q in reagents)
        for spell, reagents in sorted(craft_rhythm.GATHERED.items()):
            for reagent in reagents:
                with self.subTest(spell=spell, entry=reagent.entry):
                    self.assertNotIn(reagent.entry, bought)

    def test_no_recipe_names_the_same_reagent_twice(self):
        for spell, reagents in sorted(craft_rhythm.GATHERED.items()):
            entries = [r.entry for r in reagents]
            with self.subTest(spell=spell):
                self.assertEqual(len(entries), len(set(entries)))

    def test_every_quantity_is_positive(self):
        """A zero per_cast would make `casts_in_hand` divide by zero and a
        negative one would make an empty bag read as infinite stock."""
        for spell, reagents in sorted(craft_rhythm.GATHERED.items()):
            for reagent in reagents:
                with self.subTest(spell=spell, reagent=reagent.label):
                    self.assertGreater(reagent.per_cast, 0)
                    self.assertGreater(reagent.entry, 0)

    def test_the_smelted_bar_recipes_are_deliberately_absent(self):
        """Copper, Steel, Mithril and Thorium Bar carry zero npc_vendor rows
        AND zero rows in every loot table on this world - they are smelted, and
        nothing in this codebase drives smelting. Including these recipes would
        send the family roaming for an item the world never drops, which is the
        one thing worse than not deciding. Pinned so a later pass that adds a
        reagent map has to think about it rather than fill the gap in."""
        for spell in (
            3922,
            7430,
            3923,
            3973,
            3938,
            12590,
            12589,
            12591,
            12599,
            12619,
            19791,
            19795,
        ):
            with self.subTest(spell=spell):
                self.assertNotIn(spell, craft_rhythm.GATHERED)

    def test_the_own_crafted_intermediates_are_deliberately_absent(self):
        """2337 needs a Minor Healing Potion, 8776 a Bolt of Linen Cloth, and
        7151/7156 a Cured Heavy Hide - which has zero rows in every loot table
        and every vendor on this world, because it exists only if somebody
        casts 3818. No gathering trip returns with any of them."""
        for spell in (2337, 8776, 7151, 7156):
            with self.subTest(spell=spell):
                self.assertNotIn(spell, craft_rhythm.GATHERED)


class TheGatheringModeIsQuestAndNotFarm(unittest.TestCase):
    """`farm` is the obvious answer and it is the wrong one: it is a valid
    name in jobs.MODES and in mod_overseer.cpp's JobModes(), so it would be
    accepted and then drive nothing at all."""

    def test_both_modes_are_ones_the_write_path_will_accept(self):
        for mode in (craft_rhythm.MODE_GATHER, craft_rhythm.MODE_CRAFT):
            with self.subTest(mode=mode):
                self.assertTrue(jobs.can_set(mode))
                self.assertEqual(jobs.why_not(mode), "")

    def test_farm_would_have_been_refused(self):
        """The reason this module does not use it, asserted rather than
        asserted in a comment."""
        self.assertFalse(jobs.can_set("farm"))
        self.assertNotEqual(jobs.why_not("farm"), "")
        self.assertNotEqual(craft_rhythm.MODE_GATHER, "farm")

    def test_the_craft_mode_is_the_one_craft_py_names(self):
        self.assertEqual(craft_rhythm.MODE_CRAFT, craft.MODE)


class TheThinnestReagentDecides(unittest.TestCase):
    def test_a_recipe_is_stopped_by_whichever_reagent_runs_out_first(self):
        """Ugga's real state: seven Silverleaf and no Peacebloom is not
        "mostly stocked", it is zero castable potions."""
        got = _stand("Ugga", 2330, {2447: 0, 765: 7})
        self.assertEqual(got.casts, 0)
        self.assertEqual(got.verdict, craft_rhythm.SHORT)
        self.assertEqual(got.thinnest, "Peacebloom")

    def test_the_per_cast_quantity_divides(self):
        """Og holding one Linen Cloth against a recipe needing two is zero
        casts, not one - the arithmetic that made his idle invisible."""
        self.assertEqual(craft_rhythm.casts_in_hand(2963, {2589: 1}), 0)
        self.assertEqual(craft_rhythm.casts_in_hand(2963, {2589: 25}), 12)

    def test_a_missing_entry_counts_as_none_held(self):
        """The bridge's count query LEFT JOINs and returns 0 for a character
        carrying none, so an absent key can only mean nobody asked."""
        self.assertEqual(craft_rhythm.casts_in_hand(2660, {}), 0)

    def test_a_recipe_with_no_gathered_reagent_has_no_answer(self):
        self.assertIsNone(craft_rhythm.casts_in_hand(3922, {2840: 99}))
        self.assertIsNone(craft_rhythm.casts_in_hand(0, {}))


class TheVerdictBoundariesAreExact(unittest.TestCase):
    """Off-by-one here is a family that flips a cast early or late for ever."""

    def test_below_the_floor_is_short(self):
        for casts in (0, 1, 2):
            with self.subTest(casts=casts):
                self.assertEqual(
                    _stand("Grug", 2660, {2835: casts}).verdict, craft_rhythm.SHORT
                )

    def test_the_floor_itself_is_already_the_dead_band(self):
        self.assertEqual(_stand("Grug", 2660, {2835: 3}).verdict, craft_rhythm.BETWEEN)

    def test_one_short_of_the_ceiling_is_still_the_dead_band(self):
        self.assertEqual(_stand("Grug", 2660, {2835: 11}).verdict, craft_rhythm.BETWEEN)

    def test_the_ceiling_itself_is_stocked(self):
        for casts in (12, 13, 500):
            with self.subTest(casts=casts):
                self.assertEqual(
                    _stand("Grug", 2660, {2835: casts}).verdict, craft_rhythm.STOCKED
                )

    def test_the_band_is_wide_enough_to_be_a_band(self):
        """The ratio is the design, not either endpoint. A floor and ceiling
        one apart would be no hysteresis at all."""
        self.assertGreater(craft_rhythm.STOCK_CASTS, craft_rhythm.SHORT_CASTS * 2)

    def test_the_ceiling_is_inside_what_the_family_has_been_measured_to_hold(self):
        """Ugga held 13 Peacebloom-casts on the night Alchemy went 1 to 14. A
        threshold above the family's measured reach never fires, and a family
        that never crafts again is a worse failure than a short session."""
        self.assertLessEqual(craft_rhythm.STOCK_CASTS, 13)

    def test_no_verdict_is_ever_silent(self):
        for spell, held in (
            (2660, {2835: 0}),
            (2660, {2835: 5}),
            (2660, {2835: 50}),
            (3922, {}),
            (0, {}),
        ):
            with self.subTest(spell=spell):
                self.assertTrue(_stand("Grug", spell, held).why)


class TheHysteresisHoldsInBothDirections(unittest.TestCase):
    """THE POINT OF THE WHOLE MODULE. The dead band means the family's current
    mode is the tie-breaker, so the same reagent count produces a different
    answer depending on where they already are - which is what stops one
    reagent hovering at a boundary re-aiming five characters every poll."""

    def test_crafting_keeps_crafting_down_through_the_band(self):
        plan = craft_rhythm.rhythm(_family({"Grug": 5, "Og": 7}), "craft")
        self.assertEqual(plan.mode, "craft")
        self.assertFalse(plan.changed)

    def test_gathering_keeps_gathering_up_through_the_same_band(self):
        """The identical world as the test above, decided the other way purely
        because the family is somewhere else. If these two ever agree, the
        hysteresis has been deleted."""
        plan = craft_rhythm.rhythm(_family({"Grug": 5, "Og": 7}), "quest")
        self.assertEqual(plan.mode, "quest")
        self.assertFalse(plan.changed)

    def test_crafting_leaves_only_when_somebody_is_truly_out(self):
        plan = craft_rhythm.rhythm(_family({"Grug": 2, "Og": 40}), "craft")
        self.assertEqual(plan.mode, craft_rhythm.MODE_GATHER)
        self.assertTrue(plan.changed)

    def test_gathering_sits_down_only_when_everybody_is_stocked(self):
        plan = craft_rhythm.rhythm(_family({"Grug": 12, "Og": 40}), "quest")
        self.assertEqual(plan.mode, craft_rhythm.MODE_CRAFT)
        self.assertTrue(plan.changed)

    def test_one_member_in_the_band_is_enough_to_keep_the_family_gathering(self):
        """All stocked means ALL. A family that sat down with one member at
        eleven casts would leave that member idle inside two polls, which is
        the silent idle this issue is about."""
        plan = craft_rhythm.rhythm(_family({"Grug": 11, "Og": 40}), "quest")
        self.assertEqual(plan.mode, "quest")
        self.assertFalse(plan.changed)

    def test_one_member_short_outranks_four_stocked(self):
        """A gathering trip is non-exclusive - the family roams together and
        everyone picks up their own - so one walk serves all five. A crafting
        session is exclusive and produces nothing for the member with no
        materials."""
        plan = craft_rhythm.rhythm(
            _family({"Bork": 99, "Grog": 99, "Grug": 99, "Og": 99, "Ugga": 0}), "craft"
        )
        self.assertEqual(plan.mode, craft_rhythm.MODE_GATHER)
        self.assertTrue(plan.changed)

    def test_an_already_correct_mode_is_never_rewritten(self):
        """`changed` is the caller's whole write gate. Without it this pass
        would insert one overseer_command row per character per cycle for
        ever."""
        plan = craft_rhythm.rhythm(_family({"Grug": 0}), "quest")
        self.assertEqual(plan.mode, craft_rhythm.MODE_GATHER)
        self.assertFalse(plan.changed)


class ItRefusesToArbitrateAnythingElse(unittest.TestCase):
    def test_a_dungeon_run_is_never_interrupted(self):
        """The dungeon coordinator's SOLE trigger is the leader's job being
        'dungeon' (mod-overseer#88/#144). A pass that helpfully switched the
        family to 'quest' mid-run would end the run."""
        plan = craft_rhythm.rhythm(_family({"Grug": 0}), "dungeon")
        self.assertEqual(plan.mode, "")
        self.assertFalse(plan.changed)
        self.assertIn("dungeon", plan.why)

    def test_a_train_errand_outranks_this_pass_too(self):
        plan = craft_rhythm.rhythm(_family({"Grug": 99, "Og": 99}), "train")
        self.assertEqual(plan.mode, "")
        self.assertFalse(plan.changed)

    def test_a_roster_that_disagrees_is_left_alone(self):
        """A fan-out can land partially - `_set_job` counts written against
        called for exactly that reason - so deciding a transition from a mode
        nobody uniformly holds would write over an order still settling."""
        self.assertEqual(
            craft_rhythm.standing_mode({"Grug": "craft", "Og": "quest"}), ""
        )
        plan = craft_rhythm.rhythm(_family({"Grug": 0}), "")
        self.assertEqual(plan.mode, "")

    def test_an_agreed_roster_reads_back_as_that_mode(self):
        self.assertEqual(
            craft_rhythm.standing_mode({"Grug": "craft", "Og": "craft"}), "craft"
        )

    def test_an_empty_roster_agrees_about_nothing(self):
        self.assertEqual(craft_rhythm.standing_mode({}), "")


class AnUnsupplyableMemberNeverHoldsTheFamilyHostage(unittest.TestCase):
    """Grog's Engineering hits a hard ceiling at skill 31, where the recipe
    wants a smelted Copper Bar that this world drops nowhere and sells nowhere.
    Counting him as permanently short would hold the other four in gathering
    mode for ever, waiting for an item no walk can return with."""

    def test_an_unjudged_member_does_not_force_gathering(self):
        stands = _family({"Bork": 40, "Og": 40}) + [_stand("Grog", 3922, {})]
        plan = craft_rhythm.rhythm(stands, "quest")
        self.assertEqual(plan.mode, craft_rhythm.MODE_CRAFT)
        self.assertTrue(plan.changed)

    def test_an_unjudged_member_does_not_block_the_stocked_verdict(self):
        stands = _family({"Bork": 40}) + [_stand("Grog", 0, {})]
        self.assertEqual(
            craft_rhythm.rhythm(stands, "quest").mode, craft_rhythm.MODE_CRAFT
        )

    def test_a_family_nobody_can_judge_changes_nothing(self):
        stands = [_stand("Grog", 3922, {}), _stand("Og", 0, {})]
        plan = craft_rhythm.rhythm(stands, "craft")
        self.assertEqual(plan.mode, "")
        self.assertFalse(plan.changed)

    def test_the_unjudged_are_named_every_pass(self):
        """A permanently unjudged member is the one thing here that will never
        fix itself, so it must never be silent."""
        stands = _family({"Bork": 40}) + [_stand("Grog", 3922, {})]
        said = craft_rhythm.report(craft_rhythm.rhythm(stands, "quest"))
        self.assertIn("Grog", said)
        self.assertIn("No opinion formed about", said)


class TheReportNamesWhatWouldOtherwiseNeedAQuery(unittest.TestCase):
    """infra#3696's own words: "a character with a correct errand and no
    materials is indistinguishable from one with nothing to do", because
    DriveCraft's reagent pre-filter is a bare `continue` with no log line."""

    def test_a_starved_character_is_named_with_its_reagent(self):
        said = craft_rhythm.report(
            craft_rhythm.rhythm([_stand("Ugga", 2330, {2447: 0, 765: 7})], "craft")
        )
        self.assertIn("Ugga", said)
        self.assertIn("Peacebloom", said)

    def test_a_pass_that_writes_nothing_says_so(self):
        said = craft_rhythm.report(craft_rhythm.rhythm(_family({"Grug": 0}), "quest"))
        self.assertIn("nothing is written", said)

    def test_a_refusal_is_never_a_bare_no(self):
        for standing in ("dungeon", "rest", ""):
            with self.subTest(standing=standing):
                plan = craft_rhythm.rhythm(_family({"Grug": 0}), standing)
                self.assertTrue(craft_rhythm.report(plan).strip())


class TheLiveFamilyIsTheOneThatWasStuck(unittest.TestCase):
    """End to end over the measured 2026-09-13 19:15 snapshot: five characters
    on job='craft', every one carrying a correct errand, every one holding
    nothing its recipe consumes, and the whole family standing still."""

    def test_the_planner_derives_the_craft_spell_each_of_them_was_carrying(self):
        """`_craft_rhythm_once` derives the errand rather than reading the
        column, so this is what makes that derivation trustworthy: the same
        five spell ids the live roster held, from the skills alone."""
        for name, spell in sorted(LIVE_SPELLS.items()):
            with self.subTest(name=name):
                self.assertEqual(craft.craft_errand(name, LIVE_SKILLS[name]), spell)

    def test_the_four_a_gathering_trip_can_help_read_as_starved(self):
        """FOUR, not five, and the fifth is not an omission. Og's corrected
        bracket at Tailoring 50 is Linen Belt, whose reagents are a bought
        Coarse Thread and an own-crafted Bolt of Linen Cloth - no gathering
        trip returns with either, so `GATHERED` deliberately holds no entry
        for 8776 and this pass has no opinion about him."""
        for name in sorted(set(LIVE_SPELLS) - {"Og"}):
            with self.subTest(name=name):
                got = _stand(name, LIVE_SPELLS[name], LIVE_HELD[name])
                self.assertEqual(got.verdict, craft_rhythm.SHORT)
                self.assertEqual(got.casts, 0)

    def test_og_abstains_rather_than_voting_on_a_trip_that_cannot_help_him(self):
        """The abstain branch, on the one live character that now reaches it.
        It must not read as SHORT - that would hold the whole family out
        gathering for a reagent no node drops."""
        got = _stand("Og", LIVE_SPELLS["Og"], LIVE_HELD["Og"])
        self.assertEqual(got.verdict, craft_rhythm.UNJUDGED)
        self.assertIn("no reagent a gathering trip produces", got.why)

    def test_the_family_is_sent_gathering(self):
        stands = [_stand(n, LIVE_SPELLS[n], LIVE_HELD[n]) for n in LIVE_SPELLS]
        plan = craft_rhythm.rhythm(stands, "craft")
        self.assertEqual(plan.mode, craft_rhythm.MODE_GATHER)
        self.assertTrue(plan.changed)

    def test_and_comes_back_once_that_gathering_has_paid_off(self):
        """The state the realm has NEVER been in, which is exactly why it is
        tested: the same five characters with a dozen casts each. If this does
        not return them to crafting, the loop only has one direction and the
        issue is not fixed."""
        stocked = {
            "Bork": {2934: 36},
            "Grog": {2835: 12},
            "Grug": {2835: 12},
            "Og": {2589: 24},
            "Ugga": {2447: 12, 765: 12},
        }
        stands = [_stand(n, LIVE_SPELLS[n], stocked[n]) for n in LIVE_SPELLS]
        plan = craft_rhythm.rhythm(stands, craft_rhythm.MODE_GATHER)
        self.assertEqual(plan.mode, craft_rhythm.MODE_CRAFT)
        self.assertTrue(plan.changed)

    def test_and_does_not_come_back_one_reagent_early(self):
        """One member left at eleven casts while the rest are full. The whole
        family stays out, because `all stocked` means all."""
        nearly = {
            "Bork": {2934: 36},
            "Grog": {2835: 12},
            "Grug": {2835: 12},
            "Og": {2589: 24},
            "Ugga": {2447: 11, 765: 40},
        }
        stands = [_stand(n, LIVE_SPELLS[n], nearly[n]) for n in LIVE_SPELLS]
        plan = craft_rhythm.rhythm(stands, craft_rhythm.MODE_GATHER)
        self.assertEqual(plan.mode, craft_rhythm.MODE_GATHER)
        self.assertFalse(plan.changed)


class TheCallerIsWiredAndWritesOnlyAJobMode(unittest.TestCase):
    """A CONTRACT TEST OVER bridge.py's SOURCE, in test_trainjob.py's pattern.
    A pure decision no live control flow reaches is a thing this repository has
    shipped before; so is a fix sitting below an early return that could never
    have fired. These pin the wiring rather than the behaviour."""

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8", errors="replace")
        start = cls.source.index("async def _craft_rhythm_once(self")
        cls.body = cls.source[
            start : cls.source.index("async def _craft_rhythm_loop(self)")
        ]

    def test_the_loop_runs_under_the_gateway_and_headless_alike(self):
        """Two lists, and a loop registered in only one of them is a feature
        that silently does not exist in dev."""
        self.assertEqual(self.source.count("self._craft_rhythm_loop,"), 2)

    def test_the_only_write_is_a_job_mode(self):
        """NOT `travel_npc`, and this is a rule rather than an oversight: a
        second writer for that column has pinned this family in a shop for half
        an hour more than once (infra#3703, infra#3708, infra#3728)."""
        for forbidden in (
            "_write_trade_errand",
            "_write_craft_errand",
            "travel_npc =",
            "_insert_town_errand",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.body)

    def test_gathering_asks_the_town_slot_for_idleness(self):
        self.assertIn('self._idle_town_slot("craft_rhythm")', self.body)
        self.assertLess(
            self.body.index('self._idle_town_slot("craft_rhythm")'),
            self.body.index("if not plan.changed:"),
            "an unchanged gather cycle must renew its idle want",
        )

    def test_it_goes_through_the_sanctioned_write_path(self):
        """`_set_job` is where `jobs.why_not` is asked. A second writer next to
        it is exactly the omission infra#3338 was filed about."""
        self.assertIn("self._set_job(", self.body)
        self.assertNotIn("_insert_job", self.body)

    def test_nothing_is_written_unless_the_mode_actually_changes(self):
        self.assertIn("if not plan.changed:", self.body)
        self.assertLess(
            self.body.index("if not plan.changed:"),
            self.body.index("self._set_job("),
            "the write must sit below the change gate",
        )

    def test_the_report_is_logged_before_the_change_gate(self):
        """The starvation this names is the half of infra#3696 that has nothing
        to do with the mode, so it must survive a pass that writes nothing."""
        self.assertLess(
            self.body.index("craft_rhythm.report(plan)"),
            self.body.index("if not plan.changed:"),
        )

    def test_the_errand_is_derived_and_not_read_off_the_roster(self):
        """craft_spell is only written while the family is already crafting, so
        a pass that read it could never let a family start.

        infra#3748 moved the derivation one step along - from
        `craft.craft_errand` to `craft_rhythm.errand`, which wraps it and may
        answer with a miner's smelt instead - but the property being pinned is
        unchanged and is the reason this test exists: the answer is COMPUTED
        from skills and bags, never read back out of the column this loop's
        own sibling writes."""
        self.assertIn("craft_rhythm.errand(", self.body)
        self.assertNotIn("_fetch_craft_spells", self.body)

    def test_it_judges_stock_against_the_recipe_it_actually_chose(self):
        """A miner may be carrying its smelt rather than its craft. Judging its
        stock against the other one would report a shortfall of the wrong
        reagent and send the family after the wrong material - so the SAME
        chooser both passes use must feed `stand`, not `craft.craft_errand`
        directly."""
        self.assertIn("craft_rhythm.reagents_to_count(", self.body)
        chose = self.body.index("craft_rhythm.errand(")
        self.assertLess(chose, self.body.index("craft_rhythm.stand("))
        self.assertNotIn("craft.craft_errand(", self.body)

    def test_the_cadence_is_configurable_like_every_other_pass(self):
        loop = self.source[self.source.index("async def _craft_rhythm_loop") :]
        self.assertIn(
            'os.environ.get("CRAFT_RHYTHM_CYCLE_SECONDS"',
            loop[: loop.index("async def _protect_characters")],
        )

    def test_the_automatic_caller_still_hears_what_set_job_says(self):
        """`_set_job` reports by speaking. An automatic pass has no channel,
        and the honest answer is a sink that keeps the sentences rather than
        one that drops them."""
        sink = self.source[self.source.index("class _LogChannel:") :]
        sink = sink[: sink.index("def _council_family")]
        self.assertIn("log.info", sink)
        self.assertTrue(re.search(r"async def send\(self, text", sink))


class SpendOrSmelt(unittest.TestCase):
    """infra#3748's alternation: which of a miner's two recipes it carries.

    THE REALM IS NOT IN ANY OF THESE STATES, WHICH IS WHY THEY ARE HERE.
    Measured 2026-09-13 22:21, Grug holds 3x Silver Ore and nothing else and
    Grog holds 1x Silver Bar and nothing else - no Copper Ore, no Rough Stone,
    no Copper Bar between them. Every branch below therefore describes a world
    no query returns today, and a rule that only worked on today's bags would
    pass a live dry run and fail the first time the family came back from a
    mine. `TheLiveFamilyIsTheOneThatWasStuck` above pins the real state; this
    pins the rule.

    Grug is ("mining", "blacksmithing") and Grog ("mining", "engineering") in
    `professions.ROSTER`, mining FIRST in both, which is the fact that makes
    the choice necessary rather than incidental - see craft.smelt_errand.
    """

    def test_a_miner_who_can_craft_crafts(self):
        """Mining is the supply line and infra#3731 is about the crafting
        trades, so the craft wins the tie. The ore keeps."""
        chosen = craft_rhythm.errand(
            "Grug",
            {"mining": 8, "blacksmithing": 1},
            {2770: 20, 2835: 20},  # 20 Copper Ore AND 20 Rough Stone
        )
        self.assertEqual(chosen.spell, 2660)  # Rough Sharpening Stone
        self.assertFalse(chosen.smelting)
        self.assertIn("spends rather than smelts", chosen.why)

    def test_a_miner_out_of_its_craft_reagent_smelts_instead_of_idling(self):
        """This is the whole point: a character with ore and no stone used to
        stand at zero casts logging nothing (DriveCraft's reagent pre-filter is
        a bare `continue`). Now it raises Mining and banks bars."""
        chosen = craft_rhythm.errand(
            "Grug",
            {"mining": 8, "blacksmithing": 1},
            {2770: 20, 2835: 0},
        )
        self.assertEqual(chosen.spell, 2657)  # Smelt Copper
        self.assertTrue(chosen.smelting)

    def test_a_bar_gated_craft_errand_is_answered_by_the_smelt(self):
        """Grog at Engineering 31 wants Handful of Copper Bolts, whose only
        reagent is a Copper Bar - which `GATHERED` deliberately cannot judge,
        because no walk returns with one. `casts_in_hand` answering None is
        precisely the signature of a recipe waiting on a smelt, and this is the
        branch that reads it that way."""
        self.assertIsNone(craft_rhythm.casts_in_hand(3922, {}))
        chosen = craft_rhythm.errand(
            "Grog",
            {"mining": 1, "engineering": 31},
            {2770: 5},
        )
        self.assertEqual(chosen.spell, 2657)
        self.assertTrue(chosen.smelting)
        self.assertIn("no gathering trip produces", chosen.why)

    def test_a_miner_with_no_ore_keeps_its_craft_errand(self):
        """AND THIS IS WHAT KEEPS THE ORE ENTRY SAFE. infra#3747 refused to add
        Copper Ore to GATHERED because a character short of it would read as
        SHORT and hold the family in gathering mode for a bar he could not
        make. He can make it now - but only if he has ore, so a character with
        neither ore nor stone must be judged on the reagent the family can
        actually be sent after, not on the ore for a smelt that would produce
        a bar nobody is waiting for."""
        chosen = craft_rhythm.errand(
            "Grug",
            {"mining": 8, "blacksmithing": 1},
            {2770: 0, 2835: 0},
        )
        self.assertEqual(chosen.spell, 2660)
        self.assertFalse(chosen.smelting)

    def test_nothing_changes_for_a_character_with_no_gathering_trade(self):
        for name, skills, spell in (
            # 8776, not 2963: at Tailoring 50 the bolt is grey. Linen Belt's
            # reagents are bought and own-crafted, so this pass has no opinion
            # about him either way - which is the branch being tested.
            ("Og", {"tailoring": 50, "enchanting": 1}, 8776),
            ("Ugga", {"alchemy": 14, "herbalism": 132}, 2330),
            ("Bork", {"leatherworking": 1, "skinning": 12}, 2881),
        ):
            with self.subTest(name=name):
                chosen = craft_rhythm.errand(name, skills, {})
                self.assertEqual(chosen.spell, spell)
                self.assertFalse(chosen.smelting)
                self.assertIn("no smeltable gathering trade", chosen.why)

    def test_no_choice_is_ever_silent(self):
        """Same rule as `Stand.why`: this swaps what a character spends a whole
        session on, and a swap nobody can explain reads as the planner having
        lost the recipe."""
        for held in ({}, {2770: 20}, {2770: 20, 2835: 20}, {2835: 20}):
            with self.subTest(held=held):
                chosen = craft_rhythm.errand(
                    "Grug", {"mining": 8, "blacksmithing": 1}, held
                )
                self.assertTrue(chosen.why.strip())
                self.assertIn("Grug", chosen.why)

    def test_both_candidates_are_counted_before_either_is_chosen(self):
        """The chicken-and-egg: choosing needs the counts, so the counts cannot
        be fetched for the chosen recipe only."""
        wanted = craft_rhythm.reagents_to_count(
            "Grug", {"mining": 8, "blacksmithing": 1}
        )
        self.assertEqual(wanted, {2770, 2835})  # Copper Ore AND Rough Stone

    def test_a_character_with_nothing_to_count_asks_for_nothing(self):
        self.assertEqual(craft_rhythm.reagents_to_count("Og", {}), set())


class TheOreEntryTheForgeChangeLands(unittest.TestCase):
    """infra#3747 wrote down exactly one deferred entry and this is it.

    Its words: "the ORE that feeds it deliberately stays out of this table too
    - adding Copper Ore here would make Grog read as SHORT and send the whole
    family mining for something he still could not turn into a bar ... The ore
    entries belong in the same change that lands the forge aim, not before it."
    """

    def test_copper_ore_is_judged_now_that_a_bar_can_be_made(self):
        self.assertIn(2657, craft_rhythm.GATHERED)
        reagents = craft_rhythm.GATHERED[2657]
        self.assertEqual(
            [(r.entry, r.label, r.per_cast) for r in reagents],
            [(2770, "Copper Ore", 1)],
        )

    def test_the_bar_it_produces_is_still_not_judged(self):
        """GATHERED means "a gathering trip produces this". A Copper Bar comes
        off a cast, so it is an own-crafted intermediate exactly like Minor
        Healing Potion, and a character short of one is correctly UNJUDGED -
        `errand` hands them the smelt, roaming does not help."""
        for spell in (3922, 7430, 3923):  # the Copper Bar consumers
            with self.subTest(spell=spell):
                self.assertNotIn(spell, craft_rhythm.GATHERED)

    def test_a_miner_short_of_ore_now_reads_as_short_rather_than_unjudged(self):
        """The inversion, stated as a test. Before this change the smelt was
        not in RECIPES at all, so there was nothing to be short OF."""
        verdict = craft_rhythm.stand("Grug", 2657, {2770: 0})
        self.assertEqual(verdict.verdict, craft_rhythm.SHORT)
        self.assertEqual(verdict.thinnest, "Copper Ore")

    def test_one_mining_trip_serves_the_smelt_and_the_stone_eaters(self):
        """Rough Stone comes off the same copper veins, so the SHORT verdict
        this entry can now produce sends the family somewhere that restocks
        every miner's other recipe at the same time. That is what makes the
        entry nearly free rather than a new competing errand."""
        self.assertEqual(craft_rhythm.GATHERED[2657][0].entry, 2770)
        for stone_recipe in (2660, 3918):  # Grug's and Grog's own brackets
            self.assertEqual(craft_rhythm.GATHERED[stone_recipe][0].entry, 2835)


if __name__ == "__main__":
    unittest.main()

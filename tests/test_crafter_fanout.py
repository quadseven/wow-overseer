"""Recipes fan out: the master first, then the specialist, then the others.

The operator, 2026-10-17 (#1095): the family's master crafters get first
priority for the recipes of their trade; a specialized crafter comes next for
the recipes of its specialization (Dragonscale or Tribal leatherworking,
Armorsmith or Weaponsmith); then the other family and guild members, for the
duplicates. "First copy goes to the master, second copy goes to the guild for
others to learn."

Before this, every copy of one recipe in one pass went to the same taker: two
Purification Potions in one bag were both kept by the one alchemist, who can
only ever learn one of them. And a recipe that needs a specialization went to
the master whether or not the master holds that specialization, which the
`use` verb then refuses.

Every test here runs on fakes; none touches a database.
"""

import pathlib
import unittest

import crafters

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

LEATHER = 165
BLACKSMITHING = 164
# The specialization spells item_template.RequiredSpell gates on
# (tradespec.SPECS).
DRAGONSCALE = 10656
TRIBAL = 10662
ARMORSMITH = 9788


def person(name, skills, family=False, assigned=(), online=True, level=60):
    return crafters.Person(
        name, skills, level, family, online, assigned=frozenset(assigned)
    )


def recipe(guid, rank, spec=0, entry=15999, spell=19999, holder="Grug"):
    extra = {"spec": spec} if spec else {}
    return crafters.Recipe(
        holder,
        guid,
        entry,
        "Pattern: Test Leather Piece",
        LEATHER,
        rank,
        spell,
        "bags",
        **extra,
    )


# Bork is the family's master leatherworker (the roster assigns him the
# trade). Hide is a second family member with leatherworking. Scales and
# Tribe are guild crafters who each took one specialization.
BORK = person("Bork", {LEATHER: 200}, family=True, assigned={LEATHER})
HIDE = person("Hide", {LEATHER: 150}, family=True)
SCALES = person("Scales", {LEATHER: 230})
TRIBE = person("Tribe", {LEATHER: 240})
GRUG = person("Grug", {BLACKSMITHING: 40}, family=True, assigned={BLACKSMITHING})
PEOPLE = [GRUG, BORK, HIDE, SCALES, TRIBE]


def specs(*pairs):
    return crafters.known_from_rows(
        [{"name": name, "spell": spell} for name, spell in pairs]
    )


def route(recipes, known=None, people=PEOPLE, n=2):
    known = known or crafters.Known()
    reg = crafters.register(people, n)
    return crafters.route(recipes, reg, people, known, 25)


class TheFirstCopyGoesToTheMaster(unittest.TestCase):
    def test_one_copy_goes_to_the_master(self):
        pick = route([recipe(1, 190)])[1]
        self.assertEqual(("Bork", crafters.MASTER), (pick.taker, pick.seat))

    def test_the_second_copy_goes_down_the_line(self):
        picks = route([recipe(1, 190), recipe(2, 190)])
        self.assertEqual("Bork", picks[1].taker)
        self.assertNotEqual(
            "Bork", picks[2].taker, "the master can learn one copy, not two"
        )
        self.assertEqual("Scales", picks[2].taker)

    def test_every_copy_has_its_own_taker_until_nobody_needs_one(self):
        copies = [recipe(g, 140) for g in (1, 2, 3, 4, 5)]
        picks = route(copies)
        takers = [picks[g].taker for g in (1, 2, 3, 4)]
        self.assertEqual("Bork", takers[0])
        self.assertEqual(4, len(set(takers)), takers)
        self.assertEqual({"Bork", "Hide", "Scales", "Tribe"}, set(takers))
        self.assertEqual("", picks[5].taker, "a fifth copy nobody needs is sold")
        self.assertIn("nobody in the guild needs it", picks[5].why)

    def test_the_order_does_not_depend_on_the_list_order(self):
        forward = route([recipe(1, 190), recipe(2, 190)])
        backward = route([recipe(2, 190), recipe(1, 190)])
        self.assertEqual(
            {g: p.taker for g, p in forward.items()},
            {g: p.taker for g, p in backward.items()},
        )

    def test_copies_matched_by_entry_when_the_spell_is_unread(self):
        picks = route([recipe(1, 190, spell=0), recipe(2, 190, spell=0)])
        self.assertNotEqual(picks[1].taker, picks[2].taker)

    def test_two_different_recipes_can_both_go_to_the_master(self):
        picks = route([recipe(1, 190, spell=1), recipe(2, 190, entry=7, spell=2)])
        self.assertEqual(["Bork", "Bork"], [picks[1].taker, picks[2].taker])

    def test_a_holder_keeps_one_copy_and_passes_the_other(self):
        bork_holds = [recipe(1, 190, holder="Bork"), recipe(2, 190, holder="Bork")]
        picks = route(bork_holds)
        self.assertTrue(picks[1].kept)
        self.assertTrue(picks[2].routed)
        self.assertEqual("Scales", picks[2].taker)


class TheSpecialistIsNext(unittest.TestCase):
    def test_the_master_with_the_specialization_is_still_first(self):
        known = specs(("Bork", DRAGONSCALE), ("Scales", DRAGONSCALE))
        pick = route([recipe(1, 190, spec=DRAGONSCALE)], known)[1]
        self.assertEqual("Bork", pick.taker)

    def test_a_specialist_beats_a_master_without_it(self):
        known = specs(("Scales", DRAGONSCALE), ("Tribe", TRIBAL))
        pick = route([recipe(1, 190, spec=DRAGONSCALE)], known)[1]
        self.assertEqual("Scales", pick.taker)
        tribal = route([recipe(2, 190, spec=TRIBAL)], known)[2]
        self.assertEqual("Tribe", tribal.taker)

    def test_the_rival_specialist_is_not_preferred(self):
        known = specs(("Tribe", TRIBAL))
        pick = route([recipe(1, 190, spec=DRAGONSCALE)], known)[1]
        self.assertEqual(
            "Bork", pick.taker, "with no specialist, the order is the usual one"
        )
        self.assertEqual(crafters.LATER, pick.when)
        self.assertIn("without the specialization", pick.why)

    def test_a_second_copy_goes_to_a_second_specialist(self):
        known = specs(("Scales", DRAGONSCALE), ("Hide", DRAGONSCALE))
        picks = route(
            [recipe(1, 190, spec=DRAGONSCALE), recipe(2, 190, spec=DRAGONSCALE)],
            known,
        )
        self.assertEqual({"Scales", "Hide"}, {picks[1].taker, picks[2].taker})

    def test_the_specialization_is_read_off_the_row(self):
        got = crafters.recipe_from_row(
            {
                "holder": "Grug",
                "item_guid": 9,
                "entry": 15729,
                "name": "Pattern: Chimeric Gloves",
                "required_skill": LEATHER,
                "required_rank": 210,
                "recipe_spell": 19049,
                "required_spell": DRAGONSCALE,
            }
        )
        self.assertEqual(DRAGONSCALE, got.spec)
        plain = crafters.recipe_from_row(
            {
                "holder": "Grug",
                "item_guid": 9,
                "entry": 1,
                "required_skill": LEATHER,
                "required_rank": 1,
            }
        )
        self.assertEqual(0, plain.spec)


class TheBridgeReadsTheSpecialization(unittest.TestCase):
    def test_the_recipe_reads_carry_required_spell(self):
        for name in ("_CRAFTER_RECIPES_SQL", "_CRAFTER_GUILD_BANK_SQL"):
            start = BRIDGE.index(name + " = (")
            block = BRIDGE[start : BRIDGE.index("\n)\n", start)]
            self.assertIn("AS required_spell", block, name)

    def test_the_known_read_asks_for_the_specialization_spells(self):
        start = BRIDGE.index("def _crafter_plan(")
        body = BRIDGE[start : BRIDGE.index("\ndef ", start + 1)]
        self.assertIn("r.spec for r in recipes", body)


if __name__ == "__main__":
    unittest.main()

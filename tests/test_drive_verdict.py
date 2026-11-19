"""The bridge's gear verdict for a roster member agrees with the module's gear
drive (#2381).

The case is a synthetic fixture: Grug (the suite's usual fixture warrior), a
level 60 Protection warrior on the roster, wears Archaedic Stone of Strength (random property
219, +13 Strength) and Naglering (+10 Stamina, a defense spell and a thorns
spell), and carries Emperor's Seal of the Whale (random property 1039, +11
Spirit and +11 Stamina on top of its +9 Stamina) and a second Naglering. The
item plan's item-level verdict said wear the Seal, so it was carried for
ever; the module's drive (GearScore against the worse worn ring) keeps the
Stone. The rows below are fixture rows in the shape the bridge's scored-gear
read returns.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import armory  # noqa: E402
import equipscore  # noqa: E402
import itemplan_data  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BOOK = armory.ItemBook.load(str(HERE))

PROTECTION = "12666,12753,12764,12803,12804,12809,12818"
WARRIOR_SKILLS = "43,44,54,55,413,414,415,433,293"
STA, SPI, AGI = 7, 6, 3
UNIQUE = 0x80000


def ring(name, entry, guid, *, slot=None, level, req, stats=(), armor=0, **kw):
    row = dict(
        holder="Grug",
        equipment_slot=slot,
        item_guid=guid,
        entry=entry,
        name=name,
        quality=3,
        item_level=level,
        required_level=req,
        item_class=4,
        item_subclass=0,
        inventory_type=11,
        allowable_class=-1,
        allowable_race=-1,
        required_skill=0,
        required_skill_rank=0,
        required_spell=0,
        required_reputation=0,
        max_count=0,
        item_flags=kw.pop("item_flags", UNIQUE),
        armor=armor,
        block=0,
        dmg_min1=0,
        dmg_max1=0,
        delay=0,
        random_property_id=kw.pop("random_property_id", 0),
        enchantments=kw.pop("enchantments", ""),
    )
    for n, (kind, amount) in enumerate(stats, start=1):
        row["stat_type%d" % n] = kind
        row["stat_value%d" % n] = amount
    row.update(kw)
    return row


def enchants(at_seven=(), slots=12):
    """item_instance.enchantments with `at_seven` from the first property slot."""
    ids = [0] * slots
    for n, enchant in enumerate(at_seven):
        ids[7 + n] = enchant
    return " ".join("%d 0 0" % e for e in ids)


ARCHAEDIC = ring(
    "Archaedic Stone",
    11118,
    54193135,
    slot=10,
    level=47,
    req=40,
    armor=50,
    random_property_id=219,
    enchantments=enchants((410,)),
)
NAGLERING = ring(
    "Naglering",
    11669,
    92713952,
    slot=11,
    level=59,
    req=54,
    stats=((STA, 10),),
    armor=50,
    spellid_1=15438,
    spelltrigger_1=1,
    spellid_2=13383,
    spelltrigger_2=1,
)
SEAL = ring(
    "Emperor's Seal",
    11934,
    92000782,
    level=61,
    req=55,
    stats=((STA, 9),),
    item_flags=0,
    random_property_id=1039,
    enchantments=enchants((365, 366)),
)
SECOND_NAGLERING = dict(NAGLERING, equipment_slot=None, item_guid=94464682)

GRUG = dict(
    name="Grug",
    class_id=1,
    level=60,
    race=1,
    talent_spells=PROTECTION,
    target_tree="",
    skills=WARRIOR_SKILLS,
)


def grug():
    return equipscore.wearer_from_row(GRUG)


class TheDrivesScore(unittest.TestCase):
    """drive_score is GearScore: tank weights, half a point per item level."""

    def test_the_stone_is_scored_with_its_rolled_strength(self):
        score, floor = equipscore.drive_score(ARCHAEDIC, "tank", BOOK)
        self.assertAlmostEqual(score, 50 + 13 * 1.5 + 47 * 0.5)
        self.assertFalse(floor)

    def test_naglerings_thorns_leave_it_a_floor(self):
        score, floor = equipscore.drive_score(NAGLERING, "tank", BOOK)
        self.assertAlmostEqual(score, 50 + 10 * 2.0 + 8 * 3.0 + 59 * 0.5)
        self.assertTrue(floor)

    def test_the_seal_is_scored_with_the_whale(self):
        score, floor = equipscore.drive_score(SEAL, "tank", BOOK)
        self.assertAlmostEqual(score, (9 + 11) * 2.0 + 61 * 0.5)
        self.assertFalse(floor)

    def test_an_unread_random_property_is_a_floor(self):
        self.assertTrue(equipscore.drive_score(SEAL, "tank", None)[1])

    def test_an_unknown_role_has_no_opinion(self):
        self.assertEqual(equipscore.drive_score(SEAL, "unknown", BOOK), (0.0, True))


class GrugsSeal(unittest.TestCase):
    def test_the_drive_keeps_the_stone_over_the_seal(self):
        verdict, why = equipscore.drive_verdict(
            SEAL, grug(), [ARCHAEDIC, NAGLERING], BOOK
        )
        self.assertEqual(verdict, equipscore.DRIVE_KEEP, why)

    def test_a_second_unique_naglering_is_not_worn(self):
        verdict, _why = equipscore.drive_verdict(
            SECOND_NAGLERING, grug(), [ARCHAEDIC, NAGLERING], BOOK
        )
        self.assertEqual(verdict, equipscore.DRIVE_REFUSED)

    def test_an_empty_finger_takes_the_seal(self):
        verdict, _why = equipscore.drive_verdict(SEAL, grug(), [NAGLERING], BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_WEAR)

    def test_a_worn_floor_cannot_be_proved_beaten(self):
        lone = dict(NAGLERING, equipment_slot=10)
        both = [lone, dict(NAGLERING, equipment_slot=11, entry=1, item_flags=0)]
        verdict, _why = equipscore.drive_verdict(SEAL, grug(), both, BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_UNDECIDED)

    def test_a_trinket_is_worn_once(self):
        # mod-overseer: the drive refuses a second copy of a worn trinket
        # (wow-overseer#2358); a pair of the same ring stays legitimate.
        heart = ring(
            "Heart of Noxxion",
            17744,
            3,
            slot=12,
            level=51,
            req=45,
            stats=((STA, 10),),
            item_flags=0,
            inventory_type=12,
        )
        copy = dict(heart, equipment_slot=None, item_guid=4)
        verdict, why = equipscore.drive_verdict(copy, grug(), [heart], BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_REFUSED, why)
        self.assertIn("trinket", why)

    def test_a_different_trinket_is_still_worn(self):
        heart = ring(
            "Heart of Noxxion",
            17744,
            3,
            slot=12,
            level=51,
            req=45,
            stats=((STA, 10),),
            item_flags=0,
            inventory_type=12,
        )
        other = ring(
            "Other Charm",
            17745,
            5,
            level=51,
            req=45,
            stats=((STA, 10),),
            item_flags=0,
            inventory_type=12,
        )
        verdict, why = equipscore.drive_verdict(other, grug(), [heart], BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_WEAR, why)

    def test_a_pair_of_the_same_ring_is_still_allowed(self):
        band = ring(
            "Plain Band",
            17746,
            6,
            slot=10,
            level=51,
            req=45,
            stats=((STA, 10),),
            item_flags=0,
        )
        copy = dict(band, equipment_slot=None, item_guid=7)
        verdict, why = equipscore.drive_verdict(copy, grug(), [band], BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_WEAR, why)

    def test_a_clearly_better_piece_beats_a_worn_floor(self):
        # The module credits a worn floor with half again for what is unread
        # (mod-overseer#221, abe76676), so a piece that clears that is worn.
        lone = dict(NAGLERING, equipment_slot=10)
        both = [lone, dict(NAGLERING, equipment_slot=11, entry=1, item_flags=0)]
        big = ring(
            "Big Band", 99001, 1, level=60, req=55, stats=((STA, 100),), item_flags=0
        )
        verdict, why = equipscore.drive_verdict(big, grug(), both, BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_WEAR, why)

    def test_a_piece_under_the_credited_floor_stays_undecided(self):
        lone = dict(NAGLERING, equipment_slot=10)
        both = [lone, dict(NAGLERING, equipment_slot=11, entry=1, item_flags=0)]
        small = ring(
            "Small Band", 99002, 2, level=60, req=55, stats=((STA, 40),), item_flags=0
        )
        verdict, why = equipscore.drive_verdict(small, grug(), both, BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_UNDECIDED, why)

    def test_drive_verdicts_reads_the_pass_rows(self):
        rows = [ARCHAEDIC, NAGLERING, SEAL, SECOND_NAGLERING]
        verdicts = equipscore.drive_verdicts([GRUG], rows, ["Grug"], BOOK)
        self.assertEqual(
            verdicts,
            {
                "Grug": {
                    11934: equipscore.DRIVE_KEEP,
                    11669: equipscore.DRIVE_REFUSED,
                }
            },
        )


def trinket(name, entry, guid, *, slot=None, level, req, stats=(), **kw):
    return ring(
        name,
        entry,
        guid,
        slot=slot,
        level=level,
        req=req,
        stats=stats,
        item_flags=kw.pop("item_flags", 0),
        inventory_type=12,
        **kw,
    )


# The fixture pieces of mod-overseer's tests/test_gear_trinket_effect.cpp, as
# rows: the same item levels, the same stats, the same spells.
EXTRA_ATTACK_PROC, ATTACK_POWER_USE = 15600, 25891
TWENTY_ATTACK_POWER, CRIT_28 = 9331, 7598
SOME_OTHER_PROC = 15438  # Naglering's thorns: a proc with no row
ON_USE, ON_EQUIP = 0, 1
# Item level 58: 20 attack power and the extra-attack proc, both equip spells.
HAND = trinket(
    "Hand of Justice",
    11815,
    21,
    level=58,
    req=53,
    spellid_1=TWENTY_ATTACK_POWER,
    spelltrigger_1=ON_EQUIP,
    spellid_2=EXTRA_ATTACK_PROC,
    spelltrigger_2=ON_EQUIP,
)
UNPRICED_HAND = dict(HAND, spellid_2=SOME_OTHER_PROC)
# Item level 63: 28 critical strike rating as an equip spell, nothing else.
BREADTH = trinket(
    "Blackhand's Breadth",
    13965,
    22,
    level=63,
    req=58,
    spellid_1=CRIT_28,
    spelltrigger_1=ON_EQUIP,
)
# Item level 66: the attack power "Use:", nothing else.
EARTHSTRIKE = trinket(
    "Earthstrike",
    21180,
    23,
    level=66,
    req=60,
    spellid_1=ATTACK_POWER_USE,
    spelltrigger_1=ON_USE,
)


def as_role(role):
    return dataclasses.replace(grug(), role=role)


def in_both_slots(row):
    """One trinket worn in both trinket slots, the live fault of #2358."""
    return [
        dict(row, equipment_slot=12, item_guid=31),
        dict(row, equipment_slot=13, item_guid=32),
    ]


class AKnownTrinketEffectIsPricedForTheRoleItFits(unittest.TestCase):
    """#2358 box 2, and the module's numbers: GearKnownEffect in
    mod-overseer prices the same rows, and its test pins the same scores."""

    def test_the_table_is_the_modules_rows(self):
        swings = frozenset({"tank", "melee"})
        self.assertEqual(
            equipscore.DRIVE_KNOWN_EFFECTS,
            {
                15600: (swings, 38, 28),
                25891: (swings | {"ranged"}, 38, 46),
            },
        )

    def test_the_proc_is_priced_for_the_roles_that_swing(self):
        # 20 attack power, 28 for the proc, half a point per item level.
        self.assertEqual(equipscore.drive_score(HAND, "melee", BOOK), (77.0, False))
        # A tank prices attack power at 0.3: 6 + 8.4 + 29.
        score, floor = equipscore.drive_score(HAND, "tank", BOOK)
        self.assertAlmostEqual(score, 43.4)
        self.assertFalse(floor)

    def test_the_proc_is_nothing_to_a_role_it_does_not_fit(self):
        # A hunter has the 20 attack power and not the melee proc.
        self.assertEqual(equipscore.drive_score(HAND, "ranged", BOOK), (49.0, False))
        self.assertEqual(equipscore.drive_score(HAND, "healer", BOOK), (29.0, False))
        self.assertEqual(equipscore.drive_score(HAND, "caster", BOOK), (29.0, False))

    def test_the_use_is_priced_at_its_share_of_the_cooldown(self):
        # 280 for 20 sec of every 120 is 46, and 33 for the item level.
        self.assertEqual(
            equipscore.drive_score(EARTHSTRIKE, "ranged", BOOK), (79.0, False)
        )
        self.assertEqual(
            equipscore.drive_score(EARTHSTRIKE, "melee", BOOK), (79.0, False)
        )
        self.assertEqual(
            equipscore.drive_score(EARTHSTRIKE, "healer", BOOK), (33.0, False)
        )

    def test_a_proc_with_no_row_is_still_a_floor(self):
        self.assertEqual(
            equipscore.drive_score(UNPRICED_HAND, "melee", BOOK), (49.0, True)
        )

    def test_the_flat_trinket_scores_its_crit(self):
        # 28 crit at 1.5 and 31.5 for the item level.
        self.assertEqual(equipscore.drive_score(BREADTH, "melee", BOOK), (73.5, False))

    def test_a_role_fitting_effect_trinket_takes_the_second_slot_from_a_duplicate(
        self,
    ):
        worn = in_both_slots(BREADTH)
        copy = dict(BREADTH, item_guid=33)
        verdict, why = equipscore.drive_verdict(copy, as_role("melee"), worn, BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_REFUSED, why)
        verdict, why = equipscore.drive_verdict(HAND, as_role("melee"), worn, BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_WEAR, why)
        self.assertIn("77.0 against 73.5", why)

    def test_the_flat_trinket_does_not_take_it_back(self):
        worn = [
            dict(BREADTH, equipment_slot=12),
            dict(HAND, equipment_slot=13),
        ]
        spare = dict(BREADTH, entry=13966, item_guid=34)
        verdict, why = equipscore.drive_verdict(spare, as_role("melee"), worn, BOOK)
        self.assertEqual(verdict, equipscore.DRIVE_KEEP, why)

    def test_without_a_row_the_same_piece_is_left_undecided(self):
        verdict, why = equipscore.drive_verdict(
            UNPRICED_HAND, as_role("melee"), in_both_slots(BREADTH), BOOK
        )
        self.assertEqual(verdict, equipscore.DRIVE_UNDECIDED, why)

    def test_a_hunter_keeps_flat_crit_over_a_melee_proc(self):
        verdict, why = equipscore.drive_verdict(
            HAND, as_role("ranged"), in_both_slots(BREADTH), BOOK
        )
        self.assertEqual(verdict, equipscore.DRIVE_KEEP, why)

    def test_a_hunters_attack_power_use_takes_the_second_slot(self):
        verdict, why = equipscore.drive_verdict(
            EARTHSTRIKE, as_role("ranged"), in_both_slots(BREADTH), BOOK
        )
        self.assertEqual(verdict, equipscore.DRIVE_WEAR, why)

    def test_a_known_effect_keeps_a_resistance_piece_out_of_the_situational_set(
        self,
    ):
        warded = dict(HAND, spellid_1=0, fire_res=10)
        self.assertFalse(equipscore.resistance_only(warded, BOOK))


def bag_row(entry, level):
    return {
        "member": "Grug",
        "entry": entry,
        "inventory_type": 11,
        "item_level": level,
        "req_level": 55,
        "level": 60,
    }


WORN = {
    "Grug": {
        "finger 1": {"entry": 11118, "item_level": 47},
        "finger 2": {"entry": 11669, "item_level": 59},
    }
}


class TheItemPlanAsksTheDrive(unittest.TestCase):
    """For a member the drive judged, the item plan's R4 verdict is the
    drive's, so a declined piece is not KEEP_CARRY for ever."""

    def test_item_level_alone_calls_the_seal_wear(self):
        verdicts = itemplan_data.upgrade_verdicts(WORN, [bag_row(11934, 61)])
        self.assertEqual(verdicts, {("Grug", 11934): "wear"})

    def test_the_drive_declines_it_so_there_is_no_wear_verdict(self):
        drive = {"Grug": {11934: equipscore.DRIVE_KEEP}}
        verdicts = itemplan_data.upgrade_verdicts(
            WORN, [bag_row(11934, 61)], drive=drive
        )
        self.assertEqual(verdicts, {})

    def test_the_drive_says_wear(self):
        drive = {"Grug": {11934: equipscore.DRIVE_WEAR}}
        verdicts = itemplan_data.upgrade_verdicts(
            WORN, [bag_row(11934, 61)], drive=drive
        )
        self.assertEqual(verdicts, {("Grug", 11934): "wear"})

    def test_a_member_the_drive_did_not_judge_keeps_item_level(self):
        drive = {"Zug": {}}
        verdicts = itemplan_data.upgrade_verdicts(
            WORN, [bag_row(11934, 61)], drive=drive
        )
        self.assertEqual(verdicts, {("Grug", 11934): "wear"})


class TheBridgeWiring(unittest.TestCase):
    """bridge.py is read as source here: it imports discord and pymysql."""

    @classmethod
    def setUpClass(cls):
        cls.source = (HERE / "bridge.py").read_text(encoding="utf-8")

    def body(self, name):
        match = re.search(
            r"^(?:async )?def %s\(.*?(?=^(?:async )?def |\Z)" % name,
            self.source,
            re.S | re.M,
        )
        self.assertIsNotNone(match, name)
        return match.group(0)

    def test_the_item_plan_reads_the_drive_verdicts_for_the_roster(self):
        body = self.body("_itemplan_reads")
        self.assertIn("_drive_verdicts(", body)
        self.assertIn("drive_verdict=", body)

    def test_the_equip_log_counts_only_what_the_drive_will_wear(self):
        body = self.source[self.source.index("    async def _equip_upgrades(") :]
        body = body[: body.index("    async def _scored_equips(")]
        self.assertIn("_drive_verdicts,", body)
        self.assertIn("the module's gear drive declines", body)


if __name__ == "__main__":
    unittest.main()

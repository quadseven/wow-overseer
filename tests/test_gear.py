"""Gear hand-off tests (mod-overseer#14, infra#2813).

Pinned to the exact scenario the issue was raised against: a green Severing
Axe (a two-hander) beats a green one-hander on item level alone while being a
downgrade for a shield-wielding tank, because equipping it silently unslots
the shield. Everything here proves plan() gets the DECISION right for
synthetic inputs - it does not and cannot prove the SQL that will produce
those inputs against a live server (see gear.py's own module docstring).
"""

import unittest

import gear

WARRIOR = 1
PALADIN = 2
ROGUE = 4
MAGE = 8
PRIEST = 5

# AllowableClass bitmasks: bit (class_id - 1).
ALL_CLASSES = (1 << 11) - 1  # every class can use it (e.g. a trinket)
WARRIOR_ONLY = 1 << (WARRIOR - 1)
PLATE_MELEE = (1 << (WARRIOR - 1)) | (1 << (PALADIN - 1))


def sword(
    holder,
    guid,
    item_level,
    allowable_class=WARRIOR_ONLY,
    quality=3,
    required_level=1,
    inventory_type=21,
    soulbound=False,
):
    """A one-handed weapon (InventoryType 21 = one-hand)."""
    return gear.Holding(
        holder=holder,
        guid=guid,
        entry=guid,
        name="Twisted Sabre",
        quality=quality,
        item_level=item_level,
        required_level=required_level,
        allowable_class=allowable_class,
        inventory_type=inventory_type,
        item_class=gear.ITEM_CLASS_WEAPON,
        soulbound=soulbound,
    )


def two_hander(holder, guid, item_level, allowable_class=PLATE_MELEE):
    return gear.Holding(
        holder=holder,
        guid=guid,
        entry=guid,
        name="Severing Axe",
        quality=3,
        item_level=item_level,
        required_level=1,
        allowable_class=allowable_class,
        inventory_type=17,  # two-hand
        item_class=gear.ITEM_CLASS_WEAPON,
    )


def character(name, class_id, level=25, equipped=None):
    return gear.CharacterState(
        name=name, class_id=class_id, level=level, equipped=equipped or {}
    )


class ClassEligibility(unittest.TestCase):
    """The 0013 case, generalised: an item nobody can use is not the family's
    problem to solve by evaporating it - and here, is not a candidate to
    move to someone who ALSO cannot use it."""

    def test_mage_cannot_equip_a_sword(self):
        holding = sword("Ugga", 1, item_level=26, allowable_class=WARRIOR_ONLY)
        og = character("Og", MAGE)
        upgrade, reason = gear.is_upgrade_for(holding, og)
        self.assertFalse(upgrade)
        self.assertIn("cannot equip", reason)

    def test_warrior_can_equip_the_same_sword(self):
        holding = sword("Ugga", 1, item_level=26, allowable_class=WARRIOR_ONLY)
        grug = character("Grug", WARRIOR)
        upgrade, _ = gear.is_upgrade_for(holding, grug)
        self.assertTrue(upgrade)

    def test_usable_by_class_reads_the_bit_for_the_right_class(self):
        holding = sword("Ugga", 1, item_level=26, allowable_class=WARRIOR_ONLY)
        self.assertTrue(gear.usable_by_class(holding, WARRIOR))
        self.assertFalse(gear.usable_by_class(holding, MAGE))


class TheSeveringAxeTest(unittest.TestCase):
    """infra#2813: a green two-hander beats a green one-hander on item level
    alone while being a downgrade for a shield tank. Grug (warrior) is
    currently wielding a one-hand weapon AND a shield (something equipped in
    the off hand) - the two-hander must be refused for him even though its
    item level is higher, and even though his class can technically use it."""

    def test_two_hander_refused_for_a_character_with_a_shield_equipped(self):
        axe = two_hander("Ugga", 2, item_level=40)
        grug = character(
            "Grug",
            WARRIOR,
            equipped={
                gear._MAIN_HAND: 30,
                gear._OFF_HAND: 20,
            },
        )
        upgrade, reason = gear.is_upgrade_for(axe, grug)
        self.assertFalse(upgrade)
        self.assertIn("off-hand", reason)

    def test_two_hander_is_fine_for_a_character_with_no_off_hand_equipped(self):
        axe = two_hander("Ugga", 2, item_level=40)
        grog = character("Grog", PALADIN, equipped={gear._MAIN_HAND: 30})
        upgrade, _ = gear.is_upgrade_for(axe, grog)
        self.assertTrue(upgrade)

    def test_one_hander_is_never_blocked_by_the_off_hand_guard(self):
        blade = sword("Ugga", 3, item_level=35, allowable_class=PLATE_MELEE)
        grug = character(
            "Grug",
            WARRIOR,
            equipped={
                gear._MAIN_HAND: 20,
                gear._OFF_HAND: 20,
            },
        )
        upgrade, _ = gear.is_upgrade_for(blade, grug)
        self.assertTrue(upgrade)

    def test_plan_never_hands_the_axe_to_a_shield_tank(self):
        axe = two_hander("Ugga", 2, item_level=40)
        grug = character(
            "Grug",
            WARRIOR,
            equipped={
                gear._MAIN_HAND: 30,
                gear._OFF_HAND: 20,
            },
        )
        grog = character("Grog", PALADIN, equipped={gear._MAIN_HAND: 25})
        result = gear.plan([axe], [grug, grog, character("Ugga", PRIEST)])
        self.assertEqual(len(result.grants), 1)
        self.assertEqual(result.grants[0].taker, "Grog")


class UpgradeVsItemLevel(unittest.TestCase):
    def test_not_an_upgrade_over_a_higher_item_level_already_equipped(self):
        holding = sword("Ugga", 4, item_level=20, allowable_class=WARRIOR_ONLY)
        grug = character("Grug", WARRIOR, equipped={gear._MAIN_HAND: 30})
        upgrade, reason = gear.is_upgrade_for(holding, grug)
        self.assertFalse(upgrade)
        self.assertIn("not an upgrade", reason)

    def test_upgrade_over_a_lower_item_level_already_equipped(self):
        holding = sword("Ugga", 4, item_level=30, allowable_class=WARRIOR_ONLY)
        grug = character("Grug", WARRIOR, equipped={gear._MAIN_HAND: 20})
        upgrade, _ = gear.is_upgrade_for(holding, grug)
        self.assertTrue(upgrade)

    def test_upgrade_for_an_empty_slot(self):
        holding = sword("Ugga", 4, item_level=15, allowable_class=WARRIOR_ONLY)
        grug = character("Grug", WARRIOR, equipped={})
        upgrade, reason = gear.is_upgrade_for(holding, grug)
        self.assertTrue(upgrade)
        self.assertIn("empty", reason)

    def test_required_level_refuses_an_underlevelled_character(self):
        holding = sword(
            "Ugga", 4, item_level=15, allowable_class=WARRIOR_ONLY, required_level=30
        )
        grug = character("Grug", WARRIOR, level=21, equipped={})
        upgrade, reason = gear.is_upgrade_for(holding, grug)
        self.assertFalse(upgrade)
        self.assertIn("requires level", reason)


class QuestItemsAndEquippedItemsAreNeverConsidered(unittest.TestCase):
    """#14's own acceptance criterion. Equipped items never even reach this
    module - see the module docstring on why the BAGS-only fetch makes that
    true by construction, not by a special-case check here. Quest items and
    other non-gear item classes are refused explicitly."""

    def test_a_non_weapon_non_armor_item_class_is_never_a_candidate(self):
        quest_item = gear.Holding(
            holder="Ugga",
            guid=5,
            entry=5,
            name="Ancient Petrified Leaf",
            quality=1,
            item_level=1,
            required_level=1,
            allowable_class=ALL_CLASSES,
            inventory_type=0,
            item_class=12,  # ITEM_CLASS_QUEST
        )
        og = character("Og", MAGE)
        upgrade, reason = gear.is_upgrade_for(quest_item, og)
        self.assertFalse(upgrade)
        self.assertIn("not gear", reason)

    def test_soulbound_items_are_never_a_candidate(self):
        holding = sword(
            "Ugga", 6, item_level=26, allowable_class=WARRIOR_ONLY, soulbound=True
        )
        grug = character("Grug", WARRIOR)
        upgrade, reason = gear.is_upgrade_for(holding, grug)
        self.assertFalse(upgrade)
        self.assertIn("soulbound", reason)


class PlanRespectsTheHoldersOwnClaim(unittest.TestCase):
    """The rule that stops this from ever shuffling gear sideways: an item
    stays put if the character already holding it would call it an upgrade
    too, regardless of who else might benefit even more."""

    def test_holder_who_could_use_it_keeps_it(self):
        holding = sword("Grug", 7, item_level=30, allowable_class=WARRIOR_ONLY)
        grug = character("Grug", WARRIOR, equipped={gear._MAIN_HAND: 10})
        grog = character("Grog", PALADIN, equipped={gear._MAIN_HAND: 5})
        result = gear.plan([holding], [grug, grog])
        self.assertEqual(result.grants, ())

    def test_holder_who_cannot_use_it_gives_it_up(self):
        holding = sword("Ugga", 8, item_level=26, allowable_class=WARRIOR_ONLY)
        ugga = character("Ugga", PRIEST)
        grug = character("Grug", WARRIOR, equipped={gear._MAIN_HAND: 5})
        result = gear.plan([holding], [ugga, grug])
        self.assertEqual(len(result.grants), 1)
        self.assertEqual(result.grants[0].holder, "Ugga")
        self.assertEqual(result.grants[0].taker, "Grug")
        self.assertEqual(result.grants[0].command, "guid:8")


class PlanPicksTheBiggestBeneficiary(unittest.TestCase):
    def test_the_bigger_gain_wins_the_item(self):
        holding = sword("Ugga", 9, item_level=40, allowable_class=PLATE_MELEE)
        ugga = character("Ugga", PRIEST)
        # Grug gains 40-10=30, Grog gains 40-35=5: Grug should win it.
        grug = character("Grug", WARRIOR, equipped={gear._MAIN_HAND: 10})
        grog = character("Grog", PALADIN, equipped={gear._MAIN_HAND: 35})
        result = gear.plan([holding], [ugga, grug, grog])
        self.assertEqual(len(result.grants), 1)
        self.assertEqual(result.grants[0].taker, "Grug")

    def test_no_eligible_taker_produces_a_note_not_a_grant(self):
        holding = sword("Ugga", 10, item_level=26, allowable_class=WARRIOR_ONLY)
        ugga = character("Ugga", PRIEST)
        og = character("Og", MAGE)
        result = gear.plan([holding], [ugga, og])
        self.assertEqual(result.grants, ())
        self.assertEqual(len(result.notes), 1)
        self.assertIn("Ugga", result.notes[0])

    def test_plan_is_deterministic_and_sorted(self):
        one = sword("Ugga", 20, item_level=26, allowable_class=WARRIOR_ONLY)
        two = sword("Ugga", 11, item_level=26, allowable_class=WARRIOR_ONLY)
        grug = character("Grug", WARRIOR, equipped={})
        ugga = character("Ugga", PRIEST)
        first = gear.plan([one, two], [ugga, grug])
        second = gear.plan([one, two], [ugga, grug])
        self.assertEqual(first, second)
        self.assertEqual([g.guid for g in first.grants], [11, 20])


class GrantCommandAndSpeech(unittest.TestCase):
    def test_command_is_a_guid_not_an_entry(self):
        holding = sword("Ugga", 42, item_level=26, allowable_class=WARRIOR_ONLY)
        grug = character("Grug", WARRIOR)
        result = gear.plan([holding], [character("Ugga", PRIEST), grug])
        self.assertEqual(result.grants[0].command, "guid:42")

    def test_lines_reads_as_party_chat(self):
        holding = sword("Ugga", 42, item_level=26, allowable_class=WARRIOR_ONLY)
        grug = character("Grug", WARRIOR)
        result = gear.plan([holding], [character("Ugga", PRIEST), grug])
        lines = gear.lines(result)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("Ugga: "))
        self.assertIn("Grug", lines[0])


if __name__ == "__main__":
    unittest.main()

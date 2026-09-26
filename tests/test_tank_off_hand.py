"""A tank's off hand holds a shield, and a lowered family grows back into its gear.

THE MEASUREMENT (dev realm, 2026-09-26). The operator lowered both families to
their natural levels. Grug, the Alliance head and Protection warrior who tanks,
went from 60 to 38; every shield he owned needed 39 to 58, and the core mailed
them to him. The gear hand-off then traded him Grog's Sorcerer Sphere (entry
9882: armour subclass 0, InventoryType 23, held in the off hand, item level 43,
required level 38) and the equip pass put it on, because an empty off hand
reads as item level 0 and `wearable_armor` abstains on subclass 0. He died four
times in thirteen minutes in Desolace to level 36 to 40 monsters.

The one shield Grug could wear at 38, Banded Shield (entry 9843, required
level 28), is soulbound to Grog and on Grog's arm, so the natural rules cannot
move it. Grog also carries Ravager's Shield (required level 39, not bound) and
Embossed Plate Shield and Brigade Defender (40), and the auction heuristic's
answer for Embossed Plate Shield was "nobody in the family would wear it, and
it can be listed".

Every character and item below is a real row off that realm.
"""

import dataclasses
import datetime
import unittest

import bag_pressure
import bankpolicy
import gear

WARRIOR, PALADIN, ROGUE, PRIEST, MAGE, DRUID = 1, 2, 4, 5, 8, 11
ANY = -1


def holding(**kw):
    base = dict(
        holder="Grog",
        guid=5743666,
        entry=9882,
        name="Sorcerer Sphere",
        quality=2,
        item_level=43,
        required_level=38,
        allowable_class=ANY,
        inventory_type=gear.INVTYPE_HOLDABLE,
        item_class=gear.ITEM_CLASS_ARMOR,
        item_subclass=gear.ARMOR_MISC,
    )
    base.update(kw)
    return gear.Holding(**base)


def shield(**kw):
    base = dict(
        guid=6333265,
        entry=14777,
        name="Ravager's Shield",
        item_level=44,
        required_level=39,
        inventory_type=gear.INVTYPE_SHIELD,
        item_subclass=gear.ARMOR_SHIELD,
    )
    base.update(kw)
    return holding(**base)


def grug(level=38, off_hand=0, kind=gear.OFF_HAND_NONE, role=gear.ROLE_TANK):
    equipped = {"main_hand": 43}
    if off_hand:
        equipped["off_hand"] = off_hand
    return gear.CharacterState(
        "Grug", WARRIOR, level, equipped, role=role, off_hand_kind=kind
    )


def grog(level=36, off_hand=33):
    return gear.CharacterState(
        "Grog",
        PALADIN,
        level,
        {"main_hand": 30, "off_hand": off_hand},
        role=gear.ROLE_DAMAGE,
        off_hand_kind=gear.OFF_HAND_SHIELD,
    )


def og():
    return gear.CharacterState("Og", MAGE, 35, {"main_hand": 30}, role="damage")


class ACasterOrbIsNeverAWarriorsOffHand(unittest.TestCase):
    def test_the_sorcerer_sphere_is_refused_to_the_tank(self):
        ok, why = gear.would_wear(holding(), grug())
        self.assertFalse(ok)
        self.assertIn("a Warrior has no use for one", why)

    def test_and_to_a_warrior_in_any_role(self):
        ok, _ = gear.would_wear(holding(), grug(role=gear.ROLE_DAMAGE))
        self.assertFalse(ok)
        ok, _ = gear.would_wear(holding(), grug(role=gear.ROLE_UNKNOWN))
        self.assertFalse(ok)

    def test_and_to_a_rogue(self):
        bork = gear.CharacterState("Bork", ROGUE, 35, {}, role="damage")
        self.assertFalse(gear.would_wear(holding(required_level=30), bork)[0])

    def test_a_shield_tank_of_a_caster_class_is_refused_too(self):
        paladin = gear.CharacterState("P", PALADIN, 40, {}, role=gear.ROLE_TANK)
        ok, why = gear.would_wear(holding(), paladin)
        self.assertFalse(ok)
        self.assertIn("a tank holds a shield in the off hand", why)

    def test_it_is_still_a_casters_and_a_bear_tanks(self):
        self.assertTrue(gear.would_wear(holding(required_level=30), og())[0])
        bear = gear.CharacterState("B", DRUID, 40, {}, role=gear.ROLE_TANK)
        self.assertTrue(gear.would_wear(holding(), bear)[0])

    def test_an_off_hand_weapon_is_not_a_shield_tanks(self):
        blade = holding(
            name="Blade",
            inventory_type=gear.INVTYPE_WEAPON_OFF_HAND,
            item_class=gear.ITEM_CLASS_WEAPON,
            item_subclass=gear.WEAPON_DAGGER,
        )
        self.assertFalse(gear.would_wear(blade, grug())[0])
        fury = grug(role=gear.ROLE_DAMAGE)
        self.assertTrue(gear.would_wear(blade, fury)[0])


class TheLiveHandOffNoLongerHappens(unittest.TestCase):
    """Grog holding the orb, Grug at 38 with an empty off hand: the plan that
    wrote trade row 281085 must not be written again."""

    def test_the_orb_goes_to_nobody_who_fights(self):
        family = [grug(), grog(), gear.CharacterState("Bork", ROGUE, 35, {})]
        plan = gear.plan([holding()], family)
        self.assertEqual((), plan.grants)
        self.assertEqual(gear.NOBODY, gear.claimant(holding(), family))

    def test_the_mage_takes_it_if_it_is_hers(self):
        family = [grug(), grog(), og()]
        plan = gear.plan([holding(required_level=30)], family)
        self.assertEqual(["Og"], [g.taker for g in plan.grants])

    def test_the_equip_pass_does_not_put_it_on_its_holder(self):
        grug_holds = holding(holder="Grug")
        self.assertEqual((), gear.equips([grug_holds], [grug()]))


class AShieldBeatsWhateverElseATankHolds(unittest.TestCase):
    def test_a_lower_shield_replaces_the_worn_orb(self):
        banded = shield(
            guid=1,
            entry=9843,
            name="Banded Shield",
            item_level=33,
            required_level=28,
        )
        tank = grug(off_hand=43, kind=gear.OFF_HAND_HELD)
        ok, why = gear.would_wear(banded, tank)
        self.assertTrue(ok)
        self.assertIn("a shield belongs there", why)
        self.assertEqual((33, why), gear.upgrade_gain(banded, tank))
        equip = gear.equips([dataclasses.replace(banded, holder="Grug")], [tank])
        self.assertEqual(["Banded Shield"], [e.name for e in equip])
        self.assertEqual(0, equip[0].worn_level)

    def test_between_two_shields_item_level_still_decides(self):
        tank = grug(level=40, off_hand=45, kind=gear.OFF_HAND_SHIELD)
        self.assertFalse(gear.would_wear(shield(), tank)[0])


class TheTankHasFirstCallOnAShield(unittest.TestCase):
    def test_grogs_ravagers_shield_goes_to_grug_at_39(self):
        family = [grug(level=39, off_hand=43, kind=gear.OFF_HAND_HELD), grog(level=39)]
        plan = gear.plan([shield()], family)
        self.assertEqual([("Grog", "Grug")], [(g.holder, g.taker) for g in plan.grants])
        self.assertEqual("Grug", gear.claimant(shield(), family))
        # And Grog's own equip pass leaves it for the tank.
        self.assertEqual((), gear.equips([shield()], family))

    def test_at_38_it_waits_for_his_level(self):
        family = [grug(off_hand=43, kind=gear.OFF_HAND_HELD), grog()]
        self.assertEqual((), gear.plan([shield()], family).grants)
        self.assertEqual("", gear.tank_claim(shield(), family))

    def test_a_soulbound_shield_never_moves(self):
        bound = shield(soulbound=True, item_level=33, required_level=28)
        family = [grug(off_hand=43, kind=gear.OFF_HAND_HELD), grog()]
        self.assertEqual("", gear.tank_claim(bound, family))
        self.assertEqual((), gear.plan([bound], family).grants)

    def test_a_tank_holding_a_shield_he_wears_keeps_it(self):
        tank_holds = shield(holder="Grug")
        other = gear.CharacterState("Zug", WARRIOR, 40, {}, role=gear.ROLE_TANK)
        self.assertEqual("", gear.tank_claim(tank_holds, [grug(level=39), other]))


class TheWornOffHandIsRead(unittest.TestCase):
    def test_characters_from_rows_reads_the_off_hand_kind(self):
        rows = [
            dict(
                name="Grug",
                class_id=WARRIOR,
                level=38,
                inventory_type=13,
                item_level=43,
            ),
            dict(
                name="Grug",
                class_id=WARRIOR,
                level=38,
                inventory_type=23,
                item_level=43,
            ),
            dict(
                name="Grog",
                class_id=PALADIN,
                level=36,
                inventory_type=14,
                item_level=33,
            ),
        ]
        got = {
            c.name: c.off_hand_kind
            for c in gear.characters_from_rows(rows, ["Grug", "Grog"])
        }
        self.assertEqual(
            {"Grug": gear.OFF_HAND_HELD, "Grog": gear.OFF_HAND_SHIELD}, got
        )


def equipped(name, class_id, spec_tab=None, tank_seat=None):
    row = dict(
        name=name, class_id=class_id, level=38, inventory_type=None, item_level=None
    )
    if spec_tab is not None:
        row["spec_tab"] = spec_tab
    if tank_seat is not None:
        row["tank_seat"] = tank_seat
    return row


class TheTreeAndTheSeatSayWhoTanks(unittest.TestCase):
    def roles(self, rows, names):
        return {c.name: c.role for c in bag_pressure.family_characters(rows, names)}

    def test_the_live_family_tanks_with_its_protection_warrior(self):
        rows = [
            equipped("Grug", WARRIOR, 2),
            equipped("Grog", PALADIN, 2),
            equipped("Ugga", PRIEST, 1),
        ]
        roles = self.roles(rows, ["Grug", "Grog", "Ugga"])
        self.assertEqual("tank", roles["Grug"])
        self.assertEqual("damage", roles["Grog"])

    def test_a_protection_paladin_tanks_over_an_arms_warrior(self):
        rows = [equipped("W", WARRIOR, 0), equipped("P", PALADIN, 1)]
        roles = self.roles(rows, ["W", "P"])
        self.assertEqual(("damage", "tank"), (roles["W"], roles["P"]))

    def test_a_feral_druid_tanks_only_in_a_tank_seat(self):
        loose = [equipped("D", DRUID, 1)]
        self.assertEqual(set(), bag_pressure.tree_tanks(loose, ["D"])[0])
        seated = [equipped("D", DRUID, 1, tank_seat=1), equipped("W", WARRIOR, 1)]
        roles = self.roles(seated, ["D", "W"])
        self.assertEqual(("tank", "damage"), (roles["D"], roles["W"]))

    def test_rows_without_either_fact_keep_the_packing(self):
        rows = [equipped("W", WARRIOR), equipped("P", PALADIN)]
        self.assertEqual("tank", self.roles(rows, ["W", "P"])["W"])


class ALevelChangeReopensEverySlot(unittest.TestCase):
    def test_attempts_before_the_change_do_not_count(self):
        t = datetime.datetime
        history = [
            dict(
                target_name="Grug", command="e Hitem:1:0", created_at=t(2026, 9, 26, 2)
            ),
            dict(
                target_name="Grug", command="e Hitem:1:0", created_at=t(2026, 9, 26, 4)
            ),
            dict(
                target_name="Grog", command="e Hitem:2:0", created_at=t(2026, 9, 26, 2)
            ),
        ]
        changed = {"Grug": t(2026, 9, 26, 3, 10)}
        kept = gear.since_level_change(history, changed)
        self.assertEqual(
            [("Grug", t(2026, 9, 26, 4)), ("Grog", t(2026, 9, 26, 2))],
            [(r["target_name"], r["created_at"]) for r in kept],
        )


class AboveLevelGearWaitsInItsOwnersBank(unittest.TestCase):
    def reach(self, wears=True, later=()):
        return bag_pressure.GearReach(
            bucket="off_hand",
            holder_role="damage",
            holder_class=PALADIN,
            holder_level=36,
            holder_wears=wears,
            later_wearers=tuple(later),
        )

    def test_grogs_uncommon_shields_are_kept_for_their_level(self):
        embossed = bankpolicy.Piece(
            holder="Grog",
            guid=6266760,
            entry=9935,
            name="Embossed Plate Shield",
            quality=2,
            item_class=bankpolicy.ARMOR,
            required_level=40,
            item_level=45,
            bound=False,
        )
        facts = bankpolicy.Facts(
            pieces=(embossed,),
            family=(bankpolicy.Keeper("Grog", PALADIN, 36, "damage"),),
            reach={6266760: self.reach(later=("Grug",))},
        )
        placed = bankpolicy.place(facts)[6266760]
        self.assertEqual(
            (bankpolicy.PERSONAL, bankpolicy.GROWS_INTO), (placed.to, placed.kind)
        )

    def test_a_banked_shield_the_tank_wears_now_is_claimed(self):
        """Ravager's Shield banked in Grog's bank, Grug at 39: claimed, so
        no rule keeps it banked and the bank pass takes it back out."""
        item_rows = [
            dict(
                holder="Grog",
                item_guid=6333265,
                entry=14777,
                name="Ravager's Shield",
                quality=2,
                item_level=44,
                required_level=39,
                allowable_class=ANY,
                inventory_type=14,
                item_class=4,
                item_subclass=6,
                instance_flags=0,
                bag=0,
                slot=40,
            )
        ]
        worn_rows = [
            dict(
                name="Grug",
                class_id=WARRIOR,
                level=39,
                inventory_type=23,
                item_level=43,
            ),
            dict(
                name="Grog",
                class_id=PALADIN,
                level=36,
                inventory_type=14,
                item_level=33,
            ),
        ]
        claimed = bankpolicy.claimed_from_rows(item_rows, worn_rows, ["Grug", "Grog"])
        self.assertIn(6333265, claimed)


if __name__ == "__main__":
    unittest.main()

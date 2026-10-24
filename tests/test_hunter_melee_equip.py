"""A hunter is never asked to wear, or walked to learn, a melee weapon (#830).

Measured on the dev realm: the bot's own `e` put on 0 of 11 melee weapons
asked of hunters over two days, though each held the skill line and the piece
was a clear upgrade. #831 taught the gear-score judge (equipscore) to refuse
them. Three other paths still reached the same command:

  - the weapon-skill planner (weaponskill.needs) walked a hunter to a weapon
    master to learn swords for a carried Gladius, then asked it to wear it;
  - the item-level judge (gear.equips), which decides for every member the
    gear-score judge cannot, picked the Gladius for an empty main hand;
  - a piece Jev chose (bag_pressure.jev_equips) became the same `e` row.

A hunter's ranged weapon is unchanged on every path.
"""

import types
import unittest

import bag_pressure
import equipscore
import weaponskill

HUNTER, WARRIOR = 3, 1
ANY_CLASS = -1
NAMES = ["Gnash", "Grug"]


def bag(name, entry, label, sub, inv, ilvl=20, rl=15):
    return {"name": name, "entry": entry, "label": label, "subclass": sub,
            "InventoryType": inv, "ItemLevel": ilvl, "RequiredLevel": rl,
            "AllowableClass": -1}  # fmt: skip


HUNTER_FACT = {
    "Gnash": {"class": "hunter", "level": 24, "equipped": {"ranged": 18},
              "skills": {"weapons": {2}}},
}  # fmt: skip


class TheWeaponMasterTrip(unittest.TestCase):
    def test_no_trip_to_learn_a_melee_weapon_for_a_hunter(self):
        rows = [
            bag("Gnash", 2489, "Gladius", 7, 13),  # one-handed sword
            bag("Gnash", 2207, "Stiletto", 15, 13),  # dagger
            bag("Gnash", 1, "Worn Battleaxe", 1, 17),  # two-handed axe
            bag("Gnash", 2, "Main Gauche", 15, 21),  # main-hand only
        ]
        self.assertEqual([], weaponskill.needs(HUNTER_FACT, rows))

    def test_a_hunter_still_learns_a_ranged_weapon(self):
        rows = [bag("Gnash", 3, "Hunting Rifle", 3, 26, ilvl=22)]
        got = [(n.name, n.skill, n.slot) for n in weaponskill.needs(HUNTER_FACT, rows)]
        self.assertEqual([("Gnash", 46, "ranged")], got)

    def test_a_warrior_still_learns_a_sword(self):
        facts = {"Grug": {"class": "warrior", "level": 24, "equipped": {},
                          "skills": {"weapons": {0}}}}  # fmt: skip
        rows = [bag("Grug", 2489, "Gladius", 7, 13)]
        self.assertEqual(["Grug"], [n.name for n in weaponskill.needs(facts, rows)])

    def test_the_judge_and_the_trip_share_one_rule(self):
        wearer = types.SimpleNamespace(class_id=HUNTER)
        sword = {"item_class": 2, "inventory_type": 13}
        self.assertTrue(equipscore._bot_refusal(sword, wearer))
        self.assertTrue(weaponskill.bot_wont_wear(HUNTER, 2, 13))
        self.assertFalse(weaponskill.bot_wont_wear(HUNTER, 2, 15))  # bow
        self.assertFalse(weaponskill.bot_wont_wear(WARRIOR, 2, 13))
        self.assertFalse(weaponskill.bot_wont_wear(HUNTER, 4, 5))  # armour


def worn(name, class_id, level, **slots):
    if not slots:
        return [dict(name=name, class_id=class_id, level=level,
                     inventory_type=None, item_level=None)]  # fmt: skip
    return [
        dict(name=name, class_id=class_id, level=level,
             inventory_type=int(inv.lstrip("i")), item_level=int(ilvl))
        for inv, ilvl in slots.items()
    ]  # fmt: skip


def weapon(**kw):
    base = dict(holder="Gnash", level=24, item_guid=9001, entry=2489, count=1,
                instance_flags=0, name="Gladius", quality=2, sell_price=500,
                required_level=15, bonding=2, item_class=2, item_subclass=7,
                item_level=20, allowable_class=ANY_CLASS, inventory_type=13)  # fmt: skip
    base.update(kw)
    return base


GNASH = worn("Gnash", HUNTER, 24, i15=18)
BOW = dict(item_guid=9002, entry=3, name="Hunting Rifle", item_subclass=3,
           inventory_type=26, item_level=24)  # fmt: skip


class TheItemLevelJudge(unittest.TestCase):
    def test_an_empty_main_hand_is_not_filled_with_a_melee_weapon(self):
        got = bag_pressure.holder_equips([weapon()], GNASH, NAMES)
        self.assertEqual((), got)

    def test_a_better_ranged_weapon_is_still_put_on(self):
        got = bag_pressure.holder_equips([weapon(**BOW)], GNASH, NAMES)
        self.assertEqual(["Hunting Rifle"], [e.name for e in got])

    def test_a_warrior_still_puts_on_the_sword(self):
        rows = [weapon(holder="Grug")]
        got = bag_pressure.holder_equips(rows, worn("Grug", WARRIOR, 24), NAMES)
        self.assertEqual(["Gladius"], [e.name for e in got])


class WhatJevChose(unittest.TestCase):
    def test_a_melee_weapon_jev_chose_for_a_hunter_is_not_asked_for(self):
        plan = types.SimpleNamespace(equip={9001: "Jev: more damage"}, no_equip=())
        got = bag_pressure.jev_equips((), [weapon()], GNASH, NAMES, plan)
        self.assertEqual((), got)

    def test_a_ranged_weapon_jev_chose_for_a_hunter_is(self):
        plan = types.SimpleNamespace(equip={9002: "Jev: more damage"}, no_equip=())
        got = bag_pressure.jev_equips((), [weapon(**BOW)], GNASH, NAMES, plan)
        self.assertEqual(["Hunting Rifle"], [e.name for e in got])


class TheCarriedPreFilter(unittest.TestCase):
    """weaponskill.may_need keeps the skill and bag reads to members who carry
    a weapon worth a trip; a hunter's melee weapon never is."""

    @staticmethod
    def _carried(sub, inv, rl=15):
        return types.SimpleNamespace(
            item_class=weaponskill.ITEM_CLASS_WEAPON,
            subclass=sub,
            inventory_type=inv,
            required_level=rl,
        )

    def test_a_hunter_carrying_only_a_melee_weapon_needs_no_trip(self):
        for inv in sorted(
            weaponskill.MELEE_INVENTORY_TYPES & set(weaponskill.WEAPON_SLOT)
        ):
            got = weaponskill.may_need(HUNTER, 24, [self._carried(7, inv)])
            self.assertFalse(got, inv)

    def test_a_hunter_carrying_a_ranged_weapon_may_need_one(self):
        self.assertTrue(weaponskill.may_need(HUNTER, 24, [self._carried(2, 15)]))

    def test_a_warrior_carrying_the_same_melee_weapon_may_need_one(self):
        self.assertTrue(weaponskill.may_need(WARRIOR, 24, [self._carried(7, 13)]))

    def test_a_melee_weapon_does_not_hide_a_ranged_one_in_the_same_bag(self):
        got = weaponskill.may_need(
            HUNTER, 24, [self._carried(7, 13), self._carried(2, 15)]
        )
        self.assertTrue(got)


if __name__ == "__main__":
    unittest.main()

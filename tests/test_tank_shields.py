"""A warrior or paladin who tanks carries and wears a shield (#550, after #549).

Live 2026-10-04: 7 of 35 warriors and paladins in the two guilds wore a shield,
3 more carried one in their bags and 25 had none. The guild's equip pass puts
on a carried shield for a member who tanks, and the gear step treats that
member's off hand as an empty slot and buys a shield with its own gold.
"""

import unittest

import bag_pressure
import guildjobs
import gearup
from test_guild_equip import carried, worn

WARRIOR, PALADIN, DRUID = 1, 2, 11
PROTECTION_TAB = {1: 2, 2: 1}  # raidroles.tree_tab of Protection per class


def _shield(**kw):
    return carried(
        item_guid=9100,
        entry=1204,
        name="Wall of the Dead",
        item_class=4,
        item_subclass=6,
        inventory_type=14,
        item_level=30,
        required_level=20,
        **kw,
    )


def _tank_rows(name, class_id, level=30, **slots):
    rows = worn(name, class_id, level, **slots)
    for row in rows:
        row["spec_tab"] = bag_pressure.raidroles.tree_tab(class_id, "Protection")
    return rows


class ATankPutsOnTheShieldItCarries(unittest.TestCase):
    def test_a_protection_warrior_wears_a_carried_shield(self):
        rows = _tank_rows("Wally", WARRIOR, i5=20)
        tanks = bag_pressure.shield_tanks(rows, ["Wally"])
        self.assertEqual({"Wally"}, tanks)
        got = bag_pressure.guild_equips(
            [_shield(holder="Wally")], rows, ["Wally"], [], tanks=tanks
        )
        self.assertEqual(["e Hitem:1204:0"], [e.command for e in got])

    def test_a_planned_tank_counts_before_it_has_spent_a_talent(self):
        rows = worn("Pally", PALADIN, 30, i5=20)
        rows[0]["target_tree"] = "Protection"
        self.assertEqual({"Pally"}, bag_pressure.shield_tanks(rows, ["Pally"]))

    def test_a_shield_over_a_worn_weapon_in_the_off_hand(self):
        # An off-hand weapon is never a tank's, so the shield replaces it.
        rows = _tank_rows("Wally", WARRIOR, i5=20, i22=25)
        got = bag_pressure.guild_equips(
            [_shield(holder="Wally")], rows, ["Wally"], [], tanks={"Wally"}
        )
        self.assertEqual(["e Hitem:1204:0"], [e.command for e in got])


class ANonTankIsUnaffected(unittest.TestCase):
    def test_a_warrior_of_another_tree_is_not_a_shield_tank(self):
        rows = worn("Axel", WARRIOR, 30, i5=20)
        rows[0]["spec_tab"] = bag_pressure.raidroles.tree_tab(WARRIOR, "Arms")
        rows[0]["target_tree"] = "Arms"
        self.assertEqual(set(), bag_pressure.shield_tanks(rows, ["Axel"]))

    def test_a_non_tank_warrior_is_planned_no_shield(self):
        warrior = _character(
            "warrior", False, {"offhand": dict(WORN_DAGGER, item_level=29)}
        )
        self.assertFalse(gearup.shield_short(warrior))
        self.assertEqual(
            (),
            gearup.plan_vendor_buys(
                {"A": warrior}, {"A": [SHIELD]}, replace_stale=True
            ),
        )

    def test_a_druid_tank_is_never_a_shield_tank(self):
        rows = worn("Bear", DRUID, 30, i5=20)
        rows[0]["tank_seat"] = 1
        self.assertEqual(set(), bag_pressure.shield_tanks(rows, ["Bear"]))
        druid = _character("druid", tank=True)
        self.assertFalse(gearup.shield_short(druid))


def _character(cls, tank, equipped=None):
    return {
        "class": cls,
        "level": 30,
        "purse": 100000,
        "shield_tank": tank,
        "equipped": equipped if equipped is not None else {},
        "skills": {"weapons": {0, 1, 4, 5, 7}},
    }


SHIELD = {
    "entry": 2200,
    "buyout": 900,
    "InventoryType": 14,
    "class": 4,
    "subclass": 6,
    "RequiredLevel": 20,
    "AllowableClass": -1,
    "ItemLevel": 28,
}
GREATSWORD = dict(SHIELD, entry=2201, InventoryType=17, subclass=8, **{"class": 2})
GREATSWORD["ItemLevel"] = 40
WORN_DAGGER = {"item_level": 20, "item_class": 2, "item_subclass": 15}


class ATankWithoutAShieldBuysOne(unittest.TestCase):
    def test_the_off_hand_counts_as_empty(self):
        warrior = _character("warrior", True, {"offhand": WORN_DAGGER})
        self.assertTrue(gearup.shield_short(warrior))
        buys = gearup.plan_vendor_buys(
            {"W": warrior}, {"W": [SHIELD]}, replace_stale=True
        )
        self.assertEqual(
            [("W", "offhand", 2200)], [(b.character, b.slot, b.entry) for b in buys]
        )

    def test_a_two_hander_does_not_block_the_shield_or_get_bought(self):
        paladin = _character("paladin", True)
        buys = gearup.plan_vendor_buys({"P": paladin}, {"P": [GREATSWORD, SHIELD]})
        self.assertEqual([2200], [b.entry for b in buys])

    def test_a_worn_or_carried_shield_buys_nothing(self):
        worn_shield = {"item_level": 25, "item_class": 4, "item_subclass": 6}
        self.assertFalse(
            gearup.shield_short(_character("warrior", True, {"offhand": worn_shield}))
        )
        carrying = dict(_character("warrior", True), shield_carried=True)
        self.assertFalse(gearup.shield_short(carrying))

    def test_it_uses_only_its_own_purse(self):
        broke = dict(_character("warrior", True), purse=100)
        self.assertEqual((), gearup.plan_vendor_buys({"W": broke}, {"W": [SHIELD]}))

    def test_the_guild_gear_step_walks_a_shieldless_tank_to_a_vendor(self):
        # Fully dressed otherwise: only the off hand is empty.
        slots = (
            "head chest legs feet hands wrist waist shoulder back neck finger1 "
            "finger2 trinket1 trinket2 ranged"
        ).split()
        equipped = {
            s: {"item_level": 30, "item_class": 4, "item_subclass": 1} for s in slots
        }
        equipped["mainhand"] = {"item_level": 30, "item_class": 2, "item_subclass": 7}
        member = guildjobs.Member(
            name="Wally",
            guild="Cave",
            role=guildjobs.RAIDER,
            level=30,
            class_id=1,
            online=True,
            map_id=0,
            x=0.0,
            y=0.0,
            money=100000,
            eligible=True,
        )
        row = dict(SHIELD, vendor=1001, vendor_name="Armorer", map_id=0, yards=40.0)
        tank = _character("warrior", True, equipped)
        step, why = guildjobs.gear_step(member, tank, [row], 600.0)
        self.assertEqual("", why)
        self.assertEqual("walk-to-vendor item:2200", step.walk.command.split(" cap")[0])
        # A member that already carries a shield is left to the equip drive.
        bag = guildjobs.Carried(guid=5, entry=1204, item_class=4, subclass=6)
        holder = guildjobs.Member(**dict(member.__dict__, carried=(bag,)))
        self.assertIsNone(guildjobs.gear_step(holder, tank, [row], 600.0)[0])
        # An unread bag is no bag, not a failure.
        unread = guildjobs.Member(**dict(member.__dict__, carried=None))
        self.assertIsNotNone(guildjobs.gear_step(unread, tank, [row], 600.0)[0])
        # And the same dressed warrior who does not tank is not sent.
        plain = _character("warrior", False, equipped)
        self.assertIsNone(guildjobs.gear_step(member, plain, [row], 600.0)[0])


if __name__ == "__main__":
    unittest.main()

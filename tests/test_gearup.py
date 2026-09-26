import unittest
from unittest import mock

import gearup


def item(inv, subclass=0, **kw):
    return {
        "id": kw.pop("id", 1),
        "entry": kw.pop("entry", 100),
        "class": kw.pop("item_class", 4),
        "subclass": subclass,
        "InventoryType": inv,
        "RequiredLevel": 1,
        "AllowableClass": 0,
        "ItemLevel": kw.pop("ilvl", 30),
        "buyout": kw.pop("price", 100),
        **kw,
    }


class GearupTests(unittest.TestCase):
    def test_campaign_yields_for_funded_gear_short_member(self):
        facts = {"T": {"equipped": {}, "purse": 20000}}
        self.assertTrue(gearup.campaign_hold(facts, False))

    def test_campaign_does_not_yield_when_gear_short_member_is_broke(self):
        facts = {"T": {"equipped": {}, "purse": 19999}}
        self.assertFalse(gearup.campaign_hold(facts, False))

    def test_campaign_finishes_run_before_yielding_for_gear(self):
        facts = {"T": {"equipped": {}, "purse": 20000}}
        self.assertFalse(gearup.campaign_hold(facts, True))

    def test_campaign_resume_ceiling_releases_gear_hold(self):
        facts = {"T": {"equipped": {}, "purse": 20000}}
        self.assertFalse(gearup.campaign_hold(facts, False, held_seconds=2700))

    def test_slot_mapping(self):
        self.assertEqual(("finger1", "finger2"), gearup.SLOT_TYPES[11])
        self.assertEqual(("mainhand",), gearup.SLOT_TYPES[21])
        self.assertEqual(("offhand",), gearup.SLOT_TYPES[23])

    def test_armor_rules_by_class_and_level(self):
        cloth, leather, mail, plate = (item(5, subclass=s) for s in (1, 2, 3, 4))
        # Cloth is for everyone, the case the first draft got wrong.
        self.assertTrue(gearup._allowed({"class": "mage", "level": 13}, cloth))
        self.assertTrue(gearup._allowed({"class": "priest", "level": 35}, cloth))
        self.assertTrue(gearup._allowed({"class": "rogue", "level": 35}, leather))
        self.assertFalse(gearup._allowed({"class": "mage", "level": 60}, leather))
        # Warriors and paladins wear mail from the start; hunters and shamans at 40.
        self.assertTrue(gearup._allowed({"class": "warrior", "level": 17}, mail))
        self.assertFalse(gearup._allowed({"class": "shaman", "level": 39}, mail))
        self.assertTrue(gearup._allowed({"class": "shaman", "level": 40}, mail))
        self.assertFalse(gearup._allowed({"class": "rogue", "level": 60}, mail))
        # Plate at 40, warriors and paladins only.
        self.assertFalse(gearup._allowed({"class": "warrior", "level": 39}, plate))
        self.assertTrue(gearup._allowed({"class": "paladin", "level": 40}, plate))

    def test_cosmetic_slots_are_not_counted_or_bought(self):
        self.assertNotIn(4, gearup.SLOT_TYPES)
        self.assertEqual(17, gearup.empty_gear_slots([]))
        self.assertEqual(16, gearup.empty_gear_slots([3, 18, 0]))

    def test_a_second_ring_is_bought_beside_a_worn_first(self):
        c = {"class": "mage", "level": 35, "purse": 10000, "equipped": {"finger1": 30}}
        ring = item(11, subclass=0, id=7, ilvl=30, price=100)
        self.assertEqual(
            ["finger2"], [b.slot for b in gearup.plan_buys({"T": c}, [ring])]
        )

    def test_weapon_requires_a_held_weapon_skill(self):
        weapon = item(13, subclass=15, item_class=2)
        self.assertFalse(gearup._allowed({"class": "rogue", "level": 35}, weapon))
        self.assertTrue(
            gearup._allowed(
                {"class": "rogue", "level": 35, "skills": {"weapons": {15}}}, weapon
            )
        )

    def test_tank_offhand_only_accepts_shield(self):
        c = {
            "class": "warrior",
            "level": 40,
            "purse": 1000,
            "tank": True,
            "equipped": {},
        }
        shield = item(14, subclass=6, item_class=4)
        holdable = item(23, subclass=0, item_class=4, id=2)
        weapon = item(22, subclass=0, item_class=2, id=3)
        self.assertEqual(
            ["offhand"],
            [b.slot for b in gearup.plan_buys({"T": c}, [shield, holdable, weapon])],
        )

    def test_budget_caps_and_best_listing_per_empty_slot(self):
        c = {"class": "mage", "level": 35, "purse": 1000, "equipped": {}}
        rows = [
            item(1, subclass=0, id=1, ilvl=20, price=201),
            item(1, subclass=0, id=2, ilvl=18, price=200),
            item(2, subclass=0, id=3, ilvl=17, price=100),
        ]
        buys = gearup.plan_buys({"T": c}, rows, repair_floor=100)
        self.assertEqual([2, 3], [b.listing_id for b in buys])
        self.assertLessEqual(sum(b.buyout for b in buys), 600)

    def test_expected_buy_assertion_fails_when_planner_is_stubbed_empty(self):
        character = {"class": "mage", "level": 35, "purse": 1000, "equipped": {}}
        with mock.patch.object(gearup, "plan_buys", return_value=()):
            with self.assertRaises(AssertionError):
                self.assertEqual(
                    1, len(gearup.plan_buys({"T": character}, [item(1, id=1)]))
                )


if __name__ == "__main__":
    unittest.main()

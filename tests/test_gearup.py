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
    def test_empty_mainhand_is_a_gear_gap_even_below_the_empty_slot_threshold(self):
        facts = {
            "Oz": {
                "equipped": {
                    "head": 34,
                    "neck": 22,
                    "shoulder": 30,
                    "chest": 37,
                    "waist": 22,
                    "legs": 32,
                    "feet": 33,
                    "wrist": 27,
                    "finger1": 36,
                    "finger2": 25,
                    "offhand": 38,
                },
                "purse": 50000,
            }
        }
        # Six slots are empty, below the configured threshold of seven; the
        # missing main hand alone must still make this an urgent gear gap.
        self.assertTrue(gearup.needs_gear_hold(facts["Oz"], empty_slots=7))
        self.assertTrue(gearup.campaign_hold(facts, False, empty_slots=7))

    def test_empty_mainhand_mail_item_funds_campaign_hold(self):
        facts = {
            "Oz": {
                "equipped": {"head": 34, "offhand": 38},
                "purse": 0,
                "mail_gear": 1,
            }
        }
        self.assertTrue(gearup.campaign_hold(facts, False))

    def test_equipped_mainhand_uses_the_existing_empty_slot_threshold(self):
        facts = {"T": {"equipped": {"mainhand": 30}, "purse": 20000}}
        self.assertFalse(gearup.needs_gear_hold(facts["T"], empty_slots=17))

    def test_campaign_yields_for_funded_gear_short_member(self):
        facts = {"T": {"equipped": {}, "purse": 20000}}
        self.assertTrue(gearup.campaign_hold(facts, False))

    def test_campaign_does_not_yield_when_gear_short_member_is_broke(self):
        facts = {"T": {"equipped": {}, "purse": 19999}}
        self.assertFalse(gearup.campaign_hold(facts, False))

    def test_campaign_yields_for_bought_gear_waiting_in_the_mail(self):
        """A buyer who spent its purse on gear is not broke: the gear is in its
        mailbox, and the hold is what gives the mail pass a town to collect it."""
        facts = {"T": {"equipped": {}, "purse": 0, "mail_gear": 3}}
        self.assertTrue(gearup.campaign_hold(facts, False))

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

    def test_two_hander_does_not_replace_a_stronger_offhand(self):
        mage = {
            "class": "mage",
            "level": 35,
            "purse": 100000,
            "skills": {"weapons": {10}},
            "equipped": {"offhand": 38},
        }
        staff = item(17, subclass=10, item_class=2, id=4, ilvl=24, price=1000)

        self.assertEqual((), gearup.plan_buys({"Og": mage}, [staff]))

    def test_two_hander_can_replace_an_offhand_when_ten_levels_better(self):
        mage = {
            "class": "mage",
            "level": 35,
            "purse": 100000,
            "skills": {"weapons": {10}},
            "equipped": {"offhand": 20},
        }
        staff = item(17, subclass=10, item_class=2, id=4, ilvl=30, price=1000)

        self.assertEqual(
            [("mainhand", 4)],
            [
                (buy.slot, buy.listing_id)
                for buy in gearup.plan_buys({"Og": mage}, [staff])
            ],
        )

    def test_one_hander_still_fills_empty_mainhand_beside_offhand(self):
        mage = {
            "class": "mage",
            "level": 35,
            "purse": 100000,
            "skills": {"weapons": {15}},
            "equipped": {"offhand": 38},
        }
        dagger = item(13, subclass=15, item_class=2, id=5, ilvl=30, price=1000)

        self.assertEqual(
            [("mainhand", 5)],
            [
                (buy.slot, buy.listing_id)
                for buy in gearup.plan_buys({"Og": mage}, [dagger])
            ],
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

    def test_two_members_never_plan_the_same_listing(self):
        """The dev realm, 2026-09-26: the paladin and the warrior planned the
        same eight auctions, the paladin's went first, and all eight of the
        warrior's came back `auction not found`."""
        plate = {"class": "paladin", "level": 36, "purse": 100000, "equipped": {}}
        warrior = {"class": "warrior", "level": 38, "purse": 500000, "equipped": {}}
        rows = [
            item(5, subclass=3, id=1, ilvl=39, price=1000),
            item(5, subclass=3, id=2, ilvl=30, price=900),
        ]
        buys = gearup.plan_buys({"Grog": plate, "Grug": warrior}, rows)
        self.assertEqual(
            [("Grog", 1), ("Grug", 2)], [(b.character, b.listing_id) for b in buys]
        )

    def test_a_member_is_left_short_rather_than_given_a_taken_listing(self):
        first = {"class": "mage", "level": 35, "purse": 100000, "equipped": {}}
        second = {"class": "mage", "level": 35, "purse": 100000, "equipped": {}}
        buys = gearup.plan_buys({"A": first, "B": second}, [item(1, id=7, price=10)])
        self.assertEqual([("A", 7)], [(b.character, b.listing_id) for b in buys])

    def test_vendor_fills_empty_slots_only(self):
        """A level 35 mage in five of seventeen slots, at an armour merchant."""
        mage = {
            "class": "mage",
            "level": 35,
            "purse": 100000,
            "equipped": {"chest": 16, "back": 13},
        }
        stock = [
            item(5, subclass=1, entry=201, ilvl=35, price=900),
            item(10, subclass=1, entry=202, ilvl=33, price=500),
            item(8, subclass=1, entry=203, ilvl=33, price=500),
        ]
        buys = gearup.plan_vendor_buys({"Og": mage}, {"Og": stock})
        self.assertEqual(
            [("hands", 202), ("feet", 203)], [(b.slot, b.entry) for b in buys]
        )
        self.assertEqual("entry:202 count:1 max:500", gearup.vendor_command(buys[0]))

    def test_vendor_keeps_class_and_budget_rules(self):
        mage = {"class": "mage", "level": 35, "purse": 1000, "equipped": {}}
        stock = [
            item(7, subclass=3, entry=301, ilvl=35, price=100),  # mail: not a mage's
            item(7, subclass=1, entry=302, ilvl=35, price=900),  # over 20% of purse
            item(7, subclass=1, entry=303, ilvl=30, price=150),
        ]
        buys = gearup.plan_vendor_buys({"Og": mage}, {"Og": stock})
        self.assertEqual([303], [b.entry for b in buys])

    def test_vendor_buys_nothing_for_a_member_with_no_vendor(self):
        mage = {"class": "mage", "level": 35, "purse": 100000, "equipped": {}}
        self.assertEqual((), gearup.plan_vendor_buys({"Og": mage}, {}))

    def _stock(self, vendor, yards, *items, map_id=0, name="Armorer"):
        return [
            dict(it, vendor=vendor, vendor_name=name, map_id=map_id, yards=yards)
            for it in items
        ]

    def test_vendor_trip_picks_the_nearest_counter_that_sells_a_short_member_gear(self):
        """The dev realm, 2026-09-27: no vendor buy in half an hour, because
        nothing walked a gear-short member to a counter."""
        mage = {"class": "mage", "level": 35, "purse": 100000, "equipped": {}}
        cloth = item(10, subclass=1, entry=202, ilvl=33, price=500)
        mail = item(10, subclass=3, entry=203, ilvl=33, price=500)
        rows = (
            self._stock(7, 40.0, mail)  # nearer, but nothing a mage wears
            + self._stock(9, 120.0, cloth)
            + self._stock(11, 300.0, cloth)
        )
        trip = gearup.vendor_trip({"Og": mage}, rows, map_id=0)
        self.assertEqual((9, ("Og",), False), (trip.vendor, trip.buyers, trip.here))

    def test_vendor_trip_needs_enough_empty_slots(self):
        worn = {s: 30 for s in list(gearup._SLOT_NUMBERS)[:17] if s not in ("shirt",)}
        mage = {"class": "mage", "level": 35, "purse": 100000, "equipped": worn}
        rows = self._stock(9, 50.0, item(10, subclass=1, entry=202, price=500))
        trip = gearup.vendor_trip({"Og": mage}, rows, map_id=0)
        self.assertEqual(0, trip.vendor)
        self.assertIn("empty slots", trip.why_not)

    def test_vendor_trip_stays_on_the_leaders_map_and_inside_the_cap(self):
        mage = {"class": "mage", "level": 35, "purse": 100000, "equipped": {}}
        cloth = item(10, subclass=1, entry=202, price=500)
        rows = self._stock(9, 50.0, cloth, map_id=1) + self._stock(11, 900.0, cloth)
        self.assertEqual(0, gearup.vendor_trip({"Og": mage}, rows, map_id=0).vendor)

    def test_vendor_trip_needs_gold_the_member_earned(self):
        broke = {"class": "mage", "level": 35, "purse": 100, "equipped": {}}
        rows = self._stock(9, 50.0, item(10, subclass=1, entry=202, price=500))
        self.assertEqual(0, gearup.vendor_trip({"Og": broke}, rows, map_id=0).vendor)

    def test_standing_at_the_counter_is_here(self):
        mage = {"class": "mage", "level": 35, "purse": 100000, "equipped": {}}
        rows = self._stock(9, 4.0, item(10, subclass=1, entry=202, price=500))
        self.assertTrue(gearup.vendor_trip({"Og": mage}, rows, map_id=0).here)

    def test_expected_buy_assertion_fails_when_planner_is_stubbed_empty(self):
        character = {"class": "mage", "level": 35, "purse": 1000, "equipped": {}}
        with mock.patch.object(gearup, "plan_buys", return_value=()):
            with self.assertRaises(AssertionError):
                self.assertEqual(
                    1, len(gearup.plan_buys({"T": character}, [item(1, id=1)]))
                )


if __name__ == "__main__":
    unittest.main()

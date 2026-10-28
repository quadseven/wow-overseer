"""A guild member with Apprentice Riding and no mount buys one (#779).

Read on the dev realm on 2026-10-10: 94 of the 97 members of the two family
guilds at level 20 or above had no Riding skill, and nothing walked a member to
a mount vendor once it had one. Grug at 43 and Og at 38 walked with 45 and 35
gold. On this world every racial mount sells for 1 gold (item_template
BuyPrice 10000) and needs Riding 75.

The examples: Grug, a level 43 human warrior, and Bonk, a level 25 Draenei.
"""

import unittest

import guildjobs
import mountbuy
import purse

# Katie Hunter's stock (Elwynn Forest, map 0): three apprentice horses and an
# epic one, as the bridge reads npc_vendor and item_template.
KATIE = 384
CHESTNUT = mountbuy.Offer(KATIE, 5656, 10000, 75, 0, "Reins of the Brown Horse")
PINTO = mountbuy.Offer(KATIE, 2414, 10000, 75, 0, "Reins of the Pinto")
DEAR = mountbuy.Offer(KATIE, 5655, 12000, 75, 0, "Reins of the Chestnut Mare")
SWIFT = mountbuy.Offer(KATIE, 18776, 1000000, 150, 0, "Swift Palomino")
# Torallius the Pack Handler's elekk (Azuremyst Isle, map 530).
ELEKK = mountbuy.Offer(17584, 28481, 10000, 75, 530, "Brown Elekk")
STOCK = (SWIFT, DEAR, CHESTNUT, PINTO, ELEKK)

RIDES = (75, 75)
NONE = (0, 0)


def decide(**over):
    args = dict(
        name="Grug",
        level=43,
        class_id=1,
        race=1,
        riding=RIDES,
        money=450000,
        reserve=0,
        map_id=0,
        carried=(),
        facts=mountbuy.Facts(False, STOCK),
    )
    args.update(over)
    return mountbuy.decide(**args)


class WhoWantsAMount(unittest.TestCase):
    def test_a_rider_with_gold_and_no_mount_buys_the_cheapest_its_race_sells(self):
        d = decide()
        self.assertEqual(mountbuy.BUY, d.kind)
        # 1g each: the lower entry of the two cheapest, never the 1g 20s mare
        # or the swift one its Riding 75 cannot use.
        self.assertEqual(PINTO, d.offer)

    def test_a_member_without_riding_wants_no_mount(self):
        self.assertEqual("", decide(riding=NONE).kind)

    def test_a_member_under_twenty_wants_no_mount(self):
        self.assertEqual("", decide(level=19).kind)

    def test_a_member_that_knows_a_mount_buys_none(self):
        d = decide(facts=mountbuy.Facts(True, STOCK))
        self.assertEqual(("", None, ""), (d.kind, d.offer, d.why))

    def test_paladins_and_warlocks_learn_theirs_from_the_class_trainer(self):
        self.assertEqual("", decide(class_id=2).kind)
        self.assertEqual("", decide(class_id=9).kind)

    def test_its_own_race_only(self):
        d = decide(name="Bonk", race=11, map_id=530)
        self.assertEqual(ELEKK, d.offer)
        self.assertEqual(mountbuy.BUY, d.kind)


class WhatItCanAfford(unittest.TestCase):
    def test_the_class_spell_reserve_comes_first(self):
        d = decide(money=30000, reserve=25000)
        self.assertEqual("", d.kind)
        self.assertIn(
            "Grug saves for a mount (1g, after 2g 50s kept for its class "
            "spells; it holds 3g)",
            d.why,
        )

    def test_the_purse_exactly_covering_both_buys(self):
        self.assertEqual(mountbuy.BUY, decide(money=35000, reserve=25000).kind)


class WhereTheVendorIs(unittest.TestCase):
    def test_a_vendor_on_another_map_is_a_note_not_a_walk(self):
        d = decide(map_id=1)
        self.assertEqual("", d.kind)
        self.assertIn("stands on another map", d.why)

    def test_a_race_with_no_known_vendor_says_so(self):
        self.assertIn("no mount vendor is known", decide(race=99).why)

    def test_a_vendor_selling_nothing_it_can_ride_says_so(self):
        d = decide(facts=mountbuy.Facts(False, (SWIFT,)))
        self.assertIn("sells nothing its Riding 75 can ride", d.why)

    def test_every_race_vendor_is_one_creature(self):
        self.assertEqual(
            len(mountbuy.MOUNT_VENDORS), len(set(mountbuy.MOUNT_VENDORS.values()))
        )


class ACarriedMount(unittest.TestCase):
    def test_a_carried_mount_item_is_used_not_bought_again(self):
        d = decide(carried=((5656, 15, 5),), money=0)
        self.assertEqual(mountbuy.USE, d.kind)
        self.assertEqual(5656, d.offer.entry)

    def test_a_carried_pet_is_no_mount(self):
        # A companion pet is item class 15 subclass 2.
        self.assertEqual(mountbuy.BUY, decide(carried=((8485, 15, 2),)).kind)


class TheRow(unittest.TestCase):
    def test_offer_from_a_stock_row(self):
        row = {
            "vendor": 384,
            "entry": 2414,
            "price": 10000,
            "rank": 75,
            "map_id": 0,
            "name": "Reins of the Pinto",
        }
        self.assertEqual(PINTO, mountbuy.offer_from_row(row))


def grug(**over):
    base = dict(
        name="Grug",
        guild="Cave",
        role=guildjobs.RAIDER,
        level=43,
        class_id=1,
        race=1,
        online=True,
        map_id=0,
        x=-9460.0,
        y=62.0,
        money=450000,
        eligible=True,
        skills={purse.RIDING_SKILL: RIDES},
    )
    base.update(over)
    m = guildjobs.Member(**base)
    return guildjobs.replace(
        m, purse=purse.order(m.name, m.level, m.money, 0, 0, RIDES[1])
    )


class TheMountWalk(unittest.TestCase):
    FACTS = mountbuy.Facts(False, STOCK)

    def test_the_walk_buys_the_mount_and_uses_it(self):
        step, note = guildjobs.mount_step(grug(), self.FACTS, (), 100)
        self.assertEqual("", note)
        self.assertEqual(mountbuy.ACTION, step.action)
        self.assertEqual("buy", step.walk.kind)
        self.assertTrue(step.walk.command.startswith("walk-to-vendor item:2414"))
        self.assertEqual(
            [("buy", "entry:2414 count:1 max:10000"), ("cast", "use entry:2414")],
            [(r.kind, r.command) for r in step.rows],
        )
        self.assertIn("Grug walks to its race's mount vendor to buy", step.said)

    def test_a_carried_mount_is_only_used(self):
        held = guildjobs.Carried(9001, 2414, 1, 15, 5, name="Reins of the Pinto")
        step, _ = guildjobs.mount_step(grug(carried=(held,)), self.FACTS, (), 100)
        self.assertIsNone(step.walk)
        self.assertEqual(["use entry:2414"], [r.command for r in step.rows])

    def test_the_class_spell_reserve_holds_the_mount(self):
        m = grug(money=12000)
        m = guildjobs.replace(
            m, purse=purse.order(m.name, m.level, m.money, 5000, 2, RIDES[1])
        )
        step, note = guildjobs.mount_step(m, self.FACTS, (), 100)
        self.assertIsNone(step)
        self.assertIn("saves for a mount", note)

    def test_not_while_fighting_or_cooling(self):
        step, _ = guildjobs.mount_step(grug(in_combat=True), self.FACTS, (), 100)
        self.assertIsNone(step)
        recent = (guildjobs.Recent("Grug", mountbuy.ACTION, 30),)
        step, _ = guildjobs.mount_step(grug(), self.FACTS, recent, 100)
        self.assertIsNone(step)

    def test_an_unread_member_takes_no_step(self):
        self.assertEqual((None, ""), guildjobs.mount_step(grug(), None, (), 100))

    def test_the_upkeep_rungs_reach_the_mount_after_riding(self):
        """A member with riding and no mount gets the mount walk from the
        member step itself, not only from mount_step."""
        found, _, _ = guildjobs._upkeep_first(
            grug(), None, None, None, None, (), 100, "", None, self.FACTS
        )
        self.assertIsNotNone(found)
        self.assertEqual(mountbuy.ACTION, found[0].action)


def refused_buy(age=30, row_id=1275201):
    """The mount buy row the module refused for full bags (#1593)."""
    return guildjobs.Recent(
        "Grug",
        mountbuy.ACTION,
        age,
        status="failed",
        command="entry:2414 count:1 max:10000",
        result='{"outcome":"refused","reason":"bags cannot take the item",'
        '"inventory_result":50}',
        refusal="bags cannot take the item",
        row_id=row_id,
    )


class FullBagsMakeRoomFirst(unittest.TestCase):
    """Read on the dev realm on 2026-10-27 (#1593): every one of the 9 mount
    buys that reached the vendor came back "bags cannot take the item", and the
    same walk was aimed again (Crag three times). The walk is no longer aimed
    at a member with no free bag slot."""

    FACTS = mountbuy.Facts(False, STOCK)
    JUNK = guildjobs.Carried(guid=11, entry=900, count=1, quality=0, sell_price=50)

    def test_full_bags_make_room_before_the_walk(self):
        m = grug(free_slots=0, bag_slots=16, carried=(self.JUNK,))
        step, note = guildjobs.mount_step(m, self.FACTS, (), 100)
        self.assertEqual("", note)
        self.assertEqual(guildjobs.ROOM_ACTION, step.action)
        self.assertEqual(["guid:11"], [r.command for r in step.rows])
        self.assertNotIn("item:2414", step.walk.command)
        self.assertIn("Reins of the Pinto", step.said)

    def test_full_bags_with_nothing_to_part_with_hold_the_walk(self):
        m = grug(free_slots=0, bag_slots=16)
        step, note = guildjobs.mount_step(m, self.FACTS, (), 100)
        self.assertIsNone(step)
        self.assertIn("holds its mount walk", note)

    def test_a_cooling_room_step_holds_the_walk(self):
        m = grug(free_slots=0, bag_slots=16, carried=(self.JUNK,))
        recent = (guildjobs.Recent("Grug", guildjobs.ROOM_ACTION, 5),)
        step, note = guildjobs.mount_step(m, self.FACTS, recent, 100)
        self.assertIsNone(step)
        self.assertIn("until a bag slot is free", note)

    def test_a_free_slot_lets_the_walk_go(self):
        m = grug(free_slots=1, bag_slots=16)
        step, _ = guildjobs.mount_step(m, self.FACTS, (), 100)
        self.assertEqual(mountbuy.ACTION, step.action)
        self.assertTrue(step.walk.command.startswith("walk-to-vendor item:2414"))

    def test_the_upkeep_rungs_make_room_for_the_mount(self):
        """With the full-bags sale cooling, the mount rung still aims no
        walk at the vendor: it makes room."""
        m = grug(free_slots=0, bag_slots=16, carried=(self.JUNK,))
        recent = (guildjobs.Recent("Grug", "sell", 30),)
        found, _, _ = guildjobs._upkeep_first(
            m, None, None, None, None, recent, 100, "", None, self.FACTS
        )
        self.assertEqual(guildjobs.ROOM_ACTION, found[0].action)


class ARefusalForFullBagsIsNotRepeated(unittest.TestCase):
    FACTS = mountbuy.Facts(False, STOCK)

    def test_unread_bags_after_a_refusal_hold_the_walk(self):
        """Past the mount cooldown, a member whose last buy was refused for
        full bags is not walked back until a free slot is read."""
        step, note = guildjobs.mount_step(grug(), self.FACTS, (refused_buy(200),), 100)
        self.assertIsNone(step)
        self.assertIn("holds its mount walk", note)

    def test_full_bags_after_a_refusal_hold_the_walk(self):
        m = grug(free_slots=0, bag_slots=16)
        step, _ = guildjobs.mount_step(m, self.FACTS, (refused_buy(200),), 100)
        self.assertIsNone(step)

    def test_a_free_slot_after_the_refusal_lets_the_walk_go(self):
        m = grug(free_slots=2, bag_slots=16)
        step, _ = guildjobs.mount_step(m, self.FACTS, (refused_buy(200),), 100)
        self.assertEqual(mountbuy.ACTION, step.action)
        self.assertIsNotNone(step.walk)

    def test_the_refusal_is_read_from_the_command_rows(self):
        rows = (
            {
                "source": "guildjobs:mount:Grug",
                "target_name": "Grug",
                "age": 200,
                "status": "failed",
                "command": "entry:2414 count:1 max:10000",
                "result": '{"outcome":"refused","reason":"bags cannot take the '
                'item","retryable":true}',
                "id": 1275201,
            },
        )
        recent = guildjobs.recent_from_rows(rows)
        self.assertTrue(guildjobs.mount_refused_for_bags("Grug", recent))

    def test_only_the_newest_buy_counts(self):
        bought_after = guildjobs.Recent(
            "Grug",
            mountbuy.ACTION,
            20,
            status="done",
            command="entry:2414 count:1 max:10000",
            result='{"outcome":"applied"}',
        )
        recent = (refused_buy(200), bought_after)
        self.assertFalse(guildjobs.mount_refused_for_bags("Grug", recent))


if __name__ == "__main__":
    unittest.main()

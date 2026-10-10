"""A guild member with nothing to eat or drink buys some with its own gold, so
its own AI rests between fights (2026-10-10).

Read on the dev realm on 2026-10-10 at 01:00 America/New_York: Femur, a level 14
Bonkers priest in Silverpine Forest, had been level 14 for 117 hours and died 57
times in 24 hours, mostly to Ferocious and Giant Grizzled Bears of levels 11 to
13. His bags held no food and no drink, and 2 silver 79 copper. mod-playerbots'
EatAction and DrinkAction rest a bot only on food and drink in its bags (the
realm grants none: BotCheats is empty and the alt maintenance is off), so after
each corpse run he pulled again at half health and mana. 119 of the two guilds'
142 members carried no food or drink at all.
"""

import unittest

import guildjobs
import restsupply

FEMUR = dict(
    name="Femur",
    guild="Bonkers",
    role=guildjobs.RAIDER,
    level=14,
    class_id=5,  # priest
    race=5,  # undead
    online=True,
    map_id=0,
    x=341.7,
    y=1553.6,
    zone_id=130,
    money=279,
    eligible=True,
    food=0,
    drink=0,
)


def member(**over):
    return guildjobs.Member(**dict(FEMUR, **over))


def offer(vendor, entry, price, req, category, yards=188.0, count=5, name=""):
    """One row of bridge._SUPPLY_VENDOR_SQL."""
    return {
        "vendor": vendor,
        "vendor_name": name or "Vendor %d" % vendor,
        "map_id": 0,
        "yards": yards,
        "entry": entry,
        "item_name": "Item %d" % entry,
        "price": price,
        "buy_count": count,
        "required_level": req,
        "category": category,
        "enemy_group": 2,  # the Alliance's enemy: a Forsaken vendor
    }


FOOD, DRINK = restsupply.FOOD_CATEGORY, restsupply.DRINK_CATEGORY

# The Sepulcher's stock, read off the dev world: Innkeeper Bates sells both.
BATES = [
    offer(6739, 4604, 25, 1, FOOD, name="Innkeeper Bates"),
    offer(6739, 4605, 125, 5, FOOD, name="Innkeeper Bates"),
    offer(6739, 4606, 500, 15, FOOD, name="Innkeeper Bates"),
    offer(6739, 159, 25, 1, DRINK, name="Innkeeper Bates"),
    offer(6739, 1179, 125, 5, DRINK, name="Innkeeper Bates"),
    offer(6739, 1205, 500, 15, DRINK, name="Innkeeper Bates"),
]
# A drink seller nearer than the inn that sells no food.
HARLY = [offer(2140, 1179, 125, 5, DRINK, yards=100.0, name="Edwin Harly")]


def grey(guid, price, count=1):
    return guildjobs.Carried(
        guid=guid, entry=900 + guid, count=count, quality=0, sell_price=price
    )


class WhoWants(unittest.TestCase):
    def test_a_priest_with_nothing_wants_food_and_drink(self):
        self.assertEqual(restsupply.wanted(member()), (DRINK, FOOD))

    def test_a_warrior_wants_no_drink(self):
        self.assertEqual(restsupply.wanted(member(class_id=1)), (FOOD,))

    def test_enough_in_the_bags_wants_nothing(self):
        full = member(food=restsupply.LOW_UNITS, drink=restsupply.LOW_UNITS)
        self.assertEqual(restsupply.wanted(full), ())

    def test_unread_bags_want_nothing(self):
        self.assertEqual(restsupply.wanted(member(food=None, drink=None)), ())


class WhatItBuys(unittest.TestCase):
    def test_femur_buys_both_at_the_inn_within_half_his_purse(self):
        buys, why = restsupply.plan(member(), BATES, junk=0)
        self.assertEqual(why, "")
        self.assertEqual({b.category for b in buys}, {FOOD, DRINK})
        self.assertEqual({b.vendor for b in buys}, {6739})
        self.assertLessEqual(sum(b.ceiling for b in buys), 279 // 2)
        self.assertTrue(all(b.units >= restsupply.MIN_UNITS for b in buys), buys)

    def test_the_best_tier_his_budget_buys_a_handful_of(self):
        buys, _why = restsupply.plan(member(money=2000), BATES, junk=0)
        entries = {b.category: b.entry for b in buys}
        # Half of 20 silver, split two ways, buys 5 of the level 5 tier and
        # never the level 15 tier he is too young for.
        self.assertEqual(entries, {FOOD: 4605, DRINK: 1179})

    def test_a_stack_at_most(self):
        buys, _why = restsupply.plan(member(money=100000), BATES, junk=0)
        self.assertTrue(all(b.units <= restsupply.STACK for b in buys), buys)

    def test_junk_sold_at_the_counter_pays_too(self):
        broke = member(money=0, carried=(grey(1, 60), grey(2, 40, 2)))
        buys, why = restsupply.plan(broke, BATES, junk=140)
        self.assertEqual(why, "")
        self.assertTrue(buys)

    def test_a_member_with_nothing_buys_nothing_and_says_so(self):
        buys, why = restsupply.plan(member(money=0), BATES, junk=0)
        self.assertEqual(buys, ())
        self.assertIn("cannot afford", why)

    def test_one_vendor_that_sells_both_beats_a_nearer_one_that_sells_one(self):
        buys, _why = restsupply.plan(member(), HARLY + BATES, junk=0)
        self.assertEqual({b.vendor for b in buys}, {6739})

    def test_no_vendor_in_reach_says_so(self):
        buys, why = restsupply.plan(member(), [], junk=0)
        self.assertEqual(buys, ())
        self.assertIn("no vendor", why)


class TheStep(unittest.TestCase):
    def test_a_walk_to_the_vendor_then_the_buys(self):
        step, why = guildjobs.supply_step(member(), BATES, 20000.0)
        self.assertEqual(why, "")
        self.assertEqual(step.action, restsupply.ACTION)
        self.assertTrue(step.walk.command.startswith("walk-to-vendor item:"))
        self.assertEqual(step.walk.kind, "buy")
        buys = [r for r in step.rows if r.kind == "buy"]
        self.assertEqual(len(buys), 2)
        for r in buys:
            self.assertRegex(r.command, r"^entry:\d+ count:\d+ max:\d+$")
            self.assertEqual(r.source, "guildjobs:supply:Femur")
        self.assertIn("food and drink", step.said)

    def test_the_junk_goes_over_the_counter_first(self):
        carrying = member(carried=(grey(11, 30),))
        step, _why = guildjobs.supply_step(carrying, BATES, 20000.0)
        self.assertEqual(step.rows[0].kind, "sell")
        self.assertEqual(step.rows[0].command, "guid:11")

    def test_a_hostile_vendor_is_never_walked_to(self):
        alliance = member(race=1)
        step, why = guildjobs.supply_step(alliance, BATES, 20000.0)
        self.assertIsNone(step)
        self.assertIn("no vendor", why)


def plan(members, supply=None, recent=()):
    return guildjobs.plan(
        members,
        masters={"Bonkers": "Zug"},
        supply=supply if supply is not None else {"Femur": BATES},
        recent=tuple(recent),
    )


class InThePass(unittest.TestCase):
    def test_femur_walks_for_food_and_drink(self):
        result = plan([member()])
        steps = [s for s in result.steps if s.holder == "Femur"]
        self.assertEqual([s.action for s in steps], [restsupply.ACTION])

    def test_fed_he_does_not(self):
        result = plan([member(food=20, drink=20)])
        self.assertFalse([s for s in result.steps if s.action == restsupply.ACTION])

    def test_one_trip_an_hour(self):
        row = guildjobs.Recent("Femur", restsupply.ACTION, 20, status="error")
        result = plan([member()], recent=(row,))
        self.assertFalse([s for s in result.steps if s.action == restsupply.ACTION])

    def test_not_in_a_fight_nor_dead(self):
        for m in (member(in_combat=True), member(alive=False), member(online=False)):
            result = plan([m])
            self.assertFalse(
                [s for s in result.steps if s.action == restsupply.ACTION], m
            )

    def test_the_class_quest_still_comes_first(self):
        source = guildjobs._member_step.__code__.co_names
        self.assertLess(source.index("class_step"), source.index("_supply_first"))
        self.assertLess(source.index("_supply_first"), source.index("_gear_first"))

    def test_the_bridge_reads_the_bags_and_the_stock(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        for needle in (
            "_SUPPLY_VENDOR_SQL",
            "_JOB_SUPPLIES_SQL",
            "supply=await self._job_supply_offers(",
        ):
            self.assertTrue(needle in source, needle)


class GearCountsTheJunk(unittest.TestCase):
    """The gear step counts what the junk sells for before it judges what the
    member can afford: the sales are the step's first rows."""

    def test_a_broke_member_with_junk_buys_gear(self):
        from test_guild_gear_step import ROWS, _character, _member

        broke = _member(money=0, carried=(grey(21, 2000, 5),))
        step, why = guildjobs.gear_step(broke, _character(purse=0), ROWS, 600.0)
        self.assertEqual(why, "")
        self.assertEqual(step.action, "gear")
        self.assertEqual(step.rows[0].kind, "sell")

    def test_without_junk_still_nothing(self):
        from test_guild_gear_step import ROWS, _character, _member

        step, _why = guildjobs.gear_step(_member(money=0), _character(purse=0), ROWS, 600.0)
        self.assertIsNone(step)


if __name__ == "__main__":
    unittest.main()

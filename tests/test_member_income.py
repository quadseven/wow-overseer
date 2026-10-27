"""Guild members sell what they loot and have no use for, and save their gold
in one order: class spells they cast, riding, gear, food (#771).

Read on the dev realm on 2026-10-10 between 14:00 and 15:10 America/New_York:
the 132 members of the two family guilds off the roster looted 4.5 to 5.4
copper of coin per kill at levels 20 to 29, sold 2.5 gold of loot between them
in a day, and owed 478 gold of class spells against 36 gold held. 118 of them
had more than 80% of their bag slots full, past which mod-playerbots leaves
every item that does not stack on the corpse. The bags held 1,116 slots of
white trade goods and 199 green weapons and armor.
Only 2 of the 87 at level 20 or above knew Apprentice Riding.

Bonk, a level 25 Draenei paladin in Cave, is the example: 6s 66c, a 16-slot
backpack with 2 free, starter chain on, Journeyman's Pants (a green, item level
10) and 22 Moongraze Stag Tenderloin in the bags.
"""

import dataclasses
import unittest

import bankforecast as bf
import classcasts
import classtrain
import gear
import guildjobs
import purse
import restsupply
import vendorsale

# Bonk's worn gear, read 2026-10-10: Tarnished Chain (item level 5) on chest,
# feet, wrists and hands, War Torn Pants (14) on the legs, Prospector's Pads
# (25) on the shoulders, Fist of Argus (16) and a Large Round Shield (5).
BONK_WORN = gear.CharacterState(
    name="Bonk",
    class_id=2,
    level=25,
    equipped={
        "shoulder": 25,
        "chest": 5,
        "waist": 29,
        "legs": 14,
        "feet": 5,
        "wrist": 5,
        "hands": 5,
        "main_hand": 16,
        "off_hand": 5,
    },
    off_hand_kind=gear.OFF_HAND_SHIELD,
)

PADDING = guildjobs.Carried(
    guid=9001,
    entry=2958,
    name="Journeyman's Pants",
    item_class=4,
    subclass=1,
    quality=2,
    sell_price=94,
    item_level=10,
    required_level=5,
    inventory_type=7,
)
TENDERLOIN = guildjobs.Carried(
    guid=9002,
    entry=23676,
    name="Moongraze Stag Tenderloin",
    count=22,
    item_class=7,
    subclass=8,
    quality=1,
    sell_price=5,
    item_level=1,
)
LINEN = guildjobs.Carried(
    guid=9003,
    entry=2589,
    name="Linen Cloth",
    count=19,
    item_class=7,
    subclass=5,
    quality=1,
    sell_price=13,
    item_level=5,
)
CRYSTAL = guildjobs.Carried(
    guid=9004,
    entry=23984,
    name="Irradiated Crystal Shard",
    count=28,
    item_class=12,
    quality=1,
    sell_price=3,
    item_level=1,
)
ROOT = guildjobs.Carried(
    guid=9005,
    entry=23329,
    name="Enriched Lasher Root",
    count=5,
    item_class=0,
    subclass=8,
    quality=1,
    sell_price=5,
    item_level=5,
)
# A chest an upgrade over Tarnished Chain (5): a mail green Bonk may wear.
CHEST = guildjobs.Carried(
    guid=9006,
    entry=6597,
    name="Battleforge Armor",
    item_class=4,
    subclass=3,
    quality=2,
    sell_price=640,
    item_level=24,
    required_level=19,
    inventory_type=5,
)
RING = guildjobs.Carried(
    guid=9007,
    entry=12054,
    name="Demon Band",
    item_class=4,
    subclass=0,
    quality=2,
    sell_price=700,
    item_level=24,
    required_level=19,
    inventory_type=11,
)
BLUE = guildjobs.Carried(
    guid=9008,
    entry=6622,
    name="Sword of Zeal",
    item_class=2,
    subclass=7,
    quality=3,
    sell_price=2600,
    item_level=32,
    required_level=27,
    inventory_type=13,
)
TIGERSEYE = guildjobs.Carried(
    guid=9009,
    entry=818,
    name="Tigerseye",
    count=1,
    item_class=3,
    subclass=7,
    quality=2,
    sell_price=100,
    item_level=15,
)
MOUNT = guildjobs.Carried(
    guid=9010,
    entry=28481,
    name="Brown Elekk",
    item_class=15,
    subclass=5,
    quality=1,
    sell_price=2500,
    item_level=20,
)
GREY = guildjobs.Carried(
    guid=9011,
    entry=4867,
    name="Broken Scorpid Leg",
    item_class=15,
    subclass=0,
    quality=0,
    sell_price=35,
)
OUTGROWN_GREEN = guildjobs.Carried(
    guid=9012,
    entry=6585,
    name="Wolf Bracers",
    item_class=4,
    subclass=2,
    quality=2,
    sell_price=60,
    item_level=12,
    required_level=7,
    inventory_type=9,
)

# A green belt under the Glimmering Mail Girdle (29) Bonk wears: no upgrade.
BELT = guildjobs.Carried(
    guid=9013,
    entry=6587,
    name="Wolf Belt",
    item_class=4,
    subclass=2,
    quality=2,
    sell_price=230,
    item_level=20,
    required_level=15,
    inventory_type=6,
)

BAGS = (
    PADDING,
    TENDERLOIN,
    LINEN,
    CRYSTAL,
    ROOT,
    CHEST,
    RING,
    BLUE,
    TIGERSEYE,
    MOUNT,
    GREY,
    OUTGROWN_GREEN,
    BELT,
)

# Cave's forecast keeps Linen Cloth (a ladder rung eats it) and nothing else
# Bonk carries.
CAVE_RESERVED = frozenset({2589})


def bonk(**over):
    base = dict(
        name="Bonk",
        guild="Cave",
        role=guildjobs.RAIDER,
        level=25,
        class_id=2,
        race=11,
        online=True,
        map_id=530,
        x=-4100.0,
        y=-11700.0,
        money=666,
        eligible=True,
        carried=BAGS,
        free_slots=2,
        bag_slots=16,
        worn=BONK_WORN,
        reserved=CAVE_RESERVED,
        food=10,
        drink=10,
    )
    base.update(over)
    return guildjobs.Member(**base)


def sold(member, kept=None):
    return {c.name for c in guildjobs.vendor_stacks(member, kept)}


class WhatAMemberSells(unittest.TestCase):
    def test_bonk_sells_his_meat_and_the_green_he_will_not_wear(self):
        self.assertEqual(
            {
                "Moongraze Stag Tenderloin",
                "Journeyman's Pants",
                "Tigerseye",
                "Broken Scorpid Leg",
                "Wolf Bracers",
                "Wolf Belt",
            },
            sold(bonk()),
        )

    def test_he_keeps_the_upgrade_the_ring_the_blue_and_the_mount(self):
        keeps = {c.name for c in BAGS} - sold(bonk())
        for name in ("Battleforge Armor", "Demon Band", "Sword of Zeal", "Brown Elekk"):
            self.assertIn(name, keeps)

    def test_he_keeps_quest_items_and_what_he_eats(self):
        keeps = {c.name for c in BAGS} - sold(bonk())
        self.assertIn("Irradiated Crystal Shard", keeps)
        self.assertIn("Enriched Lasher Root", keeps)

    def test_the_forecasts_reserved_material_is_kept(self):
        self.assertNotIn("Linen Cloth", sold(bonk()))

    def test_an_unread_forecast_sells_no_material(self):
        self.assertEqual(
            {"Journeyman's Pants", "Broken Scorpid Leg", "Wolf Bracers", "Wolf Belt"},
            sold(bonk(reserved=None)),
        )

    def test_unread_worn_gear_sells_only_outgrown_gear(self):
        names = sold(bonk(worn=None))
        self.assertNotIn("Wolf Belt", names)
        self.assertIn("Wolf Bracers", names)
        self.assertIn("Journeyman's Pants", names)

    def test_the_verdict_says_why(self):
        judge = guildjobs.vendor_judge(bonk())
        self.assertEqual(
            (vendorsale.KEEP, "an upgrade: item level 24 beats the equipped 5"),
            vendorsale.verdict(CHEST, judge),
        )
        self.assertEqual(
            (vendorsale.SELL, "not an upgrade (currently equipped is item level 29)"),
            vendorsale.verdict(BELT, judge),
        )
        self.assertEqual(
            (vendorsale.SELL, "outgrown (item level 10 at level 25)"),
            vendorsale.verdict(PADDING, judge),
        )

    def test_a_tool_is_never_sold(self):
        pick = guildjobs.Carried(
            guid=9020,
            entry=guildjobs.MINING_PICK,
            item_class=2,
            subclass=14,
            quality=1,
            sell_price=16,
            item_level=11,
            inventory_type=21,
        )
        self.assertNotIn(pick, guildjobs.vendor_stacks(bonk(carried=(pick,)), None))


class TheSaleWalk(unittest.TestCase):
    """Full bags stop the loot: the sale comes first."""

    def test_two_free_of_sixteen_is_short_of_loot_room(self):
        self.assertTrue(guildjobs.loot_room_short(bonk()))
        self.assertFalse(guildjobs.loot_room_short(bonk(free_slots=5)))
        self.assertFalse(guildjobs.loot_room_short(bonk(bag_slots=None)))

    def test_a_member_short_of_loot_room_walks_to_sell_first(self):
        plan = guildjobs.plan([bonk()])
        (step,) = plan.steps
        self.assertEqual("sell", step.action)
        self.assertIn("(2 of 16 bag slots free)", step.said)
        self.assertEqual("walk-to-vendor any", step.walk.command.split(" max:")[0])
        self.assertEqual(6, len(step.rows))

    def test_with_room_and_little_to_sell_it_does_not_walk(self):
        self.assertIsNone(
            guildjobs._full_bags_first(bonk(free_slots=8), None, (), 600.0)
        )

    def test_a_food_walk_sells_the_same_stacks_at_the_counter(self):
        rows = guildjobs.junk_sales(bonk(), None, restsupply.ACTION)
        self.assertEqual(6, len(rows))


class ThePurchaseOrder(unittest.TestCase):
    def order(self, money=666, spells=37600, count=9, riding=0, level=25, hungry=False):
        return purse.order("Bonk", level, money, spells, count, riding, hungry)

    def test_the_order_is_spells_riding_food_gear(self):
        o = self.order()
        self.assertEqual(
            [purse.SPELLS, purse.RIDING, purse.FOOD, purse.GEAR],
            [w.kind for w in o.wants],
        )
        self.assertEqual(40000, o.want(purse.RIDING).copper)

    def test_gear_spends_only_above_the_spells_and_riding(self):
        o = self.order(money=100000)
        self.assertEqual(100000 - 37600 - 40000, o.spendable(purse.GEAR))
        self.assertEqual(0, self.order().spendable(purse.GEAR))

    def test_a_hungry_member_buys_food_from_the_whole_purse(self):
        self.assertEqual(666, self.order(hungry=True).spendable(purse.FOOD))
        self.assertEqual(0, self.order().spendable(purse.FOOD))

    def test_riding_ranks_by_level_and_skill(self):
        self.assertIsNone(purse.riding_due(19, 0))
        self.assertEqual(purse.APPRENTICE, purse.riding_due(20, 0))
        self.assertIsNone(purse.riding_due(39, 75))
        self.assertEqual(purse.JOURNEYMAN, purse.riding_due(40, 75))
        self.assertIsNone(purse.riding_due(45, 150))

    def test_the_signature_ignores_the_purse_but_not_what_it_covers(self):
        self.assertEqual(self.order(money=600).signature, self.order().signature)
        self.assertNotEqual(self.order(money=80000).signature, self.order().signature)

    def test_the_line_names_the_order_and_what_it_is_short_for(self):
        self.assertEqual(
            "purse: Bonk (25) holds 6s 66c; order: class spells (9 it casts) 3g 76s, "
            "Apprentice Riding 4g, food and drink, gear; short for: class spells "
            "(9 it casts) 3g 76s, Apprentice Riding 4g",
            self.order().line,
        )


class TheRidingWalk(unittest.TestCase):
    def test_a_member_whose_purse_covers_riding_walks_to_the_trainer(self):
        o = purse.order("Bonk", 25, 80000, 37600, 9, 0)
        step, note = guildjobs.riding_step(bonk(money=80000, purse=o), ())
        self.assertEqual("", note)
        self.assertEqual(guildjobs.RIDING_ACTION, step.action)
        self.assertTrue(
            step.rows[0].command.startswith(
                "walk-to-trainer skill:762 learn:33388 max:"
            )
        )
        self.assertEqual("cast", step.rows[0].kind)

    def test_a_member_short_of_its_spells_and_riding_saves(self):
        o = purse.order("Bonk", 25, 666, 37600, 9, 0)
        step, note = guildjobs.riding_step(bonk(purse=o), ())
        self.assertIsNone(step)
        self.assertIn("saves for Apprentice Riding (4g, after 3g 76s kept", note)

    def test_gear_is_planned_from_the_purse_above_the_order(self):
        o = purse.order("Bonk", 25, 666, 37600, 9, 0)
        self.assertEqual(0, guildjobs.spendable(bonk(purse=o), purse.GEAR, 666))
        self.assertEqual(666, guildjobs.spendable(bonk(), purse.GEAR, 666))

    def test_riding_waits_when_last_refusal_was_no_trainer_on_this_map_and_map_id_unchanged(
        self,
    ):
        refusal_text = "no trainer on this map will teach this character that skill"
        recent = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Bruk",
                    "command": "walk-to-trainer skill:762 learn:33388 max:20000",
                    "source": "guildjobs:train:Bruk",
                    "status": "error",
                    "age": 5,
                    "result": '{"outcome":"refused","reason":"'
                    + refusal_text
                    + '","retryable":false}',
                },
            )
        )[0]
        # Replace with a Recent that has map_id set (simulating the fix)
        recent_with_map = guildjobs.Recent(
            name=recent.name,
            action=recent.action,
            age_minutes=recent.age_minutes,
            status=recent.status,
            skill_id=recent.skill_id,
            walk=recent.walk,
            refusal=recent.refusal,
            retryable=recent.retryable,
            command=recent.command,
            result=recent.result,
            map_id=530,
        )
        m = bonk(name="Bruk", map_id=530, money=80000)
        o = purse.order("Bruk", 60, 80000, 37600, 9, 0)
        m = dataclasses.replace(m, purse=o)
        step, note = guildjobs.riding_step(m, (recent_with_map,))
        self.assertIsNone(step)
        self.assertIn(
            "waits on the map change before walking to a riding trainer", note
        )

    def test_riding_proceeds_when_last_refusal_was_no_trainer_on_this_map_but_map_id_changed(
        self,
    ):
        refusal_text = "no trainer on this map will teach this character that skill"
        recent = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Bruk",
                    "command": "walk-to-trainer skill:762 learn:33388 max:20000",
                    "source": "guildjobs:train:Bruk",
                    "status": "error",
                    "age": 5,
                    "result": '{"outcome":"refused","reason":"'
                    + refusal_text
                    + '","retryable":false}',
                },
            )
        )[0]
        recent_with_map = guildjobs.Recent(
            name=recent.name,
            action=recent.action,
            age_minutes=recent.age_minutes,
            status=recent.status,
            skill_id=recent.skill_id,
            walk=recent.walk,
            refusal=recent.refusal,
            retryable=recent.retryable,
            command=recent.command,
            result=recent.result,
            map_id=530,
        )
        m = bonk(name="Bruk", map_id=1, money=80000)  # Different map_id
        o = purse.order("Bruk", 60, 80000, 37600, 9, 0)
        m = dataclasses.replace(m, purse=o)
        step, note = guildjobs.riding_step(m, (recent_with_map,))
        self.assertIsNotNone(step)
        self.assertEqual("", note)

    def test_other_riding_refusals_keep_the_180_minute_cooldown(self):
        order = purse.order("Bruk", 60, 80000, 37600, 9, 0)
        m = bonk(name="Bruk", level=60, money=80000, map_id=530)
        m = dataclasses.replace(m, purse=order)

        for reason in (
            "character is in combat",
            "died on the way to the trainer",
            "too far from the trainer",
        ):
            with self.subTest(reason=reason):

                def refusal_at(age):
                    return guildjobs.recent_from_rows(
                        (
                            {
                                "target_name": "Bruk",
                                "command": "walk-to-trainer skill:762 learn:33388 max:20000",
                                "source": "guildjobs:riding:Bruk",
                                "status": "error",
                                "age": age,
                                "target_arg": "530",
                                "result": (
                                    '{"outcome":"refused","reason":"'
                                    + reason
                                    + '","retryable":true}'
                                ),
                            },
                        )
                    )

                step, note = guildjobs.riding_step(m, refusal_at(5))
                self.assertIsNone(step)
                self.assertEqual("", note)

                step, note = guildjobs.riding_step(m, refusal_at(181))
                self.assertEqual(guildjobs.RIDING_ACTION, step.action)
                self.assertEqual("", note)


class TheTrainStep(unittest.TestCase):
    def test_train_step_waits_when_last_refusal_was_no_trainer_on_this_map_and_map_id_unchanged(
        self,
    ):
        refusal_text = "no trainer on this map will teach this character that skill"
        recent = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Bruk",
                    "command": "walk-to-trainer skill:197 max:20000",  # Tailoring
                    "source": "guildjobs:train:Bruk",
                    "status": "error",
                    "age": 5,
                    "result": '{"outcome":"refused","reason":"'
                    + refusal_text
                    + '","retryable":false}',
                },
            )
        )[0]
        recent_with_map = guildjobs.Recent(
            name=recent.name,
            action=recent.action,
            age_minutes=recent.age_minutes,
            status=recent.status,
            skill_id=recent.skill_id,
            walk=recent.walk,
            refusal=recent.refusal,
            retryable=recent.retryable,
            command=recent.command,
            result=recent.result,
            map_id=530,
        )
        m = bonk(name="Bruk", map_id=530, money=10000, skills={197: (75, 75)})
        step, note = guildjobs._train_step(
            m, {"Bruk": (197,)}, 1000, (recent_with_map,)
        )
        self.assertIsNone(step)
        self.assertIn(
            "waits on the map change before walking to a Tailoring trainer", note
        )

    def test_train_step_proceeds_when_last_refusal_was_no_trainer_on_this_map_but_map_id_changed(
        self,
    ):
        refusal_text = "no trainer on this map will teach this character that skill"
        # Use age > 120 minutes (past the cooldown for a single failed train)
        recent = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Bruk",
                    "command": "walk-to-trainer skill:197 max:20000",  # Tailoring
                    "source": "guildjobs:train:Bruk",
                    "status": "error",
                    "age": 150,
                    "result": '{"outcome":"refused","reason":"'
                    + refusal_text
                    + '","retryable":false}',
                },
            )
        )[0]
        recent_with_map = guildjobs.Recent(
            name=recent.name,
            action=recent.action,
            age_minutes=recent.age_minutes,
            status=recent.status,
            skill_id=recent.skill_id,
            walk=recent.walk,
            refusal=recent.refusal,
            retryable=recent.retryable,
            command=recent.command,
            result=recent.result,
            map_id=530,
        )
        m = bonk(
            name="Bruk", map_id=1, money=10000, skills={197: (75, 75)}
        )  # Different map_id
        step, note = guildjobs._train_step(
            m, {"Bruk": (197,)}, 1000, (recent_with_map,)
        )
        self.assertIsNotNone(step)
        self.assertEqual("", note)


class TheLearnStep(unittest.TestCase):
    def test_learn_step_returns_none_when_last_refusal_was_no_trainer_on_this_map_and_map_id_unchanged(
        self,
    ):
        refusal_text = "no trainer on this map will teach this character that skill"
        recent = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Bruk",
                    "command": "walk-to-trainer skill:129 learn:3273",  # First Aid
                    "source": "guildjobs:train:Bruk",
                    "status": "error",
                    "age": 5,
                    "result": '{"outcome":"refused","reason":"'
                    + refusal_text
                    + '","retryable":false}',
                },
            )
        )[0]
        recent_with_map = guildjobs.Recent(
            name=recent.name,
            action=recent.action,
            age_minutes=recent.age_minutes,
            status=recent.status,
            skill_id=recent.skill_id,
            walk=recent.walk,
            refusal=recent.refusal,
            retryable=recent.retryable,
            command=recent.command,
            result=recent.result,
            map_id=530,
        )
        m = bonk(name="Bruk", map_id=530, money=10000, skills={129: (75, 150)})
        step = guildjobs._learn_step(m, 1000, (recent_with_map,))
        self.assertIsNone(step)

    def test_learn_step_proceeds_when_last_refusal_was_no_trainer_on_this_map_but_map_id_changed(
        self,
    ):
        refusal_text = "no trainer on this map will teach this character that skill"
        recent = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Bruk",
                    "command": "walk-to-trainer skill:129 learn:3273",  # First Aid
                    "source": "guildjobs:train:Bruk",
                    "status": "error",
                    "age": 150,
                    "result": '{"outcome":"refused","reason":"'
                    + refusal_text
                    + '","retryable":false}',
                },
            )
        )[0]
        recent_with_map = guildjobs.Recent(
            name=recent.name,
            action=recent.action,
            age_minutes=recent.age_minutes,
            status=recent.status,
            skill_id=recent.skill_id,
            walk=recent.walk,
            refusal=recent.refusal,
            retryable=recent.retryable,
            command=recent.command,
            result=recent.result,
            map_id=530,
        )
        m = bonk(
            name="Bruk", map_id=1, money=10000, skills={129: (75, 150)}
        )  # Different map_id
        step = guildjobs._learn_step(m, 1000, (recent_with_map,))
        self.assertIsNotNone(step)


class TheSpellsItCasts(unittest.TestCase):
    ROWS = [
        {"spell": 133, "level": 1, "cost": 0},  # Fireball
        {"spell": 143, "level": 6, "cost": 100},  # Fireball rank 2
        {"spell": 3561, "level": 20, "cost": 8000},  # Teleport: Stormwind
        {"spell": 10059, "level": 40, "cost": 0},  # Portal: Stormwind
    ]

    def test_a_mage_saves_for_fireball_and_not_for_a_teleport(self):
        everything = classtrain.due(self.ROWS, {133}, 25)
        casts = classtrain.due(self.ROWS, {133}, 25, class_id=8)
        self.assertEqual((8100, 2), (everything.copper, everything.count))
        self.assertEqual((100, 1), (casts.copper, casts.count))

    def test_passives_and_the_summoning_ritual_count(self):
        self.assertTrue(classcasts.casts(1, 674))  # Dual Wield, passive
        self.assertTrue(classcasts.casts(9, 698))  # Ritual of Summoning
        self.assertFalse(classcasts.casts(3, 1494))  # Track Beasts
        self.assertTrue(classcasts.casts(99, 1494))  # an unknown class saves


class TheForecastsReserve(unittest.TestCase):
    MEAT = bf.Item(
        23676, "Moongraze Stag Tenderloin", bf.ITEM_CLASS_TRADE_GOODS, 8, 1, 20, 5
    )

    def test_meat_nobody_cooks_past_a_stack_is_over_target(self):
        cook = bf.Member("Grug", 25, {185: 1}, family=True)
        forecast = bf.plan(
            (), {23676: self.MEAT}, (cook,), {23676: 600}, entries=(23676,)
        )
        self.assertIn(23676, forecast.over_target)
        self.assertEqual(frozenset(), forecast.reserved)

    def test_a_stack_is_kept_while_somebody_cooks(self):
        cook = bf.Member("Grug", 25, {185: 1}, family=True)
        forecast = bf.plan(
            (), {23676: self.MEAT}, (cook,), {23676: 15}, entries=(23676,)
        )
        self.assertEqual(frozenset({23676}), forecast.reserved)

    def test_an_unread_forecast_reserves_nothing_known(self):
        self.assertIsNone(bf.Forecast().reserved)


class TheBridgeLaysThemOn(unittest.TestCase):
    """The bridge reads the forecast and the spells it casts, and every member
    is planned with its guild's reserve and its own purchase order."""

    def test_each_member_carries_its_guilds_reserve_and_its_order(self):
        from unittest import mock

        from test_guildsocial_bridge import bridge

        forecast = bf.Forecast(judged=frozenset({2589, 23676}), over_target={23676: ""})
        due = {"Bonk": classtrain.Due(37600, 9, 100)}
        with (
            mock.patch.object(bridge, "_bank_forecast", return_value=forecast),
            mock.patch.object(bridge, "_class_training_due", return_value=due) as read,
        ):
            (m,) = bridge._with_purses_and_reserves(
                [bonk(reserved=None, purse=None)], {"Cave": "Grug"}
            )
        self.assertEqual({"casts_only": True}, read.call_args.kwargs)
        self.assertEqual(frozenset({2589}), m.reserved)
        self.assertEqual(37600, m.purse.want(purse.SPELLS).copper)
        self.assertEqual(purse.APPRENTICE.spell, m.purse.want(purse.RIDING).spell)

    def test_unread_spells_leave_the_member_without_an_order(self):
        from unittest import mock

        from test_guildsocial_bridge import bridge

        with (
            mock.patch.object(bridge, "_bank_forecast", return_value=bf.Forecast()),
            mock.patch.object(bridge, "_class_training_due", return_value={}),
        ):
            (m,) = bridge._with_purses_and_reserves(
                [bonk(purse=None)], {"Cave": "Grug"}
            )
        self.assertIsNone(m.purse)
        self.assertIsNone(m.reserved)


if __name__ == "__main__":
    unittest.main()

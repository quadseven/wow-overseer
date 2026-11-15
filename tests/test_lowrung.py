"""The low rungs of cloth, leather and stone have a feed (#2502).

Read from the dev realm on 2026-11-15: a guild vault held 35 Rough Stone
against a target of 62, and the guild's miners and skinners at level 60 were
sent to fields in their own level band, where no Rough Stone, Light Leather or
Linen Cloth drops. The feed sends a member who has out-levelled a rung back to
the creatures or veins that drop it. Nothing here grants an item, a skill or
gold, and nothing lists or buys at the house: the member farms and loots.
"""

import pathlib
import unittest
from dataclasses import replace

import bankforecast as bf
import guildjobs as gj
import lowrung

ROUGH_STONE, COARSE_STONE = 2835, 2836
LIGHT_LEATHER, LINEN, WOOL = 2318, 2589, 2592
SILK, MAGEWEAVE = 4306, 4338
WOOL_ITEM = bf.Item(WOOL, "Wool Cloth", 7, 5, 1, 20, 33)
TAILORING = 197


ROOMY = {
    "Cave": lowrung.Room(vault=10),
    "Bonkers": lowrung.Room(vault=10),
}


def feed_plan(members, starved, crafters=None, focus=None, room=ROOMY):
    return lowrung.plan(members, starved, crafters, focus, room)


def feed_unfed(members, starved, crafters=None, focus=None, room=ROOMY):
    return lowrung.unfed(members, starved, crafters, focus, room)


def member(name, level, skills, guild="Cave", role=None):
    return gj.Member(
        name=name,
        guild=guild,
        role=role or gj.MAINTENANCE,
        level=level,
        online=True,
        map_id=0,
        x=0.0,
        y=0.0,
        skills={k: (v, 300) for k, v in skills.items()},
        skills_read=True,
        eligible=True,
    )


class TheForecastNamesAStarvedMaterial(unittest.TestCase):
    members = (bf.Member("Og", 38, {TAILORING: 81}, family=True),)

    def test_a_material_the_guild_holds_less_of_than_it_eats_is_starved(self):
        forecast = bf.plan(
            (), {WOOL: WOOL_ITEM}, self.members, {WOOL: 3}, entries=(WOOL,)
        )
        self.assertGreater(forecast.starved.get(WOOL, 0), 0)

    def test_a_material_held_past_its_target_is_not(self):
        forecast = bf.plan(
            (), {WOOL: WOOL_ITEM}, self.members, {WOOL: 5000}, entries=(WOOL,)
        )
        self.assertNotIn(WOOL, forecast.starved)


class AMemberWhoOutgrewARungIsSentBackToIt(unittest.TestCase):
    def test_a_level_60_skinner_hunts_the_beasts_that_drop_light_leather(self):
        skinner = member("Skinz", 60, {gj.SKINNING: 300})
        feeds = feed_plan([skinner], {"Cave": {LIGHT_LEATHER: 40}})
        feed = feeds["Skinz"]
        self.assertEqual(lowrung.SKIN, feed.kind)
        self.assertEqual(LIGHT_LEATHER, feed.entry)
        low, high = feed.band
        self.assertLessEqual(high, 25)
        self.assertLess(low, high)

    def test_a_skinner_whose_own_band_already_covers_the_rung_is_left_alone(self):
        skinner = member("Skinz", 18, {gj.SKINNING: 150})
        self.assertEqual({}, feed_plan([skinner], {"Cave": {LIGHT_LEATHER: 40}}))

    def test_a_member_without_the_trade_cannot_feed_leather_or_stone(self):
        miner = member("Digz", 60, {gj.MINING: 300})
        self.assertEqual({}, feed_plan([miner], {"Cave": {LIGHT_LEATHER: 40}}))
        skinner = member("Skinz", 60, {gj.SKINNING: 300})
        self.assertEqual({}, feed_plan([skinner], {"Cave": {ROUGH_STONE: 27}}))

    def test_a_miner_is_sent_to_the_copper_vein_for_rough_stone(self):
        feed = feed_plan(
            [member("Digz", 60, {gj.MINING: 300})], {"Cave": {ROUGH_STONE: 27}}
        )["Digz"]
        self.assertEqual(lowrung.NODE, feed.kind)
        self.assertEqual((38,), feed.locks)

    def test_coarse_stone_needs_the_skill_to_open_a_tin_vein(self):
        green = member("Green", 60, {gj.MINING: 30})
        self.assertEqual({}, feed_plan([green], {"Cave": {COARSE_STONE: 10}}))
        ready = member("Ready", 60, {gj.MINING: 80})
        self.assertEqual(
            (39,), feed_plan([ready], {"Cave": {COARSE_STONE: 10}})["Ready"].locks
        )

    def test_cloth_goes_to_a_member_with_no_gathering_field_of_its_own(self):
        free = member("Free", 60, {})
        feed = feed_plan([free], {"Cave": {LINEN: 100}})["Free"]
        self.assertEqual(lowrung.CLOTH, feed.kind)
        self.assertLessEqual(feed.band[1], 30)
        busy = member("Busy", 60, {gj.MINING: 300})
        self.assertEqual({}, feed_plan([busy], {"Cave": {LINEN: 100}}))

    def test_only_the_guild_that_is_short_sends_anybody(self):
        skinner = member("Skinz", 60, {gj.SKINNING: 300}, guild="Bonkers")
        self.assertEqual({}, feed_plan([skinner], {"Cave": {LIGHT_LEATHER: 40}}))

    def test_two_feeders_a_rung_and_one_rung_a_member(self):
        crew = [member("S%d" % i, 60, {gj.SKINNING: 300}) for i in range(5)]
        feeds = feed_plan(crew, {"Cave": {LIGHT_LEATHER: 40}})
        self.assertEqual(lowrung.FEEDERS_PER_RUNG, len(feeds))
        self.assertEqual(["S0", "S1"], sorted(feeds))

    def test_the_biggest_shortfall_is_fed_first(self):
        crew = [member("S0", 60, {gj.SKINNING: 300})]
        feeds = feed_plan(crew, {"Cave": {LIGHT_LEATHER: 5, 2934: 90}})
        self.assertEqual(2934, feeds["S0"].entry)

    def test_a_member_off_the_job_roster_is_not_sent(self):
        raider = member("Raid", 60, {gj.SKINNING: 300}, role=gj.RAIDER)
        self.assertEqual({}, feed_plan([raider], {"Cave": {LIGHT_LEATHER: 40}}))


class TheStarvedLadderIsSaidInTheLog(unittest.TestCase):
    def test_a_feed_names_the_crafters_the_material_and_the_source(self):
        skinner = member("Skinz", 60, {gj.SKINNING: 300})
        feed = feed_plan(
            [skinner],
            {"Cave": {LIGHT_LEATHER: 40}},
            crafters={LIGHT_LEATHER: ("Bork",)},
        )["Skinz"]
        text = lowrung.line(feed)
        for word in ("Bork", "Light Leather", "Skinz", "40"):
            self.assertIn(word, text)

    def test_a_starved_rung_nobody_can_feed_is_still_said(self):
        notes = feed_unfed(
            [member("Digz", 60, {gj.MINING: 300})],
            {"Cave": {LIGHT_LEATHER: 40}},
            crafters={LIGHT_LEATHER: ("Bork",)},
        )
        self.assertEqual(1, len(notes))
        self.assertIn("Bork", notes[0])
        self.assertIn("Light Leather", notes[0])


class TheFieldsTakeTheBand(unittest.TestCase):
    def test_a_skinning_field_in_the_low_band(self):
        beasts = [
            (gj.Spot(kind="creature", spawn=i, map_id=0, x=10.0 * i, y=0.0), 8)
            for i in range(5)
        ]
        self.assertIsNone(gj.skinning_field(beasts, (0.0, 0.0), 60, 300))
        spot = gj.skinning_field(beasts, (0.0, 0.0), 60, 300, band=(2, 20))
        self.assertIsNotNone(spot)

    def test_a_cloth_field_in_the_low_band(self):
        mobs = [
            (gj.Spot(kind="creature", spawn=i, map_id=0, x=10.0 * i, y=0.0), 12)
            for i in range(5)
        ]
        self.assertIsNone(gj.cloth_field(mobs, (0.0, 0.0), 60))
        self.assertIsNotNone(gj.cloth_field(mobs, (0.0, 0.0), 60, band=(6, 25)))


class AFullDestinationStopsTheFeed(unittest.TestCase):
    """The loot needs somewhere to land: the vault, a banker or a crafter."""

    skinner = member("Skinz", 60, {gj.SKINNING: 300})
    starved = {"Cave": {LIGHT_LEATHER: 40}}

    def test_a_guild_with_no_room_anywhere_sends_nobody(self):
        room = {"Cave": lowrung.Room(vault=0, bankers=0, crafters=0)}
        self.assertEqual({}, feed_plan([self.skinner], self.starved, room=room))

    def test_a_guild_whose_room_was_never_read_sends_nobody(self):
        self.assertEqual({}, feed_plan([self.skinner], self.starved, room={}))
        self.assertEqual({}, feed_plan([self.skinner], self.starved, room=None))

    def test_one_free_stack_is_under_what_a_feed_needs(self):
        room = {"Cave": lowrung.Room(vault=1)}
        self.assertEqual({}, feed_plan([self.skinner], self.starved, room=room))

    def test_room_in_the_vault_a_banker_or_the_crafters_lets_it_through(self):
        for room in (
            lowrung.Room(vault=2),
            lowrung.Room(bankers=5),
            lowrung.Room(crafters=3),
            lowrung.Room(vault=1, crafters=1),
        ):
            feeds = feed_plan([self.skinner], self.starved, room={"Cave": room})
            self.assertIn("Skinz", feeds, room)

    def test_room_in_another_guild_does_not_count(self):
        room = {"Cave": lowrung.Room(), "Bonkers": lowrung.Room(vault=50)}
        self.assertEqual({}, feed_plan([self.skinner], self.starved, room=room))

    def test_a_full_destination_is_said_with_where_the_room_is_not(self):
        notes = feed_unfed(
            [self.skinner],
            self.starved,
            crafters={LIGHT_LEATHER: ("Bork",)},
            room={"Cave": lowrung.Room(vault=0, bankers=0, crafters=1)},
        )
        self.assertEqual(1, len(notes))
        for word in ("Bork", "Light Leather", "vault 0", "bankers 0", "crafters 1"):
            self.assertIn(word, notes[0])

    def test_room_is_counted_in_stacks_with_a_banker_keeping_its_reserve(self):
        import bank

        def banker(bag_free, bank_free, level=60):
            return bank.Member(
                name="Banky",
                level=level,
                bag_free=bag_free,
                bank_free=bank_free,
                carried=(),
                banked=(),
            )

        full = banker(lowrung.guildledger.BAG_RESERVE, bank.BANK_FREE_RESERVE)
        self.assertEqual(0, lowrung.room_of(0, [full]).total)
        roomy = banker(lowrung.guildledger.BAG_RESERVE + 3, bank.BANK_FREE_RESERVE + 4)
        self.assertEqual(7, lowrung.room_of(0, [roomy]).bankers)
        unread = banker(40, 40, level=0)
        self.assertEqual(0, lowrung.room_of(0, [unread], [unread]).total)


def fake_world(packs):
    """A fake adapter for the bridge's two creature surveys.

    `packs` is [(level, first_spawn_id)]: six spawns of that level close
    together. Each survey answers what the real query does, the spawns whose
    level lies in the asked band, and records what it was asked.
    """
    asked = []

    def survey(map_id, x, y, low, high):
        asked.append((low, high))
        return [
            (
                gj.Spot(
                    kind="creature",
                    spawn=first + i,
                    map_id=map_id,
                    x=x + 20.0 * i,
                    y=y,
                ),
                level,
            )
            for level, first in packs
            for i in range(6)
            if low <= level <= high
        ]

    return survey, asked


class TheBridgeWalksTheFeed(unittest.IsolatedAsyncioTestCase):
    """_job_fields and the band path run through a fake adapter."""

    # a pack for each rung's band, and one at the member's own level
    PACKS = [(10, 100), (28, 200), (40, 300), (48, 400), (59, 900)]

    def setUp(self):
        import bridge

        self.bridge = bridge
        survey, self.asked = fake_world(self.PACKS)
        self.keep = (bridge._survey_job_beasts, bridge._survey_job_cloth)
        bridge._survey_job_beasts = survey
        bridge._survey_job_cloth = survey
        self.node = bridge.Bridge.__new__(bridge.Bridge)

    def tearDown(self):
        self.bridge._survey_job_beasts, self.bridge._survey_job_cloth = self.keep

    def fed(self, who, entry):
        return replace(who, feed=feed_plan([who], {"Cave": {entry: 40}})[who.name])

    async def fields(self, who):
        return await self.node._job_fields([who])

    async def test_without_a_feed_a_level_60_skinner_goes_to_its_own_band(self):
        out = await self.fields(member("Skinz", 60, {gj.SKINNING: 300}))
        self.assertIn(out["Skinz"].spawn, range(900, 906))

    async def test_light_leather_sends_the_skinner_to_the_low_beasts(self):
        who = self.fed(member("Skinz", 60, {gj.SKINNING: 300}), LIGHT_LEATHER)
        out = await self.fields(who)
        self.assertEqual((2, 20), self.asked[0])
        self.assertIn(out["Skinz"].spawn, range(100, 106))

    async def test_linen_sends_a_free_member_to_the_low_humanoids(self):
        out = await self.fields(self.fed(member("Free", 60, {}), LINEN))
        self.assertEqual((6, 25), self.asked[0])
        self.assertIn(out["Free"].spawn, range(100, 106))

    async def test_silk_sends_a_free_member_to_levels_25_to_45(self):
        out = await self.fields(self.fed(member("Free", 60, {}), SILK))
        self.assertEqual((25, 45), self.asked[0])
        self.assertIn(out["Free"].spawn, [*range(200, 206), *range(300, 306)])

    async def test_mageweave_sends_a_free_member_to_levels_31_to_50(self):
        out = await self.fields(self.fed(member("Free", 60, {}), MAGEWEAVE))
        self.assertEqual((31, 50), self.asked[0])
        self.assertIn(out["Free"].spawn, [*range(300, 306), *range(400, 406)])

    async def test_a_feed_with_no_field_in_range_falls_back_to_its_own_field(self):
        survey, _asked = fake_world([(59, 900)])
        self.bridge._survey_job_cloth = survey
        out = await self.fields(self.fed(member("Free", 60, {}), SILK))
        self.assertIn(out["Free"].spawn, range(900, 906))

    async def test_the_miners_feed_asks_for_the_vein_locks_only(self):
        seen = []

        async def gathering(member, skills, surveys, only_locks=None):
            seen.append(only_locks)
            return gj.Spot(kind="gameobject", spawn=7, map_id=0, x=0.0, y=0.0)

        self.node._gathering_field = gathering
        who = self.fed(member("Digz", 60, {gj.MINING: 300}), ROUGH_STONE)
        out = await self.fields(who)
        self.assertEqual([(38,)], seen)
        self.assertEqual(7, out["Digz"].spawn)


class TheBridgeLaysTheFeedOnMembers(unittest.TestCase):
    """_with_low_rung_feeds and _low_rung_room, with the reads faked."""

    def setUp(self):
        import bridge

        self.bridge = bridge
        self.keep = (
            bridge._bank_forecast,
            bridge._fetch_guild_bank_setup,
            bridge._fetch_bank_items,
            bridge._log_changed,
        )
        self.said = []
        bridge._bank_forecast = lambda names, fresh=False: bf.Forecast(
            starved={LIGHT_LEATHER: 40}, short={LIGHT_LEATHER: ("Bork",)}
        )
        bridge._log_changed = lambda key, lines: self.said.extend(lines)
        self.setup = {"purchased_tabs": 1, "tab_items": {0: 98}}
        bridge._fetch_guild_bank_setup = lambda names: self.setup
        self.rows = []
        bridge._fetch_bank_items = lambda names: self.rows

    def tearDown(self):
        (
            self.bridge._bank_forecast,
            self.bridge._fetch_guild_bank_setup,
            self.bridge._fetch_bank_items,
            self.bridge._log_changed,
        ) = self.keep

    def lay(self):
        who = member("Skinz", 60, {gj.SKINNING: 300})
        return self.bridge._with_low_rung_feeds([who], {"Cave": "Cavemaster"})[0]

    def test_a_full_vault_and_no_room_elsewhere_lays_no_feed(self):
        self.assertIsNone(self.lay().feed)
        self.assertTrue(any("free stack" in line for line in self.said))

    def test_the_second_tab_with_room_lets_the_feed_through(self):
        self.setup = {"purchased_tabs": 2, "tab_items": {0: 98, 1: 90}}
        feed = self.lay().feed
        self.assertIsNotNone(feed)
        self.assertEqual(LIGHT_LEATHER, feed.entry)

    def test_a_crafter_with_room_in_its_bags_lets_it_through(self):
        # Bork's backpack holds one stack, so the rest of it is free
        self.rows = [
            {"holder": "Bork", "level": 60, "bag": 0, "slot": 23, "item_guid": 1}
        ]
        self.assertIsNotNone(self.lay().feed)

    def test_an_unreadable_room_feeds_nobody(self):
        import pymysql

        def broken(names):
            raise pymysql.err.OperationalError(2003, "down")

        self.bridge._fetch_guild_bank_setup = broken
        self.assertIsNone(self.lay().feed)

    def test_nothing_is_granted(self):
        text = pathlib.Path("lowrung.py").read_text(encoding="utf-8").lower()
        for word in ("additem", "add item", ".modify money", "kind='auction'"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()

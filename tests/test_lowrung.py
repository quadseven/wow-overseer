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

import bankforecast as bf
import guildjobs as gj
import lowrung

ROUGH_STONE, COARSE_STONE = 2835, 2836
LIGHT_LEATHER, LINEN, WOOL = 2318, 2589, 2592
WOOL_ITEM = bf.Item(WOOL, "Wool Cloth", 7, 5, 1, 20, 33)
TAILORING = 197


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
        feeds = lowrung.plan([skinner], {"Cave": {LIGHT_LEATHER: 40}})
        feed = feeds["Skinz"]
        self.assertEqual(lowrung.SKIN, feed.kind)
        self.assertEqual(LIGHT_LEATHER, feed.entry)
        low, high = feed.band
        self.assertLessEqual(high, 25)
        self.assertLess(low, high)

    def test_a_skinner_whose_own_band_already_covers_the_rung_is_left_alone(self):
        skinner = member("Skinz", 18, {gj.SKINNING: 150})
        self.assertEqual({}, lowrung.plan([skinner], {"Cave": {LIGHT_LEATHER: 40}}))

    def test_a_member_without_the_trade_cannot_feed_leather_or_stone(self):
        miner = member("Digz", 60, {gj.MINING: 300})
        self.assertEqual({}, lowrung.plan([miner], {"Cave": {LIGHT_LEATHER: 40}}))
        skinner = member("Skinz", 60, {gj.SKINNING: 300})
        self.assertEqual({}, lowrung.plan([skinner], {"Cave": {ROUGH_STONE: 27}}))

    def test_a_miner_is_sent_to_the_copper_vein_for_rough_stone(self):
        feed = lowrung.plan(
            [member("Digz", 60, {gj.MINING: 300})], {"Cave": {ROUGH_STONE: 27}}
        )["Digz"]
        self.assertEqual(lowrung.NODE, feed.kind)
        self.assertEqual((38,), feed.locks)

    def test_coarse_stone_needs_the_skill_to_open_a_tin_vein(self):
        green = member("Green", 60, {gj.MINING: 30})
        self.assertEqual({}, lowrung.plan([green], {"Cave": {COARSE_STONE: 10}}))
        ready = member("Ready", 60, {gj.MINING: 80})
        self.assertEqual(
            (39,), lowrung.plan([ready], {"Cave": {COARSE_STONE: 10}})["Ready"].locks
        )

    def test_cloth_goes_to_a_member_with_no_gathering_field_of_its_own(self):
        free = member("Free", 60, {})
        feed = lowrung.plan([free], {"Cave": {LINEN: 100}})["Free"]
        self.assertEqual(lowrung.CLOTH, feed.kind)
        self.assertLessEqual(feed.band[1], 30)
        busy = member("Busy", 60, {gj.MINING: 300})
        self.assertEqual({}, lowrung.plan([busy], {"Cave": {LINEN: 100}}))

    def test_only_the_guild_that_is_short_sends_anybody(self):
        skinner = member("Skinz", 60, {gj.SKINNING: 300}, guild="Bonkers")
        self.assertEqual({}, lowrung.plan([skinner], {"Cave": {LIGHT_LEATHER: 40}}))

    def test_two_feeders_a_rung_and_one_rung_a_member(self):
        crew = [member("S%d" % i, 60, {gj.SKINNING: 300}) for i in range(5)]
        feeds = lowrung.plan(crew, {"Cave": {LIGHT_LEATHER: 40}})
        self.assertEqual(lowrung.FEEDERS_PER_RUNG, len(feeds))
        self.assertEqual(["S0", "S1"], sorted(feeds))

    def test_the_biggest_shortfall_is_fed_first(self):
        crew = [member("S0", 60, {gj.SKINNING: 300})]
        feeds = lowrung.plan(crew, {"Cave": {LIGHT_LEATHER: 5, 2934: 90}})
        self.assertEqual(2934, feeds["S0"].entry)

    def test_a_member_off_the_job_roster_is_not_sent(self):
        raider = member("Raid", 60, {gj.SKINNING: 300}, role=gj.RAIDER)
        self.assertEqual({}, lowrung.plan([raider], {"Cave": {LIGHT_LEATHER: 40}}))


class TheStarvedLadderIsSaidInTheLog(unittest.TestCase):
    def test_a_feed_names_the_crafters_the_material_and_the_source(self):
        skinner = member("Skinz", 60, {gj.SKINNING: 300})
        feed = lowrung.plan(
            [skinner],
            {"Cave": {LIGHT_LEATHER: 40}},
            crafters={LIGHT_LEATHER: ("Bork",)},
        )["Skinz"]
        text = lowrung.line(feed)
        for word in ("Bork", "Light Leather", "Skinz", "40"):
            self.assertIn(word, text)

    def test_a_starved_rung_nobody_can_feed_is_still_said(self):
        notes = lowrung.unfed(
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


class TheBridgeCarriesTheFeed(unittest.TestCase):
    source = pathlib.Path("bridge.py").read_text(encoding="utf-8")

    def test_the_planner_lays_the_feed_on_each_member(self):
        body = self.source.split("def _with_purses_and_reserves", 1)[1].split(
            "\ndef ", 1
        )[0]
        self.assertIn("_with_low_rung_feeds(", body)
        self.assertIn("lowrung.plan(", self.source)

    def test_the_job_fields_follow_the_feed(self):
        body = self.source.split("async def _job_fields", 1)[1].split(
            "async def _gathering_field", 1
        )[0]
        self.assertIn("m.feed", body)

    def test_the_module_ships_in_the_image(self):
        self.assertIn("lowrung.py", pathlib.Path("Dockerfile").read_text("utf-8"))

    def test_nothing_is_granted(self):
        text = pathlib.Path("lowrung.py").read_text(encoding="utf-8").lower()
        for word in ("additem", "add item", ".modify money", "kind='auction'"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()

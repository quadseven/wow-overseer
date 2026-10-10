"""An outlevelled guild member leaves a grey zone: the boat off map 530, and a
band that a late quest chain does not stretch.

Measured on the dev realm on 2026-10-10 (UTC 03:00 to 04:00): 25 of Cave's 71
members and 12 of Bonkers' 71 gained no level in 24 hours.

  * Cave's Draenei at 22 to 26 stood on Bloodmyst and Azuremyst Isles, whose
    quests top out at 19. Their level walk was refused every pass with "no walk
    leaves map 530 ... and no row takes it", so none of them had a level row in
    a day. A row does take it now: the module's `cross-to-map map:<id>` rides
    the member's own side's boat, and the world's transports carry Elune's
    Blessing from Valaar's Berth to Auberdine.
  * 33 Cave members were walked to the flight master at Sentinel Hill in
    Westfall in a day, levels 13 to 28 among them, because five level-44 Sweet
    Amber quests set in Westfall made its band 10 to 44: Westfall then fits
    every Alliance member up to 44 and is the lowest band that does, and a
    member standing there never reads as outgrown before 45.
"""

import unittest

import classquest
import guildjobs
import guildlevel
import guildroute
import levelroute

EASTERN_KINGDOMS, KALIMDOR, OUTLAND = 0, 1, 530
HUMAN, DRAENEI, BLOOD_ELF = 1, 11, 10
PALADIN = 2

WESTFALL, REDRIDGE, WETLANDS, DARKSHORE, ASHENVALE = 40, 44, 11, 148, 331
AZUREMYST, BLOODMYST, GHOSTLANDS, SILVERMOON = 3524, 3525, 3433, 3487
REDRIDGE_TOP = 25


def quests_in(zone, low, high, start):
    return [
        {
            "quest": start + i,
            "zone": zone,
            "level": level,
            "min_level": max(level - 4, 1),
            "races": 0,
            "classes": 0,
        }
        for i, level in enumerate(range(low, high + 1))
    ]


def sweet_amber(start):
    """Westfall's five level-44 quests on the dev realm (quest 48 to 53)."""
    return [
        {
            "quest": start + i,
            "zone": WESTFALL,
            "level": 44,
            "min_level": 40,
            "races": 0,
            "classes": 0,
        }
        for i in range(5)
    ]


QUESTS = tuple(
    # Westfall as the dev world has it: its own quests 9 to 20, five of them
    # twice over, and the Sweet Amber chain at 44.
    quests_in(WESTFALL, 9, 20, 1000)
    + quests_in(WESTFALL, 12, 20, 1100)
    + sweet_amber(1200)
    + quests_in(REDRIDGE, 15, REDRIDGE_TOP, 3000)
    + quests_in(WETLANDS, 21, 31, 3500)
    + quests_in(DARKSHORE, 12, 21, 4000)
    + quests_in(ASHENVALE, 20, 32, 4500)
    + quests_in(BLOODMYST, 12, 19, 7000)
    + quests_in(GHOSTLANDS, 10, 20, 8000)
)

ALL_HUBS = levelroute.HUBS + levelroute.STARTING_LAND_HUBS


def master_rows():
    return [
        {
            "guid": 90000 + i,
            "map_id": hub.point[0],
            "x": hub.point[1] + 5.0,
            "y": hub.point[2],
            "name": "%s flight master" % hub.name,
            "enemy_group": 0,
        }
        for i, hub in enumerate(ALL_HUBS)
    ]


def spawn_of(key):
    return 90000 + [h.key for h in ALL_HUBS].index(key)


def world():
    return guildlevel.world(QUESTS, master_rows())


def bands(team=levelroute.ALLIANCE):
    return levelroute.bands(QUESTS, team)


def member(name="Bonk", **over):
    base = dict(
        name=name,
        guild="Cave",
        role=guildjobs.RAIDER,
        level=25,
        class_id=PALADIN,
        race=DRAENEI,
        online=True,
        map_id=OUTLAND,
        # Blood Watch, where Cave's Bonk, Clobba and Drogg stood.
        x=-2440.0,
        y=-12192.0,
        zone_id=BLOODMYST,
        money=0,
        eligible=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


def plan(members, **kw):
    kw.setdefault("masters", {"Cave": "Grug", "Bonkers": "Zug"})
    kw.setdefault("leveling", world())
    kw.setdefault("cap", guildroute.FAR_WALK_YARDS)
    return guildjobs.plan(members, **kw)


def level_steps(result):
    return [s for s in result.steps if s.action == guildlevel.ACTION]


def crossing(name, age, status="error", reason="", retry=False, dest=KALIMDOR):
    """One `cross-to-map` row of the level step, as recent_from_rows reads it."""
    return guildjobs.Recent(
        name,
        guildlevel.CROSS_ACTION,
        age,
        status,
        refusal=reason,
        retryable=retry,
        reason=reason,
        dest=dest,
    )


class AZonesBand(unittest.TestCase):
    def test_a_late_chain_far_above_the_zone_does_not_stretch_its_band(self):
        floor, ceiling, _count = bands()[WESTFALL]
        self.assertLessEqual(ceiling, 20)
        self.assertGreaterEqual(floor, 9)

    def test_a_zone_with_no_such_chain_keeps_its_percentiles(self):
        self.assertEqual(bands()[REDRIDGE][:2], (16, 24))
        self.assertEqual(bands()[ASHENVALE][:2], (21, 31))

    def test_a_member_past_westfalls_own_quests_has_outgrown_it(self):
        why = guildlevel.outgrown(24, HUMAN, EASTERN_KINGDOMS, WESTFALL, bands())
        self.assertIn("outgrown Westfall", why)

    def test_a_member_past_redridge_is_not_sent_back_to_westfall(self):
        got = guildlevel.choose(
            26,
            HUMAN,
            EASTERN_KINGDOMS,
            bands(),
            guildlevel.hub_masters(master_rows()),
            zone_id=REDRIDGE,
        )
        self.assertEqual(got.refused, "")
        self.assertEqual(got.hub.key, "wetlands")


class TheBoatOffMapFiveThirty(unittest.TestCase):
    def test_an_outlevelled_draenei_takes_its_sides_boat_to_kalimdor(self):
        result = plan([member()])
        steps = level_steps(result)
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertIsNone(step.walk)
        self.assertEqual(len(step.rows), 1)
        row = step.rows[0]
        self.assertEqual(row.kind, "job")
        self.assertEqual(row.command, "cross-to-map map:1")
        self.assertEqual(row.source, "guildjobs:level-cross:Bonk")
        # The log line names the boat and the hub it levels at after it.
        self.assertIn("takes the boat", step.said)
        self.assertIn("Valaar's Berth", step.said)
        self.assertIn("Auberdine", step.said)
        self.assertIn("Astranaar in Ashenvale", step.said)
        self.assertIn("outgrown Bloodmyst Isle", step.said)
        self.assertEqual(result.lines["Bonk"], step.said)

    def test_a_draenei_on_azuremyst_past_blood_watch_takes_the_boat_too(self):
        steps = level_steps(plan([member("Snipp", level=24, zone_id=AZUREMYST)]))
        self.assertEqual([s.rows[0].command for s in steps], ["cross-to-map map:1"])

    def test_the_hub_it_heads_for_is_one_on_the_boats_far_side(self):
        got = guildlevel.choose(
            25,
            DRAENEI,
            OUTLAND,
            bands(),
            guildlevel.hub_masters(master_rows()),
            zone_id=BLOODMYST,
        )
        self.assertEqual(got.refused, "")
        self.assertIsNone(got.master)
        self.assertEqual(got.cross_to, KALIMDOR)
        self.assertEqual(got.hub.key, "ashenvale-a")

    def test_on_kalimdor_it_walks_on_to_the_hub(self):
        landed = member(map_id=KALIMDOR, zone_id=DARKSHORE, x=6550.0, y=938.0)
        steps = level_steps(plan([landed]))
        self.assertEqual(len(steps), 1)
        self.assertEqual(
            steps[0].rows[0].command,
            "walk-to-spawn creature:%d max:%d"
            % (spawn_of("ashenvale-a"), int(guildroute.FAR_WALK_YARDS)),
        )

    def test_a_draenei_whose_island_band_still_fits_walks_on_the_island(self):
        steps = level_steps(plan([member(level=14, zone_id=AZUREMYST)]))
        self.assertEqual(len(steps), 1)
        self.assertIn("creature:%d " % spawn_of("bloodmyst"), steps[0].rows[0].command)

    def test_a_blood_elf_has_no_boat_and_is_named_not_crossed(self):
        elf = member(
            "Fabulosa",
            guild="Bonkers",
            race=BLOOD_ELF,
            level=24,
            zone_id=SILVERMOON,
            x=9600.0,
            y=-7100.0,
        )
        result = plan([elf])
        self.assertEqual(level_steps(result), [])
        note = "; ".join(result.notes)
        self.assertIn("Orb of Translocation", note)
        self.assertIn("no row takes it", note)

    def test_a_ghost_is_not_sent_to_the_boat(self):
        self.assertEqual(level_steps(plan([member(alive=False)])), [])


class OneCrossingAtATime(unittest.TestCase):
    def test_a_young_crossing_holds_the_member_with_no_new_row(self):
        recent = (crossing("Bonk", 5, status="claimed"),)
        result = plan([member()], recent=recent)
        self.assertEqual(level_steps(result), [])
        # Held on the crossing: no ordinary job is started over it.
        self.assertEqual([s for s in result.steps if s.holder == "Bonk"], [])
        self.assertIn("takes the boat", result.lines["Bonk"])

    def test_a_class_quest_crossing_under_way_holds_it_too(self):
        recent = (
            guildjobs.Recent(
                "Bonk", classquest.CROSS_ACTION, 5, "claimed", dest=KALIMDOR
            ),
        )
        self.assertEqual(level_steps(plan([member()], recent=recent)), [])

    def test_after_the_cooldown_it_is_asked_again(self):
        recent = (crossing("Bonk", classquest.CROSS_COOLDOWN_MINUTES, "unchanged"),)
        self.assertEqual(len(level_steps(plan([member()], recent=recent))), 1)

    def test_a_retryable_refusal_is_asked_again_sooner(self):
        full = "the realm already has as many crossings as it allows"
        young = (crossing("Bonk", 3, reason=full, retry=True),)
        self.assertEqual(level_steps(plan([member()], recent=young)), [])
        due = (
            crossing("Bonk", classquest.CROSS_RETRY_MINUTES, reason=full, retry=True),
        )
        self.assertEqual(len(level_steps(plan([member()], recent=due))), 1)

    def test_a_boat_the_module_does_not_know_is_a_named_wall(self):
        no_route = (
            "no transport the module knows sails from this map to that map "
            "for this faction"
        )
        recent = (
            crossing("Bonk", classquest.CROSS_COOLDOWN_MINUTES + 5, reason=no_route),
        )
        result = plan([member()], recent=recent)
        self.assertEqual(level_steps(result), [])
        note = "; ".join(result.notes)
        self.assertIn("Bonk", note)
        self.assertIn(no_route, note)
        later = (crossing("Bonk", classquest.CROSS_WALL_MINUTES, reason=no_route),)
        self.assertEqual(len(level_steps(plan([member()], recent=later))), 1)

    def test_the_crossing_counts_against_the_guilds_level_steps(self):
        crew = [member("Draenei%d" % i) for i in range(4)]
        self.assertEqual(len(level_steps(plan(crew))), guildlevel.STEPS_PER_GUILD)


if __name__ == "__main__":
    unittest.main()

"""A guild member that has outgrown its zone walks to a quest hub (guildlevel.py).

Measured on the dev realm on 2026-10-05: natural guild members never left their
starting zones. The random level teleport is skipped for them, which is right,
and nothing walked them anywhere instead, so Cave's priests stood at 14 and 15
in Azuremyst Isle, Elwynn Forest, Dun Morogh and Darnassus among grey mobs and
never reached 17, the dungeon finder's floor. These tests hold the walk a player
would make: out of a zone it has outgrown, to the flight master of the lowest
hub of its side whose band fits its level, on its own continent.
"""

import pathlib
import unittest

import guildjobs
import guildlevel
import guildroute
import levelroute

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

EASTERN_KINGDOMS, KALIMDOR, OUTLAND = 0, 1, 530
HUMAN, NIGHT_ELF, DRAENEI, ORC, BLOOD_ELF = 1, 4, 11, 2, 10
PRIEST = 5

# Zone ids: the starting zones and capitals the priests stood in, and hubs.
ELWYNN, DUN_MOROGH, DARNASSUS, AZUREMYST = 12, 1, 1657, 3524
WESTFALL, LOCH_MODAN, REDRIDGE, DARKSHORE = 40, 38, 44, 148
BARRENS, SILVERPINE = 17, 130
# The map-530 starting lands, and Hellfire Peninsula beyond them.
EVERSONG, GHOSTLANDS, BLOODMYST, THE_EXODAR, HELLFIRE = 3430, 3433, 3525, 3557, 3483


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


QUESTS = tuple(
    quests_in(WESTFALL, 10, 20, 1000)
    + quests_in(LOCH_MODAN, 12, 18, 2000)
    + quests_in(REDRIDGE, 15, 25, 3000)
    + quests_in(DARKSHORE, 11, 19, 4000)
    + quests_in(BARRENS, 10, 25, 5000)
    + quests_in(SILVERPINE, 10, 20, 6000)
    + quests_in(BLOODMYST, 10, 20, 7000)
    + quests_in(GHOSTLANDS, 10, 20, 8000)
)

ALL_HUBS = levelroute.HUBS + levelroute.STARTING_LAND_HUBS


def master_rows():
    """One flight master beside every hub's taxi node, spawn id by hub order."""
    rows = []
    for i, hub in enumerate(ALL_HUBS):
        point = hub.point
        rows.append(
            {
                "guid": 90000 + i,
                "map_id": point[0],
                "x": point[1] + 5.0,
                "y": point[2],
                "name": "%s flight master" % hub.name,
                "enemy_group": 0,
            }
        )
    return rows


def spawn_of(key):
    return 90000 + [h.key for h in ALL_HUBS].index(key)


def world(roster=()):
    return guildlevel.world(QUESTS, master_rows(), roster)


def bands(team=levelroute.ALLIANCE):
    return levelroute.bands(QUESTS, team)


def member(name="Cleric", **over):
    base = dict(
        name=name,
        guild="Cave",
        role=guildjobs.RAIDER,
        level=14,
        class_id=PRIEST,
        race=HUMAN,
        online=True,
        map_id=EASTERN_KINGDOMS,
        x=-9000.0,
        y=100.0,
        zone_id=ELWYNN,
        money=0,
        eligible=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


def plan(members, **kw):
    kw.setdefault("masters", {"Cave": "Grug"})
    kw.setdefault("leveling", world())
    kw.setdefault("cap", guildroute.FAR_WALK_YARDS)
    return guildjobs.plan(members, **kw)


def level_steps(result):
    return [s for s in result.steps if s.action == guildlevel.ACTION]


class TheOutgrownRule(unittest.TestCase):
    def test_a_starting_zone_or_capital_has_no_band_and_is_outgrown(self):
        for zone in (ELWYNN, DUN_MOROGH, DARNASSUS):
            why = guildlevel.outgrown(14, HUMAN, EASTERN_KINGDOMS, zone, bands())
            self.assertIn("no quest band", why, zone)

    def test_a_level_over_the_band_ceiling_is_outgrown(self):
        # Westfall's band is 11 to 19 (levelroute's 10th to 90th percentile).
        why = guildlevel.outgrown(20, HUMAN, EASTERN_KINGDOMS, WESTFALL, bands())
        self.assertIn("outgrown", why)
        self.assertIn("top out at 19", why)

    def test_a_zone_whose_band_still_fits_is_not_outgrown(self):
        self.assertEqual(
            guildlevel.outgrown(14, HUMAN, EASTERN_KINGDOMS, WESTFALL, bands()), ""
        )
        self.assertEqual(
            guildlevel.outgrown(19, HUMAN, EASTERN_KINGDOMS, WESTFALL, bands()), ""
        )

    def test_outland_proper_is_outside_the_classic_world(self):
        why = guildlevel.outgrown(14, DRAENEI, OUTLAND, HELLFIRE, bands())
        self.assertIn("outside the classic world", why)

    def test_an_unread_zone_or_a_dungeon_is_not_judged(self):
        self.assertEqual(
            guildlevel.outgrown(14, HUMAN, EASTERN_KINGDOMS, None, bands()), ""
        )
        self.assertEqual(guildlevel.outgrown(14, HUMAN, 36, ELWYNN, bands()), "")
        self.assertEqual(guildlevel.outgrown(14, HUMAN, None, ELWYNN, bands()), "")


class TheHubChoice(unittest.TestCase):
    def masters(self):
        return guildlevel.hub_masters(master_rows())

    def test_the_lowest_fitting_band_on_its_own_continent(self):
        got = guildlevel.choose(14, HUMAN, EASTERN_KINGDOMS, bands(), self.masters())
        self.assertEqual(got.refused, "")
        self.assertEqual(got.hub.key, "westfall")
        self.assertEqual(got.master.spawn, spawn_of("westfall"))

    def test_kalimdor_sends_an_alliance_member_to_darkshore(self):
        got = guildlevel.choose(14, NIGHT_ELF, KALIMDOR, bands(), self.masters())
        self.assertEqual(got.hub.key, "darkshore")

    def test_the_horde_goes_to_its_own_hubs(self):
        horde = bands(levelroute.HORDE)
        on_kalimdor = guildlevel.choose(14, ORC, KALIMDOR, horde, self.masters())
        on_the_east = guildlevel.choose(
            14, ORC, EASTERN_KINGDOMS, horde, self.masters()
        )
        self.assertEqual(on_kalimdor.hub.key, "barrens")
        self.assertEqual(on_the_east.hub.key, "silverpine")

    def test_a_band_it_has_outgrown_is_passed_over(self):
        got = guildlevel.choose(22, HUMAN, EASTERN_KINGDOMS, bands(), self.masters())
        self.assertEqual(got.hub.key, "redridge")

    def test_a_band_far_above_it_does_not_fit(self):
        got = guildlevel.choose(5, HUMAN, EASTERN_KINGDOMS, bands(), self.masters())
        self.assertIsNone(got.master)
        self.assertIn("no alliance hub fits level 5", got.refused)

    def test_no_fit_on_its_continent_is_named_not_walked(self):
        only_darkshore = {DARKSHORE: bands()[DARKSHORE]}
        got = guildlevel.choose(
            14, HUMAN, EASTERN_KINGDOMS, only_darkshore, self.masters()
        )
        self.assertIsNone(got.master)
        self.assertIn("across the sea", got.refused)
        self.assertEqual(got.hub.key, "darkshore")

    def test_the_other_sides_master_at_the_node_is_never_matched(self):
        westfall = levelroute.BY_KEY["westfall"].point
        hostile = {
            "guid": 1,
            "map_id": westfall[0],
            "x": westfall[1],
            "y": westfall[2],
            "name": "a Horde master",
            "enemy_group": 2,
        }
        masters = guildlevel.hub_masters([hostile, *master_rows()])
        self.assertEqual(masters["westfall"].spawn, spawn_of("westfall"))

    def test_a_hub_with_no_master_spawned_is_not_chosen(self):
        rows = [r for r in master_rows() if r["guid"] != spawn_of("westfall")]
        got = guildlevel.choose(
            14, HUMAN, EASTERN_KINGDOMS, bands(), guildlevel.hub_masters(rows)
        )
        self.assertNotEqual(got.hub.key, "westfall")


class TheStep(unittest.TestCase):
    def test_an_outgrown_priest_walks_to_the_hub_flight_master(self):
        result = plan([member()])
        steps = level_steps(result)
        self.assertEqual(len(steps), 1)
        row = steps[0].rows[0]
        self.assertEqual(row.kind, "job")
        self.assertEqual(
            row.command,
            "walk-to-spawn creature:%d max:%d"
            % (spawn_of("westfall"), int(guildroute.FAR_WALK_YARDS)),
        )
        self.assertEqual(row.source, "guildjobs:level:Cleric")
        # The pass's log line says the choice and why.
        self.assertIn("Sentinel Hill in Westfall", steps[0].said)
        self.assertIn("11 to 19", steps[0].said)
        self.assertIn("no quest band", steps[0].said)
        self.assertEqual(result.lines["Cleric"], steps[0].said)

    def test_it_comes_before_the_ordinary_job(self):
        keeper = member("Keeper", role=guildjobs.MAINTENANCE, money=10**6)
        steps = [s for s in plan([keeper]).steps if s.holder == "Keeper"]
        self.assertEqual(steps[0].action, guildlevel.ACTION)

    def test_a_member_whose_zone_still_fits_stays(self):
        self.assertEqual(level_steps(plan([member(zone_id=WESTFALL)])), [])

    def test_a_member_already_at_the_flight_master_is_not_walked_again(self):
        point = levelroute.BY_KEY["westfall"].point
        here = member(x=point[1], y=point[2], zone_id=ELWYNN)
        self.assertEqual(level_steps(plan([here])), [])

    def test_no_step_without_the_world_read(self):
        self.assertEqual(level_steps(plan([member()], leveling=None)), [])
        self.assertIsNone(guildlevel.world(None, master_rows()))

    def test_no_step_at_the_level_cap_offline_or_fighting(self):
        for m in (
            member(level=guildlevel.LEVEL_CAP),
            member(online=False),
            member(in_combat=True),
        ):
            self.assertEqual(level_steps(plan([m])), [], m)

    def test_a_member_not_yet_naturalized_still_walks_to_level(self):
        """2026-10-05: 1 of Cave's 60 and none of Bonkers' 56 held the natural
        reset; the reset gates contributions, not where a member levels."""
        self.assertEqual(len(level_steps(plan([member(eligible=False)]))), 1)


class TheBounds(unittest.TestCase):
    def test_a_member_walks_at_most_once_per_cooldown(self):
        recent = (guildjobs.Recent("Cleric", guildlevel.ACTION, 30, "delivered"),)
        self.assertEqual(level_steps(plan([member()], recent=recent)), [])
        later = (
            guildjobs.Recent(
                "Cleric", guildlevel.ACTION, guildlevel.COOLDOWN_MINUTES, "delivered"
            ),
        )
        self.assertEqual(len(level_steps(plan([member()], recent=later))), 1)

    def test_a_few_walks_per_guild_per_pass(self):
        crew = [member("Cleric%d" % i) for i in range(5)]
        result = plan(crew)
        self.assertEqual(len(level_steps(result)), guildlevel.STEPS_PER_GUILD)
        self.assertTrue(any("waits" in n for n in result.notes))

    def test_a_busy_member_or_one_in_a_guild_run_is_not_walked(self):
        self.assertEqual(level_steps(plan([member()], busy={"Cleric"})), [])

    def test_a_roster_family_member_is_left_to_levelroute(self):
        result = plan([member()], leveling=world(roster={"Cleric"}))
        self.assertEqual(level_steps(result), [])


def islander(name="Ekka", **over):
    """A Draenei priest on Azuremyst Isle, as Cave's stood on 2026-10-05."""
    base = dict(race=DRAENEI, map_id=OUTLAND, zone_id=AZUREMYST, x=-4000.0, y=-12000.0)
    base.update(over)
    return member(name, **base)


def blood_elf(name="Glamhands", **over):
    """A Blood Elf in Eversong Woods, as Bonkers' stood on 2026-10-05."""
    base = dict(race=BLOOD_ELF, map_id=OUTLAND, zone_id=EVERSONG, x=9400.0, y=-6800.0)
    base.update(over)
    return member(name, guild="Bonkers", **base)


class MapFiveThirty(unittest.TestCase):
    """The Draenei and Blood Elf starting lands (mod-overseer#765).

    On the dev realm on 2026-10-05 Cave's Draenei priests at 14 and 15 and
    Bonkers' Blood Elves stayed on map 530 with the note "no walk leaves map
    530", so none reached 17. A player of those races at that level goes to the
    second zone of its start, Bloodmyst Isle or the Ghostlands, before the boat
    or the orb; the module walks a guild member inside the starting lands.
    """

    def masters(self):
        return guildlevel.hub_masters(master_rows())

    def test_the_starting_lands_are_judged_like_a_continent(self):
        alliance = bands()
        self.assertIn(
            "no quest band",
            guildlevel.outgrown(14, DRAENEI, OUTLAND, AZUREMYST, alliance),
        )
        self.assertIn(
            "no quest band",
            guildlevel.outgrown(14, DRAENEI, OUTLAND, THE_EXODAR, alliance),
        )
        self.assertEqual(
            guildlevel.outgrown(15, DRAENEI, OUTLAND, BLOODMYST, alliance), ""
        )
        self.assertIn(
            "top out at 19",
            guildlevel.outgrown(21, DRAENEI, OUTLAND, BLOODMYST, alliance),
        )

    def test_outland_beyond_the_starting_lands_stays_outside(self):
        why = guildlevel.outgrown(14, DRAENEI, OUTLAND, HELLFIRE, bands())
        self.assertIn("outside the classic world", why)
        got = guildlevel.choose(
            14, DRAENEI, OUTLAND, bands(), self.masters(), zone_id=HELLFIRE
        )
        self.assertIsNone(got.master)

    def test_a_draenei_on_azuremyst_walks_to_blood_watch(self):
        result = plan([islander()])
        steps = level_steps(result)
        self.assertEqual(len(steps), 1)
        self.assertEqual(
            steps[0].rows[0].command,
            "walk-to-spawn creature:%d max:%d"
            % (spawn_of("bloodmyst"), int(guildroute.FAR_WALK_YARDS)),
        )
        self.assertIn("Blood Watch in Bloodmyst Isle", steps[0].said)

    def test_a_draenei_in_the_exodar_walks_to_blood_watch(self):
        steps = level_steps(plan([islander(zone_id=THE_EXODAR)]))
        self.assertEqual(len(steps), 1)
        self.assertIn("creature:%d " % spawn_of("bloodmyst"), steps[0].rows[0].command)

    def test_a_blood_elf_in_eversong_walks_to_tranquillien(self):
        steps = level_steps(plan([blood_elf()], masters={"Bonkers": "Grug"}))
        self.assertEqual(len(steps), 1)
        self.assertIn("creature:%d " % spawn_of("ghostlands"), steps[0].rows[0].command)
        self.assertIn("Tranquillien in Ghostlands", steps[0].said)

    def test_a_draenei_on_bloodmyst_whose_band_fits_stays(self):
        self.assertEqual(level_steps(plan([islander(zone_id=BLOODMYST)])), [])

    def test_past_the_starting_lands_the_note_names_the_boat(self):
        result = plan([islander(level=21, zone_id=BLOODMYST)])
        self.assertEqual(level_steps(result), [])
        note = "; ".join(result.notes)
        self.assertIn("no walk leaves map 530", note)
        self.assertIn("Valaar's Berth", note)
        self.assertIn("Auberdine", note)

    def test_past_the_starting_lands_the_note_names_the_orb(self):
        result = plan(
            [blood_elf(level=21, zone_id=GHOSTLANDS)], masters={"Bonkers": "Grug"}
        )
        self.assertEqual(level_steps(result), [])
        note = "; ".join(result.notes)
        self.assertIn("Orb of Translocation in Silvermoon City", note)
        self.assertIn("the Undercity", note)

    def test_a_member_on_a_continent_is_never_sent_to_the_starting_lands(self):
        only_bloodmyst = {BLOODMYST: bands()[BLOODMYST]}
        got = guildlevel.choose(
            14, HUMAN, EASTERN_KINGDOMS, only_bloodmyst, self.masters(), zone_id=ELWYNN
        )
        self.assertIsNone(got.master)
        self.assertIsNone(got.hub)

    def test_the_starting_land_hubs_are_never_a_familys(self):
        keys = {h.key for h in levelroute.HUBS}
        self.assertNotIn("bloodmyst", keys)
        self.assertNotIn("ghostlands", keys)
        for hub in levelroute.STARTING_LAND_HUBS:
            self.assertTrue(hub.friendly, hub.key)
            self.assertEqual(hub.map_id, OUTLAND, hub.key)


class TheWiring(unittest.TestCase):
    def test_the_bridge_reads_the_zone_the_masters_and_the_roster(self):
        reads = BRIDGE[
            BRIDGE.index("_JOB_MEMBERS_SQL = (") : BRIDGE.index("def _job_read(")
        ]
        self.assertIn("s.zone_id", reads)
        self.assertIn("_JOB_HUB_MASTERS_SQL", reads)
        self.assertIn("EnemyGroup", reads)
        # Map 530 too, for the starting-land hubs' flight masters.
        self.assertIn("c.map IN (%s, %s, %s)", reads)
        self.assertIn("classic.OUTLAND_MAP,", BRIDGE)
        self.assertIn("overseer_roster", reads)
        self.assertIn('zone_id=_row_int(r, "zone_id")', BRIDGE)

    def test_the_pass_hands_the_world_to_the_plan_from_levelroutes_reads(self):
        self.assertIn("leveling=(await asyncio.to_thread(_job_leveling, facts)", BRIDGE)
        body = BRIDGE[BRIDGE.index("def _job_leveling(") :][:600]
        self.assertIn("_level_world()", body)
        self.assertIn("guildlevel.world(", body)

    def test_the_starting_land_quests_are_read_for_their_bands(self):
        for zone in (BLOODMYST, GHOSTLANDS):
            self.assertIn(str(zone), levelroute.QUESTS_SQL)

    def test_the_module_ships(self):
        self.assertIn("guildlevel.py", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()

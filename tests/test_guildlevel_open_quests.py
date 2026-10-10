"""A guild member levels where its quests are: it leaves a zone whose quests
have run out, rotates through every hub of its side, and rides its side's
zeppelin rather than walk across the other side's ground (guildlevel.py).

Run against the live bands of 2026-10-10, the level walk kept a member in one
zone until the zone's 90th-percentile level and never read which quests the
member had done. Horde members on the Eastern Kingdoms stood in Hillsbrad from
21 to 40 and Alliance members on Kalimdor in Ashenvale from 22 to 32; Duskwood,
Dustwallow Marsh, Un'Goro, Felwood, both Plaguelands and Silithus were never
chosen; and a Horde member on the Eastern Kingdoms was walked to Grom'gol at 43
through Alliance ground. Rokk (22) and Whakk (20) stood in Searing Gorge with no
open quest, Tugga (26) in Hillsbrad with one.
"""

import pathlib
import unittest

import guildjobs
import guildlevel
import guildroute
import levelroute

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

EASTERN_KINGDOMS, KALIMDOR = 0, 1
HUMAN, NIGHT_ELF, ORC, UNDEAD = 1, 4, 2, 5
WARRIOR = 1

# Hub zones.
SILVERPINE, BARRENS, STONETALON, ASHENVALE, HILLSBRAD = 130, 17, 406, 331, 267
NEEDLES, DESOLACE, ARATHI, STRANGLETHORN, DUSTWALLOW = 400, 405, 45, 33, 15
BADLANDS, SWAMP, FERALAS, TANARIS, HINTERLANDS = 3, 8, 357, 440, 47
AZSHARA, SEARING, UNGORO, FELWOOD, BURNING = 16, 51, 490, 361, 46
WINTERSPRING, EASTERN_PLAGUE, SILITHUS = 618, 139, 1377
WESTFALL, LOCH_MODAN, REDRIDGE, WETLANDS, DUSKWOOD = 40, 38, 44, 11, 10
DARKSHORE, WESTERN_PLAGUE = 148, 28
# Where a member stands that is no hub: Tirisfal Glades, Durotar.
TIRISFAL, DUROTAR = 85, 14

# A fixed classic quest set: every hub zone of both sides by its usual levels,
# two quests a level, open to both sides.
RANGES = {
    SILVERPINE: (10, 20),
    BARRENS: (10, 25),
    STONETALON: (15, 27),
    ASHENVALE: (18, 30),
    HILLSBRAD: (20, 32),
    NEEDLES: (24, 35),
    DESOLACE: (30, 39),
    ARATHI: (30, 40),
    STRANGLETHORN: (30, 45),
    DUSTWALLOW: (35, 45),
    BADLANDS: (35, 45),
    SWAMP: (35, 45),
    FERALAS: (40, 50),
    TANARIS: (40, 50),
    HINTERLANDS: (40, 50),
    AZSHARA: (45, 55),
    SEARING: (43, 50),
    UNGORO: (48, 55),
    FELWOOD: (48, 55),
    BURNING: (50, 58),
    WINTERSPRING: (53, 60),
    EASTERN_PLAGUE: (53, 60),
    SILITHUS: (55, 60),
    WESTFALL: (10, 18),
    LOCH_MODAN: (11, 19),
    REDRIDGE: (15, 25),
    WETLANDS: (21, 31),
    DUSKWOOD: (18, 30),
    DARKSHORE: (11, 21),
    WESTERN_PLAGUE: (50, 58),
}


def quest_rows():
    rows, qid = [], 10000
    for zone, (low, high) in sorted(RANGES.items()):
        for level in range(low, high + 1):
            for _copy in range(2):
                qid += 1
                rows.append(
                    {
                        "quest": qid,
                        "zone": zone,
                        "level": level,
                        "min_level": max(level - 4, 1),
                        "races": 0,
                        "classes": 0,
                    }
                )
    return rows


QUESTS = quest_rows()


def fact_rows(over=None, quests=QUESTS):
    """A QUEST_FACTS_SQL row per quest: given, solo, no chain, but for `over`
    (quest id -> columns)."""
    over = over or {}
    out = []
    for row in quests:
        fact = {
            "quest": row["quest"],
            "prev": 0,
            "info": 0,
            "group_size": 0,
            "special": 0,
            "given": 1,
        }
        fact.update(over.get(row["quest"], {}))
        out.append(fact)
    return out


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


def world(facts=None):
    return guildlevel.world(
        QUESTS, master_rows(), fact_rows=fact_rows() if facts is None else facts
    )


WORLD = world()
MASTERS = guildlevel.hub_masters(master_rows())


def done_in(*zones, below=None):
    """Every quest of `zones` (under level `below`, when given)."""
    return frozenset(
        r["quest"]
        for r in QUESTS
        if r["zone"] in zones and (below is None or r["level"] < below)
    )


def opens(race, level, done=frozenset(), w=WORLD):
    return guildlevel.member_opens(w, race, level, done)


def choose(race, level, map_id, zone_id, done=frozenset(), nodes=None):
    team = guildlevel.side_of(race)
    return guildlevel.choose(
        level,
        race,
        map_id,
        WORLD.bands[team],
        MASTERS,
        zone_id=zone_id,
        opens=opens(race, level, done),
        nodes=nodes,
    )


def member(name="Tugga", **over):
    base = dict(
        name=name,
        guild="Cave",
        role=guildjobs.RAIDER,
        level=26,
        class_id=WARRIOR,
        race=HUMAN,
        online=True,
        map_id=EASTERN_KINGDOMS,
        x=-711.0,
        y=-515.0,
        zone_id=HILLSBRAD,
        money=0,
        eligible=True,
        rewarded=done_in(HILLSBRAD, below=29),
    )
    base.update(over)
    return guildjobs.Member(**base)


def plan(members, w=WORLD):
    return guildjobs.plan(
        members,
        masters={"Cave": "Grug", "Bonkers": "Zug"},
        leveling=w,
        cap=guildroute.FAR_WALK_YARDS,
    )


def level_steps(result):
    return [s for s in result.steps if s.action == guildlevel.ACTION]


class TheOpenQuests(unittest.TestCase):
    def test_a_quest_in_its_window_it_has_not_done_is_open(self):
        # Hillsbrad at 26: levels 21 to 29 are in the window, two a level.
        self.assertEqual(opens(HUMAN, 26)[HILLSBRAD], 18)

    def test_a_rewarded_quest_is_not_open(self):
        got = opens(HUMAN, 26, done_in(HILLSBRAD, below=29))
        self.assertEqual(got.get(HILLSBRAD, 0), 2)

    def test_a_quest_out_of_its_window_is_not_open(self):
        # Westfall tops out at 18: nothing in 21 to 29.
        self.assertEqual(opens(HUMAN, 26).get(WESTFALL, 0), 0)

    def test_a_group_repeatable_or_ungiven_quest_is_not_open(self):
        hills = [r["quest"] for r in QUESTS if r["zone"] == HILLSBRAD]
        over = {
            hills[0]: {"info": 1},
            hills[1]: {"group_size": 3},
            hills[2]: {"special": guildlevel.REPEATABLE_FLAG},
            hills[3]: {"given": 0},
            hills[4]: {"info": 81},
        }
        w = world(fact_rows(over))
        # Levels 20 and 21 (hills[0..3]) and one of 22 are gone; 21 is in the
        # window at 26, 20 is not.
        self.assertEqual(opens(HUMAN, 26, w=w)[HILLSBRAD], 18 - 3)

    def test_a_chain_counts_from_its_head(self):
        hills = [r for r in QUESTS if r["zone"] == HILLSBRAD and r["level"] >= 21]
        first, second, third = (r["quest"] for r in hills[:3])
        chain = {second: {"prev": first}, third: {"prev": second}}
        chained = world(fact_rows(chain))
        self.assertEqual(opens(HUMAN, 26, w=chained)[HILLSBRAD], 18)
        # The head is another race's: nothing after it can be taken.
        rows = [dict(r, races=2) if r["quest"] == first else r for r in QUESTS]
        book = guildlevel.quest_book(rows, fact_rows(chain))
        got = guildlevel.open_quests(book[levelroute.ALLIANCE], 26, HUMAN, frozenset())
        self.assertEqual(got[HILLSBRAD], 18 - 3)

    def test_a_quest_of_another_race_or_above_its_level_is_not_open(self):
        rows = [
            dict(r, races=2) if r["zone"] == HILLSBRAD and r["level"] == 22 else r
            for r in QUESTS
        ]
        book = guildlevel.quest_book(rows, fact_rows())
        got = guildlevel.open_quests(book[levelroute.ALLIANCE], 26, HUMAN, frozenset())
        self.assertEqual(got[HILLSBRAD], 16)
        # Minimum level 25 to 28 for the level 29 to 32 quests: 29 is still
        # takeable at 26, the rest are over the window.
        self.assertEqual(opens(HUMAN, 26)[HILLSBRAD], 18)

    def test_unread_rewards_or_facts_are_not_read_as_none_done(self):
        self.assertIsNone(guildlevel.member_opens(WORLD, HUMAN, 26, None))
        unread = guildlevel.world(QUESTS, master_rows())
        self.assertIsNone(unread.quests)
        self.assertIsNone(guildlevel.member_opens(unread, HUMAN, 26, frozenset()))
        self.assertIsNone(guildlevel.world(QUESTS, master_rows(), fact_rows=[]).quests)


class ADryZoneIsLeft(unittest.TestCase):
    def bands(self):
        return WORLD.bands[levelroute.ALLIANCE]

    def test_a_zone_with_fewer_than_min_open_quests_is_outgrown(self):
        # Hillsbrad's band (21 to 31) still fits Tugga's 26.
        done = done_in(HILLSBRAD, below=29)
        why = guildlevel.outgrown(
            26, HUMAN, 0, HILLSBRAD, self.bands(), opens(HUMAN, 26, done)
        )
        self.assertEqual(
            why, "it has 2 open quests left in Hillsbrad Foothills at level 26"
        )

    def test_a_member_past_the_ceiling_with_quests_left_stays(self):
        # Westfall tops out at 17; at 20 its 15 to 18 quests are still open.
        self.assertEqual(
            guildlevel.outgrown(20, HUMAN, 0, WESTFALL, self.bands(), opens(HUMAN, 20)),
            "",
        )
        self.assertIn(
            "outgrown Westfall",
            guildlevel.outgrown(20, HUMAN, 0, WESTFALL, self.bands()),
        )

    def test_the_walk_names_the_quests_left_and_the_quests_ahead(self):
        result = plan([member()])
        steps = level_steps(result)
        self.assertEqual(len(steps), 1)
        said = steps[0].said
        self.assertIn(
            "it has 2 open quests left in Hillsbrad Foothills at level 26", said
        )
        self.assertIn("open quests there", said)
        self.assertIn("Tugga walks to the flight master at", said)

    def test_a_member_with_quests_left_is_not_walked(self):
        self.assertEqual(level_steps(plan([member(rewarded=frozenset())])), [])

    def test_unread_rewards_keep_the_band_rule(self):
        # Hillsbrad's band still fits 26: no walk while the rewards are unread.
        self.assertEqual(level_steps(plan([member(rewarded=None)])), [])


class TheHubWithTheMostQuests(unittest.TestCase):
    def test_the_most_open_quests_before_the_lowest_band(self):
        # Alliance at 22 out of a worked Redridge: Westfall is lower but grey,
        # Wetlands has 19 to 25 open and Duskwood 17 to 25.
        got = choose(HUMAN, 22, 0, REDRIDGE, done_in(REDRIDGE))
        self.assertEqual(got.refused, "")
        self.assertEqual(got.hub.key, "duskwood")
        self.assertEqual(got.master.spawn, spawn_of("duskwood"))
        self.assertEqual(got.open, 16)

    def test_a_zone_it_has_done_is_passed_over(self):
        got = choose(HUMAN, 22, 0, REDRIDGE, done_in(REDRIDGE, DUSKWOOD))
        self.assertNotIn(got.hub.key, ("redridge", "duskwood"))
        self.assertEqual(got.hub.key, "hillsbrad-a")
        self.assertEqual(got.open, 12)

    def test_a_known_flight_point_breaks_a_tie(self):
        # At 33 with Ashenvale, Stonetalon, the Barrens and Needles' level 28
        # quests worked, Desolace (30 to 36) and Needles (29 to 35) hold 14
        # open quests each; the flight point it knows wins.
        needles_28 = {
            r["quest"] for r in QUESTS if r["zone"] == NEEDLES and r["level"] == 28
        }
        done = done_in(ASHENVALE, STONETALON, BARRENS) | needles_28
        team_opens = opens(ORC, 33, done)
        self.assertEqual(team_opens[DESOLACE], team_opens[NEEDLES])
        knows_needles = choose(ORC, 33, 1, ASHENVALE, done, nodes=frozenset({30}))
        knows_desolace = choose(ORC, 33, 1, ASHENVALE, done, nodes=frozenset({38}))
        self.assertEqual(knows_needles.hub.key, "needles")
        self.assertEqual(knows_desolace.hub.key, "desolace")


class TheHordeNorthRidesItsZeppelin(unittest.TestCase):
    def north(self, level, done):
        return choose(UNDEAD, level, 0, HILLSBRAD, done)

    def test_grom_gol_is_never_walked_to_from_the_north(self):
        # At 43 the north's Arathi is worked and the Hinterlands not yet open
        # enough; Stranglethorn has the most quests but lies past Duskwood.
        done = done_in(HILLSBRAD, ARATHI, SILVERPINE, HINTERLANDS)
        got = self.north(43, done)
        self.assertNotEqual(got.hub.key, "stranglethorn")
        self.assertIsNone(got.master)
        self.assertEqual(got.cross_to, KALIMDOR)
        self.assertEqual(got.transport, "the zeppelin from the Undercity to Orgrimmar")
        self.assertEqual(got.hub.map_id, KALIMDOR)

    def test_the_badlands_and_the_swamp_are_not_walked_to_either(self):
        for level in range(30, 50):
            got = self.north(level, done_in(HILLSBRAD, ARATHI, below=level + 4))
            if got.hub is not None and got.master is not None:
                self.assertNotIn(
                    got.hub.zone_id, (STRANGLETHORN, BADLANDS, SWAMP, SEARING, BURNING)
                )

    def test_the_crossing_is_one_cross_to_map_row(self):
        done = done_in(HILLSBRAD, ARATHI, SILVERPINE, HINTERLANDS)
        zug = member(
            "Rotney",
            guild="Bonkers",
            race=UNDEAD,
            level=43,
            x=-30.0,
            y=-860.0,
            rewarded=done,
        )
        steps = level_steps(plan([zug]))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].rows[0].command, "cross-to-map map:1")
        self.assertEqual(steps[0].rows[0].source, "guildjobs:level-cross:Rotney")
        self.assertIn("the zeppelin from the Undercity to Orgrimmar", steps[0].said)

    def test_only_stranglethorn_left_names_the_zeppelin_no_row_rides(self):
        # Every quest but Stranglethorn's done: the north and Kalimdor are dry.
        done = done_in(*(z for z in RANGES if z != STRANGLETHORN))
        got = self.north(40, done)
        self.assertEqual(got.hub.key, "stranglethorn")
        self.assertIsNone(got.master)
        self.assertIn("past the other side's ground", got.refused)
        self.assertIn("the zeppelin from the Undercity to Grom'gol", got.refused)

    def test_landed_at_grom_gol_it_works_stranglethorn(self):
        got = choose(UNDEAD, 40, 0, STRANGLETHORN, done_in(STRANGLETHORN, below=36))
        self.assertEqual(got.hub.key, "stranglethorn")
        self.assertIsNotNone(got.master)

    def test_from_grom_gol_it_rides_to_orgrimmar_never_walks_north(self):
        got = choose(UNDEAD, 40, 0, STRANGLETHORN, done_in(STRANGLETHORN))
        self.assertEqual(got.cross_to, KALIMDOR)
        self.assertIn("Grom'gol to Orgrimmar", got.transport)

    def test_the_badlands_has_no_ride_and_is_named(self):
        # No zeppelin calls in the Badlands, and the north lies past Loch Modan:
        # the member stays, named, with Feralas the best hub across the sea.
        done = done_in(BADLANDS, SEARING, BURNING)
        got = choose(UNDEAD, 44, 0, BADLANDS, done)
        self.assertIsNone(got.master)
        self.assertIsNone(got.cross_to)
        self.assertEqual(got.hub.key, "feralas")
        self.assertIn(
            "is across the sea, and no horde ride leaves the Badlands", got.refused
        )
        # With Kalimdor worked too, the Hinterlands are named past Loch Modan.
        north_only = done | done_in(
            FERALAS, TANARIS, DUSTWALLOW, AZSHARA, STRANGLETHORN, SWAMP
        )
        got = choose(UNDEAD, 44, 0, BADLANDS, north_only)
        self.assertEqual(got.hub.key, "hinterlands")
        self.assertIn(
            "lies past the other side's ground from the Badlands", got.refused
        )

    def test_the_alliance_takes_its_boat_from_menethil(self):
        done = done_in(*(z for z, r in RANGES.items() if z != DUSTWALLOW))
        got = choose(HUMAN, 40, 0, WETLANDS, done)
        self.assertEqual(got.hub.key, "dustwallow-a")
        self.assertEqual(got.cross_to, KALIMDOR)
        self.assertIn("Menethil Harbor", got.transport)


def route(race, level, map_id, zone_id, top=60):
    """The hubs a member levels at from `level` to `top`, working every open
    quest of the zone it stands in each level, like a player."""
    done, visited = set(), []
    for _ in range(200):
        if level >= top:
            break
        team = guildlevel.side_of(race)
        left = opens(race, level, frozenset(done))
        why = guildlevel.outgrown(level, race, map_id, zone_id, WORLD.bands[team], left)
        if why:
            got = guildlevel.choose(
                level,
                race,
                map_id,
                WORLD.bands[team],
                MASTERS,
                zone_id=zone_id,
                opens=left,
            )
            if got.refused:
                visited.append(("refused", level, got.refused))
                level += 1
                continue
            if got.cross_to is not None:
                visited.append(("cross", level, got.transport))
                map_id = got.cross_to
                zone_id = DUROTAR if got.cross_to == KALIMDOR else TIRISFAL
                continue
            map_id, zone_id = got.master.map_id, got.hub.zone_id
            visited.append((got.hub.key, level, got.open))
        book = WORLD.quests[team]
        done |= {
            q.id
            for q in book.values()
            if q.zone == zone_id and level - guildlevel.GREEN_BELOW <= q.level <= level
        }
        level += 1
    return visited


class TheRouteTable(unittest.TestCase):
    """The route of each side and continent against the fixed quest set: the
    hub, the level it is chosen at and the quests open for the member there,
    and each zeppelin or boat taken. Every big quest zone of a side is
    chosen, and Stranglethorn, the Badlands and the Swamp of Sorrows are never
    walked to from the Horde's north."""

    def test_horde_on_the_eastern_kingdoms(self):
        self.assertEqual(
            route(UNDEAD, 21, 0, TIRISFAL),
            [
                ("silverpine", 21, 10),
                ("hillsbrad", 22, 12),
                ("arathi", 32, 12),
                ("hinterlands", 40, 8),
                ("cross", 50, "the zeppelin from the Undercity to Orgrimmar"),
                ("azshara", 50, 18),
                ("ungoro", 55, 12),
                ("winterspring", 56, 14),
            ],
        )

    def test_horde_on_kalimdor(self):
        self.assertEqual(
            route(ORC, 20, 1, DUROTAR),
            [
                ("barrens", 20, 18),
                ("ashenvale", 25, 18),
                ("needles", 30, 18),
                ("desolace", 35, 18),
                ("dustwallow", 39, 16),
                ("feralas", 45, 18),
                ("azshara", 50, 18),
                ("ungoro", 55, 12),
                ("winterspring", 56, 14),
            ],
        )

    def test_alliance_on_the_eastern_kingdoms(self):
        self.assertEqual(
            route(HUMAN, 20, 0, WESTFALL),
            [
                ("redridge", 21, 18),
                ("duskwood", 25, 18),
                ("hillsbrad-a", 30, 16),
                ("arathi-a", 32, 12),
                ("stranglethorn-a", 40, 18),
                ("hinterlands-a", 45, 18),
                ("searing-a", 50, 12),
                ("burning-a", 51, 10),
                ("plaguelands-a", 58, 16),
            ],
        )

    def test_alliance_on_kalimdor(self):
        self.assertEqual(
            route(NIGHT_ELF, 20, 1, DARKSHORE),
            [
                ("stonetalon-a", 21, 18),
                ("ashenvale-a", 27, 18),
                ("desolace-a", 30, 8),
                ("dustwallow-a", 39, 16),
                ("feralas-a", 45, 18),
                ("azshara-a", 50, 18),
                ("ungoro-a", 55, 12),
                ("winterspring-a", 56, 14),
            ],
        )

    def test_every_hub_is_chosen_with_quests_open(self):
        for start in (
            (UNDEAD, 21, 0, TIRISFAL),
            (ORC, 20, 1, DUROTAR),
            (HUMAN, 20, 0, WESTFALL),
            (NIGHT_ELF, 20, 1, DARKSHORE),
        ):
            for step in route(*start):
                self.assertNotEqual(step[0], "refused", step)
                if step[0] != "cross":
                    self.assertGreaterEqual(step[2], guildlevel.MIN_OPEN, step)


class TheWiring(unittest.TestCase):
    def test_the_bridge_reads_every_rewarded_quest_and_the_taximask(self):
        self.assertIn(
            "FROM character_queststatus_rewarded WHERE guid IN ({guids})", BRIDGE
        )
        self.assertIn('"c.taximask, "', BRIDGE)
        self.assertIn('taxi_nodes=flightlearn.known_nodes(r.get("taximask"))', BRIDGE)
        self.assertIn("rewarded=None if rewarded is None", BRIDGE)

    def test_the_bridge_reads_the_quest_facts_once_and_hands_them_on(self):
        self.assertIn("guildlevel.QUEST_FACTS_SQL", BRIDGE)
        body = BRIDGE[BRIDGE.index("def _job_leveling(") :][:900]
        self.assertIn('fact_rows=facts.get("quest_facts")', body)

    def test_the_facts_read_names_the_givers_and_the_chain(self):
        sql = guildlevel.QUEST_FACTS_SQL
        for word in (
            "creature_queststarter",
            "gameobject_queststarter",
            "PrevQuestID",
            "QuestInfoID",
            "SuggestedGroupNum",
            "SpecialFlags",
            "game_event_creature",
        ):
            self.assertIn(word, sql)
        for zone in levelroute.ZONES:
            self.assertIn(str(zone), sql)

    def test_the_step_hands_the_open_quests_and_the_flights_to_the_choice(self):
        source = (HERE / "guildjobs.py").read_text(encoding="utf-8")
        body = source[source.index("def level_step(") :][:3500]
        self.assertIn(
            "guildlevel.member_opens(world, m.race, m.level, m.rewarded)", body
        )
        self.assertIn("opens=opens", body)
        self.assertIn("nodes=m.taxi_nodes", body)


if __name__ == "__main__":
    unittest.main()

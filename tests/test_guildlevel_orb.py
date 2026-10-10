"""An outlevelled Blood Elf leaves map 530 by the Orb of Translocation.

Measured on the dev realm on 2026-10-10 (UTC 04:30): 7 of Bonkers' Blood Elves
stood on map 530 past the Ghostlands' band (quests 10 to 20), levels 21 to 30,
in Eversong Woods, the Ghostlands and Silvermoon City. Every pass named them
with "no walk leaves map 530 ... and no row takes it" and left them there; a
hearth sends a Blood Elf home to Sunstrider Isle, so a member that had levelled
on Kalimdor came back to the island and stayed. Their time past level 20 on
record came to about 395 member-hours (Sparklez 101, Elfabulous 82, Blingz 81,
Fabulosa 60, Prettyboi 39, Selfie 25, Manicure 7).

A Blood Elf player leaves by the orb in Silvermoon City: it walks to it and
clicks it, and the orb's own spell carries it to the Undercity. That is the
module's `walk-to-spawn gameobject:<spawn>` and then its `use-gameobject
<entry>` row (quadseven/mod-overseer#865), the same click a class quest makes.
From the Undercity the level step walks it on to a hub that fits, as it walks
an Alliance member on from Auberdine after the boat.
"""

import pathlib
import unittest

import guildjobs
import guildlevel
import guildroute
import levelroute

EASTERN_KINGDOMS, KALIMDOR, OUTLAND = 0, 1, 530
HUMAN, DRAENEI, BLOOD_ELF, UNDEAD = 1, 11, 10, 5
MAGE = 8

EVERSONG, GHOSTLANDS, SILVERMOON, HELLFIRE = 3430, 3433, 3487, 3483
SILVERPINE, HILLSBRAD, BARRENS, ASHENVALE = 130, 267, 17, 331
BLOODMYST, DARKSHORE, UNDERCITY = 3525, 148, 1497

# The Silvermoon orb as the dev world holds it: gameobject 184502, spawn 12608.
ORB_SPAWN = 12608
ORB_X, ORB_Y = 10032.4, -7000.29


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
    quests_in(GHOSTLANDS, 10, 20, 1000)
    + quests_in(SILVERPINE, 10, 20, 2000)
    + quests_in(HILLSBRAD, 21, 32, 3000)
    + quests_in(BARRENS, 10, 25, 4000)
    + quests_in(ASHENVALE, 20, 30, 5000)
    + quests_in(BLOODMYST, 12, 19, 6000)
    + quests_in(DARKSHORE, 12, 21, 7000)
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


def orb_rows():
    """The world's Orb of Translocation spawns: Silvermoon's, and the
    Undercity's way back, which no member leaving the island takes."""
    return [
        {"guid": ORB_SPAWN, "entry": 184502, "map_id": OUTLAND, "x": ORB_X, "y": ORB_Y},
        {
            "guid": 44984,
            "entry": 184503,
            "map_id": EASTERN_KINGDOMS,
            "x": 1805.85,
            "y": 348.865,
        },
    ]


def world(orbs=True):
    return guildlevel.world(QUESTS, master_rows(), orb_rows=orb_rows() if orbs else ())


def member(name="Sparklez", **over):
    base = dict(
        name=name,
        guild="Bonkers",
        role=guildjobs.RAIDER,
        level=24,
        class_id=MAGE,
        race=BLOOD_ELF,
        online=True,
        map_id=OUTLAND,
        # Sunstrider Isle, where a Blood Elf's hearthstone takes it.
        x=10411.0,
        y=-6350.0,
        zone_id=EVERSONG,
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


def orb_row(name, age, status="applied", walk=False):
    """One row of the level step's orb, as recent_from_rows reads it."""
    return guildjobs.Recent(name, guildlevel.ORB_ACTION, age, status, walk=walk)


class TheOrbIsReadFromTheWorld(unittest.TestCase):
    def test_the_silvermoon_orb_is_the_hordes_way_off_the_island(self):
        orbs = guildlevel.orbs_from(orb_rows())
        self.assertEqual(set(orbs), {levelroute.HORDE})
        orb = orbs[levelroute.HORDE]
        self.assertEqual(orb.spawn, ORB_SPAWN)
        self.assertEqual(orb.entry, 184502)
        self.assertEqual(orb.map_id, OUTLAND)
        self.assertEqual(orb.lands_on, EASTERN_KINGDOMS)

    def test_an_unreadable_row_is_left_out(self):
        self.assertEqual(guildlevel.orbs_from([{"guid": "x", "entry": 184502}]), {})
        self.assertEqual(guildlevel.orbs_from(None), {})


class TheChoice(unittest.TestCase):
    def test_a_blood_elf_past_the_ghostlands_heads_for_a_hub_the_orb_reaches(self):
        got = guildlevel.choose(
            24,
            BLOOD_ELF,
            OUTLAND,
            levelroute.bands(QUESTS, levelroute.HORDE),
            guildlevel.hub_masters(master_rows()),
            zone_id=EVERSONG,
            orbs=guildlevel.orbs_from(orb_rows()),
        )
        self.assertEqual(got.refused, "")
        self.assertIsNone(got.master)
        self.assertEqual(got.cross_to, EASTERN_KINGDOMS)
        self.assertIsNotNone(got.orb)
        # The Barrens fits too, from a lower floor, but lies across the sea
        # from where the orb lands: Tarren Mill is the hub on the Undercity's
        # side.
        self.assertEqual(got.hub.key, "hillsbrad")

    def test_the_alliance_still_takes_its_boat(self):
        got = guildlevel.choose(
            21,
            DRAENEI,
            OUTLAND,
            levelroute.bands(QUESTS, levelroute.ALLIANCE),
            guildlevel.hub_masters(master_rows()),
            zone_id=BLOODMYST,
            orbs=guildlevel.orbs_from(orb_rows()),
        )
        self.assertEqual(got.cross_to, KALIMDOR)
        self.assertIsNone(got.orb)


class TheOrbStep(unittest.TestCase):
    def test_an_outlevelled_blood_elf_walks_to_the_orb_and_clicks_it(self):
        result = plan([member()])
        steps = level_steps(result)
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step.walk.kind, "job")
        self.assertEqual(
            step.walk.command,
            "walk-to-spawn gameobject:%d max:%d"
            % (ORB_SPAWN, int(guildroute.FAR_WALK_YARDS)),
        )
        self.assertEqual(step.walk.source, "guildjobs:level-orb-walk:Sparklez")
        self.assertEqual(len(step.rows), 1)
        row = step.rows[0]
        self.assertEqual(row.kind, "quest")
        self.assertEqual(row.command, "use-gameobject 184502")
        self.assertEqual(row.source, "guildjobs:level-orb:Sparklez")
        self.assertEqual(step.goal, "the Orb of Translocation")
        # The log line names the orb, where it lands and the hub after it.
        self.assertIn("Orb of Translocation", step.said)
        self.assertIn("Undercity", step.said)
        self.assertIn("Tarren Mill in Hillsbrad Foothills", step.said)
        self.assertIn("EversongWoods", step.said)
        self.assertEqual(result.lines["Sparklez"], step.said)

    def test_in_the_ghostlands_and_in_silvermoon_too(self):
        for zone, x, y in (
            (GHOSTLANDS, 7009.0, -7255.0),
            (SILVERMOON, 9527.0, -7216.0),
        ):
            got = level_steps(plan([member(level=21, zone_id=zone, x=x, y=y)]))
            self.assertEqual(
                [s.rows[0].command for s in got], ["use-gameobject 184502"]
            )

    def test_a_member_beside_the_orb_clicks_it_with_no_walk(self):
        here = member(zone_id=SILVERMOON, x=ORB_X + 2.0, y=ORB_Y)
        step = level_steps(plan([here]))[0]
        self.assertIsNone(step.walk)
        self.assertEqual(step.rows[0].command, "use-gameobject 184502")

    def test_a_blood_elf_the_ghostlands_still_fit_walks_to_tranquillien(self):
        steps = level_steps(plan([member(level=16)]))
        self.assertEqual(len(steps), 1)
        self.assertIn(
            "walk-to-spawn creature:%d " % spawn_of("ghostlands"),
            steps[0].rows[0].command,
        )

    def test_once_in_the_undercity_it_walks_on_to_tarren_mill(self):
        landed = member(map_id=EASTERN_KINGDOMS, zone_id=UNDERCITY, x=1804.9, y=326.9)
        steps = level_steps(plan([landed]))
        self.assertEqual(len(steps), 1)
        self.assertEqual(
            steps[0].rows[0].command,
            "walk-to-spawn creature:%d max:%d"
            % (spawn_of("hillsbrad"), int(guildroute.FAR_WALK_YARDS)),
        )

    def test_with_no_orb_read_it_is_named_and_left(self):
        result = plan([member("Fabulosa")], leveling=world(orbs=False))
        self.assertEqual(level_steps(result), [])
        note = "; ".join(result.notes)
        self.assertIn("Orb of Translocation", note)
        self.assertIn("no row takes it", note)

    def test_beyond_the_starting_lands_no_walk_reaches_the_orb(self):
        out = member(zone_id=HELLFIRE, x=-200.0, y=4000.0)
        result = plan([out])
        self.assertEqual(level_steps(result), [])
        self.assertIn("Orb of Translocation", "; ".join(result.notes))

    def test_a_ghost_is_not_sent_to_the_orb(self):
        self.assertEqual(level_steps(plan([member(alive=False)])), [])


class OneOrbStepAtATime(unittest.TestCase):
    def test_a_young_orb_step_holds_the_member_with_no_new_row(self):
        result = plan([member()], recent=(orb_row("Sparklez", 10, "error"),))
        self.assertEqual(level_steps(result), [])
        self.assertEqual([s for s in result.steps if s.holder == "Sparklez"], [])
        self.assertIn("Orb of Translocation", result.lines["Sparklez"])

    def test_its_walk_holds_the_member_too(self):
        recent = (orb_row("Sparklez", 10, "verifying", walk=True),)
        self.assertEqual(level_steps(plan([member()], recent=recent)), [])

    def test_after_the_cooldown_it_is_asked_again(self):
        recent = (orb_row("Sparklez", guildlevel.ORB_COOLDOWN_MINUTES, "error"),)
        self.assertEqual(len(level_steps(plan([member()], recent=recent))), 1)

    def test_the_orb_counts_against_the_guilds_level_steps(self):
        crew = [member("Elf%d" % i) for i in range(4)]
        self.assertEqual(len(level_steps(plan(crew))), guildlevel.STEPS_PER_GUILD)


class TheBridgeReadsTheOrb(unittest.TestCase):
    BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
        encoding="utf-8"
    )

    def test_the_orb_spawn_is_read_once_and_handed_to_the_world(self):
        self.assertIn("_JOB_ORBS_SQL", self.BRIDGE)
        self.assertIn("(guildlevel.ORB_ENTRY, classic.OUTLAND_MAP)", self.BRIDGE)
        body = self.BRIDGE[self.BRIDGE.index("def _job_leveling(") :][:700]
        self.assertIn('orb_rows=facts.get("orbs", ())', body)

    def test_a_refused_click_gives_up_no_class_quest(self):
        body = self.BRIDGE[self.BRIDGE.index("async def _class_use_row(") :][:3000]
        self.assertIn("if step.action == classquest.ACTION:", body)


if __name__ == "__main__":
    unittest.main()

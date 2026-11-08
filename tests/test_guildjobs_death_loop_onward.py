"""After a death loop's hearth the member walks on to another zone (#2014).

WHY THIS EXISTS. The death loop's way out (guildjobs.death_loop_first, #1464)
hearths the member home. The hearth row lets go of the member when it lands,
and the member's own wandering then picks the nearest ground for its level,
which is the zone it was dying in; the next guild jobs pass comes 15 to 20
minutes later. Read on the dev realm on 2026-11-08: of 184 guild-job hearths
in a day, 58 were followed by another death in the zone just left within two
hours, and Jawless hearthed out of The Hinterlands to Hammerfall at 01:38 and
died in The Hinterlands again at 01:43.

So the hearth step carries a second row: once home, the member walks to the
flight master of a hub of another zone that fits its level, chosen from the
home, never the loop's zone. The walk holds it until it gets there.
"""

import dataclasses
import unittest

import deathloop
import guildjobs
import guildlevel
import guildroute
from test_guildlevel_open_quests import (
    HILLSBRAD,
    QUESTS,
    fact_rows,
    master_rows,
    member,
    spawn_of,
)

NAME = "Looper"
EASTERN_KINGDOMS = 0
# Goldshire's inn, in Elwynn Forest: far from every Hillsbrad hub.
GOLDSHIRE_INN = (-9459.0, 43.0)
ELWYNN = 12
HILLSBRAD_HUBS = {spawn_of("hillsbrad"), spawn_of("hillsbrad-a")}


def loop_of(name=NAME, level=26):
    return deathloop.Loop(
        name=name,
        zone=HILLSBRAD,
        map_id=EASTERN_KINGDOMS,
        deaths=7,
        killer="Hillsbrad Farmer",
        level=level,
        first_age=3000,
        last_age=120,
    )


def leveling(roster=()):
    w = guildlevel.world(QUESTS, master_rows(), fact_rows=fact_rows())
    if roster:
        w = dataclasses.replace(w, roster=frozenset(roster))
    return w


def plan(members, loops, world=None):
    return guildjobs.plan(
        members,
        masters={"Cave": "Grug", "Bonkers": "Zug"},
        leveling=world or leveling(),
        cap=guildroute.FAR_WALK_YARDS,
        recent=(),
        loops=loops,
    )


def bound_in_elwynn(**over):
    return member(
        NAME,
        rewarded=frozenset(),
        home_map=EASTERN_KINGDOMS,
        home_x=GOLDSHIRE_INN[0],
        home_y=GOLDSHIRE_INN[1],
        home_zone=ELWYNN,
        **over,
    )


def hearth_steps(result):
    return [s for s in result.steps if s.action == "hearth"]


class TheOnwardWalk(unittest.TestCase):
    def test_the_hearth_is_followed_by_a_walk_to_a_hub_of_another_zone(self):
        result = plan([bound_in_elwynn()], {NAME: loop_of()})
        (step,) = hearth_steps(result)
        self.assertEqual(len(step.rows), 2, step.rows)
        hearth, walk = step.rows
        self.assertEqual((hearth.kind, hearth.command), ("hearth", "use"))
        self.assertEqual(walk.kind, "job")
        self.assertTrue(walk.command.startswith("walk-to-spawn creature:"), walk)
        spawn = int(walk.command.split()[1].split(":")[1])
        self.assertNotIn(spawn, HILLSBRAD_HUBS)
        # Written as a level walk, so its cooldown and deadly-way reads see it.
        self.assertEqual(walk.source, guildjobs.source_for(guildlevel.ACTION, NAME))

    def test_the_walk_is_said(self):
        result = plan([bound_in_elwynn()], {NAME: loop_of()})
        (step,) = hearth_steps(result)
        self.assertIn("then walks on to", step.said)

    def test_the_walk_is_chosen_from_the_home_not_the_loop(self):
        step = guildjobs.death_loop_hearth(
            bound_in_elwynn(), loop_of(), (), leveling(), guildroute.FAR_WALK_YARDS
        )
        walk = step.rows[1]
        spawn = int(walk.command.split()[1].split(":")[1])
        choice = guildlevel.choose(
            26,
            1,
            EASTERN_KINGDOMS,
            leveling().bands.get("alliance", {}),
            leveling().masters,
            zone_id=ELWYNN,
            opens=guildlevel.member_opens(leveling(), 1, 26, frozenset()),
            avoid=HILLSBRAD,
        )
        self.assertEqual(spawn, int(choice.master.spawn))


class TheHearthAlone(unittest.TestCase):
    def test_no_world_read_keeps_the_hearth_alone(self):
        step = guildjobs.death_loop_hearth(bound_in_elwynn(), loop_of(), ())
        self.assertEqual([r.kind for r in step.rows], ["hearth"])

    def test_a_roster_member_keeps_the_hearth_alone(self):
        step = guildjobs.death_loop_hearth(
            bound_in_elwynn(),
            loop_of(),
            (),
            leveling(roster=(NAME,)),
            guildroute.FAR_WALK_YARDS,
        )
        self.assertEqual([r.kind for r in step.rows], ["hearth"])

    def test_an_unread_home_keeps_the_hearth_alone(self):
        step = guildjobs.death_loop_hearth(
            member(NAME, rewarded=frozenset()),
            loop_of(),
            (),
            leveling(),
            guildroute.FAR_WALK_YARDS,
        )
        self.assertEqual([r.kind for r in step.rows], ["hearth"])

    def test_a_member_at_the_cap_keeps_the_hearth_alone(self):
        m = bound_in_elwynn(level=guildlevel.LEVEL_CAP)
        step = guildjobs.death_loop_hearth(
            m,
            loop_of(level=guildlevel.LEVEL_CAP),
            (),
            leveling(),
            guildroute.FAR_WALK_YARDS,
        )
        self.assertEqual([r.kind for r in step.rows], ["hearth"])


if __name__ == "__main__":
    unittest.main()

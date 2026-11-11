"""A roster member in a death loop leaves its zone like anyone else (#1620).

WHY THIS EXISTS. The death loop's way out (guildjobs.death_loop_first,
#1464) is a hearth home, then the level walk to a hub of another zone. The
level walk refuses a roster family member outright (level_step: "never a
roster family member, levelroute walks those"), and nothing tells
levelroute about the loop: the family route only puts a zone the family
keeps dying in last, it never rules it out. So a roster member whose
hearth could not start (it was dead, fighting, or its hearthstone was
cooling when the pass ran) got the loop's third answer, "plans no quest
in the zone", pass after pass: no step, no walk, standing in the zone it
keeps dying in while its own AI picks the same ground after every
respawn. Measured on the dev realm: two roster members, levels 24 and
26, died 60+ times each in Hillsbrad Foothills over two days with the
death loop listed the whole time.

A roster member NOT in a death loop is still levelroute's to walk: the
refusal stands for the ordinary outgrown walk. Only the escape out of
the zone the member is dying in goes ahead of it.
"""

import unittest

import deathloop
import guildjobs
from test_guild_rest_supply import BATES
from test_guild_rest_supply import member as supply_member
import guildlevel
import guildroute
from test_guildlevel_open_quests import (
    HILLSBRAD,
    QUESTS,
    fact_rows,
    level_steps,
    master_rows,
    member,
    spawn_of,
)

NAME = "Looper"


def loop_of(name=NAME, level=26):
    return deathloop.Loop(
        name=name,
        zone=HILLSBRAD,
        map_id=0,
        deaths=7,
        killer="Hillsbrad Farmer",
        level=level,
        first_age=3000,
        last_age=120,
    )


def roster_world(*names):
    return guildlevel.world(QUESTS, master_rows(), roster=names, fact_rows=fact_rows())


def plain_world():
    return guildlevel.world(QUESTS, master_rows(), fact_rows=fact_rows())


def plan(members, w, recent=(), loops=None):
    return guildjobs.plan(
        members,
        masters={"Cave": "Grug", "Bonkers": "Zug"},
        leveling=w,
        cap=guildroute.FAR_WALK_YARDS,
        recent=recent,
        loops=loops or {},
    )


def hearth_cooling(name=NAME):
    """A hearth 30 minutes ago: inside the hearthstone's hour, so the
    loop's hearth rung cannot start and the walk has to be the way out."""
    return (guildjobs.Recent(name, "hearth", 30, "applied"),)


class TheRosterEscape(unittest.TestCase):
    def test_a_roster_member_in_a_death_loop_walks_out_when_it_cannot_hearth(self):
        # Nothing rewarded: Hillsbrad's quests have NOT run out for it, so
        # the deaths alone are the reason it leaves.
        m = member(NAME, rewarded=frozenset())
        result = plan(
            [m],
            roster_world(NAME),
            recent=hearth_cooling(),
            loops={NAME: loop_of()},
        )
        steps = level_steps(result)
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step.holder, NAME)
        # The walk leaves Hillsbrad: its target spawn is another hub's
        # flight master, named in the walk-to-spawn row.
        self.assertNotEqual(step.key, spawn_of("hillsbrad-a"))
        self.assertIn("walk-to-spawn creature:%d" % step.key, step.rows[0].command)
        self.assertIn("died 7 times in Hillsbrad Foothills", step.said)

    def test_a_roster_member_outgrown_without_a_loop_is_not_level_walked(self):
        # The ordinary refusal stands: levelroute walks the roster, so a
        # roster member whose Hillsbrad quests have run out (all rewarded)
        # gets no level step from the guild pass.
        import test_guildlevel_open_quests as oq

        m = member(NAME, rewarded=oq.done_in(HILLSBRAD))
        result = plan([m], roster_world(NAME))
        self.assertEqual(level_steps(result), [])

    def test_a_member_off_the_roster_in_a_death_loop_walks_out(self):
        m = member(NAME)
        result = plan(
            [m],
            plain_world(),
            recent=hearth_cooling(),
            loops={NAME: loop_of()},
        )
        self.assertEqual(len(level_steps(result)), 1)


if __name__ == "__main__":
    unittest.main()


# --- #2152: the escape first on every pass, or one logged reason ---------

CAP = guildroute.FAR_WALK_YARDS


def no_hub_world(*names):
    return guildlevel.world(QUESTS, [], roster=names, fact_rows=fact_rows())


def line_of(found):
    return found[2] if found and len(found) > 2 else ""


class TheEscapeComesFirst(unittest.TestCase):
    def test_in_the_zone_the_escape_beats_the_food_step(self):
        # Femur (test_guild_rest_supply) stands in its loop's zone, short of
        # food, with a vendor in reach: the hearth is issued, not the buy.
        m = supply_member()
        found = guildjobs.death_loop_first(
            m,
            deathloop.Loop(
                name=m.name,
                zone=130,
                map_id=0,
                deaths=6,
                killer="Giant Grizzled Bear",
                level=14,
                first_age=3000,
                last_age=120,
            ),
            None,
            (),
            CAP,
            supply=BATES,
        )
        self.assertIsNotNone(found)
        self.assertEqual(found[0].action, "hearth")

    def test_in_the_zone_the_escape_beats_the_ordinary_plan(self):
        m = member(NAME, rewarded=frozenset())
        result = plan([m], plain_world(), loops={NAME: loop_of()})
        self.assertEqual([s.action for s in result.steps], ["hearth"])


class OneLoggedReasonPerBranch(unittest.TestCase):
    def found(self, m, world, recent=(), campaign=""):
        return guildjobs.death_loop_first(
            m, loop_of(), world, recent, CAP, campaign=campaign, supply={}
        )

    def test_in_combat(self):
        found = self.found(member(NAME, in_combat=True), plain_world())
        self.assertIsNone(found[0])
        self.assertIn("in combat", line_of(found))

    def test_hearth_cooling(self):
        recent = hearth_cooling() + (
            guildjobs.Recent(NAME, guildlevel.ACTION, 30, "applied"),
        )
        found = self.found(member(NAME), plain_world(), recent=recent)
        self.assertIsNone(found[0])
        self.assertIn("hearth cooling", line_of(found))

    def test_no_reachable_hub(self):
        # Hearthstone bound in the loop's zone (the home test's Southshore
        # inn stands in Hillsbrad) and a world with no hub masters at all.
        m = member(
            NAME,
            home_map=0,
            home_x=-715.0,
            home_y=-512.0,
            home_zone=HILLSBRAD,
        )
        found = self.found(m, no_hub_world())
        self.assertIsNone(found[0])
        self.assertIn("no reachable hub", line_of(found))

    def test_roster_member(self):
        # Hearthed out to Goldshire within the resume window, on the roster:
        # the walk on refuses a roster member, and that is the logged reason.
        m = member(
            NAME,
            rewarded=frozenset(),
            zone_id=12,
            x=-9459.0,
            y=43.0,
            home_map=0,
            home_x=-9459.0,
            home_y=43.0,
            home_zone=12,
        )
        recent = (guildjobs.Recent(NAME, "hearth", 10, "applied"),)
        found = guildjobs.death_loop_first(
            m, loop_of(), roster_world(NAME), recent, CAP, supply={}
        )
        self.assertIsNotNone(found)
        self.assertIsNone(found[0])
        self.assertIn("roster member", line_of(found))

    def test_campaign_member(self):
        recent = hearth_cooling()
        found = self.found(
            member(NAME), roster_world(NAME), recent=recent, campaign="door"
        )
        self.assertIsNone(found[0])
        self.assertIn("campaign member", line_of(found))

    def test_dead(self):
        found = self.found(member(NAME, alive=False), plain_world())
        self.assertIsNone(found[0])
        self.assertIn("dead", line_of(found))

    def test_the_reason_is_one_line_in_the_plan_notes(self):
        m = member(NAME, in_combat=True)
        result = plan([m], plain_world(), loops={NAME: loop_of()})
        named = [n for n in result.notes if "gets no death-loop escape" in n]
        self.assertEqual(len(named), 1)
        self.assertIn("in combat", named[0])
        self.assertEqual(result.steps, ())


class OutOfTheZone(unittest.TestCase):
    def test_no_step_back_into_the_loop_zone(self):
        # Standing in Silverpine (130), outgrown there, loop in Hillsbrad:
        # any level step this pass must not land on a Hillsbrad hub spawn.
        m = member(NAME, zone_id=130, rewarded=frozenset())
        result = guildjobs.plan(
            [m],
            masters={"Cave": "Grug", "Bonkers": "Zug"},
            leveling=plain_world(),
            cap=CAP,
            loops={NAME: loop_of()},
        )
        hillsbrad_spawns = {spawn_of("hillsbrad"), spawn_of("hillsbrad-a")}
        for step in result.steps:
            self.assertNotIn(step.key, hillsbrad_spawns)

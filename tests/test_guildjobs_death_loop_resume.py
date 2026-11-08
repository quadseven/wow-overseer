"""A member that hearthed out of a death loop and was not walked on is walked on (#1882).

WHY THIS EXISTS. The hearth step of a death loop (guildjobs.death_loop_hearth)
writes the walk on to a hub of another zone in the same instant as the hearth,
and the hearth holds the member until it lands. Read on the dev realm on
2026-11-08: of 39 level walks written within five minutes of a hearth row, 33
were refused "character is held by another verb" and 6 started. Nothing asked
again: the member stood at its home out of the loop's zone, the loop rung
returned None, and its own wandering took it back into the zone it had left.
"""

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
)

NAME = "Looper"
EASTERN_KINGDOMS = 0
# Goldshire's inn, in Elwynn Forest: far from every Hillsbrad hub.
GOLDSHIRE_INN = (-9459.0, 43.0)
ELWYNN = 12
CAP = guildroute.FAR_WALK_YARDS


def loop_of(level=26):
    return deathloop.Loop(
        name=NAME,
        zone=HILLSBRAD,
        map_id=EASTERN_KINGDOMS,
        deaths=7,
        killer="Hillsbrad Farmer",
        level=level,
        first_age=3000,
        last_age=120,
    )


def world():
    return guildlevel.world(QUESTS, master_rows(), fact_rows=fact_rows())


def at_home(**over):
    """Hearthed home: standing in Goldshire, bound there, out of the loop zone."""
    base = dict(
        rewarded=frozenset(),
        home_map=EASTERN_KINGDOMS,
        home_x=GOLDSHIRE_INN[0],
        home_y=GOLDSHIRE_INN[1],
        home_zone=ELWYNN,
        x=GOLDSHIRE_INN[0],
        y=GOLDSHIRE_INN[1],
        zone_id=ELWYNN,
    )
    base.update(over)
    return member(NAME, **base)


def hearthed(age=3):
    return guildjobs.Recent(NAME, "hearth", age, "applied")


def refused_walk(age=3):
    return guildjobs.Recent(
        NAME,
        guildlevel.ACTION,
        age,
        "error",
        refusal="character is held by another verb",
        retryable=True,
        reason="character is held by another verb",
    )


def resume(m, recent):
    return guildjobs.death_loop_first(m, loop_of(), world(), recent, CAP)


class TheResumedWalk(unittest.TestCase):
    def test_a_landed_hearth_whose_walk_was_refused_is_walked_on_after_the_wait(self):
        # The refusal is a passing one: five minutes, then the walk again.
        found = resume(at_home(), (hearthed(8), refused_walk(8)))
        self.assertIsNotNone(found[0])
        step = found[0]
        self.assertEqual(step.action, guildlevel.ACTION)
        (walk,) = step.rows
        self.assertTrue(walk.command.startswith("walk-to-spawn creature:"), walk)
        self.assertEqual(walk.source, guildjobs.source_for(guildlevel.ACTION, NAME))
        self.assertIn("hearthed out of Hillsbrad Foothills", step.said)

    def test_the_walk_waits_out_the_refusal_it_just_had(self):
        self.assertEqual(resume(at_home(), (hearthed(3), refused_walk(3))), None)

    def test_a_walk_that_started_is_not_written_again(self):
        started = guildjobs.Recent(NAME, guildlevel.ACTION, 8, "applied")
        self.assertIsNone(resume(at_home(), (hearthed(9), started)))

    def test_no_recent_hearth_no_walk(self):
        self.assertIsNone(resume(at_home(), ()))
        old = guildjobs.Recent(NAME, "hearth", 200, "applied")
        self.assertIsNone(resume(at_home(), (old,)))

    def test_a_hearth_that_never_landed_is_not_resumed(self):
        failed = guildjobs.Recent(NAME, "hearth", 8, "error")
        self.assertIsNone(resume(at_home(), (failed,)))

    def test_a_member_still_in_the_loop_zone_is_left_to_the_loop_rungs(self):
        m = member(NAME, rewarded=frozenset())  # stands in Hillsbrad
        step = guildjobs.death_loop_resume(
            m, loop_of(), (hearthed(8), refused_walk(8)), world(), CAP
        )
        self.assertIsNone(step)

    def test_a_dead_member_is_walked_nowhere(self):
        m = at_home(alive=False)
        self.assertIsNone(resume(m, (hearthed(8), refused_walk(8))))

    def test_no_world_read_no_walk(self):
        self.assertIsNone(
            guildjobs.death_loop_resume(
                at_home(), loop_of(), (hearthed(8), refused_walk(8)), None, CAP
            )
        )


if __name__ == "__main__":
    unittest.main()

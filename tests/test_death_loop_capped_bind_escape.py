"""A death loop's escape for a member at the level cap whose hearthstone is
bound in the loop's zone (#2152).

WHY THIS EXISTS. Read on the dev realm on 2026-11-17: ten level-60 members
looped in Silithus, bound at Cenarion Hold. The loop's hearth skips a home in
the loop's zone (it only returns them), and its second rung, the level walk,
never starts at the level cap, so the pass logged "hearthstone bound in the
loop zone" and issued nothing: they died again and again with no step. The way
out for them is a walk to a hub of another zone and a new bind there, at that
hub's innkeeper (the module's own `bind` row, as inn_step writes it).
"""

import unittest

import deathloop
import guildjobs
import guildlevel
import guildroute
from test_guildlevel_bind import hub, inn_of, inn_rows
from test_guildlevel_open_quests import (
    KALIMDOR,
    QUESTS,
    SILITHUS,
    WINTERSPRING,
    fact_rows,
    master_rows,
    member,
    spawn_of,
)

NAME = "Capper"
LEVEL = guildlevel.LEVEL_CAP


def loop_of(name=NAME):
    return deathloop.Loop(
        name=name,
        zone=SILITHUS,
        map_id=KALIMDOR,
        deaths=9,
        killer="Hive'Ashi Drone",
        level=LEVEL,
        first_age=3000,
        last_age=120,
    )


def world():
    return guildlevel.world(
        QUESTS, master_rows(), fact_rows=fact_rows(), inn_rows=inn_rows()
    )


def at(key, **over):
    """A level 60 member standing 5 yards off a hub's flight point, bound at
    the Silithus hub's inn (inside the loop's zone)."""
    h = hub(key)
    inn = hub("silithus")
    base = dict(
        level=LEVEL,
        map_id=h.point[0],
        x=h.point[1] + 5.0,
        y=h.point[2],
        zone_id=h.zone_id,
        rewarded=frozenset(),
        home_map=inn.point[0],
        home_x=inn.point[1] + 40.0,
        home_y=inn.point[2],
        home_zone=SILITHUS,
    )
    base.update(over)
    return member(NAME, **base)


def plan(members, recent=(), loops=None):
    return guildjobs.plan(
        members,
        masters={"Cave": "Grug", "Bonkers": "Zug"},
        leveling=world(),
        cap=guildroute.FAR_WALK_YARDS,
        recent=tuple(recent),
        loops=loops if loops is not None else {NAME: loop_of()},
    )


def of(result, action):
    return [s for s in result.steps if s.holder == NAME and s.action == action]


class TheCappedMemberBoundInTheLoopZone(unittest.TestCase):
    def test_it_does_not_hearth_back_into_the_zone(self):
        result = plan([at("silithus")])
        self.assertEqual(of(result, "hearth"), [])

    def test_it_walks_to_a_hub_of_another_zone(self):
        steps = of(plan([at("silithus")]), guildlevel.ACTION)
        self.assertEqual(len(steps), 1)
        self.assertNotIn(
            steps[0].key, (0, spawn_of("silithus"), spawn_of("silithus-a"))
        )

    def test_its_walk_never_chooses_the_loop_zone(self):
        w = world()
        m = at("silithus")
        step, _doing, _note, _ = guildjobs.death_loop_first(
            m, loop_of(), w, (), guildroute.FAR_WALK_YARDS
        )
        self.assertIsNotNone(step)
        self.assertNotIn("Cenarion Hold", step.goal)

    def test_a_capped_member_out_of_a_loop_still_has_no_level_walk(self):
        # The cap blocks the level walk everywhere but a loop's own zone.
        result = plan([at("silithus")], loops={})
        self.assertEqual(of(result, guildlevel.ACTION), [])


class TheNewBind(unittest.TestCase):
    def test_a_capped_member_out_of_the_zone_binds_at_the_hubs_inn(self):
        steps = of(plan([at("winterspring")]), guildlevel.INN_ACTION)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].key, inn_of("winterspring-a"))
        self.assertEqual(steps[0].rows[0].kind, "bind")

    def test_it_does_not_bind_in_the_loop_zone(self):
        result = plan([at("silithus")])
        self.assertEqual(of(result, guildlevel.INN_ACTION), [])

    def test_a_member_bound_outside_the_loop_zone_is_not_rebound(self):
        w = hub("winterspring")
        m = at(
            "winterspring",
            home_map=w.point[0],
            home_x=w.point[1] + 40.0,
            home_y=w.point[2],
            home_zone=WINTERSPRING,
        )
        self.assertEqual(of(plan([m]), guildlevel.INN_ACTION), [])

    def test_a_capped_member_with_no_loop_is_never_rebound(self):
        result = plan([at("winterspring")], loops={})
        self.assertEqual(of(result, guildlevel.INN_ACTION), [])


if __name__ == "__main__":
    unittest.main()

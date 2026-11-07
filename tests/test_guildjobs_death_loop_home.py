"""A death loop's hearth is skipped when the hearth is bound in the loop's zone (#1882).

WHY THIS EXISTS. The death loop's way out (guildjobs.death_loop_first, #1464)
is a hearth home first, then the level walk to a hub of another zone. inn_step
binds a member's hearthstone at the inn of the zone it levels in, so the zone
a member keeps dying in is often the zone its hearth is bound in, and the
hearth put it straight back there. Measured on the dev realm on 2026-11-07:
of 138 death-loop hearths, 52 were followed by three or more deaths in the same
zone within three hours; 10 of the 11 members bound at Brackenwall Village
that hearthed out of a Dustwallow Marsh loop died there again.

The home's zone is read from where the hearth is bound, not from the row's
zoneId: once a member binds at an inn, the core writes the inn's AREA id there
(Brackenwall Village 496, not Dustwallow Marsh 15).
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
    level_steps,
    master_rows,
    member,
    spawn_of,
)

NAME = "Looper"
EASTERN_KINGDOMS = 0
KALIMDOR = 1
# Southshore's inn, a few yards off its flight point (taxi node 14).
SOUTHSHORE_INN = (-715.0, -512.0)
# The area id the core writes for a hearth bound at that inn: not a zone id.
SOUTHSHORE_AREA = 271
# Brackenwall Village's inn and the area id written for it, read off the dev
# realm's character_homebind on 2026-11-07.
BRACKENWALL_INN = (-3160.87, -2908.86)
BRACKENWALL_AREA = 496
DUSTWALLOW = 15
# Goldshire's inn, in Elwynn Forest: far from every Hillsbrad hub.
GOLDSHIRE_INN = (-9459.0, 43.0)
ELWYNN = 12


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


def plan(members, recent=(), loops=None):
    return guildjobs.plan(
        members,
        masters={"Cave": "Grug", "Bonkers": "Zug"},
        leveling=guildlevel.world(QUESTS, master_rows(), fact_rows=fact_rows()),
        cap=guildroute.FAR_WALK_YARDS,
        recent=recent,
        loops=loops or {},
    )


def bound_at(inn, area, **over):
    return member(
        NAME,
        rewarded=frozenset(),
        home_map=EASTERN_KINGDOMS,
        home_x=inn[0],
        home_y=inn[1],
        home_zone=area,
        **over,
    )


def hearth_steps(result):
    return [s for s in result.steps if s.action == "hearth"]


class TheHomeZone(unittest.TestCase):
    def test_a_home_at_a_hubs_inn_is_in_the_hubs_zone_whatever_the_area_id(self):
        self.assertEqual(
            DUSTWALLOW,
            guildlevel.home_zone_of(KALIMDOR, *BRACKENWALL_INN, BRACKENWALL_AREA),
        )

    def test_a_home_near_no_hub_keeps_the_rows_own_id(self):
        # A hearth never moved off its starting inn: the row holds a zone id.
        self.assertEqual(14, guildlevel.home_zone_of(KALIMDOR, 3000.0, 3000.0, 14))

    def test_an_unread_home_is_none(self):
        self.assertIsNone(guildlevel.home_zone_of(None, None, None, None))

    def test_the_hub_must_be_on_the_homes_map(self):
        # Brackenwall's coordinates on the other continent are no Brackenwall.
        self.assertEqual(
            BRACKENWALL_AREA,
            guildlevel.home_zone_of(
                EASTERN_KINGDOMS, *BRACKENWALL_INN, BRACKENWALL_AREA
            ),
        )


class TheLoopHearth(unittest.TestCase):
    def test_a_member_bound_in_the_loop_zone_walks_out_instead_of_hearthing(self):
        m = bound_at(SOUTHSHORE_INN, SOUTHSHORE_AREA)
        result = plan([m], loops={NAME: loop_of()})
        self.assertEqual(hearth_steps(result), [])
        steps = level_steps(result)
        self.assertEqual(len(steps), 1)
        self.assertNotEqual(steps[0].key, spawn_of("hillsbrad-a"))
        self.assertIn("died 7 times in Hillsbrad Foothills", steps[0].said)

    def test_the_skipped_hearth_is_said(self):
        m = bound_at(SOUTHSHORE_INN, SOUTHSHORE_AREA)
        loop = loop_of()
        _step, _doing, note, _ = guildjobs.death_loop_first(
            m,
            loop,
            guildlevel.world(QUESTS, master_rows(), fact_rows=fact_rows()),
            (),
            guildroute.FAR_WALK_YARDS,
        )
        self.assertIn(
            "Looper does not hearth: its hearthstone is bound in Hillsbrad "
            "Foothills, the zone it keeps dying in",
            note,
        )

    def test_a_member_bound_in_another_zone_still_hearths_first(self):
        m = member(
            NAME,
            rewarded=frozenset(),
            home_map=EASTERN_KINGDOMS,
            home_x=GOLDSHIRE_INN[0],
            home_y=GOLDSHIRE_INN[1],
            home_zone=ELWYNN,
        )
        result = plan([m], loops={NAME: loop_of()})
        self.assertEqual([s.holder for s in hearth_steps(result)], [NAME])

    def test_a_member_whose_home_is_unread_still_hearths_first(self):
        m = member(NAME, rewarded=frozenset())
        result = plan([m], loops={NAME: loop_of()})
        self.assertEqual([s.holder for s in hearth_steps(result)], [NAME])


if __name__ == "__main__":
    unittest.main()

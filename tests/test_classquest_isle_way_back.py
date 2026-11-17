"""A class quest set on map 530 is reached again from Kalimdor (#2052).

A Draenei whose class quest is set on the isles it started on (map 530) and
who has since crossed to Kalimdor had no way back for it. `classquest.far_map`
knows only the two classic continents, so a quest whose every spawn is on map
530 read from Kalimdor as the plain MAP blocker ("on another map than the
member") and no `cross-to-map map:530` row was ever asked. Since an outgrown
islander takes its level crossing with an isle class quest still open, that
blocker never cleared. Example: Call of Fire (quest 9467), whose spawns are
all on map 530.

The Alliance's boat between Auberdine in Darkshore and Valaar's Berth on
Azuremyst Isle sails both ways, and the module prices it from its own
transport catalogue. These tests hold the planner to that boat: the crossing
back is asked from the continent it sails from, by the side it carries, and
anybody else is told which way back is missing.
"""

import unittest

import classquest
import guildlevel
import levelroute
from test_classquest import EASTERN, KALIMDOR, ORC, class_plan, givers, qrow, who
from test_classquest import book as classic_book

ISLE = 530
DRAENEI = 11
EVERY_RACE = 0
NO_ROUTE = (
    "no transport the module knows sails from this map to that map for this faction"
)


def on_the_isle(row):
    return dict(row, map_id=ISLE)


def chain_rows():
    return [
        qrow(1505, "Veteran Uzzek", races=EVERY_RACE),
        qrow(
            1498,
            "Path of Defense",
            races=EVERY_RACE,
            prev=1505,
            reward=8121,
            item1=6486,
            item_count1=5,
        ),
    ]


def chain_givers():
    return [g for g in givers() if g["quest"] in (1505, 1498)]


def isle_book():
    """The warrior chain of test_classquest with every giver spawn moved to
    map 530, open to every race."""
    isle_givers = [on_the_isle(g) for g in chain_givers()]
    return classic_book(quest_rows=chain_rows(), giver_rows=isle_givers, spawn_rows=[])


def draenei(**over):
    base = dict(race=DRAENEI, map_id=KALIMDOR, x=6400.0, y=500.0, zone_id=148)
    base.update(over)
    return who("Velo", **base)


class TheWayBack(unittest.TestCase):
    def test_a_draenei_on_kalimdor_crosses_back_to_the_isle(self):
        move, blocked = classquest.next_move(isle_book(), draenei())
        self.assertIsNotNone(move, blocked)
        self.assertEqual((move.kind, move.to_map), (classquest.CROSS, ISLE))
        self.assertEqual(blocked, [])
        self.assertIn("map 530", move.said)

    def test_the_step_is_one_cross_row_to_map_530(self):
        steps = [
            s
            for s in class_plan([draenei()], isle_book()).steps
            if s.rows and classquest.is_cross_row(s.rows[0].command)
        ]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].rows[0].command, "cross-to-map map:530")
        self.assertIsNone(steps[0].walk)
        self.assertIn("map 530", steps[0].goal)

    def test_a_refused_crossing_back_keeps_the_modules_reason(self):
        m = draenei(no_crossing={ISLE: NO_ROUTE})
        move, blocked = classquest.next_move(isle_book(), m)
        self.assertIsNone(move)
        self.assertIn("map 530", blocked[0])
        self.assertIn("no transport the module knows", blocked[0])

    def test_a_refusal_for_kalimdor_does_not_wall_the_isle(self):
        m = draenei(no_crossing={KALIMDOR: NO_ROUTE})
        move, _blocked = classquest.next_move(isle_book(), m)
        self.assertEqual((move.kind, move.to_map), (classquest.CROSS, ISLE))


class NoWayBack(unittest.TestCase):
    def test_from_the_eastern_kingdoms_the_blocker_names_where_the_boat_sails(self):
        m = draenei(map_id=EASTERN, x=-3800.0, y=-600.0, zone_id=11)
        move, blocked = classquest.next_move(isle_book(), m)
        self.assertIsNone(move)
        self.assertIn("map 530", blocked[0])
        self.assertIn("sails from Kalimdor", blocked[0])
        self.assertIn("not from Eastern Kingdoms", blocked[0])

    def test_a_side_with_no_boat_there_is_told_so(self):
        move, blocked = classquest.next_move(isle_book(), who(race=ORC))
        self.assertIsNone(move)
        self.assertIn("map 530", blocked[0])
        self.assertIn("no boat or zeppelin", blocked[0])


class Unchanged(unittest.TestCase):
    def test_a_member_on_map_530_walks_to_its_own_maps_spawns(self):
        m = draenei(map_id=ISLE, x=300.0, y=-4800.0, zone_id=3524)
        move, _blocked = classquest.next_move(isle_book(), m)
        self.assertIsNotNone(move)
        self.assertNotEqual(move.kind, classquest.CROSS)

    def test_a_member_on_map_530_does_not_cross_for_a_classic_quest(self):
        m = draenei(map_id=ISLE, x=0.0, y=0.0, zone_id=3524)
        book = classic_book(
            quest_rows=chain_rows(), giver_rows=chain_givers(), spawn_rows=[]
        )
        move, blocked = classquest.next_move(book, m)
        self.assertIsNone(move)
        self.assertIn("map", blocked[0])

    def test_far_map_still_names_only_the_classic_continents(self):
        # questers.py reads far_map and indexes CONTINENTS with its answer.
        quest = isle_book().quests[1505]
        self.assertEqual(classquest.far_map(draenei(), list(quest.starters)), -1)


class TheCatalogue(unittest.TestCase):
    """classquest stays import-free, so its copy of which side's boat serves
    map 530, and from which continent, is held to guildlevel's and
    levelroute's here."""

    def test_the_boat_and_its_continent_match_guildlevels(self):
        for race, sails_from in classquest.ISLE_BOAT_FROM.items():
            side = guildlevel.side_of(race)
            self.assertEqual(guildlevel.BOAT_EXITS.get(side), sails_from, race)

    def test_every_race_of_a_side_with_a_boat_is_listed(self):
        for side, sails_from in guildlevel.BOAT_EXITS.items():
            mask = levelroute.RACE_MASK[side]
            races = {r for r in range(1, 12) if mask & (1 << (r - 1))}
            self.assertEqual(
                {r for r, c in classquest.ISLE_BOAT_FROM.items() if c == sails_from},
                races,
            )


if __name__ == "__main__":
    unittest.main()

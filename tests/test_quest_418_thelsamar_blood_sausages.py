"""Thelsamar Blood Sausages (quest 418, Loch Modan, level 11) waits for its last
ingredient's levels instead of being dropped as stalled.

The quest asks for three ingredients, three of each: Boar Intestines (3172),
Bear Meat (3173) and Spider Ichor (3174), each dropped by many creatures. A
quester that has gathered two of them and holds the third with every dropper of
that third over its level (classquest.OVERLEVEL_MAX above it) can hunt nothing
the quest still needs, so it is waiting for its levels, as quest 25 was (#1728).
Two things kept its stall clock running anyway:

  - `_unhuntable` counted the droppers of the ingredients already gathered, which
    the hunt skips, so the clock waited for spawns nobody would hunt; and
  - a quest that was the last move's (`last_quest`) runs the clock whether or
    not it can be hunted, so two hours later it was dropped as stalled.

The creature entries are the ticket's world rows. Their levels are invented:
the lane could not read the world, and the test fixes them to show the rule.
The rows are shaped as questers.catalogue reads them, through the helpers of
test_questers.
"""

import unittest

import classquest
import questers
from test_questers import HUMAN, LOCH_MODAN, PRIEST, giver, mirra, quest, spawn, world

THELSAMAR_BLOOD_SAUSAGES = 418
BOAR_INTESTINES = 3172
BEAR_MEAT = 3173
SPIDER_ICHOR = 3174
INGREDIENTS = {
    BOAR_INTESTINES: (
        157,
        345,
        454,
        547,
        1190,
        1191,
        1192,
        4422,
        4511,
        4512,
        4514,
        7333,
        7334,
    ),
    BEAR_MEAT: (
        822,
        1130,
        1186,
        1188,
        1189,
        1225,
        1778,
        1797,
        1961,
        2163,
        2164,
        2165,
        2354,
        2356,
        3809,
        3810,
        3811,
        6788,
        12432,
        17347,
        17348,
        17661,
    ),
    SPIDER_ICHOR: (
        217,
        442,
        471,
        505,
        539,
        569,
        574,
        616,
        930,
        949,
        1111,
        1112,
        1184,
        1185,
        1195,
        1780,
        1781,
        3819,
        3820,
        3821,
        4005,
        4006,
        4007,
        4040,
        4263,
        4264,
        11921,
        12433,
        14266,
    ),
}
WANTED = 3
QUEST_LEVEL = 11
MIN_LEVEL = 7
# Invented levels: the boars and spiders are within reach of the quester; the
# bears are over its level (11 + OVERLEVEL_MAX = 14), so they are not hunted yet.
INREACH_LEVEL = 10
BEAR_LEVEL = 15
TWO_HOURS_OF_PASSES = 13


def thelsamar_world():
    row = quest(
        THELSAMAR_BLOOD_SAUSAGES,
        LOCH_MODAN,
        QUEST_LEVEL,
        min_level=MIN_LEVEL,
        title="Thelsamar Blood Sausages",
    )
    for i, item in enumerate(INGREDIENTS, start=1):
        row.update({"item%d" % i: item, "item_count%d" % i: WANTED})
    spawns, loot, guid = [], [], 9000
    for item, entries in INGREDIENTS.items():
        level = BEAR_LEVEL if item == BEAR_MEAT else INREACH_LEVEL
        for entry in entries:
            guid += 1
            spawns.append(spawn(guid, entry, 100.0 + guid, 100.0, level=level))
            loot.append({"item": item, "entry": entry})
    return world(
        extra_quests=[row],
        extra_givers=[
            giver(THELSAMAR_BLOOD_SAUSAGES, "start", 5418, 235, 0, 0),
            giver(THELSAMAR_BLOOD_SAUSAGES, "end", 5418, 235, 0, 0),
        ],
        extra_spawns=spawns,
        extra_loot=loot,
    )


def holder(level=11, counts=None):
    """Mirra in Loch Modan, holding the quest with these ingredient counts."""
    counts = counts or {BOAR_INTESTINES: WANTED, BEAR_MEAT: 0, SPIDER_ICHOR: WANTED}
    return mirra(
        name="Mirra",
        level=level,
        race=HUMAN,
        class_id=PRIEST,
        zone_id=LOCH_MODAN,
        x=0.0,
        y=0.0,
        quest_log={THELSAMAR_BLOOD_SAUSAGES: questers.STATUS_INCOMPLETE},
        quest_progress={THELSAMAR_BLOOD_SAUSAGES: sum(counts.values())},
        quest_item_objectives={THELSAMAR_BLOOD_SAUSAGES: counts},
    )


def two_hours_of_play(cat, member, last_quest) -> questers.Plan:
    """The Plan of the pass after two hours of play with nothing moved."""
    clock = questers.Clock()
    plan = questers.plan(cat, member, clock, 0.0, last_quest=last_quest)
    for i in range(1, TWO_HOURS_OF_PASSES):
        plan = questers.plan(cat, member, clock, 600.0 * i, last_quest=last_quest)
    return plan


class AQuesterWaitingForItsLevelIsNotStalled(unittest.TestCase):
    def test_two_hours_after_its_last_move_it_is_not_dropped(self):
        plan = two_hours_of_play(
            thelsamar_world(), holder(), last_quest=THELSAMAR_BLOOD_SAUSAGES
        )
        self.assertEqual([b.quest for b in plan.broken], [])

    def test_two_hours_with_no_last_move_it_is_not_dropped(self):
        plan = two_hours_of_play(thelsamar_world(), holder(), last_quest=0)
        self.assertEqual([b.quest for b in plan.broken], [])

    def test_its_clock_waits_while_the_last_ingredient_is_over_its_level(self):
        self.assertFalse(
            questers._unhuntable(thelsamar_world(), holder(), THELSAMAR_BLOOD_SAUSAGES)
        )

    def test_gathered_ingredients_are_not_hunted_even_in_level(self):
        # At level 15 the boars and spiders are in level too, but both
        # ingredients are gathered: only the bears are still worth hunting.
        cat = thelsamar_world()
        quest_row = cat.quest(THELSAMAR_BLOOD_SAUSAGES)
        fields = questers._held_objective_fields(
            holder(level=15), THELSAMAR_BLOOD_SAUSAGES, quest_row
        )
        self.assertEqual({s.entry for s in fields}, set(INGREDIENTS[BEAR_MEAT]))


class AQuesterHuntsTheLastIngredientOnceItLevels(unittest.TestCase):
    def test_at_level_fifteen_it_hunts_a_bear(self):
        cat = thelsamar_world()
        move = questers.plan(cat, holder(level=15), questers.Clock(), 0.0).move
        self.assertEqual(
            (move.kind, move.quest), (classquest.HUNT, THELSAMAR_BLOOD_SAUSAGES)
        )
        self.assertIn(move.spot.entry, INGREDIENTS[BEAR_MEAT])


if __name__ == "__main__":
    unittest.main()

"""Elixir of Pain (quest 501) hunts for its ten Mountain Lion Blood items.

The quest, item and creature entry rows come from the ticket. Quest, giver,
spawn and log rows use the shapes read by questers.QUESTS_SQL,
classquest.LOOT_SQL, classquest.SPAWNS_SQL and questers.LOG_SQL. Giver and
spawn GUIDs, positions and levels are fixture values, not claims about the
world.
"""

import unittest

import classhunt
import classquest
import questers
from test_questers import HUMAN, PRIEST, giver, quest, spawn, world

ELIXIR_OF_PAIN = 501
HILLSBRAD_FOOTHILLS = 267
MOUNTAIN_LION_BLOOD = 3496
MOUNTAIN_LIONS = (2384, 2385, 2406, 2407)
WANTED_BLOOD = 10


def elixir_world():
    elixir = quest(
        ELIXIR_OF_PAIN,
        HILLSBRAD_FOOTHILLS,
        24,
        min_level=21,
        title="Elixir of Pain",
    )
    elixir.update(item1=MOUNTAIN_LION_BLOOD, item_count1=WANTED_BLOOD)
    return world(
        extra_quests=[elixir],
        extra_givers=[
            giver(ELIXIR_OF_PAIN, "start", 9501, 9501, 400, 0),
            giver(ELIXIR_OF_PAIN, "end", 9502, 9502, 500, 0),
        ],
        extra_spawns=[
            spawn(9600 + index, entry, 100.0 + 30 * index, 0, level=24)
            for index, entry in enumerate(MOUNTAIN_LIONS)
        ],
        extra_loot=[
            {"item": MOUNTAIN_LION_BLOOD, "entry": entry} for entry in MOUNTAIN_LIONS
        ],
    )


def elixir_quester(blood, status=questers.STATUS_INCOMPLETE):
    """A quester built from the member and LOG_SQL row shapes."""
    member_row = {
        "guid": 1,
        "name": "Quest Tester",
        "level": 24,
        "race": HUMAN,
        "class_id": PRIEST,
        "online": 1,
        "map_id": 0,
        "pos_x": 0.0,
        "pos_y": 0.0,
        "zone_id": HILLSBRAD_FOOTHILLS,
    }
    log_row = {
        "guid": 1,
        "quest": ELIXIR_OF_PAIN,
        "status": status,
        "progress": blood,
        "npc1": 0,
        "npc2": 0,
        "npc3": 0,
        "npc4": 0,
        "mobcount1": 0,
        "mobcount2": 0,
        "mobcount3": 0,
        "mobcount4": 0,
        "item1": MOUNTAIN_LION_BLOOD,
        "itemcount1": blood,
        "item2": 0,
        "itemcount2": 0,
        "item3": 0,
        "itemcount3": 0,
        "item4": 0,
        "itemcount4": 0,
        "item5": 0,
        "itemcount5": 0,
        "item6": 0,
        "itemcount6": 0,
    }
    return questers.members_from_rows([member_row], [log_row], [])[0]


class ElixirOfPain(unittest.TestCase):
    def test_partial_item_progress_keeps_hunt_target_at_ten(self):
        cat = elixir_world()
        member = elixir_quester(4)

        plan = questers.plan(cat, member, questers.Clock(), 0.0)
        step = questers.step_for(member, plan.move, 0, cat.quest(ELIXIR_OF_PAIN))

        self.assertEqual(
            (plan.move.kind, plan.move.quest), (classquest.HUNT, ELIXIR_OF_PAIN)
        )
        self.assertEqual(
            [row.command for row in step.rows],
            [
                "hunt-spawn creature:2384 item:3496 count:10 max:%d"
                % classhunt.MAX_SECONDS
            ],
        )

    def test_ten_items_make_the_quest_ready_for_turn_in(self):
        cat = elixir_world()
        member = elixir_quester(WANTED_BLOOD)

        move = questers.plan(cat, member, questers.Clock(), 0.0).move

        self.assertEqual((move.kind, move.quest), (classquest.TURN_IN, ELIXIR_OF_PAIN))

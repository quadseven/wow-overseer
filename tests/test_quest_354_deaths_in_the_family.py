"""Deaths in the Family (quest 354, Tirisfal Glades, level 11) is broken:
the required items have no huntable source in the world.

The quest asks for three items, one each: Gregor's Remains (2829) from
creature 1654, Nissa's Remains (2828) from creature 1655, and Thurman's
Remains (2830) from creature 1656. The world rows name these creatures as
the sources, but they have no spawns in Tirisfal Glades (or do not drop the
items), so the items have no huntable source. A quester that takes the quest
stands with all objectives at zero for two hours and is filed as stalled.

The creature entries are the ticket's world rows. The test fixes them to
have no spawns, showing the rule. The rows are shaped as questers.catalogue
reads them, through the helpers of test_questers.
"""

import unittest

import classquest
import questers
from tests.test_questers import ORC, giver, quest, spawn, world

# Constants from test_questers_eligibility
TIRISFAL = 85
TAUREN = 6


DEATHS_IN_THE_FAMILY = 354
GREGORS_REMAINS = 2829
NISSAS_REMAINS = 2828
THURMANS_REMAINS = 2830
INGREDIENTS = {
    GREGORS_REMAINS: 1654,
    NISSAS_REMAINS: 1655,
    THURMANS_REMAINS: 1656,
}
WANTED = 1
QUEST_LEVEL = 11
MIN_LEVEL = 7
TWO_HOURS_OF_PASSES = 13


def deaths_world_no_spawns():
    """World where the quest exists but its source creatures have no spawns."""
    row = quest(
        DEATHS_IN_THE_FAMILY,
        TIRISFAL,
        QUEST_LEVEL,
        min_level=MIN_LEVEL,
        title="Deaths in the Family",
    )
    for i, (item, entry) in enumerate(INGREDIENTS.items(), start=1):
        row.update({"item%d" % i: item, "item_count%d" % i: WANTED})
    # No spawns for the source creatures, no loot linking them to the items
    return world(
        extra_quests=[row],
        extra_givers=[
            giver(DEATHS_IN_THE_FAMILY, "start", 5418, 235, 0, 0),
            giver(DEATHS_IN_THE_FAMILY, "end", 5418, 235, 0, 0),
        ],
        extra_spawns=[],
        extra_loot=[],
    )


def deaths_world_with_spawns():
    """World where the quest exists and its source creatures have spawns (for comparison)."""
    row = quest(
        DEATHS_IN_THE_FAMILY,
        TIRISFAL,
        QUEST_LEVEL,
        min_level=MIN_LEVEL,
        title="Deaths in the Family",
    )
    for i, (item, entry) in enumerate(INGREDIENTS.items(), start=1):
        row.update({"item%d" % i: item, "item_count%d" % i: WANTED})
    spawns, loot, guid = [], [], 9000
    for item, entry in INGREDIENTS.items():
        guid += 1
        spawns.append(spawn(guid, entry, 100.0 + guid, 100.0, level=10))
        loot.append({"item": item, "entry": entry})
    return world(
        extra_quests=[row],
        extra_givers=[
            giver(DEATHS_IN_THE_FAMILY, "start", 5418, 235, 0, 0),
            giver(DEATHS_IN_THE_FAMILY, "end", 5418, 235, 0, 0),
        ],
        extra_spawns=spawns,
        extra_loot=loot,
    )


def holder(
    level=11, counts=None, race=ORC, status=questers.STATUS_INCOMPLETE, quest_log=None
):
    """A quester in Tirisfal Glades holding quest 354 with these counts."""
    counts = counts or {item: 0 for item in INGREDIENTS}
    if quest_log is None:
        quest_log = {DEATHS_IN_THE_FAMILY: status}
    base = {
        "name": "Grakk",
        "level": level,
        "race": race,
        "class_id": 9,  # Warlock
        "map_id": 0,
        "x": 0.0,
        "y": 0.0,
        "zone_id": TIRISFAL,
        "online": True,
        "quest_log": quest_log,
        "quest_progress": {DEATHS_IN_THE_FAMILY: sum(counts.values())},
        "quest_objectives": {
            DEATHS_IN_THE_FAMILY: {
                entry: counts.get(item, 0) for item, entry in INGREDIENTS.items()
            }
        },
        "quest_item_objectives": {DEATHS_IN_THE_FAMILY: counts},
    }
    return questers.Member(**base)


def two_hours_of_play(cat, member, last_quest) -> questers.Plan:
    """The Plan of the pass after two hours of play with nothing moved."""
    clock = questers.Clock()
    plan = questers.plan(cat, member, clock, 0.0, last_quest=last_quest)
    for i in range(1, TWO_HOURS_OF_PASSES):
        plan = questers.plan(cat, member, clock, 600.0 * i, last_quest=last_quest)
    return plan


class DeathsInTheFamilyHasNoHuntableSource(unittest.TestCase):
    def test_quest_is_not_in_reach_when_no_spawns(self):
        """The quest is not offered when its items have no huntable source."""
        cat = deaths_world_no_spawns()
        member = holder(quest_log={})  # Not holding it yet
        self.assertNotIn(DEATHS_IN_THE_FAMILY, questers.in_reach(cat, member, TIRISFAL))
        # The quest has no fields (spawns) for its objectives
        quest_obj = cat.quest(DEATHS_IN_THE_FAMILY)
        self.assertEqual(quest_obj.fields, ())
        self.assertEqual(quest_obj.drops, ())

    def test_quester_holds_it_and_stalls_with_specific_reason(self):
        """A quester holding the quest stalls with a specific reason naming the items."""
        cat = deaths_world_no_spawns()
        member = holder()
        clock = questers.Clock()
        plan = questers.plan(cat, member, clock, 0.0, last_quest=DEATHS_IN_THE_FAMILY)
        # Initially no broken (clock hasn't run yet)
        self.assertEqual(plan.broken, ())
        # After two hours of no progress
        for i in range(1, TWO_HOURS_OF_PASSES):
            plan = questers.plan(
                cat, member, clock, 600.0 * i, last_quest=DEATHS_IN_THE_FAMILY
            )
        self.assertEqual(len(plan.broken), 1)
        self.assertEqual(plan.broken[0].quest, DEATHS_IN_THE_FAMILY)
        reason = plan.broken[0].reason
        # The reason should be the specific DEATHS_IN_THE_FAMILY reason
        self.assertIn("Gregor's Remains", reason)
        self.assertIn("Nissa's Remains", reason)
        self.assertIn("Thurman's Remains", reason)
        self.assertIn("2829", reason)
        self.assertIn("2828", reason)
        self.assertIn("2830", reason)
        self.assertIn("no spawned creature drops", reason)

    def test_ledger_reason_explains_the_missing_sources(self):
        """The broken reason names the specific items and creatures."""
        cat = deaths_world_no_spawns()
        member = holder()
        clock = questers.Clock()
        for i in range(TWO_HOURS_OF_PASSES):
            plan = questers.plan(
                cat, member, clock, 600.0 * i, last_quest=DEATHS_IN_THE_FAMILY
            )
        reason = plan.broken[0].reason
        # The reason should mention the items and that they have no source
        self.assertIn("Gregor's Remains", reason)
        self.assertIn("Nissa's Remains", reason)
        self.assertIn("Thurman's Remains", reason)
        self.assertIn("2829", reason)
        self.assertIn("2828", reason)
        self.assertIn("2830", reason)
        self.assertIn("no spawned creature drops", reason)


class DeathsInTheFamilyWithSpawnsWorks(unittest.TestCase):
    """When the world provides spawns and loot, the quest works normally."""

    def test_quester_can_finish_it(self):
        cat = deaths_world_with_spawns()
        # The quester hunts each creature in turn
        counts = {}
        for _ in INGREDIENTS:
            move = questers.plan(cat, holder(counts=counts), questers.Clock(), 0.0).move
            self.assertEqual(
                (move.kind, move.quest), (classquest.HUNT, DEATHS_IN_THE_FAMILY)
            )
            item = next(i for i, e in INGREDIENTS.items() if e == move.spot.entry)
            self.assertLess(counts.get(item, 0), WANTED)
            counts[item] = WANTED
        # All items gathered, quest is complete and handed in
        full = {item: WANTED for item in INGREDIENTS}
        move = questers.plan(
            cat,
            holder(counts=full, status=questers.STATUS_COMPLETE),
            questers.Clock(),
            0.0,
        ).move
        self.assertEqual(
            (move.kind, move.quest), (classquest.TURN_IN, DEATHS_IN_THE_FAMILY)
        )

    def test_it_stalls_when_no_progress_is_made(self):
        """A huntable quest still stalls if the quester makes no progress for 2 hours."""
        cat = deaths_world_with_spawns()
        member = holder()
        clock = questers.Clock()
        for i in range(TWO_HOURS_OF_PASSES):
            plan = questers.plan(
                cat, member, clock, 600.0 * i, last_quest=DEATHS_IN_THE_FAMILY
            )
        self.assertEqual(len(plan.broken), 1)
        self.assertEqual(plan.broken[0].quest, DEATHS_IN_THE_FAMILY)
        self.assertEqual(plan.broken[0].reason, questers.STALLED)


if __name__ == "__main__":
    unittest.main()

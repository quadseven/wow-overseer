"""Dungeon quest pickup and turn-in for a queued campaign.

The acceptance criteria the module must meet:

* Before the first Zul'Farrak run, the family holds eligible dungeon quests
  read from the world database.
* Between runs, completed dungeon quests are turned in and follow-ups picked
  up.
* No quest data is hand-authored: every quest read comes from `QUEST_SQL`'s
  world-database query.

These are pure decisions over rows, so they are asserted here without a
database.
"""

import unittest

import dungeonquests

ZULFARRAK_ZONE = 978


def _quest(
    quest_id,
    prev_quest_id=0,
    starter=1000,
    ender=1000,
    zone=ZULFARRAK_ZONE,
    min_level=45,
    races=0,
):
    return dungeonquests.Quest(
        quest_id=quest_id,
        zone=zone,
        min_level=min_level,
        races=races,
        prev_quest_id=prev_quest_id,
        starter=starter,
        ender=ender,
    )


def _member(name, level=50, race=1, map_id=ZULFARRAK_ZONE, x=10.0, y=10.0, z=0.0):
    return dungeonquests.Member(
        name=name, level=level, race=race, map_id=map_id, x=x, y=y, z=z
    )


def _facts(
    quests, members, rewarded=None, statuses=None, spawn=None, due=True, mid_run=False
):
    return dungeonquests.Facts(
        dungeon="zulfarrak",
        quests=quests,
        members=members,
        rewarded=rewarded or {},
        statuses=statuses or {},
        spawn=spawn or (ZULFARRAK_ZONE, 10.0, 10.0, 0.0),
        due=due,
        mid_run=mid_run,
    )


class BeforeTheFirstRun(unittest.TestCase):
    """The family picks up eligible dungeon quests before run one."""

    def test_takes_an_eligible_quest_at_its_giver(self):
        quest = _quest(10)
        facts = _facts(
            quests=(quest,),
            members=(_member("Grug", map_id=ZULFARRAK_ZONE, x=10.0, y=10.0),),
            statuses={"Grug": {10: dungeonquests.STATUS_NONE}},
            spawn=(ZULFARRAK_ZONE, 10.0, 10.0, 0.0),
        )
        step = dungeonquests.step(facts)
        self.assertEqual(step.rows, (("Grug", "take quest:10"),))
        self.assertTrue(step.release)

    def test_turns_in_a_complete_quest(self):
        quest = _quest(10)
        facts = _facts(
            quests=(quest,),
            members=(_member("Grug", map_id=ZULFARRAK_ZONE, x=10.0, y=10.0),),
            statuses={"Grug": {10: dungeonquests.STATUS_COMPLETE}},
            spawn=(ZULFARRAK_ZONE, 10.0, 10.0, 0.0),
        )
        step = dungeonquests.step(facts)
        self.assertEqual(step.rows, (("Grug", "turnin quest:10"),))

    def test_waits_while_inside_the_dungeon(self):
        quest = _quest(10)
        facts = _facts(
            quests=(quest,),
            members=(_member("Grug", map_id=ZULFARRAK_ZONE),),
            statuses={"Grug": {10: dungeonquests.STATUS_NONE}},
            mid_run=True,
        )
        step = dungeonquests.step(facts)
        self.assertEqual(step.verdict, dungeonquests.WAIT)
        self.assertTrue(step.hold_planner)


class BetweenRuns(unittest.TestCase):
    """Completed dungeon quests are turned in and follow-ups picked up."""

    def test_turns_in_a_completed_quest(self):
        complete = _quest(10)
        facts = _facts(
            quests=(complete,),
            members=(_member("Grug", map_id=ZULFARRAK_ZONE),),
            statuses={"Grug": {10: dungeonquests.STATUS_COMPLETE}},
        )
        step = dungeonquests.step(facts)
        self.assertEqual(step.rows, (("Grug", "turnin quest:10"),))

    def test_picks_up_a_follow_up_once_its_predecessor_is_rewarded(self):
        first = _quest(10, prev_quest_id=0)
        follow_up = _quest(11, prev_quest_id=10, starter=1001, ender=1001)
        # 10 has been turned in and rewarded; 11 is complete and due a turn-in.
        facts = _facts(
            quests=(first, follow_up),
            members=(_member("Grug", map_id=ZULFARRAK_ZONE),),
            rewarded={"Grug": {10}},
            statuses={
                "Grug": {
                    10: dungeonquests.STATUS_NONE,
                    11: dungeonquests.STATUS_COMPLETE,
                }
            },
        )
        step = dungeonquests.step(facts)
        self.assertEqual(step.rows, (("Grug", "turnin quest:11"),))

    def test_does_not_pick_up_a_follow_up_before_its_predecessor_is_rewarded(self):
        first = _quest(10, prev_quest_id=0)
        follow_up = _quest(11, prev_quest_id=10, starter=1001, ender=1001)
        # 10 is not yet rewarded, so 11 is not eligible even though it is NONE.
        facts = _facts(
            quests=(first, follow_up),
            members=(_member("Grug", map_id=ZULFARRAK_ZONE),),
            rewarded={},
            statuses={
                "Grug": {10: dungeonquests.STATUS_NONE, 11: dungeonquests.STATUS_NONE}
            },
        )
        step = dungeonquests.step(facts)
        self.assertEqual(step.rows, (("Grug", "take quest:10"),))

    def test_has_nothing_left_when_everything_is_rewarded(self):
        first = _quest(10, prev_quest_id=0)
        follow_up = _quest(11, prev_quest_id=10, starter=1001, ender=1001)
        facts = _facts(
            quests=(first, follow_up),
            members=(_member("Grug", map_id=ZULFARRAK_ZONE),),
            rewarded={"Grug": {10, 11}},
            statuses={
                "Grug": {10: dungeonquests.STATUS_NONE, 11: dungeonquests.STATUS_NONE}
            },
        )
        step = dungeonquests.step(facts)
        self.assertEqual(step.rows, ())
        self.assertEqual(step.verdict, dungeonquests.DONE)


class EligibilityComesFromWorldData(unittest.TestCase):
    """A quest is open only when a member passes level, race and prerequisite."""

    def test_rejects_underlevel_wrong_faction_and_missing_prerequisite(self):
        rows = [
            {
                "quest": 1,
                "zone": ZULFARRAK_ZONE,
                "min_level": 20,
                "races": 1,
                "prev_quest": 0,
            },
            {
                "quest": 2,
                "zone": ZULFARRAK_ZONE,
                "min_level": 1,
                "races": 2,
                "prev_quest": 0,
            },
            {
                "quest": 3,
                "zone": ZULFARRAK_ZONE,
                "min_level": 1,
                "races": 0,
                "prev_quest": 99,
            },
            {
                "quest": 4,
                "zone": ZULFARRAK_ZONE,
                "min_level": 1,
                "races": 0,
                "prev_quest": 0,
            },
        ]
        self.assertEqual(
            dungeonquests.open_quests(
                rows,
                rewarded={"Grug": {4}},
                members=(_member("Grug", level=19, race=1),),
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()

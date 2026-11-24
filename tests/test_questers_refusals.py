"""A refusal about bags or eligibility at one moment is not a fact about the quest.

Quest 298 (a start-item quest) was refused "not eligible" while its quester's
bags were full, and the ledger then held it broken for good: `known_broken`
read every broken row that was not a stall. Quest 297 (an item objective) had
its hunts refused "no free bag slot" while the quester's read of its bags said
there was room, so nothing moved and the quest stalled."""

import unittest

import classhunt
import classquest
import questledger
import questers
from test_questers import ended, giver, mirra, quest, spawn, started, world

NOT_ELIGIBLE = "not eligible (level, race, class, prerequisite or exclusive group)"
NO_GIVER_IN_REACH = "no giver of that quest in reach"
DEFENSE_QUEST = 263
LOCH_MODAN = 38


def refused_take(qid=1, age=10, name="Mirra"):
    return questers.Attempt(
        name, "take quest:%d" % qid, "error", reason=NOT_ELIGIBLE, age_minutes=age
    )


def full_hunt(age=2, name="Mirra"):
    return questers.Attempt(
        name,
        "hunt-spawn creature:1167 item:2636 count:8 max:480",
        "error",
        reason="the character has no free bag slot",
        age_minutes=age,
    )


class ARefusedTakeIsNotBrokenForGood(unittest.TestCase):
    def test_a_ledger_row_broken_by_a_refused_take_is_not_held(self):
        reason = questers.REFUSED_TAKE + ": " + NOT_ELIGIBLE
        state = questers.ledger_state("broken", reason)
        self.assertEqual(state, questers.LEDGER_STALLED)
        ledger = {("Mirra", 298): state}
        self.assertEqual(questers.known_broken("Mirra", {}, ledger), frozenset())

    def test_a_world_fact_row_is_still_held(self):
        state = questers.ledger_state("broken", questers.GIVER_MISSING)
        self.assertEqual(state, questers.LEDGER_BROKEN)

    def test_a_held_refusal_with_none_left_on_record_is_asked_again(self):
        held = {1: questers.REFUSED_TAKE + ": " + NOT_ELIGIBLE, 2: questers.STALLED}
        self.assertEqual(questers.retry_take_refusals("Mirra", held, ()), {1})

    def test_a_refusal_still_on_record_stays_held(self):
        tried = [refused_take(age=m) for m in (300, 200, 100)]
        held = {1: questers.REFUSED_TAKE}
        self.assertEqual(questers.retry_take_refusals("Mirra", held, tried), set())


def defense_catalogue():
    """The ticket's quest row and objective counts with fixture-only positions.

    The ticket gives no spawn coordinates or maps. The positions below only
    exercise the normal quester path; they do not claim live spawn locations.
    """
    row = quest(
        DEFENSE_QUEST,
        LOCH_MODAN,
        15,
        min_level=10,
        prev=237,
        kill=1197,
        count=10,
        title="In Defense of the King's Lands",
    )
    row.update(npc2=1164, npc_count2=10)
    givers = [
        giver(DEFENSE_QUEST, "start", 12630, 9000, 0, 0, name="Test giver"),
        giver(DEFENSE_QUEST, "end", 12631, 9001, 0, 0, name="Test ender"),
    ]
    spawns = [
        spawn(13000 + i, 1197, 100 + i, 0, level=13, name="Objective creature")
        for i in range(23)
    ] + [
        spawn(14000 + i, 1164, 200 + i, 0, level=13, name="Objective creature")
        for i in range(17)
    ]
    cat = questers.catalogue(
        [row],
        givers,
        spawns,
        [],
        [started(DEFENSE_QUEST, 9000)],
        [ended(DEFENSE_QUEST, 9001)],
    )
    member = mirra(
        name="TestQuester",
        level=15,
        zone_id=LOCH_MODAN,
        quests_done=frozenset({237}),
    )
    return cat, member


class RetryableQuestGiverRefusal(unittest.TestCase):
    def test_quest_263_can_retry_a_giver_wait_and_finish(self):
        cat, member = defense_catalogue()
        refusal = questers.Attempt(
            member.name,
            "take quest:263",
            "error",
            reason=NO_GIVER_IN_REACH,
            age_minutes=10,
            retryable=True,
        )

        waiting = questers.plan(cat, member, questers.Clock(), 0.0, tried=[refusal])

        self.assertEqual(waiting.broken, ())
        self.assertNotEqual(
            (getattr(waiting.move, "kind", None), getattr(waiting.move, "quest", None)),
            (classquest.TAKE, DEFENSE_QUEST),
        )
        self.assertEqual(
            questers.refusals(member.name, [refusal]),
            {},
        )

        retry = questers.Attempt(
            **{**refusal.__dict__, "age_minutes": questers.TAKE_GIVER_RETRY_MINUTES}
        )
        ready = questers.plan(cat, member, questers.Clock(), 0.0, tried=[retry])
        self.assertEqual((ready.move.kind, ready.move.quest), (classquest.TAKE, 263))

        held = questers.Member(
            **{
                **member.__dict__,
                "quest_log": {DEFENSE_QUEST: questers.STATUS_INCOMPLETE},
                "quest_progress": {DEFENSE_QUEST: 0},
                "quest_objectives": {DEFENSE_QUEST: {1197: 0, 1164: 0}},
            }
        )
        first_hunt = questers.plan(cat, held, questers.Clock(), 0.0).move
        self.assertEqual((first_hunt.kind, first_hunt.quest), (classquest.HUNT, 263))
        first_done = questers.Member(
            **{
                **held.__dict__,
                "quest_progress": {DEFENSE_QUEST: 10},
                "quest_objectives": {DEFENSE_QUEST: {1197: 10, 1164: 0}},
            }
        )
        second_hunt = questers.plan(cat, first_done, questers.Clock(), 60.0).move
        self.assertEqual((second_hunt.kind, second_hunt.quest), (classquest.HUNT, 263))
        complete = questers.Member(
            **{
                **held.__dict__,
                "quest_progress": {DEFENSE_QUEST: 20},
                "quest_objectives": {DEFENSE_QUEST: {1197: 10, 1164: 10}},
            }
        )
        hand_in = questers.plan(cat, complete, questers.Clock(), 120.0).move
        self.assertEqual((hand_in.kind, hand_in.quest), (classquest.TURN_IN, 263))

        (ledger_update,) = questledger.changes(
            {7: member.name},
            [
                {
                    "quest": DEFENSE_QUEST,
                    "guid": 7,
                    "character_name": member.name,
                    "state": questledger.BROKEN,
                    "first_taken": None,
                    "finished": None,
                    "reason": questers.REFUSED_TAKE + ": " + NO_GIVER_IN_REACH,
                }
            ],
            [],
            [{"guid": 7, "quest": DEFENSE_QUEST}],
            "now",
        )
        self.assertEqual(
            (ledger_update.state, ledger_update.reason), (questledger.COMPLETED, "")
        )


class AnItemHuntRefusedForBagRoomSellsFirst(unittest.TestCase):
    def test_the_refusal_is_read_for_this_quester_inside_the_cooldown(self):
        self.assertTrue(questers.bags_full_hunt("Mirra", [full_hunt()]))
        self.assertFalse(questers.bags_full_hunt("Kellan", [full_hunt()]))
        old = [full_hunt(age=questers.BAG_HUNT_RETRY_MINUTES)]
        self.assertFalse(questers.bags_full_hunt("Mirra", old))

    def test_a_bag_read_with_room_still_needs_a_sale_after_it(self):
        self.assertFalse(questers.needs_sale(mirra(free_slots=8)))
        self.assertTrue(questers.needs_sale(mirra(free_slots=8), [full_hunt()]))

    def test_the_stall_clock_waits_while_hunts_are_refused_for_bags(self):
        cat = world()
        member = mirra(x=0.0, quest_log={1: questers.STATUS_INCOMPLETE})
        for tried in ((), (full_hunt(),)):
            clock = questers.Clock()
            for i in range(0, 14):
                questers.plan(cat, member, clock, 600.0 * i, tried=tried, last_quest=1)
            played = clock.played("Mirra", 1)
            if tried:
                self.assertEqual(played, 0)
            else:
                self.assertGreater(played, 0)

    def test_the_constant_is_the_modules_words(self):
        self.assertEqual(classhunt.BAGS_FULL_REASON, "no free bag slot")


if __name__ == "__main__":
    unittest.main()

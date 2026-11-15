"""A refusal about bags or eligibility at one moment is not a fact about the quest.

Quest 298 (a start-item quest) was refused "not eligible" while its quester's
bags were full, and the ledger then held it broken for good: `known_broken`
read every broken row that was not a stall. Quest 297 (an item objective) had
its hunts refused "no free bag slot" while the quester's read of its bags said
there was room, so nothing moved and the quest stalled."""

import unittest

import classhunt
import questers
from test_questers import mirra, world

NOT_ELIGIBLE = "not eligible (level, race, class, prerequisite or exclusive group)"


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


class AnItemHuntRefusedForBagRoomSellsFirst(unittest.TestCase):
    def test_the_refusal_is_read_for_this_quester_inside_the_cooldown(self):
        self.assertTrue(questers.bags_full_hunt("Mirra", [full_hunt()]))
        self.assertFalse(questers.bags_full_hunt("Kellan", [full_hunt()]))
        old = [full_hunt(age=questers.SELL_COOLDOWN_MINUTES)]
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

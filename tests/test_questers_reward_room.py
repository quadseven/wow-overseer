"""A hand-in the core refuses to reward while the bags are full is a wait (#2788, #2790).

The core's CanRewardQuest also asks whether the reward the quester picks fits
in its bags. Pindle's Return to Bellowfiz (a choice of three weapons) was
refused 959 times in six days and Fizzik's The Perfect Stout (a choice of two)
sat refused for nine, each quester standing with every slot in every bag full,
and each quest was filed broken although other questers had handed both in.
The refusal says nothing about the quest while the bags read full: the quester
sells first and asks again, and the quest is not counted broken."""

import unittest

import classquest
import questers
from test_questers import mirra, world


def reward_refused(qid=1, age=10, name="Mirra"):
    return questers.Attempt(
        name,
        "turnin quest:%d" % qid,
        "error",
        reason=questers.REWARD_REFUSAL,
        age_minutes=age,
    )


def complete_member(**kw):
    return mirra(x=0.0, quest_log={1: questers.STATUS_COMPLETE}, **kw)


class TheModulesWords(unittest.TestCase):
    def test_the_constant_is_the_modules_words(self):
        self.assertEqual(questers.REWARD_REFUSAL, "the core will not reward it now")


class AFullBagRewardRefusalIsNotBroken(unittest.TestCase):
    def test_three_refusals_with_full_bags_are_not_counted(self):
        tried = [reward_refused(age=m) for m in (300, 200, 100)]
        self.assertEqual(questers.refusals("Mirra", tried, 0), {})
        p = questers.plan(
            world(), complete_member(free_slots=0), questers.Clock(), 0.0, tried=tried
        )
        self.assertEqual(p.broken, ())

    def test_the_same_refusals_with_room_in_the_bags_still_count(self):
        tried = [reward_refused(age=m) for m in (300, 200, 100)]
        for free in (1, 8, None):
            self.assertEqual(
                questers.refusals("Mirra", tried, free)[("turnin", 1)][0], 3
            )
        p = questers.plan(
            world(), complete_member(free_slots=8), questers.Clock(), 0.0, tried=tried
        )
        self.assertEqual([b.quest for b in p.broken], [1])
        self.assertTrue(p.broken[0].reason.startswith(questers.REFUSED_TURN_IN))

    def test_another_refusal_with_full_bags_still_counts(self):
        tried = [
            questers.Attempt(
                "Mirra",
                "turnin quest:1",
                "error",
                reason="no taker of that quest in reach",
                age_minutes=m,
            )
            for m in (300, 200, 100)
        ]
        self.assertEqual(questers.refusals("Mirra", tried, 0)[("turnin", 1)][0], 3)

    def test_a_refused_take_with_the_same_words_is_not_a_reward_refusal(self):
        take = questers.Attempt(
            "Mirra",
            "take quest:1",
            "error",
            reason=questers.REWARD_REFUSAL,
            age_minutes=5,
        )
        self.assertEqual(questers.reward_room_refused("Mirra", [take], 0), frozenset())
        self.assertEqual(questers.refusals("Mirra", [take], 0)[("take", 1)][0], 1)


class TheHandInWaitsForTheSale(unittest.TestCase):
    def test_a_just_refused_hand_in_is_held_until_the_cooldown_ends(self):
        tried = [reward_refused(age=2)]
        self.assertEqual(
            questers.reward_room_refused("Mirra", tried, 0), frozenset({1})
        )
        self.assertEqual(questers.turn_in_held("Mirra", tried, 0), frozenset({1}))
        later = [reward_refused(age=questers.SELL_COOLDOWN_MINUTES)]
        self.assertEqual(questers.reward_room_refused("Mirra", later, 0), frozenset())
        self.assertEqual(questers.turn_in_held("Mirra", later, 0), frozenset())

    def test_the_hand_in_is_not_walked_to_while_held_and_is_asked_after(self):
        member = complete_member(free_slots=0)
        held = questers.plan(
            world(), member, questers.Clock(), 0.0, tried=[reward_refused(age=2)]
        )
        self.assertNotEqual(
            (held.move.kind if held.move else None, held.move and held.move.quest),
            (classquest.TURN_IN, 1),
        )
        after = questers.plan(
            world(),
            member,
            questers.Clock(),
            0.0,
            tried=[reward_refused(age=questers.SELL_COOLDOWN_MINUTES)],
        )
        self.assertEqual((after.move.kind, after.move.quest), (classquest.TURN_IN, 1))

    def test_a_quester_with_room_is_not_held(self):
        tried = [reward_refused(age=2)]
        self.assertEqual(questers.turn_in_held("Mirra", tried, 8), frozenset())
        self.assertEqual(
            questers.reward_room_refused("Mirra", tried, None), frozenset()
        )

    def test_another_quester_s_refusal_holds_nothing(self):
        tried = [reward_refused(age=2, name="Kellan")]
        self.assertEqual(questers.reward_room_refused("Mirra", tried, 0), frozenset())

    def test_the_full_bag_quester_is_sent_to_sell(self):
        self.assertTrue(questers.needs_sale(mirra(free_slots=0), [reward_refused()]))


if __name__ == "__main__":
    unittest.main()

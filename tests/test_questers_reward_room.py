"""A retryable reward refusal is a wait, not a broken quest (#2790).

The world marks "the core will not reward it now" as retryable. A quester
must keep trying that hand-in without turning the refusal into a broken-quest
ledger row, even when the bridge's free-slot read is positive or unavailable.

The former room-based expectations are inverted below: these refusals stay
uncounted when there is room, and the hand-in remains held during its retry
window because the module marks the refusal retryable."""

import json
import unittest
from dataclasses import replace

import classquest
import guildjobs
import questers
from test_questers import HUMAN, PRIEST, giver, mirra, quest, world


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


def retryable_reward_refusal_row(qid=320, age=10, name="Quester"):
    command = "turnin quest:%d" % qid
    result = json.dumps(
        {
            "outcome": "refused",
            "reason": questers.REWARD_REFUSAL,
            "who": name,
            "quest_id": qid,
            "giver": 1320,
            "holder": "creature",
            "status": questers.STATUS_COMPLETE,
            "retryable": True,
            "request": command,
        },
        separators=(",", ":"),
    )
    return {
        "id": age,
        "target_name": name,
        "command": command,
        "source": guildjobs.source_for(questers.ACTION, name),
        "status": "error",
        "result": result,
        "age": age,
    }


def delivered_turn_in_row(qid=320, age=0, name="Quester"):
    command = "turnin quest:%d" % qid
    result = json.dumps(
        {
            "outcome": "handed in",
            "reason": "",
            "who": name,
            "quest_id": qid,
            "giver": 1320,
            "holder": "creature",
            "status": 0,
            "request": command,
        },
        separators=(",", ":"),
    )
    return {
        "id": age,
        "target_name": name,
        "command": command,
        "source": guildjobs.source_for(questers.ACTION, name),
        "status": "delivered",
        "result": result,
        "age": age,
    }


def quest_320_from_rows():
    quest_row = quest(320, 1, 8, min_level=2, prev=319, title="Return to Bellowfiz")
    quest_row.update(item1=2696, item_count1=1, provided0=2696)
    cat = world(
        extra_quests=[quest_row],
        extra_givers=[
            giver(320, "start", 1320, 1320, 0, 0, name="Bellowfiz"),
            giver(320, "end", 1320, 1320, 0, 0, name="Bellowfiz"),
        ],
    )
    members = questers.members_from_rows(
        [
            {
                "guid": 3200,
                "name": "Quester",
                "class_id": PRIEST,
                "race": HUMAN,
                "level": 8,
                "online": 1,
                "map_id": 0,
                "saved_zone": 1,
                "pos_x": 0.0,
                "pos_y": 0.0,
                "zone_id": 1,
                "health": 100,
            }
        ],
        [
            {
                "guid": 3200,
                "quest": 320,
                "status": questers.STATUS_COMPLETE,
                "progress": 1,
                "item1": 2696,
                "itemcount1": 1,
            }
        ],
        [{"guid": 3200, "quest": 319}],
    )
    (member,) = members
    return cat, member


class TheModulesWords(unittest.TestCase):
    def test_the_constant_is_the_modules_words(self):
        self.assertEqual(questers.REWARD_REFUSAL, "the core will not reward it now")


class ARetryableRewardRefusalIsNotBroken(unittest.TestCase):
    def test_three_refusals_with_full_bags_are_not_counted(self):
        tried = [reward_refused(age=m) for m in (300, 200, 100)]
        self.assertEqual(questers.refusals("Mirra", tried), {})
        p = questers.plan(
            world(), complete_member(free_slots=0), questers.Clock(), 0.0, tried=tried
        )
        self.assertEqual(p.broken, ())

    def test_same_refusals_with_room_do_not_count_when_retryable(self):
        tried = [reward_refused(age=m) for m in (300, 200, 100)]
        for free in (0, 1, 8, None):
            self.assertEqual(questers.refusals("Mirra", tried), {})
            p = questers.plan(
                world(),
                complete_member(free_slots=free),
                questers.Clock(),
                0.0,
                tried=tried,
            )
            self.assertEqual(p.broken, (), free)

    def test_same_refusals_count_when_the_module_says_not_retryable(self):
        tried = [
            replace(reward_refused(age=m), retryable=False) for m in (300, 200, 100)
        ]
        for free in (0, 1, 8, None):
            self.assertEqual(questers.refusals("Mirra", tried)[("turnin", 1)][0], 3)
            p = questers.plan(
                world(),
                complete_member(free_slots=free),
                questers.Clock(),
                0.0,
                tried=tried,
            )
            self.assertEqual([broken.quest for broken in p.broken], [1], free)
            self.assertTrue(
                p.broken[0].reason.startswith(questers.CANNOT_TURN_IN), free
            )

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
        for free in (0, 1, 8, None):
            self.assertEqual(questers.refusals("Mirra", tried)[("turnin", 1)][0], 3)
            p = questers.plan(
                world(),
                complete_member(free_slots=free),
                questers.Clock(),
                0.0,
                tried=tried,
            )
            self.assertEqual([b.quest for b in p.broken], [1])
            self.assertTrue(p.broken[0].reason.startswith(questers.REFUSED_TURN_IN))

    def test_a_refused_take_with_the_same_words_is_not_a_reward_refusal(self):
        take = questers.Attempt(
            "Mirra",
            "take quest:1",
            "error",
            reason=questers.REWARD_REFUSAL,
            age_minutes=5,
        )
        self.assertEqual(
            questers.retryable_reward_refused("Mirra", [take]), frozenset()
        )
        self.assertEqual(questers.refusals("Mirra", [take])[("take", 1)][0], 1)


class TheHandInWaitsForRetry(unittest.TestCase):
    def test_a_just_refused_hand_in_is_held_until_the_cooldown_ends(self):
        tried = [reward_refused(age=2)]
        self.assertEqual(
            questers.retryable_reward_refused("Mirra", tried), frozenset({1})
        )
        self.assertEqual(questers.turn_in_held("Mirra", tried), frozenset({1}))
        later = [reward_refused(age=questers.SELL_COOLDOWN_MINUTES)]
        self.assertEqual(questers.retryable_reward_refused("Mirra", later), frozenset())
        self.assertEqual(questers.turn_in_held("Mirra", later), frozenset())

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

    def test_quest_320_retryable_refusal_waits_and_is_retried(self):
        cat, member = quest_320_from_rows()
        rows = [retryable_reward_refusal_row(age=age) for age in (30, 20, 10)]
        tried = questers.attempts(rows)
        self.assertTrue(all(attempt.retryable for attempt in tried))
        self.assertEqual(
            [attempt.reason for attempt in tried],
            [questers.REWARD_REFUSAL] * 3,
        )

        member = replace(member, free_slots=8)
        self.assertTrue(questers.needs_sale(member, tried))
        waiting = questers.plan(cat, member, questers.Clock(), 0.0, tried=tried)
        self.assertEqual(waiting.broken, ())
        self.assertNotEqual(
            (waiting.move.kind, waiting.move.quest)
            if waiting.move is not None
            else (None, None),
            (classquest.TURN_IN, 320),
        )

        elapsed = questers.attempts(
            [retryable_reward_refusal_row(age=questers.SELL_COOLDOWN_MINUTES)]
        )
        retried = questers.plan(cat, member, questers.Clock(), 0.0, tried=elapsed)
        self.assertEqual(
            (retried.move.kind, retried.move.quest), (classquest.TURN_IN, 320)
        )
        completed = questers.settled(
            member, questers.attempts([delivered_turn_in_row()])
        )
        self.assertNotIn(320, completed.quest_log)
        self.assertIn(320, completed.quests_done)

    def test_a_quester_with_room_waits_after_retryable_refusal(self):
        tried = [reward_refused(age=2)]
        member = complete_member(free_slots=8)
        self.assertEqual(questers.turn_in_held("Mirra", tried), frozenset({1}))
        self.assertEqual(
            questers.retryable_reward_refused("Mirra", tried), frozenset({1})
        )
        waiting = questers.plan(world(), member, questers.Clock(), 0.0, tried=tried)
        self.assertEqual(waiting.broken, ())
        self.assertNotEqual(
            (waiting.move.kind, waiting.move.quest)
            if waiting.move is not None
            else (None, None),
            (classquest.TURN_IN, 1),
        )

    def test_another_quester_s_refusal_holds_nothing(self):
        tried = [reward_refused(age=2, name="Kellan")]
        self.assertEqual(questers.retryable_reward_refused("Mirra", tried), frozenset())

    def test_the_full_bag_quester_is_sent_to_sell(self):
        self.assertTrue(questers.needs_sale(mirra(free_slots=0), [reward_refused()]))


if __name__ == "__main__":
    unittest.main()

"""A take refused only for bag room is a wait, not a broken quest (#1992).

mod-overseer#1393 gives a take the module refused only because the giver's
start item will not fit in the bags its own words (BAG_ROOM_REFUSAL) and marks
it retryable. Before it the same refusal read "not eligible", and quests 94,
106, 118 and 120 were filed broken for it (#1778, #1836, #1837). The bridge
counted every take refusal toward FAILS_BEFORE_BROKEN, so a quester whose bags
read as having room but were full to the core (a free slot only in a
profession bag) still filed the quest broken after three tries. Now that
refusal is never counted: the quester sells first (`sell_step`, #1813) and
the take is asked again after the sale."""

import types
import unittest
from unittest import mock

import classquest
import keep
import questers
from test_questers import mirra, world
from test_questers_bridge import Pass, bridge
from test_questers_sell import GREY, MEAT_STACK, worn


def bag_room(qid=1, age=10, name="Mirra"):
    return questers.Attempt(
        name,
        "take quest:%d" % qid,
        "error",
        reason=questers.BAG_ROOM_REFUSAL,
        age_minutes=age,
    )


def not_eligible(qid=1, age=10):
    return questers.Attempt(
        "Mirra",
        "take quest:%d" % qid,
        "error",
        reason="not eligible (level, race, class, prerequisite or exclusive group)",
        age_minutes=age,
    )


class ABagRoomRefusalIsNotBroken(unittest.TestCase):
    def test_the_module_s_own_words(self):
        self.assertEqual(
            questers.BAG_ROOM_REFUSAL, "no bag room for the item the giver hands over"
        )

    def test_three_bag_room_refusals_in_a_day_do_not_break_the_quest(self):
        tried = [bag_room(age=m) for m in (300, 200, 100)]
        self.assertEqual(questers.refusals("Mirra", tried), {})
        p = questers.plan(world(), mirra(x=0.0), questers.Clock(), 0.0, tried=tried)
        self.assertEqual(p.broken, ())
        # Older than the hold: the take is asked again.
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 1))

    def test_a_real_eligibility_refusal_still_counts(self):
        tried = [not_eligible(age=m) for m in (300, 200, 100)]
        p = questers.plan(world(), mirra(x=0.0), questers.Clock(), 0.0, tried=tried)
        self.assertEqual([b.quest for b in p.broken], [1])
        self.assertTrue(p.broken[0].reason.startswith(questers.REFUSED_TAKE))

    def test_a_take_just_refused_for_bag_room_is_held_until_the_sale(self):
        tried = [bag_room(age=2)]
        self.assertEqual(questers.bag_room_refused("Mirra", tried), frozenset({1}))
        p = questers.plan(world(), mirra(x=0.0), questers.Clock(), 0.0, tried=tried)
        self.assertEqual(p.broken, ())
        self.assertNotEqual((p.move.kind, p.move.quest), (classquest.TAKE, 1))
        later = [bag_room(age=questers.SELL_COOLDOWN_MINUTES)]
        self.assertEqual(questers.bag_room_refused("Mirra", later), frozenset())

    def test_another_quester_s_refusal_holds_nothing(self):
        tried = [bag_room(age=2, name="Kellan")]
        self.assertFalse(questers.needs_sale(mirra(free_slots=8), tried))
        self.assertEqual(questers.bag_room_refused("Mirra", tried), frozenset())


class TheQuesterSellsAfterABagRoomRefusal(unittest.TestCase):
    def test_bags_read_with_room_still_need_a_sale_after_the_refusal(self):
        self.assertFalse(questers.needs_sale(mirra(free_slots=8)))
        self.assertTrue(questers.needs_sale(mirra(free_slots=8), [bag_room(age=2)]))
        self.assertTrue(questers.needs_sale(mirra(free_slots=None), [bag_room(age=2)]))

    def test_the_sale_step_is_built_with_room_read(self):
        step = questers.sell_step(
            mirra(free_slots=8),
            (GREY, MEAT_STACK),
            worn(),
            keep.Reservations(),
            world(),
            (),
            0,
            tried=[bag_room(age=2)],
        )
        self.assertIsNotNone(step)
        self.assertEqual(step.action, questers.SELL_ACTION)
        self.assertIn("no bag room", step.said)
        unread = questers.sell_step(
            mirra(free_slots=None),
            (GREY,),
            worn(),
            keep.Reservations(),
            world(),
            (),
            0,
            tried=[bag_room(age=2)],
        )
        self.assertIn("no bag room", unread.said)

    def test_through_the_bridge_the_next_move_is_the_sale_not_the_take(self):
        run = Pass([mirra(x=0.0, free_slots=8)])
        run.tried = (bag_room(age=2),)
        asked = []

        def bags(names):
            asked.append(list(names))
            return {"Mirra": (GREY, MEAT_STACK)}, {"Mirra": worn()}, ()

        with mock.patch.multiple(
            bridge,
            _fetch_quester_bags=bags,
            _KEEP=types.SimpleNamespace(now=lambda: keep.Reservations()),
        ):
            run.run()
        self.assertEqual(asked, [["Mirra"]])
        (step,) = run.started
        self.assertEqual(step.action, questers.SELL_ACTION)
        self.assertEqual(run.recorded, [])


def hunt_bags_full(age=2, name="Mirra"):
    return questers.Attempt(
        name,
        "hunt-spawn creature:200 count:8 max:480",
        "error",
        reason="the character has no free bag slot",
        age_minutes=age,
    )


class AHuntRefusedForBagRoomWaitsOnTheSale(unittest.TestCase):
    """A hunt the world refused for a full bag was asked again every pass: the
    member's refusals ran to 142 in a day. The member sells first, then the hunt
    waits for room or the bounded retry window."""

    HUNTING = dict(x=-400.0, quest_log={1: 3}, quests_done=frozenset({2, 3}))

    def test_the_refusal_is_held_until_the_bounded_retry_window_ends(self):
        self.assertTrue(questers.bags_full_hunt("Mirra", [hunt_bags_full(age=2)]))
        within = [hunt_bags_full(age=questers.SELL_COOLDOWN_MINUTES)]
        self.assertTrue(questers.bags_full_hunt("Mirra", within))
        old = [hunt_bags_full(age=questers.BAG_HUNT_RETRY_MINUTES)]
        self.assertFalse(questers.bags_full_hunt("Mirra", old))
        self.assertFalse(
            questers.bags_full_hunt("Mirra", [hunt_bags_full(name="Kellan")])
        )

    def test_it_sends_the_member_to_sell_whatever_its_bags_read(self):
        self.assertTrue(questers.needs_sale(mirra(free_slots=8), [hunt_bags_full()]))

    def test_the_hunt_is_not_asked_again_until_the_bounded_wait_is_over(self):
        member = mirra(**self.HUNTING)
        asked = questers.plan(world(), member, questers.Clock(), 0.0)
        self.assertEqual(asked.move.kind, classquest.HUNT)
        held = questers.plan(
            world(), member, questers.Clock(), 0.0, tried=[hunt_bags_full()]
        )
        self.assertIsNone(held.move)
        self.assertIn("bag", held.line)
        sale_cooldown = [hunt_bags_full(age=questers.SELL_COOLDOWN_MINUTES)]
        still_held = questers.plan(
            world(), member, questers.Clock(), 0.0, tried=sale_cooldown
        )
        self.assertIsNone(still_held.move)
        later = [hunt_bags_full(age=questers.BAG_HUNT_RETRY_MINUTES)]
        again = questers.plan(world(), member, questers.Clock(), 0.0, tried=later)
        self.assertEqual(again.move.kind, classquest.HUNT)

    def test_a_free_slot_read_does_not_release_the_hold(self):
        member = mirra(**self.HUNTING, free_slots=2)
        refused = [hunt_bags_full(age=10)]
        held = questers.plan(world(), member, questers.Clock(), 0.0, tried=refused)
        self.assertIsNone(held.move)
        self.assertIn("waits for room or", held.line)

    def test_a_free_slot_read_cannot_restart_the_refusal_loop(self):
        member = mirra(**self.HUNTING, free_slots=2)
        once = [hunt_bags_full(age=3)]
        self.assertTrue(questers.bags_full_hunt("Mirra", once, 2))
        held = questers.plan(world(), member, questers.Clock(), 0.0, tried=once)
        self.assertIsNone(held.move)
        old = [hunt_bags_full(age=questers.BAG_HUNT_RETRY_MINUTES + 1)] * 2
        self.assertTrue(questers.bags_full_hunt("Mirra", old + once, 2))

    def test_a_refusal_of_another_kind_holds_nothing(self):
        other = questers.Attempt(
            "Mirra",
            "hunt-spawn creature:200",
            "error",
            reason="in combat",
            age_minutes=2,
        )
        self.assertFalse(questers.bags_full_hunt("Mirra", [other]))

    def test_the_wait_is_long_enough_to_keep_a_day_under_ten_asks(self):
        self.assertLess(24 * 60 / questers.BAG_HUNT_RETRY_MINUTES, 10)


if __name__ == "__main__":
    unittest.main()

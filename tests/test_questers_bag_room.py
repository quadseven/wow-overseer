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

    def test_watchful_eye_bag_room_refusals_do_not_make_a_broken_ledger_row(self):
        # Quest 94 was reported broken after the world refused its take for
        # lack of room for the giver's start item. These are the same recent
        # attempt rows read by questers.refusals() from the command log.
        tried = [bag_room(94, age=m) for m in (300, 200, 100)]
        self.assertEqual(questers.refusals("Mirra", tried), {})

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


if __name__ == "__main__":
    unittest.main()

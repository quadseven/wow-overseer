"""A walk the world keeps releasing is refused for longer each time.

A mailbox the module gave up as unreachable was refused for one window and then
issued again, for ever, holding the family's traveller for the whole round
trip each time. The refusal now grows with every repeat, and the mail pass
skips a box it has given up on, as clearance does.
"""

import pathlib
import re
import unittest

import townslot

AIM = "at:0:1:2:3"
WHO = "mail"


def _slot():
    return townslot.Slot(releasable=lambda _aim: True)


class TheRefusalGrows(unittest.TestCase):
    def test_a_first_give_up_is_refused_for_one_window(self):
        slot = _slot()
        slot.abandon(WHO, AIM, False, 0.0)
        self.assertTrue(slot.spent(WHO, AIM, townslot.SPENT_SECONDS - 1))
        self.assertFalse(slot.spent(WHO, AIM, townslot.SPENT_SECONDS + 1))

    def test_a_repeat_after_the_window_is_refused_for_twice_as_long(self):
        slot = _slot()
        slot.abandon(WHO, AIM, False, 0.0)
        again = townslot.SPENT_SECONDS + 1
        slot.abandon(WHO, AIM, False, again)
        self.assertTrue(slot.spent(WHO, AIM, again + 2 * townslot.SPENT_SECONDS - 1))
        self.assertFalse(slot.spent(WHO, AIM, again + 2 * townslot.SPENT_SECONDS + 1))

    def test_the_refusal_is_bounded(self):
        slot = _slot()
        now = 0.0
        for _ in range(12):
            slot.abandon(WHO, AIM, False, now)
            now += slot.spent_window(WHO, AIM) + 1
        self.assertEqual(townslot.SPENT_CEILING_SECONDS, slot.spent_window(WHO, AIM))

    def test_a_give_up_long_after_the_ceiling_starts_over(self):
        slot = _slot()
        slot.abandon(WHO, AIM, False, 0.0)
        slot.abandon(WHO, AIM, False, townslot.SPENT_SECONDS + 1)
        late = 10 * townslot.SPENT_CEILING_SECONDS
        slot.abandon(WHO, AIM, False, late)
        self.assertEqual(townslot.SPENT_SECONDS, slot.spent_window(WHO, AIM))

    def test_a_repeat_inside_the_window_does_not_count(self):
        slot = _slot()
        slot.abandon(WHO, AIM, False, 0.0)
        slot.abandon(WHO, AIM, False, 10.0)
        self.assertEqual(townslot.SPENT_SECONDS, slot.spent_window(WHO, AIM))

    def test_the_refusal_is_per_claimant_and_aim(self):
        slot = _slot()
        slot.abandon(WHO, AIM, False, 0.0)
        slot.abandon(WHO, AIM, False, townslot.SPENT_SECONDS + 1)
        self.assertEqual(townslot.SPENT_SECONDS, slot.spent_window("clearance", AIM))
        self.assertEqual(townslot.SPENT_SECONDS, slot.spent_window(WHO, "at:0:9:9:9"))

    def test_a_lapsed_lease_grows_it_too(self):
        slot = _slot()
        holder = townslot.Holder(character="L", claimant=WHO, aim=AIM, since=0.0)
        slot.let_go(holder, True, 10 * townslot.SPENT_SECONDS)
        later = 11 * townslot.SPENT_SECONDS
        slot.let_go(holder, True, later)
        self.assertEqual(2 * townslot.SPENT_SECONDS, slot.spent_window(WHO, AIM))


class TheMailPassSkipsAGivenUpMailbox(unittest.TestCase):
    def test_the_nearest_mailbox_is_asked_with_the_slots_refusal(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        start = src.index("    async def _mail_once(")
        end = re.search(r"\n    (async def |def )", src[start + 1 :]).start()
        body = src[start : start + end]
        self.assertNotIn("_nearest_mailbox, leader)", body)
        self.assertIn('mail_slot.spent("mail"', body)


if __name__ == "__main__":
    unittest.main()

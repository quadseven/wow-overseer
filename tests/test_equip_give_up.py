"""Equips the world refuses stop retrying after the give-up count (#869).

Ticket #869: members (Cronk, Bonk) show "Trying to wear X" for hours because
the equip command keeps being queued even after repeated failures. The
`give_up` parameter to `gear.equips_to_queue` was accepted but never checked,
so retries never stopped.

What is pinned here:
- After `give_up` tries, the equip is NOT queued again.
- The note explains the give-up with the try count, so the roster shows why
  instead of "waiting for the game to accept it" forever.
"""

import unittest

import bag_pressure
import gear


class GiveUpAfterRepeatedTries(unittest.TestCase):
    def setUp(self):
        self.equip = gear.Equip(
            holder="Cronk",
            guid=12345,
            entry=1234,
            name="Odo's Ley Staff",
            slot="mainhand",
            item_level=50,
            worn_level=40,
            reason="upgrade",
        )
        self.wanted = (self.equip,)
        self.key = ("Cronk", self.equip.command)

    def test_after_give_up_tries_it_is_not_queued(self):
        # 3 tries (the default give_up) with no success: stop queueing.
        # This is the red test: give_up is accepted but never checked.
        queue, notes = bag_pressure.equips_to_queue(
            self.wanted, set(), {self.key: 3}, give_up=3
        )
        self.assertEqual(queue, ())

    def test_below_give_up_it_is_still_queued(self):
        # 2 tries < give_up=3: still eligible.
        queue, notes = bag_pressure.equips_to_queue(
            self.wanted, set(), {self.key: 2}, give_up=3
        )
        self.assertEqual(queue, self.wanted)

    def test_give_up_note_names_the_try_count(self):
        # The note must say why, so the roster doesn't show a bare stuck.
        queue, notes = bag_pressure.equips_to_queue(
            self.wanted, set(), {self.key: 3}, give_up=3
        )
        self.assertEqual(len(notes), 1)
        self.assertIn("3", notes[0])

    def test_offline_holder_is_not_queued(self):
        # #869: Bonk was offline and still got equip commands. An offline
        # holder never gets a new equip command.
        queue, notes = bag_pressure.equips_to_queue(
            self.wanted, set(), {}, online={"SomeoneElse"}
        )
        self.assertEqual(queue, ())
        self.assertEqual(len(notes), 1)
        self.assertIn("offline", notes[0].lower())

    def test_online_holder_is_queued(self):
        queue, notes = bag_pressure.equips_to_queue(
            self.wanted, set(), {}, online={"Cronk"}
        )
        self.assertEqual(queue, self.wanted)


if __name__ == "__main__":
    unittest.main()

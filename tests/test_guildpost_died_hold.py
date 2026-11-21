"""A mailbox walk that ended in a death is not asked again until the member is stronger (#2152).

Measured on the dev realm over a day: a dozen guild members ended a mailbox
walk "died on the way to the mailbox", one of them four times, because the post
pass remembered a refusal for being held but not a death on the road.
"""

import pathlib
import unittest

import guildpost

BRIDGE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
LETTER = {
    "receiver": "Grakk",
    "mail_id": 7,
    "item_guid": 70,
    "name": "Woolen Bag",
    "delivered": 1,
    "cod": 0,
    "online": 1,
}


def letters():
    return [x for x in map(guildpost.letter_from_row, [LETTER]) if x]


class ADeathOnTheMailRoadIsRemembered(unittest.TestCase):
    def test_a_member_that_died_on_the_road_is_not_walked_again(self):
        plan, notes = guildpost.visits(letters(), {"Grakk"}, died={"Grakk"})
        self.assertEqual(plan, [])
        self.assertTrue(any("Grakk" in n and "died" in n for n in notes))
        plan, _ = guildpost.visits(letters(), {"Grakk"}, died=set())
        self.assertEqual(len(plan), 1)

    def test_only_a_death_answer_starts_the_hold(self):
        self.assertTrue(guildpost.is_died("died on the way to the mailbox"))
        self.assertFalse(guildpost.is_died("entered combat on the way to the mailbox"))
        self.assertFalse(guildpost.is_died(""))

    def test_the_hold_lasts_until_a_level_is_gained(self):
        struck = {"Grakk": (48, 1000.0)}
        self.assertEqual(guildpost.died_names(struck, {"Grakk": 48}, 10.0), {"Grakk"})
        self.assertEqual(guildpost.died_names(struck, {"Grakk": 49}, 10.0), set())

    def test_the_hold_ends_at_its_time_for_a_member_that_gains_no_level(self):
        struck = {"Grakk": (60, 1000.0)}
        self.assertEqual(guildpost.died_names(struck, {"Grakk": 60}, 999.0), {"Grakk"})
        self.assertEqual(guildpost.died_names(struck, {"Grakk": 60}, 1000.0), set())

    def test_an_unread_level_keeps_the_hold(self):
        struck = {"Grakk": (None, 1000.0)}
        self.assertEqual(guildpost.died_names(struck, {"Grakk": 50}, 10.0), {"Grakk"})
        self.assertEqual(guildpost.died_names({"Grakk": (50, 1000.0)}, {}, 10.0), {"Grakk"})

    def test_the_bridge_starts_and_reads_the_hold(self):
        self.assertIn("guildpost.is_died(answer.said)", BRIDGE)
        self.assertIn("self._post_died[visit.receiver]", BRIDGE)
        self.assertIn("guildpost.died_names(", BRIDGE)


if __name__ == "__main__":
    unittest.main()

"""A stand-in guest an ocean away from the family is not seated (#1143).

On the dev realm two stand-in guests on Kalimdor joined a family on the Eastern
Kingdoms, found no way across but a 13,000 yard walk to a berth through hostile
ground, and stayed split from their leader for 79 to 207 minutes (or died on
the way). The seat is filled from the family's own continent, or stays empty
for a short-handed run, the operator's no-guest rule.
"""

import unittest

import standin
from test_standin import facts, member, seated, HUNTER, MAGE, WARLOCK

EASTERN, KALIMDOR = 0, 1


def over(name, level, class_id, map_id):
    return member(name, level, class_id, map_id=map_id)


class AGuestOnTheFamilysContinent(unittest.TestCase):
    def test_a_guest_across_the_water_is_skipped_for_one_beside_the_family(self):
        far = over("Arrow", 23, HUNTER, KALIMDOR)
        near = over("Zappy", 21, MAGE, EASTERN)
        step = standin.step(facts(candidates=(far, near), leader_map=EASTERN))
        self.assertEqual("Zappy", step.seat.in_name)

    def test_the_only_guest_across_the_water_leaves_the_seat_empty(self):
        far = over("Arrow", 23, HUNTER, KALIMDOR)
        step = standin.step(facts(candidates=(far,), leader_map=EASTERN))
        self.assertFalse(step.seat.has_guest)

    def test_a_guest_who_crossed_is_given_back_between_runs(self):
        far = over("Locky", 20, WARLOCK, KALIMDOR)
        step = standin.step(
            facts(candidates=(far,), current=seated(), leader_map=EASTERN)
        )
        self.assertFalse(step.seat.has_guest)
        self.assertIn("another continent", step.why)

    def test_an_unread_head_map_judges_nothing(self):
        far = over("Arrow", 23, HUNTER, KALIMDOR)
        step = standin.step(facts(candidates=(far,)))
        self.assertEqual("Arrow", step.seat.in_name)

    def test_a_guest_inside_an_instance_is_not_across_the_water(self):
        self.assertFalse(standin.across_the_water(36, EASTERN))
        self.assertTrue(standin.across_the_water(KALIMDOR, EASTERN))

    def test_the_head_map_is_read_from_the_family(self):
        family = (over("Grug", 20, MAGE, KALIMDOR), over("Og", 20, MAGE, EASTERN))
        self.assertEqual(KALIMDOR, standin.head_map(family, "Grug"))
        self.assertEqual(-1, standin.head_map(family, "Nobody"))


if __name__ == "__main__":
    unittest.main()

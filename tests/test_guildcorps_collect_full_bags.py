"""A mail collection refused for bag room is not asked again every half hour.

The corps blocker pass found Nobody refused "no room in the bags" 11, then 14
times in 24 hours, every one the same `take-item` of the same letter, written by
the collect step. Its cooldown is 30 minutes whatever the last row answered, so
a member whose bags stay full was sent to the mailbox, refused, and sent again
about every hour, with nothing in between to make room.

A collect row the module refused for bag room now holds the step for
FULL_BAGS_COLLECT_MINUTES. Any other answer keeps the ordinary half hour."""

import unittest

import guildcorps as gc
from test_guildcorps import TRAINABLE, VENDORS, held, tailor

FULL = '{"outcome":"refused","reason":"no room in the bags","retryable":true}'
OTHER = '{"outcome":"refused","reason":"letter not found","retryable":true}'


def collect_row(age, result, source="guildcorps:collect:2589", name="Tailor"):
    return {"target_name": name, "source": source, "age": age, "result": result}


def asks(recent):
    t = tailor(
        "Tailor",
        21,
        75,
        known=frozenset({3908, 2963}),
        carried=(held(2589, 19),),
        mail=(gc.Letter(55, 5001, 2589, 20),),
    )
    plan = gc.plan([t], {}, TRAINABLE, VENDORS, recent, set())
    return [s.action for s in plan.steps]


class ACollectRefusedForBagRoom(unittest.TestCase):
    def test_the_refusal_is_read_into_its_own_key(self):
        recent = gc.recent_from_rows([collect_row(40, FULL)])
        self.assertEqual(recent[("Tailor", "collect-full", 2589)], 40)
        self.assertEqual(recent[("Tailor", "collect", 2589)], 40)

    def test_another_refusal_is_not_a_full_bag(self):
        recent = gc.recent_from_rows([collect_row(40, OTHER)])
        self.assertNotIn(("Tailor", "collect-full", 2589), recent)

    def test_a_row_without_a_result_is_not_a_full_bag(self):
        row = collect_row(40, None)
        del row["result"]
        self.assertNotIn(("Tailor", "collect-full", 2589), gc.recent_from_rows([row]))

    def test_the_walk_row_is_not_a_refusal(self):
        recent = gc.recent_from_rows(
            [collect_row(40, FULL, source="guildcorps:collect-walk:2589")]
        )
        self.assertNotIn(("Tailor", "collect-full", 2589), recent)

    def test_it_is_not_asked_again_after_the_ordinary_half_hour(self):
        recent = gc.recent_from_rows([collect_row(45, FULL)])
        self.assertNotIn("collect", asks(recent))

    def test_it_is_asked_again_once_the_full_bag_wait_is_over(self):
        recent = gc.recent_from_rows(
            [collect_row(gc.FULL_BAGS_COLLECT_MINUTES + 1, FULL)]
        )
        self.assertIn("collect", asks(recent))

    def test_the_wait_is_long_enough_to_keep_a_day_under_ten_asks(self):
        self.assertLess(24 * 60 / gc.FULL_BAGS_COLLECT_MINUTES, 10)

    def test_any_other_collect_still_waits_only_the_half_hour(self):
        recent = gc.recent_from_rows([collect_row(45, OTHER)])
        self.assertIn("collect", asks(recent))


if __name__ == "__main__":
    unittest.main()

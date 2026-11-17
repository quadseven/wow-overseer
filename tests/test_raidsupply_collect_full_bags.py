"""A raid-supply collect refused for bag room waits four hours (#2925).

The corps blocker pass read Gugga refused "no room in the bags" ten times in a
day on `raidsupply:collect`, every one the same `take-item` of the same letter,
about every forty minutes. The raid supply plan has its own thirty minute
collect cooldown and did not know the corps' full-bag wait (#2870), so a raider
whose bags stay full was sent to the mailbox again and again. The same wait now
applies to a collect the module refused for bag room."""

import unittest

import guildcorps as gc
import raidsupply as rs
from test_raidsupply import facts, member

FULL = '{"outcome":"refused","reason":"no room in the bags","retryable":true}'
OTHER = '{"outcome":"refused","reason":"letter not found","retryable":true}'


def collect_row(age, result):
    key = rs.MAJOR_HEALING
    return {
        "target_name": "Anneve",
        "source": "raidsupply:collect:%d" % key,
        "age": age,
        "result": result,
    }


def actions(rows):
    letter = gc.Letter(77, 88, rs.MAJOR_HEALING, 4, True)
    people = [member("Anneve", maintenance=False, class_id=rs.WARRIOR, mail=(letter,))]
    recent = gc.recent_from_rows(rows, prefix=rs.SOURCE)
    return [s.action for s in rs.plan_guild(facts(people), recent, set()).steps]


class ARaidSupplyCollectRefusedForBagRoom(unittest.TestCase):
    def test_it_is_not_asked_again_after_the_ordinary_half_hour(self):
        self.assertNotIn("collect", actions([collect_row(45, FULL)]))

    def test_it_is_asked_again_once_the_full_bag_wait_is_over(self):
        age = gc.FULL_BAGS_COLLECT_MINUTES + 1
        self.assertIn("collect", actions([collect_row(age, FULL)]))

    def test_any_other_collect_still_waits_only_the_half_hour(self):
        self.assertIn("collect", actions([collect_row(45, OTHER)]))

    def test_a_collect_inside_the_half_hour_still_waits(self):
        self.assertNotIn("collect", actions([collect_row(10, OTHER)]))

    def test_the_rows_read_carry_the_result_of_a_collect(self):
        sql = rs_rows_sql()
        self.assertIn("AS result", sql)
        self.assertIn(":collect:", sql)


def rs_rows_sql():
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "_RAID_SUPPLY_ROWS_SQL" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("_RAID_SUPPLY_ROWS_SQL is gone")


if __name__ == "__main__":
    unittest.main()

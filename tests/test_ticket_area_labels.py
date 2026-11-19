"""Every issue the bridge files carries exactly one `area:` label (#2759).

The station holds a ticket with no `area:` label until a person adds one, so
a broken quest or a blocked corps member the bridge found waited for a hand
label before any lane could take it. These tests read the payload the App
client posts, the same one GitHub receives.
"""

import pathlib
import sys
import types
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import corpstickets
    import questledger
    import questtickets


class FakeGitHub:
    def __init__(self):
        self.calls = []

    def call(self, method, path, body=None, ok=(200,)):
        self.calls.append((method, path, body))
        n = 1000 + len(self.calls)
        return types.SimpleNamespace(json=lambda: {"id": n * 10, "number": n})

    def labels(self):
        return [c[2]["labels"] for c in self.calls if c[1] == "/issues"]


class Store:
    """One broken quest row, with the writes a pass makes."""

    def __init__(self):
        self.row = {
            "quest": 2759,
            "guid": 7,
            "character_name": "Durgan",
            "state": questledger.BROKEN,
            "reason": questledger.FAILED_REASON,
            "ticket": None,
        }

    def broken(self):
        return [self.row]

    def objectives(self, quest):
        return [{"guid": 7, "mobcount1": 3, "itemcount2": 1}]

    def ticket(self, quest):
        return None

    def take(self, quest, ticket):
        self.row["ticket"] = ticket

    def filed(self, quest, ticket):
        self.row["ticket"] = ticket

    def release(self, quest):
        self.row["ticket"] = None

    def record_pass(self, when):
        pass


class CorpsStore:
    def __init__(self, rows):
        self._rows, self.memo = rows, {}

    def rows(self):
        return self._rows

    def known(self):
        return dict(self.memo)

    def mark(self, key, ticket, now):
        self.memo[key] = ticket

    def release(self, key):
        self.memo.pop(key, None)


def refused(name, reason, n):
    return [
        {
            "target_name": name,
            "status": "error",
            "source": "guildjobs:level:%s" % name,
            "result": '{"outcome": "refused", "reason": "%s"}' % reason,
        }
        for _ in range(n)
    ]


def areas(labels):
    return [x for x in labels if x.startswith("area:")]


class QuestTickets(unittest.TestCase):
    def test_a_broken_quest_issue_is_filed_under_questing(self):
        github = FakeGitHub()
        done = questtickets.run(Store(), questtickets.Client(github), (), "")
        self.assertEqual(1, done["filed"])
        (labels,) = github.labels()
        self.assertEqual(["loom:ticket", "loom:queued", "area:questing"], labels)


class CorpsTickets(unittest.TestCase):
    def filed_labels(self, rows):
        github = FakeGitHub()
        client = questtickets.Client(github, epic=corpstickets.EPIC)
        corpstickets.run(CorpsStore(rows), client, 0.0)
        return github.labels()

    def test_a_dead_loop_is_filed_under_stability(self):
        (labels,) = self.filed_labels(refused("Grunty", "character is in combat", 73))
        self.assertEqual(["area:stability"], areas(labels))
        self.assertIn("loom:ticket", labels)
        self.assertIn("loom:queued", labels)

    def test_a_member_off_the_classic_world_is_filed_under_stability(self):
        why = "character stands in Outland, outside the classic world (map 530)"
        (labels,) = self.filed_labels(refused("Saelis", why, 30))
        self.assertEqual(["area:stability"], areas(labels))

    def test_full_bags_are_filed_under_economy(self):
        (labels,) = self.filed_labels(refused("Kellan", "no free bag slot", 12))
        self.assertEqual(["area:economy"], areas(labels))

    def test_every_kind_has_one_area_and_no_quest_area(self):
        for kind in (
            corpstickets.DEAD_LOOP,
            corpstickets.OFF_WORLD,
            corpstickets.FULL_BAGS,
            "a kind added later",
        ):
            labels = corpstickets.labels(corpstickets.Blocker("M", kind, "r", 20))
            self.assertEqual(1, len(areas(labels)), kind)
            self.assertNotIn("area:questing", labels, kind)

    def test_a_caller_cannot_file_with_two_areas_or_none(self):
        client = questtickets.Client(FakeGitHub())
        for bad in (("loom:ticket",), ("area:site", "area:economy")):
            with self.assertRaises(ValueError):
                client.file("t", "b", labels=bad)
        self.assertEqual([], client.github.calls)


if __name__ == "__main__":
    unittest.main()

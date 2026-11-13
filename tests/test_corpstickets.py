"""A blocked guild corps member becomes one GitHub issue (#2399).

The row shapes are the ones read on the dev realm on 2026-11-13: a quester
refused every walk as "outside the classic world", a maintenance member
refused one vendor walk "in combat" 73 times, a member refused buys for bag
room 44 times while other rows succeeded.

Pure unit tests against corpstickets, plus source checks on the bridge.
"""

import json
import pathlib
import unittest

import corpstickets
import questtickets

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def row(name, status, reason="", source="guildjobs:level:%s"):
    result = json.dumps({"outcome": "refused", "reason": reason}) if reason else ""
    return {
        "target_name": name,
        "status": status,
        "source": source % name if "%s" in source else source,
        "result": result,
    }


def refused(name, reason, n, source="guildjobs:quester-walk:%s"):
    return [row(name, "error", reason, source) for _ in range(n)]


OUTLAND = (
    "character stands in Outland or Northrend, outside the classic world (map 530)"
)
COMBAT = "character is in combat"
BAGS = "bags cannot take the item"


class FindingBlockers(unittest.TestCase):
    def test_a_member_refused_as_outland_all_day_is_off_world(self):
        (b,) = corpstickets.blockers(refused("Saelis", OUTLAND, 675))
        self.assertEqual(
            ("Saelis", corpstickets.OFF_WORLD, 675), (b.name, b.kind, b.count)
        )
        self.assertIn("map N", b.reason)
        self.assertEqual(("guildjobs:quester-walk",), b.sources)

    def test_one_step_refused_in_combat_every_time_is_a_dead_loop(self):
        rows = refused("Grunty", COMBAT, 73, "guildcorps:shop-walk:6260")
        (b,) = corpstickets.blockers(rows)
        self.assertEqual(corpstickets.DEAD_LOOP, b.kind)
        self.assertEqual("Grunty:dead-loop", b.key)

    def test_refusals_mixed_with_successes_are_no_dead_loop(self):
        rows = refused("Yamon", COMBAT, 40) + [row("Yamon", "applied")]
        self.assertEqual([], corpstickets.blockers(rows))

    def test_a_few_refusals_are_no_blocker(self):
        self.assertEqual([], corpstickets.blockers(refused("Rubba", COMBAT, 5)))

    def test_bag_refusals_are_full_bags_even_with_successes(self):
        rows = refused("Pokka", BAGS, 44, "guildcorps:shop:2321") + [
            row("Pokka", "applied")
        ]
        (b,) = corpstickets.blockers(rows)
        self.assertEqual(corpstickets.FULL_BAGS, b.kind)

    def test_the_title_and_body_have_the_ticket_shape(self):
        (b,) = corpstickets.blockers(refused("Saelis", OUTLAND, 675))
        self.assertIn("Saelis", corpstickets.title(b))
        text = corpstickets.body(b, epic=7)
        for part in ("## Why", "## Acceptance criteria", "Size: S", "## Out of scope"):
            self.assertIn(part, text)
        self.assertIn("Part of #7", text)
        self.assertNotIn("@", text)


class FakeStore:
    def __init__(self, rows, known=None):
        self._rows, self.memo, self.released = rows, dict(known or {}), []

    def rows(self):
        return self._rows

    def known(self):
        return dict(self.memo)

    def mark(self, key, ticket, now):
        self.memo[key] = ticket

    def release(self, key):
        self.memo.pop(key, None)
        self.released.append(key)


class FakeClient:
    def __init__(self, fail=None):
        self.filed, self.unlinked, self.fail = [], [], fail

    def file(self, heading, text):
        if self.fail:
            raise self.fail
        self.filed.append(heading)
        return 900 + len(self.filed)


class FilingOnce(unittest.TestCase):
    def test_a_pass_files_each_blocker_once(self):
        store = FakeStore(
            refused("Saelis", OUTLAND, 675) + refused("Grunty", COMBAT, 73)
        )
        client = FakeClient()

        first = corpstickets.run(store, client, 0.0)
        second = corpstickets.run(store, client, 1.0)

        self.assertEqual(2, len(first["filed"]))
        self.assertEqual([], second["filed"])
        self.assertEqual({"Grunty:dead-loop": 901, "Saelis:off-world": 902}, store.memo)

    def test_a_pass_files_at_most_its_cap(self):
        rows = []
        for i in range(corpstickets.MAX_PER_PASS + 3):
            rows += refused("M%d" % i, COMBAT, 30)
        done = corpstickets.run(FakeStore(rows), FakeClient(), 0.0)
        self.assertEqual(corpstickets.MAX_PER_PASS, len(done["filed"]))

    def test_a_refused_filing_frees_its_key(self):
        store = FakeStore(refused("Grunty", COMBAT, 73))
        with self.assertRaises(RuntimeError):
            corpstickets.run(store, FakeClient(fail=RuntimeError("422")), 0.0)
        self.assertEqual({}, store.memo)
        self.assertEqual(["Grunty:dead-loop"], store.released)

    def test_a_filing_left_in_flight_is_reported(self):
        store = FakeStore([], {"Grunty:dead-loop": corpstickets.FILING})
        self.assertEqual(
            ["Grunty:dead-loop"], corpstickets.run(store, FakeClient(), 0.0)["stuck"]
        )


class TheClientAndTheBridge(unittest.TestCase):
    def test_the_quest_client_links_under_the_epic_it_is_given(self):
        calls = []

        class GitHub:
            def call(self, method, path, payload, ok=()):
                calls.append(path)

                class R:
                    def json(self_inner):
                        return {"id": 5, "number": 77}

                return R()

        client = questtickets.Client(GitHub(), epic=corpstickets.EPIC)
        self.assertEqual(77, client.file("t", "b"))
        self.assertIn("/issues/%d/sub_issues" % corpstickets.EPIC, calls)
        self.assertEqual(questtickets.EPIC, questtickets.Client(GitHub()).epic)

    def test_the_bridge_runs_the_pass_only_with_an_app(self):
        self.assertTrue('_Pass("_corps_tickets_loop")' in BRIDGE)
        self.assertTrue(
            "questtickets.client_from_env(log, epic=corpstickets.EPIC)" in BRIDGE
        )
        self.assertTrue("corpstickets.run(corpstickets.SqlStore(cur)" in BRIDGE)

    def test_the_image_ships_the_module(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertTrue("corpstickets.py" in dockerfile)


if __name__ == "__main__":
    unittest.main()

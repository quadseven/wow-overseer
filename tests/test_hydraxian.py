"""Natural Hydraxian quest steps and the family trip to their real giver."""

import asyncio
import time
import types
import unittest
from unittest import mock

import attunestep
import hydraxian

from _stub_modules import PYMYSQL, fresh_import

GIVER = (1, 2849.59, -7297.15, 20.3987)


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


def _member(name="MemberA", *, at=None, map_id=1, level=60, race=1):
    x, y, z = at if at is not None else GIVER[1:]
    return hydraxian.Member(name, level, race, map_id, x, y, z)


def _giver_facts(*, at=None, quest=None, rewarded=None, statuses=None, recent=()):
    quest = quest or hydraxian.Quest(6821, 55, 0, 6805, 13278, 13278)
    return hydraxian.Facts(
        members=(_member(at=at),),
        quests=(quest,),
        rewarded=rewarded or {"MemberA": {6805}},
        statuses=statuses or {},
        givers={13278: GIVER},
        recent=frozenset(recent),
    )


class HydraxianQuestTests(unittest.TestCase):
    def test_a_family_with_an_available_quest_walks_to_the_live_giver(self):
        step = hydraxian.step(_giver_facts(at=(-7000.0, 500.0, 30.0)), allow_walk=True)

        self.assertEqual(step.aim, 13278)
        self.assertTrue(step.hold_planner)
        self.assertEqual(step.rows, ())

    def test_missing_giver_spawn_is_neither_a_quest_command_nor_a_walk_target(self):
        facts = _giver_facts(at=(-7000.0, 500.0, 30.0))
        facts = hydraxian.Facts(
            members=facts.members,
            quests=facts.quests,
            rewarded=facts.rewarded,
            statuses=facts.statuses,
        )

        step = hydraxian.step(facts, allow_walk=True)

        self.assertEqual(step, hydraxian.Step())

    def test_take_is_per_member_only_at_the_real_giver(self):
        facts = hydraxian.Facts(
            members=(
                _member("MemberA"),
                _member("MemberB", at=(2850.0, -7297.0, 20.4)),
            ),
            quests=(
                hydraxian.Quest(6821, 55, 0, 6805, 13278, 13278),
                hydraxian.Quest(6824, 55, 0, 6823, 13278, 13278),
            ),
            rewarded={"MemberA": {6805}, "MemberB": set()},
            statuses={"MemberA": {}, "MemberB": {}},
            givers={13278: GIVER},
        )

        step = hydraxian.step(facts)

        self.assertEqual(step.rows, (("MemberA", "take quest:6821"),))
        self.assertFalse(step.hold_planner)
        self.assertIsNone(step.aim)

    def test_item_started_6804_is_not_taken_but_a_real_complete_quest_walks_to_duke(
        self,
    ):
        facts = hydraxian.Facts(
            members=(_member(at=(-7000.0, 500.0, 30.0)),),
            quests=(hydraxian.Quest(6804, 55, 0, 0, 0, 13278),),
            statuses={"MemberA": {6804: hydraxian.STATUS_COMPLETE}},
            givers={13278: GIVER},
        )

        step = hydraxian.step(facts, allow_walk=True)

        self.assertEqual(step.aim, 13278)
        self.assertEqual(step.rows, ())
        self.assertTrue(step.hold_planner)

    def test_a_completed_quest_is_turned_in_only_for_a_member_at_the_ender(self):
        facts = hydraxian.Facts(
            members=(
                _member("MemberA"),
                _member("MemberB", map_id=530, at=(0.0, 0.0, 0.0)),
            ),
            quests=(hydraxian.Quest(6824, 55, 0, 6823, 13278, 13278),),
            statuses={
                "MemberA": {6824: hydraxian.STATUS_COMPLETE},
                "MemberB": {6824: hydraxian.STATUS_COMPLETE},
            },
            givers={13278: GIVER},
        )

        self.assertEqual(
            hydraxian.step(facts).rows,
            (("MemberA", "turnin quest:6824"),),
        )

    def test_a_written_command_is_not_asked_for_again(self):
        facts = _giver_facts(
            recent={("MemberA", "take quest:6821")},
        )

        self.assertEqual(hydraxian.step(facts).rows, ())

    def test_predecessor_rules_match_positive_and_negative_prev_quest_ids(self):
        member = _member()
        positive = hydraxian.Quest(6821, 55, 0, 6805, 13278, 13278)
        negative = hydraxian.Quest(6821, 55, 0, -6805, 13278, 13278)

        self.assertFalse(hydraxian.eligible(positive, member, {}, {}))
        self.assertTrue(hydraxian.eligible(positive, member, {"MemberA": {6805}}, {}))
        self.assertTrue(
            hydraxian.eligible(
                negative,
                member,
                {},
                {"MemberA": {6805: hydraxian.STATUS_INCOMPLETE}},
            )
        )

    def test_facts_adapter_keeps_snapshot_quest_state_giver_and_recent_rows(self):
        facts = hydraxian.facts_from_rows(
            [{"name": "MemberA", "level": 60, "race": 1}],
            [{"name": "MemberA", "map_id": 1, "pos_x": 1, "pos_y": 2, "pos_z": 3}],
            [
                {
                    "quest": 6821,
                    "min_level": 55,
                    "races": 0,
                    "prev_quest": -6805,
                    "starter": 13278,
                    "ender": 13278,
                }
            ],
            [{"name": "MemberA", "quest": 6805}],
            [{"name": "MemberA", "quest": 6821, "status": 3}],
            [{"id": 13278, "map_id": 1, "x": 1, "y": 2, "z": 3}],
            [{"target_name": "MemberA", "command": "take quest:6821"}],
        )

        self.assertEqual(facts.members, (_member(at=(1.0, 2.0, 3.0)),))
        self.assertEqual(facts.quests[0].prev_quest_id, -6805)
        self.assertEqual(facts.rewarded, {"MemberA": {6805}})
        self.assertEqual(facts.statuses, {"MemberA": {6821: 3}})
        self.assertEqual(facts.givers[13278], GIVER[:1] + (1.0, 2.0, 3.0))
        self.assertIn(("MemberA", "take quest:6821"), facts.recent)

    def test_hydraxian_uses_the_shared_attunement_quest_primitives(self):
        self.assertIs(hydraxian.Member, attunestep.Member)
        self.assertIs(hydraxian.command, attunestep.command)
        self.assertIs(hydraxian.race_admitted, attunestep.race_admitted)

    def test_the_switch_is_on_by_default_and_can_be_disabled(self):
        self.assertTrue(hydraxian.enabled({}))
        self.assertFalse(hydraxian.enabled({"HYDRAXIAN_STEP": "off"}))


class HydraxianBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = _import_bridge()

    def _host(self, *, mid_run=False):
        host = object.__new__(self.bridge.Bridge)
        host._hydraxian_since = {}
        host.claims = []
        host.releases = []
        host.written = []

        async def is_mid_run(_names):
            return mid_run

        async def claim(*args, **kwargs):
            host.claims.append((args, kwargs))
            return True

        host._mid_run = is_mid_run
        host._claim_town_slot = claim
        return host

    def _run_pass(self, facts, *, host=None, enabled=True, prof_loop=False, skip=()):
        host = host or self._host()
        family = {"leader": {"name": "MemberA", "job": "quest"}, "names": ["MemberA"]}
        with (
            mock.patch.object(self.bridge.hydraxian, "enabled", return_value=enabled),
            mock.patch.object(self.bridge, "_cohort_of", return_value="grug"),
            mock.patch.object(self.bridge.bonds, "head_of_family", return_value=[]),
            mock.patch.object(self.bridge, "_prof_loop_family", return_value=prof_loop),
            mock.patch.object(self.bridge, "_hydraxian_facts", return_value=facts),
            mock.patch.object(self.bridge, "_queue_level_rows", return_value=[]),
            mock.patch.object(
                self.bridge, "_insert_quest_row", side_effect=self._write(host)
            ),
            mock.patch.object(
                self.bridge, "_release_trade_errand", side_effect=self._release(host)
            ),
        ):
            held = asyncio.run(
                self.bridge.Bridge._hydraxian_pass(
                    host, {"grug": []}, {"grug": family}, skip=skip
                )
            )
        return host, held

    @staticmethod
    def _write(host):
        def write(name, said, source, _feature):
            host.written.append((name, said, source))
            return len(host.written)

        return write

    @staticmethod
    def _release(host):
        def release(name, aim):
            host.releases.append((name, aim))
            return True

        return release

    def test_disabled_profession_loop_and_mid_run_guards_leave_quest_state_alone(self):
        facts = _giver_facts()
        with mock.patch.object(self.bridge, "_hydraxian_facts") as read:
            _host, held = self._run_pass(facts, enabled=False)
            self.assertEqual(held, set())
            read.assert_not_called()

            _host, held = self._run_pass(facts, prof_loop=True)
            self.assertEqual(held, set())
            read.assert_not_called()

            _host, held = self._run_pass(facts, host=self._host(mid_run=True))
            self.assertEqual(held, set())
            read.assert_not_called()

            _host, held = self._run_pass(facts, skip={"grug"})
            self.assertEqual(held, set())
            read.assert_not_called()

    def test_pass_walks_the_leader_and_holds_the_family_planner(self):
        facts = _giver_facts(at=(-7000.0, 500.0, 30.0))
        host, held = self._run_pass(facts)

        self.assertEqual(held, {"grug"})
        self.assertEqual(host.written, [])
        self.assertEqual(host.claims[0][0][:3], ("attunement", "MemberA", "13278"))

    def test_an_expired_walk_releases_the_aim_and_gives_the_planner_back(self):
        host = self._host()
        host._hydraxian_since["grug"] = (
            time.monotonic() - hydraxian.HOLD_LIMIT_SECONDS - 1
        )

        _host, held = self._run_pass(_giver_facts(at=(-7000.0, 500.0, 30.0)), host=host)

        self.assertEqual(held, set())
        self.assertEqual(host.claims, [])
        self.assertEqual(host.releases, [("MemberA", "13278")])

    def test_pass_writes_a_real_take_and_releases_the_giver_walk(self):
        host, held = self._run_pass(_giver_facts())

        self.assertEqual(held, set())
        self.assertEqual(
            host.written,
            [("MemberA", "take quest:6821", hydraxian.SOURCE)],
        )
        self.assertEqual(host.releases, [("MemberA", "13278")])

    def test_pass_does_not_swallow_programming_errors(self):
        host = self._host()

        async def broken_mid_run(_names):
            raise RuntimeError("bug")

        host._mid_run = broken_mid_run
        with self.assertRaisesRegex(RuntimeError, "bug"):
            self._run_pass(_giver_facts(), host=host)

    def test_pass_contains_expected_database_errors(self):
        host = self._host()

        async def database_down(_names):
            raise self.bridge.pymysql.err.MySQLError("down")

        host._mid_run = database_down
        _host, held = self._run_pass(_giver_facts(), host=host)

        self.assertEqual(held, set())
        self.assertEqual(host.claims, [])


if __name__ == "__main__":
    unittest.main()

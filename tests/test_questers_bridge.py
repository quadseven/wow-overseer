"""The bridge's quester pass (#924), driven for real with the reads stubbed:
each quester's move becomes a guild job step, a quest found broken is written
into the quest ledger with its reason, and the five share their quests."""

import asyncio
import types
import unittest
from unittest import mock

import questers
import raidteams
from test_guildsocial_bridge import bridge
from test_questers import ELWYNN, world


def quester(name="Mirra", **kw):
    base = dict(
        name=name,
        level=2,
        race=1,
        class_id=5,
        map_id=0,
        x=10.0,
        y=0.0,
        zone_id=ELWYNN,
        online=True,
    )
    base.update(kw)
    return questers.Member(**base)


class Pass:
    """A bridge with only what the quester pass reads, and what it wrote."""

    def __init__(self, members, ledger=None, cat=None):
        self.members = list(members)
        self.ledger = dict(ledger or {})
        self.cat = cat or world()
        self.hunts_open = 0
        self.started, self.recorded, self.shared, self.asked = [], [], [], []
        self.self = types.SimpleNamespace(
            _job_steps={},
            _guild_walk_cap=lambda: 0,
            _start_quester_step=self._start,
        )

    def _start(self, step, cap):
        # The step runs and ends before the next pass.
        self.started.append(step)
        self.self._job_steps.pop(step.holder, None)

    def _facts(self, names):
        self.asked.append(list(names))
        return self.members, (), self.ledger, self.hunts_open

    def run(self, now=0.0):
        with (
            mock.patch.multiple(
                bridge,
                _quester_memos=lambda: ({}, {}),
                _quester_memos_write=lambda *a: None,
                _quester_catalogue=lambda: self.cat,
                _fetch_quester_facts=self._facts,
                _record_quest_broken=lambda b: self.recorded.append(b) or True,
                _share_family_quests=lambda *a: self.shared.append(a),
            ),
            mock.patch.object(bridge.time, "time", return_value=now),
        ):
            asyncio.run(bridge.Bridge._quester_once(self.self))
        return self


class TheQuesterPass(unittest.TestCase):
    def test_it_reads_the_questers_and_nobody_else(self):
        run = Pass([quester()]).run()
        self.assertEqual(run.asked, [sorted(raidteams.quester_names())])

    def test_a_quester_takes_the_nearest_open_quest_of_its_zone(self):
        run = Pass([quester(x=0.0)]).run()
        (step,) = run.started
        self.assertEqual(step.holder, "Mirra")
        self.assertEqual(
            step.walk.command.split()[:2], ["walk-to-spawn", "creature:1001"]
        )
        self.assertEqual([r.command for r in step.rows], ["take quest:1"])

    def test_it_moves_zones_only_when_nothing_in_its_zone_is_left(self):
        left = Pass([quester(level=5, quests_done=frozenset({1, 3, 6}))]).run()
        self.assertEqual([r.command for r in left.started[0].rows], ["take quest:2"])
        done = Pass([quester(level=5, quests_done=frozenset({1, 2, 3, 6}))]).run()
        self.assertEqual([r.command for r in done.started[0].rows], ["take quest:20"])

    def test_a_quester_already_on_a_step_is_given_no_other(self):
        run = Pass([quester()])
        run.self._job_steps["Mirra"] = bridge.time.monotonic()
        run.run()
        self.assertEqual(run.started, [])

    def test_the_five_of_a_guild_share_their_quests(self):
        names = sorted(raidteams.quester_names("Cave"))
        run = Pass([quester(n) for n in names]).run()
        self.assertEqual([a[0] for a in run.shared], [names])

    def test_a_stalled_quest_is_recorded_broken_with_its_reason_and_dropped(self):
        member = quester(quest_log={1: 3}, quests_done=frozenset({2, 3}), x=150.0)
        run = Pass([member])
        for minute in range(0, 125, 5):
            run.started.clear()
            run.run(now=minute * 60.0)
        self.assertEqual(
            [(b.name, b.quest, b.reason, b.held) for b in run.recorded],
            [("Mirra", 1, questers.STALLED, True)],
        )
        (step,) = run.started
        self.assertEqual([r.command for r in step.rows], ["abandon quest:1"])

    def test_a_broken_quest_the_ledger_holds_is_not_written_again(self):
        member = quester(quest_log={3: 1})
        cat = world(drop={1003})
        run = Pass([member], cat=cat).run()
        self.assertEqual(
            [(b.quest, b.reason) for b in run.recorded], [(3, questers.ENDER_MISSING)]
        )
        run.ledger[("Mirra", 3)] = "broken"
        run.recorded.clear()
        run.run()
        self.assertEqual(run.recorded, [])

    def test_a_broken_quest_the_ledger_lost_is_written_again(self):
        # The ledger's own pass reads only the log: while the quest is still
        # held it may read it as taken again (#923). The quester puts it back.
        run = Pass([quester(quest_log={3: 1})], cat=world(drop={1003})).run()
        run.ledger[("Mirra", 3)] = "taken"
        run.recorded.clear()
        run.run()
        self.assertEqual(
            [(b.quest, b.reason) for b in run.recorded], [(3, questers.ENDER_MISSING)]
        )

    def test_a_broken_quest_is_never_taken_again(self):
        run = Pass([quester(x=0.0)], ledger={("Mirra", 1): "broken"}).run()
        self.assertNotIn(
            "take quest:1", [r.command for s in run.started for r in s.rows]
        )
        self.assertEqual(run.started[0].rows[0].command.split()[0], "take")

    def test_a_hunt_is_a_walk_to_the_objective_and_the_hunt_of_its_creature(self):
        member = quester(quest_log={1: 3}, quests_done=frozenset({2, 3}), x=-400.0)
        (step,) = Pass([member]).run().started
        self.assertEqual((step.action, step.key), (questers.ACTION, 1))
        self.assertIn("creature:2001", step.walk.command)
        self.assertEqual(
            [r.command for r in step.rows], ["hunt-spawn creature:200 count:8 max:480"]
        )

    def test_a_quester_at_its_objective_hunts_with_no_walk(self):
        member = quester(quest_log={1: 3}, quests_done=frozenset({2, 3}), x=150.0)
        (step,) = Pass([member]).run().started
        self.assertIsNone(step.walk)
        self.assertEqual(step.rows[0].command.split()[0], "hunt-spawn")

    def test_the_questers_hold_no_more_than_their_share_of_the_realms_hunts(self):
        far = dict(quest_log={1: 3}, quests_done=frozenset({2, 3}), x=-400.0)
        names = sorted(raidteams.quester_names("Cave"))
        run = Pass([quester(n, **far) for n in names]).run()
        hunting = [s for s in run.started if s.rows]
        self.assertEqual(len(hunting), bridge.QUESTER_HUNTS)
        self.assertEqual(len(run.started), len(names))
        full = Pass([quester(**far)])
        full.hunts_open = bridge.QUESTER_HUNTS
        (step,) = full.run().started
        self.assertEqual(step.rows, ())

    def test_with_no_hunt_verb_a_quester_at_its_objective_is_left_to_work_it(self):
        member = quester(quest_log={1: 3}, quests_done=frozenset({2, 3}), x=150.0)
        run = Pass([member])
        run.self._class_hunt_unsupported_until = bridge.time.monotonic() + 600
        self.assertEqual(run.run().started, [])


if __name__ == "__main__":
    unittest.main()

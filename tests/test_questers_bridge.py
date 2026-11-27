"""The bridge's quester pass (#924), driven for real with the reads stubbed:
each quester's move becomes a guild job step, a quest found broken is written
into the quest ledger with its reason, and the five share their quests."""

import asyncio
import types
import unittest
from unittest import mock

import guildjobs
import questers
import raidteams
from test_guildsocial_bridge import bridge
from test_questers import (
    ELWYNN,
    NO_TRANSPORT,
    ORC,
    REDRIDGE,
    crossing_row,
    giver,
    quest,
    started,
    ended,
    spawn,
    world,
)

SILVERPINE = 130


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


def erland_world():
    row = quest(
        435,
        SILVERPINE,
        11,
        min_level=10,
        count=0,
        title="Escorting Erland",
    )
    return questers.catalogue(
        [row],
        [
            giver(435, "start", 900435, 900435, 0, 0),
            giver(435, "end", 900435, 900435, 0, 0),
        ],
        [spawn(900435, 900435, 0, 0, level=11)],
        [],
        [started(435, 900435)],
        [ended(435, 900435)],
    )


class Pass:
    """A bridge with only what the quester pass reads, and what it wrote."""

    def __init__(
        self, members, ledger=None, cat=None, broken=None, clock=None, judged=None
    ):
        self.members = list(members)
        self.ledger = dict(ledger or {})
        self.cat = cat or world()
        self.broken = {name: dict(rows) for name, rows in (broken or {}).items()}
        self.clock = dict(clock or {})
        self.broken_written = None
        self.judged = dict(judged or {})
        self.judged_written = None
        self.hunts_open = 0
        self.crossings = ()
        self.tried = ()
        self.started, self.recorded, self.shared, self.asked = [], [], [], []
        self.self = types.SimpleNamespace(
            _job_steps={},
            _guild_walk_cap=lambda: 0,
            _start_quester_step=self._start,
        )
        for method in ("_quester_ledger", "_quester_start"):
            setattr(
                self.self,
                method,
                types.MethodType(getattr(bridge.Bridge, method), self.self),
            )

    def _start(self, step, cap):
        # The step runs and ends before the next pass.
        self.started.append(step)
        self.self._job_steps.pop(step.holder, None)

    def _facts(self, names):
        self.asked.append(list(names))
        return self.members, self.tried, self.ledger, self.hunts_open, self.crossings

    def _write_memos(self, _clock, broken, _now):
        self.broken_written = {name: dict(rows) for name, rows in broken.items()}

    def _write_judged(self, judged, _now):
        self.judged_written = dict(judged)

    def run(self, now=0.0):
        with (
            mock.patch.multiple(
                bridge,
                _quester_memos=lambda: (self.clock, self.broken),
                _quester_memos_write=self._write_memos,
                _quester_judged=lambda: dict(self.judged),
                _quester_judged_write=self._write_judged,
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
    def test_a_quest_waiting_for_a_hunt_slot_does_not_stall(self):
        # The item/dropper values mirror the ticket's world rows in the
        # quest, loot and spawn row shapes read by questers and classquest.
        wanted = quest(398, 85, 10, min_level=4, title="Wanted: Maggot Eye")
        wanted.update(item1=3635, item_count1=1)
        cat = questers.catalogue(
            [wanted],
            [
                giver(398, "start", 5398, 100, 0, 0),
                giver(398, "end", 5399, 101, 0, 0),
            ],
            [spawn(51753, 1753, 20, 0, level=0, name="Maggot Eye")],
            [{"item": 3635, "entry": 1753}],
            [{"quest": 398, "kind": "creature", "entry": 100}],
            [{"quest": 398, "kind": "creature", "entry": 101}],
        )
        member = quester(
            name="Quester",
            level=10,
            zone_id=85,
            x=20.0,
            quest_log={398: questers.STATUS_INCOMPLETE},
            quest_progress={398: 0},
            quest_objectives={398: {}},
            quest_item_objectives={398: {3635: 0}},
        )
        clock = questers.Clock()
        started = []
        bridge_state = types.SimpleNamespace(
            _job_steps={},
            _quester_last={},
            _start_quester_step=lambda step, cap: started.append(step),
        )

        first = questers.plan(cat, member, clock, 0.0)
        self.assertEqual((first.move.kind, first.move.quest), ("hunt", 398))
        self.assertFalse(
            bridge.Bridge._quester_start(
                bridge_state, member, first, cat, 0, 0.0, hunt=False
            )
        )
        self.assertEqual(started, [])

        for minute in range(5, 125, 5):
            waiting = questers.plan(
                cat,
                member,
                clock,
                minute * 60.0,
                last_quest=bridge_state._quester_last.get(member.name, 0),
            )

        self.assertEqual(waiting.broken, ())
        ready = questers.plan(cat, member, clock, 7500.0)
        self.assertTrue(
            bridge.Bridge._quester_start(
                bridge_state, member, ready, cat, 0, 7500.0, hunt=True
            )
        )
        self.assertEqual(
            [row.command for row in started[0].rows],
            ["hunt-spawn creature:1753 item:3635 count:1 max:480"],
        )

    def test_a_stalled_quest_with_remote_droppers_is_retried_and_unheld(self):
        wanted = quest(180, REDRIDGE, 26, title="Wanted: Lieutenant Fangore")
        wanted.update(item1=3632, item_count1=1)
        cat = questers.catalogue(
            [wanted],
            [
                giver(180, "start", 5180, 187, 0, 0),
                giver(180, "end", 5181, 187, 400, 0),
            ],
            [spawn(5703, 703, 100, 0, level=26, map_id=0)],
            [{"item": 3632, "entry": 703}],
            [{"quest": 180, "kind": "creature", "entry": 187}],
            [{"quest": 180, "kind": "creature", "entry": 187}],
        )
        sylvi = quester(
            name="Sylvi",
            level=28,
            race=4,
            map_id=1,
            zone_id=1657,
            quest_log={180: questers.STATUS_INCOMPLETE},
            quest_progress={180: 0},
            quest_objectives={180: {}},
        )
        clock = {
            "Sylvi:180": [
                [questers.STATUS_INCOMPLETE, 0],
                questers.STALL_SECONDS,
                questers.STALL_SECONDS,
            ]
        }
        run = Pass(
            [sylvi],
            cat=cat,
            broken={"Sylvi": {180: questers.STALLED}},
            clock=clock,
        ).run()

        self.assertEqual(
            [r.command for r in run.started[0].rows], ["cross-to-map map:0"]
        )
        self.assertEqual(run.broken_written, {"Sylvi": {}})
        self.assertEqual(run.recorded, [])
        self.assertEqual(run.judged_written, {"Sylvi": frozenset({180})})

        # The same stall held again: judged once retried, so it stays held.
        again = Pass(
            [sylvi],
            cat=cat,
            broken={"Sylvi": {180: questers.STALLED}},
            clock=clock,
            judged=run.judged_written,
        ).run()
        self.assertEqual(again.broken_written, {"Sylvi": {180: questers.STALLED}})
        self.assertEqual(again.judged_written, {"Sylvi": frozenset({180})})

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

    def test_kobold_camp_cleanup_walks_inside_the_quest_givers_reach(self):
        cat = world(
            extra_quests=[
                quest(7, 9, 2, kill=40, count=8, title="Kobold Camp Cleanup")
            ],
            extra_givers=[
                giver(7, "start", 1007, 197, 55, 0),
                giver(7, "end", 1007, 197, 55, 0),
            ],
            extra_starts=[started(7, 197)],
            extra_ends=[ended(7, 197)],
            extra_spawns=[spawn(2007, 40, 250, 0)],
            drop={1001},
        )
        run = Pass(
            [quester(x=55.0, quests_done=frozenset({1, 2, 3, 6}))], cat=cat
        ).run()
        (step,) = run.started
        self.assertEqual([r.command for r in step.rows], ["take quest:7"])
        self.assertEqual(step.walk.command, "walk-to-spawn creature:1007 near:12")

        hand_in = Pass(
            [quester(quest_log={7: questers.STATUS_COMPLETE})], cat=cat
        ).run()
        (step,) = hand_in.started
        self.assertEqual([r.command for r in step.rows], ["turnin quest:7"])
        self.assertEqual(step.walk.command, "walk-to-spawn creature:1007 near:12")

        hunt = Pass(
            [
                quester(
                    quest_log={7: questers.STATUS_INCOMPLETE},
                    quests_done=frozenset({1, 2, 3, 6}),
                    x=225.0,
                )
            ],
            cat=cat,
        ).run()
        (step,) = hunt.started
        self.assertEqual(
            [r.command for r in step.rows], ["hunt-spawn creature:40 count:8 max:480"]
        )
        self.assertEqual(step.walk.command, "walk-to-spawn creature:2007 near:12")

    def test_it_moves_zones_only_when_nothing_in_its_zone_is_left(self):
        left = Pass([quester(level=5, quests_done=frozenset({1, 3, 6}))]).run()
        self.assertEqual([r.command for r in left.started[0].rows], ["take quest:2"])
        done = Pass([quester(level=5, quests_done=frozenset({1, 2, 3, 6}))]).run()
        self.assertEqual([r.command for r in done.started[0].rows], ["take quest:20"])

    def test_a_crossing_the_world_refused_for_good_is_not_written_every_pass(self):
        # Two death knights in Acherus asked for Kalimdor 1,097 times in a day
        # (2026-10-18); the quester pass reads the crossing rows and holds it.
        member = quester(level=5, quests_done=frozenset({1, 2, 3, 6, 20, 30}))
        cat = world(
            extra_quests=[quest(40, 148, 4, title="Darkshore Fish")],
            extra_givers=[
                giver(40, "start", 1040, 140, 0, 0, map_id=1),
                giver(40, "end", 1040, 140, 0, 0, map_id=1),
            ],
        )
        first = Pass([member], cat=cat).run()
        self.assertEqual(
            [(r.command, r.source) for r in first.started[0].rows],
            [("cross-to-map map:1", "guildjobs:quester-cross:Mirra")],
        )
        walled = Pass([member], cat=cat)
        walled.crossings = guildjobs.recent_from_rows(
            [crossing_row(NO_TRANSPORT, False, age=3)]
        )
        self.assertEqual(walled.run().started, [])

    def test_a_quester_already_on_a_step_is_given_no_other(self):
        run = Pass([quester()])
        run.self._job_steps["Mirra"] = bridge.time.monotonic()
        run.run()
        self.assertEqual(run.started, [])

    def test_a_step_that_fails_to_start_leaves_no_marker_holding_the_quester(self):
        run = Pass([quester(x=0.0)])

        def refuse(step, cap):
            raise RuntimeError("no task")

        run.self._start_quester_step = refuse
        with self.assertRaises(RuntimeError):
            run.run()
        self.assertNotIn("Mirra", run.self._job_steps)

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

    def test_erland_world_rows_leave_no_move_and_explain_why_no_quester_can_finish(
        self,
    ):
        cat = erland_world()
        held = cat.quest(435)
        self.assertEqual(
            (held.kills, held.items, held.objects, held.uses), ((), (), (), ())
        )
        member = quester(
            name="Quester",
            level=11,
            race=ORC,
            zone_id=SILVERPINE,
            quest_log={435: questers.STATUS_INCOMPLETE},
        )
        run = Pass([member], cat=cat)
        for minute in range(0, 121, 5):
            run.started.clear()
            run.run(now=minute * 60.0)
            if minute < 120:
                self.assertEqual(run.started, [])
                self.assertEqual(run.recorded, [])
        self.assertEqual(
            [(b.quest, b.reason, b.held) for b in run.recorded],
            [
                (
                    435,
                    "the world rows define no required creature, item, or object "
                    "objective a quester can work",
                    True,
                )
            ],
        )
        (step,) = run.started
        self.assertEqual([r.command for r in step.rows], ["abandon quest:435"])

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

    def test_a_stale_retryable_reward_refusal_is_cleared_and_retried(self):
        row = quest(320, 1, 8, min_level=2, prev=319, title="Return to Bellowfiz")
        row.update(item1=2696, item_count1=1, provided0=2696)
        cat = world(
            extra_quests=[row],
            extra_givers=[
                giver(320, "start", 1320, 1320, 0, 0, name="Bellowfiz"),
                giver(320, "end", 1320, 1320, 0, 0, name="Bellowfiz"),
            ],
        )
        member = quester(
            name="Quester",
            level=8,
            zone_id=1,
            x=0.0,
            free_slots=8,
            quests_done=frozenset({319}),
            quest_log={320: questers.STATUS_COMPLETE},
            quest_progress={320: 1},
            quest_item_objectives={320: {2696: 1}},
        )
        reason = questers.RETRYABLE_REWARD_LEDGER_REASON
        ledger = {
            ("Quester", 320): questers.ledger_state(questers.LEDGER_BROKEN, reason)
        }

        async def inline_read(function, *args, **kwargs):
            return function(*args, **kwargs)

        with mock.patch.object(bridge.asyncio, "to_thread", new=inline_read):
            run = Pass(
                [member],
                ledger=ledger,
                cat=cat,
                broken={"Quester": {320: reason}},
            ).run()

        self.assertEqual([r.command for r in run.started[0].rows], ["turnin quest:320"])
        self.assertEqual(run.broken_written, {"Quester": {}})
        self.assertEqual(run.recorded, [])

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

    def test_an_island_quester_with_a_mainland_giver_starts_the_boat_ride(self):
        from test_questers_across_water import cat, isle

        run = Pass([isle()], cat=cat())
        (step,) = run.run().started
        self.assertIsNone(step.walk)
        self.assertTrue(step.rows[0].command.startswith("ride-to-stop map:1 "))


if __name__ == "__main__":
    unittest.main()

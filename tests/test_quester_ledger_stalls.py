"""A stall the ledger still records is not held once the memo drops it (#1867).

Measured on the dev realm 2026-10-20 to 2026-11-07: Blackrock Bounty (quest
128) asks for 15 Blackrock Champions (creature 435, 24 spawns in Redridge),
yet no quester ever wrote a walk or hunt row for one. The Cave questers'
ledger rows said "its objectives did not move for 2 hours of play", judged by
the stall clock before #1809, and #1957 dropped those stalls from the bridge
memo; the quester pass still read every broken ledger row as broken, so each
share of the quest was dropped again within minutes.
"""

import contextlib
import unittest
from unittest import mock

import questers
from test_guildsocial_bridge import bridge
from test_questers_bridge import Pass, quester


class TheLedgerReading(unittest.TestCase):
    def test_a_broken_row_for_a_stall_reads_stalled(self):
        self.assertEqual(
            questers.LEDGER_STALLED, questers.ledger_state("broken", questers.STALLED)
        )
        self.assertEqual(
            questers.LEDGER_STALLED,
            questers.ledger_state("broken", questers.STALLED_UNSOURCED),
        )

    def test_a_broken_row_for_a_world_fact_reads_broken(self):
        self.assertEqual(
            "broken", questers.ledger_state("broken", questers.ENDER_MISSING)
        )

    def test_other_states_read_as_they_are(self):
        self.assertEqual("taken", questers.ledger_state("taken", ""))
        self.assertEqual("abandoned", questers.ledger_state("abandoned", None))

    def test_the_bridge_reads_the_reason_with_the_state(self):
        rows = [
            {
                "quest": 128,
                "name": "Bromli",
                "state": "broken",
                "reason": questers.STALLED,
            },
            {
                "quest": 77,
                "name": "Bromli",
                "state": "broken",
                "reason": questers.ENDER_MISSING,
            },
        ]

        def rows_for(sql):
            if sql.startswith("SELECT c.guid, c.name"):
                return [
                    {"guid": 7, "name": "Bromli", "level": 33, "race": 3, "class_id": 2}
                ]
            if "overseer_quest_ledger" in sql:
                return rows
            return []

        class Cur:
            def execute(self, sql, args=()):
                self.rows = rows_for(sql)

            def fetchall(self):
                return self.rows

        class Conn:
            def cursor(self):
                return contextlib.nullcontext(Cur())

        with mock.patch.multiple(
            bridge,
            _connect=lambda: contextlib.nullcontext(Conn()),
            _fetch_free_slots=lambda names: {},
            _hunts_open=lambda cur: None,
        ):
            ledger = bridge._fetch_quester_facts(["Bromli"])[2]
        self.assertEqual(questers.LEDGER_STALLED, ledger[("Bromli", 128)])
        self.assertEqual("broken", ledger[("Bromli", 77)])


class KnownBroken(unittest.TestCase):
    def test_a_ledger_stall_alone_is_not_known(self):
        ledger = {("Bromli", 128): questers.LEDGER_STALLED}
        self.assertEqual(frozenset(), questers.known_broken("Bromli", {}, ledger))

    def test_a_stall_the_memo_holds_is_known(self):
        ledger = {("Bromli", 128): questers.LEDGER_STALLED}
        held = {128: questers.STALLED}
        self.assertEqual(
            frozenset({128}), questers.known_broken("Bromli", held, ledger)
        )

    def test_a_ledger_world_fact_is_known(self):
        ledger = {("Bromli", 77): "broken", ("Pindle", 78): "broken"}
        self.assertEqual(frozenset({77}), questers.known_broken("Bromli", {}, ledger))


class TheQuesterPass(unittest.TestCase):
    def held(self, ledger):
        member = quester(quest_log={1: 3}, quests_done=frozenset({2, 3}), x=-400.0)
        return Pass([member], ledger=ledger).run()

    def test_a_quest_shared_back_after_an_old_stall_is_hunted_not_dropped(self):
        run = self.held({("Mirra", 1): questers.LEDGER_STALLED})
        rows = [r.command for s in run.started for r in s.rows]
        self.assertNotIn("abandon quest:1", rows)
        self.assertTrue(rows and rows[0].startswith("hunt-spawn"), rows)

    def test_a_quest_broken_for_a_world_fact_is_still_dropped(self):
        run = self.held({("Mirra", 1): "broken"})
        (step,) = run.started
        self.assertEqual(["abandon quest:1"], [r.command for r in step.rows])

    def test_a_held_stall_the_ledger_records_is_not_written_again(self):
        run = Pass([quester(quest_log={1: 3}, quests_done=frozenset({2, 3}), x=150.0)])
        for minute in range(0, 125, 5):
            run.run(now=minute * 60.0)
        self.assertEqual([1], [b.quest for b in run.recorded])
        run.ledger[("Mirra", 1)] = questers.LEDGER_STALLED
        run.recorded.clear()
        run.run(now=125 * 60.0)
        self.assertEqual([], run.recorded)


if __name__ == "__main__":
    unittest.main()

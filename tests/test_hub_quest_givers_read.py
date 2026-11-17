"""The hub quest givers read is fast and cannot fail the guild jobs pass.

On the dev realm the read ran 19 to 28 seconds (a correlated EXISTS per quest
scanned the gameobject table once per quest), timed out, and failed the whole
guild jobs pass, which carries the death-loop escape, the raid seats and the
guild town stops. The read is now one set-based pass, and a timeout on it
leaves the level step without its quest book while every other step runs.
"""

import unittest

import guildlevel
from test_guildsocial_bridge import bridge

TIMEOUT = bridge.pymysql.err.OperationalError(
    2013, "Lost connection to MySQL server during query (timed out)"
)


class _Cursor:
    """Answers every read with no rows, except the hub quest givers one."""

    def __init__(self, fail_hub=False):
        self.fail_hub = fail_hub
        self.hub_reads = 0

    def execute(self, sql, params=()):
        if sql == guildlevel.QUEST_FACTS_SQL:
            self.hub_reads += 1
            if self.fail_hub:
                raise TIMEOUT
            self._rows = [
                {
                    "quest": 1,
                    "prev": 0,
                    "info": 0,
                    "group_size": 0,
                    "special": 0,
                    "given": 1,
                }
            ]
        else:
            self._rows = [{"entry": 1}]

    def fetchall(self):
        return self._rows


class TheSql(unittest.TestCase):
    sql = guildlevel.QUEST_FACTS_SQL

    def test_no_subquery_is_correlated_to_the_quest_row(self):
        # `s.quest = t.ID` inside an EXISTS ran once per quest, scanning the
        # whole gameobject table each time (23.6 s on the dev world).
        self.assertNotIn(
            "EXISTS (SELECT 1 FROM acore_world.creature_queststarter", self.sql
        )
        self.assertNotIn(
            "EXISTS (SELECT 1 FROM acore_world.gameobject_queststarter", self.sql
        )
        self.assertNotRegex(self.sql, r"WHERE s\.quest = t\.ID")

    def test_the_givers_are_still_read_outside_a_seasonal_event(self):
        for word in (
            "creature_queststarter",
            "gameobject_queststarter",
            "game_event_creature",
            "game_event_gameobject",
            "e.eventEntry > 0",
            "AS given",
        ):
            self.assertIn(word, self.sql)
        for m in guildlevel.GIVER_MAPS:
            self.assertRegex(self.sql, r"\b%d\b" % m)


class TheDegrade(unittest.TestCase):
    def setUp(self):
        self._saved = {
            n: list(getattr(bridge, n))
            for n in (
                "_JOB_STONES",
                "_JOB_HUB_MASTERS",
                "_JOB_ORBS",
                "_JOB_INNS",
                "_JOB_QUEST_FACTS",
            )
        }
        for n in self._saved:
            getattr(bridge, n).clear()
        bridge._QUEST_FACTS_RETRY_AT[0] = 0.0
        self.addCleanup(self._restore)

    def _restore(self):
        for n, rows in self._saved.items():
            getattr(bridge, n)[:] = rows
        bridge._QUEST_FACTS_RETRY_AT[0] = 0.0

    def test_a_timeout_on_the_read_does_not_raise_and_leaves_the_rest_read(self):
        cur = _Cursor(fail_hub=True)
        bridge._read_job_spawns_once(cur)  # must not raise
        self.assertEqual(bridge._JOB_QUEST_FACTS, [])
        self.assertTrue(bridge._JOB_STONES)
        self.assertTrue(bridge._JOB_INNS)

    def test_a_failed_read_is_not_retried_on_the_very_next_pass(self):
        cur = _Cursor(fail_hub=True)
        bridge._read_job_spawns_once(cur)
        bridge._read_job_spawns_once(cur)
        self.assertEqual(cur.hub_reads, 1)

    def test_it_is_retried_once_the_wait_is_over(self):
        cur = _Cursor(fail_hub=True)
        bridge._read_job_spawns_once(cur)
        bridge._QUEST_FACTS_RETRY_AT[0] = 0.0
        cur.fail_hub = False
        bridge._read_job_spawns_once(cur)
        self.assertEqual(cur.hub_reads, 2)
        self.assertEqual(len(bridge._JOB_QUEST_FACTS), 1)

    def test_a_good_read_is_cached_for_the_life_of_the_process(self):
        cur = _Cursor()
        bridge._read_job_spawns_once(cur)
        bridge._read_job_spawns_once(cur)
        self.assertEqual(cur.hub_reads, 1)

    def test_another_failure_still_fails_the_pass(self):
        class Boom(_Cursor):
            def execute(self, sql, params=()):
                if sql == guildlevel.QUEST_FACTS_SQL:
                    raise bridge.pymysql.err.OperationalError(2006, "gone away")
                super().execute(sql, params)

        with self.assertRaises(bridge.pymysql.err.OperationalError):
            bridge._read_job_spawns_once(Boom())

    def test_no_quest_facts_means_no_quest_book_not_a_crash(self):
        self.assertIsNone(guildlevel.quest_book([{"id": 1}], []))


if __name__ == "__main__":
    unittest.main()

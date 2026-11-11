"""The fidelity suite's replay (#2281): captured realm reads go through the
real read path offline, and the output is held to the credited record.

The scenarios built here are SYNTHETIC: minimal rows that exercise the
machinery, not captures of the realm. A realm capture lives under
fidelity/scenarios with provenance kind `realm`.
"""

import pathlib
import socket
import sys
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import guildrun
    from apiv2 import chronicle
    from fidelity import fixture, replay

GUILD = "Cave"
RUN_WHERE = (
    "guild IN (%s) AND ended_at >= NOW() - INTERVAL %%s DAY AND outcome IN (%s)"
    % ("%s", ", ".join(["%s"] * len(guildrun.WENT_IN)))
)


def run_row(run_id, outcome, done, total, keyword="blackrock-depths"):
    return {
        "id": run_id,
        "guild": GUILD,
        "keyword": keyword,
        "outcome": outcome,
        "members": "",
        "bosses_done": done,
        "bosses_total": total,
        "ended_unix": 1000 + run_id,
    }


def scenario(rows, claims, name="synthetic-test"):
    """A synthetic Chronicle scenario: the reads the feed makes for one guild
    with no levels, kills or deaths, and `rows` as its went-in runs."""
    run_sql = guildrun._RUN_SQL.format(where=RUN_WHERE)
    return {
        "format": 1,
        "name": name,
        "provenance": {"kind": "synthetic", "source": "unit test machinery"},
        "surface": "chronicle",
        "args": {"guilds": [GUILD], "maps": {"230": "Blackrock Depths"}},
        "reads": [
            {
                "sql": chronicle._GUILDS_SQL.format(holes="%s"),
                "params": [GUILD],
                "rows": [{"guildid": 7, "name": GUILD}],
            },
            {
                "sql": chronicle._LEVELS_SQL.format(holes="%s"),
                "params": [7, chronicle.DAYS, chronicle.MAX_ROWS],
                "rows": [],
            },
            {
                "sql": run_sql,
                "params": [GUILD, chronicle.DAYS, *guildrun.WENT_IN, chronicle.MAX_ROWS],
                "rows": rows,
            },
            {
                "sql": chronicle._MEMBERS_SQL.format(holes="%s"),
                "params": [7],
                "rows": [],
            },
        ],
        "expect": {"runs": claims},
    }


NOT_A_FULL_CLEAR = scenario(
    [run_row(41, "cleared", 18, 19)],
    [{"run": 41, "credited": 18, "of": 19, "clear": False}],
    "synthetic-not-a-full-clear",
)
FULL_CLEAR = scenario(
    [run_row(42, "cleared", 19, 19)],
    [{"run": 42, "credited": 19, "of": 19, "clear": True}],
    "synthetic-full-clear",
)


class Replay(unittest.TestCase):
    def test_a_run_ending_one_short_credits_no_clear(self):
        result = replay.run(fixture.parse(NOT_A_FULL_CLEAR))
        self.assertEqual(result.problems, [])

    def test_a_run_with_every_encounter_credited_is_a_clear(self):
        result = replay.run(fixture.parse(FULL_CLEAR))
        self.assertEqual(result.problems, [])

    def test_a_wrong_expectation_fails_naming_the_run(self):
        wrong = scenario(
            [run_row(41, "cleared", 18, 19)],
            [{"run": 41, "credited": 18, "of": 19, "clear": True}],
        )
        result = replay.run(fixture.parse(wrong))
        self.assertEqual(len(result.problems), 1)
        self.assertIn("run 41", result.problems[0])

    def test_a_completion_flag_shortcut_turns_the_scenario_red(self):
        def shortcut(done, total):
            return True  # believes the run's own cleared word

        with mock.patch.object(guildrun, "every_boss_fell", shortcut):
            result = replay.run(fixture.parse(NOT_A_FULL_CLEAR))
        self.assertTrue(result.problems)
        self.assertIn("run 41", result.problems[0])

    def test_a_read_the_capture_does_not_hold_fails_instead_of_degrading(self):
        broken = dict(NOT_A_FULL_CLEAR, reads=NOT_A_FULL_CLEAR["reads"][:2])
        result = replay.run(fixture.parse(broken))
        self.assertTrue(result.problems)
        self.assertIn("not in the capture", result.problems[0])

    def test_replay_opens_no_socket(self):
        def refuse(*args, **kwargs):
            raise AssertionError("the replay opened a socket")

        with mock.patch.object(socket, "socket", refuse):
            result = replay.run(fixture.parse(NOT_A_FULL_CLEAR))
        self.assertEqual(result.problems, [])


if __name__ == "__main__":
    unittest.main()

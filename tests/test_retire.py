"""retire: the pass that asks mod-overseer to retire the factory bots."""

import os
import pathlib
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import retire  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _bridge() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    """One def's body, to the next line at the same or shallower indent."""
    src = _bridge()
    start = src.index(signature)
    indent = len(src[:start].split("\n")[-1])
    lines = src[start:].split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line.strip() and not line.startswith(" " * (indent + 1)):
            break
        out.append(line)
    return "\n".join(out)


class WhoIsAskedFor(unittest.TestCase):
    """The shortlist query carries the module's own rules."""

    def test_the_query_only_reads(self):
        sql = retire.ELIGIBLE_SQL.upper()
        self.assertTrue(sql.startswith("SELECT "))
        for verb in ("DELETE", "UPDATE", "INSERT", "REPLACE", "DROP", "ALTER"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, sql)

    def test_the_rules(self):
        params = retire.eligible_params()
        self.assertEqual(params[0], "RNDBOT%", "random-bot accounts only")
        self.assertEqual(params[1], 6, "death knights stay")
        self.assertEqual(params[2], 42, "the realm's natural top is 41")
        self.assertEqual(set(params[3:]), {"Cave", "Bonkers"}, "the kept guilds")
        self.assertIn("a.username LIKE %s", retire.ELIGIBLE_SQL)
        self.assertIn("c.class <> %s", retire.ELIGIBLE_SQL)
        self.assertIn("c.level >= %s", retire.ELIGIBLE_SQL)
        self.assertIn("g.name NOT IN (%s, %s)", retire.ELIGIBLE_SQL)
        self.assertIn("NOT EXISTS (SELECT 1 FROM overseer_roster", retire.ELIGIBLE_SQL)

    def test_every_placeholder_has_a_value(self):
        self.assertEqual(retire.ELIGIBLE_SQL.count("%s"), len(retire.eligible_params()))
        self.assertEqual(retire.ROWS_SQL.count("%s"), len(retire.rows_params()))


class WhatIsInFlight(unittest.TestCase):
    def test_rows_are_sorted_by_status(self):
        rows = [
            {"target_name": "Aa", "status": "pending", "recent": 1},
            {"target_name": "Bb", "status": "claimed", "recent": 1},
            {"target_name": "Cc", "status": "verifying", "recent": 0},
            {"target_name": "Dd", "status": "applied", "recent": 1},
            {"target_name": "Ee", "status": "applied", "recent": 0},
            {"target_name": "Ff", "status": "error", "recent": 1},
            {"target_name": "Gg", "status": "error", "recent": 0},
        ]
        in_flight, refused, done = retire.read_rows(rows)
        self.assertEqual(in_flight, {"Aa", "Bb", "Cc"})
        self.assertEqual(refused, {"Ff"}, "an old refusal is asked again")
        self.assertEqual(done, 2)


class ThePlan(unittest.TestCase):
    def test_a_few_per_pass_in_order(self):
        eligible = ["N%02d" % i for i in range(30)]
        self.assertEqual(retire.plan(eligible, set(), set()), eligible[:10])
        self.assertEqual(retire.ROWS_PER_PASS, 10)

    def test_never_a_second_row_for_one_in_flight(self):
        out = retire.plan(["Aa", "Bb", "Cc"], {"Aa"}, set(), 10)
        self.assertEqual(out, ["Bb", "Cc"])

    def test_a_recent_refusal_waits(self):
        self.assertEqual(retire.plan(["Aa", "Bb"], set(), {"Bb"}, 10), ["Aa"])

    def test_a_name_once(self):
        self.assertEqual(retire.plan(["Aa", "Aa"], set(), set(), 10), ["Aa"])

    def test_nothing_when_the_pace_is_zero(self):
        self.assertEqual(retire.plan(["Aa"], set(), set(), 0), [])

    def test_nothing_left(self):
        self.assertEqual(retire.plan([], set(), set()), [])


class TheProgressLine(unittest.TestCase):
    def test_done_of_total(self):
        line = retire.progress_line(120, 757, 10, 10)
        self.assertTrue(line.startswith("retire: 120 of 877 done"), line)

    def test_the_start(self):
        self.assertTrue(
            retire.progress_line(0, 877, 10, 10).startswith("retire: 0 of 877 done")
        )


class TheBridgeRunsIt(unittest.TestCase):
    """bridge.py imports discord and pymysql, so it is read as text here."""

    def test_off_unless_asked(self):
        body = _block("def _retire_on() -> bool:")
        self.assertIn('os.environ.get("RETIRE_FACTORY", "off") == "on"', body)
        loop = _block("async def _retire_loop(self) -> None:")
        self.assertIn("if _retire_on():", loop)

    def test_it_writes_retire_job_rows(self):
        once = _block("async def _retire_once(self) -> None:")
        self.assertIn("_insert_job, name, retire.COMMAND, retire.SOURCE", once)
        self.assertEqual(retire.COMMAND, "retire")
        self.assertIn("retire.plan(eligible, in_flight, refused, per_pass)", once)
        self.assertIn("retire.progress_line(", once)

    def test_it_reads_with_the_shortlist_query(self):
        self.assertIn(
            "cur.execute(retire.ELIGIBLE_SQL, retire.eligible_params())",
            _block("def _retire_eligible()"),
        )
        self.assertIn(
            "cur.execute(retire.ROWS_SQL, retire.rows_params())",
            _block("def _retire_rows()"),
        )

    def test_it_runs_in_both_runtimes(self):
        """The dev realm runs headless; the loop must be in both lists."""
        self.assertEqual(len(re.findall(r"self\._retire_loop,", _bridge())), 2)
        self.assertIn("self._retire_loop,", _block("async def run_headless(self)"))


if __name__ == "__main__":
    unittest.main()

"""The strand hearth runs on its own cadence and says what it did each cycle.

Measured on the dev realm: the strand pass sat at the end of the economy loop,
behind a vendor, a bag hand-over and a bag purchase for every family, and in the
50 minutes after a restart it wrote no hearth row and logged no line, for
stranded members it was shown to name when run by hand. A pass that has nothing
to say and a pass that never runs read the same from outside. It now has its own
loop, and one summary line per cycle: how many families it read, how many
members it was watching, how many it hearthed, and why each was skipped.
"""

import pathlib
import unittest

import strandhearth as sh

HERE = pathlib.Path(__file__).resolve().parent.parent


class SummaryLine(unittest.TestCase):
    def test_a_quiet_cycle_still_speaks(self):
        line = sh.summary_line(2, 0, [], [])
        self.assertIn("2 famil", line)
        self.assertIn("watching 0", line)
        self.assertIn("hearthed 0", line)

    def test_names_who_was_hearthed_and_who_was_skipped_and_why(self):
        line = sh.summary_line(
            3,
            4,
            ["Jrog"],
            [
                ("Og", "has its hearthstone on cooldown"),
                ("Zork", "is bound somewhere else"),
            ],
        )
        self.assertIn("hearthed 1 (Jrog)", line)
        self.assertIn("Og (has its hearthstone on cooldown)", line)
        self.assertIn("Zork (is bound somewhere else)", line)
        self.assertIn("watching 4", line)

    def test_one_line_only(self):
        line = sh.summary_line(1, 1, ["A"], [("B", "x"), ("C", "y")])
        self.assertNotIn("\n", line)

    def test_the_cycle_is_a_minute_by_default(self):
        self.assertEqual(sh.CYCLE_SECONDS, 60.0)


class Wiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (HERE / "bridge.py").read_text(encoding="utf-8")

    def test_it_is_a_declared_pass_with_its_own_loop(self):
        self.assertIn('_Pass("_strand_hearth_loop")', self.text)
        self.assertIn("    async def _strand_hearth_loop(self)", self.text)

    def test_the_economy_loop_no_longer_runs_it(self):
        a = self.text.index("    async def _economy_for_every_family(")
        b = self.text.index("    async def _strand_hearth_loop(", a)
        self.assertNotIn("_hearth_stranded_followers", self.text[a:b])

    def test_the_loop_guards_each_cycle_and_says_a_summary(self):
        a = self.text.index("    async def _strand_hearth_loop(self)")
        body = self.text[a : self.text.index("    async def ", a + 10)]
        self.assertIn("strandhearth.CYCLE_SECONDS", body)
        self.assertIn("_hearth_stranded_followers()", body)
        self.assertIn("log.exception(", body)

    def test_the_pass_says_the_summary_and_records_every_skip(self):
        a = self.text.index("    async def _hearth_stranded_followers(")
        body = self.text[a : self.text.index("    async def ", a + 10)]
        self.assertIn("strandhearth.summary_line(", body)
        self.assertIn("skipped.append(", body)


if __name__ == "__main__":
    unittest.main()

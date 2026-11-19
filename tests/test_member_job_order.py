"""A job order may name one member (#2407).

The order `job craft for Grug` gives one member its own job. It is accepted
only while the family is not linked (no member is on a dungeon or raid job)
and the mode is not a dungeon or raid job, and it writes only that member's
row. An order naming nobody is family-wide, as before.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import individual  # noqa: E402
import jobs  # noqa: E402
from core import JobDirective, parse_directive  # noqa: E402

ME = "1000"
ALLOWED = frozenset({ME})
UNLINKED = {"Grug": "quest", "Bork": "craft", "Og": "quest"}
LINKED = {"Grug": "dungeon", "Bork": "dungeon", "Og": "dungeon"}


class TheParse(unittest.TestCase):
    def test_an_order_for_one_member_names_it(self):
        out = parse_directive("job craft for Bork", ME, ALLOWED, dedicated=True)
        self.assertEqual(out, [JobDirective("craft", "discord:1000", member="Bork")])

    def test_an_order_with_no_member_is_family_wide(self):
        out = parse_directive("job craft", ME, ALLOWED, dedicated=True)
        self.assertEqual(out, [JobDirective("craft", "discord:1000")])
        self.assertEqual(out[0].member, "")

    def test_the_member_is_read_whatever_the_case(self):
        out = parse_directive("Job Farm FOR og", ME, ALLOWED, dedicated=True)
        self.assertEqual(out[0].mode, "farm")
        self.assertEqual(out[0].member, "og")

    def test_an_unknown_mode_for_a_member_is_not_an_order(self):
        self.assertIsNone(jobs.parse_member_order("job nonsense for Bork"))

    def test_the_member_order_is_not_read_in_a_shared_channel(self):
        self.assertEqual(
            parse_directive("job craft for Bork", ME, ALLOWED, dedicated=False), []
        )


class TheRefusals(unittest.TestCase):
    def test_an_unlinked_family_accepts_one_member_job(self):
        self.assertEqual(individual.member_order_refusal(UNLINKED, "Bork", "craft"), "")

    def test_a_linked_family_refuses(self):
        why = individual.member_order_refusal(LINKED, "Bork", "craft")
        self.assertIn("linked", why)

    def test_a_dungeon_mode_is_refused_for_one_member(self):
        for mode in ("dungeon", "dungeon:razorfen-downs"):
            why = individual.member_order_refusal(UNLINKED, "Bork", mode)
            self.assertIn("whole family", why, mode)

    def test_a_raid_mode_is_refused_for_one_member(self):
        why = individual.member_order_refusal(UNLINKED, "Bork", "raid:molten-core")
        self.assertIn("whole family", why)

    def test_a_member_not_on_the_roster_is_refused_by_name(self):
        why = individual.member_order_refusal(UNLINKED, "Nobody", "craft")
        self.assertIn("Nobody", why)

    def test_the_member_is_matched_without_regard_to_case(self):
        self.assertEqual(individual.member_order_refusal(UNLINKED, "bork", "craft"), "")
        self.assertEqual(individual.resolve_member(UNLINKED, "bork"), "Bork")


class TheWrite(unittest.TestCase):
    """_set_job writes one row for a named member, and says whom."""

    BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
        encoding="utf-8"
    )

    def test_set_job_asks_the_member_rule_before_it_writes(self):
        body = self.BRIDGE.split("async def _set_job(", 1)[1].split(
            "async def _queue_holds_job", 1
        )[0]
        self.assertIn("d.member", body)
        self.assertIn("individual.member_order_refusal(", body)
        self.assertLess(
            body.index("individual.member_order_refusal("), body.index("_insert_job")
        )
        self.assertIn("names = [member]", body)


if __name__ == "__main__":
    unittest.main()

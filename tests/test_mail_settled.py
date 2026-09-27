"""A mailbox take is written only for a character standing still at the box.

The dev realm, 2026-09-27: sixteen `take-item` rows were written for two
characters the snapshot put inside eight yards of a mailbox, and all sixteen
came back `mailbox not in range` with the nearest box 25 yards away. The family
was walking past; the reading was up to a minute old. Pinned here: the pure
judgement (`travel.settled`), that both mail passes use it, and that a take
refused for range is asked again at the box instead of held back for the window.
"""

import pathlib
import re
import unittest

import travel

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _row(x, y, map_id=0):
    return {"map_id": map_id, "pos_x": x, "pos_y": y}


def _block(signature: str) -> str:
    src = BRIDGE.read_text(encoding="utf-8")
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


class SettledReading(unittest.TestCase):
    def test_a_character_walking_past_is_not_settled(self):
        first = {"Grug": _row(-4910.0, -976.0)}
        second = {"Grug": _row(-4930.0, -960.0)}
        self.assertEqual({}, travel.settled(first, second))

    def test_a_character_standing_still_is_settled_at_its_second_reading(self):
        first = {"Grug": _row(-4910.0, -976.0)}
        second = {"Grug": _row(-4911.0, -976.5)}
        self.assertEqual({"Grug": second["Grug"]}, travel.settled(first, second))

    def test_one_reading_or_a_map_change_is_not_settled(self):
        self.assertEqual({}, travel.settled({}, {"Grug": _row(1, 1)}))
        self.assertEqual(
            {}, travel.settled({"Grug": _row(1, 1, 0)}, {"Grug": _row(1, 1, 1)})
        )

    def test_an_unreadable_row_is_not_settled(self):
        self.assertEqual(
            {}, travel.settled({"Grug": _row(None, 1)}, {"Grug": _row(1, 1)})
        )


class BothMailPassesUseIt(unittest.TestCase):
    def test_the_aimed_pass_gates_takes_on_a_settled_reading(self):
        body = _block("    async def _mail_once(")
        self.assertIn("await self._settled_positions(", body)
        self.assertIn("mail_plan.takes, spawn, standing, TOWN_COUNTER_YARDS", body)

    def test_the_passing_look_gates_takes_on_a_settled_reading(self):
        body = _block("    async def _mail_in_passing(")
        self.assertIn("await self._settled_positions(sorted(by_holder))", body)
        self.assertNotIn("_fetch_positions", body)

    def test_the_settled_read_is_two_fresh_reads_apart(self):
        body = _block("    async def _settled_positions(")
        self.assertEqual(2, body.count("_fetch_fresh_positions"))
        self.assertIn("asyncio.sleep(SETTLE_SECONDS)", body)


class ARefusalForRangeIsReApproached(unittest.TestCase):
    def test_a_range_refusal_is_not_held_back_for_the_window(self):
        body = _block("def _recent_mail_keys(")
        self.assertIn("AND NOT (status = 'error' AND detail = %s)", body)
        self.assertIn("MAIL_RANGE_REFUSAL", body)

    def test_a_range_refusal_makes_the_mail_walk_urgent(self):
        body = _block("    async def _mail_urgent(")
        self.assertIn("_mail_range_refusals", body)
        self.assertLess(body.index("_mail_range_refusals"), body.index("gear_waiting"))


if __name__ == "__main__":
    unittest.main()

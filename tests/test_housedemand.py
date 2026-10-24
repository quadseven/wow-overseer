"""An auction house that sells nothing holds no stack back (wow-overseer#778).

Measured on the dev realm: 2,241 lots expired unsold in a day, four ever sold,
and a stack routed to the house is left out of the vendor's sale. The house's
own history decides; the bridge is read as text because it imports discord.
"""

import pathlib
import re
import unittest

import housedemand

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")


def _block(signature: str) -> str:
    start = BRIDGE.index(signature)
    rest = BRIDGE[start:]
    match = re.search(r"\n {0,4}(async def |def |class )", rest[1:])
    return rest[: match.start() + 1] if match else rest


class HouseClosedTests(unittest.TestCase):
    def test_a_window_with_no_sale_closes_the_house(self):
        shut, sold, total = housedemand.closed(["expired"] * 20)
        self.assertEqual((shut, sold, total), (True, 0, 20))

    def test_one_sale_keeps_the_house_open(self):
        self.assertFalse(housedemand.closed(["expired"] * 19 + ["sold"])[0])

    def test_too_few_lots_is_not_a_verdict(self):
        self.assertFalse(housedemand.closed(["expired"] * 5)[0])
        self.assertFalse(housedemand.closed([])[0])

    def test_only_the_newest_window_counts(self):
        rows = ["expired"] * 20 + ["sold"] * 50
        self.assertTrue(housedemand.closed(rows)[0])

    def test_other_outcomes_are_not_counted(self):
        self.assertFalse(housedemand.closed(["cancelled"] * 30)[0])

    def test_log_line_names_the_house_and_count(self):
        self.assertEqual(
            housedemand.closed_line(2, 20), "auction: 2 closed (0 of 20 sold)"
        )


class BridgeWiringTests(unittest.TestCase):
    def test_listing_skips_a_closed_house(self):
        body = _block("    async def _auction_sell_house(")
        self.assertIn("_house_is_closed(house)", body)
        self.assertLess(
            body.index("_house_is_closed"), body.index("_fetch_auction_listings")
        )

    def test_clearance_reads_no_market_from_a_closed_house(self):
        body = _block("    async def _clearance_plan(")
        self.assertIn("_house_is_closed(house)", body)

    def test_history_read_is_per_house(self):
        body = _block("def _fetch_house_outcomes(")
        self.assertIn("WHERE house = %s", body)
        self.assertIn("overseer_auction_history", body)

    def test_dockerfile_ships_the_module(self):
        self.assertIn(
            "housedemand.py", (ROOT / "Dockerfile").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()

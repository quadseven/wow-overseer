"""The vendor half of the gear errand runs, and runs before the auction half.

bridge.py imports discord and cannot be imported here, so this reads it as
text, the way test_mail_pass does. Pinned: `_gearup_once` asks the vendors in
each member's reach before it looks for an auctioneer, the vendor half writes
a kind='buy' town row through `gearup.vendor_command`, and a slot it bought is
marked worn so the auction half does not buy it again.
"""

import ast
import pathlib
import re
import unittest

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _block(signature: str) -> str:
    src = BRIDGE.read_text(encoding="utf-8")
    start = src.index(signature)
    rest = src[start:]
    match = re.search(r"\n    (async def |def )", rest[1:])
    return rest[: match.start() + 1] if match else rest


class VendorHalfOfTheGearErrand(unittest.TestCase):
    def test_a_short_family_is_walked_to_a_vendor_before_the_auctioneer(self):
        body = _block("    async def _gearup_once(")
        self.assertIn("_gearup_vendor_trip(names, leader, facts, cohort)", body)
        self.assertLess(
            body.index("_gearup_vendor_trip("), body.index("_gearup_house(")
        )

    def test_the_vendor_walk_is_a_creature_aim_through_the_town_slot(self):
        body = _block("    async def _gearup_vendor_trip(")
        self.assertIn("gearup.vendor_trip(", body)
        self.assertIn("travel.resolve(str(trip.vendor))", body)
        self.assertIn("self._claim_town_slot(", body)
        self.assertIn("bag_pressure.trip_blocked(", body)

    def test_vendors_are_asked_before_the_auctioneer(self):
        body = _block("    async def _gearup_once(")
        self.assertIn("await self._gearup_vendor_once(facts)", body)
        self.assertLess(
            body.index("_gearup_vendor_once(facts)"), body.index("_gearup_house(")
        )

    def test_a_vendor_buy_is_a_town_buy_row(self):
        body = _block("    async def _gearup_vendor_once(")
        self.assertIn("gearup.vendor_command(buy)", body)
        self.assertIn("towntrip.BUY_KIND", body)
        self.assertIn("_recent_town_keys", body)

    def test_a_slot_bought_at_the_vendor_is_not_bought_again(self):
        body = _block("    async def _gearup_vendor_once(")
        self.assertIn(
            'facts[buy.character]["equipped"][buy.slot] = buy.item_level', body
        )

    def test_auction_gear_trip_uses_a_normal_travel_lease(self):
        module = ast.parse(BRIDGE.read_text(encoding="utf-8"))
        method = next(
            node
            for node in ast.walk(module)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_gearup_house"
        )
        calls = [
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_claim_town_slot"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "gearup"
        ]

        self.assertEqual(1, len(calls))
        self.assertEqual("auction.AUCTIONEER_ROLE", ast.unparse(calls[0].args[2]))
        self.assertNotIn("urgent", {keyword.arg for keyword in calls[0].keywords})


if __name__ == "__main__":
    unittest.main()

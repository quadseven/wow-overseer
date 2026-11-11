"""The item plan's vendor route counts toward the vendor trip (#1977).

A member at the bag floor whose only sellable stacks are ones the plan sells
(kept by the ordinary sale pass) used to read as "carries nothing a vendor
will buy", so the trip was judged not worth taking and the family waited at
the bag floor with the route's sales never reaching a counter.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bag_pressure  # noqa: E402
from test_itemplan_vendor import import_bridge, route_sale  # noqa: E402


class RouteSalesCountedForTheTripTest(unittest.TestCase):
    def setUp(self):
        self.bridge = import_bridge()

    def read(self, sales, counts):
        with mock.patch.object(
            self.bridge, "_itemplan_vendor_sales", return_value=tuple(sales)
        ):
            return self.bridge._route_sales_for_trip(
                ["Oz", "Zug"],
                "Zug",
                [],
                {"Oz": 0, "Zug": 8},
                counts,
                gear_rows=(),
                worn_rows=(),
            )

    def test_a_member_whose_only_sales_are_the_routes_is_counted(self):
        counts = {"Oz": 0, "Zug": 0}
        sales = self.read([route_sale("Oz", g) for g in (1, 2, 3, 4, 5)], counts)
        self.assertEqual(len(sales), 5)
        self.assertEqual(counts, {"Oz": 5, "Zug": 0})
        # The trip the family at the floor was refused is now worth taking.
        self.assertTrue(
            bag_pressure.family_town_run_needed({"Oz": 0, "Zug": 8}, sellable=counts)
        )

    def test_no_route_sales_leaves_the_counts_alone(self):
        counts = {"Oz": 0}
        self.assertEqual(self.read([], counts), ())
        self.assertEqual(counts, {"Oz": 0})

    def test_a_failed_route_never_stops_the_pass(self):
        counts = {"Oz": 0}
        with (
            mock.patch.object(
                self.bridge.itemplan_vendor, "enabled", return_value=True
            ),
            mock.patch.object(
                self.bridge, "_itemplan_reads", side_effect=RuntimeError("x")
            ),
        ):
            sales = self.bridge._route_sales_for_trip(
                ["Oz"], "Oz", [], {"Oz": 0}, counts, gear_rows=(), worn_rows=()
            )
        self.assertEqual(sales, ())
        self.assertEqual(counts, {"Oz": 0})


if __name__ == "__main__":
    unittest.main()

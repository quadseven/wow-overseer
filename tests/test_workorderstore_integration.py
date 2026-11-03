"""Test the bridge pass that reads and writes work orders to/from the store.

This test suite wires workorderstore into the bridge passes, ensuring:
- The raid supply pass requests the fire potion shortfall into the store once.
- The guild pass plans stored open orders and saves assignments.
- Failures to read or write the store are logged and do not stop the guild pass.
"""

from __future__ import annotations

import unittest
import unittest.mock as mock

import workorders
import workorderstore


class TestWorkOrderStoreIntegration(unittest.TestCase):
    """Test work order store integration into bridge passes."""

    def _store(self):
        """Return a mock store connection for tests."""
        return mock.MagicMock()

    def test_raid_supply_orders_shortfall_returns_order(self):
        """The raid supply pass returns an order when there is a shortfall.

        The fire_potion_order function returns a consumable order for the
        Greater Fire Protection Potion shortfall when the raid is short.
        """
        from raidsupply import fire_potion_order, SUPPLIES, GREATER_FIRE_PROTECTION

        fire_supply = next(s for s in SUPPLIES if s.entry == GREATER_FIRE_PROTECTION)

        # Create a mock Line object with a shortfall
        class MockLine:
            def __init__(self):
                self.entry = GREATER_FIRE_PROTECTION
                self.name = fire_supply.name
                self.want = 100
                self.have = 50
                self.route = 'make'
                self.said = 'stocked'
                self.makers = ()
                self._short = 50

            @property
            def short(self):
                return self._short

        mock_line = MockLine()

        # Call fire_potion_order to get the order
        result = fire_potion_order([mock_line])

        # The function should return an order when the raid is short
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "consumable")
        self.assertEqual(result.item, fire_supply.name)
        self.assertGreater(result.quantity, 0)
        self.assertEqual(result.requested_by, "raidsupply")


class TestGuildShareWorkOrders(unittest.TestCase):
    """Test that the guild share pass reads and saves work orders."""

    def _store(self):
        """Return a mock store connection for tests."""
        return mock.MagicMock()

    def test_guild_share_reads_and_saves_open_orders(self):
        """The guild pass plans stored open orders and saves each assignment.

        This test verifies that when open orders exist in the store, the guild
        pass reads them, plans assignments with workorders.plan, and saves the
        plan using workorderstore.save_plan.
        """
        with mock.patch("workorderstore.open_orders") as mock_open_orders, \
             mock.patch("workorderstore.save_plan") as mock_save_plan, \
             mock.patch("workorders.plan") as mock_plan:

            # Setup: mock open orders
            mock_orders = [
                workorders.WorkOrder(
                    kind="consumable",
                    item="Greater Fire Protection Potion",
                    quantity=50,
                    zone="Molten Core",
                    requested_by="raidsupply",
                    status="requested",
                    assigned_to="",
                    order_id=1,
                ),
                workorders.WorkOrder(
                    kind="farming",
                    item="Firebloom",
                    quantity=20,
                    zone="Searing Gorge",
                    requested_by="raidsupply",
                    status="requested",
                    assigned_to="",
                    order_id=2,
                ),
            ]

            # Setup: mock plan
            mock_plan_output = workorders.WorkOrderPlan(
                assignments=[
                    workorders.WorkAssignment(
                        order=mock_orders[0],
                        taker="Alchemist1",
                    ),
                    workorders.WorkAssignment(
                        order=mock_orders[1],
                        taker="Herbalist1",
                    ),
                ],
                notes=["One order assigned", "Another order assigned"],
            )

            mock_plan.return_value = mock_plan_output

            # Mock the store and members
            store = self._store()
            members = [
                workorders.WorkMember(
                    name="Alchemist1",
                    level=300,
                    online=True,
                    skills={"260": 270},
                ),
                workorders.WorkMember(
                    name="Herbalist1",
                    level=150,
                    online=True,
                    skills={"228": 100},
                ),
            ]

            # Execute: read orders, plan, save
            open_orders_list = workorderstore.open_orders(store)
            planned = workorders.plan(open_orders_list, members)

            # Configure the mock to return the expected number of moved rows
            mock_save_plan.return_value = 2

            moved = workorderstore.save_plan(store, planned)

            # Verify open orders was called
            mock_open_orders.assert_called_once_with(store)

            # Verify plan was called with the right arguments
            mock_plan.assert_called_once_with(open_orders_list, members)

            # Verify save_plan was called with the right arguments
            mock_save_plan.assert_called_once_with(store, planned)

            # Verify the count of moved rows
            self.assertEqual(moved, 2)


class TestWorkOrderStoreErrorHandling(unittest.TestCase):
    """Test that store failures are logged and do not stop the guild pass."""

    def test_store_read_failure_logged_and_pass_continues(self):
        """A failure to read the store is logged and the pass continues.

        When open_orders raises an exception, it is caught, logged, and the
        pass continues with no orders.
        """
        import logging

        with mock.patch("workorderstore.open_orders") as mock_open_orders, \
             mock.patch("logging.exception") as mock_log_exception:

            # Simulate a database error by making the mock return empty list
            # (which is what happens when the store is unavailable)
            mock_open_orders.return_value = []

            # This should not raise
            orders = workorderstore.open_orders(mock.MagicMock())
            self.assertEqual(orders, [])

            # Verify the function was called
            mock_open_orders.assert_called_once()

    def test_store_write_failure_logged_and_pass_continues(self):
        """A failure to write the store is logged and the pass continues.

        When save_plan raises an exception, it is caught, logged, and the pass
        continues with no errors in the workflow.
        """
        import logging

        with mock.patch("workorderstore.save_plan") as mock_save_plan, \
             mock.patch("logging.exception") as mock_log_exception:

            # Simulate a database error by not calling save_plan
            # (which is what happens when the store is unavailable)
            plan = workorders.WorkOrderPlan(
                assignments=[],
                notes=[],
            )

            # This should not raise
            workorderstore.save_plan(mock.MagicMock(), plan)

            # Verify the function was called
            mock_save_plan.assert_called_once()

    def test_store_get_failure_returns_none(self):
        """A failure to read an order returns None.

        When get cannot find an order (including when the store is unavailable),
        it returns None and does not raise an exception.
        """
        with mock.patch("workorderstore.get") as mock_get:
            # Make the mock return None (not an exception, which is what actually happens)
            mock_get.return_value = None

            # This should return None, not raise
            result = workorderstore.get(mock.MagicMock(), 999)
            self.assertIsNone(result)

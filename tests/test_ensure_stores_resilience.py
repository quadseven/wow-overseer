"""Test that _ensure_stores continues after a failed index ensure on a
worldserver-owned table (T1368)."""

import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()


class EnsureStoresResilience(unittest.TestCase):
    """_ensure_stores must not stop when _ensure_dungeon_run_event_store fails."""

    def test_index_failure_logged_and_other_ensures_run(self):
        """When the index ensure raises, it is logged and later ensures still run."""
        log_lines = []

        def fake_log_exception(msg, *args):
            log_lines.append(msg % args)

        # Track which ensures were called
        ensures_called = []

        # Make _ensure_dungeon_run_event_store raise an error
        def failing_ensure():
            ensures_called.append("_ensure_dungeon_run_event_store")
            raise RuntimeError("ALTER TABLE failed: lock wait timeout")

        # Other ensures just record they were called
        def make_ensure(name):
            def ensure():
                ensures_called.append(name)

            return ensure

        # Patch all the ensure functions
        with (
            mock.patch.object(
                bridge, "_ensure_dungeon_run_event_store", failing_ensure
            ),
            mock.patch.object(
                bridge, "_ensure_thought_store", make_ensure("_ensure_thought_store")
            ),
            mock.patch.object(
                bridge, "_ensure_goal_store", make_ensure("_ensure_goal_store")
            ),
            mock.patch.object(
                bridge, "_ensure_sample_store", make_ensure("_ensure_sample_store")
            ),
            mock.patch.object(
                bridge, "_ensure_economy_store", make_ensure("_ensure_economy_store")
            ),
            mock.patch.object(
                bridge, "_ensure_trade_store", make_ensure("_ensure_trade_store")
            ),
            mock.patch.object(
                bridge, "_ensure_jev_store", make_ensure("_ensure_jev_store")
            ),
            mock.patch.object(
                bridge,
                "_ensure_guild_run_store",
                make_ensure("_ensure_guild_run_store"),
            ),
            mock.patch.object(
                bridge, "_ensure_standin_store", make_ensure("_ensure_standin_store")
            ),
            mock.patch.object(
                bridge, "_ensure_queue_store", make_ensure("_ensure_queue_store")
            ),
            mock.patch.object(
                bridge, "_ensure_memo_store", make_ensure("_ensure_memo_store")
            ),
            mock.patch.object(
                bridge, "_ensure_watch_store", make_ensure("_ensure_watch_store")
            ),
            mock.patch.object(
                bridge,
                "_ensure_quest_ledger_store",
                make_ensure("_ensure_quest_ledger_store"),
            ),
            mock.patch.object(
                bridge, "_ensure_now_store", make_ensure("_ensure_now_store")
            ),
            mock.patch.object(
                bridge, "_ensure_order_store", make_ensure("_ensure_order_store")
            ),
            mock.patch.object(bridge.log, "exception", fake_log_exception),
        ):
            # We need to call the actual _ensure_stores method, but it's an instance method
            # So we create a minimal bridge instance
            class MockBridge:
                _class_owing = None
                _vendor_movement = None
                _vendor_family_movement = None
                _bank_family_movement = None
                _family_lead_since = None
                _guild_run_recovered = types.SimpleNamespace(set=lambda: None)
                _guild_run_formed_at = None

                async def _ensure_stores(self):
                    # This is a copy of the actual _ensure_stores logic
                    # We'll test the real one by importing and running it
                    pass

            # Actually, let's test the real _ensure_stores by creating a proper mock
            import asyncio

            # Create a real bridge instance with mocked dependencies
            with (
                mock.patch.object(
                    bridge, "_guild_run_last_formed_at", return_value=None
                ),
                mock.patch.object(bridge, "_restore_bag_holds"),
                mock.patch.object(bridge.Bridge, "__init__", lambda self: None),
            ):
                b = bridge.Bridge.__new__(bridge.Bridge)
                b._class_owing = None
                b._vendor_movement = None
                b._vendor_family_movement = None
                b._bank_family_movement = None
                b._family_lead_since = None
                b._guild_run_recovered = types.SimpleNamespace(set=lambda: None)
                b._guild_run_formed_at = None

                # Run the actual _ensure_stores method
                asyncio.run(b._ensure_stores())

        # Verify the failing ensure was called
        self.assertIn("_ensure_dungeon_run_event_store", ensures_called)

        # Verify later ensures were still called
        self.assertIn("_ensure_goal_store", ensures_called)
        self.assertIn("_ensure_economy_store", ensures_called)
        self.assertIn("_ensure_now_store", ensures_called)
        self.assertIn("_ensure_order_store", ensures_called)

        # Verify the error was logged
        self.assertTrue(
            any("index ensure failed" in line for line in log_lines),
            f"Expected error log not found in {log_lines}",
        )

    def test_guild_run_recovered_set_after_index_failure(self):
        """_guild_run_recovered must be set even when index ensure fails."""
        guild_run_recovered_set = []

        def failing_ensure():
            raise RuntimeError("ALTER TABLE failed: privilege denied")

        def make_ensure(name):
            def ensure():
                pass

            return ensure

        with (
            mock.patch.object(
                bridge, "_ensure_dungeon_run_event_store", failing_ensure
            ),
            mock.patch.object(
                bridge, "_ensure_thought_store", make_ensure("_ensure_thought_store")
            ),
            mock.patch.object(
                bridge, "_ensure_goal_store", make_ensure("_ensure_goal_store")
            ),
            mock.patch.object(
                bridge, "_ensure_sample_store", make_ensure("_ensure_sample_store")
            ),
            mock.patch.object(
                bridge, "_ensure_economy_store", make_ensure("_ensure_economy_store")
            ),
            mock.patch.object(
                bridge, "_ensure_trade_store", make_ensure("_ensure_trade_store")
            ),
            mock.patch.object(
                bridge, "_ensure_jev_store", make_ensure("_ensure_jev_store")
            ),
            mock.patch.object(
                bridge,
                "_ensure_guild_run_store",
                make_ensure("_ensure_guild_run_store"),
            ),
            mock.patch.object(
                bridge, "_ensure_standin_store", make_ensure("_ensure_standin_store")
            ),
            mock.patch.object(
                bridge, "_ensure_queue_store", make_ensure("_ensure_queue_store")
            ),
            mock.patch.object(
                bridge, "_ensure_memo_store", make_ensure("_ensure_memo_store")
            ),
            mock.patch.object(
                bridge, "_ensure_watch_store", make_ensure("_ensure_watch_store")
            ),
            mock.patch.object(
                bridge,
                "_ensure_quest_ledger_store",
                make_ensure("_ensure_quest_ledger_store"),
            ),
            mock.patch.object(
                bridge, "_ensure_now_store", make_ensure("_ensure_now_store")
            ),
            mock.patch.object(
                bridge, "_ensure_order_store", make_ensure("_ensure_order_store")
            ),
            mock.patch.object(bridge, "_guild_run_last_formed_at", return_value=None),
            mock.patch.object(bridge, "_restore_bag_holds"),
            mock.patch.object(bridge.Bridge, "__init__", lambda self: None),
            mock.patch.object(bridge.log, "exception", lambda *a, **k: None),
        ):
            import asyncio

            b = bridge.Bridge.__new__(bridge.Bridge)
            b._class_owing = None
            b._vendor_movement = None
            b._vendor_family_movement = None
            b._bank_family_movement = None
            b._family_lead_since = None
            b._guild_run_recovered = types.SimpleNamespace(
                set=lambda: guild_run_recovered_set.append(True)
            )
            b._guild_run_formed_at = None

            asyncio.run(b._ensure_stores())

        # Verify _guild_run_recovered.set() was called
        self.assertTrue(
            guild_run_recovered_set,
            "_guild_run_recovered.set() was not called after index ensure failure",
        )


if __name__ == "__main__":
    unittest.main()

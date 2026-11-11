import unittest
from datetime import datetime, timedelta, timezone

from eventclips import clip_window, retain, trigger_kind


class TriggerKindTests(unittest.TestCase):
    def test_epic_family_guild_loot_triggers_but_rare_and_foreign_loot_do_not(self):
        epic = {
            "kind": "item_loot",
            "quality": 4,
            "family_member": True,
            "family_guild": True,
        }
        self.assertEqual("loot", trigger_kind(epic))
        self.assertIsNone(trigger_kind({**epic, "quality": 3}))
        self.assertIsNone(trigger_kind({**epic, "family_guild": False}))

    def test_only_first_family_boss_kill_and_first_clear_trigger(self):
        boss = {"kind": "boss_kill", "family_member": True, "first_kill": True}
        clear = {"kind": "clear", "family_member": True, "first_clear": True}
        self.assertEqual("boss_kill", trigger_kind(boss))
        self.assertEqual("clear", trigger_kind(clear))
        self.assertIsNone(trigger_kind({**boss, "first_kill": False}))
        self.assertIsNone(trigger_kind({**clear, "first_clear": False}))

    def test_only_family_level_sixty_is_a_level_trigger(self):
        level = {"kind": "level_up", "family_member": True, "level": 60}
        self.assertEqual("level_60", trigger_kind(level))
        self.assertIsNone(trigger_kind({**level, "level": 59}))
        self.assertIsNone(trigger_kind({**level, "family_member": False}))


class ClipWindowTests(unittest.TestCase):
    def setUp(self):
        self.event_at = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)

    def test_clip_starts_thirty_seconds_before_event_and_adds_tail(self):
        start, end = clip_window(self.event_at)
        self.assertEqual(self.event_at - timedelta(seconds=30), start)
        self.assertEqual(self.event_at + timedelta(seconds=15), end)

    def test_matching_equip_extends_clip_through_equip_and_tail(self):
        equipped = self.event_at + timedelta(seconds=42)
        _start, end = clip_window(self.event_at, equip_at=equipped)
        self.assertEqual(equipped + timedelta(seconds=15), end)

    def test_late_equip_uses_bounded_loot_fallback(self):
        late = self.event_at + timedelta(minutes=5, seconds=1)
        _start, end = clip_window(self.event_at, equip_at=late)
        self.assertEqual(self.event_at + timedelta(seconds=15), end)


class RetentionTests(unittest.TestCase):
    def test_retention_enforces_age_then_keeps_newest_up_to_count_cap(self):
        now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
        rows = [
            {"id": "old", "saved_at": now - timedelta(days=31)},
            {"id": "one", "saved_at": now - timedelta(days=3)},
            {"id": "two", "saved_at": now - timedelta(days=2)},
            {"id": "three", "saved_at": now - timedelta(days=1)},
        ]
        kept = retain(rows, now=now, max_age=timedelta(days=30), max_count=2)
        self.assertEqual(["three", "two"], [row["id"] for row in kept])


if __name__ == "__main__":
    unittest.main()

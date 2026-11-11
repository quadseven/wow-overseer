"""The clip ledger: which events earn a clip request, and what the row says.

Everything goes through clipledger's public functions over fake rows. No
database is involved; the adapter in map_server is tested in
test_clipledger_store.py.
"""

import pathlib
import sys
import unittest
from datetime import datetime, timedelta

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import clipledger  # noqa: E402

NOW = datetime(2026, 11, 9, 12, 0, 0)
GUILDS = ["Lantern Wardens"]


def streamed(name):
    return "wd" + name.lower()


def loot(event_id, quality=4, guild="Lantern Wardens", at=None, guid=900, who="Alder"):
    return {
        "id": event_id,
        "character_name": who,
        "kind": "item_loot",
        "subject_id": 1111,
        "subject_name": "Test Blade",
        "subject_quality": quality,
        "item_guid": guid,
        "guild": guild,
        "first_seen": at or NOW - timedelta(minutes=8),
    }


def plan(**kw):
    args = dict(
        loot_rows=[],
        event_rows=[],
        cleared_runs=[],
        family_guilds=GUILDS,
        roster=["Alder", "Birch"],
        now=NOW,
        existing_keys=(),
        path_of=streamed,
    )
    args.update(kw)
    return clipledger.plan_requests(**args)


class TriggerSelectionTests(unittest.TestCase):
    def test_epic_loot_by_a_family_guild_member_writes_one_pending_row(self):
        rows = plan(loot_rows=[loot(7, at=NOW - timedelta(minutes=8))])
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("loot", row["kind"])
        self.assertEqual("Alder", row["character"])
        self.assertEqual("pending", row["state"])
        self.assertEqual("wdalder", row["stream_path"])

    def test_rare_loot_and_foreign_guild_loot_write_nothing(self):
        self.assertEqual([], plan(loot_rows=[loot(7, quality=3)]))
        self.assertEqual([], plan(loot_rows=[loot(8, guild="Strangers")]))
        self.assertEqual([], plan(loot_rows=[loot(9, guild=None)]))


def equip(who="Alder", guid=900, at=None):
    return {
        "id": 70,
        "character_name": who,
        "kind": "item_equip",
        "subject_id": 1111,
        "item_guid": guid,
        "first_seen": at,
    }


def secs(n):
    return timedelta(seconds=n)


class WindowTimingTests(unittest.TestCase):
    def test_window_start_allows_for_the_flush_lag(self):
        at = NOW - timedelta(minutes=8)
        row = plan(loot_rows=[loot(7, at=at)])[0]
        self.assertEqual(at - secs(30) - clipledger.FLUSH_INTERVAL, row["window_start"])
        self.assertEqual(at, row["event_at"])

    def test_loot_with_a_timely_equip_ends_after_the_equip_plus_tail(self):
        at = NOW - timedelta(minutes=2)
        worn = at + secs(40)
        rows = plan(loot_rows=[loot(7, at=at), equip(at=worn)])
        self.assertEqual(1, len(rows))
        self.assertEqual(worn + secs(15), rows[0]["window_end"])

    def test_loot_waits_while_the_equip_wait_is_still_running(self):
        at = NOW - timedelta(minutes=2)
        self.assertEqual([], plan(loot_rows=[loot(7, at=at)]))

    def test_loot_whose_wait_ran_out_ends_after_the_tail(self):
        at = NOW - timedelta(minutes=6)
        late = at + timedelta(minutes=5, seconds=30)
        before = at - secs(10)
        rows = plan(loot_rows=[loot(7, at=at), equip(at=late), equip(at=before)])
        self.assertEqual(1, len(rows))
        self.assertEqual(at + secs(15), rows[0]["window_end"])

    def test_an_equip_of_another_item_or_character_does_not_extend(self):
        at = NOW - timedelta(minutes=2)
        others = [equip(guid=1, at=at + secs(20)), equip(who="Birch", at=at + secs(20))]
        self.assertEqual([], plan(loot_rows=[loot(7, at=at)] + others))


class OtherTriggerTests(unittest.TestCase):
    def kill(self, event_id, who, boss, at):
        return {
            "id": event_id,
            "character_name": who,
            "kind": "boss_kill",
            "subject_id": boss,
            "subject_name": "Boss %d" % boss,
            "first_seen": at,
        }

    def test_first_family_kill_of_a_boss_writes_a_row_ending_after_the_tail(self):
        at = NOW - timedelta(minutes=3)
        rows = plan(event_rows=[self.kill(1, "Alder", 5, at)])
        self.assertEqual(1, len(rows))
        self.assertEqual("boss_kill", rows[0]["kind"])
        self.assertEqual("boss_kill:5", rows[0]["event_key"])
        self.assertEqual("pending", rows[0]["state"])
        self.assertEqual(at + secs(15), rows[0]["window_end"])

    def test_a_repeat_kill_is_not_a_first(self):
        old = NOW - timedelta(days=2)
        recent = NOW - timedelta(minutes=3)
        rows = plan(
            event_rows=[
                self.kill(1, "Birch", 5, old),
                self.kill(2, "Alder", 5, recent),
            ]
        )
        self.assertEqual([], rows)

    def test_a_kill_by_a_stranger_is_not_a_family_first(self):
        at = NOW - timedelta(minutes=3)
        self.assertEqual([], plan(event_rows=[self.kill(1, "Stranger", 5, at)]))

    def test_level_sixty_writes_a_row_and_other_levels_write_nothing(self):
        at = NOW - timedelta(minutes=3)
        up = {"id": 3, "character_name": "Alder", "kind": "level_up", "level": 60}
        rows = plan(event_rows=[dict(up, first_seen=at)])
        self.assertEqual(["level_60"], [r["kind"] for r in rows])
        self.assertEqual("level_60:Alder", rows[0]["event_key"])
        self.assertEqual([], plan(event_rows=[dict(up, level=59, first_seen=at)]))
        self.assertEqual([], plan(event_rows=[dict(up, level=30, first_seen=at)]))

    def test_first_clear_of_a_dungeon_writes_a_row_for_the_leader(self):
        at = NOW - timedelta(minutes=3)
        clear = {"map_id": 36, "dungeon": "Test Mines", "leader": "Alder", "at": at}
        rows = plan(cleared_runs=[clear])
        self.assertEqual(["clear"], [r["kind"] for r in rows])
        self.assertEqual("clear:36", rows[0]["event_key"])
        self.assertEqual("Alder", rows[0]["character"])
        self.assertEqual(at + secs(15), rows[0]["window_end"])

    def test_only_the_earliest_clear_of_a_dungeon_is_a_first(self):
        old = {
            "map_id": 36,
            "dungeon": "T",
            "leader": "Birch",
            "at": NOW - timedelta(days=1),
        }
        new = {
            "map_id": 36,
            "dungeon": "T",
            "leader": "Alder",
            "at": NOW - timedelta(minutes=3),
        }
        self.assertEqual([], plan(cleared_runs=[new, old]))


class NoViewTests(unittest.TestCase):
    def test_a_character_with_no_streamed_view_gets_a_no_view_row(self):
        rows = plan(loot_rows=[loot(7)], path_of=lambda name: "")
        self.assertEqual(1, len(rows))
        self.assertEqual("no_view", rows[0]["state"])
        self.assertEqual("", rows[0]["stream_path"])

    def test_no_view_applies_to_every_trigger_kind(self):
        at = NOW - timedelta(minutes=3)
        up = {"id": 3, "character_name": "Alder", "kind": "level_up", "level": 60}
        rows = plan(event_rows=[dict(up, first_seen=at)], path_of=lambda name: "")
        self.assertEqual(["no_view"], [r["state"] for r in rows])


class RestartAndBackfillTests(unittest.TestCase):
    def test_a_second_scan_with_the_stored_keys_writes_nothing(self):
        args = dict(loot_rows=[loot(7), loot(8, guid=901)])
        first = plan(**args)
        self.assertEqual(["loot:7", "loot:8"], [r["event_key"] for r in first])
        again = plan(existing_keys={r["event_key"] for r in first}, **args)
        self.assertEqual([], again)

    def test_only_the_unseen_key_is_written_after_a_restart(self):
        rows = plan(loot_rows=[loot(7), loot(8, guid=901)], existing_keys=["loot:7"])
        self.assertEqual(["loot:8"], [r["event_key"] for r in rows])

    def test_event_keys_are_unique_within_one_scan(self):
        rows = plan(loot_rows=[loot(7), loot(7)])
        self.assertEqual(1, len(rows))

    def test_events_older_than_the_agent_buffer_are_not_backfilled(self):
        old = NOW - clipledger.AGENT_BUFFER - timedelta(minutes=1)
        self.assertEqual([], plan(loot_rows=[loot(7, at=old)]))
        up = {"id": 3, "character_name": "Alder", "kind": "level_up", "level": 60}
        self.assertEqual([], plan(event_rows=[dict(up, first_seen=old)]))

    def test_a_window_start_still_inside_the_buffer_is_written(self):
        at = NOW - clipledger.AGENT_BUFFER + timedelta(minutes=1)
        self.assertEqual(1, len(plan(loot_rows=[loot(7, at=at)])))


class RetentionTests(unittest.TestCase):
    def ledger_row(self, row_id, age, state="ready"):
        return {"id": row_id, "state": state, "created_at": NOW - age}

    def test_rows_past_the_age_cap_are_marked_expired(self):
        rows = [
            self.ledger_row(1, timedelta(days=31)),
            self.ledger_row(2, timedelta(days=29)),
        ]
        self.assertEqual([1], clipledger.expired_ids(rows, now=NOW))

    def test_the_count_cap_keeps_the_newest_and_expires_the_rest(self):
        rows = [self.ledger_row(i, timedelta(hours=i)) for i in range(1, 6)]
        self.assertEqual(
            [4, 5], sorted(clipledger.expired_ids(rows, now=NOW, max_count=3))
        )

    def test_only_ready_rows_count_and_expire(self):
        rows = [
            self.ledger_row(1, timedelta(days=40), state="pending"),
            self.ledger_row(2, timedelta(days=40), state="no_view"),
            self.ledger_row(3, timedelta(days=40), state="deleted"),
            self.ledger_row(4, timedelta(days=40), state="expired"),
            self.ledger_row(5, timedelta(days=40), state="ready"),
        ]
        self.assertEqual([5], clipledger.expired_ids(rows, now=NOW))

    def test_retention_returns_ids_only_and_leaves_the_rows_alone(self):
        rows = [self.ledger_row(1, timedelta(days=40))]
        clipledger.expired_ids(rows, now=NOW)
        self.assertEqual("ready", rows[0]["state"])


if __name__ == "__main__":
    unittest.main()

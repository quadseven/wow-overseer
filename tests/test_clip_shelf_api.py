"""GET /api/clips: the ready clips, newest first, for the shelf."""

import json
import pathlib
import sys
import unittest
from datetime import datetime

from _stub_modules import PYMYSQL, stub_modules
from sandbox_caps import LOCALHOST, NO_LOCALHOST

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import map_server
    from clip_fakes import FakeLedger, clip_row, serving


class ShelfPayload(unittest.TestCase):
    def test_loot_events_add_inventory_item_data_and_unambiguous_run_context(self):
        first = datetime(2026, 11, 12, 22, 27, 0)
        second = datetime(2026, 11, 13, 10, 57, 0)
        ledger_rows = [
            clip_row(
                id=1,
                event_key="loot:101",
                detail="Shadowblade",
                file_name="clip-1-loot.mp4",
                event_at=first,
            ),
            clip_row(
                id=2,
                event_key="loot:102",
                detail="Shadowblade",
                file_name="clip-2-loot.mp4",
                event_at=second,
            ),
            clip_row(
                id=3,
                state="failed",
                file_name=None,
                event_at=second,
            ),
            clip_row(
                id=4,
                state="no_view",
                file_name=None,
                event_at=second,
            ),
        ]
        events = [
            {
                "id": event_id,
                "kind": "item_loot",
                "character_name": "Testchar",
                "subject_id": 18821,
                "subject_name": "Shadowblade",
                "subject_quality": 4,
                "map": 230,
                "zone": 0,
                "source": "General Angerforge",
                "first_seen": at,
            }
            for event_id, at in ((101, first), (102, second))
        ]
        items = [{"entry": 18821, "name": "Shadowblade", "quality": 4, "displayid": 77}]
        runs = [
            {
                "id": 42,
                "map_id": 230,
                "started_at": datetime(2026, 11, 12, 22, 0, 0),
                "ended_at": datetime(2026, 11, 13, 11, 10, 0),
            }
        ]

        class Read:
            def rows(self, sql, params, *, what):
                if "FROM overseer_event" in sql:
                    self.event_params = params
                    return events
                if "FROM acore_world.item_template" in sql:
                    self.item_params = params
                    return items
                if "FROM overseer_dungeon_run" in sql:
                    self.run_params = params
                    return runs
                raise AssertionError("unexpected shelf query: %s" % what)

        read = Read()
        payload = map_server._clip_shelf_payload(
            read,
            [row for row in ledger_rows if row["state"] == "ready"],
            [row for row in ledger_rows if row["state"] != "ready"],
            icons={77: "inv_sword_04"},
            zones={10: "Duskwood"},
        )

        self.assertEqual(len(payload["clips"]), 2)
        self.assertEqual(
            [clip["item"]["entry"] for clip in payload["clips"]], [18821, 18821]
        )
        self.assertEqual([clip["item"]["quality"] for clip in payload["clips"]], [4, 4])
        self.assertEqual(
            [clip["item"]["icon"] for clip in payload["clips"]], ["inv_sword_04"] * 2
        )
        self.assertEqual(
            [clip["context"] for clip in payload["clips"]],
            ["Blackrock Depths run 42, General Angerforge"] * 2,
        )
        self.assertEqual(payload["missed"][0]["failed"], 1)
        self.assertEqual(payload["missed"][0]["no_view"], 1)
        self.assertEqual(read.event_params, (101, 102))
        self.assertEqual(read.item_params, (18821,))

    def test_open_world_loot_uses_the_event_zone(self):
        payload = map_server.clipledger.shelf(
            [
                clip_row(
                    id=1,
                    detail="Test Blade",
                    event_key="loot:101",
                    event_at=datetime(2026, 11, 13, 10, 57, 0),
                )
            ],
            event_rows=[
                {
                    "id": 101,
                    "kind": "item_loot",
                    "subject_id": 18821,
                    "subject_name": "Test Blade",
                    "subject_quality": 4,
                    "map": 0,
                    "zone": 10,
                    "source": "",
                    "first_seen": datetime(2026, 11, 13, 10, 57, 0),
                }
            ],
            item_rows=[],
            zones={10: "Duskwood"},
        )

        self.assertEqual(payload["clips"][0]["context"], "Duskwood")


@unittest.skipUnless(LOCALHOST, NO_LOCALHOST)
class ShelfList(unittest.TestCase):
    def ask(self, rows):
        with serving(FakeLedger(rows), "") as get:
            status, _headers, body = get("/api/clips")
        return status, json.loads(body)

    def test_ready_clips_newest_first_with_kind_character_time_and_url(self):
        status, payload = self.ask(
            [
                clip_row(
                    id=1,
                    detail="Test Blade",
                    file_name="clip-1-loot.mp4",
                    event_at=datetime(2026, 11, 9, 10, 0, 0),
                ),
                clip_row(
                    id=2,
                    kind="boss_kill",
                    character="Otherchar",
                    event_key="boss_kill:7",
                    detail="Test Warden",
                    file_name="clip-2-boss_kill.mp4",
                    event_at=datetime(2026, 11, 9, 11, 30, 0),
                ),
            ]
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            payload["clips"],
            [
                {
                    "id": 2,
                    "kind": "boss_kill",
                    "character": "Otherchar",
                    "view_owner": "Otherchar",
                    "subject": "Test Warden",
                    "at": "2026-11-09T11:30:00",
                    "url": "/clips/clip-2-boss_kill.mp4",
                    "poster": "/clips/clip-2-boss_kill-poster.jpg",
                },
                {
                    "id": 1,
                    "kind": "loot",
                    "character": "Testchar",
                    "view_owner": "Testchar",
                    "subject": "Test Blade",
                    "at": "2026-11-09T10:00:00",
                    "url": "/clips/clip-1-loot.mp4",
                    "poster": "/clips/clip-1-loot-poster.jpg",
                },
            ],
        )

    def test_only_ready_rows_are_listed(self):
        at = datetime(2026, 11, 9, 10, 0, 0)
        rows = [
            clip_row(id=i, state=state, file_name="clip-%d-loot.mp4" % i, event_at=at)
            for i, state in enumerate(
                [
                    "pending",
                    "cutting",
                    "ready",
                    "no_view",
                    "failed",
                    "expired",
                    "deleted",
                ],
                1,
            )
        ]
        _status, payload = self.ask(rows)
        self.assertEqual([c["id"] for c in payload["clips"]], [3])

    def test_no_clips_is_an_empty_list_with_a_line_to_say_so(self):
        status, payload = self.ask([])
        self.assertEqual(status, 200)
        self.assertEqual(payload["clips"], [])
        self.assertTrue(payload["empty"])

    def test_missed_moments_are_counted_per_day_and_never_listed(self):
        day = datetime(2026, 11, 9, 10, 0, 0)
        later = datetime(2026, 11, 10, 8, 0, 0)
        rows = [
            clip_row(id=1, file_name="clip-1-loot.mp4", event_at=day),
            clip_row(id=2, state="no_view", file_name=None, event_at=day),
            clip_row(id=3, state="failed", file_name=None, event_at=day),
            clip_row(id=4, state="no_view", file_name=None, event_at=later),
            clip_row(id=5, state="pending", file_name=None, event_at=later),
        ]
        _status, payload = self.ask(rows)
        self.assertEqual([c["id"] for c in payload["clips"]], [1])
        self.assertEqual(
            payload["missed"],
            [
                {"day": "2026-11-10", "no_view": 1, "failed": 0},
                {"day": "2026-11-09", "no_view": 1, "failed": 1},
            ],
        )

    def test_no_missed_moments_is_an_empty_list(self):
        _status, payload = self.ask([])
        self.assertEqual(payload["missed"], [])


if __name__ == "__main__":
    unittest.main()

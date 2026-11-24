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
    from clip_fakes import FakeLedger, clip_row, serving


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
                    "poster": "/clips/clip-2-boss_kill.jpg",
                },
                {
                    "id": 1,
                    "kind": "loot",
                    "character": "Testchar",
                    "view_owner": "Testchar",
                    "subject": "Test Blade",
                    "at": "2026-11-09T10:00:00",
                    "url": "/clips/clip-1-loot.mp4",
                    "poster": "/clips/clip-1-loot.jpg",
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

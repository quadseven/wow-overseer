"""Clip links on Chronicle loot stories and run timeline entries.

A ready ledger row gives the entry a link. A no_view row gives it the line
that no live view was up. A failed row gives the line that no clip was saved,
with its reason. No row, or any other state, gives it nothing.
"""

import json
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import clipledger
    import lootstory
    import runreport
    import runtimeline

T0 = datetime(2026, 9, 22, 12, 0, 0)
ZONES = {12: "Elwynn Forest"}


def loot_rows(loot_id=41):
    base = {
        "character_name": "Testchar",
        "subject_id": 647,
        "subject_name": "Testblade",
        "subject_quality": 4,
        "map": 0,
        "zone": 12,
        "item_guid": 9001,
        "counterpart": "",
        "via": "loot",
        "source": "a test mob",
        "guild": "Cave",
    }
    return [
        dict(base, id=loot_id, kind="item_loot", first_seen=T0, last_seen=T0),
        dict(
            base,
            id=loot_id + 1,
            kind="item_equip",
            first_seen=T0 + timedelta(minutes=2),
            last_seen=T0 + timedelta(minutes=2),
        ),
    ]


def ledger(**over):
    row = {
        "event_key": "loot:41",
        "kind": "loot",
        "state": "ready",
        "file_name": "clip-9-loot.mp4",
    }
    row.update(over)
    return {row["event_key"]: row}


class LootStories(unittest.TestCase):
    def story(self, clips):
        return lootstory.build_loot(loot_rows(), ZONES, clips=clips)["stories"][0]

    def test_a_ready_clip_is_linked_by_the_loot_events_key(self):
        story = self.story(ledger())
        self.assertEqual(
            story["clip"], {"url": "/clips/clip-9-loot.mp4", "kind": "loot"}
        )
        self.assertNotIn("clip_note", story)

    def test_a_no_view_row_says_no_live_view_was_up(self):
        story = self.story(ledger(state="no_view", file_name=None))
        self.assertEqual(story["clip_note"], clipledger.NO_VIEW_LINE)
        self.assertIn("live view was up", story["clip_note"])
        self.assertNotIn("clip", story)

    def test_no_row_says_nothing_about_clips(self):
        for clips in (None, {}):
            story = self.story(clips)
            self.assertNotIn("clip", story)
            self.assertNotIn("clip_note", story)

    def test_a_row_for_another_event_does_not_attach(self):
        story = self.story(ledger(event_key="loot:999"))
        self.assertNotIn("clip", story)

    def test_a_timed_out_row_gives_its_reason_not_the_no_view_line(self):
        story = self.story(
            ledger(
                state="failed",
                file_name=None,
                detail="view: Testchar (leader); " + clipledger.PENDING_FAILED_DETAIL,
            )
        )
        self.assertEqual(
            story["clip_note"],
            "No clip was saved: %s." % clipledger.PENDING_FAILED_DETAIL,
        )
        self.assertNotIn("live view was up", story["clip_note"])

    def test_a_late_row_gives_its_reason(self):
        story = self.story(
            ledger(state="failed", file_name=None, detail=clipledger.LATE_DETAIL)
        )
        self.assertEqual(
            story["clip_note"], "No clip was saved: %s." % clipledger.LATE_DETAIL
        )

    def test_a_cutter_failure_gives_its_reason_in_the_same_form(self):
        story = self.story(
            ledger(
                state="failed", file_name=None, detail=clipledger.CUTTING_FAILED_DETAIL
            )
        )
        self.assertEqual(
            story["clip_note"],
            "No clip was saved: %s." % clipledger.CUTTING_FAILED_DETAIL,
        )

    def test_a_failed_row_with_only_view_text_still_says_no_clip(self):
        story = self.story(
            ledger(state="failed", file_name=None, detail="view: Testchar (leader)")
        )
        self.assertEqual(story["clip_note"], "No clip was saved.")

    def test_a_row_that_is_not_ready_failed_or_no_view_says_nothing(self):
        for state in ("pending", "cutting", "expired", "deleted"):
            story = self.story(ledger(state=state))
            self.assertNotIn("clip", story, state)
            self.assertNotIn("clip_note", story, state)


def a_cleared_run(run_id=12, map_id=389, ended_age=600):
    rows = [
        {
            "id": i,
            "family": "Zug",
            "leader_name": "Zug",
            "character_name": "",
            "run_id": run_id,
            "campaign_id": 8,
            "run_number": 1,
            "portal": "ragefire",
            "phase": phase,
            "kind": kind,
            "detail": detail,
            "age_seconds": age,
        }
        for i, (kind, detail, phase, age) in enumerate(
            [
                (
                    "phase",
                    "IDLE -> RESET (ragefire, run 1 of campaign 8)",
                    "RESET",
                    ended_age + 900,
                ),
                ("ended", "complete: the last boss fell", "CLEARING", ended_age),
                ("phase", "CLEARING -> IDLE", "IDLE", ended_age - 5),
            ],
            1,
        )
    ]
    report = runreport.build(
        {
            "id": run_id,
            "leader_name": "Zug",
            "members": "Zug,Oz",
            "map_id": map_id,
            "run_number": 1,
            "state": "ended",
            "outcome": "complete",
            "ended_reason": "",
            "duration_seconds": 900,
        },
        [],
        [],
        "Ragefire Chasm",
    )
    return rows, {run_id: report}


NOW = datetime(2026, 9, 23, 20, 0, 0, tzinfo=timezone.utc)


def clear_row(**over):
    row = {
        "event_key": "clear:389",
        "kind": "clear",
        "character": "Zug",
        "state": "ready",
        "file_name": "clip-5-clear.mp4",
        "age_seconds": 620,
    }
    row.update(over)
    return row


class TimelineEntries(unittest.TestCase):
    def card(self, clips, **run):
        rows, reports = a_cleared_run(**run)
        built = runtimeline.build_run_timeline(
            rows, {"Zug": ["Zug", "Oz"]}, now=NOW, reports=reports, clips=clips
        )
        return built["families"][0]["runs"][0]

    def test_a_ready_clear_clip_links_the_run_that_cleared(self):
        card = self.card([clear_row()])
        self.assertEqual(
            card["clip"], {"url": "/clips/clip-5-clear.mp4", "kind": "clear"}
        )

    def test_a_no_view_clear_says_no_live_view_was_up(self):
        card = self.card([clear_row(state="no_view", file_name=None)])
        self.assertEqual(card["clip_note"], clipledger.NO_VIEW_LINE)
        self.assertNotIn("clip", card)

    def test_a_failed_clear_gives_its_reason(self):
        card = self.card(
            [
                clear_row(
                    state="failed",
                    file_name=None,
                    detail=clipledger.PENDING_FAILED_DETAIL,
                )
            ]
        )
        self.assertEqual(
            card["clip_note"],
            "No clip was saved: %s." % clipledger.PENDING_FAILED_DETAIL,
        )

    def test_no_row_says_nothing(self):
        for clips in (None, []):
            card = self.card(clips)
            self.assertNotIn("clip", card)
            self.assertNotIn("clip_note", card)

    def test_a_clear_of_the_same_dungeon_at_another_time_is_not_this_run(self):
        card = self.card([clear_row(age_seconds=90000)])
        self.assertNotIn("clip", card)

    def test_a_clear_of_another_dungeon_is_not_this_run(self):
        card = self.card([clear_row(event_key="clear:33")])
        self.assertNotIn("clip", card)

    def test_a_run_that_did_not_clear_carries_no_link(self):
        rows, reports = a_cleared_run()
        rows[1]["detail"] = "wipe: everyone died"
        reports[12]["outcome"] = "wipe"
        built = runtimeline.build_run_timeline(
            rows, {"Zug": ["Zug"]}, now=NOW, reports=reports, clips=[clear_row()]
        )
        self.assertNotIn("clip", built["families"][0]["runs"][0])

    def test_the_payload_is_json(self):
        json.dumps(self.card([clear_row()]))


if __name__ == "__main__":
    unittest.main()

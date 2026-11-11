"""Clip links on the /api/v2/chronicle feed: first kills and level 60.

A first kill is picked by the one picker the clip ledger uses, and its link
is the ledger row under the same boss_key. A level item at 60 carries one
entry per character with a row under level_key. Rows are plain dicts and the
route runs over the in-memory realm reader, so no database is involved.
"""

import pathlib
import sys
import types
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import clipledger
    import guildrun
    import realmread
    from apiv2 import chronicle
    from test_apiv2_guilds import NOW, Ctx

DAY = 86400
KIN = [("Cave", "Grug", ["Grug", "Og"]), ("Bonkers", "Zug", ["Zug", "Oz"])]


def kill(who, at, boss=5, name="Test Warden"):
    return {
        "character_name": who,
        "kind": "boss_kill",
        "subject_id": boss,
        "subject_name": name,
        "first_seen": at,
    }


def ledger(key, **over):
    row = {
        "event_key": key,
        "kind": "boss_kill",
        "character": "Grug",
        "state": "ready",
        "file_name": "clip-3-boss_kill.mp4",
        "detail": "",
    }
    row.update(over)
    return {key: row}


def items(kills, clips=None, now=NOW):
    return chronicle.first_kill_items(kills, KIN, clips or {}, now)


class FirstKillPick(unittest.TestCase):
    def test_one_item_per_family_per_boss_from_the_ledgers_picker(self):
        out = items(
            [
                kill("Og", NOW - 200),
                kill("Grug", NOW - 100),
                kill("Zug", NOW - 50),
                kill("Grug", NOW - 10, boss=6, name="Test Brute"),
            ]
        )
        got = sorted((i["guild"], i["who"][0], i["at"]) for i in out)
        self.assertEqual(
            got,
            [
                ("Bonkers", "Zug", NOW - 50),
                ("Cave", "Grug", NOW - 10),
                ("Cave", "Og", NOW - 200),
            ],
        )
        first = [i for i in out if i["who"] == ["Og"]][0]
        self.assertEqual(first["kind"], "first_kill")
        self.assertEqual(
            first["text"], "Og landed the family's first kill of Test Warden."
        )

    def test_it_is_the_ledgers_own_selection(self):
        rows = [kill("Og", NOW - 200), kill("Grug", NOW - 100)]
        (pick,) = clipledger.first_kills(rows, ["Grug", "Og"], lambda n: "")
        (item,) = [i for i in items(rows) if i["guild"] == "Cave"]
        self.assertEqual(item["who"], [pick["character_name"]])

    def test_a_first_older_than_the_feed_window_is_not_promoted_or_listed(self):
        old = NOW - (chronicle.DAYS + 1) * DAY
        self.assertEqual(items([kill("Og", old), kill("Grug", NOW - 100)]), [])


class FirstKillLink(unittest.TestCase):
    def one(self, clips):
        (item,) = items([kill("Grug", NOW - 100)], clips)
        return item

    def test_a_ready_row_gives_a_clip(self):
        item = self.one(ledger(clipledger.boss_key(5, "Grug")))
        self.assertEqual(
            item["clip"], {"url": "/clips/clip-3-boss_kill.mp4", "kind": "boss_kill"}
        )
        self.assertNotIn("clip_note", item)

    def test_no_view_and_failed_rows_give_a_note(self):
        for state in ("no_view", "failed"):
            item = self.one(
                ledger(clipledger.boss_key(5, "Grug"), state=state, file_name=None)
            )
            self.assertIn("clip_note", item, state)
            self.assertNotIn("clip", item, state)

    def test_no_row_and_in_flight_rows_give_neither(self):
        cases = [{}] + [
            ledger(clipledger.boss_key(5, "Grug"), state=s, file_name=None)
            for s in ("pending", "cutting")
        ]
        for clips in cases:
            item = self.one(clips)
            self.assertNotIn("clip", item)
            self.assertNotIn("clip_note", item)

    def tie(self, clips):
        # Two members on one first_seen: the feed picks Grug (roster order),
        # the ledger may have credited the streamed member, Og.
        (item,) = items([kill("Og", NOW - 100), kill("Grug", NOW - 100)], clips)
        self.assertEqual(item["who"], ["Grug"])
        return item

    def test_a_tie_links_the_row_whichever_member_the_ledger_credited(self):
        item = self.tie(ledger(clipledger.boss_key(5, "Grug"), character="Og"))
        self.assertEqual(item["clip"]["url"], "/clips/clip-3-boss_kill.mp4")

    def test_a_tie_with_a_failed_row_gives_the_note(self):
        item = self.tie(
            ledger(
                clipledger.boss_key(5, "Grug"),
                character="Og",
                state="failed",
                file_name=None,
            )
        )
        self.assertIn("clip_note", item)
        self.assertNotIn("clip", item)


class FirstKillPerFamilyLink(unittest.TestCase):
    def test_each_family_item_links_its_own_row_and_never_the_others(self):
        kills = [kill("Grug", NOW - 100), kill("Zug", NOW - 50)]
        clips = {}
        clips.update(ledger(clipledger.boss_key(5, "Grug"), character="Grug"))
        zug = ledger(
            clipledger.boss_key(5, "Zug"),
            character="Zug",
            file_name="clip-4-boss_kill.mp4",
        )
        by_guild = {i["guild"]: i for i in items(kills, {**clips, **zug})}
        self.assertEqual(by_guild["Cave"]["clip"]["url"], "/clips/clip-3-boss_kill.mp4")
        self.assertEqual(
            by_guild["Bonkers"]["clip"]["url"], "/clips/clip-4-boss_kill.mp4"
        )

    def test_a_row_under_the_old_realm_wide_key_is_never_matched(self):
        old = ledger("boss_kill:5", character="Grug")
        (item,) = items([kill("Grug", NOW - 100)], old)
        self.assertNotIn("clip", item)
        self.assertNotIn("clip_note", item)


class LevelSixty(unittest.TestCase):
    def levels(self, rows, clips=None):
        return chronicle.level_items(rows, {23: "Cave"}, clips)

    def test_sixty_with_a_row_carries_one_entry_for_that_character(self):
        rows = [
            {"name": "Bonk", "level": 60, "guild_id": 23, "at": NOW},
            {"name": "Durg", "level": 59, "guild_id": 23, "at": NOW - 60},
        ]
        clips = ledger(clipledger.level_key("Bonk"), kind="level_60", character="Bonk")
        (item,) = self.levels(rows, clips)
        self.assertEqual(
            item["clips"],
            [
                {
                    "who": "Bonk",
                    "clip": {
                        "url": "/clips/clip-3-boss_kill.mp4",
                        "kind": "level_60",
                    },
                }
            ],
        )

    def test_a_no_view_row_gives_that_character_a_note(self):
        rows = [{"name": "Bonk", "level": 60, "guild_id": 23, "at": NOW}]
        clips = ledger(
            clipledger.level_key("Bonk"),
            kind="level_60",
            character="Bonk",
            state="no_view",
            file_name=None,
        )
        (item,) = self.levels(rows, clips)
        (entry,) = item["clips"]
        self.assertEqual(entry["who"], "Bonk")
        self.assertEqual(entry["clip_note"], clipledger.NO_VIEW_LINE)

    def test_sixty_without_a_row_has_no_clips_key(self):
        rows = [{"name": "Bonk", "level": 60, "guild_id": 23, "at": NOW}]
        for clips in (None, {}):
            (item,) = self.levels(rows, clips)
            self.assertNotIn("clips", item)

    def test_fifty_nine_never_carries_clips(self):
        rows = [{"name": "Bonk", "level": 59, "guild_id": 23, "at": NOW}]
        clips = ledger(clipledger.level_key("Bonk"), kind="level_60", character="Bonk")
        (item,) = self.levels(rows, clips)
        self.assertNotIn("clips", item)


class Route(unittest.TestCase):
    class Server:
        achievements = types.SimpleNamespace(MAP_NAMES={36: "The Deadmines"})

    def answers(self, ledger_rows):
        return {
            chronicle._GUILDS_SQL: lambda args: [
                {"guildid": {"Cave": 23, "Bonkers": 24}[a], "name": a}
                for a in args
                if a in ("Cave", "Bonkers")
            ],
            chronicle._LEVELS_SQL: [
                {"name": "Bonk", "level": 60, "guild_id": 23, "at": NOW}
            ],
            guildrun._RUN_SQL: [],
            chronicle._MEMBERS_SQL: [],
            chronicle._DEATHS_SQL: [],
            chronicle._KILLS_SQL: [dict(kill("Grug", NOW - 100), now=NOW)],
            chronicle._CLIPS_SQL: ledger_rows,
        }

    def ask(self, ledger_rows, query=None):
        ctx = Ctx(self.answers(ledger_rows), self.Server)
        code, body = chronicle.chronicle(query or {"guild": ["Cave"]}, ctx)
        self.assertEqual(code, 200)
        return body["items"], ctx

    def test_the_payload_carries_the_first_kill_with_its_clip(self):
        rows = list(ledger(clipledger.boss_key(5, "Grug")).values())
        found, _ctx = self.ask(rows)
        (first,) = [i for i in found if i["kind"] == "first_kill"]
        self.assertEqual(first["guild"], "Cave")
        self.assertEqual(first["clip"]["kind"], "boss_kill")

    def test_a_realm_without_the_ledger_renders_both_items_unchanged(self):
        found, _ctx = self.ask(realmread.MISSING_TABLE)
        (first,) = [i for i in found if i["kind"] == "first_kill"]
        (level,) = [i for i in found if i["kind"] == "level"]
        for item in (first, level):
            self.assertNotIn("clip", item)
            self.assertNotIn("clip_note", item)
            self.assertNotIn("clips", item)

    def test_the_ledger_is_asked_for_the_keys_of_the_items_shown(self):
        _found, ctx = self.ask([])
        (params,) = [p for sql, p in ctx.read.asked if "overseer_clip" in sql]
        self.assertEqual(
            sorted(params),
            sorted([clipledger.boss_key(5, "Grug"), clipledger.level_key("Bonk")]),
        )

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
        runs=(),
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


def only(*names):
    """A path_of that streams just the named characters."""
    return lambda name: "wd" + name.lower() if name in names else ""


FAMILY = ["Alder", "Birch", "Cedar", "Dogwood"]
MAP = 33


def run(leader="Alder", map_id=MAP, ended=None, run_id=1, started_min=40):
    """A dungeon run row; ended=None is a run still in progress."""
    return {
        "id": run_id,
        "leader_name": leader,
        "map_id": map_id,
        "state": "ended" if ended else "active",
        "started_at": NOW - timedelta(minutes=started_min),
        "ended_at": ended,
    }


def seen_in(who, map_id=MAP, minutes=20, event_id=500):
    """Something the character did inside the instance: presence in the run."""
    return {
        "id": event_id,
        "character_name": who,
        "kind": "item_equip",
        "item_guid": 1,
        "map": map_id,
        "first_seen": NOW - timedelta(minutes=minutes),
    }


def in_dungeon(row, map_id=MAP):
    return dict(row, map=map_id)


class FamilyViewTests(unittest.TestCase):
    """Fixed decision 1: own view, then the run leader, then a party member."""

    def family_plan(self, path_of, runs, extra=(), who="Cedar"):
        return plan(
            loot_rows=[in_dungeon(loot(7, who=who))] + list(extra),
            runs=runs,
            roster=FAMILY,
            path_of=path_of,
        )

    def test_unstreamed_winner_in_a_run_led_by_a_streamed_member_uses_the_leader(
        self,
    ):
        (row,) = self.family_plan(only("Alder"), [run()])
        self.assertEqual("pending", row["state"])
        self.assertEqual("Cedar", row["character"])
        self.assertEqual("wdalder", row["stream_path"])
        self.assertIn("view: Alder (leader)", row["detail"])
        self.assertIn("Test Blade", row["detail"])

    def test_leader_not_streamed_falls_to_a_streamed_party_member_in_roster_order(
        self,
    ):
        present = [seen_in("Dogwood", event_id=501), seen_in("Birch", event_id=502)]
        (row,) = self.family_plan(only("Birch", "Dogwood"), [run()], extra=present)
        self.assertEqual("pending", row["state"])
        self.assertEqual("wdbirch", row["stream_path"])
        self.assertIn("view: Birch (party member)", row["detail"])

    def test_a_streamed_subject_keeps_its_own_path_and_detail(self):
        (row,) = self.family_plan(only("Alder", "Cedar"), [run()])
        self.assertEqual("wdcedar", row["stream_path"])
        self.assertEqual("Test Blade", row["detail"])

    def test_a_streamed_subject_outside_any_run_keeps_its_own_path_and_detail(self):
        (row,) = self.family_plan(only("Cedar"), [])
        self.assertEqual("wdcedar", row["stream_path"])
        self.assertEqual("Test Blade", row["detail"])

    def test_no_streamed_family_member_in_the_run_is_no_view_with_that_reason(self):
        (row,) = self.family_plan(only("Dogwood"), [run()], extra=[seen_in("Birch")])
        self.assertEqual("no_view", row["state"])
        self.assertEqual("", row["stream_path"])
        self.assertIn("no streamed family member in the run", row["detail"])

    def test_no_run_is_no_view_with_the_not_in_a_run_reason(self):
        (row,) = self.family_plan(only("Alder"), [])
        self.assertEqual("no_view", row["state"])
        self.assertIn("subject not streamed and not in a run", row["detail"])

    def test_a_run_on_another_map_or_after_the_event_does_not_count(self):
        (row,) = self.family_plan(only("Alder"), [run(map_id=99)])
        self.assertEqual("no_view", row["state"])
        later = run()
        later["started_at"] = NOW
        (row,) = self.family_plan(only("Alder"), [later])
        self.assertEqual("no_view", row["state"])

    def test_a_streamed_family_member_who_was_not_in_the_run_is_not_a_view(self):
        (row,) = self.family_plan(
            only("Birch"), [run()], extra=[seen_in("Birch", map_id=99)]
        )
        self.assertEqual("no_view", row["state"])

    def test_a_run_still_in_progress_supplies_the_leader_view(self):
        still_open = run(ended=None)
        self.assertIsNone(still_open["ended_at"])
        (row,) = self.family_plan(only("Alder"), [still_open])
        self.assertEqual("wdalder", row["stream_path"])
        self.assertIn("view: Alder (leader)", row["detail"])

    def test_a_run_still_in_progress_supplies_a_party_member_view(self):
        (row,) = self.family_plan(
            only("Birch"), [run(ended=None)], extra=[seen_in("Birch")]
        )
        self.assertEqual("wdbirch", row["stream_path"])
        self.assertIn("view: Birch (party member)", row["detail"])

    def test_an_ended_run_still_resolves(self):
        ended = run(ended=NOW - timedelta(minutes=2))
        (row,) = self.family_plan(only("Alder"), [ended])
        self.assertIn("view: Alder (leader)", row["detail"])

    def test_the_ledger_character_stays_the_subject_for_a_boss_kill(self):
        kill = {
            "id": 1,
            "character_name": "Cedar",
            "kind": "boss_kill",
            "subject_id": 5,
            "subject_name": "Boss 5",
            "map": MAP,
            "first_seen": NOW - timedelta(minutes=3),
        }
        (row,) = plan(
            event_rows=[kill], runs=[run()], roster=FAMILY, path_of=only("Alder")
        )
        self.assertEqual("Cedar", row["character"])
        self.assertEqual("wdalder", row["stream_path"])
        self.assertIn("view: Alder (leader)", row["detail"])

    def test_a_clear_falls_to_a_streamed_party_member_when_the_leader_is_not(self):
        clear = {
            "map_id": MAP,
            "dungeon": "Test Mines",
            "leader": "Alder",
            "members": ["Alder", "Birch"],
            "at": NOW - timedelta(minutes=3),
        }
        (row,) = plan(cleared_runs=[clear], roster=FAMILY, path_of=only("Birch"))
        self.assertEqual("Alder", row["character"])
        self.assertEqual("wdbirch", row["stream_path"])
        self.assertIn("view: Birch (party member)", row["detail"])
        self.assertIn("Test Mines", row["detail"])

    def test_a_clear_with_no_streamed_member_is_no_view_with_the_run_reason(self):
        clear = {
            "map_id": MAP,
            "dungeon": "T",
            "leader": "Alder",
            "at": NOW - timedelta(minutes=3),
        }
        (row,) = plan(cleared_runs=[clear], roster=FAMILY, path_of=only())
        self.assertEqual("no_view", row["state"])
        self.assertIn("no streamed family member in the run", row["detail"])


TWO_FAMILIES = {"first": ["Alder", "Birch"], "second": ["Cedar", "Dogwood"]}


class TwoFamiliesOneDungeonTests(unittest.TestCase):
    """Two families inside one dungeon at once: each event stays in its own."""

    def two_runs(self):
        # The first family's run started earlier, so a map-and-time match
        # alone would pick it for everyone.
        return [
            run(leader="Alder", run_id=1, started_min=50),
            run(leader="Cedar", run_id=2, started_min=40),
        ]

    def loot_plan(
        self, path_of, extra=(), runs=None, families=TWO_FAMILIES, who="Dogwood"
    ):
        return plan(
            loot_rows=[in_dungeon(loot(7, who=who))] + list(extra),
            runs=self.two_runs() if runs is None else runs,
            roster=FAMILY,
            families=families,
            path_of=path_of,
        )

    def test_a_second_family_member_takes_their_own_leaders_view(self):
        (row,) = self.loot_plan(only("Alder", "Cedar"))
        self.assertEqual("wdcedar", row["stream_path"])
        self.assertIn("view: Cedar (leader)", row["detail"])

    def test_a_second_family_party_member_comes_from_that_family_only(self):
        extra = [seen_in("Birch", event_id=501), seen_in("Cedar", event_id=502)]
        (row,) = self.loot_plan(only("Birch", "Alder"), extra=extra)
        self.assertEqual("no_view", row["state"])
        self.assertIn("no streamed family member in the run", row["detail"])
        self.assertNotIn("Birch", row["detail"])

    def test_the_party_member_is_the_one_from_the_subjects_family(self):
        runs = self.two_runs()
        extra = [seen_in("Birch", event_id=501), seen_in("Dogwood", event_id=502)]
        (row,) = self.loot_plan(
            only("Birch", "Dogwood"), extra=extra, runs=runs, who="Cedar"
        )
        self.assertEqual("wddogwood", row["stream_path"])
        self.assertIn("view: Dogwood (party member)", row["detail"])

    def test_presence_does_not_cross_families(self):
        extra = [seen_in("Cedar", event_id=501)]
        (row,) = self.loot_plan(
            only("Cedar"), extra=extra, runs=[run(leader="Alder")], who="Birch"
        )
        self.assertEqual("no_view", row["state"])
        self.assertEqual("", row["stream_path"])

    def test_an_unknown_family_with_one_matching_run_keeps_the_old_behavior(self):
        (row,) = self.loot_plan(
            only("Alder"), runs=[run(leader="Alder")], families={}, who="Cedar"
        )
        self.assertEqual("wdalder", row["stream_path"])

    def test_an_unknown_family_with_two_matching_runs_is_ambiguous(self):
        (row,) = self.loot_plan(only("Alder", "Cedar"), families={}, who="Dogwood")
        self.assertEqual("no_view", row["state"])
        self.assertEqual("", row["stream_path"])
        self.assertIn("run ambiguous", row["detail"])

    def test_a_clear_does_not_borrow_a_view_from_the_other_family(self):
        clear = {
            "map_id": MAP,
            "dungeon": "T",
            "leader": "Alder",
            "members": ["Alder", "Birch", "Cedar"],
            "at": NOW - timedelta(minutes=3),
        }
        (row,) = plan(
            cleared_runs=[clear],
            roster=FAMILY,
            families=TWO_FAMILIES,
            path_of=only("Cedar"),
        )
        self.assertEqual("no_view", row["state"])
        self.assertIn("no streamed family member in the run", row["detail"])


class TiedFirstKillTests(unittest.TestCase):
    def kill(self, event_id, who, at):
        return {
            "id": event_id,
            "character_name": who,
            "kind": "boss_kill",
            "subject_id": 5,
            "subject_name": "Boss 5",
            "first_seen": at,
        }

    def tie(self, order):
        at = NOW - timedelta(minutes=3)
        return [self.kill(i, who, at) for i, who in enumerate(order, 1)]

    def test_a_tie_picks_the_streamed_member_whatever_the_row_order(self):
        for order in (["Alder", "Birch", "Cedar"], ["Cedar", "Birch", "Alder"]):
            (row,) = plan(
                event_rows=self.tie(order), roster=FAMILY, path_of=only("Birch")
            )
            self.assertEqual("Birch", row["character"], order)
            self.assertEqual("wdbirch", row["stream_path"])

    def test_a_tie_among_streamed_members_picks_roster_order(self):
        for order in (["Cedar", "Birch"], ["Birch", "Cedar"]):
            (row,) = plan(
                event_rows=self.tie(order),
                roster=FAMILY,
                path_of=only("Birch", "Cedar"),
            )
            self.assertEqual("Birch", row["character"], order)

    def test_a_tie_with_no_streamed_member_still_picks_by_roster_order(self):
        (row,) = plan(
            event_rows=self.tie(["Cedar", "Birch"]), roster=FAMILY, path_of=only()
        )
        self.assertEqual("Birch", row["character"])
        self.assertEqual("no_view", row["state"])

    def test_an_earlier_row_beats_a_streamed_later_one(self):
        early = self.kill(1, "Alder", NOW - timedelta(minutes=4))
        late = self.kill(2, "Birch", NOW - timedelta(minutes=3))
        (row,) = plan(event_rows=[late, early], roster=FAMILY, path_of=only("Birch"))
        self.assertEqual("Alder", row["character"])


class ShelfViewOwnerTests(unittest.TestCase):
    def shelf_of(self, **over):
        row = {
            "id": 1,
            "kind": "loot",
            "character": "Cedar",
            "event_at": NOW,
            "state": "ready",
            "file_name": "clip-1-loot.mp4",
            "stream_path": "wdalder",
            "detail": "",
        }
        row.update(over)
        (clip,) = clipledger.shelf([row])["clips"]
        return clip

    def test_a_clip_from_the_leaders_view_names_the_leader(self):
        clip = self.shelf_of(detail="Test Blade; view: Alder (leader)")
        self.assertEqual("Alder", clip["view_owner"])
        self.assertEqual("Cedar", clip["character"])

    def test_a_clip_from_a_party_members_view_names_that_member(self):
        clip = self.shelf_of(detail="view: Birch (party member)")
        self.assertEqual("Birch", clip["view_owner"])

    def test_a_trailing_note_after_the_view_does_not_hide_the_owner(self):
        clip = self.shelf_of(detail="Test Blade; view: Alder (leader) | dark 1 of 5")
        self.assertEqual("Alder", clip["view_owner"])

    def test_a_clip_from_the_subjects_own_view_names_the_subject(self):
        clip = self.shelf_of(detail="Test Blade")
        self.assertEqual("Cedar", clip["view_owner"])


class EventKeyTests(unittest.TestCase):
    def test_the_key_functions_spell_what_the_planner_writes(self):
        at = NOW - timedelta(minutes=3)
        kill = {
            "id": 1,
            "character_name": "Alder",
            "kind": "boss_kill",
            "subject_id": 5,
            "subject_name": "Boss 5",
            "first_seen": at,
        }
        sixty = {
            "id": 2,
            "character_name": "Alder",
            "kind": "level_up",
            "level": 60,
            "first_seen": at,
        }
        keys = [r["event_key"] for r in plan(event_rows=[kill, sixty])]
        self.assertEqual(
            sorted([clipledger.boss_key(5), clipledger.level_key("Alder")]),
            sorted(keys),
        )
        self.assertEqual("boss_kill:5", clipledger.boss_key(5))
        self.assertEqual("level_60:Alder", clipledger.level_key("Alder"))


class ShelfSubjectTests(unittest.TestCase):
    def subject_of(self, **over):
        row = {
            "id": 1,
            "kind": "boss_kill",
            "character": "Cedar",
            "event_at": NOW,
            "state": "ready",
            "file_name": "clip-1-boss_kill.mp4",
            "detail": "Test Warden",
        }
        row.update(over)
        (clip,) = clipledger.shelf([row])["clips"]
        return clip["subject"]

    def test_a_boss_first_kill_names_the_boss(self):
        self.assertEqual("Test Warden", self.subject_of())

    def test_a_loot_clip_names_the_item(self):
        self.assertEqual(
            "Test Blade", self.subject_of(kind="loot", detail="Test Blade")
        )

    def test_the_view_text_and_a_cutter_note_are_not_the_subject(self):
        self.assertEqual(
            "Test Warden",
            self.subject_of(detail="Test Warden; view: Alder (leader); dark 1 of 5"),
        )
        self.assertEqual("", self.subject_of(detail="view: Alder (leader)"))

    def test_a_kind_without_a_named_subject_has_none(self):
        self.assertEqual("", self.subject_of(kind="level_60", detail=""))
        self.assertEqual("", self.subject_of(kind="clear", detail="Test Mines"))


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

    def test_an_event_seen_after_its_footage_left_the_buffer_is_a_failed_row(self):
        old = NOW - clipledger.AGENT_BUFFER - timedelta(minutes=1)
        (row,) = plan(loot_rows=[loot(7, at=old)])
        self.assertEqual("failed", row["state"])
        self.assertIn(clipledger.LATE_DETAIL, row["detail"])
        up = {"id": 3, "character_name": "Alder", "kind": "level_up", "level": 60}
        (row,) = plan(event_rows=[dict(up, first_seen=old)])
        self.assertEqual("failed", row["state"])
        self.assertIn(clipledger.LATE_DETAIL, row["detail"])

    def test_history_older_than_the_late_horizon_is_not_recorded(self):
        old = NOW - clipledger.LATE_HORIZON - timedelta(minutes=1)
        self.assertEqual([], plan(loot_rows=[loot(7, at=old)]))

    def test_a_late_row_is_written_once_per_event_key(self):
        old = NOW - clipledger.AGENT_BUFFER - timedelta(minutes=1)
        (row,) = plan(loot_rows=[loot(7, at=old), loot(7, at=old)])
        again = plan(loot_rows=[loot(7, at=old)], existing_keys=[row["event_key"]])
        self.assertEqual([], again)

    def test_a_late_row_without_a_stream_path_is_late_not_no_view(self):
        old = NOW - clipledger.AGENT_BUFFER - timedelta(minutes=1)
        (row,) = plan(loot_rows=[loot(7, at=old)], path_of=lambda who: "")
        self.assertEqual("failed", row["state"])

    def test_a_late_row_keeps_the_view_text_ahead_of_its_reason(self):
        old = NOW - clipledger.AGENT_BUFFER - timedelta(minutes=1)
        (row,) = plan(
            loot_rows=[in_dungeon(loot(7, who="Cedar", at=old))],
            runs=[run()],
            roster=FAMILY,
            path_of=only("Alder"),
        )
        self.assertEqual("failed", row["state"])
        self.assertIn("view: Alder (leader)", row["detail"])
        self.assertTrue(row["detail"].endswith("; " + clipledger.LATE_DETAIL))

    def test_a_window_start_still_inside_the_buffer_is_written(self):
        at = NOW - clipledger.AGENT_BUFFER + timedelta(minutes=1)
        self.assertEqual(1, len(plan(loot_rows=[loot(7, at=at)])))


class LateHorizonTests(unittest.TestCase):
    def test_a_scan_with_no_last_scan_looks_back_a_day(self):
        self.assertEqual(timedelta(hours=24), clipledger.scan_horizon(NOW, None))

    def test_a_steady_scan_looks_back_twenty_minutes(self):
        last = NOW - timedelta(minutes=1)
        self.assertEqual(timedelta(minutes=20), clipledger.scan_horizon(NOW, last))

    def test_a_longer_gap_looks_back_to_the_last_scan(self):
        last = NOW - timedelta(minutes=90)
        self.assertEqual(timedelta(minutes=90), clipledger.scan_horizon(NOW, last))

    def test_a_gap_longer_than_a_day_is_capped_at_a_day(self):
        last = NOW - timedelta(days=3)
        self.assertEqual(timedelta(hours=24), clipledger.scan_horizon(NOW, last))

    def test_an_event_inside_the_gap_is_one_failed_row_and_a_rescan_writes_nothing(
        self,
    ):
        horizon = timedelta(hours=3)
        inside = NOW - timedelta(hours=2)
        (row,) = plan(loot_rows=[loot(7, at=inside)], late_horizon=horizon)
        self.assertEqual("failed", row["state"])
        self.assertEqual("loot:7", row["event_key"])
        self.assertIn(clipledger.LATE_DETAIL, row["detail"])
        again = plan(
            loot_rows=[loot(7, at=inside)],
            late_horizon=horizon,
            existing_keys=[row["event_key"]],
        )
        self.assertEqual([], again)

    def test_an_event_older_than_the_horizon_gets_no_row(self):
        old = NOW - timedelta(hours=4)
        rows = plan(loot_rows=[loot(7, at=old)], late_horizon=timedelta(hours=3))
        self.assertEqual([], rows)


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

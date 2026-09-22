"""The live recap, the loot board and the provenance index, as pure functions.

THE FIRST CLASS IN THIS FILE IS THE ONE THAT MATTERS. Every other suite here
is ordinary coverage; TheEquipRecordIsARescan pins the fact the whole module
was written around, which is that `overseer_event` rows of kind `item_equip`
are not equips. They are a periodic re-scan of worn gear, hourly-bucketed with
an occurrences count, so "equips inside the run window" means "everything the
party had on", and the Chronicle shipped that as a loot list. The rows in
SCAN_ROWS are shaped exactly like the live ones that proved it.

Stdlib only, no database, no HTTP: every judgement in recap.py is reachable
from here, which is the whole reason the module is separate from map_server.

Tickets: infra#2597, mod-overseer#88, mod-overseer#159.
"""

import pathlib
import unittest
from datetime import datetime, timedelta

import achievements
import recap

HERE = pathlib.Path(__file__).resolve().parent.parent

NOW = datetime(2026, 9, 5, 14, 0, 0)
ROSTER = ["Bork", "Grog", "Grug", "Og", "Ugga"]
WAILING = 43
DUNGEONS = {43: "Wailing Caverns", 36: "The Deadmines"}
ZONES = {10: "Duskwood", 17: "Barrens"}
ITEMS = {
    2169: {"name": "Buzzer Blade", "Quality": 2, "ItemLevel": 22, "displayid": 1},
    10413: {
        "name": "Gloves of the Fang",
        "Quality": 3,
        "ItemLevel": 24,
        "displayid": 2,
    },
}


def equip(
    who, entry, name, when, map_id=WAILING, zone=718, occurrences=1, detail="slot 9"
):
    return {
        "character_name": who,
        "kind": "item_equip",
        "subject_id": entry,
        "subject_name": name,
        "detail": detail,
        "map": map_id,
        "zone": zone,
        "occurrences": occurrences,
        "first_seen": when,
        "last_seen": when,
    }


def run(map_id=WAILING, state="active", started=None, ended=None, **kw):
    row = {
        "id": 1,
        "leader_name": "Grug",
        "map_id": map_id,
        "state": state,
        "started_at": started or datetime(2026, 9, 5, 13, 49, 49),
        "last_progress_at": datetime(2026, 9, 5, 13, 57, 33),
        "ended_at": ended,
        "ended_reason": "",
        "outcome": "",
    }
    row.update(kw)
    return row


def snapshot(
    name, map_id=WAILING, health=100, maximum=100, combat=0, seen=None, level=25
):
    return {
        "name": name,
        "level": level,
        "map_id": map_id,
        "health": health,
        "max_health": maximum,
        "in_combat": combat,
        "updated_at": seen or NOW,
    }


# The live shape, reduced: one item worn since before the run and re-scanned
# three times inside it, and one item first seen during the run.
SCAN_ROWS = [
    equip(
        "Ugga",
        2169,
        "Buzzer Blade",
        datetime(2026, 9, 2, 15, 41),
        map_id=36,
        zone=1581,
        occurrences=4,
    ),
    equip(
        "Ugga",
        2169,
        "Buzzer Blade",
        datetime(2026, 9, 5, 11, 2),
        map_id=0,
        zone=10,
        occurrences=4,
    ),
    equip(
        "Ugga", 2169, "Buzzer Blade", datetime(2026, 9, 5, 13, 51, 29), occurrences=3
    ),
    equip("Bork", 10413, "Gloves of the Fang", datetime(2026, 9, 5, 13, 55, 54)),
]


class TheEquipRecordIsARescan(unittest.TestCase):
    """What the module knows that the window filter did not."""

    def test_the_earliest_row_for_a_pair_is_the_one_kept(self):
        firsts = recap.first_equips(SCAN_ROWS)
        self.assertEqual(
            firsts[("Ugga", 2169)]["first_seen"], datetime(2026, 9, 2, 15, 41)
        )

    def test_one_pair_with_three_rows_is_one_entry(self):
        self.assertEqual(len(recap.first_equips(SCAN_ROWS)), 2)

    def test_rows_of_other_kinds_are_not_treated_as_equips(self):
        """The adapter reads overseer_event for four other views, so a quest
        row reaching this function is a question of when, not whether."""
        rows = SCAN_ROWS + [
            {
                "character_name": "Og",
                "kind": "quest_accept",
                "subject_id": 255,
                "first_seen": NOW,
            }
        ]
        self.assertNotIn(("Og", 255), recap.first_equips(rows))

    def test_the_same_pair_is_scanned_over_and_over(self):
        """The evidence for the header's claim, counted off the fixture: one
        sword, three rows, eight scans."""
        mine = [row for row in SCAN_ROWS if row["subject_id"] == 2169]
        self.assertEqual(len(mine), 3)
        self.assertEqual(sum(row["occurrences"] for row in mine), 11)

    def test_a_rescan_inside_the_run_is_not_that_runs_loot(self):
        """THE REGRESSION. Ugga's sword was re-scanned on the dungeon map, in
        the middle of the run, and every fact the window rule looked at says
        it is loot. It was first worn in the Deadmines three days earlier."""
        loot = recap.run_loot(
            run(), recap.first_equips(SCAN_ROWS), ITEMS, {}, NOW, DUNGEONS, ZONES
        )
        self.assertEqual([line["name"] for line in loot], ["Gloves of the Fang"])

    def test_the_window_rule_would_have_taken_both(self):
        """Stated as a test so the fix cannot be quietly reverted into
        something that passes the suite above by accident."""
        started = run()["started_at"]
        window = {
            (row["character_name"], row["subject_id"])
            for row in SCAN_ROWS
            if row["map"] == WAILING and started <= row["first_seen"] <= NOW
        }
        self.assertEqual(len(window), 2)


class WhatARunsLootIs(unittest.TestCase):
    def test_an_item_first_worn_on_another_map_is_not_this_runs(self):
        rows = [
            equip(
                "Og",
                6538,
                "Willow Robe",
                datetime(2026, 9, 5, 13, 52),
                map_id=0,
                zone=10,
            )
        ]
        self.assertEqual(
            recap.run_loot(
                run(), recap.first_equips(rows), {}, {}, NOW, DUNGEONS, ZONES
            ),
            [],
        )

    def test_an_item_first_worn_before_the_run_opened_is_not_this_runs(self):
        rows = [equip("Og", 6538, "Willow Robe", datetime(2026, 9, 5, 10, 0))]
        self.assertEqual(
            recap.run_loot(
                run(), recap.first_equips(rows), {}, {}, NOW, DUNGEONS, ZONES
            ),
            [],
        )

    def test_an_ended_runs_window_closes_at_its_end(self):
        ended = run(state="ended", ended=datetime(2026, 9, 5, 13, 52))
        rows = [equip("Bork", 10413, "Gloves", datetime(2026, 9, 5, 13, 55))]
        self.assertEqual(
            recap.run_loot(
                ended, recap.first_equips(rows), {}, {}, NOW, DUNGEONS, ZONES
            ),
            [],
        )

    def test_the_line_carries_who_when_and_where(self):
        loot = recap.run_loot(
            run(), recap.first_equips(SCAN_ROWS), ITEMS, {}, NOW, DUNGEONS, ZONES
        )
        self.assertEqual(loot[0]["who"], "Bork")
        self.assertEqual(loot[0]["place"], "Wailing Caverns")
        self.assertEqual(loot[0]["at"], "2026-09-05T13:55:54")


class WherePlacesGetTheirNames(unittest.TestCase):
    def test_a_dungeon_map_is_named_by_the_dungeon_table(self):
        self.assertEqual(recap.place_name(43, 718, DUNGEONS, ZONES), "Wailing Caverns")

    def test_an_outdoor_zone_is_named_by_the_frozen_client_table(self):
        self.assertEqual(recap.place_name(0, 10, DUNGEONS, ZONES), "Duskwood")

    def test_an_unknown_place_prints_its_ids_rather_than_shrugging(self):
        """`areatable_dbc` holds zero rows on this realm, so this is a real
        state and not a defensive branch. The ids are what somebody can go
        and look up; "unknown" throws them away."""
        self.assertEqual(recap.place_name(0, 1581, DUNGEONS, ZONES), "map 0, zone 1581")

    def test_a_place_with_no_zone_at_all_names_the_map(self):
        self.assertEqual(recap.place_name(169, 0, DUNGEONS, ZONES), "map 169")

    def test_zone_names_come_out_of_the_zones_file_shape(self):
        continents = {
            "0": {"zones": [{"area_id": 10, "name": "Duskwood"}]},
            "1": {"zones": [{"area_id": 17, "name": "Barrens"}]},
        }
        self.assertEqual(recap.zone_names(continents), {10: "Duskwood", 17: "Barrens"})


class HowFarThroughTheyAre(unittest.TestCase):
    ENCOUNTERS = [
        {"entry": 591, "creditEntry": 5775, "name": "Verdan"},
        {"entry": 585, "creditEntry": 3671, "name": "Anacondra"},
        {"entry": 586, "creditEntry": 3669, "name": "Cobrahn"},
    ]

    def test_the_encounters_come_back_in_the_tables_own_order(self):
        self.assertEqual(
            [e["name"] for e in recap.encounter_order(self.ENCOUNTERS)],
            ["Anacondra", "Cobrahn", "Verdan"],
        )

    def test_the_mask_is_read_bit_by_bit_in_that_order(self):
        down = recap.encounters_down(3, recap.encounter_order(self.ENCOUNTERS))
        self.assertEqual(down["down"], ["Anacondra", "Cobrahn"])
        self.assertEqual(down["left"], ["Verdan"])
        self.assertEqual(down["line"], "2 of 3 bosses down")

    def test_no_record_is_not_the_same_as_nothing_down(self):
        """A mask of 0 says the core watched and nothing fell. None says the
        core has no row at all. Rendering those alike is a lie in one of the
        two directions whichever way it is done."""
        none = recap.encounters_down(None, recap.encounter_order(self.ENCOUNTERS))
        zero = recap.encounters_down(0, recap.encounter_order(self.ENCOUNTERS))
        self.assertFalse(none["known"])
        self.assertTrue(zero["known"])
        self.assertNotEqual(none["line"], zero["line"])

    def test_a_map_with_no_encounter_rows_says_so(self):
        self.assertEqual(recap.encounters_down(7, [])["total"], 0)
        self.assertFalse(recap.encounters_down(7, [])["known"])

    def test_the_basis_admits_the_bit_order_is_inferred(self):
        """DungeonEncounter.dbc is not loaded on this realm, so which bit is
        which boss cannot be read. The payload must carry that admission or
        the page draws a confident bar over a guess."""
        basis = recap.encounters_down(7, recap.encounter_order(self.ENCOUNTERS))[
            "basis"
        ]
        self.assertIn("inferred", basis)
        self.assertIn("instance_encounters", basis)

    def test_the_basis_says_the_lockout_outlives_the_run(self):
        basis = recap.encounters_down(7, recap.encounter_order(self.ENCOUNTERS))[
            "basis"
        ]
        self.assertIn("lockout", basis)


class WhichInstanceRowIsThisRuns(unittest.TestCase):
    ROWS = [
        {"id": 2, "map": 43, "completedEncounters": 7},
        {"id": 1, "map": 43, "completedEncounters": 1},
        {"id": 3, "map": 36, "completedEncounters": 127},
    ]

    def test_the_newest_row_on_the_runs_map_wins(self):
        self.assertEqual(recap.bind_instance(run(), self.ROWS), 7)

    def test_a_row_on_another_map_is_never_claimed(self):
        self.assertIsNone(recap.bind_instance(run(map_id=209), self.ROWS))

    def test_no_row_is_none_and_not_zero(self):
        self.assertIsNone(recap.bind_instance(run(), []))


class WhoIsInThere(unittest.TestCase):
    def test_a_member_on_the_dungeon_map_is_inside(self):
        state = recap.party_state(["Grug"], [snapshot("Grug")], run(), NOW)[0]
        self.assertTrue(state["inside"])
        self.assertEqual(state["note"], "inside")

    def test_a_member_elsewhere_is_not(self):
        state = recap.party_state(["Grug"], [snapshot("Grug", map_id=1)], run(), NOW)[0]
        self.assertFalse(state["inside"])

    def test_zero_health_is_down_and_nothing_cleverer(self):
        """overseer_snapshot has no dead flag. A corpse and a ghost both read
        zero, and that is the whole of what the column supports."""
        state = recap.party_state(["Grug"], [snapshot("Grug", health=0)], run(), NOW)[0]
        self.assertFalse(state["alive"])
        self.assertEqual(state["note"], "down")

    def test_fighting_is_said_when_the_snapshot_says_so(self):
        state = recap.party_state(["Grug"], [snapshot("Grug", combat=1)], run(), NOW)[0]
        self.assertEqual(state["note"], "fighting")

    def test_an_old_snapshot_is_reported_as_old(self):
        old = snapshot("Grug", seen=NOW - timedelta(minutes=4))
        state = recap.party_state(["Grug"], [old], run(), NOW)[0]
        self.assertTrue(state["stale"])
        self.assertIn("old", state["note"])

    def test_a_member_with_no_row_is_unknown_rather_than_absent(self):
        state = recap.party_state(["Grug"], [], run(), NOW)[0]
        self.assertFalse(state["known"])
        self.assertIn("nothing here knows", state["note"])

    def test_every_member_carries_a_tone_the_page_can_paint_from(self):
        """The page used to work the tone out of inside/alive/in_combat, which
        is three judgements about a character in a place no test can reach."""
        rows = [
            snapshot("Bork"),
            snapshot("Grog", combat=1),
            snapshot("Grug", health=0),
            snapshot("Og", map_id=1),
        ]
        tones = {
            m["name"]: m["tone"]
            for m in recap.party_state(
                ["Bork", "Grog", "Grug", "Og", "Ugga"], rows, run(), NOW
            )
        }
        self.assertEqual(
            tones,
            {
                "Bork": "",
                "Grog": "fighting",
                "Grug": "dead",
                "Og": "away",
                "Ugga": "away",
            },
        )

    def test_a_stale_snapshot_is_toned_as_away_rather_than_as_present(self):
        old = snapshot("Grug", seen=NOW - timedelta(minutes=4))
        self.assertEqual(
            recap.party_state(["Grug"], [old], run(), NOW)[0]["tone"], "away"
        )

    def test_the_roster_order_is_never_reordered(self):
        rows = [snapshot(name) for name in reversed(ROSTER)]
        got = [m["name"] for m in recap.party_state(ROSTER, rows, run(), NOW)]
        self.assertEqual(got, ROSTER)


class TheRecapWhenSomethingIsHappening(unittest.TestCase):
    def build(self, **kw):
        args = dict(
            run_rows=[run()],
            event_rows=SCAN_ROWS,
            death_rows=[],
            snapshot_rows=[snapshot(n) for n in ROSTER],
            instance_rows=[{"id": 2, "map": 43, "completedEncounters": 3}],
            encounter_rows=HowFarThroughTheyAre.ENCOUNTERS,
            roster=ROSTER,
            items=ITEMS,
            icons={},
            dungeons=DUNGEONS,
            zones=ZONES,
            now=NOW,
        )
        args.update(kw)
        return recap.build_recap(**args)

    def test_it_is_live_and_names_the_dungeon_and_the_elapsed_time(self):
        p = self.build()
        self.assertTrue(p["live"])
        self.assertEqual(p["headline"], "Wailing Caverns, 10m in")
        self.assertEqual(p["run"]["leader"], "Grug")

    def test_the_loot_header_counts_the_rows_the_list_shows(self):
        """THE BUG THE OPERATOR SAW WAS THE HEADER, not the list. A header
        that overstates its list is worse than no header at all."""
        p = self.build()
        self.assertEqual(len(p["loot"]), 1)
        self.assertEqual(p["loot_line"], "1 first worn in here")

    def test_the_loot_carries_the_caveat_and_never_says_looted(self):
        p = self.build()
        self.assertEqual(p["loot_caveat"], recap.LOOT_CAVEAT)
        self.assertNotIn("looted here", p["loot_line"])

    def test_the_party_line_is_written_here_and_not_in_the_page(self):
        self.assertEqual(self.build()["party_line"], "all 5 inside, all standing")

    def test_the_party_line_counts_the_fallen_separately(self):
        rows = [snapshot(n) for n in ROSTER[:4]] + [snapshot("Ugga", health=0)]
        self.assertEqual(
            self.build(snapshot_rows=rows)["party_line"],
            "all 5 inside, 4 standing and 1 down",
        )

    def test_a_family_that_is_not_in_there_is_said_plainly(self):
        rows = [snapshot(n, map_id=1) for n in ROSTER]
        self.assertIn("nobody", self.build(snapshot_rows=rows)["party_line"])

    def test_progress_is_read_from_the_bound_instance(self):
        self.assertEqual(self.build()["progress"]["count"], 2)

    def test_a_run_with_no_progress_for_ten_minutes_says_it_may_be_over(self):
        stale = run(last_progress_at=datetime(2026, 9, 5, 13, 40))
        p = self.build(run_rows=[stale])
        self.assertTrue(p["run"]["stalled"])
        self.assertIn("may have ended", p["run"]["stall_note"])

    def test_the_newest_active_run_wins_when_two_are_open(self):
        older = run(started=datetime(2026, 9, 5, 12, 0))
        older["id"] = 9
        p = self.build(run_rows=[older, run()])
        self.assertEqual(p["run"]["id"], 1)

    def test_only_deaths_inside_the_run_and_on_its_map_are_counted(self):
        deaths = [
            {
                "character_name": "Ugga",
                "map": 43,
                "zone": 718,
                "killer_name": "Skum",
                "killer_type": "creature",
                "created_at": datetime(2026, 9, 5, 13, 55),
            },
            {
                "character_name": "Og",
                "map": 0,
                "zone": 10,
                "killer_name": "a wolf",
                "killer_type": "creature",
                "created_at": datetime(2026, 9, 5, 13, 55),
            },
        ]
        p = self.build(death_rows=deaths)
        self.assertEqual([d["who"] for d in p["deaths"]], ["Ugga"])
        self.assertEqual(p["deaths_line"], "1 down so far")


class TheRecapWhenNothingIsHappening(unittest.TestCase):
    """DEGRADING IS HALF THE JOB. Nothing is running most of the time."""

    def build(self, run_rows):
        return recap.build_recap(
            run_rows=run_rows,
            event_rows=SCAN_ROWS,
            death_rows=[],
            snapshot_rows=[],
            instance_rows=[],
            encounter_rows=[],
            roster=ROSTER,
            items=ITEMS,
            icons={},
            dungeons=DUNGEONS,
            zones=ZONES,
            now=NOW,
        )

    def test_no_open_run_is_not_live_and_says_why(self):
        p = self.build([run(state="ended", ended=NOW)])
        self.assertFalse(p["live"])
        self.assertEqual(p["headline"], "no dungeon run is open right now")

    def test_a_realm_that_has_never_run_one_says_something_different(self):
        p = self.build([])
        self.assertIn("has ever been recorded", p["headline"])
        self.assertIsNone(p["last"])

    def test_the_last_run_stands_in_and_is_summarised(self):
        p = self.build(
            [
                run(
                    state="ended",
                    ended=datetime(2026, 9, 5, 13, 59),
                    ended_reason="the party walked back out",
                )
            ]
        )
        self.assertIsNotNone(p["last"])
        self.assertIn("Wailing Caverns", p["last"]["line"])
        self.assertEqual(p["last"]["ended_reason"], "the party walked back out")

    def test_the_last_runs_loot_header_is_written_here_too(self):
        p = self.build([run(state="ended", ended=datetime(2026, 9, 5, 13, 59))])
        self.assertEqual(p["last"]["loot_line"], "1 first worn in there")
        self.assertEqual(len(p["last"]["loot"]), 1)

    def test_nothing_is_left_holding_a_stale_count(self):
        p = self.build([])
        for key in ("party", "loot", "deaths"):
            self.assertEqual(p[key], [], key)
        self.assertIsNone(p["progress"])
        self.assertEqual(p["inside_count"], 0)


class WhichMapTheBoardIsFor(unittest.TestCase):
    def test_an_explicit_request_wins(self):
        self.assertEqual(recap.board_map([run()], 209), 209)

    def test_otherwise_the_live_runs_map(self):
        self.assertEqual(recap.board_map([run()], None), 43)

    def test_then_the_most_recent_runs_map(self):
        rows = [
            run(map_id=36, state="ended", ended=NOW),
            run(
                map_id=209, state="ended", ended=NOW, started=datetime(2026, 9, 1, 1, 1)
            ),
        ]
        self.assertEqual(recap.board_map(rows, None), 36)

    def test_and_a_default_rather_than_an_empty_frame(self):
        self.assertEqual(recap.board_map([], None), 43)

    def test_the_runs_map_is_reported_separately_from_the_boards(self):
        """THE BUG THIS SPLIT FIXED. Browsing the Deadmines' loot while the
        family is in Wailing Caverns fetched the Deadmines' encounter list and
        counted the Wailing Caverns lockout mask against it, so the recap read
        "6 of 6 bosses down" over a dungeon nobody had entered."""
        rows = [run(map_id=43)]
        self.assertEqual(recap.run_map(rows), 43)
        self.assertEqual(recap.board_map(rows, 36), 36)

    def test_no_open_run_has_no_map_at_all(self):
        self.assertIsNone(recap.run_map([run(state="ended", ended=NOW)]))

    def test_the_items_to_name_are_sorted_and_deduplicated(self):
        self.assertEqual(recap.wanted_items(SCAN_ROWS), [2169, 10413])


def drop(
    entry,
    name,
    ilvl,
    inv_type,
    klass=4,
    subclass=2,
    required=0,
    chance=50.0,
    creature=3669,
    allowable=-1,
    group=1,
):
    return {
        "Entry": 3669,
        "Item": entry,
        "Chance": chance,
        "GroupId": group,
        "creature": creature,
        "item_name": name,
        "quality": 3,
        "item_level": ilvl,
        "required_level": required,
        "class": klass,
        "subclass": subclass,
        "inventory_type": inv_type,
        "displayid": None,
        "allowable_class": allowable,
    }


def worn(who, slot, name, ilvl, klass=4, subclass=2, inv_type=5):
    return {
        "name": who,
        "slot": slot,
        "entry": 900 + slot,
        "item_name": name,
        "quality": 2,
        "item_level": ilvl,
        "class": klass,
        "subclass": subclass,
        "inventory_type": inv_type,
        "displayid": None,
    }


class WhetherADropBeatsWhatIsWorn(unittest.TestCase):
    """The ranking, and everything it refuses to claim."""

    def member(self, level=25, klass=1, gear=None):
        gear = gear if gear is not None else [worn("Grug", 4, "Old Tunic", 20)]
        return recap.family_members(
            [{"name": "Grug", "level": level, "class": klass}], gear, ["Grug"]
        )[0]

    def test_a_higher_item_level_in_the_slot_is_an_upgrade(self):
        v = recap.verdict(drop(1, "Armor of the Fang", 23, 5), self.member())
        self.assertEqual(v["verdict"], recap.UPGRADE)
        self.assertIn("23 against the 20 of the Old Tunic", v["why"])

    def test_the_same_item_level_is_reported_as_a_tie(self):
        v = recap.verdict(drop(1, "Armor of the Fang", 20, 5), self.member())
        self.assertEqual(v["verdict"], recap.SIDEGRADE)
        self.assertIn("the same as", v["why"])

    def test_a_lower_item_level_is_not_dressed_up(self):
        self.assertEqual(
            recap.verdict(drop(1, "Rag", 12, 5), self.member())["verdict"], recap.WORSE
        )

    def test_an_empty_slot_is_all_gain_and_says_which_slot(self):
        v = recap.verdict(drop(1, "Leggings", 23, 7), self.member())
        self.assertEqual(v["verdict"], recap.EMPTY)
        self.assertEqual(v["slot"], "legs")
        self.assertIn("nothing is worn", v["why"])

    def test_armour_too_heavy_for_what_they_wear_is_refused(self):
        """READ OFF THE CHARACTER, NOT OFF A CLASS TABLE. A Warrior may wear
        plate and cannot until level 40; what he has on is the proficiency he
        actually has today."""
        v = recap.verdict(drop(1, "Plate Chest", 40, 5, subclass=4), self.member())
        self.assertEqual(v["verdict"], recap.TOO_HEAVY)
        self.assertIn("heaviest", v["why"])

    def test_armour_no_heavier_than_what_they_wear_is_ranked_normally(self):
        v = recap.verdict(drop(1, "Cloth Robe", 23, 5, subclass=1), self.member())
        self.assertEqual(v["verdict"], recap.UPGRADE)

    def test_a_level_they_have_not_reached_is_said_with_both_numbers(self):
        v = recap.verdict(
            drop(1, "Big Chest", 40, 5, required=30), self.member(level=25)
        )
        self.assertEqual(v["verdict"], recap.LOCKED)
        self.assertIn("needs level 30 and Grug is 25", v["why"])

    def test_an_item_restricted_to_other_classes_is_refused(self):
        v = recap.verdict(drop(1, "Idol", 23, 5, allowable=2), self.member(klass=1))
        self.assertEqual(v["verdict"], recap.WRONG_CLASS)

    def test_a_character_wearing_no_graded_armour_is_not_guessed_at(self):
        bare = self.member(gear=[worn("Grug", 14, "Cloak", 10, subclass=0)])
        v = recap.verdict(drop(1, "Mail Chest", 23, 5, subclass=3), bare)
        self.assertEqual(v["verdict"], recap.UNRANKED)
        self.assertIn("no graded armour", v["why"])

    def test_a_worn_item_the_world_table_cannot_name_is_not_ranked(self):
        """The equipment query LEFT JOINs item_template so a custom or removed
        entry still reports as worn. Reading its missing level as zero would
        rank every drop in the game above it, and print "against the 0 of the
        item worn there"."""
        gear = [dict(worn("Grug", 4, "Old Tunic", 20), item_name=None, item_level=None)]
        v = recap.verdict(drop(1, "Armor of the Fang", 23, 5), self.member(gear=gear))
        self.assertEqual(v["verdict"], recap.UNRANKED)
        self.assertIn("does not know the item worn", v["why"])

    def test_an_unnamed_item_is_the_one_a_ring_would_displace(self):
        gear = [
            dict(worn("Grug", 10, "Good Ring", 22, inv_type=11)),
            dict(worn("Grug", 11, "Mystery", 0, inv_type=11), item_level=None),
        ]
        v = recap.verdict(drop(1, "Heart Ring", 18, 11), self.member(gear=gear))
        self.assertEqual(v["verdict"], recap.UNRANKED)

    def test_a_bag_is_not_ranked_at_all(self):
        v = recap.verdict(
            drop(1, "Snakeskin Bag", 25, 18, klass=1, subclass=0), self.member()
        )
        self.assertEqual(v["verdict"], recap.UNRANKED)

    def test_a_second_ring_displaces_the_weaker_of_the_two(self):
        gear = [
            worn("Grug", 10, "Good Ring", 22, inv_type=11),
            worn("Grug", 11, "Poor Ring", 14, inv_type=11),
        ]
        v = recap.verdict(drop(1, "Heart Ring", 18, 11), self.member(gear=gear))
        self.assertEqual(v["verdict"], recap.UPGRADE)
        self.assertEqual(v["worn"], "Poor Ring")

    def test_an_empty_ring_slot_beats_comparing_against_the_full_one(self):
        gear = [worn("Grug", 10, "Good Ring", 22, inv_type=11)]
        v = recap.verdict(drop(1, "Heart Ring", 18, 11), self.member(gear=gear))
        self.assertEqual(v["verdict"], recap.EMPTY)

    def test_a_one_hander_is_compared_against_the_main_hand_only(self):
        """It fits the off hand too, and allowing that made every one-handed
        drop in the dungeon "wanted by" all five, because nobody has an off
        hand filled. Whether they may dual wield is not checked here."""
        self.assertEqual(recap.slots_for(13), (15,))

    def test_the_armour_grade_is_the_heaviest_piece_worn(self):
        gear = [
            worn("Grug", 4, "Mail Chest", 20, subclass=3),
            worn("Grug", 6, "Leather Legs", 20, subclass=2),
        ]
        self.assertEqual(recap.armour_grade(gear), 3)

    def test_a_shield_does_not_count_as_an_armour_grade(self):
        self.assertIsNone(
            recap.armour_grade([worn("Grug", 16, "Shield", 20, subclass=6)])
        )


class TheBoardAsAWhole(unittest.TestCase):
    ENCOUNTERS = [
        {"entry": 585, "creditEntry": 3671, "name": "Lady Anacondra"},
        {"entry": 586, "creditEntry": 3669, "name": "Lord Cobrahn"},
    ]
    LOOT = [
        drop(10410, "Leggings of the Fang", 23, 7, creature=3669),
        drop(6465, "Robe of the Moccasin", 22, 20, subclass=1, creature=3669),
        drop(5404, "Serpent's Shoulders", 23, 3, creature=3671),
        drop(6446, "Snakeskin Bag", 25, 18, klass=1, subclass=0, creature=3671),
    ]
    CHARS = [{"name": "Grug", "level": 29, "class": 1}]
    WORN = [
        worn("Grug", 4, "Defender Tunic", 23),
        worn("Grug", 2, "Old Pads", 18, inv_type=3),
    ]

    def board(self):
        return recap.build_lootboard(
            43,
            "Wailing Caverns",
            self.ENCOUNTERS,
            self.LOOT,
            self.CHARS,
            self.WORN,
            {},
            ["Grug"],
        )

    def test_the_bosses_are_the_encounter_tables_and_in_its_order(self):
        self.assertEqual(
            [b["name"] for b in self.board()["bosses"]],
            ["Lady Anacondra", "Lord Cobrahn"],
        )

    def test_a_bag_is_left_off_the_board_entirely(self):
        names = [d["name"] for b in self.board()["bosses"] for d in b["drops"]]
        self.assertNotIn("Snakeskin Bag", names)

    def test_a_drop_somebody_wants_sorts_above_one_nobody_does(self):
        cobrahn = self.board()["bosses"][1]
        self.assertTrue(cobrahn["drops"][0]["wanted_by"])

    def test_the_boss_line_counts_what_is_worth_taking(self):
        self.assertEqual(
            self.board()["bosses"][0]["line"], "1 pieces, 1 of them worth taking"
        )

    def test_every_member_gets_a_verdict_on_every_drop(self):
        for boss in self.board()["bosses"]:
            for drop_ in boss["drops"]:
                self.assertEqual(len(drop_["readers"]), 1)
                self.assertIn("why", drop_["readers"][0])

    def test_the_basis_refuses_a_stat_weighting_out_loud(self):
        self.assertIn("no stat weighting", self.board()["basis"])

    def test_a_map_with_no_encounters_says_so_rather_than_drawing_nothing(self):
        empty = recap.build_lootboard(
            1, "Kalimdor", [], [], self.CHARS, self.WORN, {}, ["Grug"]
        )
        self.assertTrue(empty["empty_note"])

    def test_a_caveat_names_no_member_because_it_is_about_the_item(self):
        """The first version interpolated members[0], so every weapon was
        captioned about Bork including the ones being read for Ugga."""
        weapon = recap.build_lootboard(
            43,
            "Wailing Caverns",
            self.ENCOUNTERS,
            [drop(6469, "Venomstrike", 24, 15, klass=2, subclass=2, creature=3669)],
            self.CHARS,
            self.WORN,
            {},
            ["Grug"],
        )
        caveats = weapon["bosses"][1]["drops"][0]["caveats"]
        self.assertTrue(caveats)
        for caveat in caveats:
            self.assertNotIn("Grug", caveat)

    def test_a_shared_roll_reports_its_group_and_not_a_percentage(self):
        """Chance 0 means the row shares one roll with its group. A number
        there would be a guess somebody would act on."""
        shared = [drop(1, "A", 20, 5, chance=0.0), drop(2, "B", 20, 5, chance=0.0)]
        board = recap.build_lootboard(
            43,
            "Wailing Caverns",
            self.ENCOUNTERS,
            shared,
            self.CHARS,
            self.WORN,
            {},
            ["Grug"],
        )
        for drop_ in board["bosses"][1]["drops"]:
            self.assertIn("shared", drop_["chance"])

    def test_a_sixth_member_is_a_different_payload_not_a_different_path(self):
        chars = self.CHARS + [{"name": "Nell", "level": 12, "class": 5}]
        gear = self.WORN + [worn("Nell", 4, "Robe", 10, subclass=1)]
        board = recap.build_lootboard(
            43,
            "Wailing Caverns",
            self.ENCOUNTERS,
            self.LOOT,
            chars,
            gear,
            {},
            ["Grug", "Nell"],
        )
        self.assertEqual(len(board["members"]), 2)
        self.assertEqual(len(board["bosses"][0]["drops"][0]["readers"]), 2)


class WhereAWornItemCameFrom(unittest.TestCase):
    EQUIPPED = [
        {"name": "Ugga", "slot": 15, "entry": 2169},
        {"name": "Ugga", "slot": 3, "entry": 4444},
    ]

    def index(self):
        return recap.provenance_index(SCAN_ROWS, self.EQUIPPED, DUNGEONS, ZONES)

    def test_the_first_equip_is_what_is_reported_not_the_latest(self):
        """The latest row is the most recent re-scan, which always says
        wherever they are standing now."""
        line = self.index()["Ugga"][2169]
        self.assertTrue(line["known"])
        self.assertEqual(line["at"], "2026-09-02T15:41:00")

    def test_it_says_first_worn_and_never_looted(self):
        line = self.index()["Ugga"][2169]
        self.assertTrue(line["line"].startswith("first worn in"))
        self.assertNotIn("looted", line["line"])

    def test_an_item_with_no_record_still_gets_a_line_saying_so(self):
        """Hiding these would make "no idea where this came from" look
        identical to "came from nowhere interesting"."""
        line = self.index()["Ugga"][4444]
        self.assertFalse(line["known"])
        self.assertIn("no record", line["line"])

    def test_the_line_names_the_date_the_record_starts(self):
        self.assertIn("02 September 2026", self.index()["Ugga"][4444]["line"])

    def test_an_empty_record_is_said_differently_from_a_missing_row(self):
        empty = recap.provenance_index([], self.EQUIPPED, DUNGEONS, ZONES)
        self.assertIn("empty", empty["Ugga"][2169]["line"])

    def test_the_record_start_is_the_oldest_equip(self):
        self.assertEqual(recap.record_starts(SCAN_ROWS), datetime(2026, 9, 2, 15, 41))


class TheChronicleCardUsesTheSameRule(unittest.TestCase):
    """achievements.py must not keep a second opinion about what loot is."""

    def cards(self, rows):
        return achievements.build_achievements(
            [run(state="ended", ended=datetime(2026, 9, 5, 13, 59))],
            rows,
            [],
            ITEMS,
            {},
            {},
            {},
            ROSTER,
            NOW,
        )["cards"]

    def test_a_rescan_inside_the_run_is_not_on_the_card(self):
        card = [c for c in self.cards(SCAN_ROWS) if c["kind"] == "run"][0]
        self.assertEqual(
            [line["name"] for line in card["loot"]], ["Gloves of the Fang"]
        )

    def test_the_card_carries_the_shared_caveat(self):
        card = [c for c in self.cards(SCAN_ROWS) if c["kind"] == "run"][0]
        self.assertEqual(card["loot_caveat"], recap.LOOT_CAVEAT)

    def test_the_rule_is_imported_and_not_reimplemented(self):
        source = (HERE / "achievements.py").read_text(encoding="utf-8")
        self.assertIn("from recap import LOOT_CAVEAT, first_equips", source)


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in (
            "recap.py",
            "achievements.py",
            "map_server.py",
            "index.html",
            "tests/test_recap.py",
            "tests/test_recap_tab.py",
        ):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )

    def test_the_module_takes_no_database_and_no_clock_of_its_own(self):
        """Pure: `now` is always passed in, so a test can stand still."""
        source = (HERE / "recap.py").read_text(encoding="utf-8")
        self.assertNotIn("import pymysql", source)
        self.assertNotIn("datetime.now()", source)


if __name__ == "__main__":
    unittest.main()

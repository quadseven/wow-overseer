"""The order to run dungeons in, asserted against the module.

The page this replaced ranked every dungeon by gear alone, so a level 60
family saw Ahn'Qiraj Temple first. These cases pin the replacement: a path in
level order for each family, Alliance and Horde both, with upgrades riding
along and never deciding the order, and an honest mark on every step the
overseer cannot run yet.
"""

import pathlib
import unittest

import council
import dungeonpath
import dungeonplan
import jobs

HERE = pathlib.Path(__file__).resolve().parent.parent


def card(map_id, gainers=(), total=0, name=None, members=None):
    """A dungeonplan card with only the keys the path reads."""
    gainers = list(gainers)
    return {
        "map_id": map_id,
        "name": name or "map %d" % map_id,
        "gainers": gainers,
        "total": total,
        "line": (
            "all %d would gain something" % len(gainers)
            if gainers
            else "nothing in here beats what is already worn"
        ),
        "members": members or [],
        "chips": [],
    }


def plan(*cards):
    return {"dungeons": list(cards)}


FIVE_AT_60 = [{"name": n, "level": 60} for n in ("A", "B", "C", "D", "E")]
HORDE_LOW = [{"name": "Z", "level": 15}] + [
    {"name": n, "level": 11} for n in ("O", "U", "K", "R")
]
PORTALS = dungeonpath.portals_by_map()


def build(
    members=FIVE_AT_60,
    faction=dungeonpath.ALLIANCE,
    the_plan=None,
    guild="",
    guild_counts=None,
    runs=(),
):
    return dungeonpath.build_family_path(
        "A",
        faction,
        members,
        the_plan or plan(),
        guild,
        guild_counts or {},
        list(runs),
        PORTALS,
    )


def step(path, map_id):
    return next(s for s in path["behind"] + path["steps"] if s["map_id"] == map_id)


def whole(path):
    return path["behind"] + path["steps"]


class ThePathIsInLevelOrder(unittest.TestCase):
    def test_a_forty_player_raid_is_never_first(self):
        """The bug the operator reported: AQ40 at the top of a level 60
        family's list, because it held the most item levels."""
        path = build(the_plan=plan(card(531, "ABCDE", 900), card(36)))
        self.assertEqual(whole(path)[0]["map_id"], 389)
        self.assertEqual(whole(path)[-1]["map_id"], 531)

    def test_every_raid_comes_after_every_dungeon(self):
        kinds = [s.kind for s in dungeonpath.PATH]
        self.assertEqual(kinds, sorted(kinds, key=lambda k: k == dungeonpath.RAID))

    def test_the_dungeons_run_lowest_band_first(self):
        floors = [s.floor for s in dungeonpath.PATH if s.kind == dungeonpath.DUNGEON]
        # Scarlet Monastery's floor is its first wing's, so it may sit a level
        # ahead of a dungeon whose band starts one lower; nothing drops by more.
        for before, after in zip(floors, floors[1:], strict=False):
            self.assertLessEqual(before - after, 1, (before, after))

    def test_a_floor_the_council_recommends_is_the_councils(self):
        """Two answers to "is the family ready for Blackrock Depths" would be
        free to disagree on the same evening."""
        for s in dungeonpath.PATH:
            if s.map_id in council.PLACES:
                self.assertEqual(s.floor, council.PLACES[s.map_id], s.map_id)

    def test_upgrades_do_not_change_the_order(self):
        quiet = [s["map_id"] for s in whole(build())]
        loud = [
            s["map_id"]
            for s in whole(
                build(the_plan=plan(card(329, "ABCDE", 500), card(531, "ABCDE", 900)))
            )
        ]
        self.assertEqual(quiet, loud)


class WhereTheFamilyStands(unittest.TestCase):
    def test_a_level_60_family_has_outgrown_the_low_dungeons(self):
        path = build()
        self.assertEqual(step(path, 36)["state"], dungeonpath.BEHIND)
        self.assertIn("Outgrown", step(path, 36)["state_line"])

    def test_next_is_the_first_step_in_range_that_holds_something(self):
        path = build(the_plan=plan(card(289, "AB", 40), card(230, "A", 10)))
        nexts = [s for s in path["steps"] if s["state"] == dungeonpath.NEXT]
        self.assertEqual([s["map_id"] for s in nexts], [230])
        self.assertIn("Next:", path["next_line"])
        self.assertIn(step(path, 230)["name"], path["next_line"])

    def test_with_nothing_to_gain_next_is_the_first_step_in_range(self):
        path = build()
        first_live = next(
            s
            for s in path["steps"]
            if s["state"] in (dungeonpath.NOW, dungeonpath.NEXT)
        )
        self.assertEqual(first_live["state"], dungeonpath.NEXT)

    def test_a_low_family_is_told_the_level_it_needs(self):
        """The Horde family at 11: nothing is in range yet, and the page says
        what level opens the first step instead of pointing at nothing."""
        path = build(members=HORDE_LOW, faction=dungeonpath.HORDE)
        self.assertFalse([s for s in path["steps"] if s["state"] == dungeonpath.NEXT])
        self.assertIn("once O reaches %d" % council.PLACES[389], path["next_line"])
        self.assertIn("No step is in range", path["family_upgrades"])

    def test_the_weakest_member_places_the_family(self):
        mixed = [{"name": "A", "level": 60}, {"name": "B", "level": 20}]
        path = build(members=mixed)
        self.assertEqual(step(path, 230)["state"], dungeonpath.AHEAD)
        self.assertIn("B, the lowest of them, is 20", step(path, 230)["state_line"])


class TheOutgrownStepsFoldAway(unittest.TestCase):
    def test_a_level_60_family_opens_on_the_first_step_in_range(self):
        path = build()
        self.assertTrue(
            all(
                s["state"] in (dungeonpath.BEHIND, dungeonpath.OFF)
                for s in path["behind"]
            )
        )
        self.assertNotIn(
            path["steps"][0]["state"], (dungeonpath.BEHIND, dungeonpath.OFF)
        )
        self.assertIn("%d steps behind them" % len(path["behind"]), path["behind_line"])

    def test_a_low_family_has_nothing_folded(self):
        path = build(members=HORDE_LOW, faction=dungeonpath.HORDE)
        self.assertEqual(path["behind"], [])
        self.assertEqual(path["behind_line"], "")

    def test_a_raid_is_not_a_family_upgrade(self):
        path = build(the_plan=plan(card(531, "ABCDE", 900), card(230, "A", 10)))
        self.assertIn("(1)", path["family_upgrades"])
        self.assertNotIn("(5)", path["family_upgrades"])


class BothFactions(unittest.TestCase):
    def test_the_stockade_is_off_the_horde_path(self):
        path = build(members=HORDE_LOW, faction=dungeonpath.HORDE)
        self.assertEqual(step(path, 34)["state"], dungeonpath.OFF)
        self.assertIn("Stormwind", step(path, 34)["state_line"])

    def test_ragefire_chasm_is_off_the_alliance_path(self):
        path = build()
        self.assertEqual(step(path, 389)["state"], dungeonpath.OFF)
        self.assertIn("Orgrimmar", step(path, 389)["state_line"])

    def test_the_faction_comes_from_the_races(self):
        self.assertEqual(
            dungeonpath.faction_of([1, 3, 4], {1, 3, 4}, {2, 5}), dungeonpath.ALLIANCE
        )
        self.assertEqual(
            dungeonpath.faction_of([2, 5, 1], {1}, {2, 5}), dungeonpath.HORDE
        )
        self.assertEqual(dungeonpath.faction_of([], {1}, {2}), "")

    def test_the_headline_names_every_family(self):
        a = build()
        h = build(members=HORDE_LOW, faction=dungeonpath.HORDE)
        h["title"] = "Z's family"
        line = dungeonpath.headline([a, h])
        self.assertIn("A's family", line)
        self.assertIn("Z's family", line)


class WhatTheOverseerCanRun(unittest.TestCase):
    def test_every_portal_keyword_has_a_map(self):
        """A portal added to jobs.py without a map here would read as a dungeon
        the overseer cannot run, which is the wrong way round."""
        self.assertEqual(set(dungeonpath.PORTAL_MAPS), set(jobs.PORTAL_KEYWORDS))

    def test_a_portal_dungeon_is_marked_runnable(self):
        path = build()
        for map_id in (36, 33, 189, 34, 43):
            self.assertTrue(step(path, map_id)["overseer"]["can"], map_id)

    def test_a_dungeon_without_a_portal_says_so(self):
        brd = step(build(), 230)
        self.assertFalse(brd["overseer"]["can"])
        self.assertIn("cannot run this one yet", brd["overseer"]["line"])
        self.assertIn(
            {"text": "overseer cannot run it yet", "tone": "no"}, brd["chips"]
        )

    def test_scarlet_names_all_four_wings(self):
        line = step(build(), 189)["overseer"]["line"]
        for wing in (
            "scarlet",
            "scarlet-library",
            "scarlet-armory",
            "scarlet-cathedral",
        ):
            self.assertIn(wing, line)

    def test_the_page_line_counts_dungeons_not_portals(self):
        line = dungeonpath.runnable_line(PORTALS, {36: "The Deadmines"})
        self.assertIn("5 dungeons", line)
        self.assertIn("The Deadmines", line)


class RunsAndUpgrades(unittest.TestCase):
    def test_runs_are_counted_and_only_complete_is_a_clear(self):
        runs = [
            {"map_id": 43, "outcome": "complete"},
            {"map_id": 43, "outcome": "emptied"},
            {"map_id": 43, "outcome": ""},
        ]
        self.assertEqual(
            step(build(runs=runs), 43)["runs_line"],
            "This family has started 3 runs here and cleared it once.",
        )
        self.assertEqual(
            step(build(), 43)["runs_line"], "This family has never started a run here."
        )

    def test_the_guild_count_is_on_the_step_and_in_the_summary(self):
        counts = {230: {"gainers": ["A", "X", "Y"], "of": 71, "pieces": 90}}
        path = build(guild="Cave", guild_counts=counts)
        self.assertEqual(
            step(path, 230)["guild_line"],
            "The guild Cave: 3 of 71 members would gain something here.",
        )
        self.assertIn(
            {"text": "Cave: 3 of 71 gain", "tone": "up"}, step(path, 230)["chips"]
        )
        self.assertIn("map 230 (3)", path["guild_upgrades"])

    def test_no_guild_says_nothing_about_a_guild(self):
        path = build()
        self.assertEqual(path["guild_upgrades"], "")
        self.assertIn("in no guild", path["who_line"])

    def test_each_member_keeps_the_best_piece_per_slot(self):
        found = {
            "who": "A",
            "gains": [
                {"slot": "chest", "name": "x"},
                {"slot": "chest", "name": "y"},
                {"slot": "head", "name": "z"},
            ],
            "line": "",
            "delta_note": "",
        }
        trimmed = dungeonpath._trim(found)
        self.assertEqual([g["name"] for g in trimmed["gains"]], ["x", "z"])
        self.assertEqual(
            trimmed["more_line"], "and 1 lesser piece for the same slots, not shown"
        )

    def test_a_raid_says_it_is_the_guilds_job(self):
        mc = step(build(), 409)
        self.assertIn("40 players", mc["raid_line"])
        self.assertEqual(mc["name"], "Molten Core")


class TheGuildCount(unittest.TestCase):
    def test_a_guild_member_who_would_gain_is_counted(self):
        encounters = [{"map_id": 36, "creature": 1, "name": "Boss"}]
        loot = [
            {
                "Entry": 1,
                "Item": 10,
                "creature": 1,
                "item_name": "Chest",
                "quality": 3,
                "item_level": 20,
                "required_level": 1,
                "class": 4,
                "subclass": 2,
                "displayid": None,
                "inventory_type": 5,
                "allowable_class": -1,
            }
        ]
        chars = [
            {"name": "A", "level": 20, "class": 1},
            {"name": "B", "level": 20, "class": 1},
        ]
        worn = [
            {
                "name": "A",
                "slot": 4,
                "entry": 1,
                "item_name": "Old",
                "quality": 1,
                "item_level": 5,
                "class": 4,
                "subclass": 2,
                "inventory_type": 5,
                "displayid": None,
            },
            {
                "name": "B",
                "slot": 4,
                "entry": 2,
                "item_name": "Good",
                "quality": 3,
                "item_level": 40,
                "class": 4,
                "subclass": 2,
                "inventory_type": 5,
                "displayid": None,
            },
        ]
        counts = dungeonplan.gainer_counts(
            encounters, loot, chars, worn, ["A", "B"], [36, 43]
        )
        self.assertEqual(counts[36], {"gainers": ["A"], "of": 2, "pieces": 1})
        self.assertEqual(counts[43], {"gainers": [], "of": 2, "pieces": 0})


class ItShipsInTheImage(unittest.TestCase):
    def test_the_module_is_copied_into_the_container(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("dungeonpath.py", dockerfile)


class NoEmDashes(unittest.TestCase):
    def test_the_module_writes_none(self):
        text = (HERE / "dungeonpath.py").read_text(encoding="utf-8")
        self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()

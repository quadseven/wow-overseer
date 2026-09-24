"""Raid readiness per guild: what stops the first raid, and what only slows it.

The finding the operator needs is the split between HARD blockers (the raid
cannot happen) and SOFT ones (it would go worse). These tests pin that split
and the two-guild grouping, which is what put the Horde guild on the tab.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import raidready  # noqa: E402
from raidlineup import (
    DRUID,
    HUNTER,
    MAGE,
    PALADIN,
    PRIEST,  # noqa: E402
    ROGUE,
    SHAMAN,
    WARLOCK,
    WARRIOR,
)

NO_GOALS = {"goals": []}


def _guild(name, guildid, spec, level=60, race=1):
    """Guild rows built by class: spec is [(class_id, count), ...]."""
    rows = []
    for class_id, count in spec:
        for index in range(count):
            rows.append(
                {
                    "name": "%s%d_%d" % (name, class_id, index),
                    "level": level,
                    "class_id": class_id,
                    "race": race,
                    "guildid": guildid,
                    "guild_name": name,
                }
            )
    return rows


FULL = [
    (WARRIOR, 10),
    (PRIEST, 12),
    (PALADIN, 9),
    (DRUID, 6),
    (SHAMAN, 6),
    (WARLOCK, 25),
    (MAGE, 9),
    (HUNTER, 8),
    (ROGUE, 6),
]


def _card(
    rows,
    family_names,
    *,
    min_level=50,
    worn=(),
    attuned=(),
    goals=NO_GOALS,
    runnable=True,
    clears=True,
    chars=(),
    quest_rows=(),
    holding_rows=(),
):
    group = raidready.group_guilds(rows, {"Head": family_names})[0]
    raids = frozenset({raidready.RAID_PORTAL}) if runnable else frozenset()
    with (
        mock.patch.object(raidready.jobs, "RAID_KEYWORDS", raids),
        mock.patch.object(raidready.raidrun, "CLEARS", clears),
    ):
        return raidready.build_guild(
            group,
            list(chars),
            list(worn),
            [{"name": n} for n in attuned],
            min_level,
            goals,
            quest_rows=list(quest_rows),
            holding_rows=list(holding_rows),
        )


class TwoFamiliesAreTwoGuilds(unittest.TestCase):
    def test_each_family_gets_its_own_guild_card_in_family_order(self):
        rows = _guild("Cave", 23, [(WARRIOR, 2)]) + _guild(
            "Bonkers", 24, [(PRIEST, 2)], level=10, race=2
        )
        groups = raidready.group_guilds(
            rows, {"Grug": ["Cave1_0"], "Zug": ["Bonkers5_0"]}
        )
        self.assertEqual([g["guild"] for g in groups], ["Cave", "Bonkers"])
        self.assertEqual(groups[1]["family"], "Zug")
        self.assertEqual(len(groups[1]["rows"]), 2)

    def test_a_family_in_no_guild_is_still_drawn(self):
        groups = raidready.group_guilds([], {"Zug": ["Zug", "Oz"]})
        self.assertEqual(groups[0]["guild"], "")
        self.assertEqual(groups[0]["family_names"], ["Zug", "Oz"])

    def test_the_faction_comes_from_the_races(self):
        self.assertEqual(raidready.faction_of([1, 3, 7]), "Alliance")
        self.assertEqual(raidready.faction_of([2, 5]), "Horde")
        self.assertEqual(raidready.faction_of([1, 2]), "")
        self.assertEqual(raidready.faction_of([]), "")


class AFamilyInNoGuildStillHasAFaction(unittest.TestCase):
    def test_the_race_comes_from_the_character_rows(self):
        group = raidready.group_guilds([], {"Zug": ["Zug", "Oz"]})[0]
        card = raidready.build_guild(
            group,
            [
                {"name": "Zug", "level": 15, "class": WARRIOR, "race": 2},
                {"name": "Oz", "level": 10, "class": MAGE, "race": 5},
            ],
            [],
            [],
            50,
            NO_GOALS,
        )
        self.assertEqual(card["faction"], "Horde")
        self.assertEqual(card["title"], "Zug's family (Horde)")


class HardBlockers(unittest.TestCase):
    def test_a_full_staffed_guild_with_a_raid_portal_is_ready(self):
        rows = _guild("Cave", 23, FULL)
        card = _card(
            rows,
            [rows[0]["name"]],
            attuned=[r["name"] for r in rows],
            worn=[{"name": r["name"], "slot": 0, "item_level": 60} for r in rows],
        )
        self.assertTrue(card["ready"])
        self.assertEqual(card["blockers"], [])
        self.assertIn("is ready", card["headline"])

    def test_without_a_raid_portal_nothing_can_start_the_raid(self):
        rows = _guild("Cave", 23, FULL)
        card = _card(rows, [rows[0]["name"]], runnable=False)
        self.assertFalse(card["ready"])
        first = card["blockers"][0]
        self.assertEqual(first["tone"], raidready.HARD)
        self.assertIn("cannot take a raid in", first["text"])
        self.assertIn("Molten Core is not one of them", first["text"])

    def test_a_run_that_cannot_clear_is_a_hard_blocker_said_plainly(self):
        """The raid run forms, assembles and enters; nothing clears. The card
        must not call the guild ready to raid on the strength of a runner that
        stops at the entrance."""
        rows = _guild("Cave", 23, FULL)
        card = _card(
            rows,
            [rows[0]["name"]],
            attuned=[r["name"] for r in rows],
            worn=[{"name": r["name"], "slot": 0, "item_level": 60} for r in rows],
            clears=False,
        )
        self.assertFalse(card["ready"])
        hard = [b["text"] for b in card["blockers"] if b["tone"] == raidready.HARD]
        self.assertEqual(1, len(hard), hard)
        self.assertIn("Nothing clears Molten Core yet", hard[0])
        self.assertIn("holds at the entrance", hard[0])

    def test_the_shipped_answer_is_that_nothing_clears(self):
        """Unpatched, the card states today's truth: the run exists and does
        not clear. This fails the moment raidrun claims a clear it has not got,
        or drops the run the module now has."""
        self.assertIn(raidready.RAID_PORTAL, raidready.jobs.RAID_KEYWORDS)
        self.assertFalse(raidready.raidrun.CLEARS)

    def test_a_small_guild_is_short_raiders_tanks_and_healers(self):
        rows = _guild(
            "Bonkers",
            24,
            [(WARRIOR, 1), (PRIEST, 1), (MAGE, 1), (SHAMAN, 1), (DRUID, 1)],
            level=10,
            race=2,
        )
        card = _card(rows, [r["name"] for r in rows])
        hard = [b["text"] for b in card["blockers"] if b["tone"] == "hard"]
        self.assertTrue(any("35 raiders short" in t for t in hard), hard)
        self.assertTrue(any("tanks short" in t for t in hard), hard)
        self.assertTrue(any("healers short" in t for t in hard), hard)
        self.assertTrue(any("below level 50" in t for t in hard), hard)
        self.assertIn("(Horde)", card["title"])
        self.assertIn("cannot raid Molten Core yet", card["headline"])

    def test_no_access_row_means_no_level_gate_is_invented(self):
        rows = _guild("Bonkers", 24, FULL, level=10, race=2)
        card = _card(rows, [rows[0]["name"]], min_level=None)
        self.assertFalse(
            any("the instance's own access row" in b["text"] for b in card["blockers"])
        )


class SoftBlockersStopNothing(unittest.TestCase):
    def setUp(self):
        self.rows = _guild(
            "Cave",
            23,
            [
                (WARRIOR, 10),
                (PRIEST, 12),
                (PALADIN, 9),
                (DRUID, 6),
                (SHAMAN, 6),
                (WARLOCK, 5),
                (MAGE, 9),
                (HUNTER, 8),
                (ROGUE, 6),
            ],
            level=58,
        )

    def test_below_the_cap_thin_gear_and_few_warlocks_are_soft(self):
        card = _card(
            self.rows,
            [self.rows[0]["name"]],
            worn=[{"name": r["name"], "slot": 0, "item_level": 40} for r in self.rows],
            goals={"goals": [{"name": "Healing potions", "status": "short"}]},
        )
        self.assertTrue(card["ready"], card["blockers"])
        tones = {b["tone"] for b in card["blockers"]}
        self.assertEqual(tones, {raidready.SOFT})
        text = " ".join(b["text"] for b in card["blockers"])
        self.assertIn("below level 60", text)
        self.assertIn("below item level 55", text)
        self.assertIn("summoners short", text)
        self.assertIn("Attunement to the Core", text)
        self.assertIn("healing potions", text)
        self.assertIn("could form its first Molten Core raid today", card["headline"])

    def test_the_shirt_and_tabard_do_not_drag_the_gear_average(self):
        worn = [
            {"name": "A", "slot": 0, "item_level": 60},
            {"name": "A", "slot": 3, "item_level": 1},
            {"name": "A", "slot": 18, "item_level": 1},
        ]
        self.assertEqual(raidready.worn_item_levels(worn), {"A": 60})


def _held(holder, name, count, slot=23):
    """One backpack stack, in the shape bank.members_from_rows reads."""
    return {
        "holder": holder,
        "level": 60,
        "item_guid": hash((holder, name)) & 0xFFFFFF,
        "count": count,
        "name": name,
        "quality": 1,
        "sell_price": 0,
        "required_level": 0,
        "bonding": 0,
        "item_class": 0,
        "container_slots": 0,
        "bag": 0,
        "slot": slot,
    }


class EachRaiderIsReadyOrSaysWhyNot(unittest.TestCase):
    """Per raider: gear against the floor, fire resistance against the role's
    target, and the night's supplies carried against what the role wants."""

    def setUp(self):
        self.rows = _guild("Cave", 23, FULL)
        self.head = self.rows[0]["name"]

    def _card_for(self, worn, held):
        return _card(
            self.rows,
            [self.head],
            worn=worn,
            holding_rows=held,
            clears=False,
        )

    def _tank_night(self, extra=0):
        wants = {
            "Greater Fire Protection Potion": 4 + extra,
            "Major Healing Potion": 5 + extra,
            "Flask of the Titans": 1,
            "Elixir of the Mongoose": 1,
            "Smoked Desert Dumplings": 2,
            "Juju Power": 1,
        }
        return [
            _held(self.head, name, n, slot=23 + i)
            for i, (name, n) in enumerate(sorted(wants.items()))
        ]

    def test_a_geared_stocked_main_tank_is_ready(self):
        worn = [
            {"name": self.head, "slot": 0, "item_level": 62, "fire_res": 120},
            {"name": self.head, "slot": 1, "item_level": 60, "fire_res": 80},
        ]
        card = self._card_for(worn, self._tank_night())
        head = next(r for r in card["raiders"] if r["name"] == self.head)
        self.assertTrue(head["ready"], head["short"])
        self.assertEqual("yes", head["cells"][-1])
        self.assertEqual("200 of 200", head["cells"][5])
        self.assertEqual("14 of 14", head["cells"][8])
        self.assertIn("1 ready for the core", card["raiders_line"])

    def test_a_big_stack_does_not_stand_in_for_a_missing_flask(self):
        held = [
            _held(self.head, "Major Healing Potion", 40, slot=23),
            _held(self.head, "Greater Fire Protection Potion", 4, slot=24),
        ]
        worn = [{"name": self.head, "slot": 0, "item_level": 62, "fire_res": 200}]
        head = next(
            r for r in self._card_for(worn, held)["raiders"] if r["name"] == self.head
        )
        self.assertEqual((9, 14), (head["supplies_carried"], head["supplies_wanted"]))
        self.assertEqual(["supplies 9 of 14"], head["short"])

    def test_targets_follow_the_role(self):
        card = self._card_for([], [])
        by_role = {}
        for r in card["raiders"]:
            by_role.setdefault((r["role"], r["main_tank"]), r)
        self.assertEqual(200, by_role[("tank", True)]["fire_target"])
        self.assertEqual(120, by_role[("tank", False)]["fire_target"])
        self.assertEqual(60, by_role[("healer", False)]["fire_target"])
        dps = by_role[("dps", False)]
        self.assertEqual(0, dps["fire_target"])
        self.assertNotIn(" of ", dps["cells"][5])
        self.assertIn("gear not read", dps["short"])


class EachRaiderIsReported(unittest.TestCase):
    """The operator asked for a row per raider: level, gear, attunement, fire
    resistance, role, and what stands in the way."""

    def setUp(self):
        self.rows = _guild("Cave", 23, FULL)
        self.head = self.rows[0]["name"]
        chars = []
        for index, row in enumerate(self.rows):
            chars.append(
                {
                    "name": row["name"],
                    "level": row["level"],
                    "class": row["class_id"],
                    "race": row["race"],
                    # Every fifth on Outland, one offline.
                    "map": 530 if index % 5 == 1 else 0,
                    "online": 0 if index == 2 else 1,
                }
            )
        self.worn = [
            {"name": self.head, "slot": 0, "item_level": 45, "fire_res": 0},
            {"name": self.head, "slot": 1, "item_level": 45, "fire_res": 10},
            {"name": self.head, "slot": 2, "item_level": 45, "fire_res": 7},
        ]
        self.card = _card(
            self.rows,
            [self.head],
            chars=chars,
            worn=self.worn,
            attuned=[self.head],
            clears=False,
        )
        self.by_name = {r["name"]: r for r in self.card["raiders"]}

    def test_forty_rows_one_per_placed_raider(self):
        self.assertEqual(40, len(self.card["raiders"]))
        self.assertEqual(
            len(raidready.RAIDER_COLUMNS), len(self.card["raiders"][0]["cells"])
        )
        self.assertEqual(list(raidready.RAIDER_COLUMNS), self.card["raider_columns"])

    def test_the_heads_row_carries_every_measurement(self):
        head = self.by_name[self.head]
        self.assertEqual(1, head["group"])
        self.assertEqual("tank", head["role"])
        self.assertEqual(60, head["level"])
        self.assertEqual(45, head["gear"])
        self.assertEqual(17, head["fire_res"])
        self.assertTrue(head["attuned"])
        self.assertEqual("Eastern Kingdoms", head["where"])
        self.assertEqual(
            [
                "1",
                self.head,
                "tank",
                "60",
                "45",
                "17 of 200",
                "yes",
                "0",
                "0 of 14",
                "Eastern Kingdoms",
                "no: gear 45 of 55; fire resistance 17 of 200; supplies 0 of 14",
            ],
            head["cells"],
        )
        self.assertTrue(head["main_tank"])
        self.assertFalse(head["ready"])

    def test_unread_gear_and_other_continents_are_said_not_guessed(self):
        others = [r for r in self.card["raiders"] if r["name"] != self.head]
        self.assertTrue(all(r["gear"] is None for r in others))
        self.assertTrue(all(r["cells"][4] == "not read" for r in others))
        self.assertIn("Outland", {r["where"] for r in others})
        self.assertTrue(any(r["where"].endswith(", offline") for r in others))

    def test_the_summary_line_counts_what_the_rows_say(self):
        line = self.card["raiders_line"]
        self.assertIn("40 raiders: 0 ready for the core, 1 attuned", line)
        self.assertIn("1 wearing any fire resistance (17 in all)", line)
        self.assertIn("0 fire protection potions carried", line)

    def test_the_card_says_what_the_run_does_and_that_clearing_is_off(self):
        self.assertIn("moltencore 1", self.card["run_line"])
        self.assertIn("does not clear", self.card["run_line"])
        self.assertIn("none of it has been validated live", self.card["clearing_line"])

    def test_the_attunement_path_is_on_the_card(self):
        att = self.card["attunement"]
        self.assertEqual(
            [
                {
                    "name": self.head,
                    "status": "attuned",
                    "line": "%s: attuned" % self.head,
                }
            ],
            att["members"],
        )
        self.assertIn("1 of 1 attuned", att["line"])
        self.assertEqual(3, len(att["steps"]))
        self.assertIn("Lothos Riftwaker", att["steps"][0])
        self.assertIn("blackrock depths", att["steps"][1])


class TheAttunementIsReadNotAssumed(unittest.TestCase):
    def test_each_state_in_order(self):
        status = raidready.raidrun.attunement_status
        self.assertEqual("not taken", status(False, False, 0))
        self.assertEqual("in the quest log", status(False, True, 0))
        self.assertEqual("fragment held", status(False, True, 1))
        self.assertEqual("attuned", status(True, False, 0))

    def test_the_quest_log_rows_drive_the_family_statuses(self):
        rows = _guild("Cave", 23, FULL)
        family = [rows[0]["name"], rows[1]["name"], rows[2]["name"]]
        card = _card(
            rows,
            family,
            quest_rows=[
                {"name": family[1], "status": 3},
                {"name": family[2], "status": 0},
            ],
        )
        statuses = {m["name"]: m["status"] for m in card["attunement"]["members"]}
        self.assertEqual("not taken", statuses[family[0]])
        self.assertEqual("in the quest log", statuses[family[1]])
        # Status 0 is QUEST_STATUS_NONE: a row, but not a quest in the log.
        self.assertEqual("not taken", statuses[family[2]])


class TheTopLine(unittest.TestCase):
    def test_it_counts_the_guilds_that_could_raid(self):
        self.assertEqual(
            raidready.build_readiness([{"ready": True}, {"ready": False}])["line"],
            "1 of 2 guilds could form its first raid today",
        )
        self.assertIn("no family", raidready.build_readiness([])["line"])

    def test_the_goal_line_states_the_operators_numbers(self):
        line = raidready.build_readiness([])["goal_line"]
        for number in (
            "40 raiders",
            "8 groups of 5",
            "10 on maintenance",
            "21 warlocks",
        ):
            self.assertIn(number, line)


if __name__ == "__main__":
    unittest.main()

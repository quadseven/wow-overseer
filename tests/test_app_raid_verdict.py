"""The raid page leads with one verdict (#3376).

The seam is the rendered page: the real view (app/views/raid.js) run in
node against fixture reads shaped like the live /api/raidgoals,
/api/v2/raidteams and /api/v2/ragnaros payloads. What a reader sees is
asserted, never the view's internals: one verdict card with the counting
rule in normal text, no green placement tiles above gates at zero, the
milestones grouped with the uncounted ones tagged, one merged blocker
list, every failing gate on the seat row as chips, the target role split
named next to the placed split, and the attunement card opening with its
verdict.
"""

import json
import unittest

from test_app_shell import node_module


REALM = {
    "families": [{"key": "Grug", "names": ["Brun", "Pella", "Mago", "Durg", "Sana"]}],
    "guilds": [{"name": "Cave", "family": "Grug"}],
}


def _teams():
    """Six approved seats, five filled, one open; two raiders fully ready."""

    def seat(name, role, cls):
        return {"name": name, "approved": name or "Rogo", "seat": role, "class": cls}

    return {
        "gaps": {"tanks": 0, "healers": 0, "damage": 1},
        "seats": [
            [
                seat("Brun", "tank", "Warrior"),
                seat("Pella", "healer", "Priest"),
                seat("Mago", "dps", "Mage"),
            ],
            [
                seat("Durg", "tank", "Warrior"),
                seat("Sana", "healer", "Priest"),
                seat(None, "dps", "Rogue"),
            ],
        ],
        "members": {
            "Brun": {
                "level": 60,
                "class": "Warrior",
                "attuned": False,
                "fire_resistance": 0,
            },
            "Pella": {
                "level": 60,
                "class": "Priest",
                "attuned": False,
                "fire_resistance": 0,
            },
            "Mago": {
                "level": 45,
                "class": "Mage",
                "attuned": False,
                "fire_resistance": None,
            },
            "Durg": {
                "level": 60,
                "class": "Warrior",
                "attuned": True,
                "fire_resistance": 250,
            },
            "Sana": {
                "level": 60,
                "class": "Priest",
                "attuned": True,
                "fire_resistance": 60,
            },
        },
    }


def _raider(name, group, role, ready, **kw):
    base = {
        "name": name,
        "group": group,
        "role": role,
        "ready": ready,
        "fire_target": 0,
        "supplies_carried": 0,
        "supplies_wanted": 0,
        "gear": 0.9,
        "cells": [str(group), name, "yes" if ready else "no"],
    }
    base.update(kw)
    return base


def _card():
    return {
        "guild": "Cave",
        "headline": "Cave cannot raid Molten Core yet: 2 things stop the first raid, and 55 more would make it harder.",
        "tiles": [
            {"label": "raiders placed", "value": "40 / 40", "tone": "up"},
            {"label": "tanks", "value": "8 / 8", "tone": "up"},
            {"label": "healers", "value": "17 / 17", "tone": "up"},
        ],
        "gates": {"min_level": 50, "gear_share": 0.5},
        "blockers": [
            {"tone": "hard", "text": "A prose blocker only the old card carried."},
            {"tone": "soft", "text": "Repair bots have no source on this realm."},
        ],
        "blockers_line": "What stops the first raid is listed first.",
        "attunement": {
            "line": "0 of 5 attuned to the Core.",
            "members": [
                {"name": "Brun", "status": "no", "line": "Brun not attuned"},
                {"name": "Pella", "status": "no", "line": "Pella not attuned"},
            ],
            "steps": ["Step one of the chain."],
            "unproven": "",
            "bots": "",
        },
        "run_line": "An order forms the raid from the lineup.",
        "raiders": [
            _raider(
                "Brun", 1, "tank", False, fire_target=200, supplies_wanted=15, gear=0.06
            ),
            _raider("Pella", 1, "healer", False, fire_target=60, supplies_wanted=10),
            _raider("Mago", 1, "dps", False, supplies_carried=5, supplies_wanted=5),
            _raider(
                "Durg",
                2,
                "tank",
                True,
                fire_target=200,
                supplies_carried=15,
                supplies_wanted=15,
            ),
            _raider(
                "Sana",
                2,
                "healer",
                True,
                fire_target=60,
                supplies_carried=10,
                supplies_wanted=10,
            ),
        ],
        "raider_columns": ["group", "raider", "ready for the core"],
        "raiders_line": "5 raiders placed.",
        "supply": {
            "line": "A night of Molten Core for 6 raiders wants 3 kinds of consumable; 3 are short.",
            "supply_columns": ["consumable", "wanted", "carried", "short"],
            "supplies": [],
            "fire_columns": ["raider", "fire resistance", "short"],
            "fire": [],
            "fire_line": "Targets: the Ragnaros tank 200, other tanks 120, healers 60.",
            "top_recipes": [],
            "seat_reagents": [],
            "seat_drink": [],
            "unobtainable": [],
            "pace": [],
        },
        "goals": {
            "line": "1 of 9 goals met.",
            "goals": [],
            "others": [],
            "others_line": "The rest of the tier.",
        },
        "preraid": {
            "line": "Next upgrades, for each member against what they wear.",
            "members": [
                {"name": "Brun", "line": "3 slots have an upgrade.", "rows": []}
            ],
            "columns": [],
            "runs": [],
            "progress": [],
            "closed": [],
        },
    }


def _milestone(key, label, unit, have, want, pct):
    return {
        "key": key,
        "label": label,
        "rule": "the rule for " + key,
        "unit": unit,
        "have": have,
        "want": want,
        "unread": 0,
        "percent": pct,
        "measured": True,
        "blockers": [],
    }


def _road(entered=0):
    return {
        "total": {
            "percent": 33,
            "how": "The mean of the seat percents of milestones A, B, C, E, F. Open seats count as short.",
            "counted": ["A", "B", "C", "E", "F"],
            "left_out": [],
        },
        "milestones": [
            _milestone("A", "6 seats at level 20", "seats", 6, 6, 100),
            _milestone("B", "6 seats at level 40", "seats", 3, 6, 50),
            _milestone("C", "6 seats at level 60", "seats", 2, 6, 33),
            _milestone(
                "D", "Classic dungeons cleared in level order", "dungeons", 16, 23, 70
            ),
            _milestone("E", "Molten Core attunement", "seats", 0, 6, 0),
            _milestone("F", "Fire resistance and supplies", "seats", 0, 6, 0),
            _milestone("G", "Repair and summoning coverage", "people", 1, 31, 3),
            {
                "key": "H",
                "label": "Ragnaros",
                "rule": "Ragnaros killed",
                "unit": "kill",
                "have": 0,
                "want": 1,
                "unread": 0,
                "percent": None,
                "measured": True,
                "blockers": [],
            },
        ],
        "blockers": [
            {
                "milestone": "E",
                "key": "unattuned",
                "text": "no Attunement to the Core",
                "seats_short": 6,
                "names": ["Brun", "Pella"],
            },
            {
                "milestone": "F",
                "key": "supplies",
                "text": "the night's supplies not in bags",
                "seats_short": 6,
                "names": [],
            },
            {
                "milestone": "C",
                "key": "level-60",
                "text": "below level 60",
                "seats_short": 4,
                "names": [],
            },
            {
                "milestone": "B",
                "key": "class-quest",
                "text": "mandatory class quests not rewarded",
                "seats_short": 3,
                "names": [],
            },
        ],
        "attempts": {
            "measured": True,
            "formed": entered,
            "entered": entered,
            "wiped": 0,
            "best": None,
            "killed": False,
        },
        "projected_60": None,
    }


def render(card=None, teams=None, road=None):
    card = _card() if card is None else card
    teams = _teams() if teams is None else teams
    road = _road() if road is None else road
    script = """
const card = %s, teams = %s, road = %s;
const ready = data => ({data, error: null, loading: false, at: 1});
const get = path => path === '/api/raidgoals' ? ready({guilds: [card], basis: 'counted from the reads'})
  : path.startsWith('/api/v2/raidteams') ? ready(teams)
  : path.startsWith('/api/v2/ragnaros') ? ready(road) : ready({});
console.log(JSON.stringify(M.default.render({get, params: {guild: 'cave'}, query: {}}).s));
""" % (json.dumps(card), json.dumps(teams), json.dumps(road))
    return node_module("views/raid.js", script, realm=REALM)


def between(text, start, end):
    i = text.index(start)
    j = text.index(end, i + len(start)) if end else len(text)
    return text[i:j]


class TheVerdictCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = render()

    def test_the_verdict_leads_with_the_answer_and_the_biggest_reason(self):
        verdict = between(self.page, "raid-verdict", "Getting to 60")
        self.assertIn("Cave cannot raid yet", verdict)
        self.assertIn("Biggest reason", verdict)
        self.assertIn("no Attunement to the Core", verdict)

    def test_the_percent_carries_its_counting_rule_in_normal_text(self):
        verdict = between(self.page, "raid-verdict", "Getting to 60")
        self.assertIn("33%", verdict)
        self.assertIn(
            "The mean of the seat percents of milestones A, B, C, E, F.", verdict
        )

    def test_the_four_figures_are_the_ones_a_reader_needs(self):
        verdict = between(self.page, "raid-verdict", "Getting to 60")
        for label, value in [
            ("Seats placed", "5 of 6"),
            ("At level 60", "2 of 6"),
            ("Attuned", "0 of 6"),
            ("Ready tonight", "2 of 6"),
        ]:
            self.assertIn(label, verdict)
            self.assertIn(value, verdict)

    def test_the_top_three_blockers_carry_a_next_action_into_the_gate_view(self):
        verdict = between(self.page, "raid-verdict", "Getting to 60")
        self.assertIn("below level 60", verdict)
        self.assertIn("view=gate&amp;gate=attune", verdict)
        self.assertIn("view=gate&amp;gate=supply", verdict)
        self.assertIn("view=gate&amp;gate=level", verdict)
        self.assertNotIn("mandatory class quests not rewarded", verdict)

    def test_no_green_placement_tile_sits_above_the_gates(self):
        self.assertNotIn("raid-tile", self.page)
        self.assertNotIn("40 / 40", self.page)
        self.assertNotIn("2 things stop the first raid", self.page)


class TheRoadGrouped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = render()

    def test_milestones_group_under_plain_subheads_in_order(self):
        heads = [
            self.page.index(h)
            for h in ("Getting to 60", "Getting in", "Ready for the night")
        ]
        self.assertEqual(heads, sorted(heads))
        getting = between(self.page, "Getting to 60", "Getting in")
        self.assertIn("6 seats at level 60", getting)
        self.assertNotIn("Molten Core attunement", getting)

    def test_the_uncounted_milestones_are_tagged_not_in_the_total(self):
        d_row = between(self.page, "Classic dungeons cleared", "Molten Core attunement")
        g_row = between(self.page, "Repair and summoning coverage", "Ragnaros")
        self.assertIn("not in the total", d_row)
        self.assertIn("not in the total", g_row)
        c_row = between(self.page, "6 seats at level 60", "Classic dungeons cleared")
        self.assertNotIn("not in the total", c_row)

    def test_letters_are_chips_not_headings_and_counts_carry_units(self):
        self.assertIn("road-key", self.page)
        self.assertNotIn("<b>A</b>", self.page)
        self.assertIn("2 of 6 seats", self.page)
        self.assertIn("16 of 23 dungeons", self.page)
        self.assertIn("1 of 31 people", self.page)

    def test_the_attempt_is_an_outcome_row_not_a_progress_row(self):
        h_row = between(self.page, 'road-key">H', "Blockers, most seats first")
        self.assertIn("Not attempted yet", h_row)
        self.assertNotIn("gate-bar", h_row)

    def test_no_attempt_yet_reads_as_no_attempt(self):
        self.assertIn("No Molten Core attempt yet", self.page)
        self.assertNotIn("Ragnaros attempts:", self.page)


class TheMergedBlockers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = render()

    def test_the_prose_blocker_card_is_gone(self):
        self.assertNotIn("What stands in the way", self.page)
        self.assertNotIn("A prose blocker only the old card carried.", self.page)
        self.assertNotIn("Repair bots have no source on this realm.", self.page)

    def test_a_blocker_outside_the_top_three_is_stated_once(self):
        self.assertEqual(self.page.count("mandatory class quests not rewarded"), 1)

    def test_the_list_is_the_road_list_sorted_by_seats_short(self):
        listing = between(self.page, "Blockers, most seats first", "Every raider")
        order = [
            listing.index(t)
            for t in (
                "no Attunement to the Core",
                "below level 60",
                "mandatory class quests not rewarded",
            )
        ]
        self.assertEqual(order, sorted(order))
        self.assertIn("6 seats short", listing)

    def test_the_page_sorts_even_when_the_read_does_not(self):
        road = _road()
        road["blockers"] = [
            road["blockers"][3],
            road["blockers"][2],
            road["blockers"][0],
            road["blockers"][1],
        ]
        page = render(road=road)
        verdict = between(page, "raid-verdict", "Getting to 60")
        self.assertIn("Biggest reason: no Attunement to the Core.", verdict)
        self.assertNotIn("mandatory class quests not rewarded", verdict)
        listing = between(page, "Blockers, most seats first", "Every raider")
        order = [
            listing.index(t)
            for t in (
                "no Attunement to the Core",
                "below level 60",
                "mandatory class quests not rewarded",
            )
        ]
        self.assertEqual(order, sorted(order))


class TheSeatRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = render()

    def test_a_seat_short_on_four_gates_shows_at_least_three_chips(self):
        row = between(self.page, 'href="#/m/Brun"', 'href="#/m/Pella"')
        for chip in ("Attunement", "Fire resistance", "Supplies"):
            self.assertIn(chip, row)
        self.assertIn("more", row)

    def test_an_unmeasured_gate_is_a_chip_too(self):
        row = between(self.page, 'href="#/m/Mago"', "Group 2")
        self.assertIn("Fire resistance", row)
        self.assertIn("not measured", row)

    def test_a_ready_seat_says_ready_and_an_open_seat_stays_open(self):
        row = between(self.page, 'href="#/m/Durg"', 'href="#/m/Sana"')
        self.assertIn("ready", row)
        self.assertIn("open seat", self.page)

    def test_group_headers_carry_subtotals(self):
        group1 = between(self.page, "Group 1", "Brun")
        self.assertIn("0 ready", group1)
        self.assertIn("3 short", group1)
        self.assertIn("worst gap", group1)
        self.assertIn("attunement", group1)
        group2 = between(self.page, "Group 2", "Durg")
        self.assertIn("2 ready", group2)
        self.assertIn("0 short", group2)

    def test_the_role_line_names_the_target_split_beside_the_placed_split(self):
        line = between(self.page, "Placed:", "Group 1")
        self.assertIn("tanks 2", line)
        self.assertIn("healers 2", line)
        self.assertIn("damage 1", line)
        self.assertIn("Target split: 8 tanks, 11 healers, 21 damage", line)


class TheGateRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = render()

    def test_gate_rows_print_pass_fail_and_not_measured(self):
        attune = between(
            self.page, 'gate-label">Attuned', 'gate-label">Fire resistance'
        )
        self.assertIn("2 pass", attune)
        self.assertIn("3 short", attune)
        level = between(self.page, 'gate-label">Level 50+', 'gate-label">Attuned')
        self.assertIn("4 pass", level)
        self.assertIn("1 short", level)

    def test_the_seat_gate_prints_filled_and_open(self):
        seat = between(self.page, 'gate-label">Seats filled', 'gate-label">Level 50+')
        self.assertIn("5 filled", seat)
        self.assertIn("1 open", seat)


class TheAttunementCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = render()

    def test_the_card_opens_with_its_verdict_before_any_chips(self):
        card = between(self.page, 'card-title">Attunement to the Core', "Every raider")
        verdict = "0 of 6 attuned. Nobody can zone in."
        self.assertIn(verdict, card)
        self.assertLess(card.index(verdict), card.index("Brun not attuned"))


class WhenTheGuildCanRaid(unittest.TestCase):
    def test_the_verdict_and_the_attunement_card_follow_the_numbers(self):
        teams = _teams()
        for m in teams["members"].values():
            m["attuned"] = True
        teams["seats"][1][2]["name"] = "Rogo"
        teams["members"]["Rogo"] = {
            "level": 60,
            "class": "Rogue",
            "attuned": True,
            "fire_resistance": 0,
        }
        card = _card()
        for r in card["raiders"]:
            r["ready"] = True
        card["raiders"].append(
            _raider("Rogo", 2, "dps", True, supplies_carried=5, supplies_wanted=5)
        )
        road = _road(entered=2)
        for m in road["milestones"]:
            if m["key"] == "E":
                m["have"] = 6
        page = render(card=card, teams=teams, road=road)
        self.assertIn("Cave can raid", page)
        self.assertNotIn("Nobody can zone in.", page)
        self.assertIn("6 of 6 attuned.", page)
        self.assertNotIn("No Molten Core attempt yet", page)


class TheDetailZone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = render()

    def test_the_detail_cards_are_closed_folds_with_headline_summaries(self):
        self.assertGreaterEqual(self.page.count("<details"), 5)
        supply = between(
            self.page, "Supply for a night in the Core", "Fire resistance, tanks first"
        )
        self.assertIn("3 kinds of consumable; 3 are short", supply)


if __name__ == "__main__":
    unittest.main()

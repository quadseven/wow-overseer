"""Member detail (#3372): the profile page on a phone.

The header line wraps so the zone is never cut, the tab row fades at its
right edge, and the paperdoll shrinks to 44px cells around a 300px stage
with the stats two to a row. One weakest threshold rules everywhere: the
server owns it (armory.WEAKEST_FLAG) and says so on the payload, and the
paperdoll tag reads that verdict instead of a second number of its own.
The Upgrades tab opens on Upgrade now on a phone, its controls wrap, the
tiles collapse to one line over the meter, and the All filter counts the
member's own slots. The Quests tab leads with a one line summary and the
quest log, and a blocked chain step with no measured reason says so
instead of printing a note nobody wrote. Bags and bank show every bag,
empty ones included, under a two line header and a name filter. Activity
leads with its scope and its counts, groups its rows by day, caps the
first draw, and can show errors only.

The views are rendered under node from canned reads, the way
test_measured_views.py renders them; the weakest payload is read straight
from armory, and the stylesheet is read as text.
"""

import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

import armory

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
CSS = (APP / "views" / "members.css").read_text(encoding="utf-8")

PRELUDE = (
    "globalThis.window = {setTimeout: (f) => f(), addEventListener() {},"
    " matchMedia: (q) => ({matches: %s && q.indexOf('coarse') !== -1})};\n"
    "globalThis.location = {hash: %s};\n"
    "globalThis.document = {querySelector: () => null, addEventListener() {}};\n"
    "globalThis.history = {replaceState() {}};\n"
    "function ctx(view, params, reads) {\n"
    "  return {view, section: 'members', params, query: {}, hash: location.hash,\n"
    "    isPhone: %s, get: (p) => (p in reads ? {data: reads[p], at: 1, error: null}"
    " : {data: undefined, at: 0, error: null, loading: true})};\n"
    "}\n"
)

REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}, {"key": "Zug", "names": ["Zug"]}],
    "guilds": [
        {"name": "Cave", "family": "Grug"},
        {"name": "Bonkers", "family": "Zug"},
    ],
}


def render(module, script, hash_="#/m/Grug", phone=False):
    """Run `script` with the app copied to a module package; M is `module`."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = (
            PRELUDE
            % (
                "true" if phone else "false",
                json.dumps(hash_),
                "true" if phone else "false",
            )
            + "(await import(%s)).learn(%s);\n"
            % (json.dumps((root / "families.js").as_uri()), json.dumps(REALM))
            + "const M = await import(%s);\n" % json.dumps((root / module).as_uri())
            + script
        )
        out = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", code],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def member(blocker=""):
    return {
        "name": "Grug",
        "guild": "Cave",
        "family": "Grug",
        "level": 42,
        "class": "Warrior",
        "race": "Human",
        "zone": "Eastern Plaguelands",
        "online": True,
        "life": "alive",
        "stuck": False,
        "step": "Questing",
        "blocker": blocker,
        "since": None,
    }


ROSTER = {"members": [member()], "checked_at": 1_800_000_000, "basis": ""}


def render_member(tab, reads, hash_=None, phone=False, blocker=""):
    roster = {"members": [member(blocker)], "checked_at": 1_800_000_000, "basis": ""}
    all_reads = {"/api/v2/roster": roster}
    all_reads.update(reads)
    return render(
        "views/member.js",
        "const reads = %s;\n" % json.dumps(all_reads)
        + "const c = ctx('member', {name: 'Grug', tab: %s}, reads);\n" % json.dumps(tab)
        + "console.log(JSON.stringify(String(M.default.render(c))));",
        hash_=hash_ or ("#/m/Grug/" + tab),
        phone=phone,
    )


# ---- the one weakest threshold -------------------------------------------------

BUCKETS = (
    "head",
    "shoulders",
    "chest",
    "waist",
    "legs",
    "feet",
    "wrists",
    "hands",
    "back",
    "main hand",
    "off hand",
    "ranged",
)


def slots_at(item_level, main_hand=None):
    out = []
    for name in BUCKETS:
        level = (
            main_hand if name == "main hand" and main_hand is not None else item_level
        )
        out.append({"slot": name, "empty": False, "item_level": level})
    return out


class TheServerOwnsTheWeakestThreshold(unittest.TestCase):
    def test_a_slot_far_behind_is_flagged_by_the_server(self):
        w = armory.weakest_payload("Grug", 1, 60, slots_at(58, main_hand=30))
        self.assertEqual(w["slot"], "main hand")
        self.assertGreaterEqual(w["shortfall"], armory.WEAKEST_FLAG)
        self.assertIs(w["flagged"], True)

    def test_a_slot_a_little_behind_is_not_flagged(self):
        w = armory.weakest_payload("Grug", 1, 60, slots_at(58, main_hand=55))
        self.assertEqual(w["slot"], "main hand")
        self.assertLess(w["shortfall"], armory.WEAKEST_FLAG)
        self.assertIs(w["flagged"], False)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ThePaperdollTagReadsTheServersVerdict(unittest.TestCase):
    def _doll(self, weakest):
        m = {
            "present": True,
            "name": "Grug",
            "level": 60,
            "race": "Human",
            "class": "Warrior",
            "guild": "Cave",
            "online": True,
            "faction": "alliance",
            "portrait": {},
            "gear": {
                "average_item_level": 50,
                "worn": 16,
                "slots": 17,
                "empty_slots": [],
            },
            "weakest": weakest,
            "slots": [],
            "stats": {"rows": [], "gloss": ""},
            "spec": None,
        }
        return render(
            "views/_members.js",
            "const m = %s;\n" % json.dumps(m)
            + "console.log(JSON.stringify(String(M.paperdoll(m, {left: [], right: []}, {bare: true}))));",
        )

    def test_a_shortfall_the_server_did_not_flag_draws_no_tag(self):
        # 15 is past the number the page used to judge by itself (12) and
        # under the server's flag (20): the tag follows the server.
        out = self._doll(
            {
                "slot": "feet",
                "item_level": 45,
                "level": 60,
                "shortfall": 15,
                "said": "feet, item level 45 at level 60",
                "flagged": False,
            }
        )
        self.assertNotIn("Weakest slot", out)

    def test_a_payload_with_no_verdict_draws_no_tag(self):
        out = self._doll(
            {
                "slot": "feet",
                "item_level": 30,
                "level": 60,
                "shortfall": 60,
                "said": "feet, item level 30 at level 60",
            }
        )
        self.assertNotIn("Weakest slot", out)

    def test_a_flagged_weakest_slot_leads_the_tag_row(self):
        out = self._doll(
            {
                "slot": "feet",
                "item_level": 30,
                "level": 60,
                "shortfall": 60,
                "said": "feet, item level 30 at level 60",
                "flagged": True,
            }
        )
        self.assertIn("Weakest slot feet, item level 30 at level 60", out)
        self.assertLess(out.index("Weakest slot"), out.index("Average item level"))


# ---- upgrades ------------------------------------------------------------------

UP_SLOT_UPGRADE = {
    "label": "Feet",
    "state": "upgrade",
    "worn": {"entry": 100, "name": "Old Boots", "score": 12},
    "now": {
        "entry": 101,
        "name": "New Boots",
        "quality": 2,
        "icon": "inv_boots_01",
        "gain": 3,
        "where": "drop",
    },
    "targets": {
        "preraid": [
            {
                "entry": 102,
                "name": "Pre Boots",
                "score": 20,
                "where": [{"label": "Quest"}],
            }
        ],
        "raid": [],
    },
    "next": {
        "entry": 104,
        "name": "Next Boots",
        "quality": 3,
        "icon": "inv_boots_02",
        "gain": 5,
        "where": [{"label": "Dungeon"}],
        "phase": "preraid",
    },
}

UP_SLOT_BEST = {
    "label": "Head",
    "state": "bis",
    "worn": {"entry": 110, "name": "Best Helm", "score": 30},
    "now": None,
    "targets": {"preraid": [], "raid": []},
    "next": None,
}

UPGRADES = {
    "name": "Grug",
    "level": 42,
    "class": "Warrior",
    "spec": {"tree": "Protection"},
    "now_count": 1,
    "ready": {"pct": 0.5, "slots_ready": 1, "slots_scored": 2, "line": "Half ready."},
    "now_basis": "",
    "scored_from": "",
    "slots": [UP_SLOT_UPGRADE, UP_SLOT_BEST],
    "items": {
        "100": {"quality": 1, "icon": "inv_boots_00"},
        "102": {"quality": 2, "icon": "inv_boots_01"},
        "110": {"quality": 4, "icon": "inv_helm_01"},
    },
}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheUpgradesTab(unittest.TestCase):
    def _render(self, phone=False, hash_="#/m/Grug/upgrades"):
        return render_member(
            "upgrades",
            {"/api/v2/upgrades?name=Grug": UPGRADES},
            hash_=hash_,
            phone=phone,
        )

    def test_the_all_filter_counts_the_members_own_slots(self):
        out = self._render()
        self.assertIn("All 2", out)
        self.assertNotIn("All 17", out)

    def test_on_a_phone_the_tab_opens_on_upgrade_now(self):
        out = self._render(phone=True)
        self.assertIn("Feet", out)
        self.assertNotIn("Head", out)
        self.assertIn('data-up-filter="now" aria-pressed="true"', out)

    def test_on_a_wide_screen_the_tab_opens_on_all_slots(self):
        out = self._render(phone=False)
        self.assertIn("Feet", out)
        self.assertIn("Head", out)
        self.assertIn('data-up-filter="all" aria-pressed="true"', out)

    def test_a_chosen_filter_still_wins_on_a_phone(self):
        out = self._render(phone=True, hash_="#/m/Grug/upgrades?filter=best")
        self.assertIn("Head", out)
        self.assertNotIn("Feet", out)

    def test_the_tiles_collapse_to_one_line_over_the_meter(self):
        out = self._render()
        self.assertIn('class="up-line', out)
        self.assertIn("1 of 2 slots have an upgrade", out)
        self.assertIn("1 of 2 at or near pre-raid best", out)
        self.assertIn("50% pre-raid ready", out)
        self.assertIn("+5 score to gain", out)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheUpgradesControls(unittest.TestCase):
    def test_the_all_label_comes_from_the_slot_count_it_is_given(self):
        out = render(
            "views/_members.js",
            'console.log(JSON.stringify(String(M.upgradesControls("all", "slot", 9))));',
        )
        self.assertIn("All 9", out)

    def test_without_a_count_the_label_claims_no_number(self):
        out = render(
            "views/_members.js",
            'console.log(JSON.stringify(String(M.upgradesControls("all", "slot"))));',
        )
        self.assertNotIn("All 17", out)
        self.assertIn("All slots", out)


# ---- quests ----------------------------------------------------------------------

CHAIN = {
    "title": "The Affray",
    "done": False,
    "steps": [
        {"title": "A Warrior's Training", "state": "done"},
        {"title": "Bartleby the Drunk", "state": "blocked"},
        {"title": "The Islander", "state": "locked", "level": 30},
    ],
}

CLASSCHAIN = {"chains": [CHAIN], "line": "One chain in the book."}

QUEST_LOG = {
    "member": {
        "name": "Grug",
        "used": 12,
        "slots": 20,
        "quests": [
            {
                "title": "The Scarlet Oracle",
                "level": 58,
                "ready": True,
                "objectives": [],
            },
            {
                "title": "Araj the Summoner",
                "level": 60,
                "ready": False,
                "objectives": [{"have": 3, "need": 8, "what": "samples"}],
            },
        ],
    }
}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheQuestsTab(unittest.TestCase):
    def _render(self, blocker=""):
        return render_member(
            "quests",
            {
                "/api/v2/classchain?name=Grug": CLASSCHAIN,
                "/api/client/quests?name=Grug": QUEST_LOG,
            },
            blocker=blocker,
        )

    def test_a_blocked_step_with_no_measured_reason_says_so(self):
        out = self._render(blocker="")
        self.assertIn("blocked, reason not measured", out)
        self.assertNotIn("Asked the guild", out)

    def test_a_blocked_step_prints_the_measured_blocker(self):
        out = self._render(blocker="waiting for a party member")
        self.assertIn("waiting for a party member", out)
        self.assertNotIn("reason not measured", out)

    def test_a_one_line_summary_leads_the_tab(self):
        out = self._render()
        self.assertIn("Quest log 12 of 20", out)
        self.assertIn("1 ready to hand in", out)
        self.assertIn("chain step 2 of 3 blocked", out)
        self.assertLess(out.index("Quest log 12 of 20"), out.index("qs-chain"))

    def test_the_log_column_carries_the_class_the_stylesheet_reorders(self):
        out = self._render()
        self.assertIn("qs-logcol", out)
        self.assertIn("qs-chains", out)


# ---- bags and bank -----------------------------------------------------------------

ITEM = {
    "entry": 2042,
    "name": "Linen Cloth",
    "quality": 1,
    "icon": "inv_fabric_linen_01",
    "count": 20,
}

BAGS = {
    "name": "Grug",
    "used": 3,
    "total": 19,
    "money": {"gold": 54, "silver": 12, "copper": 30},
    "containers": [
        {
            "name": "Backpack",
            "cells": [ITEM, None, dict(ITEM, name="Wool Cloth", count=4)],
        },
        {"name": "Mooncloth Bag", "cells": []},
        {"name": "Empty Pouch", "cells": [None, None]},
    ],
}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheInventoryTab(unittest.TestCase):
    def _render(self, tab="bags", phone=False, hash_=None):
        path = (
            "/api/client/bags?name=Grug"
            if tab == "bags"
            else "/api/client/bank?name=Grug"
        )
        return render_member(tab, {path: BAGS}, hash_=hash_, phone=phone)

    def test_every_bag_is_shown_even_one_with_no_cells_read(self):
        out = self._render()
        self.assertIn("Backpack", out)
        self.assertIn("Mooncloth Bag", out)
        self.assertIn("Empty Pouch", out)
        self.assertIn("0 of 0", out)

    def test_the_header_is_two_lines_and_the_slots_line_leads(self):
        out = self._render()
        self.assertIn('class="inv-head"', out)
        self.assertIn("Bags: 3 of 19 slots used", out)
        self.assertNotIn("slots used |", out)
        self.assertIn("54g", out)

    def test_a_phone_never_says_hover(self):
        out = self._render(phone=True)
        self.assertNotIn("hover", out)
        self.assertIn("tap an item", out)

    def test_a_wide_screen_keeps_hover_or_tap(self):
        out = self._render(phone=False)
        self.assertIn("hover or tap an item", out)

    def test_the_bank_header_names_the_bank(self):
        out = self._render(tab="bank")
        self.assertIn("Bank: 3 of 19 slots used", out)
        self.assertNotIn("slots used |", out)

    def test_a_name_filter_is_offered_and_keeps_what_was_typed(self):
        out = self._render(hash_="#/m/Grug/bags?bagq=Linen")
        self.assertIn("data-bag-filter", out)
        self.assertIn('placeholder="Filter items by name"', out)
        self.assertIn('value="Linen"', out)


# ---- activity ------------------------------------------------------------------------


def command(at, said, status="ok", answer="done"):
    return {
        "at": at,
        "kind": "quest",
        "source": "bridge",
        "said": said,
        "status": status,
        "answer": answer,
    }


JAN15 = 1_800_000_000  # 2027-01-15 08:00 UTC
JAN14 = JAN15 - 86_400

ACTIVITY = {
    "name": "Grug",
    "commands": [
        command(JAN15, "Walk to the quest giver"),
        command(
            JAN15 - 3600, "Sell at the vendor", "error", "refused: vendor not in range"
        ),
        command(JAN14, "Take the boat", "error", "refused: the boat is not here"),
        command(JAN14 - 3600, "Hand in the quest"),
        command(JAN14 - 7200, "Ride to the inn"),
        command(JAN14 - 10_800, "Buy bread"),
    ],
    "levels": [],
    "level": 42,
    "start_level": 41,
    "days": 7,
    "checked_at": JAN15,
}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheActivityTab(unittest.TestCase):
    def _render(self, activity=ACTIVITY, hash_="#/m/Grug/activity"):
        return render_member(
            "activity", {"/api/v2/activity?name=Grug": activity}, hash_=hash_
        )

    def test_the_scope_and_the_counts_lead_the_list(self):
        out = self._render()
        self.assertIn("commands the bridge gave Grug", out)
        self.assertIn("6 commands, 2 errors", out)
        self.assertLess(out.index("6 commands, 2 errors"), out.index("pf-cmd"))
        self.assertIn("Errors only (2)", out)

    def test_the_rows_are_grouped_by_day(self):
        out = self._render()
        self.assertEqual(out.count("data-act-day"), 2)
        self.assertIn("Jan 15", out)
        self.assertIn("Jan 14", out)
        self.assertLess(out.index("Jan 15"), out.index("Walk to the quest giver"))
        self.assertLess(out.index("Jan 14"), out.index("Take the boat"))

    def test_errors_only_draws_only_the_errors(self):
        out = self._render(hash_="#/m/Grug/activity?aerr=1")
        self.assertIn("Sell at the vendor", out)
        self.assertIn("Take the boat", out)
        self.assertNotIn("Walk to the quest giver", out)
        self.assertNotIn("Buy bread", out)

    def test_errors_only_with_no_errors_says_so(self):
        calm = dict(ACTIVITY)
        calm["commands"] = [
            command(JAN15, "Walk to the quest giver"),
            command(JAN14, "Hand in the quest"),
        ]
        out = self._render(activity=calm, hash_="#/m/Grug/activity?aerr=1")
        self.assertIn("no errors recorded", out)
        self.assertNotIn("Walk to the quest giver", out)

    def test_the_first_draw_is_capped_and_says_it_can_show_more(self):
        many = dict(ACTIVITY)
        many["commands"] = [
            command(JAN15 - i * 60, "Command %d" % i) for i in range(30)
        ]
        out = self._render(activity=many)
        rows = re.findall(r'<div class="pf-cmd" data-act-row[^>]*>', out)
        self.assertEqual(len(rows), 30)
        self.assertEqual(sum("hidden" in r for r in rows), 5)
        self.assertEqual(sum("data-capped" in r for r in rows), 5)
        self.assertIn("data-act-more", out)

    def test_a_day_whose_rows_are_all_past_the_cap_gets_no_heading(self):
        many = dict(ACTIVITY)
        many["commands"] = [
            command(JAN15 - i * 60, "Newest day %d" % i) for i in range(26)
        ] + [command(JAN14 - i * 60, "Older day %d" % i) for i in range(4)]
        out = self._render(activity=many)
        self.assertEqual(out.count("data-act-day"), 1)
        self.assertIn("Jan 15", out)

    def test_show_more_draws_every_row(self):
        many = dict(ACTIVITY)
        many["commands"] = [
            command(JAN15 - i * 60, "Command %d" % i) for i in range(30)
        ]
        out = self._render(activity=many, hash_="#/m/Grug/activity?amore=1")
        rows = re.findall(r'<div class="pf-cmd" data-act-row[^>]*>', out)
        self.assertEqual(len(rows), 30)
        self.assertEqual(sum("hidden" in r for r in rows), 0)
        self.assertNotIn("data-act-more", out)


# ---- the shell of the page -----------------------------------------------------------


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheTabRow(unittest.TestCase):
    def test_the_tab_row_carries_the_fade_class(self):
        out = render_member("overview", {})
        self.assertIn('class="tabs pf-tabs"', out)


# ---- the stylesheet ---------------------------------------------------------------------


def phone_block(css):
    """The #3372 phone block, from its comment to the end of the file."""
    return css[css.index("member detail on a phone (#3372)") :]


class ThePhoneStylesheet(unittest.TestCase):
    def test_the_header_line_wraps_on_a_phone(self):
        block = phone_block(CSS)
        self.assertIn(".pf-line", block)
        self.assertIn("white-space: normal", block)

    def test_the_tab_row_fades_at_its_right_edge(self):
        block = phone_block(CSS)
        self.assertIn(".pf-tabs", block)
        self.assertIn("mask-image: linear-gradient(to right", block)

    def test_the_doll_shrinks_around_a_300px_stage(self):
        block = phone_block(CSS)
        self.assertIn("grid-template-columns: 44px minmax(0, 1fr) 44px", block)
        self.assertIn(".pd-doll .icell { width: 44px; height: 44px; }", block)
        self.assertIn(".pd-stage { height: 300px; min-height: 300px; }", block)

    def test_the_corner_numbers_sit_on_a_dark_plate(self):
        block = phone_block(CSS)
        self.assertIn(".pd-doll .icell .lv", block)
        self.assertIn("background: rgb(14 15 24 / 0.78)", block)

    def test_the_stats_go_two_to_a_row_under_the_doll(self):
        block = phone_block(CSS)
        self.assertIn(
            ".pd-stats { display: grid; grid-template-columns: 1fr 1fr;", block
        )
        self.assertIn(".pd-gloss { grid-column: 1 / -1; }", block)

    def test_the_quest_log_leads_on_a_phone(self):
        block = phone_block(CSS)
        self.assertIn(".qs-logcol { order: -1; }", block)

    def test_the_upgrades_controls_wrap_and_the_tiles_collapse(self):
        self.assertIn(".up-controls .seg {", CSS)
        self.assertIn("flex-wrap: wrap", CSS)
        self.assertIn(".up-line { display: none; }", CSS)
        wide = CSS[CSS.index("@media (max-width: 899.98px)") :]
        self.assertIn(".up-tiles { display: none; }", wide)
        self.assertIn(".up-line { display: block; }", wide)

    def test_a_dimmed_bag_cell_and_a_hidden_activity_row_have_rules(self):
        self.assertIn(".inv-dim", CSS)
        self.assertIn("opacity: .18", CSS)
        self.assertIn(".pf-cmd[hidden]", CSS)


if __name__ == "__main__":
    unittest.main()

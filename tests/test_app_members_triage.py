"""Members triage (app/views/members.js): the sticky triage bar with its
summary line and the gear and level band chips, gear problem badges on the
cards, and stuck members grouped by family with the shared blocker stated
once. Run under node with fixture reads, the same harness as
test_table_sort.py.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

PAGE = """
globalThis.window = {setTimeout: (f) => f(), addEventListener() {}};
globalThis.location = {hash: START};
globalThis.history = {replaceState: (_s, _t, url) => { location.hash = url; }};
globalThis.document = {querySelector: () => null, addEventListener() {}};
function el() {
  return {innerHTML: "", value: "", textContent: "", on: {}, focused: false,
    addEventListener(t, f) { this.on[t] = f; }, querySelector: (s) => main.querySelector(s), querySelectorAll: () => [],
    setAttribute() {}, focus() { this.focused = true; }};
}
const els = new Map();
const main = {querySelector: (s) => { if (!els.has(s)) els.set(s, el()); return els.get(s); }, querySelectorAll: () => []};
function button(attrs) {
  return {getAttribute: (n) => (n in attrs ? attrs[n] : null), hasAttribute: (n) => n in attrs};
}
function click(wrap, attrs) { main.querySelector(wrap).on.click({target: {closest: () => button(attrs)}}); }
function ctx(tab, reads) {
  return {view: "members", section: "members", params: {tab}, query: {}, hash: START, isPhone: false,
    get: (p) => (p in reads ? {data: reads[p], at: 1, error: null} : {data: undefined, at: 0, error: null, loading: true})};
}
"""


def run(start, script):
    """Run `script` with the app copied to a module package; V is the view."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = ("const START = %s;\n%s\nconst V = (await import(%s)).default;\n%s") % (
            json.dumps(start),
            PAGE,
            json.dumps((root / "views" / "members.js").as_uri()),
            script,
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


def render(start="#/members"):
    script = (
        "const c = ctx(undefined, %s);\nconsole.log(JSON.stringify(V.render(c).s));"
    ) % (json.dumps(READS),)
    return run(start, script)


def member(
    name,
    level,
    cls,
    guild,
    zone,
    family="",
    lead=False,
    stuck=False,
    since=None,
    blocker="",
    step="questing",
    life="alive",
    online=True,
):
    return {
        "name": name,
        "level": level,
        "class": cls,
        "guild": guild,
        "zone": zone,
        "family": family,
        "lead": lead,
        "stuck": stuck,
        "since": since,
        "blocker": blocker,
        "step": step,
        "life": life,
        "online": online,
    }


SHARED_GRUG = "no quest, level or gear change for the family"
SHARED_ZUG = "town errand, no vendor within reach"

ROSTER = {
    "checked_at": 100000,
    "basis": "",
    "families": {"Grug": ["Grug", "Bork", "Og"], "Zug": ["Zug", "Zork"]},
    "stalled_families": [
        {
            "leader": "Grug",
            "members": ["Grug", "Bork", "Og"],
            "since": 96820,
            "blocker": SHARED_GRUG,
        },
        {
            "leader": "Zug",
            "members": ["Zug", "Zork"],
            "since": 82000,
            "blocker": SHARED_ZUG,
        },
    ],
    "members": [
        member(
            "Grug",
            60,
            "Warrior",
            "Cave",
            "Stormwind",
            family="Grug",
            lead=True,
            stuck=True,
            since=96820,
            blocker=SHARED_GRUG,
            step="Walking to the vendor",
        ),
        member(
            "Bork",
            60,
            "Rogue",
            "Cave",
            "Stormwind",
            family="Grug",
            stuck=True,
            since=96820,
            blocker=SHARED_GRUG,
            step="Waiting on Grug to move on",
        ),
        member(
            "Og",
            59,
            "Mage",
            "Cave",
            "Stormwind",
            family="Grug",
            stuck=True,
            since=96820,
            blocker=SHARED_GRUG,
            step="Waiting on Grug to move on",
        ),
        member(
            "Zug",
            60,
            "Warrior",
            "Bonkers",
            "Silverpine Forest",
            family="Zug",
            lead=True,
            stuck=True,
            since=82000,
            blocker=SHARED_ZUG,
            step="Walking a town errand",
        ),
        member(
            "Zork",
            60,
            "Druid",
            "Bonkers",
            "Silverpine Forest",
            family="Zug",
            stuck=True,
            since=82000,
            blocker=SHARED_ZUG,
            step="Waiting on Zug",
        ),
        member("Loner", 39, "Shaman", "Hollow", "The Barrens", step="questing"),
        member(
            "Ghosty",
            50,
            "Priest",
            "Rumble",
            "Tirisfal Glades",
            life="ghost",
            online=False,
            step="",
        ),
    ],
}


def gear(name, level, cls, guild, avg, worn, empty, weapon, weakest, flags):
    return {
        "name": name,
        "level": level,
        "class": cls,
        "guild": guild,
        "role": "",
        "avg_item_level": avg,
        "worn": worn,
        "of": 17,
        "empty": empty,
        "empty_slots": [],
        "weapon": weapon,
        "weakest": weakest,
        "gold": None,
        "presence": "online",
        "online": True,
        "life": "alive",
        "flags": flags,
        "strip": [],
    }


GUILDGEAR = {
    "empty_warn": 6,
    "empty_warn_level": 20,
    "slots": 17,
    "guilds": [
        {
            "name": "Cave",
            "members": [
                gear(
                    "Grug",
                    60,
                    "Warrior",
                    "Cave",
                    54,
                    17,
                    0,
                    True,
                    {"slot": "feet", "item_level": 45, "name": "Boots", "entry": 1},
                    [],
                ),
                gear(
                    "Bork",
                    60,
                    "Rogue",
                    "Cave",
                    50,
                    16,
                    1,
                    True,
                    {"slot": "hands", "item_level": 52, "name": "Gloves", "entry": 2},
                    [],
                ),
                gear("Og", 59, "Mage", "Cave", 48, 17, 0, True, None, []),
            ],
        },
        {
            "name": "Bonkers",
            "members": [
                gear(
                    "Zug",
                    60,
                    "Warrior",
                    "Bonkers",
                    52,
                    17,
                    0,
                    True,
                    {
                        "slot": "off hand",
                        "item_level": 40,
                        "name": "Shield",
                        "entry": 3,
                    },
                    [],
                ),
                gear(
                    "Zork",
                    60,
                    "Druid",
                    "Bonkers",
                    50,
                    17,
                    0,
                    True,
                    {"slot": "chest", "item_level": 50, "name": "Vest", "entry": 4},
                    [],
                ),
            ],
        },
        {
            "name": "Hollow",
            "members": [
                gear(
                    "Loner",
                    39,
                    "Shaman",
                    "Hollow",
                    19,
                    7,
                    10,
                    False,
                    {"slot": "waist", "item_level": 5, "name": "Cord", "entry": 5},
                    ["no weapon", "10 empty"],
                ),
            ],
        },
        {
            "name": "Rumble",
            "members": [
                gear("Ghosty", 50, "Priest", "Rumble", 44, 17, 0, True, None, []),
            ],
        },
    ],
}

READS = {"/api/v2/roster": ROSTER, "/api/guildgear": GUILDGEAR}


def card_of(markup, name):
    """The one card chunk (of the cards grid) that links to `name`."""
    for chunk in markup.split('<div class="card ro-card'):
        if ('href="#/m/' + name + '"') in chunk:
            return chunk
    raise AssertionError("no card for " + name + " in " + markup[:400])


def region(markup):
    return markup.split('data-region="roster"', 1)[1]


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheCardBadges(unittest.TestCase):
    def test_a_member_with_gear_problems_wears_the_badges(self):
        card = card_of(render(), "Loner")
        self.assertIn("No weapon", card)
        self.assertIn("10 empty", card)
        self.assertIn("Weakest: waist, ilvl 5", card)

    def test_a_far_behind_slot_badges_without_a_server_flag(self):
        # Zug is fully worn with a weapon, but his off hand is 20 item
        # levels behind his level: the weakest badge still shows.
        card = card_of(render(), "Zug")
        self.assertIn("Weakest: off hand, ilvl 40", card)

    def test_a_healthy_member_has_no_badge_row(self):
        out = render()
        self.assertNotIn("ro-badges", card_of(out, "Grug"))
        self.assertNotIn("ro-badges", card_of(out, "Bork"))
        # Only Loner and Zug carry a badge row in the whole list.
        self.assertEqual(region(out).count('class="ro-badges"'), 2)

    def test_the_card_fact_line_is_level_class_guild_zone(self):
        card = card_of(render(), "Loner")
        self.assertIn("L39 Shaman · Hollow · The Barrens", card)
        self.assertNotIn("L39 Shaman | Hollow", card)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheTriageBar(unittest.TestCase):
    def test_the_summary_line_counts_the_roster(self):
        out = render()
        self.assertIn("<b>5 stuck</b>", out)
        self.assertIn("<b>1</b> dead or ghost", out)
        self.assertIn("<b>1</b> flagged for empty slots", out)
        self.assertIn("of 7", out)

    def test_the_gear_problems_chip_filters_to_flagged_members(self):
        out = render("#/members?gear=1")
        self.assertIn('data-chip="gear"', out)
        body = region(out)
        self.assertIn("Loner", body)
        self.assertNotIn("Grug", body)
        self.assertNotIn("Zug", body)

    def test_guild_chips_cover_every_guild_on_the_roster(self):
        out = render()
        for slug in ("cave", "bonkers", "hollow", "rumble"):
            self.assertIn('data-chip="' + slug + '"', out)

    def test_a_level_band_chip_sets_the_level_filter(self):
        script = (
            "const c = ctx(undefined, %s);\nconst first = V.render(c).s;\nV.after(main, c);\n"
            "click('.ro-wrap', {'data-band': '50-59'});\n"
            "console.log(JSON.stringify({first, hash: location.hash,"
            " body: main.querySelector('[data-region=roster]').innerHTML}));"
        ) % (json.dumps(READS),)
        got = run("#/members", script)
        self.assertIn('data-band="50-59"', got["first"])
        self.assertIn("lvl=50-59", got["hash"])
        self.assertIn('href="#/m/Og"', got["body"])
        self.assertIn('href="#/m/Ghosty"', got["body"])
        self.assertNotIn('href="#/m/Grug"', got["body"])
        self.assertNotIn('href="#/m/Loner"', got["body"])


class TheStuckGrouping(unittest.TestCase):
    """With the Stuck chip on, members group by family and each family's
    shared blocker is stated once, in the family header."""

    def _sections(self, out):
        region = out.split('<div data-region="roster">', 1)[1]
        cards_part, table_part = region.split('<div class="card ro-table">', 1)
        return cards_part, table_part

    def test_family_headers_carry_the_shared_blocker_once(self):
        out = render("#/members?stuck=1")
        cards_part, table_part = self._sections(out)
        for part in (cards_part, table_part):
            self.assertIn("Grug&#39;s family", part)
            self.assertIn("Zug&#39;s family", part)
            self.assertIn("Stalled 53m", part)
            self.assertIn("Stalled 5h 0m", part)
            self.assertEqual(2, part.count("Shared blocker, stated once: "))
            self.assertEqual(1, part.count(SHARED_GRUG))
            self.assertEqual(1, part.count(SHARED_ZUG))

    def test_grouped_members_show_their_step_not_the_blocker(self):
        out = render("#/members?stuck=1")
        cards_part, _ = self._sections(out)
        self.assertIn("Walking to the vendor", cards_part)
        self.assertIn("Waiting on Zug", cards_part)
        self.assertNotIn('class="muted ro-blocker"', cards_part)

    def test_without_the_stuck_chip_there_is_no_grouping(self):
        out = render("#/members")
        cards_part, _ = self._sections(out)
        self.assertNotIn("Grug&#39;s family", out)
        self.assertNotIn("Shared blocker, stated once: ", out)
        # Ungrouped, each stuck member's card still carries its own blocker.
        self.assertEqual(3, cards_part.count(SHARED_GRUG))


class TheTriageCss(unittest.TestCase):
    """The triage bar sticks while the list scrolls, and a card blocker is
    clamped to two lines."""

    CSS = (APP / "views" / "members.css").read_text(encoding="utf-8")

    def _rule(self, selector):
        return self.CSS.split(selector + " {", 1)[1].split("}", 1)[0]

    def test_the_triage_bar_is_sticky(self):
        rule = self._rule(".ro-triage")
        self.assertIn("position: sticky", rule)
        self.assertIn("top: 44px", rule)

    def test_the_card_blocker_clamps_to_two_lines(self):
        self.assertIn("-webkit-line-clamp: 2", self._rule(".ro-blocker"))


if __name__ == "__main__":
    unittest.main()

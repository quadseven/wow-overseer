"""The gear table's phone face (app/views/gear.js), run under node with a
stand-in page: the triage cards carry the problems the read already reports
(grey or white worn at 50+, the server flags verbatim, no gold), a flagged
member's card goes straight to their upgrades, the cards have their own sort
select and problem chips that write the URL query, and the upgrades panel
links onward to the next member with problems.
"""

import json
import pathlib
import re
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
function ctx(tab, reads, query) {
  return {view: VIEW, section: "members", params: {tab}, query: query || {}, hash: START, isPhone: false,
    get: (p) => (p in reads ? {data: reads[p], at: 1, error: null} : {data: undefined, at: 0, error: null, loading: true})};
}
"""


def run(start, script, query=None):
    """Run `script` with the app copied to a module package; V is gear.js."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = (
            "const START = %s, VIEW = %s;\n%s\n"
            "const V = (await import(%s)).default;\n%s"
        ) % (
            json.dumps(start),
            json.dumps("gear"),
            PAGE,
            json.dumps((root / "views" / "gear.js").as_uri()),
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


def render(tab, reads, start, query=None):
    script = "console.log(JSON.stringify(V.render(ctx(%s, %s, %s)).s));" % (
        json.dumps(tab),
        json.dumps(reads),
        json.dumps(query or {}),
    )
    return run(start, script, query)


def strip(*qualities):
    return [
        {"slot": "slot%d" % i, "quality": q, "name": "piece" if q is not None else ""}
        for i, q in enumerate(qualities)
    ]


def gear(name, **kw):
    m = {
        "name": name,
        "class": "Warrior",
        "level": 60,
        "role": "tank",
        "guild": "Cave",
        "avg_item_level": 50,
        "worn": 17,
        "empty": 0,
        "weapon": True,
        "weakest": None,
        "gold": {"text": "12g 34s"},
        "flags": [],
        "strip": [],
        "online": True,
        "life": "alive",
        "presence": "online",
    }
    m.update(kw)
    return m


ROSTER = {"checked_at": 1, "members": [], "families": {}}


def reads(members):
    return {
        "/api/v2/roster": ROSTER,
        "/api/guildgear": {"guilds": [{"guild": "Cave", "members": members}]},
    }


def cards(markup):
    return markup.split('class="gt-cards"', 1)[1]


def card_names(markup):
    return re.findall(r'class="mname"[^>]*>([A-Za-z]+)</span>', cards(markup))


# Fleshless: no weapon (flagged), three grey or white pieces at level 60.
# Zug: flagged for empty slots, nothing grey or white.
# Og: the same grey pieces as Fleshless but level 49, unflagged.
FLESHLESS = gear(
    "Fleshless",
    weapon=False,
    flags=["no weapon"],
    worn=14,
    empty=3,
    avg_item_level=47,
    weakest={"slot": "feet", "item_level": 45},
    strip=strip(2, 0, 3, 1, 4, 2, 0),
)
ZUG = gear(
    "Zug",
    flags=["7 empty"],
    worn=10,
    empty=7,
    avg_item_level=35,
    weakest={"slot": "back", "item_level": 20},
    strip=strip(3, 3, 3, 3),
)
OG = gear(
    "Og",
    level=49,
    worn=14,
    empty=3,
    avg_item_level=30,
    weakest={"slot": "waist", "item_level": 5},
    strip=strip(2, 0, 3, 1, 4, 2, 0),
)
MEMBERS = [FLESHLESS, ZUG, OG]


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheTriageCards(unittest.TestCase):
    def markup(self):
        return render("table", reads(MEMBERS), "#/members/gear/table")

    def test_grey_or_white_at_50_plus_is_badged_from_the_strip(self):
        got = cards(self.markup())
        self.assertIn("3 grey or white at 50+", got)
        # Og wears the same grey pieces at level 49: no badge for him.
        og = got.split('href="#/m/Og/gear"', 1)[1]
        self.assertNotIn("grey or white", og)

    def test_flags_are_tags_and_gold_is_gone_from_the_card(self):
        got = cards(self.markup())
        self.assertIn("no weapon", got)
        self.assertIn("7 empty", got)
        self.assertNotIn("12g 34s", got)

    def test_a_flagged_members_card_goes_straight_to_their_upgrades(self):
        got = cards(self.markup())
        self.assertIn('href="#/members/gear/upgrades?name=Fleshless"', got)
        self.assertIn('href="#/members/gear/upgrades?name=Zug"', got)
        self.assertIn('href="#/m/Og/gear"', got)

    def test_the_strip_has_a_text_twin(self):
        got = cards(self.markup())
        self.assertIn("3 empty, weakest feet at item level 45", got)
        self.assertIn("7 empty, weakest back at item level 20", got)

    def test_the_card_anatomy_names_level_class_role_and_guild(self):
        got = cards(self.markup())
        self.assertIn("L60 Warrior, Tank, Cave", got)
        self.assertIn("iLvl 47, 14 of 17 worn", got)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheTriageControls(unittest.TestCase):
    def test_the_sort_select_offers_the_triage_sorts_and_marks_the_current_one(self):
        got = render("table", reads(MEMBERS), "#/members/gear/table?sort=ilvl")
        self.assertIn("data-gselect", got)
        for value in ('value=""', 'value="ilvl"', 'value="-empty"', 'value="level"'):
            self.assertIn(value, got)
        self.assertIn('<option value="ilvl" selected>', got)

    def test_a_problem_chip_in_the_query_filters_the_cards(self):
        got = render("table", reads(MEMBERS), "#/members/gear/table?prob=weapon")
        self.assertEqual(card_names(got), ["Fleshless"])
        self.assertIn('data-prob="weapon" aria-pressed="true"', got)

    def test_the_grey_problem_chip_filters_on_the_badge(self):
        got = render("table", reads(MEMBERS), "#/members/gear/table?prob=grey")
        self.assertEqual(card_names(got), ["Fleshless"])

    def test_clicking_a_problem_chip_filters_in_place(self):
        script = (
            "const c = ctx('table', %s);\nconst first = V.render(c).s;\nV.after(main, c);\n"
            "click('.gt-wrap', {'data-prob': 'weapon'});\n"
            "console.log(JSON.stringify({first, hash: location.hash, "
            "region: main.querySelector('[data-region=gtable]').innerHTML}));"
        ) % json.dumps(reads(MEMBERS))
        got = run("#/members/gear/table", script)
        self.assertIn("prob=weapon", got["hash"])
        self.assertEqual(
            re.findall(
                r'class="mname"[^>]*>([A-Za-z]+)</span>',
                got["region"].split('class="gt-cards"', 1)[1],
            ),
            ["Fleshless"],
        )

    def test_changing_the_sort_select_writes_the_query_and_resorts(self):
        script = (
            "const c = ctx('table', %s);\nconst first = V.render(c).s;\nV.after(main, c);\n"
            "const sel = main.querySelector('[data-gselect]');\n"
            "sel.value = '-empty';\nsel.on.change();\n"
            "console.log(JSON.stringify({first, hash: location.hash, "
            "region: main.querySelector('[data-region=gtable]').innerHTML}));"
        ) % json.dumps(reads(MEMBERS))
        got = run("#/members/gear/table", script)
        self.assertIn("sort=-empty", got["hash"])
        self.assertEqual(card_names(got["region"])[0], "Zug")

    def test_the_worst_first_note_says_what_the_sort_does(self):
        # The comparator's real order, weapon step included: flagged, then
        # no weapon, then most empty slots, then lowest item level.
        got = render("table", reads(MEMBERS), "#/members/gear/table")
        self.assertIn(
            "worst first: flagged, then no weapon, most empty slots, lowest item level",
            got,
        )


def upgrades(name):
    return {
        "name": name,
        "level": 60,
        "class": "Warrior",
        "slots": [],
        "ready": {},
        "spec": {},
        "now_count": 0,
        "now_basis": "",
        "scored_from": "",
    }


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheUpgradesWalk(unittest.TestCase):
    def markup(self, name):
        r = reads(MEMBERS)
        r["/api/v2/upgrades?name=" + name] = upgrades(name)
        return render(
            "upgrades", r, "#/members/gear/upgrades?name=" + name, {"name": name}
        )

    def test_the_next_member_with_problems_links_onward(self):
        self.assertIn("Next member with problems: Zug", self.markup("Fleshless"))
        self.assertIn("Next member with problems: Fleshless", self.markup("Og"))

    def test_the_last_flagged_member_has_no_next_link(self):
        self.assertNotIn("Next member with problems", self.markup("Zug"))


def doll_member(name, guild, faction):
    return {
        "name": name,
        "present": True,
        "portrait": {},
        "faction": faction,
        "party_role": "tank",
        "level": 60,
        "race": "Human",
        "class": "Warrior",
        "guild": guild,
        "online": True,
        "gear": {"average_item_level": 50, "worn": 17, "slots": 17, "empty_slots": []},
        "slots": [],
        "stats": {"rows": []},
        "spec": None,
        "weakest": None,
        "model": None,
    }


ARMORY = {
    "sides": [
        {"faction": "alliance", "family": "Grug", "guild": "Cave", "names": ["Grug"]},
        {"faction": "horde", "family": "Zug", "guild": "Bonkers", "names": ["Zug"]},
    ],
    "pairs": [{"left": "Grug", "right": "Zug", "role": "tank"}],
    "members": [
        doll_member("Grug", "Cave", "alliance"),
        doll_member("Zug", "Bonkers", "horde"),
    ],
    "doll": {"left": [], "right": []},
    "no_counterpart": "no one in this role on this side",
}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ThePaperdollHubLabels(unittest.TestCase):
    def test_each_pair_card_is_labelled_with_its_guild(self):
        r = reads([])
        r["/api/armory"] = ARMORY
        got = render("armory", r, "#/members/gear")
        self.assertIn('<span class="mb-kick pd-slot-guild">Cave</span>', got)
        self.assertIn('<span class="mb-kick pd-slot-guild">Bonkers</span>', got)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ThePaperdollHubJumpBar(unittest.TestCase):
    def test_the_jump_bar_reaches_guildmates(self):
        mate = {
            "name": "Og",
            "class": "Mage",
            "level": 49,
            "guild": "Cave",
            "avg_item_level": 30,
            "worn": 14,
            "of": 17,
            "weakest": {"slot": "waist", "item_level": 5},
            "strip": [],
        }
        r = reads([mate])
        r["/api/armory"] = ARMORY
        got = render("armory", r, "#/members/gear")
        self.assertIn('data-jump="Og"', got)
        self.assertIn('id="armory-Og"', got)


class ThePaperdollHubOnAPhone(unittest.TestCase):
    def test_pairs_stack_and_the_stage_is_shorter(self):
        css = (APP / "views" / "members.css").read_text(encoding="utf-8")
        self.assertNotIn("grid-auto-columns: 92%", css)
        self.assertNotIn("scroll-snap-type: x mandatory", css)
        phone_rule = "@media (max-width: 759.98px) { .pd-stage { min-height: 240px; } }"
        self.assertIn(phone_rule, css)
        # Equal specificity: the phone rule only wins the cascade if it
        # comes after the base .pd-stage rule in the file.
        self.assertGreater(css.index(phone_rule), css.index(".pd-stage {"))

    def test_the_quality_strip_is_ten_px(self):
        css = (APP / "views" / "members.css").read_text(encoding="utf-8")
        self.assertIn(".gm-cell { flex: 1; height: 10px;", css)


if __name__ == "__main__":
    unittest.main()

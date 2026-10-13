"""The Quests view (app/views/quests.js), rendered under node from canned
reads: the quester parties, the coverage and the catalogue from the three
quest reads, the filters and search that narrow the catalogue, and the page a
row opens with that quest's attempts. The nav and the route too.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}, {"key": "Zug", "names": ["Zug"]}],
    "guilds": [
        {"name": "Cave", "family": "Grug"},
        {"name": "Bonkers", "family": "Zug"},
    ],
}


def run(module, script, hash_="#/quests"):
    """Run `script` with the app copied to a module package; M is `module`."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = (
            "globalThis.window = {setTimeout: (f) => f(), addEventListener() {}};\n"
            "globalThis.location = {hash: %s};\n"
            "globalThis.history = {replaceState(_s, _t, h) { location.hash = h; }};\n"
            # after() queries its main argument; the interaction test below
            # supplies that element and its controls. This stub is only global.
            "globalThis.document = {querySelector: () => null, addEventListener() {}};\n"
            "(await import(%s)).learn(%s);\n"
            "const M = await import(%s);\n"
            "const V = M.default;\n"
            "function ctx(params, query, reads) {\n"
            "  return {view: 'quests', section: 'quests', params: params || {}, query: query || {}, hash: '',\n"
            "    isPhone: true, get: (p) => (p in reads ? {data: reads[p], at: 1, error: null}"
            " : {data: undefined, at: 0, error: null, loading: true})};\n"
            "}\n%s"
        ) % (
            json.dumps(hash_),
            json.dumps((root / "families.js").as_uri()),
            json.dumps(REALM),
            json.dumps((root / module).as_uri()),
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


def quester(name, cls, level, zone, quest=None, completed=0, broken=0):
    return {
        "name": name,
        "class": cls,
        "race": "Orc",
        "role": "dps",
        "level": level,
        "zone": zone,
        "quest": quest,
        "completed": completed,
        "broken": broken,
    }


QUESTERS = {
    "parties": [
        {
            "guild": "Cave",
            "faction": "Alliance",
            "questers": [
                quester(
                    "Tharn",
                    "Druid",
                    6,
                    "Teldrassil",
                    {"id": 456, "title": "The Balance of Nature"},
                    4,
                    1,
                ),
                quester("Mirra", "Priest", 3, "Northshire Valley", None, 2, 0),
                quester("Velo", "Shaman", 2, "Ammen Vale"),
                quester("Durga", "Hunter", 2, "Coldridge Valley"),
                quester("Fizzik", "Warlock", None, None),
            ],
        },
        {
            "guild": "Bonkers",
            "faction": "Horde",
            "questers": [
                quester("Saelis", "Paladin", 4, "Sunstrider Isle"),
                quester("Morwick", "Priest", 4, "Deathknell"),
                quester("Hoofa", "Hunter", 3, "Camp Narache"),
                quester(
                    "Grakk",
                    "Warlock",
                    5,
                    "Valley of Trials",
                    {"id": 788, "title": "Cutting Teeth"},
                    3,
                    0,
                ),
                quester("Zinja", "Mage", 5, "Valley of Trials"),
            ],
        },
    ]
}


def quest(id_, title, faction, zone, level, status, attempts=0):
    return {
        "id": id_,
        "title": title,
        "faction": faction,
        "zone": zone,
        "level": level,
        "status": status,
        "attempts": attempts,
    }


QUESTS = {
    "totals": {
        "factions": [
            {
                "faction": "Alliance",
                "completed": 4,
                "broken": 1,
                "not_reached": 95,
                "total": 100,
            },
            {
                "faction": "Horde",
                "completed": 3,
                "broken": 0,
                "not_reached": 97,
                "total": 100,
            },
        ],
        "zones": [
            {
                "zone": "Teldrassil",
                "faction": "Alliance",
                "completed": 4,
                "broken": 1,
                "not_reached": 20,
                "total": 25,
            },
            {
                "zone": "Durotar",
                "faction": "Horde",
                "completed": 3,
                "broken": 0,
                "not_reached": 22,
                "total": 25,
            },
        ],
    },
    "quests": [
        quest(
            456, "The Balance of Nature", "Alliance", "Teldrassil", 1, "completed", 1
        ),
        quest(457, "Webwood Venom", "Alliance", "Teldrassil", 4, "broken", 2),
        quest(788, "Cutting Teeth", "Horde", "Durotar", 1, "completed", 1),
        quest(792, "Vile Familiars", "Horde", "Durotar", 3, "not_reached"),
        quest(835, "Securing the Lines", "Horde", "Durotar", 9, "not_reached"),
    ],
}

ATTEMPTS = {
    "quest": QUESTS["quests"][1],
    "attempts": [
        {
            "quester": "Tharn",
            "guild": "Cave",
            "level": 4,
            "started_at": 1760000000,
            "ended_at": 1760000600,
            "outcome": "broken",
            "reason": "The spiders never drop the sac.",
            "ticket": {"number": 940, "url": "https://example.com/tickets/940"},
        },
        {
            "quester": "Mirra",
            "guild": "Cave",
            "level": 4,
            "started_at": 1760001000,
            "ended_at": None,
            "outcome": "broken",
            "reason": "",
            "ticket": {"number": 1, "url": "javascript:alert(1)"},
        },
    ],
}

READS = {"/api/v2/questers": QUESTERS, "/api/v2/quests": QUESTS}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheQuestsView(unittest.TestCase):
    def page(self, query=None, hash_="#/quests"):
        got = run(
            "views/quests.js",
            "const c = ctx({}, %s, %s);\nconsole.log(JSON.stringify({reads: V.reads(c), html: V.render(c).s}));"
            % (json.dumps(query or {}), json.dumps(READS)),
            hash_,
        )
        return got["reads"], got["html"]

    def test_it_reads_the_questers_and_the_quests(self):
        reads, _ = self.page()
        self.assertEqual(reads, ["/api/v2/questers", "/api/v2/quests"])

    def test_the_parties_draw_every_quester_with_level_zone_quest_and_counts(self):
        _, html = self.page()
        for p in QUESTERS["parties"]:
            self.assertIn(p["guild"], html)
            for m in p["questers"]:
                self.assertIn("#/m/%s/quests" % m["name"], html)
        self.assertEqual(html.count('class="card qs-quester"'), 10)
        self.assertIn("L6", html)
        self.assertIn("Teldrassil", html)
        self.assertIn('href="#/quests/456"', html)
        self.assertIn("The Balance of Nature", html)
        self.assertIn("4 completed", html)
        self.assertIn("1 broken", html)
        # A level or zone the server does not report is not measured, never 0.
        self.assertIn("level not measured", html)
        self.assertIn("zone not measured", html)
        self.assertIn("no quest on", html)

    def test_coverage_counts_each_faction_and_zone(self):
        _, html = self.page()
        self.assertIn("95 not reached", html)
        self.assertIn("97 not reached", html)
        self.assertIn('aria-label="4 completed, 1 broken, 95 not reached of 100"', html)
        self.assertIn('href="#/quests?faction=Horde&amp;zone=Durotar"', html)
        self.assertIn("2 zones", html)
        self.assertIn("7 quests completed and 1 found broken, of 200.", html)

    def test_coverage_bar_stays_within_its_track_when_totals_disagree(self):
        quests = json.loads(json.dumps(QUESTS))
        quests["totals"]["factions"][0].update(
            completed=8, broken=4, not_reached=8, total=10
        )
        reads = dict(READS, **{"/api/v2/quests": quests})
        got = run(
            "views/quests.js",
            "console.log(JSON.stringify(V.render(ctx({}, {}, %s)).s));"
            % json.dumps(reads),
        )
        self.assertIn('class="qs-bar-ok" style="width:40.00%"', got)
        self.assertIn('class="qs-bar-bad" style="width:20.00%"', got)
        self.assertIn('class="qs-bar-none" style="width:40.00%"', got)

    def test_the_catalogue_lists_every_quest(self):
        _, html = self.page()
        self.assertIn("5 of 5 quests", html)
        for q in QUESTS["quests"]:
            self.assertIn(q["title"], html)
            self.assertIn('href="#/quests/%d"' % q["id"], html)
        self.assertIn("Not reached", html)
        self.assertIn("qs-table", html)
        self.assertIn("qs-qcards", html)

    def test_filters_and_search_narrow_the_catalogue(self):
        cases = [
            ("faction=Horde", {"faction": "Horde"}, {788, 792, 835}),
            ("zone=Teldrassil", {"zone": "Teldrassil"}, {456, 457}),
            ("status=broken", {"status": "broken"}, {457}),
            ("lvl=3-5", {"lvl": "3-5"}, {457, 792}),
            ("lvl=5-", {"lvl": "5-"}, {835}),
            ("q=venom", {"q": "venom"}, {457}),
            (
                "faction+status",
                {"faction": "Horde", "status": "not_reached", "lvl": "-4"},
                {792},
            ),
        ]
        for label, query, ids in cases:
            hash_ = "#/quests?" + "&".join(k + "=" + v for k, v in query.items())
            _, html = self.page(query, hash_)
            got = {
                q["id"]
                for q in QUESTS["quests"]
                if 'href="#/quests/%d?' % q["id"] in html
            }
            self.assertEqual(got, ids, label)
            self.assertIn("%d of 5 quests" % len(ids), html, label)

    def test_search_skips_the_fields_the_server_did_not_send(self):
        got = run(
            "views/quests.js",
            "const x = {id: 1, title: 'Lost Letter', zone: null};\n"
            "const hit = (q) => M.keep(x, M.filters({q}));\n"
            "console.log(JSON.stringify([hit('undefined'), hit('null'), hit('lost'), hit('1')]));",
        )
        self.assertEqual(got, [False, False, True, True])

    def test_a_filter_that_matches_nothing_says_so_and_offers_a_clear(self):
        _, html = self.page(
            {"q": "nothing like this"}, "#/quests?q=nothing%20like%20this"
        )
        self.assertIn("No quests match", html)
        self.assertIn("data-clear", html)

    def test_the_zones_offered_are_the_chosen_factions(self):
        _, html = self.page({"faction": "Horde"}, "#/quests?faction=Horde")
        zone_select = html[html.index('id="qs-zone"') :]
        zone_select = zone_select[: zone_select.index("</select>")]
        self.assertIn("Durotar", zone_select)
        self.assertNotIn("Teldrassil", zone_select)

    def test_a_long_catalogue_grows_on_request(self):
        many = dict(
            QUESTS,
            quests=[
                quest(i, "Quest %d" % i, "Horde", "Durotar", 1, "not_reached")
                for i in range(1, 251)
            ],
        )
        got = run(
            "views/quests.js",
            "const reads = %s;\n"
            "const first = M.catalogueBody(reads['/api/v2/quests'], {});\n"
            "console.log(JSON.stringify(first.s));"
            % json.dumps({"/api/v2/quests": many}),
        )
        self.assertIn("250 of 250 quests, the first 100 shown", got)
        self.assertIn("Show 100 more", got)
        self.assertIn('href="#/quests/100"', got)
        self.assertNotIn('href="#/quests/101"', got)

    def test_show_more_grows_the_list_by_a_step_until_it_is_all_drawn(self):
        many = dict(
            QUESTS,
            quests=[
                quest(i, "Quest %d" % i, "Horde", "Durotar", 1, "not_reached")
                for i in range(1, 251)
            ],
        )
        # Rendered first, as the browser does before after(). The click lands
        # on the list region; its target answers closest() the way a click on
        # the Show more button does.
        got = run(
            "views/quests.js",
            "const ls = [];\n"
            "let h = '';\n"
            "const region = {addEventListener(k, f) { if (k === 'click') ls.push(f); },\n"
            "  get innerHTML() { return h; }, set innerHTML(v) { h = v; }};\n"
            "const main = {querySelector: (s) => (s === '[data-region=catalogue]' ? region : null)};\n"
            "const c = ctx({}, {}, %s);\n"
            "V.render(c);\n"
            "V.after(main, c);\n"
            "const more = {target: {closest: (s) => (s === '[data-more]' ? {} : null)}};\n"
            "const after = [];\n"
            "for (let i = 0; i < 2; i++) { ls.forEach((f) => f(more)); after.push(h); }\n"
            "console.log(JSON.stringify(after));"
            % json.dumps({"/api/v2/quests": many}),
        )
        second, third = got
        self.assertIn("250 of 250 quests, the first 200 shown", second)
        self.assertIn("Show 50 more", second)
        self.assertIn('href="#/quests/200"', second)
        self.assertNotIn('href="#/quests/201"', second)
        self.assertIn("250 of 250 quests</p>", third)
        self.assertIn('href="#/quests/250"', third)
        self.assertNotIn("data-more", third)

    def test_a_faction_or_zone_with_markup_stays_text_in_the_filters(self):
        hostile = dict(
            QUESTS,
            quests=[
                quest(
                    1,
                    "Odd",
                    'Horde"><b>',
                    "<img src=x onerror=alert(1)>",
                    1,
                    "not_reached",
                )
            ],
        )
        reads = dict(READS, **{"/api/v2/quests": hostile})
        got = run(
            "views/quests.js",
            "console.log(JSON.stringify(V.render(ctx({}, {}, %s)).s));"
            % json.dumps(reads),
        )
        self.assertIn('<option value="Horde&quot;&gt;&lt;b&gt;">', got)
        self.assertIn('<option value="&lt;img src=x onerror=alert(1)&gt;">', got)
        self.assertNotIn("<img", got)
        self.assertNotIn('"><b>', got)

    def test_a_row_opens_that_quests_attempts_and_keeps_the_filters(self):
        _, html = self.page({"zone": "Teldrassil"}, "#/quests?zone=Teldrassil")
        self.assertIn('href="#/quests/457?zone=Teldrassil"', html)
        got = run(
            "views/quests.js",
            "const c = ctx({id: '457'}, {zone: 'Teldrassil'}, {'/api/v2/quests/457': %s});\n"
            "console.log(JSON.stringify({reads: V.reads(c), title: V.title(c), html: V.render(c).s}));"
            % json.dumps(ATTEMPTS),
            "#/quests/457?zone=Teldrassil",
        )
        self.assertEqual(got["reads"], ["/api/v2/quests/457"])
        html = got["html"]
        self.assertIn("Webwood Venom", html)
        self.assertIn("2 attempts", html)
        self.assertIn("#/m/Tharn/quests", html)
        self.assertIn("The spiders never drop the sac.", html)
        self.assertIn('href="https://example.com/tickets/940"', html)
        self.assertIn("Ticket #940", html)
        # A broken attempt with no reason says so; a ticket that is not a web
        # link is not drawn as one.
        self.assertIn("no reason recorded", html)
        self.assertNotIn("javascript:", html)
        self.assertIn('href="#/quests?zone=Teldrassil"', html)

    def test_a_quest_the_server_does_not_know_says_so(self):
        got = run(
            "views/quests.js",
            "const c = ctx({id: '9'}, {}, {'/api/v2/quests/9': {error: 'no such quest'}});\n"
            "console.log(JSON.stringify(V.render(c).s));",
        )
        self.assertIn("This quest was not found", got)
        self.assertIn("no such quest", got)

    def test_the_controls_narrow_the_list_and_bind_once_after_a_redraw(self):
        # The view's handlers look up their elements on `main`, not on the
        # global document, so this `main` answers with stand-in elements. A
        # write to .qs-catalogue makes new ones, as the browser's innerHTML does.
        got = run(
            "views/quests.js",
            "let els = {}, writes = 0;\n"
            "function el() {\n"
            "  const ls = {};\n"
            "  return {value: '', focus() {}, addEventListener(k, f) { (ls[k] = ls[k] || []).push(f); },\n"
            "    fire(k, e) { (ls[k] || []).forEach((f) => f(e || {})); }};\n"
            "}\n"
            "function fresh() {\n"
            "  els = {};\n"
            "  for (const id of ['qs-q', 'qs-faction', 'qs-zone', 'qs-status', 'qs-lo', 'qs-hi']) els['#' + id] = el();\n"
            "  const r = el(); let h = '';\n"
            "  Object.defineProperty(r, 'innerHTML', {get: () => h, set: (v) => { h = v; writes++; }});\n"
            "  els['[data-region=catalogue]'] = r;\n"
            "}\n"
            "fresh();\n"
            "const cat = {set innerHTML(_v) { fresh(); }};\n"
            "const main = {querySelector: (s) => (s === '.qs-catalogue' ? cat : els[s] || null)};\n"
            "const c = ctx({}, {}, %s);\n"
            "V.after(main, c);\n"
            "const list = () => els['[data-region=catalogue]'].innerHTML;\n"
            "els['#qs-q'].value = 'venom'; els['#qs-q'].fire('input');\n"
            "const searched = [list(), location.hash];\n"
            "els['#qs-faction'].value = 'Horde'; els['#qs-faction'].fire('change');\n"
            "els['#qs-q'].value = ''; writes = 0; els['#qs-q'].fire('input');\n"
            "const typed = writes, faction = [list(), location.hash];\n"
            "els['#qs-faction'].value = ''; els['#qs-faction'].fire('change');\n"
            "els['#qs-faction'].value = 'Horde'; els['#qs-faction'].fire('change');\n"
            "writes = 0; els['#qs-status'].value = 'completed'; els['#qs-status'].fire('change');\n"
            "console.log(JSON.stringify({searched, faction, typed, again: writes, status: list()}));"
            % json.dumps(READS),
        )
        html, hash_ = got["searched"]
        self.assertIn("1 of 5 quests", html)
        self.assertIn("#/quests/457?", html)
        self.assertIn("q=venom", hash_)
        html, hash_ = got["faction"]
        self.assertIn("3 of 5 quests", html)
        self.assertIn("faction=Horde", hash_)
        # One keystroke after a redraw writes the list once, however many
        # times the controls were drawn again before it.
        self.assertEqual(got["typed"], 1)
        self.assertEqual(got["again"], 1)
        self.assertIn("1 of 5 quests", got["status"])
        self.assertIn("#/quests/788?", got["status"])

    def test_the_list_click_binds_once_on_the_new_region_after_a_redraw(self):
        many = dict(
            QUESTS,
            quests=[
                quest(i, "Quest %d" % i, "Horde", "Durotar", 1, "not_reached")
                for i in range(1, 251)
            ],
        )
        # Two faction changes and a Clear each rewrite the controls and the
        # list region. One Show more click on the region drawn last must grow
        # the list by one step, not by one step per redraw.
        got = run(
            "views/quests.js",
            "let els = {};\n"
            "function el() {\n"
            "  const ls = {};\n"
            "  return {value: '', focus() {}, addEventListener(k, f) { (ls[k] = ls[k] || []).push(f); },\n"
            "    fire(k, e) { (ls[k] || []).forEach((f) => f(e || {})); }};\n"
            "}\n"
            "function fresh() {\n"
            "  els = {};\n"
            "  for (const id of ['qs-q', 'qs-faction', 'qs-zone', 'qs-status', 'qs-lo', 'qs-hi']) els['#' + id] = el();\n"
            "  const r = el(); let h = '';\n"
            "  Object.defineProperty(r, 'innerHTML', {get: () => h, set: (v) => { h = v; }});\n"
            "  els['[data-region=catalogue]'] = r;\n"
            "}\n"
            "fresh();\n"
            "const cat = {set innerHTML(_v) { fresh(); }};\n"
            "const main = {querySelector: (s) => (s === '.qs-catalogue' ? cat : els[s] || null)};\n"
            "const c = ctx({}, {}, %s);\n"
            "V.after(main, c);\n"
            "const region = () => els['[data-region=catalogue]'];\n"
            "const hit = (sel) => ({target: {closest: (s) => (s === sel ? {} : null)}});\n"
            "els['#qs-faction'].value = 'Horde'; els['#qs-faction'].fire('change');\n"
            "els['#qs-faction'].value = ''; els['#qs-faction'].fire('change');\n"
            "region().fire('click', hit('[data-clear]'));\n"
            "region().fire('click', hit('[data-more]'));\n"
            "console.log(JSON.stringify(region().innerHTML));"
            % json.dumps({"/api/v2/quests": many}),
        )
        self.assertIn("250 of 250 quests, the first 200 shown", got)
        self.assertIn("Show 50 more", got)

    def test_one_click_grows_the_list_once_however_the_two_redraws_alternate(self):
        many = dict(
            QUESTS,
            quests=[
                quest(i, "Quest %d" % i, "Horde", "Durotar", 1, "not_reached")
                for i in range(1, 251)
            ],
        )
        # A plain redraw (a keystroke) and a controls redraw (a faction, a Clear)
        # alternate here, the way a user's hands alternate. The first writes the
        # region it already has; the second replaces that region with a new one.
        # However often they alternate, the region on screen carries one click
        # handler and one Show more grows the list by one step, and the count
        # line agrees with the rows drawn under it.
        got = run(
            "views/quests.js",
            "let els = {}, made = 0;\n"
            "function el() {\n"
            "  const ls = {};\n"
            "  return {made: ++made, value: '', focus() {}, addEventListener(k, f) { (ls[k] = ls[k] || []).push(f); },\n"
            "    fire(k, e) { (ls[k] || []).forEach((f) => f(e || {})); }, handlers(k) { return (ls[k] || []).length; }};\n"
            "}\n"
            "function fresh() {\n"
            "  els = {};\n"
            "  for (const id of ['qs-q', 'qs-faction', 'qs-zone', 'qs-status', 'qs-lo', 'qs-hi']) els['#' + id] = el();\n"
            "  const r = el(); let h = '';\n"
            "  Object.defineProperty(r, 'innerHTML', {get: () => h, set: (v) => { h = v; }});\n"
            "  els['[data-region=catalogue]'] = r;\n"
            "}\n"
            "fresh();\n"
            "const cat = {set innerHTML(_v) { fresh(); }};\n"
            "const main = {querySelector: (s) => (s === '.qs-catalogue' ? cat : els[s] || null)};\n"
            "const c = ctx({}, {}, %s);\n"
            "V.after(main, c);\n"
            "const region = () => els['[data-region=catalogue]'];\n"
            "const hit = (sel) => ({target: {closest: (s) => (s === sel ? {} : null)}});\n"
            "const type = (v) => { els['#qs-q'].value = v; els['#qs-q'].fire('input'); };\n"
            "const step = () => {\n"
            "  const h = region().innerHTML, m = /the first (\\d+) shown/.exec(h);\n"
            "  return [region().made, region().handlers('click'), (h.match(/qs-title/g) || []).length,\n"
            "    m ? Number(m[1]) : 0, h.indexOf('data-more') !== -1];\n"
            "}\n"
            "const where = [];\n"
            "type('Quest'); where.push(step());\n"
            "els['#qs-faction'].value = 'Horde'; els['#qs-faction'].fire('change');\n"
            "type(''); where.push(step());\n"
            "els['#qs-faction'].value = ''; els['#qs-faction'].fire('change');\n"
            "type(''); where.push(step());\n"
            "region().fire('click', hit('[data-clear]')); type(''); where.push(step());\n"
            "region().fire('click', hit('[data-more]')); const first = step();\n"
            "region().fire('click', hit('[data-more]')); const second = step();\n"
            "console.log(JSON.stringify({where, first, second}));" % json.dumps({"/api/v2/quests": many}),
        )
        for _, handlers, rows, said, more in got["where"]:
            self.assertEqual(handlers, 1)
            self.assertEqual(rows, 100)
            # The count line is drawn by the same call as the rows, so the two
            # can never disagree, whatever ran before this one.
            self.assertEqual(said, rows)
            self.assertTrue(more)
        # Each controls redraw left the region on screen a new element.
        drawn = [w[0] for w in got["where"]]
        self.assertEqual(len(set(drawn)), len(drawn))
        self.assertEqual(got["first"][1:], [1, 200, 200, True])
        self.assertEqual(got["second"][1:], [1, 250, 0, False])

    def test_a_quest_read_with_no_entry_yet_shows_skeletons(self):
        # The cache can answer a read it has never started with nothing at
        # all; the quest page waits on it rather than reading into it.
        got = run(
            "views/quests.js",
            "const c = ctx({id: '9'}, {}, {});\n"
            "c.get = () => null;\n"
            "console.log(JSON.stringify(V.render(c).s));",
        )
        self.assertIn("skeleton", got)
        self.assertNotIn("not found", got)

    def test_before_the_reads_answer_it_shows_skeletons(self):
        got = run(
            "views/quests.js",
            "console.log(JSON.stringify(V.render(ctx({}, {}, {})).s));",
        )
        self.assertIn("skeleton", got)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheQuestsRoute(unittest.TestCase):
    def test_the_nav_lists_quests(self):
        got = run(
            "shell.js",
            "console.log(JSON.stringify(M.NAV.map((n) => [n.key, n.href])));",
        )
        self.assertIn(["quests", "#/quests"], got)

    def test_quests_and_one_quest_resolve(self):
        got = run(
            "router.js",
            "const r = (h) => M.resolve(M.parse(h));\n"
            'console.log(JSON.stringify([r("#/quests"), r("#/quests?status=broken"), r("#/quests/457"), r("#/quests/457/x"), M.SECTIONS]));',
        )
        self.assertEqual(got[0], {"view": "quests", "section": "quests", "params": {}})
        self.assertEqual(got[1]["view"], "quests")
        self.assertEqual(
            got[2], {"view": "quests", "section": "quests", "params": {"id": "457"}}
        )
        self.assertEqual(got[3], {"redirect": "#/quests/457"})
        self.assertIn("quests", got[4])


if __name__ == "__main__":
    unittest.main()

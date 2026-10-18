"""The Quests view (app/views/quests.js), rendered under node from canned
reads: the quester parties, the coverage and the catalogue from the three
quest reads, the filters and search that narrow the catalogue, and the page a
row opens with that quest's attempts. The nav and the route too.
"""

import datetime
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import questcatalogue as qc  # noqa: E402
import questledger as ql  # noqa: E402
import questlog  # noqa: E402
from apiv2 import quests as v2quests  # noqa: E402

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


# The fixtures are the server's own payloads: apiv2/quests.py builds them
# from canned rows, so the view is tested against the shapes it is served.
# The first version of this view read imagined shapes (parties,
# totals.factions) and its tests passed on fixtures in those same shapes, while
# the live page showed no questers at all (#1129).

WHEN = datetime.datetime(2026, 10, 13, 9, 30, 0)


def catalogue_quest(id_, title, faction, zone, level):
    return qc.Quest(
        id=id_,
        title=title,
        level=level,
        min_level=max(1, level - 2),
        zone=zone,
        zone_name=qc.zone_name(zone),
        faction=faction,
        races=0,
        classes=0,
        follows=0,
    )


TELDRASSIL, DUROTAR, BARRENS, ELWYNN = 141, 14, 17, 12
CATALOGUE = (
    catalogue_quest(456, "The Balance of Nature", qc.ALLIANCE, TELDRASSIL, 1),
    catalogue_quest(457, "Webwood Venom", qc.ALLIANCE, TELDRASSIL, 4),
    catalogue_quest(788, "Cutting Teeth", qc.HORDE, DUROTAR, 1),
    catalogue_quest(792, "Vile Familiars", qc.HORDE, DUROTAR, 3),
    catalogue_quest(835, "Securing the Lines", qc.HORDE, DUROTAR, 9),
    catalogue_quest(870, "The Forgotten Pools", qc.BOTH, BARRENS, 14),
)
# quest -> the ledger states its attempts ended in.
ATTEMPTED = {
    456: [ql.COMPLETED],
    457: [ql.BROKEN, ql.BROKEN],
    788: [ql.COMPLETED],
    835: [ql.ABANDONED],
    870: [ql.TAKEN],
}


def ledger_counts(attempted):
    return [
        {"quest": q, "state": state, "n": states.count(state)}
        for q, states in attempted.items()
        for state in sorted(set(states))
    ]


def quests_payload(catalogue=CATALOGUE, attempted=None):
    return v2quests.build_quests(
        catalogue, ledger_counts(ATTEMPTED if attempted is None else attempted)
    )


# Every quester is on the realm but Fizzik, who has not been recruited yet.
# Tharn has two quests in its log; Grakk stands in no zone the server names.
GUIDS = {name: 100 + i for i, name in enumerate(ql.quester_names())}
CHARACTERS = [
    {
        "guid": guid,
        "name": name,
        "level": 2,
        "race": 1,
        "class": 1,
        "zone": ELWYNN if ql.guild_of(name) == "Cave" else DUROTAR,
        "online": 1,
    }
    for name, guid in GUIDS.items()
    if name != "Fizzik"
]
for row in CHARACTERS:
    if row["name"] == "Tharn":
        row.update(level=6, zone=TELDRASSIL)
    if row["name"] == "Grakk":
        row.update(zone=0)
LOG = [
    {"guid": GUIDS["Tharn"], "quest": 456, "status": questlog.COMPLETE},
    {"guid": GUIDS["Tharn"], "quest": 457, "status": questlog.INCOMPLETE},
]
COUNTS = [
    {"guid": GUIDS["Tharn"], "state": ql.COMPLETED, "n": 4},
    {"guid": GUIDS["Tharn"], "state": ql.BROKEN, "n": 1},
]
QUESTERS = v2quests.build_questers(
    CHARACTERS, LOG, COUNTS, {q.id: q.title for q in CATALOGUE}
)
QUESTS = quests_payload()


def attempt(name, state, reason="", finished=WHEN):
    return {
        "quest": 457,
        "guid": GUIDS[name],
        "character_name": name,
        "state": state,
        "first_taken": WHEN,
        "finished": finished,
        "reason": reason,
    }


ATTEMPTS = v2quests.build_quest(
    CATALOGUE[1],
    [
        attempt("Tharn", ql.BROKEN, "The spiders never drop the sac."),
        attempt("Mirra", ql.BROKEN, "", None),
    ],
)


def many_quests(n=250):
    return quests_payload(
        tuple(
            catalogue_quest(i, "Quest %d" % i, qc.HORDE, DUROTAR, 1)
            for i in range(1, n + 1)
        ),
        {},
    )


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

    def test_the_parties_draw_every_quester_the_server_lists(self):
        _, html = self.page()
        names = [m["name"] for m in QUESTERS["questers"]]
        self.assertEqual(names, ql.quester_names())
        for name in names:
            self.assertIn("#/m/%s/quests" % name, html)
        self.assertEqual(html.count('class="card qs-quester"'), len(names))
        # One party per guild, in the order the server lists them.
        self.assertIn('aria-label="Cave questers"', html)
        self.assertIn('aria-label="Bonkers questers"', html)
        self.assertLess(html.index("Cave questers"), html.index("Bonkers questers"))
        self.assertIn(
            "%d questers" % sum(ql.guild_of(n) == "Cave" for n in names), html
        )

    def test_a_quester_card_has_level_zone_current_quests_and_counts(self):
        _, html = self.page()
        tharn = html[html.index('href="#/m/Tharn/quests"') :]
        tharn = tharn[: tharn.index('class="card qs-quester"')]
        self.assertIn("L6", tharn)
        self.assertIn("Teldrassil", tharn)
        self.assertIn('href="#/quests/456"', tharn)
        self.assertIn('href="#/quests/457"', tharn)
        self.assertIn("Webwood Venom", tharn)
        self.assertIn("4 completed", tharn)
        self.assertIn("1 broken", tharn)
        # A quester not on the realm yet says so; a zone the server cannot
        # name is not measured; an empty log is no quest, never a blank.
        fizzik = html[html.index('href="#/m/Fizzik/quests"') :]
        self.assertIn("not on the realm yet", fizzik[: fizzik.index("</div>")])
        grakk = html[html.index('href="#/m/Grakk/quests"') :]
        grakk = grakk[: grakk.index('class="card qs-quester"')]
        self.assertIn("zone not measured", grakk)
        self.assertIn("no quest on", grakk)

    def test_coverage_counts_each_faction_and_zone(self):
        _, html = self.page()
        self.assertIn(
            'aria-label="1 completed, 0 broken, 1 taken, 1 abandoned,'
            ' 1 not reached of 4"',
            html,
        )
        self.assertIn(
            'aria-label="1 completed, 1 broken, 1 taken, 0 abandoned,'
            ' 0 not reached of 3"',
            html,
        )
        self.assertIn('href="#/quests?faction=horde"', html)
        self.assertIn(">Horde</a>", html)
        self.assertIn(">Alliance</a>", html)
        # Per zone, counted off the catalogue the same read sends.
        self.assertIn("3 zones", html)
        self.assertIn('href="#/quests?zone=Durotar"', html)
        self.assertIn('href="#/quests?zone=The%20Barrens"', html)
        self.assertIn(
            'aria-label="1 completed, 0 broken, 0 taken, 1 abandoned,'
            ' 1 not reached of 3"',
            html,
        )
        self.assertIn("2 quests completed and 1 found broken, of 6.", html)

    def test_coverage_bar_stays_within_its_track_when_totals_disagree(self):
        quests = json.loads(json.dumps(QUESTS))
        quests["by_faction"]["alliance"].update(
            completed=8, broken=4, taken=0, abandoned=0, not_reached=8, quests=10
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
        self.assertIn("6 of 6 quests", html)
        for q in QUESTS["quests"]:
            self.assertIn(q["title"], html)
            self.assertIn('href="#/quests/%d"' % q["id"], html)
        for word in ("Completed", "Broken", "Taken", "Abandoned", "Not reached"):
            self.assertIn(word, html)
        # The zone and side read as words, never as an area id or a key.
        self.assertIn("L4 | Teldrassil | Alliance", html)
        self.assertIn("L14 | The Barrens | Both sides", html)
        self.assertIn("qs-table", html)
        self.assertIn("qs-qcards", html)

    def test_filters_and_search_narrow_the_catalogue(self):
        cases = [
            # A side keeps its own quests and the ones both sides take, as
            # the server's own faction filter does.
            ("faction=horde", {"faction": "horde"}, {788, 792, 835, 870}),
            ("faction=alliance", {"faction": "alliance"}, {456, 457, 870}),
            ("zone=Teldrassil", {"zone": "Teldrassil"}, {456, 457}),
            ("status=broken", {"status": "broken"}, {457}),
            ("status=taken", {"status": "taken"}, {870}),
            ("status=abandoned", {"status": "abandoned"}, {835}),
            ("lvl=3-5", {"lvl": "3-5"}, {457, 792}),
            ("lvl=5-", {"lvl": "5-"}, {835, 870}),
            ("q=venom", {"q": "venom"}, {457}),
            ("q=barrens", {"q": "barrens"}, {870}),
            (
                "faction+status",
                {"faction": "horde", "status": "not_reached", "lvl": "-4"},
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
            self.assertIn("%d of 6 quests" % len(ids), html, label)

    def test_search_skips_the_fields_the_server_did_not_send(self):
        got = run(
            "views/quests.js",
            "const x = {id: 1, title: 'Lost Letter', zone: 12, zone_name: null};\n"
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
        _, html = self.page({"faction": "horde"}, "#/quests?faction=horde")
        zone_select = html[html.index('id="qs-zone"') :]
        zone_select = zone_select[: zone_select.index("</select>")]
        self.assertIn("Durotar", zone_select)
        self.assertIn("The Barrens", zone_select)
        self.assertNotIn("Teldrassil", zone_select)

    def test_a_long_catalogue_grows_on_request(self):
        many = many_quests()
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
        many = many_quests()
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

    def test_a_zone_or_side_with_markup_stays_text(self):
        odd = catalogue_quest(1, "Odd", 'horde"><b>', DUROTAR, 1)
        odd = qc.Quest(**dict(odd.__dict__, zone_name="<img src=x onerror=alert(1)>"))
        hostile = quests_payload((odd,), {})
        reads = dict(READS, **{"/api/v2/quests": hostile})
        got = run(
            "views/quests.js",
            "console.log(JSON.stringify(V.render(ctx({}, {}, %s)).s));"
            % json.dumps(reads),
        )
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
        self.assertIn("L4 | Teldrassil | Alliance", html)
        self.assertIn("2 attempts", html)
        self.assertIn("#/m/Tharn/quests", html)
        self.assertIn("#/m/Mirra/quests", html)
        self.assertIn("Cave", html)
        self.assertIn("finished ", html)
        self.assertIn("taken ", html)
        self.assertIn("The spiders never drop the sac.", html)
        # A broken attempt with no reason says so.
        self.assertIn("no reason recorded", html)
        self.assertNotIn("quester not measured", html)
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
            "els['#qs-faction'].value = 'horde'; els['#qs-faction'].fire('change');\n"
            "els['#qs-q'].value = ''; writes = 0; els['#qs-q'].fire('input');\n"
            "const typed = writes, faction = [list(), location.hash];\n"
            "els['#qs-faction'].value = ''; els['#qs-faction'].fire('change');\n"
            "els['#qs-faction'].value = 'horde'; els['#qs-faction'].fire('change');\n"
            "writes = 0; els['#qs-status'].value = 'completed'; els['#qs-status'].fire('change');\n"
            "console.log(JSON.stringify({searched, faction, typed, again: writes, status: list()}));"
            % json.dumps(READS),
        )
        html, hash_ = got["searched"]
        self.assertIn("1 of 6 quests", html)
        self.assertIn("#/quests/457?", html)
        self.assertIn("q=venom", hash_)
        html, hash_ = got["faction"]
        self.assertIn("4 of 6 quests", html)
        self.assertIn("faction=horde", hash_)
        # One keystroke after a redraw writes the list once, however many
        # times the controls were drawn again before it.
        self.assertEqual(got["typed"], 1)
        self.assertEqual(got["again"], 1)
        self.assertIn("1 of 6 quests", got["status"])
        self.assertIn("#/quests/788?", got["status"])

    def test_the_list_click_binds_once_on_the_new_region_after_a_redraw(self):
        many = many_quests()
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
            "els['#qs-faction'].value = 'horde'; els['#qs-faction'].fire('change');\n"
            "els['#qs-faction'].value = ''; els['#qs-faction'].fire('change');\n"
            "region().fire('click', hit('[data-clear]'));\n"
            "region().fire('click', hit('[data-more]'));\n"
            "console.log(JSON.stringify(region().innerHTML));"
            % json.dumps({"/api/v2/quests": many}),
        )
        self.assertIn("250 of 250 quests, the first 200 shown", got)
        self.assertIn("Show 50 more", got)

    def test_one_click_grows_the_list_once_however_the_two_redraws_alternate(self):
        many = many_quests()
        # A plain redraw (a keystroke) and a controls redraw (a faction, a Clear)
        # alternate here, the way a user's hands alternate. The first writes the
        # region it already has; the second replaces that region with a new one.
        # However often they alternate, the region on screen carries one click
        # handler and one Show more grows the list by one step, and the count
        # line agrees with the rows drawn under it.
        got = run(
            "views/quests.js",
            "let els = {}, regions = 0;\n"
            "function el() {\n"
            "  const ls = {};\n"
            "  return {value: '', focus() {}, addEventListener(k, f) { (ls[k] = ls[k] || []).push(f); },\n"
            "    fire(k, e) { (ls[k] || []).forEach((f) => f(e || {})); }, handlers(k) { return (ls[k] || []).length; }};\n"
            "}\n"
            "function fresh() {\n"
            "  els = {};\n"
            "  for (const id of ['qs-q', 'qs-faction', 'qs-zone', 'qs-status', 'qs-lo', 'qs-hi']) els['#' + id] = el();\n"
            "  const r = el(); let h = '';\n"
            "  Object.defineProperty(r, 'innerHTML', {get: () => h, set: (v) => { h = v; }});\n"
            "  r.stamp = ++regions;\n"
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
            "  return [region().stamp, region().handlers('click'), (h.match(/qs-title/g) || []).length,\n"
            "    m ? Number(m[1]) : 0, h.indexOf('data-more') !== -1];\n"
            "}\n"
            "const where = [];\n"
            "type('Quest'); where.push(step());\n"
            "els['#qs-faction'].value = 'horde'; els['#qs-faction'].fire('change');\n"
            "type(''); where.push(step());\n"
            "els['#qs-faction'].value = ''; els['#qs-faction'].fire('change');\n"
            "type(''); where.push(step());\n"
            "region().fire('click', hit('[data-clear]')); type(''); where.push(step());\n"
            "region().fire('click', hit('[data-more]')); const first = step();\n"
            "region().fire('click', hit('[data-more]')); const second = step();\n"
            "console.log(JSON.stringify({where, first, second}));"
            % json.dumps({"/api/v2/quests": many}),
        )
        for _, handlers, rows, said, more in got["where"]:
            self.assertEqual(handlers, 1)
            self.assertEqual(rows, 100)
            # The count line is drawn by the same call as the rows, so the two
            # can never disagree, whatever ran before this one.
            self.assertEqual(said, rows)
            self.assertTrue(more)
        # A plain redraw (a keystroke) keeps the region it has; a controls
        # redraw (a faction, a Clear) replaces it. A controls redraw that
        # reused the region instead is the only way a second handler could
        # land on it, so the stamp may only change on the second step.
        self.assertEqual([w[0] for w in got["where"]], [1, 2, 3, 4])
        # A Show more rewrites that region's contents in place: same region,
        # one handler, and the list grown by one step and then by all of it.
        self.assertEqual(got["first"], [4, 1, 200, 200, True])
        self.assertEqual(got["second"], [4, 1, 250, 0, False])

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

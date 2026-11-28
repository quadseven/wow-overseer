"""The gear feed groups changes and keeps visit times per page key."""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

# Drive the rendered form's public click handler from its actual HTML. The
# stub only supplies the browser's attribute decoding and storage boundary.
MARK_ACTION = r"""
const store = new Map([['overseer.gear-since.site', '1767266000000']]);
const ROOT_MARK = 'overseer.gear-since.v1:%2F:site';
const events = [];
Date.now = () => 1767268000000;
globalThis.window = {
    localStorage: {getItem: key => store.get(key) ?? null,
                   setItem: (key, value) => store.set(key, value)},
    dispatchEvent: event => { events.push(event.type); return true; },
    addEventListener: () => {},
    location: {reload: () => events.push('reload')},
};
function clickMarked(view, markup, ctx = {get: () => ({data: null})}) {
    const tag = markup.match(/<button [^>]*data-mark-seen[^>]*>/);
    if (!tag) return;
    const attrs = Object.fromEntries(Array.from(tag[0].matchAll(/(data-[\w-]+)="([^"]*)"/g),
        ([_, key, value]) => [key, value.replaceAll('&quot;', '"').replaceAll('&amp;', '&')]));
    let click = null;
    const button = {getAttribute: key => attrs[key] ?? null,
                    addEventListener: (_name, handler) => { click = handler; }};
    const main = {querySelector: () => null,
                  querySelectorAll: selector => selector === '[data-mark-seen]' ? [button] : []};
    view.after(main, ctx);
    if (click) click();
}
"""


class TestGearChangesView(unittest.TestCase):
    def test_feed_items_are_tooltip_links_and_comparison_names_gains_and_losses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, root)
            (root / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            module = (root / "views/gearchanges.js").as_uri()
            code = (
                "globalThis.document = {querySelector: () => null, addEventListener: () => {}}; const V = await import(%s); const row = {kind:'worn', item:'New blade', entry:22, "
                "quality:3, replaced:'Old blade', prior_entry:11, prior_quality:2, "
                "item_level:30, item_level_change:2, at:'now'}; "
                "const html = String(V.renderFeed({changes:[row]}, 'site')); "
                "const diff = V.compareItems({tooltip:{item_level:28, armor:4, damage:{dps:8}, stats:['+5 Stamina','+2 Agility']}}, "
                "{tooltip:{item_level:30, armor:9, damage:{dps:6}, stats:['+1 Agility','+7 Stamina']}}); "
                "process.stdout.write(JSON.stringify({html, diff}));"
            ) % json.dumps(module)
            result = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", code],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        got = json.loads(result.stdout)
        self.assertIn('data-item="22"', got["html"])
        self.assertIn('data-item="11"', got["html"])
        self.assertIn("+2 item level", got["diff"])
        self.assertIn("+5 Armor", got["diff"])
        self.assertIn("-2 DPS", got["diff"])
        self.assertIn("+2 Stamina", got["diff"])
        self.assertIn("-1 Agility", got["diff"])
        self.assertIn('data-compare="11,22"', got["html"])

    def test_an_unchanged_item_says_no_stat_changes(self):
        same = {
            "tooltip": {
                "item_level": 30,
                "armor": 9,
                "damage": {"dps": 6},
                "stats": ["+7 Stamina"],
            }
        }
        got = self._run_view(
            "process.stdout.write(JSON.stringify(V.compareItems(%s, %s)));"
            % (json.dumps(same), json.dumps(same))
        )
        self.assertEqual(got, "No stat changes")

    def test_a_failed_comparison_says_unavailable_instead_of_loading_forever(self):
        # Entry 1 answers with a stats field that is not a list, entry 2 fails
        # with a 500, entry 3 cannot be reached at all. Every span must leave
        # "Loading stat changes" and no promise may be left unhandled.
        code = (
            "const unhandled = []; process.on('unhandledRejection', (err) => unhandled.push(String(err)));\n"
            "console.warn = () => {};\n"
            "globalThis.fetch = async (url) => {\n"
            "  if (url.endsWith('entry=3')) throw new Error('network down');\n"
            "  if (url.endsWith('entry=2')) return {ok: false, status: 500, text: async () => ''};\n"
            "  const body = url.endsWith('entry=1') ? {tooltip: {stats: 5}} : {tooltip: {stats: ['+1 Stamina']}};\n"
            "  return {ok: true, status: 200, text: async () => JSON.stringify(body)};\n"
            "};\n"
            "const nodes = ['1,9', '2,9', '3,9'].map((pair) => ({textContent: 'Loading stat changes', "
            "getAttribute: () => pair}));\n"
            "const main = {querySelectorAll: (sel) => sel === '[data-compare]' ? nodes : []};\n"
            "V.default.after(main);\n"
            "await new Promise((done) => setTimeout(done, 200));\n"
            "process.stdout.write(JSON.stringify({text: nodes.map((n) => n.textContent), unhandled}));\n"
        )
        got = self._run_view(code)
        self.assertEqual(got["text"], ["Stat changes unavailable"] * 3)
        self.assertEqual(got["unhandled"], [])

    def _run_view(self, body, mount=""):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, root)
            (root / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            module = (root / "views/gearchanges.js").as_uri()
            code = (
                "const mount = %s;\n"
                "globalThis.document = {querySelector: selector => selector === 'meta[name=\"overseer-base\"]' "
                "? {getAttribute: () => mount} : null, addEventListener: () => {}};\n"
                "globalThis.window = {sessionStorage: {getItem: () => null, setItem: () => {}}};\n"
                "const viewUrl = %s; const V = await import(viewUrl);\n"
            ) % (json.dumps(mount), json.dumps(module)) + body
            result = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", code],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def _row(self, **kw):
        row = {
            "character": "Jug",
            "guild": "Rumble",
            "kind": "worn",
            "entry": 100,
            "item": "Boots of the Fang",
            "quality": 3,
            "item_level": 45,
            "replaced": "Ragged Leather Boots",
            "prior_entry": 90,
            "prior_quality": 2,
            "prior_item_level": 39,
            "item_level_change": 6,
            "at": "2026-01-01 10:00:00",
        }
        row.update(kw)
        return row

    def _changes(self):
        return [
            self._row(),
            self._row(item="Worn Shortsword", item_level=40, item_level_change=-4),
            self._row(
                kind="looted",
                item="Thick Hide Belt",
                replaced="not recorded",
                prior_entry=None,
                prior_quality=None,
                prior_item_level=None,
                item_level_change=None,
            ),
            self._row(character="Grug", guild="Cave", item_level_change=2),
            self._row(character="Grug", guild="Cave", kind="looted", item="Gold Bar"),
            self._row(
                character="Og",
                guild="Cave",
                replaced="was empty",
                prior_entry=None,
                prior_quality=None,
                prior_item_level=None,
                item_level_change=None,
            ),
        ]

    def test_the_head_counts_equips_upgrades_loot_and_members(self):
        changes = self._changes()
        code = (
            "const changes = %s;\n"
            "const html = String(V.renderFeed({changes}, 'site'));\n"
            "process.stdout.write(JSON.stringify({html, counts: V.summarize(changes)}));\n"
        ) % json.dumps(changes)
        got = self._run_view(code)
        self.assertEqual(
            got["counts"], {"equips": 4, "upgrades": 2, "looted": 2, "members": 3}
        )
        self.assertIn("4 equips, 2 upgrades, 2 looted, 3 members", got["html"])
        self.assertIn("Since ", got["html"])
        self.assertNotRegex(got["html"], r"\d{4}-\d{2}-\d{2}T")

    def test_rows_carry_a_toned_rail_a_delta_chip_and_a_relative_time(self):
        import datetime

        two_hours_ago = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        ).strftime("%Y-%m-%d %H:%M:%S")
        changes = [
            self._row(at=two_hours_ago),
            self._row(item="Worn Shortsword", item_level=40, item_level_change=-4),
            self._row(
                kind="looted",
                item="Thick Hide Belt",
                replaced="not recorded",
                prior_entry=None,
                prior_quality=None,
                prior_item_level=None,
                item_level_change=None,
            ),
        ]
        code = (
            "const changes = %s;\n"
            "process.stdout.write(JSON.stringify(String(V.renderFeed({changes}, 'site'))));\n"
        ) % json.dumps(changes)
        html = self._run_view(code)
        self.assertIn("gc-rail ok", html)
        self.assertIn("+6 iLvl", html)
        self.assertIn("replaced", html)
        self.assertIn("(ilvl 39)", html)
        self.assertIn("2h ago", html)
        self.assertIn("gc-rail bad", html)
        self.assertIn("-4 iLvl", html)
        self.assertIn("a downgrade", html)
        self.assertIn("Not recorded as worn", html)
        self.assertNotIn("2026-01-01 10:00:00", html)

    def test_an_upgrade_row_never_calls_itself_a_downgrade(self):
        changes = [self._row()]
        code = (
            "const changes = %s;\n"
            "process.stdout.write(JSON.stringify(String(V.renderFeed({changes}, 'site'))));\n"
        ) % json.dumps(changes)
        html = self._run_view(code)
        self.assertNotIn("a downgrade", html)

    def test_loot_rows_have_no_stat_comparison_and_a_neutral_rail(self):
        changes = [
            self._row(
                kind="looted",
                item="Thick Hide Belt",
                replaced="not recorded",
                prior_entry=None,
                prior_quality=None,
                prior_item_level=None,
                item_level_change=None,
            )
        ]
        code = (
            "const changes = %s;\n"
            "process.stdout.write(JSON.stringify(String(V.renderFeed({changes}, 'site'))));\n"
        ) % json.dumps(changes)
        html = self._run_view(code)
        self.assertIn('class="gc-rail"', html)
        self.assertIn(">looted<", html)
        self.assertNotIn("data-compare", html)

    def test_member_headers_link_and_carry_guild_and_count(self):
        changes = self._changes()
        code = (
            "const changes = %s;\n"
            "process.stdout.write(JSON.stringify(String(V.renderFeed({changes}, 'site'))));\n"
        ) % json.dumps(changes)
        html = self._run_view(code)
        self.assertIn('href="#/m/Jug"', html)
        self.assertIn("Rumble · 3 changes", html)
        self.assertIn("Cave · 2 changes", html)
        self.assertIn("Cave · 1 change", html)
        self.assertNotIn("<h2>Jug</h2>", html)

    def test_filters_default_to_worn_and_reject_unknown_kinds(self):
        code = (
            "process.stdout.write(JSON.stringify([V.filterFromQuery({}), "
            "V.filterFromQuery({kind: 'upgrades'}), V.filterFromQuery({kind: 'bogus'}), "
            "V.filterFromQuery({guild: 'Cave'})]));"
        )
        got = self._run_view(code)
        self.assertEqual(
            got,
            [
                {"kind": "worn", "guild": ""},
                {"kind": "upgrades", "guild": ""},
                {"kind": "worn", "guild": ""},
                {"kind": "worn", "guild": "Cave"},
            ],
        )

    def test_visible_keeps_only_the_filtered_kind_and_guild(self):
        changes = self._changes()
        code = (
            "const changes = %s;\n"
            "const names = (rows) => rows.map((r) => r.item);\n"
            "process.stdout.write(JSON.stringify({"
            "upgrades: names(V.visible(changes, {kind: 'upgrades', guild: ''})), "
            "looted: names(V.visible(changes, {kind: 'looted', guild: ''})), "
            "caveWorn: names(V.visible(changes, {kind: 'worn', guild: 'Cave'}))}));\n"
        ) % json.dumps(changes)
        got = self._run_view(code)
        self.assertEqual(got["upgrades"], ["Boots of the Fang", "Boots of the Fang"])
        self.assertEqual(got["looted"], ["Thick Hide Belt", "Gold Bar"])
        self.assertEqual(got["caveWorn"], ["Boots of the Fang", "Boots of the Fang"])

    def test_the_site_feed_renders_chips_and_shows_only_the_filtered_rows(self):
        changes = self._changes()
        code = (
            "const changes = %s;\n"
            "const looted = String(V.renderFeed({changes}, 'site', '', {kind: 'looted', guild: ''}));\n"
            "const worn = String(V.renderFeed({changes}, 'site', '', {kind: 'worn', guild: ''}));\n"
            "const plain = String(V.renderFeed({changes}, 'site'));\n"
            "process.stdout.write(JSON.stringify({looted, worn, plain}));\n"
        ) % json.dumps(changes)
        got = self._run_view(code)
        self.assertIn('data-gc-kind="looted" aria-pressed="true"', got["looted"])
        self.assertIn('data-gc-guild="Cave"', got["looted"])
        self.assertIn('data-gc-guild="Rumble"', got["looted"])
        self.assertIn("Thick Hide Belt", got["looted"])
        self.assertNotIn("Boots of the Fang", got["looted"])
        self.assertIn("Boots of the Fang", got["worn"])
        self.assertNotIn("Thick Hide Belt", got["worn"])
        self.assertNotIn("data-gc-kind", got["plain"])
        self.assertIn("Thick Hide Belt", got["plain"])

    def test_a_filter_that_matches_nothing_says_so(self):
        changes = [self._row(kind="looted", item="Thick Hide Belt")]
        code = (
            "const changes = %s;\n"
            "process.stdout.write(JSON.stringify(String(V.renderFeed({changes}, 'site', '', {kind: 'upgrades', guild: ''}))));\n"
        ) % json.dumps(changes)
        html = self._run_view(code)
        self.assertIn("No upgrades since then", html)

    def test_mark_seen_targets_the_newest_shown_change(self):
        import datetime

        changes = [
            self._row(at="2026-01-01 10:00:00", event_id="31", occurrences=1),
            self._row(at="2026-01-01 12:30:00", event_id="19", occurrences=2),
            self._row(at="2026-01-01 11:15:00", event_id="89", occurrences=1),
        ]
        newest_ms = int(
            datetime.datetime(
                2026, 1, 1, 12, 30, tzinfo=datetime.timezone.utc
            ).timestamp()
            * 1000
        )
        got = self._run_view(
            MARK_ACTION
            + "const changes = %s;\n" % json.dumps(changes)
            + "clickMarked(V.default, String(V.renderFeed({changes, limited: false}, 'site')));\n"
            + "process.stdout.write(store.get(ROOT_MARK));"
        )
        self.assertEqual(got, {"v": 1, "at": newest_ms, "seen": [["19", 2]]})

    def test_marking_an_empty_feed_does_not_hide_a_change_arriving_during_render(self):
        got = self._run_view(
            MARK_ACTION
            + "const before = String(V.renderFeed({changes: [], limited: false}, 'site'));\n"
            + "clickMarked(V.default, before);\n"
            + "process.stdout.write(JSON.stringify({stored: store.get('overseer.gear-since.site'), saved: store.has(ROOT_MARK), events}));"
        )
        self.assertEqual(got["stored"], "1767266000000")
        self.assertFalse(got["saved"])
        self.assertEqual(got["events"], [])

    def test_mark_seen_keeps_unseen_and_revised_older_ids_at_the_same_timestamp(self):
        at = "2026-01-01 12:30:00"
        shown = [
            self._row(event_id="19", occurrences=1, item="Already seen", at=at),
            self._row(event_id="17", occurrences=3, item="Old revision", at=at),
        ]
        refreshed = [
            shown[0],
            dict(shown[1], occurrences=4, item="Updated equipment"),
            self._row(event_id="12", occurrences=1, item="New arrival", at=at),
        ]
        got = self._run_view(
            MARK_ACTION
            + "const shown = %s; const refreshed = %s;\n"
            % (json.dumps(shown), json.dumps(refreshed))
            + "const before = V.default.reads()[0];\n"
            + "clickMarked(V.default, String(V.renderFeed({changes: shown, limited: false}, 'site')));\n"
            + "const url = V.default.reads()[0];\n"
            + "const after = String(V.renderFeed({changes: refreshed, limited: false}, 'site'));\n"
            + "const stale = String(V.renderFeed({changes: [{...shown[1], occurrences: 2}], limited: false}, 'site'));\n"
            + "process.stdout.write(JSON.stringify({before, url, after, stale, events}));"
        )
        self.assertEqual(
            got["before"],
            "/api/v2/gear/changes?since=2026-01-01T11%3A13%3A20.000Z&oldest_first=1",
        )
        self.assertIn("include_boundary=1", got["url"])
        self.assertNotIn("Already seen", got["after"])
        self.assertIn("Updated equipment", got["after"])
        self.assertIn("New arrival", got["after"])
        self.assertNotIn("Old revision", got["stale"])
        self.assertEqual(got["events"], ["overseer:redraw"])

    def test_mark_seen_stores_the_newest_change_and_redraws_in_place(self):
        changes = [
            self._row(event_id="19", occurrences=3, at="2026-01-01 12:30:00"),
        ]
        got = self._run_view(
            MARK_ACTION
            + "const changes = %s;\n" % json.dumps(changes)
            + "clickMarked(V.default, String(V.renderFeed({changes, limited: false}, 'site')));\n"
            + "process.stdout.write(JSON.stringify({stored: JSON.parse(store.get(ROOT_MARK)), events}));"
        )
        self.assertEqual(
            got["stored"], {"v": 1, "at": 1767270600000, "seen": [["19", 3]]}
        )
        self.assertEqual(got["events"], ["overseer:redraw"])

    def test_uncertain_coverage_leaves_the_marker_alone(self):
        good = self._row(event_id="19", occurrences=3, at="2026-01-01 12:30:00")
        got = self._run_view(
            MARK_ACTION
            + "const good = %s;\n" % json.dumps(good)
            + """const examples = [
                {changes: [good], limited: true},
                {changes: [good, {...good, event_id: ''}], limited: false},
                {changes: [good]},
            ];
            for (const data of examples) clickMarked(V.default, String(V.renderFeed(data, 'site')));
            process.stdout.write(JSON.stringify({stored: store.get('overseer.gear-since.site'), saved: store.has(ROOT_MARK), events}));
            """
        )
        self.assertEqual(got, {"stored": "1767266000000", "saved": False, "events": []})

    def test_prefixed_realm_does_not_adopt_or_overwrite_the_root_cursor(self):
        change = self._row(event_id="19", occurrences=1)
        got = self._run_view(
            MARK_ACTION
            + "const changes = [%s];\n" % json.dumps(change)
            + """const M = await import(new URL('../models/gearchanges.js', viewUrl));
            const before = M.since('site');
            clickMarked(V.default, String(V.renderFeed({changes, limited: false}, 'site')));
            process.stdout.write(JSON.stringify({before, after: M.since('site'), stores: Object.fromEntries(store)}));
            """,
            mount="/second-world",
        )
        self.assertEqual(got["before"], "2025-12-31T11:46:40.000Z")
        self.assertEqual(got["after"], "2026-01-01T10:00:00.000Z")
        self.assertEqual(got["stores"]["overseer.gear-since.site"], "1767266000000")
        self.assertIn("overseer.gear-since.v1:%2Fsecond-world:site", got["stores"])

    def test_root_keeps_the_versioned_cursor_when_an_old_tab_writes_its_marker(self):
        change = self._row(event_id="19", occurrences=1, at="2026-01-01 12:30:00")
        got = self._run_view(
            MARK_ACTION
            + "const changes = [%s];\n" % json.dumps(change)
            + """const M = await import(new URL('../models/gearchanges.js', viewUrl));
            const before = M.since('site');
            clickMarked(V.default, String(V.renderFeed({changes, limited: false}, 'site')));
            store.set('overseer.gear-since.site', '1767276000000');
            process.stdout.write(JSON.stringify({before, after: M.since('site'), url: V.default.reads()[0]}));
            """
        )
        self.assertEqual(got["before"], "2026-01-01T11:13:20.000Z")
        self.assertEqual(got["after"], "2026-01-01T12:30:00.000Z")
        self.assertIn("include_boundary=1", got["url"])

    def test_exact_limit_and_later_changes_remain_acknowledgeable(self):
        change = self._row(event_id="19", occurrences=1, at="2026-01-01 12:30:00")
        got = self._run_view(
            MARK_ACTION
            + "const row = %s;\n" % json.dumps(change)
            + """const M = await import(new URL('../models/gearchanges.js', viewUrl));
            const changes = Array.from({length: 500}, (_, i) => ({...row, event_id: String(i + 1)}));
            clickMarked(V.default, String(V.renderFeed({changes, limited: false}, 'site')));
            const prior = M.since('site');
            const next = {...row, event_id: '501', item: 'Later item', at: '2026-01-01 12:31:00'};
            const html = String(V.renderFeed({changes: [...changes, next], limited: false}, 'site'));
            clickMarked(V.default, html);
            process.stdout.write(JSON.stringify({prior, after: M.since('site'), events, html}));
            """
        )
        self.assertEqual(got["prior"], "2026-01-01T12:30:00.000Z")
        self.assertEqual(got["after"], "2026-01-01T12:31:00.000Z")
        self.assertEqual(got["events"], ["overseer:redraw", "overseer:redraw"])
        self.assertIn("Later item", got["html"])
        self.assertNotIn("Boots of the Fang", got["html"])

    def test_a_capped_batch_marks_only_the_complete_prefix(self):
        change = self._row(event_id="19", occurrences=1, at="2026-01-01 12:30:00")
        got = self._run_view(
            MARK_ACTION
            + "const complete = %s;\n" % json.dumps(change)
            + """const M = await import(new URL('../models/gearchanges.js', viewUrl));
            const partial = {...complete, event_id: '20', item: 'Partial cohort', at: '2026-01-01 12:31:00'};
            const batch = {limited: true, complete_through: complete.at, changes: [complete, partial]};
            const html = String(V.renderFeed(batch, 'site'));
            clickMarked(V.default, html);
            const remainder = String(V.renderFeed(batch, 'site'));
            const blocked = String(V.renderFeed({...batch, complete_through: null}, 'site'));
            process.stdout.write(JSON.stringify({seen: M.since('site'), events, html, remainder, blocked}));
            """
        )
        self.assertEqual(got["seen"], "2026-01-01T12:30:00.000Z")
        self.assertEqual(got["events"], ["overseer:redraw"])
        self.assertIn("Mark batch seen", got["html"])
        self.assertIn("Partial cohort", got["remainder"])
        self.assertNotIn("data-mark-seen", got["remainder"])
        self.assertIn("500 changes", got["blocked"])
        self.assertNotIn("data-mark-seen", got["blocked"])

    def test_malformed_timestamp_cannot_crash_or_advance_the_feed(self):
        good = self._row(event_id="19", occurrences=1)
        got = self._run_view(
            MARK_ACTION
            + "const good = %s;\n" % json.dumps(good)
            + """const malformed = {...good, event_id: '20', at: {toString: null}};
            const html = String(V.renderFeed({changes: [good, malformed], limited: false}, 'site'));
            clickMarked(V.default, html);
            process.stdout.write(JSON.stringify({html, events}));
            """
        )
        self.assertIn("Boots of the Fang", got["html"])
        self.assertNotIn("data-mark-seen", got["html"])
        self.assertEqual(got["events"], [])

    def test_member_gear_marks_only_its_current_read_without_reloading(self):
        changes = [
            self._row(event_id="19", occurrences=3, at="2026-01-01 12:30:00"),
        ]
        got = self._run_view(
            MARK_ACTION
            + "const changes = %s;\n" % json.dumps(changes)
            + """const member = await import(new URL('./member.js', viewUrl));
            const name = 'Jug';
            const ctx = {
                params: {tab: 'gear'},
                get: path => ({data: path.startsWith('/api/v2/gear/changes?')
                    ? {changes, limited: false} : undefined, loading: true}),
            };
            clickMarked(member.default, String(member.gearTab(ctx, {name})), ctx);
            process.stdout.write(JSON.stringify({
                stored: JSON.parse(store.get('overseer.gear-since.v1:%2F:member:jug')),
                site: store.get('overseer.gear-since.site'),
                url: member.readsFor(name, 'gear')[2], events,
            }));
            """
        )
        self.assertEqual(
            got["stored"], {"v": 1, "at": 1767270600000, "seen": [["19", 3]]}
        )
        self.assertEqual(got["site"], "1767266000000")
        self.assertIn("include_boundary=1&member=Jug", got["url"])
        self.assertEqual(got["events"], ["overseer:redraw"])

    def test_a_chip_click_refilters_the_feed_region_in_place(self):
        changes = self._changes()
        code = (
            "const changes = %s;\n"
            "globalThis.location = {hash: '#/gear-changes'};\n"
            "globalThis.history = {replaceState: (a, b, url) => { globalThis.location.hash = url; }};\n"
            "globalThis.window = {localStorage: {getItem: () => null, setItem: () => {}}, dispatchEvent: () => true};\n"
            "let clickFn = null;\n"
            "const region = {innerHTML: '', addEventListener: (ev, fn) => { clickFn = fn; }};\n"
            "const chip = {closest: () => chip, hasAttribute: (n) => n === 'data-gc-kind', getAttribute: () => 'looted'};\n"
            "const main = {querySelectorAll: (sel) => sel === '[data-region=gc-feed]' ? [region] : []};\n"
            "V.default.after(main, {get: () => ({data: {changes}})});\n"
            "clickFn({target: chip});\n"
            "process.stdout.write(JSON.stringify({html: region.innerHTML, hash: globalThis.location.hash}));\n"
        ) % json.dumps(changes)
        got = self._run_view(code)
        self.assertIn("Thick Hide Belt", got["html"])
        self.assertNotIn("Boots of the Fang", got["html"])
        self.assertIn("kind=looted", got["hash"])

    def test_the_stylesheet_is_written_on_tokens(self):
        css = (APP / "views/gearchanges.css").read_text(encoding="utf-8")
        self.assertNotIn("rem", css)
        for token in ("--fs-1", "--fs-2", "--space-3", "--ok", "--bad"):
            self.assertIn("var(" + token + ")", css)
        self.assertIn("position: sticky", css)
        self.assertIn(".gc-rail.ok", css)
        self.assertIn(".gc-rail.bad", css)

    def test_the_page_title_is_gear_changes(self):
        got = self._run_view("process.stdout.write(JSON.stringify(V.default.title()));")
        self.assertEqual(got, "Gear changes")

    def test_invalid_stored_times_fall_back_to_the_first_visit_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, root)
            (root / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            module = (root / "models/gearchanges.js").as_uri()
            code = (
                "const M = await import(%s); const now = 200000000;\n"
                "const values = ['-1', '', '1.5', '9007199254740992', '8640000000000001'];\n"
                "const got = values.map(value => M.since('key-' + value, {getItem: () => value}, now));\n"
                "process.stdout.write(JSON.stringify(got));\n"
            ) % json.dumps(module)
            result = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", code],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            ["1970-01-02T07:33:20.000Z"] * 5,
        )

    def test_storage_is_read_and_written_per_page_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, root)
            (root / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            module = (root / "models/gearchanges.js").as_uri()
            code = (
                "const data = new Map(); const storage = {getItem: k => data.get(k), "
                "setItem: (k, v) => data.set(k, v)};\n"
                "const M = await import(%s);\n"
                "const a = M.since('site', storage, 200000000);\n"
                "const b = M.since('member:tharn', storage, 300000000);\n"
                "M.markSeen('site', storage, M.observedMarker({limited: false, "
                "changes: [{event_id: '19', occurrences: 1, at: 400000}]}));\n"
                "process.stdout.write(JSON.stringify([a, b, M.since('site', storage), "
                "M.since('member:tharn', storage)]));\n"
            ) % json.dumps(module)
            result = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", code],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        got = json.loads(result.stdout)
        self.assertEqual(got[0], "1970-01-02T07:33:20.000Z")
        self.assertEqual(got[1], "1970-01-03T11:20:00.000Z")
        self.assertEqual(got[2], "1970-01-05T15:06:40.000Z")
        self.assertEqual(got[3], got[1])


if __name__ == "__main__":
    unittest.main()

"""The gear feed groups changes and keeps visit times per page key."""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"


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

    def _run_view(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, root)
            (root / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            module = (root / "views/gearchanges.js").as_uri()
            code = (
                "globalThis.document = {querySelector: () => null, addEventListener: () => {}};\n"
                "globalThis.window = {sessionStorage: {getItem: () => null, setItem: () => {}}};\n"
                "const V = await import(%s);\n"
            ) % json.dumps(module) + body
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
            self._row(at="2026-01-01 10:00:00"),
            self._row(at="2026-01-01 12:30:00"),
            self._row(at="2026-01-01 11:15:00"),
        ]
        newest_ms = int(
            datetime.datetime(
                2026, 1, 1, 12, 30, tzinfo=datetime.timezone.utc
            ).timestamp()
            * 1000
        )
        code = (
            "const changes = %s;\n"
            "const html = String(V.renderFeed({changes}, 'site'));\n"
            "process.stdout.write(JSON.stringify({html, newest: V.newestChangeMs(changes)}));\n"
        ) % json.dumps(changes)
        got = self._run_view(code)
        self.assertEqual(got["newest"], newest_ms)
        self.assertIn('data-newest="%d"' % newest_ms, got["html"])

    def test_mark_seen_stores_the_newest_change_and_redraws_in_place(self):
        code = (
            "const store = new Map(); const events = [];\n"
            "globalThis.window = {localStorage: {getItem: (k) => store.has(k) ? store.get(k) : null, "
            "setItem: (k, v) => store.set(k, String(v))}, "
            "dispatchEvent: (e) => { events.push(e.type); return true; }};\n"
            "let handler = null;\n"
            "const button = {getAttribute: (n) => n === 'data-mark-seen' ? 'site' : "
            "n === 'data-newest' ? '1767267000000' : null, "
            "addEventListener: (ev, fn) => { handler = fn; }};\n"
            "const main = {querySelectorAll: (sel) => sel === '[data-mark-seen]' ? [button] : []};\n"
            "V.default.after(main, {get: () => ({data: null})});\n"
            "handler();\n"
            "process.stdout.write(JSON.stringify({stored: store.get('overseer.gear-since.site'), events}));\n"
        )
        got = self._run_view(code)
        self.assertEqual(got["stored"], "1767267000000")
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
                "M.markSeen('site', storage, 400000000);\n"
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

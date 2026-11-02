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

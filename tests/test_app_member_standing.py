"""Standing labels use spell names and keep unknown spell IDs readable."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_app_shell import node_module
from test_app_sw import _boot_graph
from test_measured_views import APP, PRELUDE, learn

CATALOG = "models/spellnames.js"

# A stand-in catalog that counts how often it is evaluated, so a test can
# tell whether anything imported it.
COUNTING_CATALOG = (
    "globalThis.catalogLoads = (globalThis.catalogLoads || 0) + 1;\n"
    "export function classSpellName(id) { return 'Named ' + id; }\n"
)

# The Gear tab drawn for one member whose trainer read holds spell 11566.
DRAW_GEAR = (
    "const training = {line: 'L42 Warrior', cap: 60, trades: [], spells: {"
    "learned: [{spell: 11566, level: 40, cost: 0}], trainable: [], above: [],"
    " needs: [], next_level: 44}};\n"
    "const c = {params: {name: 'Grug', tab: 'gear'}, query: {}, isPhone: false,"
    " get: (p) => p.startsWith('/api/v2/training')"
    " ? {data: training, at: 1, error: null}"
    " : {data: undefined, at: 0, error: null, loading: true}};\n"
    "const draw = () => String(M.gearTab(c, {name: 'Grug'}));\n"
    "let redraws = 0;\n"
    "window.dispatchEvent = (e) => { if (e.type === 'overseer:redraw') redraws += 1; };\n"
    "const L = await import(new URL('../models/spelllookup.js', M_URL));\n"
)


def member_view(script, catalog=None):
    """Run `script` with the member view imported as M (its URL is M_URL)
    from a copy of the app. `catalog`, when given, is written over the
    copy's spell names module first."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        if catalog is not None:
            (root / CATALOG).write_text(catalog, encoding="utf-8")
        code = (
            PRELUDE % json.dumps("#/m/Grug/gear")
            + learn(root)
            + "const M_URL = %s;\n" % json.dumps((root / "views/member.js").as_uri())
            + "const M = await import(M_URL);\n"
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


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class StandingSpellNames(unittest.TestCase):
    def test_known_and_unknown_spell_names_keep_spell_links(self):
        out = node_module(
            "models/spellnames.js",
            "console.log(JSON.stringify([M.classSpellName(750), "
            "M.classSpellName(11566), M.classSpellName(999999), "
            "M.wowheadSpellUrl(750), M.wowheadSpellUrl(11566)]));",
        )
        self.assertEqual(
            out,
            [
                "Plate Mail",
                "Heroic Strike (Rank 7)",
                "Spell 999999",
                "https://www.wowhead.com/wotlk/spell=750",
                "https://www.wowhead.com/wotlk/spell=11566",
            ],
        )

    def test_every_exported_trainer_spell_has_a_name(self):
        # A realm snapshot across all ten classes is a coverage sample, not
        # the generator's input: ranks above the snapshot's cap also belong.
        ids = json.loads(
            (
                Path(__file__).parent / "fixtures/class_trainer_spell_ids.json"
            ).read_text()
        )
        missing = node_module(
            "models/spellnames.js",
            "console.log(JSON.stringify("
            + json.dumps(ids)
            + ".filter(id => M.classSpellName(id) === 'Spell ' + id)));",
        )
        self.assertEqual(len(missing), 0, f"Unnamed trainer spells: {missing[:12]}")


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class SpellNamesLoadLazily(unittest.TestCase):
    def test_importing_the_member_view_does_not_import_the_catalog(self):
        loads = member_view(
            "console.log(JSON.stringify(globalThis.catalogLoads || 0));",
            catalog=COUNTING_CATALOG,
        )
        self.assertEqual(loads, 0)
        self.assertNotIn(CATALOG, _boot_graph("views/member.js"))

    def test_a_spell_reads_as_an_unknown_id_until_the_catalog_arrives(self):
        before, loaded, link = member_view(
            DRAW_GEAR
            + "const out = draw();\n"
            + "console.log(JSON.stringify([out.includes('Spell 11566 <span'),"
            " globalThis.catalogLoads || 0,"
            " out.includes('href=\"https://www.wowhead.com/wotlk/spell=11566\"')]));",
            catalog=COUNTING_CATALOG,
        )
        self.assertTrue(before, "the chip reads Spell N before the catalog arrives")
        self.assertEqual(loaded, 0, "the first draw did not wait for the catalog")
        self.assertTrue(link, "the spell link needs no catalog")

    def test_the_name_is_drawn_after_the_catalog_arrives_and_a_redraw_is_asked(self):
        first, arrived, redraws, second = member_view(
            DRAW_GEAR
            + "const first = draw();\n"
            + "draw();\n"
            + "const arrived = await L.requestSpellNames();\n"
            + "const second = draw();\n"
            + "console.log(JSON.stringify([first.includes('Heroic Strike'), arrived,"
            " redraws, second.includes('Heroic Strike (Rank 7) <span')]));",
        )
        self.assertFalse(first)
        self.assertTrue(arrived)
        self.assertEqual(redraws, 1, "one redraw for one arrival, however many asks")
        self.assertTrue(second, "the real catalog's name is drawn after the redraw")

    def test_a_catalog_that_fails_to_load_leaves_ids_and_asks_no_redraw(self):
        arrived, redraws, out = member_view(
            DRAW_GEAR
            + "console.warn = () => {};\n"
            + "draw();\n"
            + "const arrived = await L.requestSpellNames();\n"
            + "console.log(JSON.stringify([arrived, redraws, draw()]));",
            catalog="throw new Error('no catalog');\n",
        )
        self.assertFalse(arrived)
        self.assertEqual(redraws, 0)
        self.assertIn("Spell 11566 <span", out)
        self.assertIn("wowhead.com/wotlk/spell=11566", out)

    def test_a_failed_load_is_tried_again_only_after_the_wait(self):
        out = node_module(
            "models/spelllookup.js",
            "console.warn = () => {};\n"
            "let t = 1000, loads = 0, redraws = 0, fail = true;\n"
            "const good = {classSpellName: (id) => 'Named ' + id};\n"
            "const k = M.makeLookup({now: () => t, redraw: () => { redraws += 1; },"
            " load: async () => { loads += 1; if (fail) throw new Error('offline'); return good; }});\n"
            "const seen = [k.spellName(5)];\n"
            "await k.request();\n"
            "t += M.RETRY_MS - 1; seen.push(k.spellName(5)); await k.request();\n"
            "const early = loads;\n"
            "fail = false; t += 1; seen.push(k.spellName(5)); await k.request();\n"
            "seen.push(k.spellName(5), k.spellName('x'));\n"
            "console.log(JSON.stringify({seen, early, loads, redraws, loaded: k.loaded()}));",
        )
        self.assertEqual(
            out,
            {
                "seen": ["Spell 5", "Spell 5", "Spell 5", "Named 5", "Named 0"],
                "early": 1,
                "loads": 2,
                "redraws": 1,
                "loaded": True,
            },
        )

    def test_the_lookup_link_matches_the_catalogs(self):
        script = (
            "console.log(JSON.stringify([750, '11566', 'x', null]"
            ".map((s) => M.wowheadSpellUrl(s))));"
        )
        self.assertEqual(
            node_module("models/spelllookup.js", script),
            node_module(CATALOG, script),
        )

    def test_now_and_the_shell_boot_without_the_catalog(self):
        now = _boot_graph("views/now.js")
        self.assertIn("views/member.js", now, "Now draws the member tabs in its tiles")
        self.assertIn("models/spelllookup.js", now)
        self.assertNotIn(CATALOG, now)
        self.assertNotIn(CATALOG, _boot_graph())
        for view in sorted((APP / "views").glob("*.js")):
            self.assertNotIn(CATALOG, _boot_graph("views/" + view.name), view.name)

"""The 220 KB spell name table loads only when a page draws a spell.

WHY. views/member.js imported the generated table statically, and the Now
page imports member.js for its tile panels, so every first load of Now pulled
the table in before a single spell was on screen. The member view now asks
models/spelllookup.js, which imports the table on its first lookup and asks
the page for a redraw when it arrives.

Ticket: #2316 (epic #2309).
"""

import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

from test_app_shell import node_module

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
STATIC_IMPORT = re.compile(
    r"""^\s*(?:import|export)\s[^;]*?from\s+["']([^"']+)["']""", re.M
)
BARE_IMPORT = re.compile(r"""^\s*import\s+["']([^"']+)["']""", re.M)


def static_closure(entry):
    """Every app file reached from `entry` by static imports (not import())."""
    seen, todo = set(), [(APP / entry).resolve()]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8")
        for spec in STATIC_IMPORT.findall(text) + BARE_IMPORT.findall(text):
            if spec.startswith("."):
                todo.append((path.parent / spec).resolve())
    return {p.relative_to(APP.resolve()).as_posix() for p in seen}


class TheTableIsNotInTheBootGraph(unittest.TestCase):
    def test_the_member_view_does_not_import_the_table(self):
        self.assertNotIn("models/spellnames.js", static_closure("views/member.js"))

    def test_the_entry_script_does_not_reach_the_table_by_a_static_import(self):
        self.assertNotIn("models/spellnames.js", static_closure("main.js"))

    def test_the_lookup_reaches_the_table_only_through_import_call(self):
        self.assertNotIn(
            "models/spellnames.js", static_closure("models/spelllookup.js")
        )
        text = (APP / "models" / "spelllookup.js").read_text(encoding="utf-8")
        self.assertIn('import("./spellnames.js")', text)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheLookup(unittest.TestCase):
    def test_a_first_lookup_reads_as_an_unknown_spell_then_the_name_arrives_and_a_redraw_is_asked(
        self,
    ):
        out = node_module(
            "models/spelllookup.js",
            """
            const events = [];
            globalThis.window = { dispatchEvent: (e) => events.push(e.type) };
            globalThis.Event = class { constructor(t) { this.type = t; } };
            const first = M.spellName(750);
            await M.ready();
            console.log(JSON.stringify({ first, later: M.spellName(750), other: M.spellName(11566), events }));
            """,
        )
        self.assertEqual(out["first"], "Spell 750")
        self.assertEqual(out["later"], "Plate Mail")
        self.assertEqual(out["other"], "Heroic Strike (Rank 7)")
        self.assertEqual(out["events"], ["overseer:redraw"])

    def test_the_table_is_asked_for_once_however_many_lookups_come_first(self):
        out = node_module(
            "models/spelllookup.js",
            """
            const events = [];
            globalThis.window = { dispatchEvent: (e) => events.push(e.type) };
            globalThis.Event = class { constructor(t) { this.type = t; } };
            [750, 11566, 999999].forEach((s) => M.spellName(s));
            await M.ready();
            console.log(JSON.stringify({ events, unknown: M.spellName(999999) }));
            """,
        )
        self.assertEqual(out["events"], ["overseer:redraw"])
        self.assertEqual(out["unknown"], "Spell 999999")

    def test_a_spell_link_needs_no_table(self):
        out = node_module(
            "models/spelllookup.js",
            "console.log(JSON.stringify([M.wowheadSpellUrl(750), M.wowheadSpellUrl('x')]));",
        )
        self.assertEqual(
            out,
            [
                "https://www.wowhead.com/wotlk/spell=750",
                "https://www.wowhead.com/wotlk/spell=0",
            ],
        )

    def test_a_table_that_fails_to_load_leaves_the_readable_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, root)
            (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
            (root / "models" / "spellnames.js").unlink()
            code = (
                "globalThis.window = { dispatchEvent: () => {} };\n"
                "globalThis.Event = class { constructor(t) { this.type = t; } };\n"
                "const M = await import(%s);\n"
                "const a = M.spellName(750);\n"
                "await M.ready();\n"
                "console.log(JSON.stringify({ a, b: M.spellName(750) }));\n"
                % json.dumps((root / "models" / "spelllookup.js").as_uri())
            )
            out = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", code],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"a": "Spell 750", "b": "Spell 750"})


if __name__ == "__main__":
    unittest.main()

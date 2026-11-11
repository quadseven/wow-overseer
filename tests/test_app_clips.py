"""The clips shelf and the clip link, drawn by app/views/_clips.js.

Run under node against small stand-ins for the browser, like the other app
view tests: the markup is checked as text, and a fake document checks that
Play turns the button into a native video element in place.
"""

import json
import re
import unittest

from test_app_flagship import app_file, needs_node, run_node

API_STUB = (
    'export const u = (p) => "/m" + p;\n'
    "export const peek = () => ({ data: undefined });\n"
    "export const load = () => Promise.resolve();\n"
)

CLIPS = [
    {
        "id": 2,
        "kind": "boss_kill",
        "character": "Otherchar",
        "subject": "Test Warden",
        "at": "2026-11-09T11:30:00",
        "url": "/clips/clip-2-boss_kill.mp4",
    },
    {
        "id": 1,
        "kind": "loot",
        "character": "Testchar",
        "subject": "Test Blade",
        "at": "2026-11-09T10:00:00",
        "url": "/clips/clip-1-loot.mp4",
    },
]

FILES = {
    "views/_clips.js": None,
    "models/time.js": None,
    "ui.js": None,
    "api.js": API_STUB,
}


def run(script):
    files = {k: (v if v is not None else app_file(k)) for k, v in FILES.items()}
    return run_node(files, "globalThis.window = { addEventListener() {} };\n" + script)


@needs_node
class TheShelf(unittest.TestCase):
    def draw(self, read):
        out = run(
            'const C = await import("./views/_clips.js");\n'
            "console.log(JSON.stringify({m: String(C.shelf(%s))}));\n"
            % json.dumps(read)
        )
        return out["m"]

    def test_each_clip_is_a_card_with_kind_character_and_a_play_button(self):
        m = self.draw({"data": {"clips": CLIPS, "empty": "none"}, "loading": False})
        self.assertEqual(m.count('class="card clip-card"'), 2)
        self.assertLess(m.index("Otherchar"), m.index("Testchar"))
        self.assertIn("Boss kill", m)
        self.assertIn('data-clip="/clips/clip-1-loot.mp4"', m)

    def test_a_card_shows_the_boss_or_the_item_and_none_when_unnamed(self):
        m = self.draw({"data": {"clips": CLIPS, "empty": "none"}, "loading": False})
        self.assertIn("Test Warden", m)
        self.assertIn("Test Blade", m)
        bare = [dict(CLIPS[0], subject="")]
        m = self.draw({"data": {"clips": bare, "empty": "none"}, "loading": False})
        self.assertNotIn("clip-subject", m)

    def test_no_video_is_loaded_until_play(self):
        m = self.draw({"data": {"clips": CLIPS, "empty": "none"}, "loading": False})
        self.assertNotIn("<video", m)

    def test_an_empty_shelf_says_so(self):
        m = self.draw(
            {
                "data": {"clips": [], "empty": "No clips have been saved yet."},
                "loading": False,
            }
        )
        self.assertIn("No clips yet", m)
        self.assertIn("No clips have been saved yet.", m)
        self.assertNotIn("clip-card", m)

    def test_a_read_that_has_not_answered_is_a_skeleton_not_an_empty_shelf(self):
        m = self.draw({"loading": True})
        self.assertNotIn("No clips yet", m)


@needs_node
class PlayInPlace(unittest.TestCase):
    def test_play_swaps_the_button_for_a_native_video(self):
        out = run(
            'const C = await import("./views/_clips.js");\n'
            "const made = [];\n"
            "globalThis.document = { createElement(tag) { const e = { tag, attrs: {},"
            " setAttribute(k, v) { this.attrs[k] = v; }, play() { this.played = true; } };"
            " made.push(e); return e; } };\n"
            "let click; let replaced;\n"
            "const button = { getAttribute: () => '/clips/clip-1-loot.mp4',"
            " addEventListener(_t, f) { click = f; }, replaceWith(e) { replaced = e; } };\n"
            "C.bindShelf({ querySelectorAll: () => [button] });\n"
            "click();\n"
            "const v = replaced;\n"
            "console.log(JSON.stringify({tag: v.tag, controls: v.controls, preload: v.preload,"
            " playsinline: 'playsinline' in v.attrs, src: v.src, played: !!v.played}));\n"
        )
        self.assertEqual(
            out,
            {
                "tag": "video",
                "controls": True,
                "preload": "metadata",
                "playsinline": True,
                "src": "/m/clips/clip-1-loot.mp4",
                "played": True,
            },
        )

    def test_a_playing_clip_is_the_same_element_after_a_redraw(self):
        out = run(
            'const C = await import("./views/_clips.js");\n'
            "const made = [];\n"
            "globalThis.document = { createElement(tag) { const e = { tag, attrs: {},"
            " setAttribute(k, v) { this.attrs[k] = v; }, play() {}, pause() {} };"
            " made.push(e); return e; } };\n"
            "const url = '/clips/clip-1-loot.mp4';\n"
            "const read = {data: {clips: [{id: 1, kind: 'loot', character: 'A',"
            " at: '2026-11-09T10:00:00', url}]}, loading: false};\n"
            "let click; let first;\n"
            "const button = { getAttribute: () => url, addEventListener(_t, f) { click = f; },"
            " replaceWith(e) { first = e; } };\n"
            "C.shelf(read);\n"
            "C.bindShelf({ querySelectorAll: (q) => (q.startsWith('button') ? [button] : []) });\n"
            "click();\n"
            "const markup = String(C.shelf(read));\n"
            "let placed;\n"
            "const slot = { getAttribute: () => url, replaceWith(e) { placed = e; } };\n"
            "C.bindShelf({ querySelectorAll: (q) => (q.startsWith('[data-clip-slot]') ? [slot] : []) });\n"
            "console.log(JSON.stringify({same: placed === first, created: made.length,"
            " video: markup.includes('<video'), slot: markup.includes('data-clip-slot'),"
            " play: markup.includes('data-clip=')}));\n"
        )
        self.assertEqual(
            out,
            {"same": True, "created": 1, "video": False, "slot": True, "play": False},
        )

    def test_a_kept_video_is_dropped_when_its_clip_leaves_the_list(self):
        out = run(
            'const C = await import("./views/_clips.js");\n'
            "const made = [];\n"
            "globalThis.document = { createElement(tag) { const e = { tag, attrs: {},"
            " setAttribute() {}, play() {}, pause() { this.paused = true; } };"
            " made.push(e); return e; } };\n"
            "const url = '/clips/clip-1-loot.mp4';\n"
            "const row = {id: 1, kind: 'loot', character: 'A', at: '2026-11-09T10:00:00', url};\n"
            "let click;\n"
            "const button = { getAttribute: () => url, addEventListener(_t, f) { click = f; },"
            " replaceWith() {} };\n"
            "C.shelf({data: {clips: [row]}, loading: false});\n"
            "C.bindShelf({ querySelectorAll: (q) => (q.startsWith('button') ? [button] : []) });\n"
            "click();\n"
            "const gone = String(C.shelf({data: {clips: []}, loading: false}));\n"
            "const back = String(C.shelf({data: {clips: [row]}, loading: false}));\n"
            "console.log(JSON.stringify({gone: gone.includes('data-clip-slot'),"
            " back: back.includes('data-clip-slot'), paused: !!made[0].paused}));\n"
        )
        self.assertEqual(out, {"gone": False, "back": False, "paused": True})


@needs_node
class TheClipLink(unittest.TestCase):
    def link(self, entry):
        out = run(
            'const C = await import("./views/_clips.js");\n'
            "console.log(JSON.stringify({m: String(C.clipLink(%s))}));\n"
            % json.dumps(entry)
        )
        return out["m"]

    def test_a_clip_is_a_link_under_the_mount(self):
        m = self.link({"clip": {"url": "/clips/clip-9-loot.mp4", "kind": "loot"}})
        self.assertIn('href="/m/clips/clip-9-loot.mp4"', m)
        self.assertIn("Watch the clip", m)

    def test_no_view_shows_the_servers_words(self):
        m = self.link({"clip_note": "No live view was up, so no clip was saved."})
        self.assertIn("No live view was up", m)
        self.assertNotIn("<a ", m)

    def test_no_clip_fields_draw_nothing(self):
        self.assertEqual(self.link({"line": "x"}), "")


class TheShelfIsWiredIntoTheChronicle(unittest.TestCase):
    def test_the_guild_view_reads_and_draws_the_shelf_and_the_links(self):
        guild = app_file("views/guild.js")
        self.assertIn("clips: () => CLIPS_READ", guild)
        self.assertTrue(re.search(r'"chronicle", "loot", "clips"', guild))
        self.assertIn("clipShelf(peek(P.clips()))", guild)
        self.assertGreaterEqual(
            guild.count("clipLink("), 3
        )  # feed, loot section, run card
        self.assertIn("bindClips(main)", guild)

    def test_the_video_is_native_and_phone_friendly(self):
        src = app_file("views/_clips.js")
        self.assertIn('v.preload = "metadata"', src)
        self.assertIn('"playsinline"', src)
        self.assertIn("v.controls = true", src)
        css = app_file("views/clips.css")
        self.assertIn("max-width: 100%", css)
        self.assertIn("min-height: 44px", css)


if __name__ == "__main__":
    unittest.main()

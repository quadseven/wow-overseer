"""The clips shelf and the clip link, drawn by app/views/_clips.js.

Run under node against small stand-ins for the browser, like the other app
view tests: the markup is checked as text, and a fake document checks that
Play turns the button into a native video element in place.
"""

import json
import re
import unittest

import clipledger

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

    def test_a_repeat_of_one_item_says_which_one_it_is(self):
        twice = [
            dict(CLIPS[1], id=4, nth=2, of=2),
            dict(CLIPS[1], id=3, nth=1, of=2),
        ]
        m = self.draw({"data": {"clips": twice, "empty": "none"}, "loading": False})
        self.assertIn("2 of 2", m)
        self.assertIn("1 of 2", m)
        once = self.draw({"data": {"clips": CLIPS, "empty": "none"}, "loading": False})
        self.assertNotIn("clip-nth", once)

    def test_a_day_footer_counts_missed_moments_and_adds_no_card(self):
        missed = [
            {"day": "2026-11-10", "no_view": 2, "failed": 1},
            {"day": "2026-11-09", "no_view": 0, "failed": 0},
        ]
        m = self.draw(
            {"data": {"clips": CLIPS, "missed": missed, "empty": "x"}, "loading": False}
        )
        self.assertEqual(m.count('class="card clip-card"'), 2)
        self.assertIn("2026-11-10: 2 with no streamed member in view", m)
        self.assertIn("1 where recording failed", m)
        self.assertNotIn("2026-11-09", m)

    def test_loot_event_fixtures_render_item_context_and_missed_counts(self):
        rows = [
            {
                "id": 1,
                "event_key": "loot:101",
                "kind": "loot",
                "character": "Testchar",
                "event_at": "2026-11-12T22:27:00",
                "state": "ready",
                "file_name": "clip-1-loot.mp4",
                "detail": "Shadowblade",
            },
            {
                "id": 2,
                "event_key": "loot:102",
                "kind": "loot",
                "character": "Testchar",
                "event_at": "2026-11-13T10:57:00",
                "state": "ready",
                "file_name": "clip-2-loot.mp4",
                "detail": "Shadowblade",
            },
            {
                "id": 3,
                "kind": "loot",
                "character": "Testchar",
                "event_at": "2026-11-13T11:00:00",
                "state": "failed",
                "detail": "encoder failed",
            },
            {
                "id": 4,
                "kind": "loot",
                "character": "Testchar",
                "event_at": "2026-11-13T11:01:00",
                "state": "no_view",
                "detail": "no streamed member in the run",
            },
        ]
        event_rows = [
            {
                "id": event_id,
                "kind": "item_loot",
                "character_name": "Testchar",
                "subject_id": 18821,
                "subject_name": "Shadowblade",
                "subject_quality": 4,
                "map": 230,
                "zone": 0,
                "source": source,
                "first_seen": at,
            }
            for event_id, at, source in (
                (101, "2026-11-12T22:27:00", "General Angerforge"),
                (102, "2026-11-13T10:57:00", "Houndmaster Grebmar"),
            )
        ]
        payload = clipledger.shelf(
            rows,
            event_rows=event_rows,
            item_rows=[
                {"entry": 18821, "name": "Shadowblade", "quality": 4, "displayid": 77}
            ],
            run_rows=[
                {
                    "id": 42,
                    "map_id": 230,
                    "started_at": "2026-11-12T22:00:00",
                    "ended_at": "2026-11-12T23:10:00",
                },
                {
                    "id": 43,
                    "map_id": 230,
                    "started_at": "2026-11-13T10:00:00",
                    "ended_at": "2026-11-13T11:10:00",
                },
            ],
            icons={77: "inv_sword_04"},
            zones={10: "Duskwood"},
        )
        m = self.draw({"data": payload, "loading": False})

        self.assertEqual(m.count('class="card clip-card"'), 2)
        self.assertEqual(m.count('class="item q4"'), 2)
        self.assertIn("Blackrock Depths run 42, General Angerforge", m)
        self.assertIn("Blackrock Depths run 43, Houndmaster Grebmar", m)
        self.assertIn("q4", m)
        self.assertIn("inv_sword_04.jpg", m)
        self.assertIn('src="/m/clips/clip-1-loot-poster.jpg"', m)
        self.assertIn('src="/m/clips/clip-2-loot-poster.jpg"', m)
        self.assertIn("1 of 2", m)
        self.assertIn("2 of 2", m)
        self.assertIn(
            "2026-11-13: 1 with no streamed member in view, 1 where recording failed.",
            m,
        )
        self.assertNotIn("encoder failed", m)
        self.assertNotIn("no streamed member in the run", m)

    def test_only_missed_moments_still_show_the_footer(self):
        missed = [{"day": "2026-11-10", "no_view": 1, "failed": 0}]
        m = self.draw(
            {"data": {"clips": [], "missed": missed, "empty": "x"}, "loading": False}
        )
        self.assertIn("1 with no streamed member in view", m)

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

    def test_a_clip_from_another_view_says_whose_under_the_link(self):
        note = "Filmed from the view of Otherchar (leader)."
        m = self.link(
            {
                "clip": {
                    "url": "/clips/clip-9-loot.mp4",
                    "kind": "loot",
                    "view_note": note,
                }
            }
        )
        self.assertIn("Watch the clip", m)
        self.assertIn(note, m)
        self.assertLess(m.index("Watch the clip"), m.index(note))
        plain = self.link({"clip": {"url": "/clips/clip-9-loot.mp4", "kind": "loot"}})
        self.assertNotIn("clip-note", plain)

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


@needs_node
class TheNamedClipLinks(unittest.TestCase):
    def links(self, entry):
        out = run(
            'const C = await import("./views/_clips.js");\n'
            "console.log(JSON.stringify({m: String(C.clipLinks(%s))}));\n"
            % json.dumps(entry)
        )
        return out["m"]

    def test_each_character_gets_the_same_link_or_note_with_the_name(self):
        m = self.links(
            {
                "clips": [
                    {
                        "who": "Bonk",
                        "clip": {
                            "url": "/clips/clip-9-level_60.mp4",
                            "kind": "level_60",
                        },
                    },
                    {
                        "who": "Durg",
                        "clip_note": "No live view was up, so no clip was saved.",
                    },
                ]
            }
        )
        self.assertIn('href="/m/clips/clip-9-level_60.mp4"', m)
        self.assertIn("Watch the clip", m)
        self.assertIn("Bonk", m)
        self.assertIn("Durg", m)
        self.assertIn("No live view was up", m)
        self.assertEqual(m.count('class="clip-link"'), 1)

    def test_an_entry_without_clips_draws_nothing(self):
        self.assertEqual(self.links({"line": "x"}), "")
        self.assertEqual(self.links({"clips": []}), "")

    def test_a_run_card_clip_is_named_by_its_character(self):
        m = self.links(
            {
                "clips": [
                    {
                        "character": "Oz",
                        "kind": "boss_kill",
                        "clip": {
                            "url": "/clips/clip-6-boss_kill.mp4",
                            "kind": "boss_kill",
                        },
                    },
                    {
                        "character": "Zug",
                        "kind": "loot",
                        "clip_note": "No clip was saved.",
                    },
                ]
            }
        )
        self.assertIn('href="/m/clips/clip-6-boss_kill.mp4"', m)
        self.assertIn("Oz", m)
        self.assertIn("Zug", m)
        self.assertIn("No clip was saved.", m)
        self.assertNotIn("undefined", m)

    def test_the_run_card_draws_its_clips_with_the_shared_helper(self):
        guild = app_file("views/guild.js")
        self.assertIn("${clipLink(r)}${clipLinks(r)}", guild)


class TheFeedDrawsFirstKillsAndSixtyClips(unittest.TestCase):
    def test_the_feed_row_draws_every_clip_shape_with_the_shared_helpers(self):
        guild = app_file("views/guild.js")
        self.assertIn("first_kill:", guild)
        self.assertIn("clipLinks(", guild)
        self.assertIn("clipLink(x)", guild)
        self.assertNotIn('x.kind === "loot" ? clipLink(x)', guild)
        self.assertIn('["level", "clear", "run", "first_kill"]', guild)


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
        self.assertIn("padding-bottom: calc(var(--tabbar-h) + 56px)", css)


if __name__ == "__main__":
    unittest.main()

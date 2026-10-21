"""Reading party and raid chat aloud on the Watch wall (chatvoice.js).

The queue, the ducking and the reader run in node with a fake speech engine
and a fake video, so the rules the page keeps are pinned without a browser:
one line at a time, stale lines dropped, repeats skipped, the queue capped,
the heard stream lowered while a line is said and put back after, error
included, and nothing said until the viewer switches reading on.
"""

import shutil
import unittest

from test_app_shell import node_module

NODE = unittest.skipUnless(
    shutil.which("node"), "node is needed to run the app's modules"
)

# A fake engine and a reader wired to it. `said` collects each utterance;
# end() and fail() finish the one being said the way the browser would.
FAKES = """
const said = [];
let cancelled = 0;
class Utter { constructor(text) { this.text = text; } }
const engine = {
  SpeechSynthesisUtterance: Utter,
  speechSynthesis: {
    getVoices: () => [
      { name: "Daniel", lang: "en-GB" },
      { name: "Samantha Female", lang: "en-US" },
      { name: "Thomas", lang: "fr-FR" },
    ],
    speak: (u) => said.push(u),
    cancel: () => { cancelled += 1; },
  },
};
const end = () => said[said.length - 1].onend();
const fail = () => said[said.length - 1].onerror({ error: "synthesis-failed" });
const video = { muted: false, volume: 0.8 };
let clock = 100000;
const asked = [];
const stored = {};
const store = {
  getItem: (k) => (k in stored ? stored[k] : null),
  setItem: (k, v) => { stored[k] = v; },
};
let feeds = [];
const reader = M.makeReader({
  families: () => ["Grug"],
  fetchFeed: async (family, after) => { asked.push([family, after]); return feeds.shift() || { rows: [], cursor: after || 0 }; },
  audible: () => video,
  engine,
  store,
  now: () => clock,
  every: () => 1,
  cancel: () => {},
});
const line = (id, text, sender = "Grug") => ({
  id, sender, text, channel: "party", age_s: 1,
  voice: { engine_voice_hint: { lang: "en", gender: "male" }, pitch: 0.7, rate: 0.85 },
});
"""


def run(script):
    return node_module(
        "views/now/chatvoice.js",
        FAKES + script,
    )


def show(expr):
    return "console.log(JSON.stringify(" + expr + "));"


@NODE
class TheQueue(unittest.TestCase):
    def queue(self, script):
        return node_module(
            "views/now/chatvoice.js",
            "const q = M.makeQueue({cap: 3, staleMs: 20000, repeatMs: 60000});\n"
            "const l = (text, at, sender = 'Grug') => ({sender, text, at});\n" + script,
        )

    def test_one_line_at_a_time(self):
        got = self.queue(
            "q.offer(l('a', 0), 0); q.offer(l('b', 0), 0);"
            "const first = q.take(1000).text; const held = q.take(1000);"
            "q.done();" + show("[first, held, q.take(1000).text]")
        )
        self.assertEqual(got, ["a", None, "b"])

    def test_a_stale_line_is_dropped_when_its_turn_comes(self):
        got = self.queue(
            "q.offer(l('old', 0), 0); q.offer(l('new', 15000), 15000);"
            + show("[q.take(25000).text, q.size()]")
        )
        self.assertEqual(got, ["new", 0])

    def test_a_repeat_from_the_same_speaker_is_skipped(self):
        got = self.queue(
            "const a = q.offer(l('Aye.', 0), 0);"
            "const b = q.offer(l('Aye.', 10000), 10000);"
            "const other = q.offer(l('Aye.', 10000, 'Ugga'), 10000);"
            + show("[a, b, other, q.size()]")
        )
        self.assertEqual(got, [True, False, True, 2])

    def test_the_same_words_are_said_again_after_a_minute(self):
        got = self.queue(
            "q.offer(l('Aye.', 0), 0);" + show("q.offer(l('Aye.', 61000), 61000)")
        )
        self.assertTrue(got)

    def test_the_queue_is_capped_and_keeps_the_newest(self):
        got = self.queue(
            "['a','b','c','d','e'].forEach((t) => q.offer(l(t, 0), 0));"
            "const n = q.size(); const out = [];"
            "for (let i = 0; i < 3; i++) { out.push(q.take(0).text); q.done(); }"
            + show("[n, out]")
        )
        self.assertEqual(got, [3, ["c", "d", "e"]])


@NODE
class Ducking(unittest.TestCase):
    def test_lowers_the_heard_stream_and_puts_it_back(self):
        got = node_module(
            "views/now/chatvoice.js",
            "const v = {muted: false, volume: 0.8}; const back = M.duck(v);"
            "const during = v.volume; back();" + show("[during, v.volume]"),
        )
        self.assertEqual(got, [0.25, 0.8])

    def test_a_muted_stream_is_never_unmuted_or_touched(self):
        got = node_module(
            "views/now/chatvoice.js",
            "const v = {muted: true, volume: 0.8}; const back = M.duck(v);"
            "const during = [v.muted, v.volume]; back();"
            + show("[during, v.muted, v.volume]"),
        )
        self.assertEqual(got, [[True, 0.8], True, 0.8])

    def test_no_heard_stream_is_nothing_to_duck(self):
        got = node_module("views/now/chatvoice.js", "M.duck(null)();" + show("'ok'"))
        self.assertEqual(got, "ok")

    def test_a_volume_the_viewer_set_mid_line_is_kept(self):
        got = node_module(
            "views/now/chatvoice.js",
            "const v = {muted: false, volume: 0.8}; const back = M.duck(v);"
            "v.volume = 0.5; back();" + show("v.volume"),
        )
        self.assertEqual(got, 0.5)


@NODE
class TheVoice(unittest.TestCase):
    def test_a_system_voice_is_picked_by_language_and_named_gender(self):
        got = run(
            "const v = engine.speechSynthesis.getVoices();"
            + show(
                "[M.pickVoice(v, {lang: 'en', gender: 'female'}).name,"
                " M.pickVoice(v, {lang: 'en', gender: 'male'}).name,"
                " M.pickVoice(v, {lang: 'fr', gender: ''}).name,"
                " M.pickVoice([], {lang: 'en'})]"
            )
        )
        # "male" is not found inside "Female": the match is on a whole word.
        self.assertEqual(got, ["Samantha Female", "Daniel", "Thomas", None])

    def test_speak_applies_the_characters_pitch_and_rate(self):
        got = run(
            "M.speak(line(1, 'Aye.'), () => {}, engine);"
            + show("[said[0].text, said[0].pitch, said[0].rate, said[0].voice.name]")
        )
        self.assertEqual(got, ["Aye.", 0.7, 0.85, "Daniel"])

    def test_speak_completes_only_once_when_engine_fires_multiple_callbacks(self):
        got = run(
            "let calls = 0; M.speak(line(1, 'Aye.'), () => { calls += 1; }, engine);"
            "said[0].onend(); said[0].onerror({error: 'late'});" + show("calls")
        )
        self.assertEqual(got, 1)

    def test_no_speech_engine_is_reported_not_swallowed(self):
        got = run(
            "let err = null; M.speak(line(1, 'Aye.'), (e) => { err = e; }, {});"
            + show("String(err)")
        )
        self.assertIn("no speech engine", got)


@NODE
class TheReader(unittest.TestCase):
    def test_off_until_switched_on_and_silent_meanwhile(self):
        got = run(
            "feeds = [{rows: [line(1, 'Aye.')], cursor: 1}];"
            "await reader.poll();" + show("[reader.isOn(), said.length]")
        )
        self.assertEqual(got, [False, 0])

    def test_the_first_poll_starts_from_now_and_the_next_sends_the_cursor(self):
        got = run(
            "feeds = [{rows: [], cursor: 40}, {rows: [line(41, 'Aye.')], cursor: 45}];"
            "await reader.start(); await reader.poll();"
            + show("[asked, said.map((u) => u.text), stored]")
        )
        self.assertEqual(got[0], [["Grug", None], ["Grug", 40]])
        self.assertEqual(got[1], ["Aye."])
        self.assertEqual(got[2], {"overseer.chatVoice": "1"})

    def test_toggle_waits_for_the_initial_poll(self):
        got = run(
            "feeds = [{rows: [], cursor: 40}];"
            "const pending = reader.toggle();"
            + show("[typeof pending.then, reader.isOn(), asked]")
        )
        self.assertEqual(got, ["function", True, [["Grug", None]]])

    def test_a_line_read_twice_across_polls_is_said_once(self):
        got = run(
            "feeds = [{rows: [], cursor: 0}, {rows: [line(1, 'Aye.')], cursor: 1},"
            " {rows: [line(2, 'Aye.')], cursor: 2}];"
            "await reader.start(); await reader.poll();"
            "end(); await reader.poll();" + show("said.length")
        )
        self.assertEqual(got, 1)

    def test_one_line_at_a_time_and_ducked_until_the_last_ends(self):
        got = run(
            "feeds = [{rows: [], cursor: 0}, {rows: [line(1, 'one'), line(2, 'two')], cursor: 2}];"
            "await reader.start(); await reader.poll();"
            "const first = [said.length, video.volume]; end();"
            "const second = [said.length, video.volume]; end();"
            + show("[first, second, video.volume]")
        )
        self.assertEqual(got, [[1, 0.25], [2, 0.25], 0.8])

    def test_the_stream_is_restored_when_speech_fails(self):
        got = run(
            "feeds = [{rows: [], cursor: 0}, {rows: [line(1, 'one'), line(2, 'two')], cursor: 2}];"
            "await reader.start(); await reader.poll();"
            "fail(); const afterFail = [said.length, said[1].text];"
            "fail();" + show("[afterFail, video.volume]")
        )
        self.assertEqual(got, [[2, "two"], 0.8])

    def test_the_stream_is_restored_when_the_engine_throws(self):
        got = run(
            "engine.speechSynthesis.speak = () => { throw new Error('gone'); };"
            "console.warn = () => {};"
            "feeds = [{rows: [], cursor: 0}, {rows: [line(1, 'one')], cursor: 1}];"
            "await reader.start(); await reader.poll();" + show("video.volume")
        )
        self.assertEqual(got, 0.8)

    def test_late_engine_error_does_not_restore_the_next_lines_duck(self):
        got = run(
            "feeds = [{rows: [], cursor: 0}, {rows: [line(1, 'one'), line(2, 'two')], cursor: 2}];"
            "await reader.start(); await reader.poll();"
            "const first = said[0]; first.onend(); first.onerror({error: 'late'});"
            + show("[said.length, video.volume]")
        )
        self.assertEqual(got, [2, 0.25])

    def test_a_line_that_waited_too_long_is_not_said(self):
        got = run(
            "feeds = [{rows: [], cursor: 0}, {rows: [line(1, 'old'), line(2, 'new')], cursor: 2}];"
            "await reader.start(); await reader.poll();"
            "clock += 30000; feeds = [{rows: [line(3, 'fresh')], cursor: 3}];"
            "end(); await reader.poll();" + show("said.map((u) => u.text)")
        )
        self.assertEqual(got, ["old", "fresh"])

    def test_switching_off_cancels_speech_restores_and_forgets(self):
        got = run(
            "feeds = [{rows: [], cursor: 0}, {rows: [line(1, 'one')], cursor: 1}];"
            "await reader.start(); await reader.poll();"
            "reader.toggle();"
            + show(
                "[reader.isOn(), cancelled, video.volume, stored['overseer.chatVoice']]"
            )
        )
        self.assertEqual(got, [False, 1, 0.8, "0"])

    def test_leaving_now_stops_but_keeps_the_choice(self):
        got = run(
            "await reader.start(); reader.stop(false);"
            + show("[reader.isOn(), stored['overseer.chatVoice']]")
        )
        self.assertEqual(got, [False, "1"])

    def test_a_malformed_row_is_skipped_and_logged_and_the_rest_said(self):
        got = run(
            "const warned = []; console.warn = (...a) => warned.push(String(a[0]));"
            "feeds = [{rows: [], cursor: 0}, {rows: [null, {sender: 'Grug'},"
            " {sender: 'Grug', text: 'no voice'}, line(1, 'Aye.')], cursor: 4}];"
            "await reader.start(); await reader.poll(); end();"
            + show("[said.map((u) => [u.text, u.pitch]), warned.length]")
        )
        self.assertEqual(got, [[["no voice", 1], ["Aye.", 0.7]], 2])

    def test_a_poll_that_throws_does_not_stop_the_next_one(self):
        got = run(
            "let broken = true;"
            "const r = M.makeReader({families: () => { if (broken) throw new Error('x'); return ['Grug']; },"
            " fetchFeed: async (f, after) => { asked.push([f, after]); return {rows: [], cursor: 0}; },"
            " audible: () => null, engine, store, now: () => clock,"
            " every: () => 1, cancel: () => {}});"
            "let thrown = false; try { await r.start(); } catch (e) { thrown = true; }"
            "broken = false; await r.poll();" + show("[thrown, asked]")
        )
        self.assertEqual(got, [True, [["Grug", None]]])

    def test_a_feed_that_fails_is_logged_and_the_reader_keeps_going(self):
        got = run(
            "const r = M.makeReader({families: () => ['Grug'],"
            " fetchFeed: async () => { throw new Error('503'); },"
            " audible: () => null, engine, store, now: () => clock,"
            " every: () => 1, cancel: () => {}});"
            "const warned = []; console.warn = (...a) => warned.push(String(a[0]));"
            "await r.start();" + show("[r.isOn(), warned.length > 0]")
        )
        self.assertEqual(got, [True, True])


@NODE
class TheRememberedChoice(unittest.TestCase):
    def test_storage_that_throws_reads_as_off(self):
        got = node_module(
            "views/now/chatvoice.js",
            "console.warn = () => {};"
            + show("M.remembered({getItem: () => { throw new Error('blocked'); }})"),
        )
        self.assertFalse(got)

    def test_a_remembered_choice_is_read_back(self):
        got = node_module(
            "views/now/chatvoice.js",
            show(
                "M.remembered({getItem: (k) => k === 'overseer.chatVoice' ? '1' : null})"
            ),
        )
        self.assertTrue(got)


if __name__ == "__main__":
    unittest.main()

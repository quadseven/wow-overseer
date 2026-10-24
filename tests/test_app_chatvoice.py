"""Reading party and raid chat aloud, as the page does it (chatvoice.js).

The queue, the ducking and the reader are pure: every browser object they
touch is handed in, so node drives them here with fakes. What is pinned is
the rate limit the ticket asks for (one line at a time, stale lines dropped,
repeats skipped, queue capped), the duck that always lifts, and a reader that
never speaks the backlog it finds when it is switched on.

Ticket: 177.
"""

import shutil
import unittest

from test_app_shell import node_module

NODE = unittest.skipUnless(
    shutil.which("node"), "node is needed to run the app's modules"
)


def run(script, prelude=""):
    return node_module(
        "views/now/chatvoice.js",
        prelude + "\nconsole.log(JSON.stringify(" + script + "));",
    )


def run_async(body, prelude):
    """`body` is an async function's body; what it returns is printed."""
    return node_module(
        "views/now/chatvoice.js",
        prelude
        + "\n(async () => {"
        + body
        + "})().then((r) => console.log(JSON.stringify(r)));",
    )


def line(speaker="Grug", text="Aye.", at=0):
    return "{speaker: %r, text: %r, heardAt: %d, voice: {pitch: 1, rate: 1}}" % (
        speaker,
        text,
        at,
    )


@NODE
class Queue(unittest.TestCase):
    def test_one_line_at_a_time(self):
        got = run(
            "[q.take(0).text, q.take(0), (q.done(), q.take(0).text)]",
            "const q = M.makeQueue(); q.offer(%s, 0); q.offer(%s, 0);"
            % (line(text="one"), line(text="two")),
        )
        self.assertEqual(got, ["one", None, "two"])

    def test_a_stale_line_is_dropped_when_its_turn_comes(self):
        got = run(
            "[q.take(M.STALE_MS + 1).text, q.size()]",
            "const q = M.makeQueue(); q.offer(%s, 0); q.offer(%s, M.STALE_MS);"
            % (line(text="old", at=0), line(text="new", at=20000)),
        )
        self.assertEqual(got, ["new", 0])

    def test_a_line_already_stale_on_arrival_is_refused(self):
        got = run(
            "[q.offer(%s, M.STALE_MS + 1), q.size()]" % line(at=0),
            "const q = M.makeQueue();",
        )
        self.assertEqual(got, ["stale", 0])

    def test_a_repeat_from_the_same_speaker_is_skipped(self):
        got = run(
            "[q.offer(%s, 0), q.offer(%s, 1000), q.offer(%s, 1000), q.size()]"
            % (line(), line(at=1000), line(speaker="Ugga", at=1000)),
            "const q = M.makeQueue();",
        )
        self.assertEqual(got, ["queued", "repeat", "queued", 2])

    def test_the_same_words_may_come_again_after_the_window(self):
        later = 60000 + 1
        got = run(
            "[q.offer(%s, 0), q.offer(%s, %d)]" % (line(), line(at=later), later),
            "const q = M.makeQueue();",
        )
        self.assertEqual(got, ["queued", "queued"])

    def test_the_queue_is_capped_and_the_oldest_falls_off(self):
        got = run(
            "[q.size() === M.QUEUE_CAP, q.take(0).text]",
            "const q = M.makeQueue();"
            "for (let i = 0; i <= M.QUEUE_CAP; i++) q.offer({speaker: 'Grug', text: 'l' + i, heardAt: 0}, 0);",
        )
        self.assertEqual(got, [True, "l1"])

    def test_a_row_is_heard_its_age_ago(self):
        got = run(
            "M.lineFromRow({speaker: 'Bork', text: 'Hi', age_s: 3, voice: {pitch: 1.5}}, 10000)",
        )
        self.assertEqual(
            got,
            {"speaker": "Bork", "text": "Hi", "heardAt": 7000, "voice": {"pitch": 1.5}},
        )

    def test_an_unmeasured_age_is_heard_now(self):
        got = run(
            "M.lineFromRow({speaker: 'Bork', text: 'Hi', age_s: null, voice: {}}, 10000).heardAt"
        )
        self.assertEqual(got, 10000)


@NODE
class Duck(unittest.TestCase):
    def test_the_stream_is_lowered_then_restored(self):
        got = run(
            "[(r = M.duck(v, M.DUCK_VOLUME), v.volume), (r(), v.volume)]",
            "const v = {muted: false, volume: 0.8}; let r;",
        )
        self.assertEqual(got, [0.25, 0.8])

    def test_a_muted_stream_is_never_unmuted_or_touched(self):
        got = run(
            "(M.duck(v, M.DUCK_VOLUME)(), v)",
            "const v = {muted: true, volume: 0.8};",
        )
        self.assertEqual(got, {"muted": True, "volume": 0.8})

    def test_a_quiet_stream_is_never_raised_to_the_duck(self):
        got = run(
            "[(r = M.duck(v, M.DUCK_VOLUME), v.volume), (r(), v.volume)]",
            "const v = {muted: false, volume: 0.1}; let r;",
        )
        self.assertEqual(got, [0.1, 0.1])

    def test_no_stream_heard_is_nothing_to_duck(self):
        got = run("typeof M.duck(null, M.DUCK_VOLUME)")
        self.assertEqual(got, "function")


@NODE
class PickVoice(unittest.TestCase):
    VOICES = (
        "const voices = [{name: 'Juan', lang: 'es-ES'}, {name: 'Daniel', lang: 'en-GB'},"
        " {name: 'Samantha', lang: 'en-US'}];"
    )

    def test_the_hinted_gender_is_preferred(self):
        got = run(
            "[M.pickVoice(voices, 'en-female').name, M.pickVoice(voices, 'en-male').name]",
            self.VOICES,
        )
        self.assertEqual(got, ["Samantha", "Daniel"])

    def test_the_language_wins_when_no_gender_is_known(self):
        self.assertEqual(run("M.pickVoice(voices, 'en').name", self.VOICES), "Daniel")

    def test_no_voice_in_the_language_leaves_the_browser_default(self):
        self.assertIsNone(run("M.pickVoice(voices, 'de-male')", self.VOICES))


# A fake browser: fetch answers from a script, speechSynthesis records what it
# was asked to say and lets the test end (or fail) the line.
FAKE = """
const said = [];
let current = null;
const video = {muted: false, volume: 1};
const synth = {
  speak(u) { said.push({text: u.text, pitch: u.pitch, rate: u.rate}); current = u; },
  cancel() { if (current) { const u = current; current = null; u.onerror({error: 'canceled'}); } },
  getVoices() { return []; },
};
class Utterance { constructor(text) { this.text = text; } }
const answers = %s;
const asked = [];
let clock = 100000;
const reader = M.makeReader({
  fetchJson: async (path) => { asked.push(path); return answers.shift() || {rows: [], after: 0}; },
  families: () => ['Grug'],
  video: () => video,
  synth, Utterance,
  now: () => clock,
  setTimer: () => 1, clearTimer: () => {},
  warn: () => {},
});
"""

ROW = "{id: %d, speaker: 'Grug', text: %r, channel: 'party', age_s: 1, voice: {pitch: 0.7, rate: 0.85, engine_voice_hint: 'en-male'}}"


def fake(answers):
    return FAKE % answers


@NODE
class Reader(unittest.TestCase):
    def test_switching_on_primes_the_cursor_and_speaks_no_backlog(self):
        got = run_async(
            "await reader.start(); await reader.poll(); return [asked, said.length];",
            fake("[{rows: [], after: 40}, {rows: [], after: 40}]"),
        )
        self.assertEqual(
            got,
            [
                ["/api/chat/party?family=Grug", "/api/chat/party?family=Grug&after=40"],
                0,
            ],
        )

    def test_a_line_is_spoken_in_its_voice_with_the_stream_ducked(self):
        got = run_async(
            "await reader.start(); await reader.poll(); const during = video.volume;"
            " current.onend(); return [said, during, video.volume];",
            fake(
                "[{rows: [], after: 40}, {rows: [%s], after: 41}]" % (ROW % (41, "Ug."))
            ),
        )
        self.assertEqual(got, [[{"text": "Ug.", "pitch": 0.7, "rate": 0.85}], 0.25, 1])

    def test_an_error_mid_line_still_lifts_the_duck_and_moves_on(self):
        got = run_async(
            "await reader.start(); await reader.poll();"
            " current.onerror({error: 'synthesis-failed'}); const after1 = video.volume;"
            " current.onend(); return [said.map((s) => s.text), after1, video.volume];",
            fake(
                "[{rows: [], after: 40}, {rows: [%s, %s], after: 42}]"
                % (ROW % (41, "One."), ROW % (42, "Two."))
            ),
        )
        self.assertEqual(got, [["One.", "Two."], 0.25, 1])

    def test_switching_off_stops_the_line_and_restores_the_stream(self):
        got = run_async(
            "await reader.start(); await reader.poll(); reader.stop();"
            " return [reader.on(), video.volume, said.length];",
            fake(
                "[{rows: [], after: 40}, {rows: [%s, %s], after: 42}]"
                % (ROW % (41, "One."), ROW % (42, "Two."))
            ),
        )
        self.assertEqual(got, [False, 1, 1])

    def test_it_is_off_until_asked(self):
        self.assertEqual(
            run("[reader.on(), asked.length, said.length]", fake("[]")), [False, 0, 0]
        )


if __name__ == "__main__":
    unittest.main()

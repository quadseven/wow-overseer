"""Black-frame detection for the live wall.

The WHEP stream can be connected and still show a black picture: a minimized
game client, an asleep display, or a loading screen all produce valid black
frames that read as healthy because the video keeps arriving. The browser
samples the rendered video and reports when the picture stays dark, so the
panel can say why instead of "LIVE".
"""

import pathlib
import shutil
import unittest

from test_app_shell import node_module
from test_now_tile_panels import run as browser_run

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

NODE = unittest.skipUnless(
    shutil.which("node"), "node is needed to run the app's modules"
)


def run(module, script):
    return node_module(
        "views/now/" + module, "console.log(JSON.stringify(" + script + "));"
    )


@NODE
class MeanBrightness(unittest.TestCase):
    def test_a_black_frame_is_dark(self):
        got = run(
            "dark.js",
            "M.isDarkFrame({data: new Uint8ClampedArray([0,0,0,255, 0,0,0,255]), width: 2, height: 1})",
        )
        self.assertTrue(got)

    def test_a_bright_frame_is_not_dark(self):
        got = run(
            "dark.js",
            "M.isDarkFrame({data: new Uint8ClampedArray([200,200,200,255, 200,200,200,255]), width: 2, height: 1})",
        )
        self.assertFalse(got)

    def test_mean_brightness_uses_luma(self):
        # Pure blue has low luma; pure yellow has high luma.
        got = run(
            "dark.js",
            "[M.meanBrightness({data: new Uint8ClampedArray([0,0,255,255]), width: 1, height: 1}),"
            " M.meanBrightness({data: new Uint8ClampedArray([255,255,0,255]), width: 1, height: 1})]",
        )
        self.assertLess(got[0], got[1])

    def test_the_threshold_is_a_small_number(self):
        got = run("dark.js", "M.DARK_THRESHOLD")
        self.assertGreater(got, 0)
        self.assertLess(got, 50)


@NODE
class ThePanelText(unittest.TestCase):
    def test_the_reason_says_the_picture_is_black(self):
        got = run("dark.js", "M.darkReason()")
        lower = got.lower()
        self.assertIn("black", lower)
        self.assertIn("asleep", lower)
        self.assertIn("loading", lower)


class TheStreamModuleWiresIt(unittest.TestCase):
    def test_streams_imports_the_detector(self):
        src = (APP / "views" / "now" / "streams.js").read_text(encoding="utf-8")
        self.assertIn("darkSampler", src)
        self.assertIn("darkReason", src)

    def test_streams_has_a_dark_state(self):
        src = (APP / "views" / "now" / "streams.js").read_text(encoding="utf-8")
        self.assertIn('state === "dark"', src)
        self.assertIn('"DARK"', src)
        self.assertIn('"Picture is dark"', src)

    def test_the_dark_state_has_a_badge_colour(self):
        css = (APP / "views" / "now.css").read_text(encoding="utf-8")
        self.assertIn('[data-state="dark"]', css)
        self.assertIn("var(--warn)", css)


# A <canvas> whose 2d context hands back whatever frame the test puts in
# `globalThis.frame`, and a window whose setInterval keeps the sampler's tick
# so the test can step it by hand.
FAKE_CANVAS = r"""
const solid = (v) => ({data: new Uint8ClampedArray([v,v,v,255, v,v,v,255]), width: 2, height: 1});
globalThis.BLACK = solid(0);
globalThis.BRIGHT = solid(200);
globalThis.frame = BRIGHT;
const ticks = [];
globalThis.tick = () => ticks.forEach((f) => f());
const makeCanvas = () => ({
  width: 0, height: 0,
  getContext: () => ({drawImage() {}, getImageData: () => globalThis.frame}),
});
"""

SAMPLER = (
    FAKE_CANVAS
    + r"""
globalThis.window = {setInterval: (f) => { ticks.push(f); return ticks.length; }, clearInterval: () => { ticks.length = 0; }};
globalThis.document = {createElement: (t) => (t === "canvas" ? makeCanvas() : {})};
const video = {videoWidth: 160, videoHeight: 90, readyState: 4};
const seen = [];
const s = M.darkSampler(video, (dark) => seen.push(dark));
const log = {};
s.start();
log.bright = seen.slice();
frame = BLACK; tick(); tick();
log.twoDark = seen.slice();
tick();
log.threeDark = seen.slice();
tick();
log.stillDark = seen.slice();
frame = BRIGHT; tick();
log.backToBright = seen.slice();
frame = BLACK; tick(); tick(); tick();
s.stop();
log.afterStop = seen.slice();
log.ticksAfterStop = ticks.length;
"""
)


@NODE
class TheSampler(unittest.TestCase):
    """darkSampler driven over a fake video: it says dark only after a streak
    of dark frames, says it once, and says not dark on the first bright one."""

    @classmethod
    def setUpClass(cls):
        cls.got = run("dark.js", "(() => {" + SAMPLER + "return log; })()")

    def test_a_bright_picture_says_nothing(self):
        self.assertEqual(self.got["bright"], [])

    def test_a_short_dark_run_is_not_enough(self):
        self.assertEqual(self.got["twoDark"], [])

    def test_a_streak_of_dark_frames_turns_it_dark_once(self):
        self.assertEqual(self.got["threeDark"], [True])
        self.assertEqual(self.got["stillDark"], [True])

    def test_one_bright_frame_turns_it_back(self):
        self.assertEqual(self.got["backToBright"], [True, False])

    def test_stop_ends_the_sampling(self):
        self.assertEqual(self.got["afterStop"], [True, False, True])
        self.assertEqual(self.got["ticksAfterStop"], 0)


# The tile's own sampler: a live picture that goes black says DARK and why,
# and says LIVE again when the picture comes back. The WHEP handshake never
# answers; the test hands the PeerConnection its track itself.
TILE_DARK = (
    FAKE_CANVAS
    + r"""
window.setInterval = (f) => { ticks.push(f); return ticks.length; };
window.clearInterval = () => { ticks.length = 0; };
const make = document.createElement;
document.createElement = (t) => (t === "canvas" ? makeCanvas() : make(t));
let pc = null;
globalThis.RTCPeerConnection = class {
  constructor() { pc = this; }
  addTransceiver() {} addEventListener() {} removeEventListener() {} close() {}
  createOffer() { return new Promise(() => {}); }
};
const slot = new El("div");
slot.getAttribute = (k) => (k === "data-stream" ? "Grug" : null);
M.mount({ querySelectorAll: (sel) => (sel === "[data-stream]" ? [slot] : []) });
const pic = slot.firstChild;
const video = pic.children.find((c) => c.className === "st-video");
const badge = pic.children.find((c) => c.className === "st-badge");
const off = pic.children.find((c) => c.className === "st-off");
Object.assign(video, {videoWidth: 160, videoHeight: 90, readyState: 4});
const look = () => ({state: pic.dataset.state, badge: badge.lastChild.textContent,
                     title: off.children[1].textContent, body: off.children[2].textContent});
M.connect("Grug", "http://media.example/grug");
pc.ontrack({streams: [{}]});
const out = {live: look()};
frame = BLACK; tick(); tick(); tick();
out.dark = look();
frame = BRIGHT; tick();
out.back = look();
console.log(JSON.stringify(out));
"""
)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheTileGoesDark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = browser_run("views/now/streams.js", TILE_DARK)

    def test_it_starts_live(self):
        self.assertEqual(self.got["live"]["state"], "live")
        self.assertEqual(self.got["live"]["badge"], "LIVE")

    def test_a_black_picture_says_dark_and_why(self):
        d = self.got["dark"]
        self.assertEqual(d["state"], "dark")
        self.assertEqual(d["badge"], "DARK")
        self.assertEqual(d["title"], "Picture is dark")
        self.assertIn("black", d["body"].lower())

    def test_the_picture_coming_back_says_live_again(self):
        b = self.got["back"]
        self.assertEqual(b["state"], "live")
        self.assertEqual(b["badge"], "LIVE")
        self.assertEqual(b["body"], "")


if __name__ == "__main__":
    unittest.main()

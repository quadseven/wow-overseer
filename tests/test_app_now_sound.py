"""The Watch view's sound gate: hasSound() over a WHEP stream's tracks.

A streamed character carries his own audio track, not a desktop mix. The
Watch view exposes a muted-by-default Hear control (streams.js), pinned by
HearControl below, and the player's sound gate is hasSound() in whep.js: a
live, unmuted audio track.
A remote track reports muted while no packets flow, and a character whose
sound server is absent still streams video: video-only means no sound, not
no picture.
"""

import shutil
import unittest

from test_app_shell import node_module
from test_now_tile_panels import run as browser_run

NODE = unittest.skipUnless(
    shutil.which("node"), "node is needed to run the app's modules"
)

JS = r"""
const videoOnly = {
  srcObject: {
    getVideoTracks: () => [{ readyState: "live" }],
    getAudioTracks: () => [],
  },
};
const live = {
  srcObject: { getAudioTracks: () => [{ readyState: "live", muted: false }] },
};
const muted = {
  srcObject: { getAudioTracks: () => [{ readyState: "live", muted: true }] },
};
const ended = {
  srcObject: { getAudioTracks: () => [{ readyState: "ended", muted: false }] },
};
const nosrc = {};
const notracks = { srcObject: {} };
console.log(JSON.stringify([
  M.hasSound(videoOnly),
  M.hasSound(live),
  M.hasSound(muted),
  M.hasSound(ended),
  M.hasSound(nosrc),
  M.hasSound(notracks),
]));
"""


def run():
    return node_module("views/now/whep.js", JS)


@NODE
class HasSound(unittest.TestCase):
    def test_video_only_stream_has_no_sound(self):
        got = run()
        # A video-only stream (a live video track, no audio tracks) is silent.
        # If hasSound() throws here the test fails: a silent character still
        # streams video rather than failing.
        self.assertIs(got[0], False)

    def test_live_unmuted_audio_track_has_sound(self):
        got = run()
        self.assertIs(got[1], True)

    def test_muted_audio_track_has_no_sound_yet(self):
        got = run()
        self.assertIs(got[2], False)

    def test_ended_audio_track_has_no_sound(self):
        got = run()
        self.assertIs(got[3], False)

    def test_no_src_object_is_silent(self):
        got = run()
        self.assertIs(got[4], False)

    def test_src_object_without_audio_tracks_is_silent(self):
        got = run()
        self.assertIs(got[5], False)


# The Watch view's audio control: every tile starts muted, so opening the
# Family view starts no sound, and Hear makes exactly one tile heard.
HEAR = r"""
const slot = (name) => {
  const s = new El("div");
  s.getAttribute = (k) => (k === "data-stream" ? name : null);
  return s;
};
const slots = [slot("Grug"), slot("Zug")];
M.mount({ querySelectorAll: (sel) => (sel === "[data-stream]" ? slots : []) });
const videos = slots.map((s) => s.firstChild.children.find((c) => c.className === "st-video"));
const look = () => videos.map((v) => v.muted);
const out = { opened: look(), attr: videos.map((v) => v.hasAttribute("muted")) };
M.toggleHear("Grug"); out.grug = look();
M.toggleHear("Zug"); out.zug = look();
M.toggleHear("Zug"); out.off = look();
console.log(JSON.stringify(out));
"""


@NODE
class HearControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = browser_run("views/now/streams.js", HEAR)

    def test_every_tile_opens_muted(self):
        self.assertEqual(self.got["opened"], [True, True])
        self.assertEqual(self.got["attr"], [True, True])

    def test_hear_unmutes_only_that_tile(self):
        self.assertEqual(self.got["grug"], [False, True])
        self.assertEqual(self.got["zug"], [True, False])

    def test_hear_again_mutes_it(self):
        self.assertEqual(self.got["off"], [True, True])


if __name__ == "__main__":
    unittest.main()

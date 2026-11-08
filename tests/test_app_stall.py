"""A stream tile whose frames have stalled must not claim LIVE.

The WHEP picture can stay connected while frames stop painting (the
caption sits at "frame 2s old" and climbs). streams.js already records
each tile's last painted frame; the picture-health seam in dark.js decides
from that record when a live tile is in fact stalled, so the badge can say
STALLED until a frame paints again.
"""

import json
import pathlib
import shutil
import unittest

from test_app_shell import node_module

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

NODE = unittest.skipUnless(
    shutil.which("node"), "node is needed to run the app's modules"
)


def run(script):
    return node_module(
        "views/now/dark.js", "console.log(JSON.stringify(" + script + "));"
    )


@NODE
class FrameStalled(unittest.TestCase):
    def test_a_fresh_frame_is_not_stalled(self):
        self.assertFalse(run("M.frameStalled('live', 10000, 11000)"))

    def test_a_frame_older_than_the_threshold_is_stalled(self):
        got = run("M.frameStalled('live', 10000, 10000 + M.STALL_MS + 1)")
        self.assertTrue(got)

    def test_exactly_at_the_threshold_is_not_stalled_yet(self):
        got = run("M.frameStalled('live', 10000, 10000 + M.STALL_MS)")
        self.assertFalse(got)

    def test_a_tile_that_never_painted_is_not_stalled(self):
        self.assertFalse(run("M.frameStalled('live', 0, 999999)"))

    def test_only_a_live_tile_can_be_stalled(self):
        for state in ("off", "connecting", "dark"):
            self.assertFalse(
                run(
                    "M.frameStalled({}, 10000, 999999)".format(
                        repr(state).replace("'", '"')
                    )
                )
            )

    def test_the_threshold_is_a_few_seconds(self):
        got = run("M.STALL_MS")
        self.assertGreaterEqual(got, 2000)
        self.assertLessEqual(got, 10000)


@NODE
class BadgeWord(unittest.TestCase):
    def test_a_live_tile_with_fresh_frames_says_live(self):
        self.assertEqual(run("M.badgeWord('live', false)"), "LIVE")

    def test_a_stalled_live_tile_says_stalled(self):
        self.assertEqual(run("M.badgeWord('live', true)"), "STALLED")

    def test_recovery_is_the_same_word_flipping_back(self):
        got = run("[M.badgeWord('live', true), M.badgeWord('live', false)]")
        self.assertEqual(got, ["STALLED", "LIVE"])

    def test_other_states_are_not_this_functions_business(self):
        for state in ("off", "connecting", "dark"):
            self.assertIsNone(run(f"M.badgeWord({json.dumps(state)}, true)"))

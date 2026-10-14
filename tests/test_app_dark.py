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


if __name__ == "__main__":
    unittest.main()

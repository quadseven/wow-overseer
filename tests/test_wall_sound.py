"""The Watch wall's sound toggle, asserted against the page as text.

Same seam as test_raid_tab.py and test_watch_wall_tab.py: index.html has no
other test seam, so it is read as text and sliced to the block in question.

The operator asked why the site kept making little ping sounds. The toggle
synthesised a tone on every fight and every death, over the game audio the
operator actually wanted to hear. So the page makes no sound of its own any
more, and "sound on" means one thing: unmute ONE stream, the game client the
operator chose.

Four rules are pinned here:

  no synthesis        no oscillator, no AudioContext, no cue function
  one stream          every tile is muted but the chosen one
  a click first       nothing is audible on load, whatever was stored
  honest silence      a stream with no audio track says so
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(HERE, "index.html"), encoding="utf-8") as _fh:
    PAGE = _fh.read()
SCRIPTS = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script[^>]*>", PAGE, re.S | re.I)
APP = max(SCRIPTS, key=len)


def code(block):
    """`block` with its whole-line comments dropped, so a comment that names
    the thing it forbids cannot trip the guard against it."""
    return "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("//")
    )


def function(name):
    body = APP[APP.index("function " + name + "(") :]
    return body[: body.index("\n}") + 2]


def absent(case, needle, haystack, where):
    case.assertFalse(needle in haystack, "%r found in %s" % (needle, where))


class ThePageMakesNoSoundOfItsOwn(unittest.TestCase):
    def test_no_synthesised_tone_anywhere(self):
        for needle in (
            "wallCue",
            "createOscillator",
            "AudioContext",
            "new Audio(",
            "<audio",
        ):
            absent(self, needle, code(APP), "the page script")
        absent(self, "<audio", PAGE, "index.html")

    def test_the_toggle_no_longer_promises_a_tone(self):
        button = PAGE[PAGE.index('<button id="wallsound"') :]
        button = button[: button.index("</button>")]
        absent(self, "synthesised", button, "the sound button")
        self.assertIn("one stream", button)


class OnlyOneStreamIsHeard(unittest.TestCase):
    def test_every_tile_but_the_chosen_one_is_muted(self):
        body = code(function("wallApplyAudio"))
        self.assertIn("for (const [name, t] of broadcasts.tiles)", body)
        self.assertIn("const audible = name === ear;", body)
        self.assertIn("t.video.muted = !audible;", body)

    def test_the_heard_tile_is_the_choice_else_the_hero(self):
        body = code(function("wallEarName"))
        self.assertIn("wall.names.indexOf(chosen) >= 0 ? chosen : wall.hero", body)

    def test_promoting_a_tile_makes_it_the_heard_one(self):
        self.assertIn("wallHear(name);", function("promote"))

    def test_each_tile_has_its_own_speaker_control(self):
        slot = code(function("wallSlot"))
        self.assertIn('el("button", "povear", "HEAR")', slot)
        self.assertIn("wallHear(name);", slot)
        self.assertIn("wallApplyAudio();", slot)
        self.assertIn(".povear {", PAGE)

    def test_leaving_the_wall_mutes_everything(self):
        """The same tiles move into the Family cards, which have no control
        to silence them."""
        body = code(function("wallApplyAudio"))
        self.assertIn("wall.sound && view === WATCH_VIEW ? wallEarName() : null", body)

    def test_every_layout_pass_reapplies_the_choice(self):
        """A reconnecting stream gets a fresh MediaStream; the mute state has
        to be put right on the next poll, not only on the next click."""
        self.assertIn("wallApplyAudio();", function("layoutBroadcasts"))


class NothingIsAudibleBeforeAClick(unittest.TestCase):
    def test_startup_forces_sound_off(self):
        start = APP[APP.index("// Read once, at startup") :][:400]
        self.assertIn("wall.sound = false;", start)

    def test_only_a_click_turns_it_on(self):
        on = [
            m.start() for m in re.finditer(r"wall\.sound = (?:true|!wall\.sound)", APP)
        ]
        self.assertEqual(len(on), 2, "sound switched on outside the two click handlers")
        self.assertIn(
            "wall.sound = !wall.sound;", APP[APP.index("wallsound.onclick") :][:200]
        )
        self.assertIn("wall.sound = true;", APP[APP.index("ear.onclick") :][:300])

    def test_every_video_is_still_created_muted(self):
        tile = function("broadcastTile")
        self.assertIn("video.muted = true;", tile)
        self.assertIn('video.setAttribute("muted", "")', tile)

    def test_the_choice_is_stored_through_the_wrapped_helpers(self):
        self.assertIn('const WALL_EAR_KEY = "overseer-wall-ear";', APP)
        self.assertIn("wallStore(WALL_EAR_KEY, name);", function("wallHear"))
        absent(self, "localStorage", code(function("wallHear")), "wallHear")


class AStreamWithNoSoundSaysSo(unittest.TestCase):
    def test_audio_tracks_are_read_off_the_media_stream(self):
        body = code(function("streamHasSound"))
        self.assertIn("video.srcObject", body)
        self.assertIn("getAudioTracks()", body)
        self.assertIn('tr.readyState === "live" && !tr.muted', body)

    def test_the_sentence_is_shown_rather_than_silence(self):
        body = code(function("wallApplyAudio"))
        self.assertIn('"\'s stream has no sound yet"', body)
        self.assertIn("wallsoundnote.textContent = say", body)
        self.assertIn('id="wallsoundnote"', PAGE)


if __name__ == "__main__":
    unittest.main()

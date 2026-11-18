"""Pressing Watch must never leave the Now page covered by a dead picture.

The Watcher card (app/views/_spectate.js) puts its picture slot inside the Now
page, and Now's wall (app/views/now/streams.js) moves a living picture into
every slot it finds. When the Watcher's slot carried the wall's own
`data-stream` attribute, the wall took it for a family tile: it built a tile
named after the stream address, never connected it ("No picture", OFF), and
its absolutely placed picture stretched over the whole page, since the
Watcher's slot is not a positioned box. These pin the two halves apart, and
what the card says while the Watcher has no picture.
"""

import json
import re
import unittest

from test_app_flagship import app_file, needs_node
from test_app_spectate import STREAM, cam, markup
from test_now_tile_panels import run as browser_run

ON = {"data": {"enabled": True}, "loading": False}


def stage(sp, op=ON):
    return markup("S.stage(%s, [], %s, true)" % (json.dumps(sp), json.dumps(op)))


WATCHING_ZORK = dict(
    active=True,
    character="Zork",
    spec="character Zork",
    target="Zork",
    note="Zork: hold, moves are rate limited (budget spent)",
    state="held",
    arrived=False,
    watcher="Watcher",
)


@needs_node
class TheWatcherSlotIsNotAWallSlot(unittest.TestCase):
    def test_the_card_has_no_wall_slot_attribute(self):
        m = stage(cam(**WATCHING_ZORK))
        self.assertIn("data-spectate-slot", m)
        self.assertIsNone(re.search(r"\sdata-stream=", m), m)
        self.assertIn('data-spectate-stream="%s"' % STREAM, m)

    def test_the_wall_skips_a_watcher_slot_even_if_it_carries_data_stream(self):
        got = browser_run(
            "views/now/streams.js",
            r"""
const slot = new El("div");
slot.setAttribute("data-spectate-slot", "");
slot.setAttribute("data-stream", "%s");
M.mount({ querySelectorAll: (sel) => (sel === "[data-stream]" ? [slot] : []) });
console.log(JSON.stringify({ children: slot.children.length, state: M.stateOf("%s") }));
"""
            % (STREAM, STREAM),
        )
        self.assertEqual(got["children"], 0)

    def test_a_family_slot_is_still_mounted(self):
        got = browser_run(
            "views/now/streams.js",
            r"""
const slot = new El("div");
slot.setAttribute("data-stream", "Grug");
M.mount({ querySelectorAll: (sel) => (sel === "[data-stream]" ? [slot] : []) });
console.log(JSON.stringify({ children: slot.children.length }));
""",
        )
        self.assertEqual(got["children"], 1)


@needs_node
class TheCardSaysWhyThereIsNoPicture(unittest.TestCase):
    def test_it_names_the_watcher_and_its_target(self):
        m = stage(cam(**WATCHING_ZORK))
        self.assertIn("Waiting to move to Zork", m)
        self.assertNotIn("Now watching Zork", m)

    def test_the_directors_reason_shows_even_with_a_target(self):
        m = stage(cam(**WATCHING_ZORK))
        self.assertIn("moves are rate limited", m)

    def test_the_picture_says_it_is_starting_before_it_plays(self):
        m = stage(cam(**WATCHING_ZORK))
        self.assertIn("Starting the Watcher's stream", m)

    def test_there_is_a_way_back(self):
        m = stage(cam(**WATCHING_ZORK))
        self.assertIn("data-spectate-stop", m)
        self.assertIn("Stop watching", m)


class TheStyle(unittest.TestCase):
    def test_the_watcher_slot_contains_what_is_put_in_it(self):
        css = app_file("views/spectate.css")
        rule = re.search(r"\.sp-slot\s*\{([^}]*)\}", css)
        self.assertIsNotNone(rule)
        self.assertIn("position: relative", rule.group(1))


if __name__ == "__main__":
    unittest.main()

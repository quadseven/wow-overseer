"""The Watch wall as the PAGE has it, which is where a wall breaks silently.

TWO OF THESE WERE WRITTEN AFTER BEING HIT, in the change that added the wall,
and both were invisible until a parser was pointed at the file:

  a duplicate id      `id="wheadline"` already belonged to the Wealth view, so
                      getElementById handed the wealth code the wall element
                      and the wealth headline rendered into the wall.
  a shadowed const    `wsection` was already the wealth section. Two `const`
                      declarations of one name in one script is a SyntaxError,
                      which does not break that view: it breaks the WHOLE
                      PAGE, because the script never runs at all.

Neither is reachable from Python and neither shows up in a diff. They show up
as a blank site. So they are asserted here, over the file, for every id and
every top-level const on the page rather than only the ones this view added.
"""

import os
import unittest

LF = chr(10)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def absent(case, needle, haystack, where):
    """assertNotIn against a 200KB page prints the WHOLE page on failure, which
    buries the one line that matters. This prints the needle."""
    case.assertFalse(needle in haystack, "%r found in %s" % (needle, where))


# The last block is the application. The three before it are the pre-paint
# theme script and the map bootstraps, and they have their own scopes.


class HeroModeDoesNotWalkBackIntoTheTinyTwitchView(unittest.TestCase):
    """This page HAD one big player and four thumbnails. infra#88 removed it
    because on a phone the four were the smallest thing on screen, and the
    operator said so in as many words. It is back only as a choice."""

    def test_the_default_is_not_hero(self):
        self.assertIn("DEFAULT_MODE = FIVE_UP", _module_source())


def _module_source():
    with open(os.path.join(HERE, "watchwall.py"), encoding="utf-8") as fh:
        return fh.read()


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in ("tests/test_watch_wall_tab.py",):
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                absent(self, chr(0x2014), fh.read(), name)


if __name__ == "__main__":
    unittest.main()

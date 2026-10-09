"""The page has a light mode and a dark mode, and neither can go missing.

WHY THIS IS A SOURCE-READING SUITE rather than a rendering one. A theme is
almost entirely CSS, and the failure it has is not "the wrong colour" but "a
colour that only exists in one branch". A token defined only inside a media
query is invisible to a reader whose system preference does not match, and the
symptom is one theme's text on the other theme's ground, which no unit test that
imports Python would ever see. So these assert the SHAPE of the cascade, which
is the part that breaks silently.
"""

import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in ("tests/test_theme.py",):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )


if __name__ == "__main__":
    unittest.main()

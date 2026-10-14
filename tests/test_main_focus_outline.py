"""The main content area draws no focus outline when a script focuses it.

On each route change main.js focuses <main tabindex="-1"> (with
preventScroll, for screen readers); Chrome treats that programmatic focus
as :focus-visible, and the general rule painted a 2px ring around the whole
main element. Its left and top edges hide under the sidebar and the top of
the page, so only the right edge showed, as a thin vertical bar. The
programmatic target draws no outline; keyboard rings elsewhere stay.
"""

import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
CSS = (HERE / "app" / "app.css").read_text(encoding="utf-8")


def rules():
    """The declarations of every rule in app.css, without comments."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


class TheMainFocusOutline(unittest.TestCase):
    def test_the_script_focus_target_draws_no_outline(self):
        found = False
        for selector, body in rules():
            sels = [s.strip() for s in selector.split(",")]
            if "main:focus-visible" in sels and '[tabindex="-1"]:focus-visible' in sels:
                self.assertRegex(body, r"outline:\s*none")
                found = True
        self.assertTrue(
            found, 'no main:focus-visible, [tabindex="-1"]:focus-visible rule'
        )

    def test_the_general_focus_ring_is_unchanged(self):
        self.assertIn(
            ":focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px;",
            CSS,
        )


if __name__ == "__main__":
    unittest.main()

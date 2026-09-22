"""A model that fails to build is retried, not remembered as built.

Same text seam as test_armory_tab.py. renderModel records the model's key
before it builds, and its catch kept that key, so a single failure at page
load made every later call return early: the first two profiles stayed
portraits for good while every card below them drew.

Tickets: #168.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")


class AFailedModelIsTriedAgain(unittest.TestCase):
    def setUp(self):
        body = PAGE[PAGE.index("async function renderModel(c, m)") :]
        self.body = body[: body.index("\n}\n")]
        self.catch = self.body[self.body.rindex("} catch (e) {") :]

    def test_the_catch_forgets_the_key(self):
        self.assertIn("c.modelKey = null;", self.catch)

    def test_the_catch_drops_a_half_built_viewer(self):
        self.assertIn("c.viewer = null;", self.catch)

    def test_the_failure_is_said_rather_than_swallowed(self):
        self.assertIn("console.warn(", self.catch)


if __name__ == "__main__":
    unittest.main()

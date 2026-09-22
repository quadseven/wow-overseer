"""RollQuiet hides the selfbot heads' roll windows and never rolls.

The streamed heads are selfbots: their playerbot AI rolls on the server, so the
client's own roll windows are never answered and stacked up on the stream. The
addon may only hide them. Rolling or passing from the client would race the AI
for the same roll.
"""

import pathlib
import unittest

ADDON = pathlib.Path(__file__).resolve().parent.parent / "wow-addons/PartyStatus"


class RollQuietOnlyHides(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lua = (ADDON / "RollQuiet.lua").read_text()
        cls.code = "".join(
            line for line in lua.splitlines(True) if not line.strip().startswith("--")
        )
        cls.toc = (ADDON / "PartyStatus.toc").read_text()

    def test_it_is_loaded(self):
        self.assertIn("RollQuiet.lua", self.toc.split())

    def test_it_hides_the_frames_as_they_open(self):
        self.assertIn('hooksecurefunc("GroupLootFrame_OpenNewFrame"', self.code)
        self.assertIn("f:Hide()", self.code)

    def test_it_never_rolls_or_passes(self):
        for call in ("RollOnLoot", "ConfirmLootRoll", "ConfirmLootSlot"):
            self.assertNotIn(call, self.code)


if __name__ == "__main__":
    unittest.main()

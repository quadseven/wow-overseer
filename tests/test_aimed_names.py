"""Who counts as having somewhere to be, and why it is not only a quest.

`bridge._aimed_names` decides which characters the strategy pass grants the
travel strategy to. Everyone it leaves out has `new rpg` taken back off them
within one cycle, and the module then cannot walk them anywhere.

Until 2026-09-07 it asked only for `drive_quest`, so a character carrying a
travel errand and no quest did not count. The live consequence, measured: one
follower was given `travel_npc = 'innkeeper'`, took the wheel, walked for
ninety seconds, was stripped of the strategy by the next strategy pass, and
then stood motionless for nineteen minutes with its errand still set until the
errand's own twenty-minute backstop released it as unreachable. The party
leader was refused the same way and logged the advice "aim the leader instead",
which was the character it had just refused.

The tell was that a sibling walked the identical errand successfully in the
same minute. He held `drive_quest = 101`; the others held 0. Nothing else
differed.

Asserted against bridge.py as source, the same way this suite guards the rest
of that module, because `_aimed_names` opens a database connection and there is
no other seam.

Ticket: infra#3409.
"""

import pathlib
import re
import unittest

BRIDGE = pathlib.Path(__file__).resolve().parent.parent / "bridge.py"


def _aimed_names_source() -> str:
    """The body of _aimed_names, up to the next top level def."""
    text = BRIDGE.read_text(encoding="utf-8")
    start = text.index("def _aimed_names(")
    rest = text[start:]
    nxt = re.search(r"\ndef ", rest)
    return rest[: nxt.start()] if nxt else rest


class AnErrandCountsAsSomewhereToBe(unittest.TestCase):
    def test_the_query_asks_for_a_travel_errand_too(self):
        """A character with an errand and no quest must count as aimed."""
        body = _aimed_names_source()
        self.assertIn(
            "travel_npc",
            body,
            "a character carrying a travel errand and no quest "
            "would not count as aimed, so the strategy pass takes "
            "`new rpg` back off it and nothing walks it anywhere",
        )

    def test_an_empty_errand_does_not_count(self):
        """The column is empty far more often than it is set.

        Treating '' as an aim would hand the wander strategy to every idle
        follower, which is the scatter this function exists to prevent: an
        unaimed follower given that strategy is what spread the family across a
        thousand yards with the healer in her own fight.
        """
        body = _aimed_names_source()
        self.assertRegex(body, r"travel_npc\s*<>\s*''")

    def test_the_quest_aim_still_counts(self):
        """The fix is additive. Removing the original condition would strand
        every character whose only aim is a quest."""
        self.assertIn("drive_quest <> 0", _aimed_names_source())

    def test_a_missing_column_still_degrades_to_leader_only(self):
        """The bridge deploys separately from the worldserver that applies the
        module's SQL, so either column can legitimately be absent. Returning an
        empty set is the safe direction and the warning is what stops it being
        silent."""
        body = _aimed_names_source()
        self.assertIn("1054", body)
        self.assertIn("return set()", body)


if __name__ == "__main__":
    unittest.main()

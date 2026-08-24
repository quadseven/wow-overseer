"""Two ways the family looked stupid while doing exactly as it was told.

SELLING. `sell junk` was in the vocabulary and is not a command.
mod-playerbots' SellAction accepts gray, *, vendor or an item link; anything
else falls through to an item-name lookup, matches nothing, sells nothing, and
returns TRUE. So the row said delivered, the character announced it was heading
to a vendor, and no grey item ever left a bag. Evan watched that happen twice.

QUESTING. The council settles on an objective and nothing turns that decision
into behaviour, so the goal supervisor's `grind` - "kill what is in front of
you" - remained the last instruction anybody gave. They were never being
stupid. They were obeying.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import voice  # noqa: E402

# SellAction::Execute compares the argument against exactly these, in this
# order, before falling through to parseItems().
SELL_ARGS = {"gray", "*", "vendor"}


class TheSellCommandIsOneThatExists(unittest.TestCase):
    def test_no_sell_entry_uses_an_argument_sellaction_rejects(self):
        for command in voice.VOCABULARY:
            parts = command.split()
            if parts[0] != "sell" or len(parts) < 2:
                continue
            self.assertIn(
                parts[1], SELL_ARGS,
                f"'{command}' is not a SellAction argument; it will sell nothing "
                f"and report success. Valid: {sorted(SELL_ARGS)}",
            )

    def test_selling_greys_is_still_offered(self):
        """The capability has to survive the correction, not just the bug."""
        self.assertTrue(
            any(c.startswith("sell ") for c in voice.VOCABULARY),
            "nothing in the vocabulary sells anything any more",
        )

    def test_the_dead_command_is_gone(self):
        self.assertNotIn("sell junk", voice.VOCABULARY)


MODULE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
)


def _live_source() -> str:
    """The module with // comments stripped.

    Searching the raw text is not a reachability test: commenting the call out
    leaves the string intact, so the guard passed against a mutant that had
    disabled the very thing it was guarding. Found by mutating it, which is the
    only reason this function exists.
    """
    out = []
    for line in MODULE.read_text(encoding="utf-8").splitlines():
        stripped = line.split("//", 1)[0]
        out.append(stripped)
    return "\n".join(out)


def _drive_quests() -> str:
    src = MODULE.read_text(encoding="utf-8")
    start = src.index("void DriveQuests()")
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("DriveQuests has no closing brace")


class TheQuestDriverPointsThemAtTheObjective(unittest.TestCase):
    def test_it_is_reachable_from_the_update_loop(self):
        """A driver nobody calls leaves them grinding exactly as before."""
        src = _live_source()
        self.assertIn("DriveQuests();", src)
        self.assertIn("QUEST_POLL_MS", src)

    def test_it_sets_the_rpg_state_rather_than_asking_through_chat(self):
        """The chat command is gated on master-or-GM, which these never satisfy."""
        self.assertIn("ChangeToDoQuest", _drive_quests())

    def test_only_the_leader_picks_an_objective_of_its_own(self):
        """The scatter lesson still holds; the enforcement point moved
        (infra#2801, "quest together").

        Sending each of them to an objective INDIVIDUALLY scatters the family -
        the 937-yard spread the follow work fixed. What does not scatter them
        is sending them all to the SAME objective, which is what an aim does,
        and quest sharing already keeps their logs aligned so a shared aim is
        usually available.

        So the family is now aimable member by member - a follower that cannot
        be aimed can never turn a quest in, because turn-in is reachable only
        through the rpg strategy - while the divergent "pick from my own log"
        walk stays behind the leader gate.
        """
        body = _drive_quests()
        self.assertNotIn("`lead` = 1", body)
        self.assertLess(body.index("if (!isLead)"), body.index("MAX_QUEST_LOG_SIZE"))

    def test_a_character_already_on_a_quest_is_left_alone(self):
        """Re-issuing every poll restarts the travel, so it never arrives."""
        body = _drive_quests()
        self.assertIn("RPG_DO_QUEST", body)
        self.assertIn("continue", body)

    def test_it_only_picks_a_quest_there_is_something_to_do_about(self):
        body = _drive_quests()
        self.assertIn("QUEST_STATUS_INCOMPLETE", body)
        self.assertIn("QUEST_STATUS_COMPLETE", body)


if __name__ == "__main__":
    unittest.main()

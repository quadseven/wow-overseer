"""The family fields a tank and a healer, and the module cannot re-roll them.

WHY THIS FILE EXISTS. mod-playerbots already picks talents and learns trainer
spells on levelup, and every branch of that is behind IsRandomBot(), which these
named characters fail three separate ways. The config said AutoPickTalents = 1
and AutoLearnTrainerSpells = 1; both were read, and neither could ever reach
this family. What it looked like in game was a level 11 warrior with 13 spells
and one talent, and a level 9 paladin with NO spells at all.

So the roles are decided here now, and the tests below are about the two things
that can silently go wrong with that: a family that fields no tank or no healer
because somebody edited a number, and a training pass that "improves" itself
into calling the factory methods that re-roll a character's level and gear.
"""
import ast
import pathlib
import unittest

import bonds


# (class, tabpage) -> what that combination actually is in game. Written out
# rather than assumed, because the whole point of the test is to catch a tab
# number that no longer means what whoever typed it thought it meant.
TANK_SPECS = {
    ("warrior", 2),   # protection
    ("paladin", 1),   # protection
    ("druid", 1),     # feral
    ("dk", 0),        # blood
}
HEALER_SPECS = {
    ("priest", 0),    # discipline
    ("priest", 1),    # holy
    ("paladin", 0),   # holy
    ("druid", 2),     # restoration
    ("shaman", 2),    # restoration
}


def _specs():
    return [
        (bond.char_class, bond.spec_tab)
        for bond in bonds.FAMILY.values()
        if bond.spec_tab >= 0
    ]


class FamilyRoles(unittest.TestCase):
    def test_someone_in_the_family_is_a_tank(self):
        """Nobody holding aggro is why they die in a heap.

        Asserted as a ROLE and not as bonds.FAMILY["Grug"].spec_tab == 2, which
        would only restate the table it is reading. This fails if Grug is moved
        to arms or fury and nobody else picks up protection.
        """
        self.assertTrue(
            TANK_SPECS & set(_specs()),
            f"no tank in the family: {_specs()}",
        )

    def test_someone_in_the_family_is_a_healer(self):
        self.assertTrue(
            HEALER_SPECS & set(_specs()),
            f"no healer in the family: {_specs()}",
        )

    def test_every_member_has_a_tree_chosen(self):
        """A member left at -1 gets NO talents at all, forever, and silently.

        -1 is the right default for the column - a character added to the roster
        by something other than bonds should not have points spent on a guess -
        but for a named member of this family it means somebody forgot.
        """
        missing = [n for n, b in bonds.FAMILY.items() if b.spec_tab < 0]
        self.assertEqual([], missing, f"no talent tree chosen for: {missing}")

    def test_tabs_are_in_the_range_the_dbc_has(self):
        bad = {n: b.spec_tab for n, b in bonds.FAMILY.items() if not -1 <= b.spec_tab <= 2}
        self.assertEqual({}, bad, f"talent tab out of range 0-2: {bad}")

    def test_spec_tabs_omits_anyone_undecided(self):
        """-1 is not written back over the column's own default."""
        undecided = bonds.Bond(role="x", blood=False, seniority=1, char_class="rogue")
        original = dict(bonds.FAMILY)
        bonds.FAMILY["Nobody"] = undecided
        try:
            self.assertNotIn("Nobody", bonds.spec_tabs())
            self.assertIn("Grug", bonds.spec_tabs())
        finally:
            bonds.FAMILY.clear()
            bonds.FAMILY.update(original)


MODULE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
)

# PlayerbotFactory methods that re-roll a character. The roster exists to keep
# these five OFF the random-bot treadmill; a training pass that called any of
# these would hand them straight back to it and wipe the levels and gear this
# whole family has been playing for.
DESTRUCTIVE = ["Randomize", "ClearEverything", "RandomTeleport", "DestroyEquippedGear"]


def _train_roster_source() -> str:
    """The body of TrainRoster, by brace matching rather than by line count."""
    src = MODULE.read_text(encoding="utf-8")
    start = src.index("void TrainRoster()")
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("TrainRoster has no closing brace")


class TrainingIsAdditive(unittest.TestCase):
    def test_training_never_calls_anything_that_re_rolls_a_character(self):
        body = _train_roster_source()
        for call in DESTRUCTIVE:
            self.assertNotIn(
                call, body,
                f"TrainRoster calls {call}, which re-rolls the character it is "
                "supposed to be teaching",
            )

    def test_training_learns_from_the_real_trainer_tables(self):
        """InitAvailableSpells is the one that walks the trainer lists.

        Without it a character learns only what the class-spell init grants and
        still never sees a trainer's list, which is the exact hole this closes.
        """
        self.assertIn("InitAvailableSpells", _train_roster_source())

    def test_training_is_gated_so_it_does_not_run_every_poll(self):
        """The expensive walk runs on level change, not on every tick."""
        self.assertIn("trained_level", _train_roster_source())

    def test_the_talent_walk_is_reachable_from_training(self):
        """A SpendTalents nobody calls is talents nobody spends."""
        self.assertIn("SpendTalents(", _train_roster_source())


class ModuleParses(unittest.TestCase):
    def test_bonds_still_parses(self):
        ast.parse((pathlib.Path(bonds.__file__)).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

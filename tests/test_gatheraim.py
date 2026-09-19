"""Where the family is sent to raise a gathering skill, and what it refuses.

infra#3789. The two things these tests exist to hold down are the two that
caused real damage before: a destination must be a SURVEYED coordinate rather
than one this process computed, and an unmeasured zone must be refused rather
than assumed safe.
"""
import pathlib
import subprocess
import sys
import unittest

import gatheraim
import gatherband

TOOL = pathlib.Path(__file__).resolve().parents[1] / "tools" / "gather_bands_from_dbc.py"


def spawn(zone, lock, map_id=1, x=0.0, y=0.0, z=0.0, name=""):
    return gatheraim.Spawn(map_id=map_id, zone_id=zone, x=x, y=y, z=z,
                           lock_id=lock, name=name)


COPPER = 38        # band 0, the most abundant low-level node in the world
TRUESILVER = 380   # band 205
EARTHROOT = 30     # herbalism, band 15


class BandsComeFromTheDbcNotFromMemory(unittest.TestCase):
    """The projection is a measurement, and these are its anchors."""

    def test_copper_has_no_minimum(self):
        # Not None. 0 means "anyone with the skill at all", which is why
        # Mining 1 can mine copper, and it is a different answer from absent.
        self.assertEqual(gatherband.band_for(COPPER, "mining"), 0)

    def test_truesilver_reads_205_not_the_widely_repeated_230(self):
        """The single best argument for reading the DBC instead of typing it."""
        self.assertEqual(gatherband.band_for(TRUESILVER, "mining"), 205)

    def test_a_lock_that_gates_no_gathering_profession_is_none(self):
        self.assertIsNone(gatherband.band_for(999999, "mining"))

    def test_skinning_has_no_locks_at_all(self):
        """Skinning comes off corpses, not gameobject nodes.

        Encoded rather than left implicit: a caller that treats skinning as
        aimable would send the family somewhere that cannot help Bork.
        """
        self.assertIsNone(gatherband.band_for(COPPER, "skinning"))
        self.assertEqual(gatherband.reachable_locks("skinning", 300), [])

    def test_in_band_is_a_floor_not_an_equality(self):
        self.assertTrue(gatherband.in_band(COPPER, "mining", 1))
        self.assertTrue(gatherband.in_band(TRUESILVER, "mining", 205))
        self.assertTrue(gatherband.in_band(TRUESILVER, "mining", 300))
        self.assertFalse(gatherband.in_band(TRUESILVER, "mining", 204))

    def test_a_junk_skill_value_refuses_rather_than_raising(self):
        self.assertFalse(gatherband.in_band(COPPER, "mining", None))
        self.assertFalse(gatherband.in_band(COPPER, "mining", "lots"))


class TheProjectionMatchesItsGenerator(unittest.TestCase):
    """The checked-in table and the tool that makes it must not drift.

    `tools/spell_focus_from_dbc.py` has the same relationship to
    test_craft.MEASURED_FOCUS. Without this, the table is a hand-edited file
    wearing a measurement's name.
    """

    def test_the_tool_exists_and_documents_the_dbc_checksum(self):
        source = TOOL.read_text(encoding="utf-8")
        self.assertIn("74ddd0458e50a1d65acb78700b45e4d1", source,
                      "the tool must name the Lock.dbc it was run against")
        self.assertIn("ANCHORS", source)

    def test_the_tool_refuses_a_file_that_is_not_a_dbc(self):
        out = subprocess.run([sys.executable, str(TOOL), str(TOOL)],
                             capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("not a DBC", out.stdout + out.stderr)


class TheFamilyTravelsAsOne(unittest.TestCase):

    def test_the_band_is_the_weakest_gatherer_not_the_strongest(self):
        """Ugga's Herbalism 133 must not pick a zone Grog's Mining 1 cannot work."""
        skills = {"Grug": {"mining": 8}, "Grog": {"mining": 1},
                  "Ugga": {"herbalism": 133}}
        self.assertEqual(gatheraim.lowest_gatherer(skills), ("mining", 1))

    def test_a_roster_holding_no_aimable_skill_says_so(self):
        got = gatheraim.choose(skills={"Bork": {"skinning": 12}},
                               standing_on=1, spawns=[spawn(148, COPPER)],
                               family_level=60, zone_levels={148: 10})
        self.assertTrue(got.refused)
        self.assertIn("skinning", got.refused)
        self.assertIsNone(got.chosen)


class TheDestinationIsAlwaysASurveyedRow(unittest.TestCase):
    """The rule a guessed Z broke: it killed a character in the void."""

    def test_the_chosen_coordinate_is_one_of_the_input_spawns(self):
        rows = [spawn(148, COPPER, x=100.0, y=100.0, z=7.5),
                spawn(148, COPPER, x=110.0, y=105.0, z=8.25),
                spawn(148, COPPER, x=120.0, y=100.0, z=9.0)]
        got = gatheraim.choose(skills={"G": {"mining": 1}}, standing_on=1,
                               spawns=rows, family_level=60,
                               zone_levels={148: 12})
        self.assertTrue(got.chosen)
        self.assertIn(got.chosen.spawn, rows,
                      "the destination must BE a surveyed row, not a centroid")

    def test_the_centroid_itself_is_never_returned(self):
        """Two spawns whose midpoint is not either of them."""
        rows = [spawn(148, COPPER, x=0.0, y=0.0, z=5.0),
                spawn(148, COPPER, x=100.0, y=0.0, z=50.0)]
        got = gatheraim.choose(skills={"G": {"mining": 1}}, standing_on=1,
                               spawns=rows, family_level=60,
                               zone_levels={148: 12})
        self.assertIn((got.chosen.spawn.x, got.chosen.spawn.z),
                      [(0.0, 5.0), (100.0, 50.0)])


class SameMapOnly(unittest.TestCase):
    """ResolveTravelTarget refuses another map, and no flight paths are known."""

    def test_an_off_map_field_is_not_a_candidate_however_rich(self):
        rows = [spawn(12, COPPER, map_id=0) for _ in range(50)]
        rows.append(spawn(148, COPPER, map_id=1))
        got = gatheraim.choose(skills={"G": {"mining": 1}}, standing_on=1,
                               spawns=rows, family_level=60,
                               zone_levels={148: 12, 12: 10})
        self.assertEqual(got.chosen.map_id, 1)
        self.assertEqual(got.chosen.zone_id, 148)

    def test_nothing_on_this_map_is_refused_not_silently_skipped(self):
        got = gatheraim.choose(skills={"G": {"mining": 1}}, standing_on=1,
                               spawns=[spawn(12, COPPER, map_id=0)],
                               family_level=60, zone_levels={12: 10})
        self.assertTrue(got.refused)
        self.assertIn("map 1", got.refused)


class DensityBeatsProximity(unittest.TestCase):

    def test_the_zone_with_more_reachable_nodes_wins(self):
        rows = [spawn(1, COPPER, x=1.0)] + [spawn(148, COPPER, x=500.0)] * 4
        got = gatheraim.choose(skills={"G": {"mining": 1}}, standing_on=1,
                               spawns=rows, family_level=60,
                               zone_levels={1: 10, 148: 12})
        self.assertEqual(got.chosen.zone_id, 148)
        self.assertEqual(got.chosen.nodes, 4)

    def test_out_of_band_nodes_do_not_count_toward_density(self):
        """A zone full of Truesilver is empty to a Mining 1 character."""
        rows = [spawn(490, TRUESILVER)] * 20 + [spawn(148, COPPER)] * 2
        got = gatheraim.choose(skills={"G": {"mining": 1}}, standing_on=1,
                               spawns=rows, family_level=60,
                               zone_levels={490: 60, 148: 12})
        self.assertEqual(got.chosen.zone_id, 148)


class TheLevelGuardIsTheOnlyOneThereIs(unittest.TestCase):
    """A ground aim early-returns before every level check in mod_overseer.cpp.

    Five characters at 43-48 were sent roaming and wiped twice on a level 61
    elite, eight deaths in four minutes. Python is the last place that can say no.
    """

    def test_a_zone_above_the_family_level_is_refused(self):
        got = gatheraim.choose(skills={"G": {"mining": 1}}, standing_on=1,
                               spawns=[spawn(148, COPPER)], family_level=45,
                               zone_levels={148: 61})
        self.assertTrue(got.refused)
        self.assertIsNone(got.chosen)

    def test_an_unmeasured_zone_is_refused_rather_than_assumed_safe(self):
        got = gatheraim.choose(skills={"G": {"mining": 1}}, standing_on=1,
                               spawns=[spawn(148, COPPER)], family_level=60,
                               zone_levels={})
        self.assertTrue(got.refused)
        self.assertIsNone(got.chosen)

    def test_the_margin_is_allowed_but_not_exceeded(self):
        at_margin = gatheraim.choose(
            skills={"G": {"mining": 1}}, standing_on=1,
            spawns=[spawn(148, COPPER)], family_level=60,
            zone_levels={148: 60 + gatheraim.LEVEL_MARGIN})
        self.assertTrue(at_margin.chosen)
        over = gatheraim.choose(
            skills={"G": {"mining": 1}}, standing_on=1,
            spawns=[spawn(148, COPPER)], family_level=60,
            zone_levels={148: 60 + gatheraim.LEVEL_MARGIN + 1})
        self.assertTrue(over.refused)

    def test_a_dangerous_dense_zone_loses_to_a_safe_thin_one(self):
        rows = [spawn(490, COPPER)] * 10 + [spawn(148, COPPER)]
        got = gatheraim.choose(skills={"G": {"mining": 1}}, standing_on=1,
                               spawns=rows, family_level=20,
                               zone_levels={490: 60, 148: 18})
        self.assertEqual(got.chosen.zone_id, 148)


class TheRealFamilyState(unittest.TestCase):
    """The measured 2026-09-19 situation, as a regression."""

    def test_ungoro_offers_the_family_nothing(self):
        ungoro = [spawn(490, TRUESILVER) for _ in range(57)]
        got = gatheraim.choose(
            skills={"Grug": {"mining": 8}, "Grog": {"mining": 1},
                    "Ugga": {"herbalism": 133}, "Bork": {"skinning": 12}},
            standing_on=1, spawns=ungoro, family_level=60,
            zone_levels={490: 60})
        self.assertTrue(got.refused)
        self.assertIn("mining 1", got.refused)

    def test_adding_one_low_level_field_answers_it(self):
        rows = [spawn(490, TRUESILVER) for _ in range(57)]
        rows += [spawn(148, COPPER, x=float(i)) for i in range(97)]
        got = gatheraim.choose(
            skills={"Grug": {"mining": 8}, "Grog": {"mining": 1},
                    "Ugga": {"herbalism": 133}, "Bork": {"skinning": 12}},
            standing_on=1, spawns=rows, family_level=60,
            zone_levels={490: 60, 148: 12})
        self.assertEqual(got.chosen.zone_id, 148)
        self.assertEqual(got.chosen.nodes, 97)
        self.assertIn("surveyed spawn", gatheraim.report(got))


if __name__ == "__main__":
    unittest.main()

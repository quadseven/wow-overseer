"""The classic ruleset (classic.py): its numbers, its lists, and the module's.

The operator restricts these worlds to a classic level-60 feel: level 60,
professions to 300, and never Outland (530) or Northrend (571). The planners'
own tests show each one obeying; this file pins the ruleset itself, and that
the module's mirrored copy in `OverseerDecisions::Classic` says the same.
"""

import json
import pathlib
import re
import unittest

import classic
import dungeonpath
import jobs

ROOT = pathlib.Path(__file__).resolve().parents[1]
DECISIONS_H = ROOT / "mod-overseer" / "src" / "overseer_decisions.h"


class TheNumbers(unittest.TestCase):
    def test_level_skill_and_the_two_maps(self):
        self.assertEqual(classic.MAX_LEVEL, 60)
        self.assertEqual(classic.MAX_PROFESSION_SKILL, 300)
        self.assertEqual(classic.EXPANSION_MAPS, {530, 571})
        self.assertEqual(classic.CLASSIC_CONTINENTS, (0, 1))

    def test_artisan_is_in_and_master_is_out(self):
        self.assertTrue(classic.skill_ok(300))
        self.assertFalse(classic.skill_ok(301))
        self.assertFalse(classic.skill_ok(375))

    def test_an_item_is_judged_on_both_numbers_and_the_list(self):
        self.assertTrue(classic.item_ok(14155, 60, 0))  # Mooncloth Bag
        self.assertTrue(classic.item_ok(19019, 80, 60))  # Thunderfury
        self.assertFalse(classic.item_ok(21841, 63, 0))  # Netherweave Bag
        self.assertFalse(classic.item_ok(1, 93, 0))
        self.assertFalse(classic.item_ok(1, 0, 61))
        self.assertTrue(classic.item_ok(4499))


class TheMaps(unittest.TestCase):
    def test_the_two_continents_and_their_instances_are_classic(self):
        for map_id in (0, 1, 36, 409, 531, 369):
            self.assertTrue(classic.is_classic_map(map_id), map_id)
            self.assertFalse(classic.outside_classic(map_id), map_id)

    def test_outland_northrend_and_their_instances_are_outside(self):
        for map_id in (530, 571, 540, 574, 533, 249, 532, 609):
            self.assertTrue(classic.outside_classic(map_id), map_id)
            self.assertFalse(classic.is_classic_map(map_id), map_id)

    def test_an_unknown_map_is_not_judged(self):
        self.assertFalse(classic.outside_classic(None))
        self.assertFalse(classic.outside_classic(999))
        self.assertFalse(classic.is_expansion_map(None))

    def test_the_two_lists_never_overlap(self):
        self.assertFalse(classic.CLASSIC_MAPS & classic.EXPANSION_INSTANCE_MAPS)

    def test_every_door_on_outland_or_northrend_is_on_the_outside_list(self):
        entrances = json.loads((ROOT / "entrances.json").read_text(encoding="utf-8"))
        behind = {int(m) for m, e in entrances.items() if int(e["map"]) in (530, 571)}
        self.assertTrue(behind)
        self.assertEqual(behind - classic.EXPANSION_INSTANCE_MAPS, set())

    def test_every_door_the_family_can_run_is_classic(self):
        for step in dungeonpath.PATH:
            self.assertIn(step.map_id, classic.CLASSIC_INSTANCE_MAPS, step)
        for keyword in jobs.PORTAL_KEYWORDS:
            map_id = dungeonpath.PORTAL_MAPS[keyword]
            self.assertIn(map_id, classic.CLASSIC_INSTANCE_MAPS, keyword)

    def test_the_note_names_the_land(self):
        self.assertEqual(
            classic.outside_note("Zora", 530),
            "Zora stands in Outland, outside the classic world",
        )
        self.assertEqual(
            classic.outside_note("Zora", 571),
            "Zora stands in Northrend, outside the classic world",
        )


# The first mod-overseer commit that carries OverseerDecisions::Classic.
MODULE_CLASSIC_SHA = "5b99ee24e12255548ef2699109680e3abd96b443"


def _module_block():
    """The Classic block of the PINNED module, or None when the pin predates it."""
    text = DECISIONS_H.read_text(encoding="utf-8")
    match = re.search(
        r"namespace Classic\s*\{(.*?)\}\s*// namespace Classic", text, re.S
    )
    return match.group(1) if match else None


@unittest.skipIf(
    _module_block() is None,
    "the pinned mod-overseer predates OverseerDecisions::Classic (%s); this "
    "comparison engages when the pin reaches it" % MODULE_CLASSIC_SHA[:7],
)
class TheModuleAgrees(unittest.TestCase):
    """mod-overseer carries the same numbers in OverseerDecisions::Classic,
    under names kept clear of the core's MAX_LEVEL macro.

    READ FROM THE PINNED SUBMODULE, so it compares the module this site is
    built against. The pin moves with the image pin in UPSTREAM-PINS.env, which
    the operator promotes, so this class skips until then and says why.
    """

    @classmethod
    def setUpClass(cls):
        cls.block = _module_block()

    def constant(self, name):
        found = re.search(r"constexpr uint32_t %s = (\d+);" % name, self.block)
        self.assertIsNotNone(found, name)
        return int(found.group(1))

    def test_the_level_cap(self):
        self.assertEqual(self.constant("LEVEL_CAP"), classic.MAX_LEVEL)

    def test_the_profession_cap(self):
        self.assertEqual(
            self.constant("PROFESSION_SKILL_CAP"), classic.MAX_PROFESSION_SKILL
        )

    def test_the_two_maps(self):
        self.assertEqual(self.constant("OUTLAND_MAP_ID"), classic.OUTLAND_MAP)
        self.assertEqual(self.constant("NORTHREND_MAP_ID"), classic.NORTHREND_MAP)


if __name__ == "__main__":
    unittest.main()

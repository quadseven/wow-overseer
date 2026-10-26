"""The Molten Core encounter table and the composer that reads a lineup
against it (#684). The composer reports; it never moves a raider."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mcencounters  # noqa: E402
import raidlineup  # noqa: E402
import raidteams  # noqa: E402
from mcencounters import (  # noqa: E402
    CURSE_DISPEL,
    DRUID,
    FIRE_RESISTANCE,
    HUNTER,
    MAGE,
    PALADIN,
    PRIEST,
    TANKS,
    TRANQUILIZING_SHOT,
    WARLOCK,
    WARRIOR,
)

MOLTEN_CORE = (
    "Lucifron",
    "Magmadar",
    "Gehennas",
    "Garr",
    "Shazzrah",
    "Baron Geddon",
    "Golemagg",
    "Sulfuron Harbinger",
    "Majordomo Executus",
    "Ragnaros",
)


def _raider(class_id, seat="dps"):
    return {"class_id": class_id, "seat": seat}


def _row(report, boss):
    return next(r for r in report if r["boss"] == boss)


class TheTableCoversEveryBoss(unittest.TestCase):
    def test_every_molten_core_boss_in_order(self):
        self.assertEqual(tuple(e.boss for e in mcencounters.ENCOUNTERS), MOLTEN_CORE)

    def test_every_boss_asks_for_a_tank_and_a_known_capability(self):
        for encounter in mcencounters.ENCOUNTERS:
            self.assertGreaterEqual(encounter.needs.get(TANKS, 0), 1, encounter.boss)
            for name, count in encounter.needs.items():
                self.assertIn(name, mcencounters.CAPABILITIES, encounter.boss)
                self.assertGreaterEqual(count, 1, (encounter.boss, name))
            self.assertTrue(encounter.why, encounter.boss)

    def test_dedicated_tanks_stay_three_to_five(self):
        """The ticket: about 3 to 5 dedicated tanks, not one a group."""
        most = max(e.needs[TANKS] for e in mcencounters.ENCOUNTERS)
        self.assertGreaterEqual(most, 3)
        self.assertLessEqual(most, 5)

    def test_fire_resistance_is_one_source_not_one_a_group(self):
        """Fire Resistance Aura and Totem are raid-wide on this realm."""
        for encounter in mcencounters.ENCOUNTERS:
            self.assertLessEqual(encounter.needs.get(FIRE_RESISTANCE, 0), 1)


class TheComposerReportsWhatIsMissing(unittest.TestCase):
    def test_an_empty_raid_lacks_everything_each_boss_asks(self):
        report = mcencounters.compose([])
        self.assertEqual([r["boss"] for r in report], list(MOLTEN_CORE))
        for row in report:
            self.assertEqual(row["lacks"], row["needs"], row["boss"])

    def test_tanks_count_the_tank_seat_not_the_class(self):
        report = mcencounters.compose([_raider(WARRIOR)] * 6)
        self.assertEqual(_row(report, "Golemagg")["lacks"], {TANKS: 3})
        report = mcencounters.compose([_raider(WARRIOR, "tank")] * 3)
        self.assertEqual(_row(report, "Golemagg")["lacks"], {})

    def test_lucifron_lacks_one_curse_dispeller(self):
        raid = [_raider(WARRIOR, "tank")] * 3 + [_raider(PRIEST, "healer")] * 2
        raid.append(_raider(MAGE))
        row = _row(mcencounters.compose(raid), "Lucifron")
        self.assertEqual(row["have"][CURSE_DISPEL], 1)
        self.assertEqual(row["lacks"], {CURSE_DISPEL: 1})
        self.assertIn(
            "Lucifron lacks 1 curse dispeller",
            mcencounters.encounter_line(mcencounters.compose(raid)),
        )

    def test_magmadar_needs_a_hunter(self):
        raid = [_raider(WARRIOR, "tank"), _raider(PRIEST, "healer")]
        self.assertEqual(
            _row(mcencounters.compose(raid), "Magmadar")["lacks"],
            {TRANQUILIZING_SHOT: 1},
        )
        raid.append(_raider(HUNTER))
        self.assertEqual(_row(mcencounters.compose(raid), "Magmadar")["lacks"], {})

    def test_a_raid_with_every_capability_is_met_everywhere(self):
        raid = (
            [_raider(WARRIOR, "tank")] * 4
            + [_raider(PRIEST, "healer")] * 4
            + [_raider(PALADIN, "healer")] * 2
            + [_raider(DRUID, "healer")] * 2
            + [_raider(MAGE)] * 4
            + [_raider(WARLOCK)] * 2
            + [_raider(HUNTER)] * 2
        )
        report = mcencounters.compose(raid)
        self.assertEqual([r["boss"] for r in report if r["lacks"]], [])
        self.assertEqual(
            mcencounters.encounter_line(report),
            "The lineup brings what every Molten Core boss asks for.",
        )


class TheLineupCarriesTheReport(unittest.TestCase):
    def _approved_roster(self, team):
        return [
            {"name": s.name, "class_id": s.class_id, "level": 60}
            for s in raidteams.seats(team)
        ]

    def test_an_approved_lineup_reports_without_moving_a_seat(self):
        for team in raidteams.GROUPS:
            lineup = raidlineup.build_lineup(self._approved_roster(team))
            self.assertEqual(lineup["approved"], team)
            seated = [[m["name"] for m in g["members"]] for g in lineup["groups"]]
            approved = [[s.name for s in g] for g in raidteams.GROUPS[team]]
            self.assertEqual(seated, approved, team)
            self.assertEqual(
                [r["boss"] for r in lineup["encounters"]], list(MOLTEN_CORE)
            )
            self.assertEqual(
                lineup["encounter_line"],
                mcencounters.encounter_line(lineup["encounters"]),
            )

    def test_an_automatic_lineup_reports_too(self):
        roster = [
            {"name": "Warrior%d" % i, "class_id": WARRIOR, "level": 60}
            for i in range(10)
        ]
        lineup = raidlineup.build_lineup(roster)
        self.assertNotIn("approved", lineup)
        self.assertEqual(len(lineup["encounters"]), len(MOLTEN_CORE))
        self.assertIn("Lucifron lacks", lineup["encounter_line"])


if __name__ == "__main__":
    unittest.main()

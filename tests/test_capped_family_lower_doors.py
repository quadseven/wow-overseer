"""A family whose members are all at the level cap runs the level 60 dungeons.

The defect (#3282): a family whose members were all at the level cap was
queued for Maraudon (the purple wing), whose band stops at 55. The planner
kept every lower door open at the cap
while its loot held any upgrade for anyone (#2207), and an empty slot counts
any drop as one. The guard that ranks such a door behind the family's band
(#2715) reads bosses per map, and Maraudon's two wings share a map, so it was
blind there and the purple wing won on raw expected item levels.

These tests hold the planner to what a group of players at 60 does: only the
doors whose band reaches the cap, best upgrades first, and a lower entry
already on the queue ends at the next point between runs, never during one.
A levelling family still runs Maraudon inside its band, and a guild group of
60s is offered no lower door either. Every test runs on fake rows.
"""

import unittest

from test_campaignplan import (
    ALLIANCE,
    EASTERN_KINGDOMS,
    KALIMDOR,
    SHADOWFORGE,
    facts,
    keywords,
    rows,
)

import campaignplan  # noqa: E402
import dungeonladder  # noqa: E402
import guildrun  # noqa: E402
import preraid  # noqa: E402

MARAUDON = 349

# Bosses as the planner reads them: per map, so the two Maraudon wings, which
# share map 349, are told None for theirs (campaignplan._history_facts).
BOSSES = {
    209: (46, 46),
    MARAUDON: (44, 48),
    109: (50, 55),
    229: (56, 60),
    230: (52, 58),
    289: (57, 60),
    329: (58, 62),
}


def gain(levels: float, name: str = "Grug") -> tuple:
    return (preraid.Gain(name, 1, 0.3, levels, "a piece"),)


def capped(map_id=KALIMDOR, **kw):
    return facts(ALLIANCE, map_id, bosses=BOSSES, **kw)


# What a run of each door is worth to the capped family: the lower doors
# score highest, as an under-geared family's empty slots make them.
WORTH = {
    "maraudon-purple": gain(30.0),
    "maraudon-orange": gain(28.0),
    "zulfarrak": gain(25.0),
    "sunken-temple": gain(22.0),
    "blackrock-depths": gain(6.0),
    "lower-blackrock-spire": gain(9.0),
    "scholomance": gain(12.0),
    "dire-maul-east-east": gain(4.0),
}


class OnlyTheDoorsWhoseBandReachesTheCap(unittest.TestCase):
    def test_maraudon_is_outgrown_at_the_cap_whatever_its_loot(self):
        kinds = campaignplan.refusal_kinds(capped(upgrades=WORTH))
        for keyword in ("maraudon-purple", "maraudon-orange", "zulfarrak"):
            self.assertEqual(kinds[keyword][0], campaignplan.REFUSED_OUTGROWN, keyword)
        east = campaignplan.refusal_kinds(
            capped(map_id=EASTERN_KINGDOMS, upgrades=WORTH)
        )
        self.assertEqual(east["sunken-temple"][0], campaignplan.REFUSED_OUTGROWN)
        self.assertEqual(kinds["maraudon-purple"][1], "outgrown: it tops out at 55")

    def test_every_door_offered_reaches_the_cap(self):
        for map_id, keys in ((KALIMDOR, None), (EASTERN_KINGDOMS, SHADOWFORGE)):
            opts = campaignplan.options(
                capped(map_id=map_id, upgrades=WORTH, keys=keys)
            )
            self.assertTrue(opts, map_id)
            for option in opts:
                self.assertEqual(option.ceiling, campaignplan.LEVEL_CAP, option.keyword)

    def test_the_pick_is_the_in_band_door_worth_most(self):
        opts = campaignplan.options(
            capped(map_id=EASTERN_KINGDOMS, upgrades=WORTH, keys=SHADOWFORGE)
        )
        self.assertEqual(
            keywords(opts),
            ["blackrock-depths", "lower-blackrock-spire", "scholomance"],
        )
        ranked = sorted(opts, key=campaignplan.rank)
        self.assertEqual(
            [o.keyword for o in ranked],
            ["scholomance", "lower-blackrock-spire", "blackrock-depths"],
        )
        self.assertEqual(campaignplan.heuristic(opts).keyword, "scholomance")

    def test_progression_still_comes_before_loot(self):
        moved = preraid.Progress(
            "blackrock-depths",
            preraid.ATTUNEMENT,
            True,
            True,
            "a run advances the Molten Core attunement",
        )
        opts = campaignplan.options(
            capped(
                map_id=EASTERN_KINGDOMS,
                upgrades=WORTH,
                keys=SHADOWFORGE,
                progress={"blackrock-depths": moved},
            )
        )
        self.assertEqual(campaignplan.heuristic(opts).keyword, "blackrock-depths")

    def test_the_ladder_says_outgrown_for_maraudon(self):
        view = dungeonladder.view(capped(upgrades=WORTH))
        states = {r["keyword"]: r["state"] for r in view["rungs"]}
        self.assertEqual(states["maraudon-purple"], dungeonladder.OUTGROWN)
        self.assertEqual(states["maraudon-orange"], dungeonladder.OUTGROWN)
        self.assertEqual(states["dire-maul-east-east"], dungeonladder.OPEN)


class NaturalProgressionIsUnchanged(unittest.TestCase):
    def test_a_levelling_family_inside_the_band_still_runs_maraudon(self):
        opts = campaignplan.options(facts(ALLIANCE, KALIMDOR, level=48))
        self.assertIn("maraudon-purple", keywords(opts))
        self.assertIn("maraudon-orange", keywords(opts))

    def test_one_member_under_the_cap_leaves_the_rule_as_it_was(self):
        """A weakest member at 59 has outgrown Maraudon by its ceiling alone."""
        family = (("Grug", 60, 1), ("Ugga", 60, 1), ("Og", 59, 1))
        refused = campaignplan.refusals(facts(family, KALIMDOR))
        self.assertEqual(refused["maraudon-purple"], "outgrown: it tops out at 55")


class AQueuedLowerEntryEndsBetweenRuns(unittest.TestCase):
    """The live queue: a planner entry for the purple wing, 0 of 13."""

    def head(self, source=campaignplan.SOURCE, keyword="maraudon-purple"):
        return {
            "id": 88,
            "family": "Grug",
            "position": 0,
            "keyword": keyword,
            "runs_wanted": 13,
            "status": "active",
            "source": source,
        }

    def due(self, level_rows, **head):
        return campaignplan.due(
            [self.head(**head)], {"dungeon_runs_done": 0}, list(level_rows), None
        )

    def test_outside_the_dungeon_the_entry_ends_and_a_door_is_planned(self):
        due = self.due(rows(ALLIANCE, EASTERN_KINGDOMS))
        self.assertEqual(due.finish, 88)
        self.assertIn("outgrown Maraudon (the purple wing)", due.reason)
        self.assertIn("tops out at 55", due.reason)
        self.assertFalse(due.dry)

    def test_inside_the_dungeon_the_run_goes_on(self):
        """Never cancel a run under way: the entry ends at the next pass after
        the party is out."""
        inside = [dict(r) for r in rows(ALLIANCE, EASTERN_KINGDOMS)]
        inside[2]["map_id"] = MARAUDON
        self.assertEqual(self.due(inside), campaignplan.Due())

    def test_an_operators_order_runs_to_its_count(self):
        due = self.due(rows(ALLIANCE, KALIMDOR), source="web:overseer")
        self.assertEqual(due, campaignplan.Due())

    def test_an_entry_for_a_level_60_door_is_left_alone(self):
        due = self.due(rows(ALLIANCE, KALIMDOR), keyword="dire-maul-east-east")
        self.assertEqual(due, campaignplan.Due())


class AGuildGroupOf60sIsOfferedNoLowerDoor(unittest.TestCase):
    def test_fitting_doors_for_five_60s(self):
        doors = guildrun.doors()
        for faction in ("Alliance", "Horde"):
            fit = guildrun.fitting_doors([60] * 5, doors, faction)
            self.assertTrue(fit, faction)
            for door in fit:
                self.assertEqual(door.ceiling, campaignplan.LEVEL_CAP, door.keyword)

    def test_maraudon_still_fits_a_member_inside_its_band(self):
        """A guild member at 54 asking for Maraudon is asking for the right
        door."""
        fit = guildrun.fitting_doors([54], guildrun.doors(), "Alliance")
        self.assertIn("maraudon-purple", [d.keyword for d in fit])


if __name__ == "__main__":
    unittest.main()

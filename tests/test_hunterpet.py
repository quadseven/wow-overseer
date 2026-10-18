"""A hunter that has learned Tame Beast tames its first pet (2026-10-10).

Read on the dev realm on 2026-10-10 at about 14:45 America/New_York: none of
the two guilds' 14 hunters had a pet (no character_pet row) or knew Tame Beast
(1515), and in 24 hours they died 1,551 times, 110.8 each, three times a mage's
36.7. The Taming the Beast chain teaches Tame Beast (1579 teaches 1515, Call Pet
883 and Dismiss Pet 2641), but its rods only charm a beast for 15 minutes, and
nothing then cast Tame Beast at a beast. Grunty, a level 17 orc, levels in the
Barrens among Savannah Prowlers (3425, level 14-15, family 2) and Hecklefang
Hyenas (4127, level 15-16, family 25): the rows below are the realm's.
"""

import pathlib
import unittest

import guildjobs
import hunterpet
import member_rungs

GRUNTY = dict(
    name="Grunty",
    guild="Bonkers",
    role=guildjobs.RAIDER,
    level=17,
    class_id=hunterpet.HUNTER,
    race=2,
    online=True,
    map_id=1,
    x=-1212.0,
    y=-3162.0,
    zone_id=17,
    eligible=True,
)


def member(**over):
    return guildjobs.Member(**dict(GRUNTY, **over))


def row(guid, entry, x, y, level, family, name="", map_id=1):
    """One row of hunterpet.BEASTS_SQL."""
    return {
        "guid": guid,
        "entry": entry,
        "map_id": map_id,
        "x": x,
        "y": y,
        "name": name or "Beast %d" % entry,
        "level": level,
        "family": family,
    }


HYENA = row(13198, 4127, -1300.0, -3200.0, 16, 25, "Hecklefang Hyena")
PROWLER = row(14193, 3425, -1250.0, -3180.0, 15, 2, "Savannah Prowler")
# Too low for a level 17 (more than LEVEL_BELOW under it).
PLAINSTRIDER = row(13001, 3244, -1215.0, -3165.0, 9, 12, "Greater Plainstrider")
# An exotic family Tame Beast refuses without the talent.
DEVILSAUR = row(15000, 6498, -1214.0, -3163.0, 17, 39, "Devilsaur")
# Over the hunter's level.
LION = row(13500, 3474, -1213.0, -3162.0, 19, 2, "Lakota'mani")

BEASTS = hunterpet.beasts_from_rows([HYENA, PROWLER, PLAINSTRIDER, DEVILSAUR, LION])


class TheBeast(unittest.TestCase):
    def test_the_exotic_family_is_never_read(self):
        self.assertNotIn(6498, {b.entry for b in BEASTS})

    def test_the_nearest_beast_of_its_level_band(self):
        beast = hunterpet.choose(member(), BEASTS)
        self.assertEqual((beast.entry, beast.guid), (3425, 14193))

    def test_never_over_its_level_nor_far_under_it(self):
        chosen = hunterpet.choose(member(), BEASTS)
        self.assertNotIn(chosen.entry, (3474, 3244))

    def test_a_beast_walked_to_lately_is_left_for_another(self):
        beast = hunterpet.choose(member(), BEASTS, frozenset({14193}))
        self.assertEqual(beast.entry, 4127)

    def test_another_map_is_no_beast(self):
        self.assertIsNone(hunterpet.choose(member(map_id=0), BEASTS))

    def test_the_cast_is_tame_beast_at_the_creature(self):
        beast = hunterpet.choose(member(), BEASTS)
        self.assertEqual(
            hunterpet.command(beast), "use-spell-on creature:3425 spell:1515"
        )


class WhoTames(unittest.TestCase):
    def test_a_hunter_with_tame_beast_and_no_pet(self):
        self.assertTrue(hunterpet.wants_pet(member(), {"Grunty"}))

    def test_not_one_with_a_pet_or_without_the_spell(self):
        self.assertFalse(hunterpet.wants_pet(member(), set()))

    def test_not_another_class(self):
        self.assertFalse(hunterpet.wants_pet(member(class_id=9), {"Grunty"}))

    def test_not_in_a_fight_dead_or_offline(self):
        for m in (member(in_combat=True), member(alive=False), member(online=False)):
            self.assertFalse(hunterpet.wants_pet(m, {"Grunty"}), m)

    def test_the_read_names_the_spell_and_the_pet_table(self):
        self.assertIn("s.spell = 1515", hunterpet.UNPETTED_SQL)
        self.assertIn("character_pet", hunterpet.UNPETTED_SQL)
        self.assertIn("(ct.type_flags & 1) <> 0", hunterpet.BEASTS_SQL)
        self.assertIn("c.class = %d " % hunterpet.HUNTER, hunterpet.UNPETTED_SQL)
        self.assertIn("ct.type = %d " % hunterpet.BEAST_TYPE, hunterpet.BEASTS_SQL)


def plan(members, pets=None, recent=()):
    return guildjobs.plan(
        members,
        masters={"Bonkers": "Zug"},
        pets=pets if pets is not None else {"Grunty": BEASTS},
        recent=tuple(recent),
    )


class InThePass(unittest.TestCase):
    def test_grunty_walks_to_a_prowler_and_tames_it(self):
        steps = [s for s in plan([member()]).steps if s.holder == "Grunty"]
        self.assertEqual([s.action for s in steps], [hunterpet.ACTION])
        step = steps[0]
        self.assertEqual(
            step.walk.command.split()[:2], ["walk-to-spawn", "creature:14193"]
        )
        self.assertEqual(
            [(r.kind, r.command) for r in step.rows],
            [("quest", "use-spell-on creature:3425 spell:1515")],
        )

    def test_a_hunter_with_a_pet_has_no_offer(self):
        result = plan([member()], pets={})
        self.assertFalse([s for s in result.steps if s.action == hunterpet.ACTION])

    def test_one_try_per_cooldown(self):
        row = guildjobs.Recent("Grunty", hunterpet.ACTION, 5, status="unchanged")
        result = plan([member()], recent=(row,))
        self.assertFalse([s for s in result.steps if s.action == hunterpet.ACTION])

    def test_the_next_try_goes_to_another_beast(self):
        walk = guildjobs.Recent(
            "Grunty", hunterpet.ACTION, 30, status="applied", walk=True, spawn=14193
        )
        steps = [
            s for s in plan([member()], recent=(walk,)).steps if s.holder == "Grunty"
        ]
        self.assertIn("creature:13198", steps[0].walk.command)

    def test_no_beast_in_reach_is_named(self):
        result = plan([member(map_id=0)])
        self.assertFalse([s for s in result.steps if s.action == hunterpet.ACTION])
        self.assertTrue([n for n in result.notes if "Tame Beast" in n])

    def test_the_class_quest_still_comes_first(self):
        source = member_rungs.names()
        self.assertLess(source.index("class_step"), source.index("_pet_first"))
        self.assertLess(source.index("_pet_first"), source.index("_supply_first"))

    def test_the_bridge_reads_the_hunters_and_the_beasts(self):
        source = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        for needle in (
            "hunterpet.UNPETTED_SQL",
            "hunterpet.BEASTS_SQL",
            "pets=await self._job_pet_offers(",
        ):
            self.assertTrue(needle in source, needle)


if __name__ == "__main__":
    unittest.main()

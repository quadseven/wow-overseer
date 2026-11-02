"""Every recipe any member is told to cast has a station something serves.

tests/recipe_stations.json is the realm's own Spell.dbc, projected by
tools/recipe_stations_from_dbc.py: spell id -> [focus, [tool categories]]. A
recipe added to any table below without a measurement fails here, and so does
one whose focus or tool nothing in this repo knows how to meet. See
quadseven/wow-overseer#1786 for what an unserved focus looks like on a client.
"""

import json
import pathlib
import unittest

import craft
import guildcorps
import raidcraft
import raidsupply

MEASURED = {
    int(spell): (focus, tuple(tools))
    for spell, (focus, tools) in json.loads(
        (pathlib.Path(__file__).parent / "recipe_stations.json").read_text()
    ).items()
}


def issued_tables() -> dict:
    """table name -> every craft spell that table can put on a member."""
    return {
        "craft": {r.spell_id for r in craft.known_recipes()},
        "raidcraft": {c.spell_id for c in raidcraft.CONSUMABLES},
        "raidsupply": {s.make.spell for s in raidsupply.SUPPLIES if s.make},
        "guildcorps": {b.spell for b in guildcorps.BAGS},
    }


def every_issued_spell() -> set:
    return set().union(*issued_tables().values())


class EveryRecipeHasAKnownStation(unittest.TestCase):
    def test_every_issued_spell_is_measured(self):
        for table, spells in issued_tables().items():
            for spell in sorted(spells):
                with self.subTest(table=table, spell=spell):
                    self.assertIn(
                        spell, MEASURED,
                        "run tools/recipe_stations_from_dbc.py: a recipe whose "
                        "focus nobody read is a recipe refused on every poll",
                    )

    def test_every_focus_is_a_known_station(self):
        for spell in sorted(every_issued_spell()):
            focus, _tools = MEASURED[spell]
            with self.subTest(spell=spell):
                self.assertTrue(
                    focus == 0 or focus in craft.STATIONS,
                    "focus %d has no entry in craft.STATIONS" % focus,
                )

    def test_every_tool_is_a_known_item(self):
        for spell in sorted(every_issued_spell()):
            with self.subTest(spell=spell):
                for tool in MEASURED[spell][1]:
                    self.assertIn(tool, craft.TOOL_ITEMS)

    def test_the_declared_focus_is_the_measured_focus(self):
        for recipe in craft.known_recipes():
            with self.subTest(recipe=recipe.name):
                self.assertEqual(recipe.focus, MEASURED[recipe.spell_id][0])
        for consumable in raidcraft.CONSUMABLES:
            with self.subTest(consumable=consumable.name):
                self.assertEqual(consumable.focus, MEASURED[consumable.spell_id][0])

    def test_a_recipe_handed_out_has_its_tools_declared(self):
        """A ladder rung needing a tool it does not declare is one the errand
        must not reach: `walked` keeps such a rung off the column."""
        for recipe in craft.known_recipes():
            tools = MEASURED[recipe.spell_id][1]
            with self.subTest(recipe=recipe.name):
                if tools and not recipe.tool:
                    self.assertFalse(craft.walked(recipe))
                if recipe.tool:
                    self.assertEqual(
                        [craft.TOOL_ITEMS[t] for t in tools], [recipe.tool]
                    )


if __name__ == "__main__":
    unittest.main()

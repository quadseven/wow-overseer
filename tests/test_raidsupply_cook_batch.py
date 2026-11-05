"""A raid-supply cook lights one fire and casts while the reagents last (#1897).

Before #1897 the cook step was clamped to one cast: guildcorps.Step.repeat
makes the bridge write every row `repeat` times, so a batch would have lit a
fire before each cast. The step now writes one Basic Campfire row and then one
cast row per dish, with repeat 1. The campfire's own reagent and tool are
checked first, so a cook without them never writes a fire that is refused on
every pass.
"""

import unittest

import guildcorps as gc
import raidsupply as rs

KALIMDOR = 1
DUMPLINGS = rs.SUPPLY_BY_ENTRY[20452].make  # Smoked Desert Dumplings
MEAT = rs.SANDWORM_MEAT


def cook(*carried):
    return gc.Member(
        name="Cookie",
        guild="Cave",
        class_id=8,
        level=60,
        online=True,
        map_id=KALIMDOR,
        maintenance=True,
        skills={gc.COOKING: (300, 300)},
        known=frozenset({DUMPLINGS.spell}),
        carried=tuple(
            gc.Held(guid, entry, count)
            for guid, (entry, count) in enumerate(carried, start=1)
        ),
    )


def step_for(crafter, want=4, vendors=frozenset()):
    return rs.craft_step(
        crafter, DUMPLINGS, "Smoked Desert Dumplings", want, vendors, 0
    )


KIT = ((rs.SIMPLE_WOOD, 1), (rs.FLINT_AND_TINDER, 1))


class OneFireThenEveryCast(unittest.TestCase):
    def test_reagents_for_several_casts_light_one_fire_then_cast_each(self):
        step = step_for(cook((MEAT, 6), *KIT), want=4)
        self.assertEqual("craft", step.action)
        self.assertEqual(
            ["818"] + [str(DUMPLINGS.spell)] * 4, [r.command for r in step.rows]
        )
        self.assertEqual(1, step.repeat)
        self.assertIn("crafts 4 Smoked Desert Dumplings", step.said)

    def test_the_casts_stop_at_the_reagents_carried(self):
        step = step_for(cook((MEAT, 3), *KIT), want=8)
        self.assertEqual(
            ["818"] + [str(DUMPLINGS.spell)] * 3, [r.command for r in step.rows]
        )

    def test_the_casts_stop_at_the_craft_batch(self):
        step = step_for(cook((MEAT, 40), *KIT), want=40)
        self.assertEqual(1 + rs.CRAFT_BATCH, len(step.rows))


class NoCampfireNoFire(unittest.TestCase):
    def test_no_campfire_reagents_and_no_vendor_is_no_step(self):
        self.assertIsNone(step_for(cook((MEAT, 6))))

    def test_no_flint_and_tinder_is_no_step(self):
        crafter = cook((MEAT, 6), (rs.SIMPLE_WOOD, 5))
        self.assertIsNone(step_for(crafter, vendors=frozenset({rs.SIMPLE_WOOD})))

    def test_no_wood_buys_it_where_a_vendor_sells_it(self):
        crafter = cook((MEAT, 6), (rs.FLINT_AND_TINDER, 1))
        step = step_for(crafter, vendors=frozenset({rs.SIMPLE_WOOD}))
        self.assertEqual("buy", step.action)
        self.assertEqual(rs.SIMPLE_WOOD, step.key)
        self.assertTrue(
            step.rows[0].command.startswith(
                "entry:%d count:%d " % (rs.SIMPLE_WOOD, rs.CAMPFIRE_WOOD_BUY)
            ),
            step.rows[0].command,
        )

    def test_the_plan_says_why_the_cook_lit_no_fire(self):
        plan = rs.plan_guild(
            rs.GuildFacts(
                "Cave",
                (cook((MEAT, 6)),),
                (rs.Raider(name="Anneve", role=rs.TANK, class_id=rs.WARRIOR),),
                (gc.Post("Cookie", "cook", gc.COOKING, 300, 300),),
                {},
            ),
            {},
            set(),
        )
        self.assertFalse([s for s in plan.steps if s.holder == "Cookie"])
        self.assertTrue(
            any("campfire" in n and "Cookie" in n for n in plan.notes), plan.notes
        )

    def test_the_bridge_reads_the_campfire_reagents(self):
        # The carried-items and vendor reads are filtered to SUPPLY_ENTRIES; an
        # entry missing there always counts 0 and the cook would never cook.
        self.assertLessEqual({rs.SIMPLE_WOOD, rs.FLINT_AND_TINDER}, rs.SUPPLY_ENTRIES)


if __name__ == "__main__":
    unittest.main()

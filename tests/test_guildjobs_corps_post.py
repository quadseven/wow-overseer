"""The corps posts what the family's crafters can use, and keeps one batch (#2397).

Measured on the dev realm on 2026-11-13: the family's crafters asked all day
for Linen, Wool and Silk Cloth, Silverleaf and Rough Stone, while the guild's
maintenance members carried about 1,500 Linen Cloth and 270 Silk Cloth. A
First Aid member kept every Linen Cloth its next bandage would eat (Grunty 26
stacks), and the post was the last rung of a member's turn, behind PvP, the
mail collection and the level walk, so the silk never left either.

Pure unit tests against guildjobs.
"""

import unittest

import guildjobs
import pvpgear

H, M, S = guildjobs.HERBALISM, guildjobs.MINING, guildjobs.SKINNING
FA, TAILORING = guildjobs.FIRST_AID, guildjobs.TAILORING
LINEN, SILK, ORE = 2589, 4306, 2770


def stack(guid, entry, count, subclass=5, price=10, name=""):
    return guildjobs.Carried(
        guid=guid,
        entry=entry,
        count=count,
        item_class=7,
        subclass=subclass,
        quality=1,
        sell_price=price,
        name=name or "item %d" % entry,
    )


def member(name="Grunty", carried=(), **over):
    base = dict(
        name=name,
        guild="Bonkers",
        role=guildjobs.MAINTENANCE,
        level=30,
        class_id=3,
        race=2,
        online=True,
        map_id=1,
        x=0.0,
        y=0.0,
        money=50000,
        eligible=True,
        skills={H: (40, 75), M: (40, 75), FA: (40, 75), guildjobs.COOKING: (1, 75)},
        carried=tuple(carried),
    )
    base.update(over)
    return guildjobs.Member(**base)


def linen_hoard():
    """Grunty's bags on 2026-11-13: 25 full stacks of Linen Cloth and one of 13."""
    return [stack(100 + i, LINEN, 20) for i in range(25)] + [stack(200, LINEN, 13)]


def aim(name="Grunty"):
    return pvpgear.Aim(name, "Bonkers", 30, 19325, "Outrider's Bow", 400, 0, pvpgear.AV)


TAILOR = {"Bonkers": {TAILORING: [("Oz", 151)]}}


class OneBatchIsKept(unittest.TestCase):
    def test_a_first_aid_member_keeps_one_stack_of_its_linen_hoard(self):
        m = member(carried=linen_hoard())
        self.assertIn(LINEN, guildjobs.craft_entries(m))

        posted = guildjobs.postable(m, None)

        self.assertEqual(25, len(posted))
        kept = {c.guid for c in m.carried} - {c.guid for c in posted}
        self.assertEqual(1, len(kept))
        (guid,) = kept
        self.assertEqual(20, next(c.count for c in m.carried if c.guid == guid))

    def test_the_batch_names_one_cast_per_craft_batch(self):
        m = member(carried=linen_hoard())
        self.assertEqual(guildjobs.CRAFT_BATCH, guildjobs.craft_keep(m)[LINEN])

    def test_one_stack_that_holds_the_batch_is_kept(self):
        m = member(carried=[stack(1, LINEN, 25)])
        self.assertEqual([], guildjobs.postable(m, None))

    def test_small_stacks_are_kept_until_they_cover_the_batch(self):
        m = member(carried=[stack(1, LINEN, 6), stack(2, LINEN, 5), stack(3, LINEN, 4)])
        posted = guildjobs.postable(m, None)
        self.assertEqual([3], [c.guid for c in posted])

    def test_a_raider_keeps_nothing_back_for_casts(self):
        m = member(role=guildjobs.RAIDER, carried=[stack(1, LINEN, 25)])
        self.assertEqual([1], [c.guid for c in guildjobs.postable(m, None)])


class TheCraftersPostComesFirst(unittest.TestCase):
    def test_silk_a_family_tailor_can_use_goes_before_a_pvp_buy(self):
        m = member(carried=[stack(1, SILK, 20, name="Silk Cloth")])
        pvp = {"Grunty": (aim(), pvpgear.Move(pvpgear.BUY, ""))}

        result = guildjobs.plan([m], crafters=TAILOR, pvp=pvp)

        (step,) = [s for s in result.steps if s.holder == "Grunty"]
        self.assertEqual("post", step.action)
        self.assertEqual("Oz", step.rows[0].target_arg)
        self.assertIn("its crafter", step.said)

    def test_a_stack_only_the_bank_takes_keeps_its_old_place(self):
        m = member(carried=[stack(1, ORE, 20, subclass=7, name="Copper Ore")])
        pvp = {"Grunty": (aim(), pvpgear.Move(pvpgear.BUY, ""))}

        result = guildjobs.plan([m], crafters=TAILOR, pvp=pvp)

        actions = [s.action for s in result.steps if s.holder == "Grunty"]
        self.assertNotIn("post", actions)

    def test_the_bank_stacks_ride_along_once_the_early_post_goes(self):
        m = member(
            carried=[
                stack(1, ORE, 20, subclass=7, name="Copper Ore"),
                stack(2, SILK, 20, name="Silk Cloth"),
            ]
        )
        step = guildjobs.crafter_post_first(m, TAILOR, "Zug", None, (), 600)
        self.assertEqual({"Oz", "Zug"}, {r.target_arg for r in step.rows})

    def test_bank_stacks_alone_do_not_start_the_early_post(self):
        m = member(carried=[stack(1, ORE, 20, subclass=7, name="Copper Ore")])
        self.assertIsNone(guildjobs.crafter_post_first(m, TAILOR, "Zug", None, (), 600))

    def test_a_raider_does_not_post_early(self):
        m = member(role=guildjobs.RAIDER, carried=[stack(2, SILK, 20)])
        self.assertIsNone(guildjobs.crafter_post_first(m, TAILOR, "Zug", None, (), 600))

    def test_a_member_in_combat_or_dead_does_not_post_early(self):
        for over in ({"in_combat": True}, {"alive": False}, {"online": False}):
            with self.subTest(**over):
                m = member(carried=[stack(2, SILK, 20)], **over)
                self.assertIsNone(
                    guildjobs.crafter_post_first(m, TAILOR, "Zug", None, (), 600)
                )


if __name__ == "__main__":
    unittest.main()

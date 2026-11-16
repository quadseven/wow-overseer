"""A craft step is written only for a member with a free bag slot (#2401).

Read-only on the dev realm 2026-11-13: every corps crafter whose craft casts
came back `unchanged` with `the cast did not start and every wall this row can
read was clear` had no free bag slot. The core refuses a create-item spell when
the product cannot be stored (Spell::CheckItems, SPELL_FAILED_DONT_REPORT), so
those casts could never land. A member with full bags makes room first, through
the same ladder a class quest and an upgrade use.
"""

import unittest

import guildjobs
from test_guildjobs import member, only_step, plan, stack

FA, H = guildjobs.FIRST_AID, guildjobs.HERBALISM
LINEN = 2589
# A priced herb the member's own First Aid does not eat.
HERB = stack(9, 2449, 5, subclass=9, price=10)


def medic(free, *extra, **over):
    return member(
        "Medic",
        skills={FA: (10, 75), H: (40, 75), 171: (10, 75)},
        carried=(stack(1, LINEN, 14, subclass=5), *extra),
        free_slots=free,
        bag_slots=16,
        **over,
    )


class ACraftNeedsAFreeBagSlot(unittest.TestCase):
    def test_a_member_with_a_free_slot_crafts(self):
        step = only_step(plan([medic(1)]), "Medic")
        self.assertEqual(step.action, "craft")

    def test_a_member_whose_bags_were_not_read_still_crafts(self):
        step = only_step(plan([medic(None)]), "Medic")
        self.assertEqual(step.action, "craft")

    def test_a_member_with_full_bags_is_given_no_craft(self):
        step = only_step(plan([medic(0)]), "Medic")
        self.assertTrue(step is None or step.action != "craft")

    def test_a_member_with_full_bags_makes_room_instead(self):
        step = only_step(plan([medic(0, HERB)]), "Medic")
        self.assertIsNotNone(step)
        self.assertEqual(step.action, guildjobs.ROOM_ACTION)
        self.assertIn("to craft Linen Bandage", step.said)

    def test_the_room_step_never_sells_the_cloth_the_craft_eats(self):
        step = only_step(plan([medic(0, HERB)]), "Medic")
        sold = {r.command for r in step.rows if r.kind == "sell"}
        self.assertNotIn("guid:1", sold)

    def test_a_full_member_on_its_room_cooldown_is_given_no_craft(self):
        recent = (guildjobs.Recent("Medic", guildjobs.ROOM_ACTION, 5),)
        step = only_step(plan([medic(0, HERB)], recent=recent), "Medic")
        self.assertTrue(step is None or step.action != "craft")

    def test_a_full_member_with_nothing_to_part_with_says_so(self):
        result = plan([medic(0)])
        step = only_step(result, "Medic")
        self.assertTrue(step is None or step.action != "craft")
        self.assertTrue(
            any("no free bag slot for its Linen Bandage" in n for n in result.notes),
            result.notes,
        )


if __name__ == "__main__":
    unittest.main()

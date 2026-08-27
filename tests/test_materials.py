"""Whose bags a reagent should end up in, and only there (infra#2830).

Pure unit tests against synthetic Holdings - this suite proves the DECISION
is right for the inputs given. It does not, and cannot, prove that
bridge.py's SQL produces those inputs correctly against a live server:
`wow-dev` was mid-RAM-swap when this landed, so that half is unverified and
materials.py's own docstring says so. See tests/test_give.py for what IS
proven about the mechanism the decision here is turned into (kind='give').
"""
import unittest

import materials


def _holding(holder, material, count, guid):
    return materials.Holding(holder=holder, material=material, count=count, guid=guid)


# The family exactly as #2830 measured it live 2026-08-24.
def _measured_holdings():
    return [
        _holding("Bork", "Linen Cloth", 19, 101),
        _holding("Bork", "Silverleaf", 19, 102),
        _holding("Bork", "Bolt of Linen Cloth", 2, 103),
        _holding("Ugga", "Linen Cloth", 13, 201),
        _holding("Ugga", "Silverleaf", 18, 202),
        _holding("Ugga", "Bolt of Linen Cloth", 1, 203),
        _holding("Og", "Linen Cloth", 15, 301),
        _holding("Og", "Silverleaf", 13, 302),
        _holding("Og", "Peacebloom", 7, 303),
        _holding("Grog", "Linen Cloth", 18, 401),
        _holding("Grug", "Linen Cloth", 19, 501),
        _holding("Grug", "Silver Ore", 2, 502),
        _holding("Grug", "Malachite", 4, 503),
    ]


class CrafterForTest(unittest.TestCase):
    def test_every_measured_reagent_resolves_to_its_assigned_crafter(self):
        self.assertEqual(materials.crafter_for("Linen Cloth"), "Og")
        self.assertEqual(materials.crafter_for("Bolt of Linen Cloth"), "Og")
        self.assertEqual(materials.crafter_for("Silverleaf"), "Ugga")
        self.assertEqual(materials.crafter_for("Peacebloom"), "Ugga")
        self.assertEqual(materials.crafter_for("Silver Ore"), "Grug")
        self.assertEqual(materials.crafter_for("Malachite"), "Grog")

    def test_an_unlisted_material_has_no_opinion(self):
        self.assertEqual(materials.crafter_for("Hearthstone"), "")


class PlanTest(unittest.TestCase):
    def test_every_stack_in_the_wrong_hands_becomes_a_grant(self):
        plan = materials.plan(_measured_holdings())
        moved = {(g.holder, g.material) for g in plan.grants}
        # Linen Cloth and the Bolts move to Og from everyone but him.
        self.assertIn(("Bork", "Linen Cloth"), moved)
        self.assertIn(("Bork", "Bolt of Linen Cloth"), moved)
        self.assertIn(("Ugga", "Linen Cloth"), moved)
        self.assertIn(("Ugga", "Bolt of Linen Cloth"), moved)
        self.assertIn(("Grog", "Linen Cloth"), moved)
        self.assertIn(("Grug", "Linen Cloth"), moved)
        # Silverleaf and Peacebloom move to Ugga from everyone but her.
        self.assertIn(("Bork", "Silverleaf"), moved)
        self.assertIn(("Og", "Silverleaf"), moved)
        # Malachite (a jewelcrafting reagent) moves off Grug to Grog, even
        # though Grug is himself a crafter - just not of THIS material.
        self.assertIn(("Grug", "Malachite"), moved)

    def test_a_stack_already_in_the_crafters_own_hands_is_not_regranted(self):
        plan = materials.plan(_measured_holdings())
        moved = {(g.holder, g.material) for g in plan.grants}
        self.assertNotIn(("Og", "Linen Cloth"), moved)

    def test_silver_ore_stays_with_grug_because_he_is_assigned_blacksmithing(self):
        """Grug is the family's assigned blacksmithing, so his own Silver Ore
        is already in the right hands - it must not be handed to himself."""
        plan = materials.plan(_measured_holdings())
        moved = {(g.holder, g.material) for g in plan.grants}
        self.assertNotIn(("Grug", "Silver Ore"), moved)

    def test_grants_name_the_right_taker_and_carry_the_guid(self):
        plan = materials.plan([_holding("Bork", "Linen Cloth", 19, 101)])
        self.assertEqual(len(plan.grants), 1)
        grant = plan.grants[0]
        self.assertEqual(grant.holder, "Bork")
        self.assertEqual(grant.taker, "Og")
        self.assertEqual(grant.count, 19)
        self.assertEqual(grant.guid, 101)
        self.assertEqual(grant.skill, "tailoring")

    def test_the_give_command_addresses_the_guid_not_the_name(self):
        """DoGive (infra#2597) parses `guid:<item_instance.guid>` - a name or
        a count in this field would be a malformed spec it refuses outright."""
        grant = materials.plan(
            [_holding("Bork", "Linen Cloth", 19, 101)]
        ).grants[0]
        self.assertEqual(grant.command, "guid:101")

    def test_an_unmapped_material_is_left_alone(self):
        plan = materials.plan([_holding("Bork", "Hearthstone", 1, 999)])
        self.assertEqual(plan.grants, ())
        self.assertEqual(plan.notes, ())

    def test_the_plan_is_deterministic(self):
        holdings = _measured_holdings()
        first = materials.plan(holdings)
        second = materials.plan(list(reversed(holdings)))
        self.assertEqual(first.grants, second.grants)

    def test_the_reason_and_the_said_line_are_never_empty(self):
        for grant in materials.plan(_measured_holdings()).grants:
            self.assertTrue(grant.reason.strip())
            self.assertTrue(grant.said.strip())

    def test_an_empty_holdings_list_plans_nothing(self):
        self.assertEqual(materials.plan([]), materials.Plan())


class LinesTest(unittest.TestCase):
    def test_lines_are_spoken_by_the_holder_giving_it_up(self):
        plan = materials.plan([_holding("Bork", "Linen Cloth", 19, 101)])
        said = materials.lines(plan)
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("Bork: "))
        self.assertIn("Og", said[0])


if __name__ == "__main__":
    unittest.main()

"""The vault's vendor and give decisions are carried out (#2602).

`bankforecast` decided "give" and "vendor" for 37 of one vault's stacks and
22 of the other's and logged them as the plan only. Only a stack listed for
the house or a crafter's reagent ever left, so the vault only filled.
`plan_surplus_withdrawals` takes the vendor stacks (and a give by the member
it is for) with the same `bank withdraw-item` verb.
"""

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bankforecast as bf  # noqa: E402
import itemplan  # noqa: E402
from test_bank_withdraw import CAVE_RIGHTS, right  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]


def stack(guid, count=5, entry=2589, tab=0):
    return bf.Stack(guid, entry, count, tab)


def vendor(guid, count=5, worth=500, item_class=7, quality=1, kind=bf.SURPLUS):
    return bf.Decision(
        stack(guid, count),
        "Junk",
        bf.VENDOR,
        kind,
        "past the target",
        worth=worth,
        item_class=item_class,
        quality=quality,
    )


def give(guid, taker, count=5):
    return bf.Decision(
        stack(guid, count), "Silk", bf.GIVE, bf.NOW, "a rung eats it", taker=taker
    )


def keep(guid, kind=bf.NOW):
    return bf.Decision(stack(guid), "Linen", bf.KEEP, kind, "needed")


def forecast(*decisions):
    line = bf.Line(
        entry=1,
        item="x",
        vault=0,
        stacks=len(decisions),
        held=0,
        target=0,
        kind=bf.SURPLUS,
        why="",
        decisions=tuple(decisions),
    )
    return bf.Forecast(lines=(line,))


def takers(free=None, rights=CAVE_RIGHTS):
    return bf.withdrawers(rights, free or {"Grug": 30, "Og": 30})


def guids(taken):
    return [w.stack.guid for w in taken]


class AVendorStackIsTaken(unittest.TestCase):
    def test_a_vendor_stack_is_planned_for_a_member_with_room_and_the_right(self):
        taken = bf.plan_surplus_withdrawals(forecast(vendor(1)), takers())
        self.assertEqual([1], guids(taken))
        self.assertEqual("Grug", taken[0].character)
        self.assertEqual(bf.WITHDRAW_SOURCE, taken[0].source)
        self.assertEqual("bank withdraw-item guid:1 tab:0", taken[0].command)
        self.assertIn("to sell to a vendor", taken[0].line)

    def test_the_biggest_pile_goes_first(self):
        taken = bf.plan_surplus_withdrawals(
            forecast(vendor(1, count=2), vendor(2, count=9), vendor(3, count=5)),
            takers(),
        )
        self.assertEqual([2, 3, 1], guids(taken))

    def test_a_member_without_room_takes_nothing(self):
        free = {"Grug": bf.WITHDRAW_KEEP_FREE, "Og": 30}
        self.assertEqual(
            (), bf.plan_surplus_withdrawals(forecast(vendor(1)), takers(free))
        )

    def test_a_visit_takes_at_most_the_visit_limit(self):
        many = forecast(*(vendor(i) for i in range(1, 20)))
        taken = bf.plan_surplus_withdrawals(many, takers())
        self.assertEqual(bf.WITHDRAW_VISIT_STACKS, len(taken))

    def test_a_rank_with_no_withdraw_right_takes_nothing(self):
        only_og = (right("Og", 1, 0, 3),)
        self.assertEqual(
            (),
            bf.plan_surplus_withdrawals(forecast(vendor(1)), takers(rights=only_og)),
        )

    def test_withdrawals_already_planned_count_against_the_visit(self):
        house = [
            bf.Withdrawal("Grug", stack(100 + i), "Linen", 700)
            for i in range(bf.WITHDRAW_VISIT_STACKS)
        ]
        taken = bf.plan_surplus_withdrawals(
            forecast(vendor(1)), takers(), planned=house
        )
        self.assertEqual((), taken)

    def test_a_stack_already_planned_is_not_named_twice(self):
        house = [bf.Withdrawal("Grug", stack(1), "Linen", 700)]
        taken = bf.plan_surplus_withdrawals(
            forecast(vendor(1), vendor(2)), takers(), planned=house
        )
        self.assertEqual([2], guids(taken))

    def test_an_entry_with_a_withdrawn_stack_still_waiting_is_not_taken_again(self):
        taken = bf.plan_surplus_withdrawals(
            forecast(vendor(1)), takers(), pending=frozenset({2589})
        )
        self.assertEqual((), taken)


class WhatIsNeverTakenOut(unittest.TestCase):
    def test_a_kept_stack_is_never_withdrawn(self):
        kept = forecast(
            keep(1, bf.NOW),
            keep(2, bf.LATER),
            keep(3, bf.RAID),
            keep(4, bf.UNJUDGED),
        )
        self.assertEqual((), bf.plan_surplus_withdrawals(kept, takers()))

    def test_a_recipe_is_never_taken_out_to_be_sold(self):
        recipe = forecast(vendor(1, item_class=bf.ITEM_CLASS_RECIPE))
        self.assertEqual((), bf.plan_surplus_withdrawals(recipe, takers()))

    def test_a_raid_reserve_marked_vendor_is_still_left_alone(self):
        raid = forecast(vendor(1, kind=bf.RAID))
        self.assertEqual((), bf.plan_surplus_withdrawals(raid, takers()))

    def test_a_dear_stack_waits_for_the_confirm_gate(self):
        dear = forecast(vendor(1, worth=itemplan.CONFIRM_VALUE))
        self.assertEqual((), bf.plan_surplus_withdrawals(dear, takers()))
        cheap = forecast(vendor(1, worth=itemplan.CONFIRM_VALUE - 1))
        self.assertEqual([1], guids(bf.plan_surplus_withdrawals(cheap, takers())))

    def test_a_rare_stack_waits_for_the_confirm_gate(self):
        rare = forecast(vendor(1, quality=3))
        self.assertEqual((), bf.plan_surplus_withdrawals(rare, takers()))

    def test_a_vendor_decision_with_no_facts_is_not_guessed_at(self):
        bare = bf.Decision(stack(1), "Junk", bf.VENDOR, bf.SURPLUS, "why")
        self.assertEqual((), bf.plan_surplus_withdrawals(forecast(bare), takers()))


class AGiveIsTakenByTheMemberItIsFor(unittest.TestCase):
    def test_the_taker_withdraws_it_under_its_own_source(self):
        rights = (right("Grug", 0, 4294967295, 255), right("Og", 1, 5, 1))
        taken = bf.plan_surplus_withdrawals(
            forecast(give(1, "Og")), takers(rights=rights)
        )
        self.assertEqual(["Og"], [w.character for w in taken])
        self.assertEqual(bf.GIVE_SOURCE, taken[0].source)
        self.assertIn("the forecast gives it to Og", taken[0].line)

    def test_a_taker_who_may_not_withdraw_gets_nothing_from_anybody_else(self):
        # Og's rank has no daily allowance: Grug does not take it in Og's stead.
        taken = bf.plan_surplus_withdrawals(forecast(give(1, "Og")), takers())
        self.assertEqual((), taken)

    def test_a_give_is_not_marked_for_sale(self):
        src = (HERE / "bankforecast.py").read_text(encoding="utf-8")
        sql = src[src.index("WITHDRAWN_SQL = (") : src.index("def read_withdrawers")]
        self.assertIn("'guildbank-give'", sql)
        self.assertTrue(re.search(r"source NOT IN \(.*guildbank-craft", sql))


class TheBridgeCarriesTheDecisionsOut(unittest.TestCase):
    def test_the_vault_pass_asks_for_vendor_and_give_decisions_too(self):
        src = (HERE / "bridge.py").read_text(encoding="utf-8")
        body = src[
            src.index("def _plan_guild_withdrawals(") : src.index(
                "def _clearance_sales("
            )
        ]
        self.assertIn("bankforecast.plan_surplus_withdrawals(", body)
        self.assertIn("planned=placed", body)
        self.assertIn("not selling and not crafting and not clearing", body)


if __name__ == "__main__":
    unittest.main()

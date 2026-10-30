import ast
import logging
import pathlib
import unittest
from unittest import mock

import bag_pressure
import disposition
from bag_pressure import (
    ItemForSale,
    bag_candidates,
    bag_purchase_allowed,
    family_sale_slots,
    family_town_run_needed,
    gear_candidates,
    item_binding,
    sellable,
    town_run_needed,
    protection_counts,
    vendor_trip_makes_room,
    vendor_batch,
    vendor_candidates,
    vendor_holders_to_queue,
)

# The family in town: a vendor in reach, nothing else built yet.
IN_TOWN = disposition.Family(vendor_reachable=True)


def gear(**kw):
    """One carried armour row, shaped as the vendor SQL returns it."""
    base = dict(
        holder="Grog",
        level=26,
        item_guid=5001,
        count=1,
        instance_flags=0,
        name="Smelting Pants",
        quality=2,
        sell_price=966,
        required_level=16,
        bonding=2,
        item_class=4,
    )
    base.update(kw)
    return base


def bag(**kw):
    """One carried container row, shaped as the vendor SQL returns it.

    Defaults are Grug's real "Green Leather Bag" (infra#4163): 8 slots,
    common quality, unbound, worth 875 copper - a redundant duplicate of one
    of his two equipped 8-slot bags.
    """
    base = dict(
        holder="Grug",
        item_guid=9001,
        count=1,
        instance_flags=0,
        name="Green Leather Bag",
        quality=1,
        sell_price=875,
        item_class=1,
        container_slots=8,
        bonding=0,
    )
    base.update(kw)
    return base


# Grug's real four equipped bags (infra#4163): two 16-slot, two 8-slot.
GRUG_EQUIPPED_BAGS = {"Grug": (16, 16, 8, 8)}


class BagPressureTests(unittest.TestCase):
    def test_full_family_triggers_town_run(self):
        self.assertTrue(town_run_needed(44, 44))
        self.assertFalse(town_run_needed(10, 44))

    def test_any_family_member_at_the_floor_triggers_town_run(self):
        self.assertTrue(family_town_run_needed({"Grug": 0, "Ugga": 10}))
        self.assertTrue(family_town_run_needed({"Grug": 2}))
        # mod-overseer's town trip starts at three free slots. The bridge must
        # produce its sale rows at the same boundary or the family reaches the
        # vendor and waits through the whole dwell with nothing to execute.
        self.assertTrue(family_town_run_needed({"Grug": 3, "Ugga": 10}))
        self.assertFalse(family_town_run_needed({"Grug": 4, "Ugga": 10}))

    def test_unknown_family_capacity_does_not_trigger_a_blind_trip(self):
        self.assertFalse(family_town_run_needed({}))
        self.assertFalse(family_town_run_needed({"Grug": -1}))
        self.assertFalse(family_town_run_needed({"Grug": None}))

    def test_never_sells_a_rare(self):
        self.assertFalse(sellable(ItemForSale(quality=3, sell_price=500)))

    def test_never_sells_quest_or_profession_materials(self):
        self.assertFalse(
            sellable(ItemForSale(quality=1, quest_item=True, sell_price=1))
        )
        self.assertFalse(sellable(ItemForSale(quality=1, reagent=True, sell_price=1)))
        self.assertFalse(
            sellable(ItemForSale(quality=1, profession_needed=True, sell_price=1))
        )

    def test_sells_only_positive_value_common_goods(self):
        self.assertTrue(sellable(ItemForSale(quality=0, sell_price=10)))
        self.assertFalse(sellable(ItemForSale(quality=1, sell_price=0)))

    def test_protection_counts_explain_overlapping_bag_pressure(self):
        rows = [
            {
                "quality": 3,
                "sell_price": 20,
                "quest_item": True,
                "reagent": False,
                "profession_needed": False,
            },
            {
                "quality": 1,
                "sell_price": 3,
                "quest_item": False,
                "reagent": True,
                "profession_needed": True,
            },
            {"quality": 0, "sell_price": 1},
        ]
        self.assertEqual(
            protection_counts(rows),
            {
                "rows": 3,
                "quest": 1,
                "reagent": 1,
                "profession": 1,
                "rare_or_better": 1,
                "unknown": 1,
            },
        )

    def test_bag_purchase_requires_empty_position_and_reserve(self):
        self.assertTrue(bag_purchase_allowed(20000, 5000, True))
        self.assertFalse(bag_purchase_allowed(12000, 5000, True))
        self.assertFalse(bag_purchase_allowed(20000, 5000, False))

    def test_vendor_candidates_preserve_identity_and_count(self):
        rows = [
            {
                "holder": "Og",
                "item_guid": 42,
                "count": 7,
                "quality": 0,
                "sell_price": 12,
                "quest_item": False,
                "reagent": False,
                "profession_needed": False,
            }
        ]
        self.assertEqual(vendor_candidates(rows)[0].item_guid, 42)
        self.assertEqual(vendor_candidates(rows)[0].count, 7)

    def test_vendor_candidates_fail_closed_for_unknowns(self):
        rows = [
            {
                "holder": "Og",
                "item_guid": 43,
                "count": 1,
                "quality": 0,
                "sell_price": 12,
            }
        ]
        self.assertEqual(vendor_candidates(rows), ())

    def test_guild_tabard_is_never_a_vendor_candidate(self):
        rows = [
            {
                "holder": "Og",
                "item_guid": 44,
                "entry": 5976,
                "count": 1,
                "quality": 0,
                "sell_price": 1,
                "quest_item": False,
                "reagent": False,
                "profession_needed": False,
            }
        ]
        self.assertEqual(vendor_candidates(rows), ())

    def test_vendor_batch_scopes_one_travelling_holder(self):
        rows = vendor_candidates(
            [
                {
                    "holder": "Og",
                    "item_guid": 7,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 3,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
                {
                    "holder": "Grug",
                    "item_guid": 8,
                    "count": 2,
                    "quality": 1,
                    "sell_price": 4,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
            ]
        )
        holder, batch = vendor_batch(rows)
        self.assertEqual(holder, "Grug")
        self.assertEqual([item.holder for item in batch], ["Grug"])

    def test_leader_arrival_queues_followers_for_executor_retry(self):
        rows = vendor_candidates(
            [
                {
                    "holder": "Og",
                    "item_guid": 7,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 3,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
                {
                    "holder": "Grug",
                    "item_guid": 8,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 4,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
            ]
        )
        self.assertEqual(
            ("Grug", "Og"),
            vendor_holders_to_queue(
                rows,
                leader="Grug",
                leader_at_counter=True,
                holder_at_counter=lambda _: False,
                leader_walking=True,
            ),
        )

    def test_before_leader_arrival_range_gate_is_preserved(self):
        rows = vendor_candidates(
            [
                {
                    "holder": "Og",
                    "item_guid": 7,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 3,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
                {
                    "holder": "Grug",
                    "item_guid": 8,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 4,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
            ]
        )
        self.assertEqual(
            ("Grug",),
            vendor_holders_to_queue(
                rows,
                leader="Grug",
                leader_at_counter=False,
                holder_at_counter=lambda name: name == "Grug",
                leader_walking=True,
            ),
        )

    def test_a_leader_walking_nowhere_gets_no_rows(self):
        """#297, measured on wow-dev 2026-09-24: a trainer walk held the
        Horde leader's travel column, the vendor aim was refused, and 57 rows
        queued from where it stood all answered `vendor not in range`."""
        rows = vendor_candidates(
            [
                {
                    "holder": name,
                    "item_guid": guid,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 4,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                }
                for guid, name in enumerate(("Zug", "Oz", "Zork"), start=1)
            ]
        )

        def queue(walking, at_counter=lambda _: False):
            return vendor_holders_to_queue(
                rows,
                leader="Zug",
                leader_at_counter=False,
                holder_at_counter=at_counter,
                leader_walking=walking,
            )

        self.assertEqual((), queue(False))
        self.assertEqual(("Zug",), queue(True))
        # A follower standing at a counter of its own still sells.
        self.assertEqual(("Oz",), queue(False, lambda name: name == "Oz"))


class BindingIsAFactAboutTheCopy(unittest.TestCase):
    def test_a_worn_bind_on_equip_green_is_soulbound(self):
        """38 of the family's 111 bind-on-equip greens are in this state."""
        self.assertEqual(
            item_binding(gear(bonding=2, instance_flags=1)), disposition.BIND_ON_PICKUP
        )

    def test_an_unworn_bind_on_equip_green_is_still_tradable(self):
        self.assertEqual(
            item_binding(gear(bonding=2, instance_flags=0)), disposition.BIND_ON_EQUIP
        )

    def test_a_bonding_value_we_cannot_read_is_no_answer_at_all(self):
        self.assertEqual(item_binding(gear(bonding=99)), "")
        self.assertEqual(gear_candidates([gear(bonding=99)], IN_TOWN), ())


class OnlyGearNobodyElseCouldEverUse(unittest.TestCase):
    """Clearing the bags without spending what the family cannot get back."""

    def test_an_outgrown_soulbound_piece_is_offered_to_the_vendor(self):
        got = gear_candidates([gear(instance_flags=1, required_level=15)], IN_TOWN)
        self.assertEqual([c.item_guid for c in got], [5001])
        self.assertEqual(got[0].holder, "Grog")

    def test_a_tradable_green_is_left_alone_while_nothing_can_list_it(self):
        self.assertEqual(
            gear_candidates([gear(instance_flags=0, required_level=15)], IN_TOWN), ()
        )

    def test_gear_close_to_level_is_never_sold_however_it_is_bound(self):
        self.assertEqual(
            gear_candidates([gear(instance_flags=1, required_level=25)], IN_TOWN), ()
        )

    def test_a_worthless_piece_is_not_walked_to_a_vendor(self):
        self.assertEqual(
            gear_candidates(
                [gear(instance_flags=1, required_level=15, sell_price=0)], IN_TOWN
            ),
            (),
        )

    def test_a_quest_item_is_refused_even_wearing_an_armour_class(self):
        self.assertEqual(
            gear_candidates(
                [gear(instance_flags=1, required_level=15, item_class=12)], IN_TOWN
            ),
            (),
        )

    def test_a_row_missing_the_facts_is_dropped_not_guessed_at(self):
        broken = gear(instance_flags=1, required_level=15)
        del broken["sell_price"]
        self.assertEqual(gear_candidates([broken], IN_TOWN), ())

    def test_no_vendor_in_reach_means_nothing_is_queued(self):
        away = disposition.Family(vendor_reachable=False)
        self.assertEqual(
            gear_candidates([gear(instance_flags=1, required_level=15)], away), ()
        )

    def test_turning_the_auction_on_stops_the_vendor_taking_them(self):
        """When mod-overseer#208 lands, the same soulbound piece is still a
        vendor sale, because soulbound is the fact that decides it."""
        both = disposition.EXECUTABLE_TODAY | {disposition.AUCTION}
        got = gear_candidates(
            [gear(instance_flags=1, required_level=15)], IN_TOWN, available=both
        )
        self.assertEqual(len(got), 1)


class RedundantCarriedBags(unittest.TestCase):
    """Bags that duplicate what a holder already wears (infra#4163)."""

    def test_a_bag_no_better_than_the_smallest_equipped_one_is_sold(self):
        got = bag_candidates([bag()], GRUG_EQUIPPED_BAGS)
        self.assertEqual([c.item_guid for c in got], [9001])
        self.assertEqual(got[0].holder, "Grug")

    def test_a_bag_that_beats_the_smallest_equipped_one_is_kept(self):
        """Grug's real Netherweave Bag: 16 slots beats his two 8-slot bags -
        an upgrade, not vendor trash, even though it is still unbound."""
        self.assertEqual(
            bag_candidates(
                [bag(container_slots=16, quality=2, sell_price=10000)],
                GRUG_EQUIPPED_BAGS,
            ),
            (),
        )

    def test_a_bind_on_equip_bag_is_kept_even_when_it_is_no_upgrade(self):
        """One accidental /equip from being useful - out of scope here."""
        self.assertEqual(bag_candidates([bag(bonding=2)], GRUG_EQUIPPED_BAGS), ())

    def test_a_holder_with_no_known_equipped_bags_keeps_everything(self):
        self.assertEqual(bag_candidates([bag()], {}), ())
        self.assertEqual(bag_candidates([bag(holder="Ugga")], GRUG_EQUIPPED_BAGS), ())

    def test_the_owners_never_dispose_mark_protects_a_bag(self):
        self.assertEqual(
            bag_candidates(
                [bag()], GRUG_EQUIPPED_BAGS, keep_names=("Green Leather Bag",)
            ),
            (),
        )

    def test_a_worthless_bag_is_not_walked_to_a_vendor(self):
        self.assertEqual(bag_candidates([bag(sell_price=0)], GRUG_EQUIPPED_BAGS), ())

    def test_a_non_container_item_class_is_never_treated_as_a_bag(self):
        self.assertEqual(bag_candidates([bag(item_class=12)], GRUG_EQUIPPED_BAGS), ())

    def test_a_bag_the_master_crafted_for_the_guild_is_kept(self):
        """#1667: a Woolen Bag (4240) the holder sewed is the corps' stock for
        a guildmate; the vendor pass sold 47 of them."""
        made = bag(name="Woolen Bag", entry=4240, self_made=True, sell_price=300)
        self.assertEqual(bag_candidates([made], GRUG_EQUIPPED_BAGS), ())

    def test_a_plain_spare_bag_is_still_sold(self):
        """A Woolen Bag the holder did not craft, and a crafted bag that is
        not a ladder bag, are ordinary spares."""
        bought = bag(name="Woolen Bag", entry=4240, self_made=False, sell_price=300)
        other = bag(entry=5571, self_made=True)
        self.assertEqual(len(bag_candidates([bought, other], GRUG_EQUIPPED_BAGS)), 2)

    def test_a_row_missing_the_facts_is_dropped_not_guessed_at(self):
        broken = bag()
        del broken["container_slots"]
        self.assertEqual(bag_candidates([broken], GRUG_EQUIPPED_BAGS), ())


class TheSurplusBagReadCarriesTheCorpsFacts(unittest.TestCase):
    """#1667: corps_bag_kept swallows a missing key and answers False, so the
    two columns and the log line must be pinned or their loss is silent.
    bridge.py is read as source (it needs discord and pymysql to import)."""

    @staticmethod
    def _tree():
        return ast.parse(BRIDGE.read_text(encoding="utf-8"))

    def _sql(self):
        for node in self._tree().body:
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_SURPLUS_BAGS_SQL"
            ):
                return ast.literal_eval(node.value)
        self.fail("_SURPLUS_BAGS_SQL not found")

    def test_the_surplus_bag_sql_reads_the_entry_and_the_crafter(self):
        sql = self._sql()
        self.assertIn("ii.itemEntry AS entry", sql)
        self.assertIn("(ii.creatorGuid = ci.guid) AS self_made", sql)

    def test_a_kept_corps_bag_is_named_in_one_log_line(self):
        fn = next(
            n
            for n in self._tree().body
            if isinstance(n, ast.FunctionDef) and n.name == "_fetch_surplus_bags"
        )
        rows = [
            bag(name="Woolen Bag", entry=4240, self_made=1, holder="Og"),
            bag(name="Linen Bag", entry=4238, self_made=0, holder="Og"),
        ]
        cursor = mock.MagicMock()
        cursor.fetchall.return_value = rows
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        logger = logging.getLogger("test_1667_bridge")
        ns = {
            "bag_pressure": bag_pressure,
            "_connect": lambda: conn,
            "_SURPLUS_BAGS_SQL": "%s",
            "log": logger,
            "pymysql": mock.MagicMock(),
        }
        exec(compile(ast.Module([fn], type_ignores=[]), str(BRIDGE), "exec"), ns)
        with self.assertLogs(logger, level="INFO") as seen:
            got = ns["_fetch_surplus_bags"](["Og"])
        self.assertEqual(len(got), 2)
        kept = [m for m in seen.output if "keeps its crafted" in m]
        self.assertEqual(len(kept), 1)
        self.assertIn("Woolen Bag", kept[0])
        self.assertIn("#1667", kept[0])


if __name__ == "__main__":
    unittest.main()


BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


class TheVendorPassAsksBothHalvesTests(unittest.TestCase):
    """infra#4190: the wiring, not the predicate.

    `family_town_run_needed` grew a `sellable` half, but a caller that omits
    it still compiles and still returns the old answer - which is exactly how
    this would silently regress. bridge.py imports discord and cannot be
    imported here, so this parses it instead. Parsed rather than grepped
    because the comments around these calls quote the old one-argument shape
    verbatim, and a text match would find the prose describing the bug and
    pass while the bug was live.
    """

    def _vendor_once(self):
        tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                and node.name == "_vendor_once"
            ):
                return node
        self.fail("_vendor_once not found in bridge.py")

    def test_every_pressure_question_in_the_vendor_pass_supplies_sellable(self):
        calls = []
        for node in ast.walk(self._vendor_once()):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "family_town_run_needed"
            ):
                calls.append(node)
        self.assertTrue(calls, "the vendor pass asks no pressure question")
        for call in calls:
            kwargs = {kw.arg for kw in call.keywords}
            self.assertIn(
                "sellable",
                kwargs,
                f"bridge.py line {call.lineno}: family_town_run_needed without "
                "`sellable=` asks only whether somebody is full, not whether a "
                "vendor could help - which is infra#4190",
            )

    def test_gear_that_survives_handoff_is_counted_before_trip_gate(self):
        body = self._vendor_once().body
        mode_at = next(
            i
            for i, node in enumerate(body)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "mode"
                for target in node.targets
            )
        )
        before_mode = ast.dump(ast.Module(body=body[:mode_at], type_ignores=[]))
        self.assertIn("gear_candidates", before_mode)
        self.assertIn("sellable_counts", before_mode)

        filtered_sales = next(
            node
            for node in reversed(body[:mode_at])
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "gear_sales"
                for target in node.targets
            )
        )
        self.assertIn("_without_bank_keeps", ast.dump(filtered_sales.value))
        # One counting helper since wow-overseer#977: `_count_sales(counts,
        # sales)`, called with the filtered gear sales before `mode` is read.
        counted = next(
            node.value
            for node in body[:mode_at]
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_count_sales"
            and any(
                isinstance(arg, ast.Name) and arg.id == "gear_sales"
                for arg in node.value.args
            )
        )
        self.assertEqual("sellable_counts", counted.args[0].id)


class AVendorTripMustBeAbleToHelpTests(unittest.TestCase):
    """infra#4190: pressure nobody can answer starved the travel column.

    Og's measured position on 2026-09-19 is the case these pin: 0 free slots
    of 62, one sellable spare bag, everything else protected. Selling all a
    vendor would take reaches 1 free slot against a trigger of 3, so the
    pressure could never clear and the vendor pass re-took the column for
    hours writing no sale.
    """

    def test_a_member_a_vendor_cannot_lift_past_the_trigger_is_not_pressure(self):
        # Og: 0 free, exactly one thing a vendor would accept. 0 + 1 = 1,
        # which is still under the trigger, so the trip cannot answer him.
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={"Og": 1}))

    def test_a_member_a_vendor_can_lift_past_the_trigger_is_pressure(self):
        # 0 + 4 clears a trigger of 3, so the trip is worth taking.
        self.assertTrue(family_town_run_needed({"Og": 0}, sellable={"Og": 4}))

    def test_exactly_reaching_the_trigger_is_not_enough(self):
        # `free <= minimum_free` is what RAISED the pressure, so landing back
        # on the boundary would re-raise it on the next cycle - the trip has
        # to get them past it or it buys nothing.
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={"Og": 3}))
        self.assertTrue(family_town_run_needed({"Og": 1}, sellable={"Og": 3}))

    def test_one_relievable_member_is_enough_even_beside_a_hopeless_one(self):
        # Og cannot be helped; Ugga can. The family should still go.
        self.assertTrue(
            family_town_run_needed({"Og": 0, "Ugga": 1}, sellable={"Og": 1, "Ugga": 9})
        )

    def test_a_member_with_room_is_never_pressure_however_much_he_carries(self):
        self.assertFalse(family_town_run_needed({"Bork": 11}, sellable={"Bork": 40}))

    def test_an_unlisted_member_reads_as_nothing_to_sell(self):
        # Fail closed, matching the existing unknown-capacity bias: a name the
        # caller could not measure must not send the family on a blind trip.
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={}))

    def test_a_broken_sellable_count_is_skipped_rather_than_trusted(self):
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={"Og": -5}))
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={"Og": None}))

    def test_omitting_the_argument_preserves_the_original_behaviour(self):
        # Every caller that only wants "is anyone low" is unchanged.
        self.assertTrue(family_town_run_needed({"Og": 0}))
        self.assertTrue(family_town_run_needed({"Og": 0}, sellable=None))


class TheTripMakesTheFamilyRoomTests(unittest.TestCase):
    """#1204: one walk to a counter sells every holder's stacks.

    The trip's product is the family's room, and the question the vendor pass
    asked was one member's. A family whose members at the floor each carry a
    few stacks a vendor will buy - none of them enough to clear the trigger
    of 3 free slots alone - therefore never cleared the bar on anybody, and
    the pass sat in counter mode writing no sale while every holder with
    something to sell logged "no vendor within reach" on every pass.
    """

    FAMILY = {"Bork": 0, "Grog": 0, "Ugga": 0, "Og": 10}

    def test_the_slots_the_trip_frees_are_the_floor_s(self):
        # Bork carries 68 stacks no vendor will buy, so he frees nothing;
        # Grog and Ugga, at the floor, carry two and one. Neither sale lifts
        # its seller past the trigger of three free slots (0 + 2 = 2, 0 + 1 =
        # 1), so the trip frees the floor for nobody and Bork stays at the
        # floor. Og's two are sold too, but Og has ten free slots: a slot
        # freed in his bags is not one in anybody's at the floor (#1243).
        self.assertEqual(
            0,
            family_sale_slots(
                self.FAMILY,
                {"Bork": 0, "Grog": 2, "Ugga": 1, "Og": 2},
            ),
        )

    def test_a_family_with_room_frees_nothing(self):
        self.assertEqual(0, family_sale_slots({"Bork": 11}, {"Bork": 40}))

    def test_a_member_nobody_can_relieve_contributes_nothing(self):
        # Bork alone: 68 kept stacks, and no vendor will buy one of them.
        self.assertEqual(0, family_sale_slots({"Bork": 0}, {"Bork": 0}))

    def test_an_unreadable_count_frees_nothing(self):
        self.assertEqual(0, family_sale_slots({"Og": 0}, {"Og": None}))
        self.assertEqual(0, family_sale_slots({"Og": 0}, {}))
        self.assertEqual(0, family_sale_slots({"Og": 0}, {"Og": -5}))

    def test_an_unknown_family_frees_nothing(self):
        self.assertEqual(0, family_sale_slots({}, {"Og": 4}))
        self.assertEqual(0, family_sale_slots({"Og": -1}, {"Og": 4}))
        self.assertEqual(0, family_sale_slots({"Og": None}, {"Og": 4}))


class TheTripMakesRoomOnlyAtTheFloorTests(unittest.TestCase):
    """#1243: a slot freed in one member's bags is not room in another's.

    #1227 summed every member's vendor stacks once anybody sat at the floor.
    A family held there by a member who carries only what it keeps (Bork's
    68 stacks no vendor will buy) never stops being at the floor, and its
    questing members pick up three vendor stacks between them in minutes: the
    sum re-armed the trip on every pass, the trip took the leader's walk,
    sold the stacks of members who had room, and left the floor where it was.
    The dungeon quest pass meanwhile held the family on "waits for bag room;
    the vendor trip keeps the travel column" for the whole of it.
    """

    # Bork pinned at the floor by kept stacks; the others questing with room.
    PINNED = {"Bork": 0, "Grog": 12, "Ugga": 9, "Og": 10}
    LOOTED = {"Bork": 0, "Grog": 2, "Ugga": 1, "Og": 2}

    def test_stacks_of_members_with_room_free_nothing_at_the_floor(self):
        self.assertEqual(0, family_sale_slots(self.PINNED, self.LOOTED))

    def test_no_trip_makes_room_for_a_member_pinned_by_kept_stacks(self):
        self.assertFalse(vendor_trip_makes_room(self.PINNED, self.LOOTED))

    def test_stacks_that_lift_no_one_past_the_trigger_free_nothing(self):
        # Zug pins the family at the floor with nothing sellable; Grog and
        # Ugga are at the floor with two and one sellable stacks. Neither sale
        # lifts its seller past the trigger of three free slots, so the trip
        # frees the floor for nobody and Zug stays at the floor. The old
        # collective sum (three) used to re-arm the vendor trip and hold the
        # travel column while Zug never gained a slot.
        self.assertEqual(
            0,
            family_sale_slots(
                {"Zug": 0, "Grog": 0, "Ugga": 0},
                {"Zug": 0, "Grog": 2, "Ugga": 1},
            ),
        )
        self.assertFalse(
            vendor_trip_makes_room(
                {"Zug": 0, "Grog": 0, "Ugga": 0},
                {"Zug": 0, "Grog": 2, "Ugga": 1},
            )
        )

    def test_a_trip_that_lifts_one_member_past_the_trigger_makes_room(self):
        self.assertTrue(vendor_trip_makes_room({"Oz": 0, "Zug": 20}, {"Oz": 4}))

    def test_a_trip_that_frees_the_floor_s_width_between_members_makes_room(self):
        # #1204's family: Grog and Ugga at the floor, two and one stacks.
        # Neither sale lifts its seller past the trigger of three free slots,
        # so the trip frees nobody past the trigger and makes no room for the
        # member who pins the family at the floor.
        self.assertFalse(
            vendor_trip_makes_room(
                {"Bork": 0, "Grog": 0, "Ugga": 0, "Og": 10},
                {"Bork": 0, "Grog": 2, "Ugga": 1, "Og": 2},
            )
        )

    def test_a_family_with_room_needs_no_trip(self):
        self.assertFalse(vendor_trip_makes_room({"Oz": 11}, {"Oz": 40}))

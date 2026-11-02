"""A member held at the bag floor lets go of what nobody will wear (#1678).

Measured on the dev realm on 2026-11-01. A shaman at 1 free slot held its
family's campaign with 36 stacks of carried gear. `gear.claimant` called 29 of
them the holder's upgrades because their item level beat the worn piece, and
the equip pass, judging the same pieces by the spec's gear score, chose 5. The
other 24 could be neither worn nor sold, so no town pass could make room.

A hold past `BAG_HOLD_STUCK_SECONDS` is the evidence the item level answer was
wrong. These tests hold the rule at its seams: the fits the sale passes read,
the sale that follows, and the slot that ends the hold.
"""

import ast
import pathlib
import types
import unittest

import bag_pressure
import clearance
import disposition
import equipscore

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
NAMES = ("Oz", "Zrog")
SHAMAN = 7
MAGE = 8
LEVEL = 46


def carried(guid, name, holder="Zrog", **extra):
    row = {
        "holder": holder,
        "level": LEVEL,
        "item_guid": guid,
        "entry": 1000 + guid,
        "count": 1,
        "name": name,
        "quality": 2,
        "sell_price": 3000,
        "required_level": 35,
        "bonding": 2,
        "instance_flags": 0,
        "item_class": 4,
        "item_subclass": 3,
        "item_level": 40,
        "allowable_class": -1,
        "inventory_type": 10,
        "bag_family": 0,
    }
    row.update(extra)
    return row


def worn(name, class_id, inventory_type, item_level):
    return {
        "name": name,
        "class_id": class_id,
        "level": LEVEL,
        "inventory_type": inventory_type,
        "item_level": item_level,
        "spec_tab": 0,
        "tank_seat": 0,
        "weapon_skills": "",
    }


# Hands at 36 on the shaman and 45 on the mage: a carried item level 40 is an
# upgrade for the holder by item level and for nobody else.
WORN = [worn("Zrog", SHAMAN, 10, 36), worn("Oz", MAGE, 10, 45)]
CLOTH_FOR_THE_MAGE = dict(item_subclass=1)
MAIL = carried(1, "Jazeraint Gauntlets")
FAMILY = disposition.Family(vendor_reachable=True)


def fits_of(rows, worn_rows=WORN):
    return bag_pressure.family_fits(rows, worn_rows, NAMES)


def released(rows, plan, held=("Zrog",), worn_rows=WORN):
    return bag_pressure.floor_release_fits(
        fits_of(rows, worn_rows), rows, worn_rows, NAMES, held, plan
    )


def plan_of(*equips, waiting=(), scored=("Oz", "Zrog")):
    return equipscore.Plan(
        equips=tuple(equips), waiting=tuple(waiting), scored=frozenset(scored)
    )


def picked(row):
    return bag_pressure.Equip(
        holder=row["holder"],
        guid=row["item_guid"],
        entry=row["entry"],
        name=row["name"],
        slot="hands",
        item_level=row["item_level"],
        worn_level=36,
        reason="gear score",
    )


def sale_guids(rows, fits):
    return {
        c.item_guid
        for c in bag_pressure.gear_candidates(
            rows, FAMILY, available=disposition.EXECUTABLE_TODAY, fits=fits
        )
    }


class TheMeasuredHoard(unittest.TestCase):
    def test_item_level_alone_keeps_the_piece_for_ever(self):
        self.assertEqual(disposition.FIT_HOLDER, fits_of([MAIL])[1])
        self.assertEqual(set(), sale_guids([MAIL], fits_of([MAIL])))

    def test_a_piece_the_spec_score_passed_over_reaches_a_vendor(self):
        fits = released([MAIL], plan_of())
        self.assertEqual(disposition.FIT_NOBODY, fits[1])
        self.assertEqual({1}, sale_guids([MAIL], fits))

    def test_a_soulbound_rare_nobody_chose_reaches_a_vendor(self):
        rare = carried(2, "Ironaya's Bracers", quality=3, bonding=1, instance_flags=1)
        self.assertEqual({2}, sale_guids([rare], released([rare], plan_of())))

    def test_a_ring_the_score_passed_over_reaches_a_vendor(self):
        ring = carried(
            3,
            "Meadow Ring",
            inventory_type=11,
            item_subclass=0,
            bonding=1,
            instance_flags=1,
        )
        self.assertEqual(disposition.FIT_UNJUDGEABLE, fits_of([ring])[3])
        self.assertEqual({3}, sale_guids([ring], released([ring], plan_of())))


class WhatStaysKept(unittest.TestCase):
    def test_the_piece_the_holder_will_wear_stays(self):
        fits = released([MAIL], plan_of(picked(MAIL)))
        self.assertEqual(disposition.FIT_HOLDER, fits[1])
        self.assertEqual(set(), sale_guids([MAIL], fits))

    def test_a_weapon_waiting_on_its_skill_stays(self):
        axe = carried(
            4, "Glutton's Cleaver", item_class=2, item_subclass=0, inventory_type=21
        )
        before = fits_of([axe])
        plan = plan_of(waiting=[("Zrog", "Glutton's Cleaver", 44)])
        fits = bag_pressure.floor_release_fits(
            before, [axe], WORN, NAMES, ("Zrog",), plan
        )
        self.assertEqual(before[4], fits[4])

    def test_a_sibling_who_would_wear_it_keeps_it_in_the_family(self):
        gloves = carried(5, "Sorcerer Gloves", **CLOTH_FOR_THE_MAGE)
        low = [worn("Zrog", SHAMAN, 10, 36), worn("Oz", MAGE, 10, 30)]
        fits = released([gloves], plan_of(), worn_rows=low)
        self.assertEqual(disposition.FIT_SIBLING, fits[5])
        self.assertEqual(set(), sale_guids([gloves], fits))

    def test_a_piece_above_the_holders_level_stays(self):
        future = carried(6, "Enduring Cap", required_level=50, item_level=52)
        fits = released([future], plan_of())
        self.assertEqual(fits_of([future])[6], fits[6])

    def test_a_tradable_ring_a_sibling_was_not_asked_about_stays(self):
        ring = carried(9, "Heart Ring", inventory_type=11, item_subclass=0)
        self.assertEqual(disposition.FIT_UNJUDGEABLE, released([ring], plan_of())[9])

    def test_a_trade_tool_stays(self):
        pick = carried(
            10, "Mining Pick", item_class=2, inventory_type=13, bag_family=1024
        )
        before = fits_of([pick])
        self.assertEqual(before[10], released([pick], plan_of())[10])

    def test_an_owner_kept_name_stays(self):
        fits = bag_pressure.floor_release_fits(
            fits_of([MAIL]),
            [MAIL],
            WORN,
            NAMES,
            ("Zrog",),
            plan_of(),
            keep_names=("Jazeraint Gauntlets",),
        )
        self.assertEqual(disposition.FIT_HOLDER, fits[1])

    def test_a_member_not_held_keeps_its_gear(self):
        fits = released([MAIL], plan_of(), held=("Oz",))
        self.assertEqual(disposition.FIT_HOLDER, fits[1])

    def test_a_member_the_score_cannot_judge_keeps_its_gear(self):
        fits = released([MAIL], plan_of(scored=("Oz",)))
        self.assertEqual(disposition.FIT_HOLDER, fits[1])

    def test_an_assigned_recipe_stays_and_an_unwanted_one_is_sold(self):
        recipe = clearance.Stack(
            holder="Zrog",
            guid=7,
            entry=4409,
            name="Schematic: Small Seaforium Charge",
            item_class=clearance.RECIPE_CLASS,
            quality=2,
            sell_price=200,
            required_skill=202,
            required_rank=100,
        )
        people = [clearance.Person("Zrog", {202: 1}, family=True, online=True)]
        kept = clearance.route(recipe, people[0], people, kept=frozenset({7}))
        sold = clearance.route(recipe, people[0], people)
        self.assertEqual(clearance.KEEP, kept.route)
        self.assertEqual(clearance.VENDOR, sold.route)


class TheReasonIsLogged(unittest.TestCase):
    def test_each_released_stack_says_why(self):
        rows = [MAIL, carried(8, "Sparkleshell Gauntlets")]
        lines = bag_pressure.floor_release_lines(
            fits_of(rows), released(rows, plan_of()), rows
        )
        self.assertEqual(2, len(lines))
        self.assertIn("Zrog's Jazeraint Gauntlets", lines[1] + lines[0])
        self.assertTrue(all("gear score" in line for line in lines))


class TheBridgeWiring(unittest.TestCase):
    def _fits(self, free, plan=None, wearers=(("Zrog",),)):
        logged = []
        ns = {
            "bag_pressure": bag_pressure,
            "equipscore": types.SimpleNamespace(plan=lambda *a, **k: plan),
            "_BAG_HOLD_STUCK": {"Zrog": ("Zrog",)},
            "OWNER_KEEPS": (),
            "_fetch_free_slots": lambda names: free,
            "_fetch_wearers": lambda names: list(wearers),
            "_fetch_scored_gear": lambda names: [MAIL],
            "_jev_item_book": lambda: None,
            "_log_changed": lambda *a, **k: logged.append(a),
        }
        wanted = [
            node
            for node in ast.parse(BRIDGE).body
            if isinstance(node, ast.FunctionDef)
            and node.name
            in ("_at_floor", "_released_floor_members", "_released_floor_fits")
        ]
        exec(  # noqa: S102 - bridge.py's own source
            compile(ast.Module(body=wanted, type_ignores=[]), "bridge.py", "exec"), ns
        )
        return ns["_released_floor_fits"](fits_of([MAIL]), [MAIL], WORN, NAMES), logged

    def test_a_released_member_at_the_floor_is_let_go_and_logged(self):
        fits, logged = self._fits({"Zrog": 1}, plan_of())
        self.assertEqual(disposition.FIT_NOBODY, fits[1])
        self.assertEqual("bag floor", logged[0][0])

    def test_a_stale_record_of_a_member_with_room_changes_nothing(self):
        fits, _ = self._fits({"Zrog": 12}, plan_of())
        self.assertEqual(disposition.FIT_HOLDER, fits[1])

    def test_an_unread_score_changes_nothing(self):
        fits, _ = self._fits({"Zrog": 1}, plan_of(), wearers=())
        self.assertEqual(disposition.FIT_HOLDER, fits[1])


class TheHoldEndsOnASlot(unittest.TestCase):
    def _trip(self, fits, rows):
        sold = sale_guids(rows, fits)
        free = {"Zrog": 1}
        return free, {"Zrog": len(sold)}, sold

    def test_the_sales_lift_the_member_off_the_floor_and_end_the_hold(self):
        rows = [carried(guid, "Green %d" % guid) for guid in range(20, 26)]
        free, sellable, _ = self._trip(fits_of(rows), rows)
        self.assertFalse(bag_pressure.vendor_trip_makes_room(free, sellable))
        free, sellable, sold = self._trip(released(rows, plan_of()), rows)
        self.assertTrue(bag_pressure.vendor_trip_makes_room(free, sellable))
        window = bag_pressure.BAG_HOLD_STUCK_SECONDS
        hold = bag_pressure.BagHoldProgress(
            best=(("Zrog", 1),), since=0.0, seen=window, released=True
        )
        after = window + 300.0
        self.assertLess(after, bag_pressure.BAG_HOLD_FORGET_SECONDS)
        self.assertIsNone(
            bag_pressure.bag_hold_progress(hold, {"Zrog": 1 + len(sold)}, after)
        )


if __name__ == "__main__":
    unittest.main()

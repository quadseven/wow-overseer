"""Resistance-only gear stays out of everyday wear (#2658).

Verified item_template rows from the realm DB:
- 11767 Emberplate Armguards: plate wrist (subclass 4, invtype 9, q 3),
  ItemLevel 57, RequiredLevel 52, armor 261, fire_res 10, zero primary stats.
- 17746 Noxxion's Shackles: plate wrist (subclass 4, invtype 9, q 3),
  ItemLevel 51, RequiredLevel 46, armor 235, fire_res 0, +5 Stamina, +15 Strength.
- 8311 Alabaster Plate Vambraces: plate wrist (subclass 4, invtype 9, q 2),
  ItemLevel 53, RequiredLevel 48, armor 222, fire_res 0, +3 Strength, +12 Stamina.
- 11766 Flameweave Cuffs: cloth wrist (subclass 1, invtype 9, q 3),
  ItemLevel 57, RequiredLevel 52, armor 35, fire_res 10, zero primary stats.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bag_pressure  # noqa: E402
import bankpolicy  # noqa: E402
import equipscore  # noqa: E402
import gear  # noqa: E402
import gearup  # noqa: E402
import itemplan_data  # noqa: E402

WARRIOR, PALADIN = 1, 2
PLATE = 4
CLOTH = 1
WRIST = 9
WRIST_SLOT = 8
ALL_CLASSES = -1


def _emberplate(holder="Grog", guid=1001, **over):
    row = {
        "holder": holder,
        "item_guid": guid,
        "entry": 11767,
        "name": "Emberplate Armguards",
        "item_name": "Emberplate Armguards",
        "quality": 3,
        "item_level": 57,
        "required_level": 52,
        "allowable_class": ALL_CLASSES,
        "inventory_type": WRIST,
        "class": 4,
        "item_class": 4,
        "subclass": PLATE,
        "item_subclass": PLATE,
        "armor": 261,
        "block": 0,
        "fire_res": 10,
        "holy_res": 0,
        "frost_res": 0,
        "nature_res": 0,
        "shadow_res": 0,
        "arcane_res": 0,
        "dmg_min1": 0,
        "dmg_max1": 0,
        "delay": 0,
        "random_property_id": 0,
        "RandomProperty": 0,
        "RandomSuffix": 0,
        "instance_flags": 1,
        "bonding": 1,
        "count": 1,
        "sell_price": 13514,
        "quest_needed": 0,
        "place": "bags",
        "stats": {},
    }
    row.update(over)
    return row


def _noxxion(holder="Grog", guid=1002, **over):
    row = _emberplate(
        holder=holder,
        guid=guid,
        entry=17746,
        name="Noxxion's Shackles",
        item_name="Noxxion's Shackles",
        item_level=51,
        required_level=46,
        armor=235,
        fire_res=0,
        stat_type1=7,
        stat_value1=5,
        stat_type2=4,
        stat_value2=15,
    )
    row.update(over)
    return row


def _alabaster(holder="Grug", guid=1003, **over):
    row = _emberplate(
        holder=holder,
        guid=guid,
        entry=8311,
        name="Alabaster Plate Vambraces",
        item_name="Alabaster Plate Vambraces",
        quality=2,
        item_level=53,
        required_level=48,
        armor=222,
        fire_res=0,
        stat_type1=4,
        stat_value1=3,
        stat_type2=7,
        stat_value2=12,
        bonding=2,
        instance_flags=0,
    )
    row.update(over)
    return row


def _flameweave(holder="Grog", guid=1004, **over):
    row = _emberplate(
        holder=holder,
        guid=guid,
        entry=11766,
        name="Flameweave Cuffs",
        item_name="Flameweave Cuffs",
        subclass=CLOTH,
        item_subclass=CLOTH,
        armor=35,
        fire_res=10,
    )
    row.update(over)
    return row


def _worn_row(name, class_id, level, item=None, *, tank_seat=0, spec_tab=0):
    row = {
        "name": name,
        "class_id": class_id,
        "level": level,
        "equipment_slot": WRIST_SLOT if item else None,
        "inventory_type": item["inventory_type"] if item else None,
        "item_level": item["item_level"] if item else None,
        "entry": item["entry"] if item else None,
        "tank_seat": tank_seat,
        "spec_tab": spec_tab,
    }
    if item:
        for key in (
            "armor",
            "block",
            "fire_res",
            "holy_res",
            "frost_res",
            "nature_res",
            "shadow_res",
            "arcane_res",
            "dmg_min1",
            "dmg_max1",
            "delay",
            "stat_type1",
            "stat_value1",
            "stat_type2",
            "stat_value2",
            "random_property_id",
            "resistance_only",
        ):
            if key in item:
                row[key] = item[key]
    return row


class EquipscoreResistanceOnlyTest(unittest.TestCase):
    PLATE_SKILL = frozenset({293})

    def test_retribution_scores_emberplate_at_zero_and_replaces_when_worn(self):
        ret = equipscore.Wearer(
            name="Grog",
            class_id=PALADIN,
            level=59,
            role="melee",
            spec="paladin-retribution",
            skills=self.PLATE_SKILL,
        )
        ember = _emberplate()
        noxx = _noxxion()

        self.assertEqual((0.0, 0.0), equipscore.value(ember, ret))
        self.assertEqual((), equipscore.choose(ret, [], [ember]))
        self.assertEqual(
            (),
            equipscore.choose(ret, [{**noxx, "equipment_slot": WRIST_SLOT}], [ember]),
        )

        pick = equipscore.choose(ret, [{**ember, "equipment_slot": WRIST_SLOT}], [noxx])
        self.assertEqual(17746, pick[0].entry)

    def test_tanks_never_prefer_emberplate_over_real_stat_wrists(self):
        prot_pal = equipscore.Wearer(
            name="Grog",
            class_id=PALADIN,
            level=59,
            role="tank",
            spec="paladin-protection",
            skills=self.PLATE_SKILL,
        )
        prot_war = equipscore.Wearer(
            name="Grug",
            class_id=WARRIOR,
            level=60,
            role="tank",
            spec="warrior-protection",
            skills=self.PLATE_SKILL,
        )
        ember = _emberplate()
        noxx = _noxxion()
        alabaster = _alabaster()

        for wearer in (prot_pal, prot_war):
            self.assertEqual((0.0, 0.0), equipscore.value(ember, wearer))
            self.assertEqual((), equipscore.choose(wearer, [], [ember]))
            self.assertEqual(
                (),
                equipscore.choose(
                    wearer, [{**alabaster, "equipment_slot": WRIST_SLOT}], [ember]
                ),
            )
            self.assertEqual(
                17746,
                equipscore.choose(
                    wearer, [{**ember, "equipment_slot": WRIST_SLOT}], [noxx]
                )[0].entry,
            )
            self.assertEqual(
                8311,
                equipscore.choose(
                    wearer, [{**ember, "equipment_slot": WRIST_SLOT}], [alabaster]
                )[0].entry,
            )

    def test_drive_score_and_verdict_exclude_resistance_only_and_upgrade_off_it(self):
        prot_pal = equipscore.Wearer(
            name="Grog",
            class_id=PALADIN,
            level=59,
            role="tank",
            spec="paladin-protection",
            skills=self.PLATE_SKILL,
        )
        prot_war = equipscore.Wearer(
            name="Grug",
            class_id=WARRIOR,
            level=60,
            role="tank",
            spec="warrior-protection",
            skills=self.PLATE_SKILL,
        )
        ember = _emberplate()
        noxx = _noxxion()
        alabaster = _alabaster()

        self.assertEqual((0.0, False), equipscore.drive_score(ember, "tank"))
        self.assertEqual((0.0, False), equipscore.drive_score(ember, "melee"))

        verdict, _ = equipscore.drive_verdict(ember, prot_war, [])
        self.assertNotEqual(equipscore.DRIVE_WEAR, verdict)

        verdict_vs_alabaster, _ = equipscore.drive_verdict(
            ember, prot_war, [{**alabaster, "equipment_slot": WRIST_SLOT}]
        )
        self.assertNotEqual(equipscore.DRIVE_WEAR, verdict_vs_alabaster)

        verdict_noxx, _ = equipscore.drive_verdict(
            noxx, prot_pal, [{**ember, "equipment_slot": WRIST_SLOT}]
        )
        self.assertEqual(equipscore.DRIVE_WEAR, verdict_noxx)

        verdict_alabaster, _ = equipscore.drive_verdict(
            alabaster, prot_war, [{**ember, "equipment_slot": WRIST_SLOT}]
        )
        self.assertEqual(equipscore.DRIVE_WEAR, verdict_alabaster)

    def test_mixed_stats_or_unread_effects_are_not_resistance_only(self):
        prot_war = equipscore.Wearer(
            name="Grug",
            class_id=WARRIOR,
            level=60,
            role="tank",
            spec="warrior-protection",
        )
        stamina_fr = _emberplate(
            entry=18812,
            name="Wristguards of True Flight",
            stat_type1=7,
            stat_value1=11,
        )
        spell_fr = _emberplate(entry=99901, spellid_1=12345)
        random_fr = _emberplate(entry=99902, random_property_id=500)

        for row in (stamina_fr, spell_fr, random_fr):
            self.assertFalse(equipscore.resistance_only(row))
            self.assertGreater(equipscore.value(row, prot_war)[0], 0.0)


class GearHandoffAndBankPolicyTest(unittest.TestCase):
    def test_gear_refuses_emberplate_for_everyday_wear_and_upgrades_over_worn(self):
        ember = _emberplate()
        noxx = _noxxion()
        alabaster = _alabaster()
        bare_grog = gear.CharacterState(name="Grog", class_id=PALADIN, level=59)

        holdings = gear.holdings_from_rows([ember, noxx, alabaster])
        h_ember, h_noxx, _h_alabaster = holdings
        self.assertTrue(h_ember.resistance_only)
        self.assertFalse(h_noxx.resistance_only)

        wears, _ = gear.would_wear(h_ember, bare_grog)
        self.assertFalse(wears)

        grog_chars = gear.characters_from_rows(
            [_worn_row("Grog", PALADIN, 59, ember, spec_tab=2)], ["Grog"]
        )
        self.assertEqual((), gear.plan([h_ember], grog_chars).grants)
        plan_all = gear.plan(holdings, grog_chars)
        self.assertEqual([8311], [g.entry for g in plan_all.grants])

        wears_noxx, _ = gear.would_wear(h_noxx, grog_chars[0])
        self.assertTrue(wears_noxx)
        self.assertEqual([17746], [e.entry for e in gear.equips(holdings, grog_chars)])

    def test_bankpolicy_keeps_emberplate_in_personal_fire_set_instead_of_claiming_it(
        self,
    ):
        ember = _emberplate(holder="Grog", guid=2001)
        flameweave = _flameweave(holder="Grog", guid=2002)
        noxx = _noxxion(holder="Grog", guid=2003, instance_flags=1)
        worn = [_worn_row("Grog", PALADIN, 59, _alabaster(), spec_tab=2)]

        claimed = bankpolicy.claimed_from_rows(
            [ember, flameweave, noxx], worn, {"Grog"}
        )
        self.assertNotIn(2001, claimed)
        self.assertNotIn(2002, claimed)

        reach = bag_pressure.gear_reach([ember, flameweave], worn, {"Grog"})
        self.assertTrue(reach[2001].holder_wears)

        facts = bankpolicy.facts_from_rows({"Grog"}, [ember, flameweave], worn, [])
        placed = bankpolicy.place(facts)
        self.assertEqual(
            (bankpolicy.PERSONAL, bankpolicy.FIRE_SET),
            (placed[2001].to, placed[2001].kind),
        )


class ItemplanAndGearupTest(unittest.TestCase):
    def test_itemplan_verdicts_fallback_never_wears_resistance_only(self):
        ember = {
            **_emberplate(guid=3001),
            "member": "Grog",
            "req_level": 52,
            "level": 59,
            "resistance_only": True,
        }
        worn = {
            "Grog": {
                "wrists": {
                    "entry": 17746,
                    "item_level": 51,
                    "inventory_type": WRIST,
                    "resistance_only": False,
                }
            }
        }
        verdicts = itemplan_data.upgrade_verdicts(worn, [ember], drive={})
        self.assertNotEqual("wear", verdicts.get(("Grog", 11767)))

    def test_itemplan_verdicts_allows_lower_ilvl_real_stat_over_worn_resistance_only(
        self,
    ):
        noxx = {
            **_noxxion(guid=3002),
            "member": "Grog",
            "req_level": 46,
            "level": 59,
            "resistance_only": False,
        }
        worn = {
            "Grog": {
                "wrists": {
                    "entry": 11767,
                    "item_level": 57,
                    "inventory_type": WRIST,
                    "resistance_only": True,
                }
            }
        }
        verdicts = itemplan_data.upgrade_verdicts(worn, [noxx], drive={})
        self.assertEqual("wear", verdicts.get(("Grog", 17746)))

    def test_gearup_skips_resistance_only_wrist_for_empty_slot(self):
        characters = {
            "Grog": {
                "class": PALADIN,
                "level": 59,
                "purse": 100000,
                "equipped": {},
                "role": "melee",
            }
        }
        listings = [
            {
                "listing_id": 1,
                "entry": 11767,
                "buyout": 1000,
                "InventoryType": WRIST,
                "class": 4,
                "subclass": PLATE,
                "RequiredLevel": 52,
                "AllowableClass": ALL_CLASSES,
                "ItemLevel": 57,
                "Quality": 3,
                "has_item_effect": 1,
                "resistance_only": 1,
            }
        ]
        self.assertEqual((), gearup.plan_buys(characters, listings))


if __name__ == "__main__":
    unittest.main()

"""A gear-short guild member walks to a vendor and buys whites for empty slots.

wow-dev 2026-10-03: 113 of 142 guild members wore gear more than six item
levels under their level, in five to eight of seventeen slots, so the gear
gate kept every guild group out of the dungeons. Nothing walked a guild
member to a vendor.
"""

import unittest

import guildjobs


def _member(**kw):
    base = dict(
        name="Aurevil",
        guild="Cave",
        role=guildjobs.RAIDER,
        level=20,
        class_id=1,
        online=True,
        map_id=0,
        x=0.0,
        y=0.0,
        money=50000,
        eligible=True,
    )
    base.update(kw)
    return guildjobs.Member(**base)


def _character(equipped=None, purse=50000):
    return {
        "class": "warrior",
        "level": 20,
        "purse": purse,
        "equipped": equipped
        if equipped is not None
        else {
            "mainhand": {"item_level": 18, "item_class": 2, "item_subclass": 7},
        },
        "skills": {"weapons": {7}},
    }


def _row(entry, inv, sub=1, ilvl=20, price=500, vendor=1001, yards=40.0):
    return {
        "vendor": vendor,
        "vendor_name": "Armorer",
        "map_id": 0,
        "yards": yards,
        "entry": entry,
        "buyout": price,
        "InventoryType": inv,
        "class": 4,
        "subclass": sub,
        "RequiredLevel": 15,
        "AllowableClass": -1,
        "ItemLevel": ilvl,
        "Quality": 1,
    }


ROWS = [_row(101, 5), _row(102, 7), _row(103, 10), _row(104, 8), _row(105, 6)]


class AGearShortMemberShops(unittest.TestCase):
    def test_walk_then_buys_at_one_vendor(self):
        step, why = guildjobs.gear_step(_member(), _character(), ROWS, 600.0)
        self.assertEqual("", why)
        self.assertEqual("gear", step.action)
        self.assertTrue(step.walk.command.startswith("walk-to-vendor item:"))
        self.assertEqual(guildjobs.GEAR_BUYS_PER_STEP, len(step.rows))
        self.assertTrue(all(r.kind == "buy" for r in step.rows))
        self.assertTrue(all(r.source == "guildjobs:gear:Aurevil" for r in step.rows))
        self.assertEqual("guildjobs:gear:Aurevil", step.walk.source)

    def test_a_geared_member_does_not(self):
        full = {
            s: {"item_level": 20, "item_class": 4, "item_subclass": 1}
            for s in (
                "head",
                "chest",
                "legs",
                "feet",
                "hands",
                "wrist",
                "waist",
                "shoulder",
                "back",
                "neck",
                "finger1",
                "finger2",
                "trinket1",
                "trinket2",
                "ranged",
            )
        }
        full["mainhand"] = {"item_level": 20, "item_class": 2, "item_subclass": 7}
        step, _why = guildjobs.gear_step(_member(), _character(full), ROWS, 600.0)
        self.assertIsNone(step)

    def test_no_vendor_in_reach_says_why(self):
        step, why = guildjobs.gear_step(_member(), _character(), [], 600.0)
        self.assertIsNone(step)
        self.assertIn("short of gear", why)

    def test_a_broke_member_buys_nothing(self):
        step, _why = guildjobs.gear_step(_member(), _character(purse=0), ROWS, 600.0)
        self.assertIsNone(step)


class ThePlanPutsGearFirst(unittest.TestCase):
    def test_gear_step_is_started(self):
        plan = guildjobs.plan([_member()], gear={"Aurevil": (_character(), ROWS)})
        self.assertEqual(["gear"], [s.action for s in plan.steps])

    def test_cooling_member_does_its_ordinary_job(self):
        recent = [guildjobs.Recent("Aurevil", "gear", 5)]
        plan = guildjobs.plan(
            [_member()], gear={"Aurevil": (_character(), ROWS)}, recent=recent
        )
        self.assertNotIn("gear", [s.action for s in plan.steps])

    def test_an_unnatural_member_never_shops(self):
        plan = guildjobs.plan(
            [_member(eligible=False)], gear={"Aurevil": (_character(), ROWS)}
        )
        self.assertEqual((), plan.steps)

    def test_no_gear_argument_changes_nothing(self):
        self.assertEqual(
            guildjobs.plan([_member()]), guildjobs.plan([_member()], gear=None)
        )


if __name__ == "__main__":
    unittest.main()

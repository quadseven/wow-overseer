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


class OnlyAFriendlyVendor(unittest.TestCase):
    """wow-dev 2026-10-03: an Alliance member was walked to Varia Hardhide,
    whose faction attacks the Alliance, and the module refused the row."""

    def test_a_hostile_vendor_is_never_picked(self):
        alliance = _member(race=1)
        hostile = [dict(r, enemy_group=2) for r in ROWS]
        step, why = guildjobs.gear_step(alliance, _character(), hostile, 600.0)
        self.assertIsNone(step)
        self.assertIn("no vendor", why)

    def test_a_friendly_vendor_is(self):
        alliance = _member(race=1)
        friendly = [dict(r, enemy_group=4) for r in ROWS]
        step, _why = guildjobs.gear_step(alliance, _character(), friendly, 600.0)
        self.assertEqual("gear", step.action)

    def test_an_unread_faction_is_left_to_the_module(self):
        rows = [dict(r, enemy_group=None) for r in ROWS]
        self.assertEqual(rows, guildjobs.friendly_vendor_rows(_member(race=2), rows))

    def test_the_vendor_query_reads_the_faction(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        self.assertIn("ft.EnemyGroup AS enemy_group", source)


def _junk_set(ilvl=4):
    """Every stat slot filled, all of it far below a level 20 wearer."""
    slots = (
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
    worn = {s: {"item_level": ilvl, "item_class": 4, "item_subclass": 1} for s in slots}
    worn["mainhand"] = {"item_level": ilvl, "item_class": 2, "item_subclass": 7}
    return worn


class StaleGearIsReplaced(unittest.TestCase):
    """wow-dev 2026-10-03: guild members died at levels 10 to 21 in pieces
    averaging item level 3 to 5. Their slots were full, so nothing counted
    them short of gear and no vendor walk was ever planned."""

    def test_a_full_set_of_junk_is_stale(self):
        import gearup

        self.assertTrue(gearup.stale_gear(_character(_junk_set())))
        self.assertFalse(gearup.gear_short(_character(_junk_set())))

    def test_gear_near_the_wearer_is_not(self):
        import gearup

        self.assertFalse(gearup.stale_gear(_character(_junk_set(ilvl=18))))

    def test_the_guild_step_replaces_junk(self):
        step, why = guildjobs.gear_step(_member(), _character(_junk_set()), ROWS, 600.0)
        self.assertEqual("", why)
        self.assertEqual("gear", step.action)
        self.assertTrue(step.rows)

    def test_the_family_planner_still_never_replaces(self):
        import gearup

        got = gearup.plan_vendor_buys({"Og": _character(_junk_set())}, {"Og": ROWS})
        self.assertEqual((), got)


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

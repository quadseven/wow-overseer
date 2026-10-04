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
        self.assertEqual(min(guildjobs.GEAR_BUYS_PER_STEP, len(ROWS)), len(step.rows))
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


class EveryNeedyMemberGetsARead(unittest.TestCase):
    """wow-dev 2026-10-03: the same three members held every vendor read
    while over a hundred stale members were never looked at."""

    def test_the_window_rolls_over_everyone(self):
        names = ["m%02d" % i for i in range(30)]
        seen, offset = set(), 0
        for _ in range(3):
            chosen, offset = guildjobs.rotate_reads(names, offset, 10)
            self.assertEqual(10, len(chosen))
            seen.update(chosen)
        self.assertEqual(set(names), seen)

    def test_a_short_list_is_read_whole(self):
        self.assertEqual((["a", "b"], 0), guildjobs.rotate_reads(["a", "b"], 7, 12))

    def test_nobody_reads_nothing(self):
        self.assertEqual(([], 0), guildjobs.rotate_reads([], 3, 12))

    def test_the_bridge_rolls_and_widens(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        self.assertIn("guildjobs.tiered_reads(", source)
        self.assertIn("guildjobs.GUILD_GEAR_VENDOR_YARDS", source)

    def test_a_vendor_past_the_family_cap_is_chosen_for_the_guild(self):
        far = [dict(r, yards=1200.0) for r in ROWS]
        step, _why = guildjobs.gear_step(_member(), _character(), far, 600.0)
        self.assertEqual("gear", step.action)


class AStrandedMemberHearthsHome(unittest.TestCase):
    """wow-dev 2026-10-03: every guild vendor walk was refused at its first
    leg, from a mountain top above Northshire, the Darnassus terraces and a
    Durotar ledge. The member hearths to its inn and walks from there."""

    def test_a_failed_gear_walk_sends_it_home(self):
        recent = [guildjobs.Recent("Aurevil", "gear", 5, status="error")]
        plan = guildjobs.plan([_member()], recent=recent)
        self.assertEqual(["hearth"], [s.action for s in plan.steps])
        row = plan.steps[0].rows[0]
        self.assertEqual(("hearth", "use"), (row.kind, row.command))
        self.assertEqual("guildjobs:hearth:Aurevil", row.source)

    def test_not_twice_in_an_hour(self):
        recent = [
            guildjobs.Recent("Aurevil", "gear", 5, status="error"),
            guildjobs.Recent("Aurevil", "hearth", 4, status="delivered"),
        ]
        plan = guildjobs.plan([_member()], recent=recent)
        self.assertNotIn("hearth", [s.action for s in plan.steps])

    def test_a_gear_walk_that_worked_does_not(self):
        recent = [guildjobs.Recent("Aurevil", "gear", 5, status="delivered")]
        plan = guildjobs.plan([_member()], recent=recent)
        self.assertNotIn("hearth", [s.action for s in plan.steps])

    def test_the_newest_gear_row_decides(self):
        recent = [
            guildjobs.Recent("Aurevil", "gear", 50, status="error"),
            guildjobs.Recent("Aurevil", "gear", 2, status="delivered"),
        ]
        self.assertFalse(guildjobs.last_gear_failed("Aurevil", recent))

    def test_an_unnatural_member_never_hearths(self):
        recent = [guildjobs.Recent("Aurevil", "gear", 5, status="error")]
        plan = guildjobs.plan([_member(eligible=False)], recent=recent)
        self.assertEqual((), plan.steps)


class GearHasItsOwnAllowance(unittest.TestCase):
    """wow-dev 2026-10-04: gear steps queued behind posts, sales and training
    in 4 steps per guild per pass, and 119 members stayed under the gate."""

    def test_gear_steps_do_not_spend_the_job_allowance(self):
        members = [_member(name="m%02d" % i) for i in range(10)]
        gear = {m.name: (_character(), ROWS) for m in members}
        plan = guildjobs.plan(members, gear=gear)
        gearing = [s for s in plan.steps if s.action == "gear"]
        self.assertEqual(guildjobs.GEAR_STEPS_PER_GUILD, len(gearing))
        self.assertGreater(len(gearing), guildjobs.STEPS_PER_GUILD)

    def test_a_successful_step_follows_sooner(self):
        ok = [guildjobs.Recent("Aurevil", "gear", 20, status="delivered")]
        failed = [guildjobs.Recent("Aurevil", "gear", 20, status="error")]
        self.assertFalse(guildjobs._cooling(_member(), "gear", ok))
        self.assertTrue(guildjobs._cooling(_member(), "gear", failed))


class RoomBeforeTheBuy(unittest.TestCase):
    """wow-dev 2026-10-04: three of four members who reached their vendor
    were refused every piece, "bags cannot take the item"."""

    def test_junk_is_sold_before_the_buys(self):
        junk = guildjobs.Carried(guid=11, entry=900, count=1, quality=0, sell_price=50)
        good = guildjobs.Carried(guid=12, entry=901, count=1, quality=2, sell_price=500)
        step, _why = guildjobs.gear_step(
            _member(carried=(junk, good)), _character(), ROWS, 600.0
        )
        kinds = [r.kind for r in step.rows]
        self.assertEqual("sell", kinds[0])
        self.assertEqual("guid:11", step.rows[0].command)
        self.assertNotIn("guid:12", [r.command for r in step.rows])
        self.assertEqual(kinds.index("buy"), kinds.count("sell"))

    def test_no_junk_means_only_buys(self):
        step, _why = guildjobs.gear_step(_member(), _character(), ROWS, 600.0)
        self.assertEqual({"buy"}, {r.kind for r in step.rows})


class MembersWhoFitADoorAreReadFirst(unittest.TestCase):
    """wow-dev 2026-10-04: 12 members at levels 10 to 14 passed the gate and
    fit no door, while 67 at 15 to 19 waited behind them."""

    def test_doorable_members_fill_the_reads_first(self):
        chosen, _ = guildjobs.tiered_reads(["a", "b"], ["x", "y", "z"], (0, 0), 4)
        self.assertEqual(["a", "b", "x", "y"], chosen)

    def test_doorable_members_rotate_among_themselves(self):
        doorable = ["d%02d" % i for i in range(9)]
        seen, offsets = set(), (0, 0)
        for _ in range(3):
            chosen, offsets = guildjobs.tiered_reads(doorable, ["low"], offsets, 3)
            self.assertNotIn("low", chosen)
            seen.update(chosen)
        self.assertEqual(set(doorable), seen)

    def test_the_bridge_tiers_by_the_door_floor(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        self.assertIn("guildjobs.tiered_reads(", source)
        self.assertIn(">= guildjobs.GUILD_DOOR_FLOOR", source)


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

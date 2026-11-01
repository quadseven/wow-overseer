"""Paid capacity recovery reaches maintenance members through the real job plan."""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

import bag_pressure as bp
import bag_upgrade as bu
import guildbags
import guildjobs
import guildroute
from test_guildjobs import member


def worker(**changes):
    return member(
        "Tailor", level=43, money=20000, free_slots=0, bag_slots=22, **changes
    )


def containers(carried=(), worn=None):
    return bu.Member(
        "Tailor",
        4,
        worn=(bu.Bag("Pouch", 6, used=6, entry=4496),) if worn is None else worn,
        carried=carried,
    )


def vendors():
    return {
        "Tailor": (
            bp.BagVendor(
                900001,
                "Vendor",
                0,
                40,
                offers=(bp.BagOffer(4496, "Pouch", 6, 500),),
            ),
        )
    }


class MaintenanceCapacity(unittest.TestCase):
    def test_a_distant_vendor_uses_the_guild_budget_and_needs_a_far_slot(self):
        distant = {"Tailor": (replace(vendors()["Tailor"][0], yards=1175),)}
        m = worker()
        self.assertEqual(guildbags.plan([m], [containers()], distant)[0], {})
        bags, _ = guildbags.plan(
            [m], [containers()], distant, guildroute.FAR_WALK_YARDS
        )
        self.assertTrue(bags["Tailor"].far)
        self.assertEqual(
            bags["Tailor"].step.walk.command, "walk-to-vendor item:4496 max:20000"
        )
        held = guildjobs.plan(
            [m], bags=bags, far_slots=0, cap=guildroute.FAR_WALK_YARDS
        )
        self.assertNotIn(guildjobs.BAG_ACTION, [s.action for s in held.steps])
        ready = guildjobs.plan(
            [m], bags=bags, far_slots=1, cap=guildroute.FAR_WALK_YARDS
        )
        self.assertEqual([s.action for s in ready.steps], [guildjobs.BAG_ACTION])

    def test_full_backpack_selects_a_paid_bag_in_the_real_guild_plan(self):
        m = worker()
        steps, notes = guildbags.plan([m], [containers()], vendors())
        plan = guildjobs.plan([m], bags=steps)
        self.assertEqual(notes, ())
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.action, guildjobs.BAG_ACTION)
        self.assertEqual(step.walk.command, "walk-to-vendor item:4496")
        self.assertEqual(
            [(r.kind, r.command) for r in step.rows],
            [
                ("buy", "entry:4496 count:1 max:500"),
                ("bot", "e Hitem:4496:0"),
            ],
        )

    def test_an_owned_spare_is_equipped_without_a_vendor_or_spending(self):
        spare = bu.Bag("Satchel", 8, entry=4498, guid=10)
        steps, _ = guildbags.plan([worker()], [containers((spare,))], {})
        step = steps["Tailor"].step
        self.assertIsNone(step.walk)
        self.assertEqual(
            [(r.kind, r.command) for r in step.rows], [("bot", "e Hitem:4498:0")]
        )

    def test_no_purchase_with_full_positions_or_a_purse_below_the_reserve(self):
        full = containers(worn=(bu.Bag("Pouch", 6, used=6),) * 4)
        self.assertEqual(guildbags.plan([worker()], [full], vendors())[0], {})
        poor = replace(worker(), money=bp.bag_reserve(43) + 499)
        self.assertEqual(guildbags.plan([poor], [containers()], vendors())[0], {})

    def test_ineligible_members_and_recent_bag_work_are_left_alone(self):
        for changes in (
            {"eligible": False},
            {"online": False},
            {"alive": False},
            {"in_combat": True},
            {"map_id": None},
            {"map_id": 530},
            {"free_slots": None},
            {"role": guildjobs.RAIDER},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(guildbags.eligible(replace(worker(), **changes)))
        recent = [guildjobs.Recent("Tailor", guildjobs.BAG_ACTION, 1)]
        self.assertFalse(guildbags.eligible(worker(), recent))
        steps, _ = guildbags.plan([worker()], [containers()], vendors())
        self.assertNotIn(
            guildjobs.BAG_ACTION,
            [
                s.action
                for s in guildjobs.plan([worker()], bags=steps, recent=recent).steps
            ],
        )
        self.assertEqual(
            guildjobs.plan([worker()], bags=steps, busy={"Tailor"}).steps, ()
        )

    def test_a_class_quest_still_precedes_the_bag_step(self):
        m = worker()
        bags, _ = guildbags.plan([m], [containers()], vendors())
        quest = replace(bags["Tailor"].step, action="classquest", said="Class quest")
        with mock.patch.object(
            guildjobs, "_quest_first", return_value=((quest, quest.said, "", ""), "")
        ):
            result = guildjobs.plan([m], bags=bags)
        self.assertEqual([s.action for s in result.steps], ["classquest"])


class LiveCaller(unittest.IsolatedAsyncioTestCase):
    async def test_the_running_guild_job_pass_actually_receives_the_bag_step(self):
        from test_guildsocial_bridge import bridge

        m = worker()
        rows = [
            dict(
                holder="Tailor",
                guid=10,
                name="Pouch",
                slots=6,
                used=6,
                bag=0,
                slot=19,
                entry=4496,
                subclass=0,
            )
        ]
        offers = [
            dict(
                entry=900001,
                name="Vendor",
                map_id=0,
                yards=40,
                item=4496,
                item_name="Pouch",
                slots=6,
                price=500,
            )
        ]
        this = SimpleNamespace(
            _class_hunts=None,
            _class_owing=None,
            _equip_room={},
            _guild_still={},
            _class_owed_by={},
            _log_purses=mock.Mock(),
            _class_book_for_plan=lambda facts: None,
        )
        for name in (
            "_job_fields",
            "_job_gear_offers",
            "_job_supply_offers",
            "_job_pet_offers",
            "_job_weapon_offers",
            "_job_pvp_moves",
        ):
            setattr(this, name, mock.AsyncMock(return_value={}))
        this._job_bag_steps = lambda *args: bridge.Bridge._job_bag_steps(this, *args)
        facts = dict(
            masters={"Cave": "Master"}, crafters={}, stones=(), recent=(), pending=()
        )
        with mock.patch.multiple(
            bridge,
            _kept_with_bank_policy=lambda *args: {},
            _with_purses_and_reserves=lambda members, *args: members,
            _guild_campaign_door=lambda *args: "",
            _fetch_mount_facts=lambda *args: {},
            _job_mail_commands=lambda *args: {},
            _job_leveling=lambda *args: None,
            _keep_class_plan=lambda *args: None,
            _fetch_bag_state=lambda *args: rows,
            _fetch_bag_vendors=lambda *args: offers,
        ):
            result = await bridge.Bridge._plan_guild_jobs(
                this, [m], facts, set(), guildroute.MAIL_RUN_YARDS, True
            )
        self.assertEqual([s.action for s in result.steps], [guildjobs.BAG_ACTION])
        self.assertEqual(result.steps[0].rows[0].command, "entry:4496 count:1 max:500")

    async def test_the_bridge_reads_maintenance_bags_and_connects_the_plan(self):
        from test_guildsocial_bridge import bridge

        rows = [
            dict(
                holder="Tailor",
                guid=10,
                name="Pouch",
                slots=6,
                used=6,
                bag=0,
                slot=19,
                entry=4496,
                subclass=0,
            )
        ]
        offers = [
            dict(
                entry=900001,
                name="Vendor",
                map_id=0,
                yards=40,
                item=4496,
                item_name="Pouch",
                slots=6,
                price=500,
            )
        ]
        with (
            mock.patch.object(bridge, "_fetch_bag_state", return_value=rows) as read,
            mock.patch.object(bridge, "_fetch_bag_vendors", return_value=offers),
        ):
            steps = await bridge.Bridge._job_bag_steps(
                SimpleNamespace(), [worker()], (), set(), guildroute.MAIL_RUN_YARDS
            )
        read.assert_called_once_with(["Tailor"])
        plan = guildjobs.plan([worker()], bags=steps)
        self.assertEqual(plan.steps[0].rows[0].command, "entry:4496 count:1 max:500")

    async def test_busy_members_never_open_a_vendor_read(self):
        from test_guildsocial_bridge import bridge

        with mock.patch.object(bridge, "_fetch_bag_state") as read:
            steps = await bridge.Bridge._job_bag_steps(
                SimpleNamespace(), [worker()], (), {"Tailor"}, guildroute.MAIL_RUN_YARDS
            )
        self.assertEqual(steps, {})
        read.assert_not_called()

"""A roster family member with Riding and no mount buys one between runs (#2642).

`mountbuy.py` and `guildjobs.mount_step` serve guild members off the roster
whose purses carry purchase orders. A roster family member has no purchase
order and plans only in the gap between dungeon runs (familyclass.py). After
Riding is held (family_riding_step, #2625), `family_mount_step` plans the
member's mount step in that same gap, keeping `FAMILY_RIDING_FLOAT` over the
price, with the same idle, ground, follower and cooldown holds.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import bridge
import classquest
import familyclass
import guildjobs
import mountbuy
from test_family_riding import GOLD, RIDING, ago, seat
from test_familyclass import book, member as class_member
from test_mountbuy import PINTO, STOCK

FACTS = mountbuy.Facts(False, STOCK)


def mount_seat(**over):
    base = dict(
        race=1,
        map_id=0,
        skills={RIDING: (75, 75)},
        money=20 * GOLD,
    )
    base.update(over)
    return seat(**base)


class WhoGetsAMountWalk(unittest.TestCase):
    def step(self, member, facts=FACTS, recent=()):
        return guildjobs.family_mount_step(member, facts, list(recent))

    def test_a_family_member_with_riding_and_no_mount_walks_for_one(self):
        step, note = self.step(mount_seat())
        self.assertEqual("", note)
        self.assertIsNotNone(step)
        self.assertEqual(mountbuy.ACTION, step.action)
        self.assertEqual("buy", step.walk.kind)
        self.assertEqual("walk-to-vendor item:2414 max:5000", step.walk.command)
        self.assertEqual(
            [("buy", "entry:2414 count:1 max:10000"), ("cast", "use entry:2414")],
            [(r.kind, r.command) for r in step.rows],
        )

    def test_the_mount_leaves_the_family_float(self):
        broke = mount_seat(money=PINTO.price)
        step, note = self.step(broke)
        self.assertIsNone(step)
        self.assertIn("saves for a mount", note)

    def test_enough_for_mount_and_float_walks(self):
        exact = mount_seat(money=PINTO.price + guildjobs.FAMILY_RIDING_FLOAT)
        step, _ = self.step(exact)
        self.assertIsNotNone(step)
        self.assertEqual(mountbuy.ACTION, step.action)

    def test_a_carried_mount_is_used_without_gold_or_walking(self):
        held = guildjobs.Carried(9001, 2414, 1, 15, 5, name="Reins of the Pinto")
        step, note = self.step(mount_seat(money=0, carried=(held,)))
        self.assertEqual("", note)
        self.assertIsNotNone(step)
        self.assertIsNone(step.walk)
        self.assertEqual(["use entry:2414"], [r.command for r in step.rows])

    def test_full_bags_make_room_within_the_family_walk_cap(self):
        junk = guildjobs.Carried(guid=11, entry=900, count=1, quality=0, sell_price=50)
        m = mount_seat(free_slots=0, bag_slots=16, carried=(junk,))
        step, note = self.step(m)
        self.assertEqual("", note)
        self.assertEqual(guildjobs.ROOM_ACTION, step.action)
        self.assertEqual(["guid:11"], [r.command for r in step.rows])


class WhenFamilyMountIsHeld(unittest.TestCase):
    def step(self, member, facts=FACTS, recent=()):
        return guildjobs.family_mount_step(member, facts, list(recent))[0]

    def test_non_family_or_ineligible_takes_no_family_mount_step(self):
        self.assertIsNone(self.step(mount_seat(role=guildjobs.RAIDER)))
        self.assertIsNone(self.step(mount_seat(eligible=False)))

    def test_not_while_offline_dead_or_fighting(self):
        for over in (dict(online=False), dict(alive=False), dict(in_combat=True)):
            self.assertIsNone(self.step(mount_seat(**over)), over)

    def test_not_walking_while_following_its_leader(self):
        self.assertIsNone(self.step(mount_seat(follows=True)))

    def test_a_follower_carrying_a_mount_still_uses_it_where_it_stands(self):
        held = guildjobs.Carried(9001, 2414, 1, 15, 5, name="Reins of the Pinto")
        step = self.step(mount_seat(follows=True, carried=(held,)))
        self.assertIsNotNone(step)
        self.assertIsNone(step.walk)

    def test_unread_ground_never_starts_an_unbounded_walk(self):
        self.assertIsNone(self.step(mount_seat(x=None)))
        self.assertIsNone(self.step(mount_seat(y=None)))
        self.assertIsNone(self.step(mount_seat(map_id=None)))

    def test_not_twice_inside_the_mount_cooldown(self):
        self.assertIsNone(self.step(mount_seat(), recent=[ago(30, mountbuy.ACTION)]))
        self.assertIsNotNone(
            self.step(mount_seat(), recent=[ago(600, mountbuy.ACTION)])
        )


class InTheFamilyPlan(unittest.TestCase):
    def plan(self, family, mounts=None, busy=(), recent=(), classes=None):
        return guildjobs.plan(
            [],
            classes=book() if classes is None else classes,
            family_members=family,
            mounts=mounts,
            busy=busy,
            recent=recent,
            now=1000.0,
            far_slots=None,
        )

    def test_an_idle_family_member_with_riding_and_no_mount_gets_mount_walk(self):
        plan = self.plan([mount_seat()], mounts={"Grugg": FACTS})
        self.assertEqual([s.action for s in plan.steps], [mountbuy.ACTION])
        self.assertEqual([s.holder for s in plan.steps], ["Grugg"])

    def test_saving_for_journeyman_still_buys_the_mount_now(self):
        m = mount_seat(level=60, skills={RIDING: (75, 75)}, money=20 * GOLD)
        plan = self.plan([m], mounts={"Grugg": FACTS})
        self.assertEqual([s.action for s in plan.steps], [mountbuy.ACTION])

    def test_riding_still_comes_before_mount_when_riding_step_is_planned(self):
        m = mount_seat(level=60, skills={RIDING: (75, 75)}, money=300 * GOLD)
        plan = self.plan([m], mounts={"Grugg": FACTS})
        self.assertEqual([s.action for s in plan.steps], [guildjobs.RIDING_ACTION])

    def test_class_quest_comes_before_mount(self):
        m = class_member(
            name="Grugg",
            race=3,
            skills={RIDING: (75, 75)},
            money=20 * GOLD,
        )
        plan = self.plan([m], mounts={"Grugg": FACTS})
        self.assertEqual([s.action for s in plan.steps], [classquest.ACTION])

    def test_busy_drive_holds_the_mount_walk(self):
        plan = self.plan([mount_seat()], mounts={"Grugg": FACTS}, busy={"Grugg"})
        self.assertEqual(plan.steps, ())

    def test_family_switch_off_holds_the_mount_walk(self):
        with mock.patch.dict(os.environ, {familyclass.ENV_SWITCH: "off"}):
            plan = self.plan([mount_seat()], mounts={"Grugg": FACTS})
        self.assertEqual(plan.steps, ())


def _bridge_stub(facts):
    from types import SimpleNamespace

    this = SimpleNamespace(
        _class_hunts=None,
        _class_owing=None,
        _equip_room={},
        _guild_still={},
        _class_owed_by={},
        _log_purses=mock.Mock(),
        _class_book_for_plan=lambda f: f.get("class_book"),
    )
    for name in (
        "_job_fields",
        "_job_gear_offers",
        "_job_supply_offers",
        "_job_bag_steps",
        "_job_pet_offers",
        "_job_weapon_offers",
        "_job_pvp_moves",
    ):
        setattr(this, name, mock.AsyncMock(return_value={}))
    return this


class BridgeFamilyMountWiring(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_reads_mounts_for_idle_family_members(self):
        guild_member = seat(
            name="Mace", role=guildjobs.RAIDER, skills={}, level=60, money=0
        )
        fam = mount_seat()
        seen_members = []

        def fake_mounts(members):
            seen_members.extend(m.name for m in members)
            return {fam.name: FACTS}

        facts = dict(
            masters={"Cave": "Mace"},
            crafters={},
            stones=(),
            recent=(),
            pending=(),
            class_book=book(),
            family_members=[fam],
        )
        this = _bridge_stub(facts)
        with mock.patch.multiple(
            bridge,
            _kept_with_bank_policy=lambda *args: {},
            _with_purses_and_reserves=lambda members, *args: members,
            _guild_campaign_door=lambda *args: "",
            _family_class_state=lambda _facts: ([fam], {}),
            _family_danger=lambda *args: {},
            _fetch_mount_facts=fake_mounts,
            _job_mail_commands=lambda *args: {},
            _job_leveling=lambda *args: None,
            _keep_class_plan=lambda *args: None,
        ):
            plan = await bridge.Bridge._plan_guild_jobs(
                this, [guild_member], facts, set(), 100.0, False
            )
        self.assertIn("Grugg", seen_members)
        self.assertEqual([s.action for s in plan.steps], [mountbuy.ACTION])
        self.assertEqual([s.holder for s in plan.steps], ["Grugg"])

    async def test_dungeon_or_errand_hold_keeps_family_mount_out(self):
        guild_member = seat(
            name="Mace", role=guildjobs.RAIDER, skills={}, level=60, money=0
        )
        fam = mount_seat()
        facts = dict(
            masters={"Cave": "Mace"},
            crafters={},
            stones=(),
            recent=(),
            pending=(),
            class_book=book(),
            family_members=[fam],
        )
        this = _bridge_stub(facts)
        with mock.patch.multiple(
            bridge,
            _kept_with_bank_policy=lambda *args: {},
            _with_purses_and_reserves=lambda members, *args: members,
            _guild_campaign_door=lambda *args: "",
            _family_class_state=lambda _facts: (
                [],
                {fam.name: "its family has an active dungeon run"},
            ),
            _family_danger=lambda *args: {},
            _fetch_mount_facts=lambda *args: {},
            _job_mail_commands=lambda *args: {},
            _job_leveling=lambda *args: None,
            _keep_class_plan=lambda *args: None,
        ):
            plan = await bridge.Bridge._plan_guild_jobs(
                this, [guild_member], facts, set(), 100.0, False
            )
        self.assertEqual(plan.steps, ())


if __name__ == "__main__":
    unittest.main()

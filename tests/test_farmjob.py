"""The farm job (#2417): a family gathers a named material on purpose.

farmjob.decide is pure, so most of this drives it with hand-built reads. The
last classes read bridge.py and the Dockerfile as text to pin the wiring.
"""

import pathlib
import unittest

import farmjob
import jobs
from gatheraim import Spawn

ROOT = pathlib.Path(__file__).resolve().parent.parent

DREAMFOIL_LOCK = 1120  # herbalism 270
SUNGRASS_LOCK = 441  # herbalism 230
PEACEBLOOM_LOCK = 29  # herbalism 0
CHEST_LOCK = 57  # a chest, no gathering skill

FAMILY = ("Grug", "Ugga", "Grog", "Bork", "Og")
LEVELS = {name: 60 for name in FAMILY}


def herbalist(value):
    skills = {name: {} for name in FAMILY}
    skills["Ugga"] = {"herbalism": value}
    return skills


def spawn(x, y, zone=490, lock=SUNGRASS_LOCK, map_id=1):
    return Spawn(
        map_id=map_id, zone_id=zone, x=float(x), y=float(y), z=0.0, lock_id=lock
    )


def leader_at(x=0.0, y=0.0, zone=1, map_id=1):
    return {"map_id": map_id, "zone_id": zone, "pos_x": x, "pos_y": y}


def order(item=8838, name="Sungrass", started=0.0, **kw):
    return farmjob.Order(
        job="farm:%d" % item, item=item, name=name, started=started, **kw
    )


def reads(**kw):
    base = dict(
        skills=herbalist(240),
        levels=LEVELS,
        leader_at=leader_at(),
        spawns=(spawn(1000, 0), spawn(1100, 0), spawn(1200, 50)),
        zone_levels={490: 55},
        free_slots={name: 20 for name in FAMILY},
        now=60.0,
    )
    base.update(kw)
    return farmjob.Reads(**base)


class TheOrderNamesItsMaterial(unittest.TestCase):
    def test_an_item_entry_and_a_skill_are_orders(self):
        self.assertEqual(farmjob.job_for(13463), "farm:13463")
        self.assertEqual(farmjob.job_for("Mining"), "farm:mining")
        self.assertEqual(farmjob.order_of("farm:13463"), (13463, ""))
        self.assertEqual(farmjob.order_of("farm:herbalism"), (0, "herbalism"))

    def test_anything_else_names_nothing(self):
        for job in (
            "farm",
            "farm:",
            "farm:0",
            "farm:013",
            "farm:skinning",
            "farm:dreamfoil",
            "quest",
            "",
            None,
            "farm:1234567890",
        ):
            self.assertEqual(farmjob.order_of(job), (0, ""), job)
            self.assertFalse(farmjob.is_farm_job(job), job)
        self.assertIsNone(farmjob.job_for("skinning"))

    def test_it_fits_the_job_column(self):
        self.assertLessEqual(len(farmjob.job_for(123456789)), jobs.COLUMN_WIDTH)


class TheBandIsTheRefusal(unittest.TestCase):
    """The ticket's own case: Dreamfoil needs 270, Sungrass 230."""

    def test_a_200_herbalist_is_refused_dreamfoil_with_the_band_named(self):
        step = farmjob.decide(
            order(13463, "Dreamfoil"),
            reads(skills=herbalist(200), spawns=(spawn(1000, 0, lock=DREAMFOIL_LOCK),)),
        )
        self.assertEqual(step.action, farmjob.END)
        self.assertIn("Dreamfoil needs herbalism 270", step.line)
        self.assertIn("best is 200", step.line)

    def test_a_herbalist_at_sungrass_band_gets_a_zone(self):
        step = farmjob.decide(order(), reads(skills=herbalist(230)))
        self.assertEqual(step.action, farmjob.WALK)
        self.assertEqual(step.zone_id, 490)
        self.assertEqual((step.spawn.x, step.spawn.y), (1000.0, 0.0))

    def test_a_chest_that_holds_the_herb_is_not_a_field(self):
        step = farmjob.decide(order(), reads(spawns=(spawn(1000, 0, lock=CHEST_LOCK),)))
        self.assertEqual(step.action, farmjob.END)
        self.assertIn("no herb or ore node", step.line)

    def test_nobody_with_the_trade_is_refused(self):
        step = farmjob.decide(order(), reads(skills={n: {} for n in FAMILY}))
        self.assertEqual(step.action, farmjob.END)
        self.assertIn("best is none", step.line)


class TheJobEndsByItself(unittest.TestCase):
    def test_the_target_ends_it(self):
        step = farmjob.decide(order(target=20), reads(gathered=20))
        self.assertEqual(step.action, farmjob.END)
        self.assertIn("target is met", step.line)

    def test_the_time_box_ends_it(self):
        step = farmjob.decide(order(time_box=600), reads(now=600.0))
        self.assertEqual(step.action, farmjob.END)
        self.assertIn("10-minute time box", step.line)

    def test_too_many_deaths_end_it(self):
        deaths = tuple((490, 1) for _ in range(farmjob.TOTAL_DEATHS))
        step = farmjob.decide(order(), reads(deaths=deaths))
        self.assertEqual(step.action, farmjob.END)
        self.assertIn("deaths", step.line)

    def test_a_skill_order_ends_on_its_time_box_not_a_count(self):
        skill = farmjob.Order(job="farm:herbalism", skill="herbalism", time_box=600)
        self.assertEqual(
            farmjob.decide(skill, reads(gathered=999)).action, farmjob.WALK
        )
        self.assertEqual(farmjob.decide(skill, reads(now=601.0)).action, farmjob.END)


class FullBagsGoToTown(unittest.TestCase):
    def test_a_member_at_three_free_slots_yields_the_column(self):
        free = {name: 20 for name in FAMILY}
        free["Ugga"] = 3
        step = farmjob.decide(order(), reads(free_slots=free))
        self.assertEqual(step.action, farmjob.TOWN)
        self.assertIn("Ugga", step.line)

    def test_unread_bags_go_to_town_too(self):
        self.assertEqual(
            farmjob.decide(order(), reads(free_slots={})).action, farmjob.TOWN
        )


class DeathsAndDangerChooseTheField(unittest.TestCase):
    def test_a_zone_with_two_deaths_is_struck_off_for_the_next(self):
        spawns = (spawn(1000, 0, zone=490), spawn(3000, 0, zone=361))
        deaths = ((490, 1), (490, 1))
        step = farmjob.decide(
            order(), reads(spawns=spawns, deaths=deaths, zone_levels={490: 55, 361: 55})
        )
        self.assertEqual(step.action, farmjob.WALK)
        self.assertEqual(step.zone_id, 361)

    def test_no_safe_field_ends_with_every_reason(self):
        spawns = (spawn(1000, 0, zone=490), spawn(3000, 0, zone=361))
        step = farmjob.decide(order(), reads(spawns=spawns, zone_levels={490: 70}))
        self.assertEqual(step.action, farmjob.END)
        self.assertIn("zone 490 tops out at 70", step.line)
        self.assertIn("zone 361 not measured", step.line)

    def test_the_weakest_member_sets_the_ceiling(self):
        levels = dict(LEVELS, Og=50)
        step = farmjob.decide(order(), reads(levels=levels, zone_levels={490: 55}))
        self.assertEqual(step.action, farmjob.END)

    def test_a_field_on_another_map_is_never_walked_to(self):
        step = farmjob.decide(order(), reads(spawns=(spawn(1000, 0, map_id=0),)))
        self.assertEqual(step.action, farmjob.END)
        self.assertIn("map 0", step.line)

    def test_one_spawns_own_ground_is_judged_again(self):
        self.assertEqual(farmjob.spawn_unsafe(60, LEVELS), "")
        self.assertIn("level 64", farmjob.spawn_unsafe(64, LEVELS))
        self.assertIn("measured", farmjob.spawn_unsafe(None, LEVELS))

    def test_the_nearest_safe_field_wins(self):
        spawns = (
            spawn(5000, 0, zone=361),
            spawn(5100, 0, zone=361),
            spawn(900, 0, zone=490),
        )
        step = farmjob.decide(
            order(), reads(spawns=spawns, zone_levels={490: 55, 361: 55})
        )
        self.assertEqual(step.zone_id, 490)


class AWalkToARefusedSpawnMovesOn(unittest.TestCase):
    """A spawn the column refused is marked visited; the next pass must not ask
    for the very same spawn again."""

    def test_a_spawn_just_tried_is_not_the_next_walk_target(self):
        near, next_ = spawn(900, 0), spawn(1000, 0)
        tried = {farmjob.spawn_key(near): 50.0}
        step = farmjob.decide(order(), reads(spawns=(near, next_), visited=tried))
        self.assertEqual(step.action, farmjob.WALK)
        self.assertEqual(step.spawn, next_)

    def test_a_spawn_tried_long_ago_is_walkable_again(self):
        near, next_ = spawn(900, 0), spawn(1000, 0)
        tried = {farmjob.spawn_key(near): 50.0}
        late = 50.0 + farmjob.REVISIT_SECONDS + 1
        step = farmjob.decide(
            order(), reads(spawns=(near, next_), visited=tried, now=late)
        )
        self.assertEqual(step.spawn, near)

    def test_when_every_spawn_was_tried_the_nearest_is_asked_again(self):
        near, next_ = spawn(900, 0), spawn(1000, 0)
        tried = {farmjob.spawn_key(near): 50.0, farmjob.spawn_key(next_): 55.0}
        step = farmjob.decide(order(), reads(spawns=(near, next_), visited=tried))
        self.assertEqual(step.spawn, near)


class InTheFieldItHops(unittest.TestCase):
    def standing(self, x=1000.0, y=0.0):
        return leader_at(x, y, zone=490)

    def test_it_hops_to_the_nearest_spawn_out_of_reach(self):
        spawns = (spawn(1010, 0), spawn(1100, 0), spawn(1500, 0))
        step = farmjob.decide(order(), reads(spawns=spawns, leader_at=self.standing()))
        self.assertEqual(step.action, farmjob.HOP)
        self.assertEqual(step.spawn.x, 1100.0)

    def test_a_spawn_hopped_to_lately_is_passed_over(self):
        spawns = (spawn(1100, 0), spawn(1500, 0))
        visited = {farmjob.spawn_key(spawns[0]): 0.0}
        step = farmjob.decide(
            order(),
            reads(spawns=spawns, leader_at=self.standing(), visited=visited, now=60.0),
        )
        self.assertEqual(step.spawn.x, 1500.0)

    def test_when_every_spawn_was_visited_the_oldest_comes_round(self):
        spawns = (spawn(1100, 0), spawn(1500, 0))
        visited = {
            farmjob.spawn_key(spawns[0]): 50.0,
            farmjob.spawn_key(spawns[1]): 10.0,
        }
        step = farmjob.decide(
            order(),
            reads(spawns=spawns, leader_at=self.standing(), visited=visited, now=60.0),
        )
        self.assertEqual(step.spawn.x, 1500.0)

    def test_a_walk_in_flight_is_not_rewritten(self):
        walking = spawn(1100, 0)
        step = farmjob.decide(order(), reads(walking=walking))
        self.assertEqual(step.action, farmjob.WAIT)

    def test_no_snapshot_waits_rather_than_ends(self):
        step = farmjob.decide(order(), reads(leader_at=None))
        self.assertEqual(step.action, farmjob.WAIT)


class SkillOrders(unittest.TestCase):
    def test_grey_nodes_give_no_skill_and_are_not_farmed(self):
        skill = farmjob.Order(job="farm:herbalism", skill="herbalism")
        step = farmjob.decide(
            skill,
            reads(skills=herbalist(240), spawns=(spawn(900, 0, lock=PEACEBLOOM_LOCK),)),
        )
        self.assertEqual(step.action, farmjob.END)
        locks = farmjob.skill_locks("herbalism", 240)
        self.assertIn(SUNGRASS_LOCK, locks)
        self.assertNotIn(PEACEBLOOM_LOCK, locks)


class TheJobIsWired(unittest.TestCase):
    def test_farm_is_implemented_and_its_orders_may_be_set(self):
        self.assertIn("farm", jobs.IMPLEMENTED)
        self.assertTrue(jobs.can_set("farm:13463"))
        self.assertTrue(jobs.can_set("farm:mining"))
        self.assertFalse(jobs.can_set("farm:skinning"))
        self.assertEqual(jobs.resolve("farm:13463"), "farm:13463")
        self.assertEqual(jobs.resolve("farm mining"), "farm:mining")
        self.assertEqual(jobs.parse_order("job farm:13463"), "farm:13463")
        self.assertTrue(jobs.is_farm_job("farm:13463"))
        self.assertIn("farm 13463", jobs.describe("farm:13463"))
        self.assertEqual(jobs.say("farm:13463"), jobs.SAYS["farm"])

    def test_jobs_and_farmjob_agree_on_the_order_shape(self):
        for job in (
            "farm:13463",
            "farm:mining",
            "farm:herbalism",
            "farm:0",
            "farm:x",
            "farm",
            "farm:skinning",
        ):
            self.assertEqual(
                jobs.farm_order(job) is not None, farmjob.is_farm_job(job), job
            )


class TheBridgeDrivesIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "bridge.py").read_text(encoding="utf-8")
        start = cls.source.index("    async def _farm_once(self, cohort=None)")
        cls.body = cls.source[start : cls.source.index("    async def _drive_skill(")]
        start = cls.source.index("def _farm_order(job: str")
        cls.body += cls.source[start : cls.source.index("def _farm_reads(names")]

    def test_the_loop_is_a_pass(self):
        self.assertEqual(self.source.count('_Pass("_farm_loop"),'), 1)
        self.assertIn(
            'await self._for_other_families("farm", self._farm_once)', self.source
        )

    def test_aims_come_from_a_surveyed_spawn_through_the_one_column(self):
        self.assertIn(
            "travel.ground_aim(spawn.map_id, spawn.x, spawn.y, spawn.z)", self.body
        )
        self.assertIn(
            "self._claim_town_slot(\n                GATHER_CLAIMANT, leader, aim",
            self.body,
        )

    def test_full_bags_and_the_end_hand_the_column_back(self):
        self.assertIn("await self._yield_gather_aim(step.line, cohort)", self.body)
        self.assertIn(
            'await self._yield_gather_aim("the farm job ended", cohort)', self.body
        )

    def test_each_decision_is_one_line_and_each_pick_is_logged(self):
        self.assertIn(
            'log.info("farm: %s %s: %s", who, step.action, step.line)', self.body
        )
        self.assertIn('"farm: %s picked %d %s (%d gathered, %d held)"', self.body)

    def test_the_end_writes_the_default_job(self):
        self.assertIn("core.JobDirective(mode=write, source=FARM_SOURCE)", self.body)
        self.assertIn("self._set_family_job(cohort, write, FARM_SOURCE)", self.body)
        self.assertIn("return jobs.DEFAULT", self.source)

    def test_deaths_are_read_from_the_death_table_since_the_order(self):
        self.assertIn("FROM overseer_death WHERE character_name IN", self.source)
        self.assertIn("created_at >= FROM_UNIXTIME(%s)", self.source)

    def test_a_bare_farm_order_is_refused(self):
        start = self.source.index("    async def _job_not_ready(self, mode: str)")
        body = self.source[start : start + 2500]
        self.assertIn('if mode == "farm":', body)
        self.assertIn("return jobs.FARM_NAMES_NOTHING", body)

    def test_jev_and_skill_goals_do_not_end_a_farm_early(self):
        start = self.source.index("    async def _activity_for(self, key: str")
        activity = self.source[start : start + 3000]
        self.assertIn("if jobs.is_farm_job(job):", activity)
        start = self.source.index("    async def _drive_skill(self, row: dict, action)")
        skill = self.source[start : start + 6000]
        self.assertIn("if jobs.is_farm_job(standing):", skill)

    def test_the_starting_count_outlives_a_restart(self):
        self.assertIn("_memo_read, FARM_MEMO_KIND", self.body)
        self.assertIn("_memo_upsert, FARM_MEMO_KIND, subject", self.body)


def where(map_id=0, x=0.0, y=0.0, instance=0):
    return {"map_id": map_id, "instance_id": instance, "pos_x": x, "pos_y": y}


class TheOrderIsTheMembersInReachOfTheLeader(unittest.TestCase):
    def test_the_leader_and_those_beside_it_are_in(self):
        pos = {"Grug": where(), "Grog": where(x=40.0, y=30.0)}
        self.assertEqual(farmjob.in_reach(pos, "Grug"), ["Grog", "Grug"])

    def test_a_member_far_away_or_on_another_map_is_out(self):
        pos = {
            "Grug": where(),
            "Bork": where(x=5000.0),
            "Og": where(map_id=1),
        }
        self.assertEqual(farmjob.in_reach(pos, "Grug"), ["Grug"])

    def test_a_member_inside_an_instance_is_never_in(self):
        pos = {"Grug": where(), "Ugga": where(map_id=0, instance=7)}
        self.assertEqual(farmjob.in_reach(pos, "Grug"), ["Grug"])
        pos = {"Grug": where(), "Ugga": where(map_id=349)}
        self.assertEqual(farmjob.in_reach(pos, "Grug"), ["Grug"])

    def test_with_no_leader_reading_nobody_is_cut(self):
        pos = {"Grog": where(x=9000.0)}
        self.assertEqual(farmjob.in_reach(pos, "Grug"), ["Grog"])

    def test_the_bridge_judges_the_order_on_the_members_in_reach(self):
        text = (ROOT / "bridge.py").read_text(encoding="utf-8")
        start = text.index("    async def _farm_job_now(")
        body = text[start : text.index("    async def _farm_state_for(")]
        self.assertIn("farmjob.in_reach(", body)


class TheLeaderDwellsAtANode(unittest.TestCase):
    """The bots gather what is within reach; hopping on at once gives them none."""

    def at_node(self, **kw):
        node = spawn(0, 10)
        far = spawn(300, 0)
        return reads(spawns=(node, far), leader_at=leader_at(0.0, 0.0, zone=490), **kw)

    def test_just_arrived_it_waits_at_the_node(self):
        step = farmjob.decide(order(), self.at_node(stood_since=50.0, now=60.0))
        self.assertEqual(step.action, farmjob.WAIT)
        self.assertIn("dwell", step.line)

    def test_after_the_dwell_it_hops_on(self):
        late = 50.0 + farmjob.DWELL_SECONDS + 1
        step = farmjob.decide(order(), self.at_node(stood_since=50.0, now=late))
        self.assertEqual(step.action, farmjob.HOP)

    def test_with_no_stand_reading_it_hops_as_before(self):
        step = farmjob.decide(order(), self.at_node(stood_since=0.0, now=60.0))
        self.assertEqual(step.action, farmjob.HOP)

    def test_the_stand_clock_starts_on_arrival_and_keeps_its_start(self):
        near, far = spawn(0, 10), spawn(300, 0)
        here = leader_at(0.0, 0.0, zone=490)
        first = farmjob.stand_update(None, (near, far), here, 100.0)
        self.assertEqual(first[1], 100.0)
        again = farmjob.stand_update(first, (near, far), here, 130.0)
        self.assertEqual(again, first)

    def test_a_spawn_in_another_zone_does_not_start_the_clock(self):
        across = spawn(0, 10, zone=361)
        got = farmjob.stand_update(
            None, (across,), leader_at(0.0, 0.0, zone=490), 100.0
        )
        self.assertEqual(got, (None, 0.0))

    def test_the_stand_clock_clears_off_a_node_and_restarts_on_another(self):
        near, far = spawn(0, 10), spawn(300, 0)
        first = farmjob.stand_update(
            None, (near, far), leader_at(0.0, 0.0, zone=490), 100.0
        )
        gone = farmjob.stand_update(
            first, (near, far), leader_at(150.0, 0.0, zone=490), 120.0
        )
        self.assertEqual(gone, (None, 0.0))
        moved = farmjob.stand_update(
            first, (near, far), leader_at(300.0, 0.0, zone=490), 140.0
        )
        self.assertEqual(moved[1], 140.0)


class AFarmEndInTheProfessionLoop(unittest.TestCase):
    """The loop owns the job, so an ended order must never leave job=quest."""

    @classmethod
    def setUpClass(cls):
        import ast

        text = (ROOT / "bridge.py").read_text(encoding="utf-8")
        node = next(
            n
            for n in ast.parse(text).body
            if isinstance(n, ast.FunctionDef) and n.name == "_farm_end_write"
        )
        ns = {"jobs": farmjob.jobs}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        cls.write = staticmethod(ns["_farm_end_write"])

    def test_outside_the_loop_the_default_job_is_written(self):
        self.assertEqual(self.write("farm:mining", False, True), farmjob.jobs.DEFAULT)

    def test_in_the_loop_a_spent_box_renews_the_same_order(self):
        self.assertEqual(self.write("farm:mining", True, True), "farm:mining")

    def test_in_the_loop_any_other_end_writes_nothing(self):
        self.assertIsNone(self.write("farm:mining", True, False))

    def test_a_spent_time_box_or_met_target_asks_for_a_renewal(self):
        box = farmjob.decide(order(started=0.0), reads(now=99999.0))
        self.assertTrue(box.renew)
        met = farmjob.decide(order(), reads(gathered=99))
        self.assertTrue(met.renew)

    def test_deaths_and_no_field_do_not(self):
        deaths = ((490, 1),) * 12
        step = farmjob.decide(order(), reads(deaths=deaths))
        self.assertEqual(step.action, farmjob.END)
        self.assertFalse(step.renew)

    def test_the_bridge_passes_the_renewal_flag_to_the_end(self):
        text = (ROOT / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("await self._end_farm(cohort, job, renew=step.renew)", text)


class AnEndedOrderThatTheLoopWritesAgain(unittest.TestCase):
    """The loop re-writes farm:mining after the time box ends the first order."""

    @classmethod
    def setUpClass(cls):
        import ast

        text = (ROOT / "bridge.py").read_text(encoding="utf-8")
        node = next(
            n
            for n in ast.parse(text).body
            if isinstance(n, ast.FunctionDef) and n.name == "_farm_order_renewed"
        )
        ns = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        cls.renewed = staticmethod(ns["_farm_order_renewed"])

    def test_a_newer_job_write_is_a_new_order(self):
        self.assertTrue(self.renewed({"ended": True, "started": 100.0}, 200.0))

    def test_the_same_write_is_still_the_ended_order(self):
        self.assertFalse(self.renewed({"ended": True, "started": 100.0}, 100.0))
        self.assertFalse(self.renewed({"ended": True, "started": 100.0}, 0.0))

    def test_a_live_order_is_never_renewed(self):
        self.assertFalse(self.renewed({"started": 100.0}, 200.0))

    def test_the_pass_drops_the_ended_state_on_a_renewed_order(self):
        text = (ROOT / "bridge.py").read_text(encoding="utf-8")
        start = text.index("    async def _farm_job_now(")
        body = text[start : text.index("    async def _farm_state_for(")]
        self.assertIn("_farm_order_renewed(state, written)", body)


if __name__ == "__main__":
    unittest.main()

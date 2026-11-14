"""The item plan's disenchant route (#1978): read from the core, carried out.

Two halves. The plan names DISENCHANT only for a stack the core would let the
holder break down, so the skill it needs is the core's own
(RequiredDisenchantSkill, and no DisenchantID means no breakdown) rather than
the convention `itemplan.disenchant_skill` falls back to. The route then turns
a carried DISENCHANT decision into a `disenchant` command row, behind its own
switch, only where the current protection would keep the stack.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import itemplan  # noqa: E402
import itemplan_data  # noqa: E402
import itemplan_disenchant as route  # noqa: E402
import itemplan_shadow as shadow  # noqa: E402
from test_itemplan import member, stack  # noqa: E402

ENCHANTING = 333
ON = {"ITEMPLAN_DISENCHANT": "on"}


def enchanter(skill):
    return member(skills=[(ENCHANTING, skill, 75)])


def bracers(**kw):
    base = dict(
        entry=500,
        name="Plate Bracers",
        item_class=4,
        subclass=4,
        quality=2,
        sell=100,
        bind=1,
        soulbound=True,
        req_level=30,
        item_level=30,
    )
    base.update(kw)
    return stack(**base)


def decision(s, who):
    plan = itemplan.plan([s], [who], itemplan.Context(fire_gear=frozenset()))
    return plan.decisions[0], plan


class ThePlanReadsTheCore(unittest.TestCase):
    def test_a_skill_the_core_asks_above_the_holders_is_not_broken_down(self):
        # The convention would ask 45 for item level 30 and let skill 60 try.
        d, _ = decision(bracers(disenchant_id=7, disenchant_skill=100), enchanter(60))
        self.assertNotEqual(itemplan.DISENCHANT, d.route)

    def test_a_skill_the_core_asks_below_the_convention_is_broken_down(self):
        d, _ = decision(bracers(disenchant_id=7, disenchant_skill=20), enchanter(30))
        self.assertEqual(itemplan.DISENCHANT, d.route)

    def test_an_item_the_core_gives_no_breakdown_is_not_broken_down(self):
        d, _ = decision(bracers(disenchant_id=0, disenchant_skill=1), enchanter(300))
        self.assertNotEqual(itemplan.DISENCHANT, d.route)

    def test_minus_one_means_never(self):
        d, _ = decision(bracers(disenchant_id=7, disenchant_skill=-1), enchanter(300))
        self.assertNotEqual(itemplan.DISENCHANT, d.route)

    def test_an_unread_core_falls_back_to_the_convention(self):
        d, _ = decision(bracers(), enchanter(60))
        self.assertEqual(itemplan.DISENCHANT, d.route)
        d, _ = decision(bracers(), enchanter(40))
        self.assertNotEqual(itemplan.DISENCHANT, d.route)


class TheTemplateRead(unittest.TestCase):
    def test_the_template_query_asks_for_the_core_facts(self):
        self.assertIn("DisenchantID", itemplan_data.ITEM_TEMPLATE_SQL)
        self.assertIn("RequiredDisenchantSkill", itemplan_data.ITEM_TEMPLATE_SQL)

    def test_a_template_row_carries_them_to_the_stack(self):
        template = {
            "entry": 500,
            "item_class": 4,
            "subclass": 4,
            "bonding": 1,
            "inventory_type": 9,
            "item_level": 30,
            "req_level": 30,
            "required_skill_rank": 0,
            "container_slots": 0,
            "fire_res": 0,
            "disenchant_id": 7,
            "disenchant_skill": 25,
        }
        got = itemplan_data.item_templates([template])
        self.assertEqual(7, got[500]["disenchant_id"])
        self.assertEqual(25, got[500]["disenchant_skill"])
        row = {
            "holder": "Ana",
            "item_guid": 9,
            "entry": 500,
            "name": "Plate Bracers",
            "quality": 2,
            "count": 1,
            "sell_price": 100,
            "item_class": 4,
        }
        built = shadow.build_stacks([row], (), got, {9: True})
        self.assertEqual(7, built[0].disenchant_id)
        self.assertEqual(25, built[0].disenchant_skill)

    def test_a_template_row_without_them_is_still_read(self):
        template = {
            "entry": 500,
            "item_class": 4,
            "subclass": 4,
            "bonding": 1,
            "inventory_type": 9,
            "item_level": 30,
            "req_level": 30,
            "required_skill_rank": 0,
            "container_slots": 0,
            "fire_res": 0,
        }
        got = itemplan_data.item_templates([template])
        self.assertIn(500, got)
        self.assertNotIn("disenchant_id", got[500])


def carried_row(guid=9, quality=2, **kw):
    base = {
        "holder": "Ana",
        "item_guid": guid,
        "entry": 500,
        "name": "Plate Bracers",
        "quality": quality,
        "count": 1,
        "sell_price": 100,
        "item_class": 4,
        "bag_family": 0,
        "quest_item": False,
        "reagent": False,
        "profession_needed": False,
    }
    base.update(kw)
    return base


def pair(s, row):
    return [(s, row)]


class TheSwitch(unittest.TestCase):
    def test_it_is_off_unless_its_own_switch_reads_on(self):
        self.assertFalse(route.enabled({}))
        self.assertFalse(route.enabled({"ITEMPLAN_SELL_VENDOR": "on"}))
        self.assertFalse(route.enabled({"ITEMPLAN_DISENCHANT": "off"}))
        self.assertTrue(route.enabled(ON))
        self.assertTrue(route.enabled({"ITEMPLAN_DISENCHANT": "1"}))


class TheJobs(unittest.TestCase):
    def jobs(self, s, row, who=None, **kw):
        _d, plan = decision(s, who or enchanter(60))
        return route.jobs_for(plan, pair(s, row), **kw)

    def test_a_carried_disenchant_decision_is_a_job_for_its_holder(self):
        s = bracers(holder="Ana")
        jobs = self.jobs(s, carried_row(), keep_names=())
        self.assertEqual(1, len(jobs))
        self.assertEqual(("Ana", 9), (jobs[0].holder, jobs[0].item_guid))
        self.assertEqual(60, jobs[0].skill)

    def test_a_stack_the_sale_pass_already_sells_is_left_to_it(self):
        # A grey is sold by the ordinary pass; the route acts only where the
        # current protection would keep the stack.
        s = bracers(holder="Ana", quality=1)
        self.assertEqual((), self.jobs(s, carried_row(quality=1)))

    def test_a_confirm_decision_waits_for_a_release(self):
        # Worth a gold or more is irreversible and waits, as a sale does.
        s = bracers(holder="Ana", sell=20000)
        d, plan = decision(s, enchanter(60))
        self.assertEqual(itemplan.DISENCHANT, d.route)
        self.assertTrue(d.confirm)
        row = carried_row(sell_price=20000)
        self.assertEqual((), route.jobs_for(plan, pair(s, row)))
        released = route.jobs_for(plan, pair(s, row), released={d.key})
        self.assertEqual(1, len(released))

    def test_a_kept_name_is_not_broken_down(self):
        s = bracers(holder="Ana")
        row = carried_row(name="Plate Bracers")
        self.assertEqual((), self.jobs(s, row, keep_names=("Plate Bracers",)))

    def test_a_stuck_or_banked_decision_is_not_a_job(self):
        s = bracers(holder="Ana", loc="bank_personal")
        _d, plan = decision(s, enchanter(60))
        self.assertEqual((), route.jobs_for(plan, pair(s, carried_row())))

    def test_a_row_naming_no_item_is_not_a_job(self):
        s = bracers(holder="Ana")
        self.assertEqual((), self.jobs(s, carried_row(guid=0)))

    def test_other_routes_are_not_jobs(self):
        s = bracers(holder="Ana", disenchant_id=0)
        self.assertEqual((), self.jobs(s, carried_row()))

    def test_the_log_line_names_the_stack_and_the_skill(self):
        s = bracers(holder="Ana")
        lines = route.lines(self.jobs(s, carried_row()))
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].startswith(route.PREFIX))
        self.assertIn("Ana", lines[0])
        self.assertIn("Plate Bracers", lines[0])
        self.assertIn("60", lines[0])


class TheBridgeSeam(unittest.TestCase):
    """`bridge._carry_out_itemplan_disenchant` writes the rows, never widening
    what the keep marks and the epic gate allow."""

    def setUp(self):
        from unittest import mock

        from test_itemplan_vendor import import_bridge

        self.mock = mock
        self.bridge = import_bridge()
        self.job = route.Job("Og", 77, "Plate Bracers", 60, "why", ("Og", 1, 5, 0))
        self.facts = self.bridge.bag_pressure.DisenchantFacts(
            item_class=4, quality=2, disenchant_id=7, required_skill=20, soulbound=True
        )

    def run_with(
        self, job=None, facts="default", skill=60, keep=False, epic=False, existing=0
    ):
        b = self.bridge
        facts = self.facts if facts == "default" else facts
        cursor = self.mock.MagicMock()
        cursor.fetchone.return_value = {"n": existing}
        cursor.lastrowid = 501
        conn = self.mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        with (
            self.mock.patch.object(b._KEEP, "blocks", return_value=keep),
            self.mock.patch.object(b, "_epic_blocks", return_value=epic),
            self.mock.patch.object(b, "_disenchant_facts", return_value=facts),
            self.mock.patch.object(b, "_family_enchanters", return_value={"Og": skill}),
            self.mock.patch.object(b, "_connect", return_value=conn),
        ):
            wrote = b._carry_out_itemplan_disenchant((job or self.job,))
        return wrote, cursor

    def inserts(self, cursor):
        return [
            c
            for c in cursor.execute.call_args_list
            if "INSERT INTO overseer_command" in c.args[0]
        ]

    def test_it_writes_one_disenchant_row_for_the_holder(self):
        wrote, cursor = self.run_with()
        self.assertEqual(1, wrote)
        (call,) = self.inserts(cursor)
        self.assertEqual(
            ("Og", "guid:77 count:1", "disenchant", "", "itemplan-disenchant"),
            call.args[1],
        )

    def test_a_kept_item_writes_nothing(self):
        wrote, cursor = self.run_with(keep=True)
        self.assertEqual((0, []), (wrote, self.inserts(cursor)))

    def test_an_epic_the_gate_keeps_writes_nothing(self):
        wrote, cursor = self.run_with(epic=True)
        self.assertEqual((0, []), (wrote, self.inserts(cursor)))

    def test_a_skill_the_core_asks_too_much_writes_nothing(self):
        facts = self.bridge.bag_pressure.DisenchantFacts(
            item_class=4, quality=2, disenchant_id=7, required_skill=100, soulbound=True
        )
        wrote, cursor = self.run_with(facts=facts)
        self.assertEqual((0, []), (wrote, self.inserts(cursor)))

    def test_unread_facts_write_nothing(self):
        wrote, cursor = self.run_with(facts=None)
        self.assertEqual((0, []), (wrote, self.inserts(cursor)))

    def test_a_row_already_standing_is_not_written_again(self):
        wrote, cursor = self.run_with(existing=1)
        self.assertEqual((0, []), (wrote, self.inserts(cursor)))

    def test_the_pass_calls_the_route_only_behind_its_switch(self):
        text = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("itemplan_disenchant.enabled()", text)
        self.assertIn("_run_itemplan_disenchant", text)


if __name__ == "__main__":
    unittest.main()

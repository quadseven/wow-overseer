"""Guild work orders: requests, assignments, cooldowns.

Pure unit tests against synthetic Members and WorkOrders, the same seam as
tests/test_guildshare.py: this suite proves the DECISION is right for the
inputs given. It does not prove bridge.py's SQL produces those inputs, and it
does not re-prove any worldserver verb - the module is pure and the bridge
persists what it decides.

WHAT THE FIXTURES CARRY. The professions and skill ids come from goals.SKILL_IDS,
the same table the module reads: alchemy 171, herbalism 182, tailoring 197,
enchanting 333. The ticket's own examples appear by name - 96 Greater Fire
Protection Potion, Firebloom in Searing Gorge, Mooncloth, Arcanite - so a rule
that passes here has been checked against a real shape rather than a convenient
one.
"""

import pathlib
import unittest

import goals
import guildshare
import workorders as guildworkorders

ALCHEMY = goals.SKILL_IDS["alchemy"]
HERBALISM = goals.SKILL_IDS["herbalism"]
TAILORING = goals.SKILL_IDS["tailoring"]


def _member(name, level=40, skills=None, online=True, cooldowns=None):
    return guildworkorders.WorkMember(
        name=name,
        level=level,
        online=online,
        skills=skills or {},
        cooldowns=cooldowns or {},
    )


def _order(
    kind,
    item,
    quantity=0,
    zone="",
    requested_by="the guild",
    status=guildworkorders.REQUESTED,
    assigned_to="",
):
    return guildworkorders.WorkOrder(
        kind=kind,
        item=item,
        quantity=quantity,
        zone=zone,
        requested_by=requested_by,
        status=status,
        assigned_to=assigned_to,
    )


class CanTakeTest(unittest.TestCase):
    """A member can take only what it holds, and only while online."""

    def test_online_alchemist_takes_a_consumable_request(self):
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 96)
        member = _member("Ugga", skills={ALCHEMY: 200})
        self.assertEqual(guildworkorders.can_take(member, order), "Ugga holds alchemy")

    def test_offline_crafter_is_not_a_taker(self):
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion")
        member = _member("Ugga", skills={ALCHEMY: 200}, online=False)
        self.assertEqual(guildworkorders.can_take(member, order), "")

    def test_member_without_the_craft_cannot_take(self):
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion")
        member = _member("Grug", skills={HERBALISM: 200})
        self.assertEqual(guildworkorders.can_take(member, order), "")

    def test_malformed_skill_value_is_not_treated_as_no_profession(self):
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion")
        member = _member("Ugga", skills={ALCHEMY: "unknown"})
        with self.assertRaises(ValueError):
            guildworkorders.can_take(member, order)

    def test_an_item_no_craft_names_is_refused_not_guessed(self):
        order = _order(guildworkorders.CONSUMABLE, "Mystery Tonic")
        member = _member("Ugga", skills={ALCHEMY: 200})
        self.assertEqual(guildworkorders.can_take(member, order), "")

    def test_online_herbalist_takes_a_farming_assignment(self):
        order = _order(guildworkorders.FARMING, "Firebloom", zone="Searing Gorge")
        member = _member("Bork", skills={HERBALISM: 200})
        self.assertEqual(
            guildworkorders.can_take(member, order), "Bork holds herbalism"
        )

    def test_a_miner_cannot_farm_an_herb(self):
        order = _order(guildworkorders.FARMING, "Firebloom", zone="Searing Gorge")
        member = _member("Grug", skills={goals.SKILL_IDS["mining"]: 200})
        self.assertEqual(guildworkorders.can_take(member, order), "")

    def test_a_farming_item_no_trade_names_is_refused(self):
        order = _order(guildworkorders.FARMING, "Unknown Weed", zone="Nowhere")
        member = _member("Bork", skills={HERBALISM: 200})
        self.assertEqual(guildworkorders.can_take(member, order), "")

    def test_a_tailor_takes_the_mooncloth_cooldown(self):
        order = _order(guildworkorders.COOLDOWN, "Mooncloth")
        member = _member("Og", skills={TAILORING: 300})
        self.assertEqual(guildworkorders.can_take(member, order), "Og holds tailoring")

    def test_an_alchemist_takes_the_arcanite_cooldown(self):
        order = _order(guildworkorders.COOLDOWN, "Arcanite")
        member = _member("Grog", skills={ALCHEMY: 300})
        self.assertEqual(guildworkorders.can_take(member, order), "Grog holds alchemy")

    def test_a_cooldown_no_profession_names_is_refused(self):
        order = _order(guildworkorders.COOLDOWN, "Unknown Cooldown")
        member = _member("Og", skills={TAILORING: 300})
        self.assertEqual(guildworkorders.can_take(member, order), "")


class PlanAssignsTest(unittest.TestCase):
    """The plan places each open order with a taker who can do it."""

    def test_a_consumable_goes_to_the_online_crafter(self):
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 96)
        plan = guildworkorders.plan([order], [_member("Ugga", skills={ALCHEMY: 200})])
        self.assertEqual(len(plan.assignments), 1)
        self.assertEqual(plan.assignments[0].taker, "Ugga")
        self.assertEqual(
            plan.assignments[0].order.item, "Greater Fire Protection Potion"
        )
        self.assertEqual(plan.assignments[0].order.status, guildworkorders.ASSIGNED)
        self.assertEqual(plan.assignments[0].order.assigned_to, "Ugga")

    def test_only_the_assignee_can_complete_an_order(self):
        order = _order(
            guildworkorders.COOLDOWN,
            "Mooncloth",
            status=guildworkorders.ASSIGNED,
            assigned_to="Og",
        )
        self.assertEqual(guildworkorders.complete(order, "Bork"), order)
        self.assertEqual(
            guildworkorders.complete(order, "Og").status, guildworkorders.COMPLETE
        )

    def test_an_order_not_yet_assigned_cannot_be_completed(self):
        # The status gate on its own: the reporter matches assigned_to, but
        # the order is still requested, so the report changes nothing.
        order = _order(
            guildworkorders.COOLDOWN,
            "Mooncloth",
            status=guildworkorders.REQUESTED,
            assigned_to="Og",
        )
        self.assertEqual(guildworkorders.complete(order, "Og"), order)

    def test_a_completed_order_stays_complete(self):
        order = _order(
            guildworkorders.COOLDOWN,
            "Mooncloth",
            status=guildworkorders.COMPLETE,
            assigned_to="Og",
        )
        self.assertEqual(guildworkorders.complete(order, "Og"), order)

    def test_the_full_life_of_an_order(self):
        # requested -> assigned (by plan) -> complete (by its assignee).
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 96)
        plan = guildworkorders.plan([order], [_member("Ugga", skills={ALCHEMY: 290})])
        assigned = plan.assignments[0].order
        self.assertEqual(assigned.status, guildworkorders.ASSIGNED)
        done = guildworkorders.complete(assigned, "Ugga")
        self.assertEqual(done.status, guildworkorders.COMPLETE)
        self.assertEqual(done.assigned_to, "Ugga")
        self.assertEqual(done.quantity, 96)

    def test_a_farming_assignment_goes_to_the_online_gatherer(self):
        order = _order(guildworkorders.FARMING, "Firebloom", zone="Searing Gorge")
        plan = guildworkorders.plan([order], [_member("Bork", skills={HERBALISM: 200})])
        self.assertEqual(len(plan.assignments), 1)
        self.assertEqual(plan.assignments[0].taker, "Bork")

    def test_a_cooldown_goes_to_the_profession_holder(self):
        order = _order(guildworkorders.COOLDOWN, "Mooncloth")
        plan = guildworkorders.plan([order], [_member("Og", skills={TAILORING: 300})])
        self.assertEqual(len(plan.assignments), 1)
        self.assertEqual(plan.assignments[0].taker, "Og")

    def test_one_order_per_member_per_cycle(self):
        # Two consumables, one alchemist: only one is placed, the other notes
        # that every taker already has an order.
        orders = [
            _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 48),
            _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 48),
        ]
        plan = guildworkorders.plan(orders, [_member("Ugga", skills={ALCHEMY: 200})])
        self.assertEqual(len(plan.assignments), 1)
        self.assertIn("already has an order this pass", plan.notes[0])

    def test_lowest_level_first_among_qualifiers(self):
        # Two herbalists, one low level and one capped: the low level takes it.
        order = _order(guildworkorders.FARMING, "Firebloom", zone="Searing Gorge")
        members = [
            _member("Bork", level=50, skills={HERBALISM: 200}),
            _member("Navnah", level=20, skills={HERBALISM: 145}),
        ]
        plan = guildworkorders.plan([order], members)
        self.assertEqual(plan.assignments[0].taker, "Navnah")

    def test_an_order_already_complete_is_skipped(self):
        order = _order(
            guildworkorders.CONSUMABLE,
            "Greater Fire Protection Potion",
            status=guildworkorders.COMPLETE,
        )
        plan = guildworkorders.plan([order], [_member("Ugga", skills={ALCHEMY: 200})])
        self.assertEqual(plan.assignments, ())
        self.assertEqual(plan.notes, ())


class PlanNoTakerTest(unittest.TestCase):
    """An order with no taker stays requested and says why."""

    def test_nobody_online_plans_nothing_and_says_why(self):
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 96)
        plan = guildworkorders.plan(
            [order], [_member("Ugga", skills={ALCHEMY: 200}, online=False)]
        )
        self.assertEqual(plan.assignments, ())
        self.assertEqual(
            plan.notes,
            (
                "nobody online holds alchemy, so Greater Fire Protection Potion stays unassigned",
            ),
        )
        self.assertEqual(
            guildworkorders.headline(plan),
            "1 open order and nobody who can take them now",
        )

    def test_an_unknown_item_nobody_can_make_says_so(self):
        order = _order(guildworkorders.CONSUMABLE, "Mystery Tonic")
        plan = guildworkorders.plan([order], [_member("Ugga", skills={ALCHEMY: 200})])
        self.assertEqual(plan.assignments, ())
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("no craft or trade this guild knows", plan.notes[0])

    def test_offline_only_members_are_not_takers(self):
        order = _order(guildworkorders.FARMING, "Firebloom", zone="Searing Gorge")
        plan = guildworkorders.plan(
            [order], [_member("Bork", skills={HERBALISM: 200}, online=False)]
        )
        self.assertEqual(plan.assignments, ())
        self.assertEqual(len(plan.notes), 1)

    def test_a_member_holding_nothing_matches_nothing(self):
        order = _order(guildworkorders.COOLDOWN, "Mooncloth")
        plan = guildworkorders.plan([order], [_member("Grug", skills={})])
        self.assertEqual(plan.assignments, ())
        self.assertEqual(len(plan.notes), 1)

    def test_deterministic_across_runs(self):
        order = _order(guildworkorders.FARMING, "Firebloom", zone="Searing Gorge")
        members = [
            _member("Bork", level=40, skills={HERBALISM: 200}),
            _member("Navnah", level=40, skills={HERBALISM: 200}),
        ]
        first = guildworkorders.plan([order], members)
        second = guildworkorders.plan([order], list(reversed(members)))
        self.assertEqual(first.assignments[0].taker, second.assignments[0].taker)


class CooldownTest(unittest.TestCase):
    """A cooldown goes only to a holder whose own cooldown is ready."""

    def test_a_tailor_on_cooldown_is_not_a_taker(self):
        order = _order(guildworkorders.COOLDOWN, "Mooncloth")
        member = _member("Og", skills={TAILORING: 300}, cooldowns={"mooncloth": 600})
        self.assertEqual(guildworkorders.can_take(member, order), "")

    def test_the_ready_tailor_takes_it_over_a_lower_level_one_on_cooldown(self):
        order = _order(guildworkorders.COOLDOWN, "Mooncloth")
        members = [
            _member(
                "Og", level=20, skills={TAILORING: 250}, cooldowns={"mooncloth": 600}
            ),
            _member("Ugga", level=60, skills={TAILORING: 300}),
        ]
        plan = guildworkorders.plan([order], members)
        self.assertEqual(plan.assignments[0].taker, "Ugga")

    def test_every_holder_on_cooldown_names_the_soonest(self):
        order = _order(guildworkorders.COOLDOWN, "Arcanite")
        members = [
            _member("Grog", skills={ALCHEMY: 300}, cooldowns={"arcanite": 7200}),
            _member("Ugga", skills={ALCHEMY: 300}, cooldowns={"arcanite": 3000}),
        ]
        plan = guildworkorders.plan([order], members)
        self.assertEqual(plan.assignments, ())
        self.assertEqual(
            plan.notes,
            ("every alchemy holder is on the Arcanite cooldown; Ugga is ready in 1h",),
        )

    def test_a_cooldown_on_another_item_does_not_block(self):
        order = _order(guildworkorders.COOLDOWN, "Arcanite")
        member = _member("Grog", skills={ALCHEMY: 300}, cooldowns={"mooncloth": 9000})
        self.assertEqual(guildworkorders.can_take(member, order), "Grog holds alchemy")

    def test_cooldowns_do_not_gate_a_consumable(self):
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 8)
        member = _member("Grog", skills={ALCHEMY: 300}, cooldowns={"arcanite": 9000})
        self.assertEqual(guildworkorders.can_take(member, order), "Grog holds alchemy")


class SaidLinesTest(unittest.TestCase):
    """What each taker says out loud."""

    def test_a_consumable_assignment_says_what_is_needed(self):
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 96)
        plan = guildworkorders.plan([order], [_member("Ugga", skills={ALCHEMY: 200})])
        self.assertEqual(
            guildworkorders.lines(plan),
            ["Ugga: the guild needs 96 Greater Fire Protection Potion"],
        )

    def test_a_farming_assignment_says_zone_and_item(self):
        order = _order(guildworkorders.FARMING, "Firebloom", zone="Searing Gorge")
        plan = guildworkorders.plan([order], [_member("Bork", skills={HERBALISM: 200})])
        self.assertEqual(
            guildworkorders.lines(plan),
            ["Bork: the guild wants Firebloom from Searing Gorge"],
        )

    def test_a_cooldown_assignment_says_the_cooldown(self):
        order = _order(guildworkorders.COOLDOWN, "Mooncloth")
        plan = guildworkorders.plan([order], [_member("Og", skills={TAILORING: 300})])
        self.assertEqual(
            guildworkorders.lines(plan),
            ["Og: the Mooncloth cooldown is mine to spend"],
        )


class HeadlineTest(unittest.TestCase):
    """The one line over the plan."""

    def test_no_orders_says_so(self):
        self.assertEqual(
            guildworkorders.headline(guildworkorders.WorkOrderPlan()),
            "no open work orders this pass",
        )

    def test_placed_orders_name_the_takers(self):
        order = _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 96)
        plan = guildworkorders.plan([order], [_member("Ugga", skills={ALCHEMY: 200})])
        self.assertEqual(
            guildworkorders.headline(plan),
            "1 work order going out to 1 member: Ugga",
        )

    def test_multiple_orders_use_the_plural(self):
        orders = [
            _order(guildworkorders.CONSUMABLE, "Greater Fire Protection Potion", 48),
            _order(guildworkorders.FARMING, "Firebloom", zone="Searing Gorge"),
        ]
        plan = guildworkorders.plan(
            orders,
            [
                _member("Ugga", skills={ALCHEMY: 200}),
                _member("Bork", skills={HERBALISM: 200}),
            ],
        )
        self.assertEqual(
            guildworkorders.headline(plan),
            "2 work orders going out to 2 members: Bork, Ugga",
        )


class RosterTest(unittest.TestCase):
    """The bridge's guild roster becomes WorkMembers unchanged."""

    def test_a_guildshare_member_carries_name_level_online_and_skills(self):
        roster = [
            guildshare.Member(
                name="Og", level=58, skills={TAILORING: 300}, online=True
            ),
            guildshare.Member(name="Bork", level=12, skills=None, online=False),
        ]
        self.assertEqual(
            guildworkorders.members_from_roster(roster),
            [
                guildworkorders.WorkMember("Og", 58, True, {TAILORING: 300}),
                guildworkorders.WorkMember("Bork", 12, False, {}),
            ],
        )

    def test_the_standing_orders_are_the_two_cooldowns(self):
        self.assertEqual(
            [(o.kind, o.item) for o in guildworkorders.STANDING_ORDERS],
            [
                (guildworkorders.COOLDOWN, "Mooncloth"),
                (guildworkorders.COOLDOWN, "Arcanite"),
            ],
        )


class BridgeWiringTest(unittest.TestCase):
    """The guild surplus pass logs the standing work orders, and writes nothing."""

    def test_the_bridge_logs_who_takes_each_standing_order(self):
        from test_guildsocial_bridge import bridge

        roster = [
            guildshare.Member(
                name="Og", level=58, skills={TAILORING: 300}, online=True
            ),
        ]
        with self.assertLogs(bridge.log, "INFO") as seen:
            bridge._log_work_orders(roster)
        said = [r.getMessage() for r in seen.records]
        self.assertEqual(
            said,
            [
                "workorders: 1 work order going out to 1 member: Og",
                "workorders: Og: the Mooncloth cooldown is mine to spend",
                "workorders: nobody online holds alchemy, so Arcanite stays unassigned",
            ],
        )

    def test_the_guild_surplus_pass_calls_it_with_its_roster(self):
        source = (
            pathlib.Path(__file__).resolve().parent.parent / "bridge.py"
        ).read_text(encoding="utf-8")
        start = source.index("    async def _guild_share_once(")
        end = source.index("    async def _write_guild_gifts(")
        self.assertIn("_log_work_orders(roster)", source[start:end])


if __name__ == "__main__":
    unittest.main()

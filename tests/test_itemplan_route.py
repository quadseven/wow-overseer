"""The item plan's bank routes are carried out (#2136).

`itemplan.plan` names GUILD_BANK (a tab) and BANK_PERSONAL for a stack nobody
in the family will wear, and nothing carried either route out: the sale paths
were refused by the loot policy, the plan's own executors write only a give, a
sale, a listing or a breakdown, and the bank pass answered a different
question. A bag full of unworn greens stayed full. `itemplan_route` turns those
decisions into the bank pass's own moves, through the loot policy and the
quest-log hold, and nothing else.
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import bank  # noqa: E402
import itemplan  # noqa: E402
import itemplan_route as route  # noqa: E402
import lootpolicy  # noqa: E402
from itemplan import Context  # noqa: E402
from test_itemplan import decide, member, stack  # noqa: E402

VAULT = {
    ("Fam", itemplan.GUILD_TAB_GEAR): 50,
    ("Fam", itemplan.GUILD_TAB_MATERIALS): 50,
}


def green(i, **kw):
    base = dict(
        entry=900 + i,
        name="Plate Thing %d" % i,
        item_class=4,
        subclass=4,
        quality=2,
        sell=900,
        bind=2,
        req_level=40,
        item_level=45,
        quest_needed=False,
    )
    base.update(kw)
    return stack(**base)


def rows_for(stacks):
    """The economy pass's carried rows, one per stack, with an item guid."""
    return [
        {
            "holder": s.holder,
            "entry": s.entry,
            "name": s.name,
            "item_guid": 5000 + n,
            "count": s.count,
            "quality": s.quality,
        }
        for n, s in enumerate(stacks)
    ]


def pairs_of(stacks, rows=None):
    return list(zip(stacks, rows or rows_for(stacks), strict=True))


def plan_of(stacks, ctx=None, who=None):
    who = who or [member(carried_slots=16, bank_slots=0)]
    ctx = ctx or Context(fire_gear=frozenset(), guild_free=VAULT)
    _, plan = decide(stacks, who, ctx)
    return plan


def bank_it(row, holder):
    return lootpolicy.Verdict(
        lootpolicy.BANK_OR_AUCTION, "a guild member could use it later"
    )


class TheLootPolicyAllowsDeposits(unittest.TestCase):
    def test_the_guild_bank_takes_only_what_the_policy_shelves(self):
        shelved = lootpolicy.Verdict(lootpolicy.BANK_OR_AUCTION, "x")
        self.assertTrue(lootpolicy.allowed(shelved, lootpolicy.GUILD_DEPOSIT))
        for name in (
            lootpolicy.UPGRADE,
            lootpolicy.DISENCHANT,
            lootpolicy.VENDOR,
            lootpolicy.HOLD,
        ):
            verdict = lootpolicy.Verdict(name, "x")
            self.assertFalse(
                lootpolicy.allowed(verdict, lootpolicy.GUILD_DEPOSIT), name
            )

    def test_a_bound_piece_that_stays_may_go_into_its_holders_own_bank_only(self):
        stays = lootpolicy.Verdict(lootpolicy.HOLD, "x", stays=True)
        self.assertTrue(lootpolicy.allowed(stays, lootpolicy.BANK_DEPOSIT))
        self.assertFalse(lootpolicy.allowed(stays, lootpolicy.GUILD_DEPOSIT))

    def test_an_unread_or_quest_hold_is_never_deposited(self):
        held = lootpolicy.Verdict(lootpolicy.HOLD, "its quest log could not be read")
        self.assertFalse(lootpolicy.allowed(held, lootpolicy.BANK_DEPOSIT))

    def test_the_old_kinds_are_unchanged(self):
        vendor = lootpolicy.Verdict(lootpolicy.VENDOR, "x")
        shelved = lootpolicy.Verdict(lootpolicy.BANK_OR_AUCTION, "x")
        self.assertTrue(lootpolicy.allowed(vendor, "sell"))
        self.assertFalse(lootpolicy.allowed(shelved, "sell"))

    def test_a_bound_usable_piece_is_marked_as_staying(self):
        row = {
            "quality": 2,
            "item_class": 7,
            "subclass": 0,
            "inventory_type": 0,
            "required_level": 1,
            "instance_flags": 1,
            "bonding": 1,
            "quest_needed": False,
            "item_guid": 1,
        }
        verdict = lootpolicy.decide(row, frozenset({1}))
        self.assertEqual((lootpolicy.HOLD, True), (verdict.route, verdict.stays))


class TheBankRoutesAreCarriedOut(unittest.TestCase):
    def test_the_plan_names_a_vault_tab_for_unworn_greens(self):
        plan = plan_of([green(i) for i in range(3)])
        self.assertEqual({itemplan.GUILD_BANK}, {d.route for d in plan.decisions})

    def test_each_guild_bank_decision_becomes_a_deposit_into_its_tab(self):
        stacks = [green(i) for i in range(3)]
        out = route.routes_for(plan_of(stacks), pairs_of(stacks), bank_it)
        self.assertEqual(3, len(out.moves))
        for n, move in enumerate(out.moves):
            self.assertEqual(
                (bank.GUILD, bank.DEPOSIT, 5000 + n, itemplan.GUILD_TAB_GEAR),
                (move.to, move.verb, move.guid, move.tab),
            )
            self.assertEqual("Ana", move.character)
        self.assertEqual(
            "bank deposit-item guid:5000 tab:1", bank.command(out.moves[0])
        )

    def test_a_personal_bank_decision_becomes_a_deposit_into_the_holders_bank(self):
        stacks = [green(1)]
        plan = plan_of(
            stacks,
            Context(fire_gear=frozenset()),
            [member(carried_slots=16, bank_slots=24)],
        )
        self.assertEqual(itemplan.BANK_PERSONAL, plan.decisions[0].route)
        out = route.routes_for(plan, pairs_of(stacks), bank_it)
        self.assertEqual(
            (bank.PERSONAL, "deposit guid:5000"),
            (out.moves[0].to, bank.command(out.moves[0])),
        )

    def test_only_the_bank_routes_are_carried_out(self):
        stacks = [
            green(1),
            stack(
                entry=78,
                name="Rag",
                item_class=15,
                quality=0,
                sell=3,
                quest_needed=False,
            ),
        ]
        plan = plan_of(stacks)

        def by_quality(row, holder):
            # What the policy says: gray goes to a vendor, never to a bank.
            if row["quality"] == 0:
                return lootpolicy.Verdict(lootpolicy.VENDOR, "gray or junk")
            return bank_it(row, holder)

        out = route.routes_for(plan, pairs_of(stacks), by_quality)
        self.assertEqual({5000}, {m.guid for m in out.moves})
        self.assertEqual(["Rag"], [h.name for h in out.held])

    def test_a_stack_a_quest_in_the_log_names_stays_in_the_bags(self):
        for needed in (True, None):
            stacks = [green(1, quest_needed=needed)]
            out = route.routes_for(plan_of(stacks), pairs_of(stacks), bank_it)
            self.assertEqual((), out.moves, needed)
            self.assertEqual(1, len(out.held), needed)
            self.assertIn("quest", out.held[0].why)

    def test_an_upgrade_for_a_guildmate_is_handed_on_not_banked(self):
        stacks = [green(1, quality=4, name="Epic Plate")]

        def upgrade(row, holder):
            return lootpolicy.Verdict(
                lootpolicy.UPGRADE, "an upgrade for Bluk", ("Bluk",)
            )

        out = route.routes_for(plan_of(stacks), pairs_of(stacks), upgrade)
        self.assertEqual((), out.moves)
        self.assertIn("UPGRADE", out.held[0].why)

    def test_an_epic_the_policy_shelves_is_deposited_never_sold(self):
        stacks = [green(1, quality=4, name="Epic Plate")]
        out = route.routes_for(plan_of(stacks), pairs_of(stacks), bank_it)
        self.assertEqual([bank.DEPOSIT], [m.verb for m in out.moves])
        self.assertEqual([bank.GUILD], [m.to for m in out.moves])

    def test_a_judge_that_fails_or_is_missing_deposits_nothing(self):
        stacks = [green(1)]
        plan = plan_of(stacks)
        self.assertEqual((), route.routes_for(plan, pairs_of(stacks), None).moves)

        def boom(row, holder):
            raise OSError("read failed")

        out = route.routes_for(plan, pairs_of(stacks), boom)
        self.assertEqual((), out.moves)
        self.assertIn("could not be judged", out.held[0].why)

    def test_the_owners_never_dispose_mark_keeps_the_stack(self):
        stacks = [green(1, name="Keepsake")]
        out = route.routes_for(
            plan_of(stacks), pairs_of(stacks), bank_it, keep_names=("keepsake",)
        )
        self.assertEqual((), out.moves)

    def test_a_row_with_no_item_guid_is_not_written(self):
        stacks = [green(1)]
        rows = rows_for(stacks)
        rows[0]["item_guid"] = 0
        out = route.routes_for(plan_of(stacks), pairs_of(stacks, rows), bank_it)
        self.assertEqual((), out.moves)

    def test_a_bound_stack_that_stays_is_not_put_in_the_vault(self):
        stacks = [green(1)]

        def bound(row, holder):
            return lootpolicy.Verdict(lootpolicy.HOLD, "bound", stays=True)

        out = route.routes_for(plan_of(stacks), pairs_of(stacks), bound)
        self.assertEqual((), out.moves)


class TheMovesJoinTheBankPlan(unittest.TestCase):
    def moves(self, n, to=bank.GUILD, holder="Ana", start=0):
        tab = itemplan.GUILD_TAB_GEAR if to == bank.GUILD else 0
        return tuple(
            bank.Move(
                holder, bank.DEPOSIT, 5000 + start + i, "Thing", 1, "why", to, tab
            )
            for i in range(n)
        )

    def test_personal_moves_join_the_banker_list_and_guild_moves_the_vault_list(self):
        base = bank.Plan(moves=self.moves(1, bank.PERSONAL, start=100))
        added = route.Routed(self.moves(2) + self.moves(1, bank.PERSONAL, start=50), ())
        merged = route.merge(base, added)
        self.assertEqual(2, len(merged.moves))
        self.assertEqual(2, len(merged.guild))

    def test_a_stack_the_bank_pass_already_moves_is_not_written_twice(self):
        base = bank.Plan(
            moves=self.moves(1, bank.PERSONAL), guild=self.moves(1, start=1)
        )
        merged = route.merge(base, route.Routed(self.moves(3), ()))
        guids = [m.guid for m in merged.guild + merged.moves]
        self.assertEqual(3, len(guids))
        self.assertEqual(3, len(set(guids)))

    def test_a_visit_carries_at_most_the_visit_limit_per_holder(self):
        added = route.Routed(self.moves(bank.VISIT_LIMIT + 5), ())
        merged = route.merge(bank.Plan(), added)
        self.assertEqual(bank.VISIT_LIMIT, len(merged.guild))

    def test_the_notes_say_what_was_added_and_what_was_held(self):
        held = route.Held("Ana", "Plate Thing", "a quest in the holder's log names it")
        merged = route.merge(bank.Plan(), route.Routed(self.moves(1), (held,)))
        text = " ".join(merged.notes)
        self.assertIn("item plan", text)
        self.assertIn("Plate Thing", text)


class TheSwitch(unittest.TestCase):
    def test_on_unless_switched_off(self):
        self.assertTrue(route.enabled({}))
        self.assertTrue(route.enabled({"ITEMPLAN_BANK": "on"}))
        for off in ("off", "0", "false", "no"):
            self.assertFalse(route.enabled({"ITEMPLAN_BANK": off}), off)


class TheBridgeAsksForTheRoutes(unittest.TestCase):
    SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
        encoding="utf-8"
    )

    def test_the_bank_plan_carries_the_item_plans_routes(self):
        body = self.SOURCE.split("def _plan_bank(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("itemplan_route.merge", body)

    def test_the_routes_are_judged_by_the_loot_policy(self):
        body = self.SOURCE.split("def _itemplan_bank_routes(", 1)[1].split("\ndef ", 1)[
            0
        ]
        self.assertIn("_policy_verdict", body)

    def test_the_deposit_rows_still_pass_the_quest_log_hold(self):
        self.assertTrue(
            re.search(r"_quest_log_holds\(move\.character, command\)", self.SOURCE)
        )
        self.assertTrue(
            re.search(r'startswith\("bank deposit"\) and _quest_log_holds', self.SOURCE)
        )


class TheRoutesReachTheCommandWritingSeam(unittest.TestCase):
    """End to end to the text the rows carry: plan, routes, merge, command."""

    def test_a_proposed_route_ends_as_the_command_the_row_writer_sends(self):
        personal = [green(1)]
        vault = [green(2), green(3)]
        who = [member(carried_slots=16, bank_slots=0)]
        out = route.routes_for(plan_of(vault, None, who), pairs_of(vault), bank_it)
        merged = route.merge(bank.Plan(), out)
        self.assertEqual(
            ["bank deposit-item guid:5000 tab:1", "bank deposit-item guid:5001 tab:1"],
            [bank.command(m) for m in merged.guild],
        )
        self.assertEqual((), merged.moves)
        plan = plan_of(
            personal,
            Context(fire_gear=frozenset()),
            [member(carried_slots=16, bank_slots=24)],
        )
        merged = route.merge(
            bank.Plan(), route.routes_for(plan, pairs_of(personal), bank_it)
        )
        self.assertEqual(["deposit guid:5000"], [bank.command(m) for m in merged.moves])

    def test_a_stale_route_whose_piece_is_gone_is_skipped_cleanly(self):
        stacks = [green(1), green(2)]
        plan = plan_of(stacks)
        # The second piece moved or was disposed of since the plan was read:
        # its carried row is no longer there.
        out = route.routes_for(plan, pairs_of(stacks[:1]), bank_it)
        self.assertEqual([5000], [m.guid for m in out.moves])
        self.assertEqual((), out.held)

    def test_a_soulbound_piece_is_never_proposed_for_the_vault(self):
        stacks = [green(1, bind=1, soulbound=True)]
        plan = plan_of(stacks)
        self.assertNotIn(itemplan.GUILD_BANK, {d.route for d in plan.decisions})
        out = route.routes_for(plan, pairs_of(stacks), bank_it)
        self.assertEqual([], [m for m in out.moves if m.to == bank.GUILD])

    def test_the_vault_pass_writes_the_command_the_bank_formats(self):
        source = TheBridgeAsksForTheRoutes.SOURCE
        start = source.split("async def _queue_guild_items(", 1)[1]
        body = start.split("async def ", 1)[0]
        self.assertIn("bank.command(move)", body)
        self.assertIn("_insert_guild", body)


class TheAuditTrailAndTheDryRun(unittest.TestCase):
    def routed(self):
        stacks = [green(1), green(2)]
        return route.routes_for(plan_of(stacks), pairs_of(stacks), bank_it)

    def test_an_executed_route_logs_who_deposited_what_where(self):
        out = self.routed()
        lines = bank.lines(out.moves)
        self.assertEqual(2, len(lines))
        for line, name in zip(lines, ("Plate Thing 1", "Plate Thing 2"), strict=True):
            self.assertIn("Ana", line)
            self.assertIn(name, line)

    def test_the_dry_run_lists_every_move_one_for_one_and_moves_nothing(self):
        out = self.routed()
        before = out.moves
        rows = route.dry_run(out)
        self.assertEqual(len(out.moves), len(rows))
        for move, row in zip(out.moves, rows, strict=True):
            self.assertEqual(
                (move.character, move.item, move.guid, bank.command(move)),
                (row[0], row[1], row[2], row[4]),
            )
        self.assertIn("guild bank tab 1", rows[0][3])
        self.assertIs(before, out.moves)
        self.assertEqual((), route.dry_run(route.Routed()))


if __name__ == "__main__":
    unittest.main()

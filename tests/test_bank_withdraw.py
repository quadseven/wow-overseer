"""The vault's stacks to list leave it by a member's own hand.

Measured on the dev realm 2026-10-10 (read-only): Cave's one tab held 98 of
98 slots, 14 of them Linen Cloth (280), and the forecast lists every one.
Rank 0 (the guild master, Grug) may withdraw without limit; ranks 1 to 4 have
`SlotPerDay` 0 on tab 0, so nobody else may take anything. Until
mod-overseer's `bank withdraw-item` nothing could leave a guild bank tab.
"""

import pathlib
import re
import unittest

import bag_pressure
import bankforecast as bf
import guildbank

LINEN = 2589
FIRST_AID = 129
TAILORING = 197
LINEN_ITEM = bf.Item(LINEN, "Linen Cloth", 7, 5, 1, 20, 13)
SCORPID = bf.Item(8401, "Pattern: Tough Scorpid Leggings", 9, 1, 2, 1, 1375, 165, 245)

FAMILY = (
    bf.Member("Grug", 43, {FIRST_AID: 12}, family=True),
    bf.Member("Og", 38, {FIRST_AID: 1, TAILORING: 81}, family=True),
)
CREW = (
    bf.Member("Totta", 23, {FIRST_AID: 56}),
    bf.Member("Glob", 16, {FIRST_AID: 31}),
)


def asks(entry, per_unit, n, count=5):
    return tuple(
        {
            "house": 2,
            "item_entry": entry,
            "item_count": count,
            "bid": per_unit * count * 4 // 5,
            "buyout": per_unit * count,
            "price_paid": 0,
            "outcome": "expired",
        }
        for _ in range(n)
    )


def cave(stacks=None, items=None, held=None):
    """Cave's forecast: fourteen stacks of linen the guild will not eat."""
    return bf.plan(
        stacks
        if stacks is not None
        else tuple(bf.Stack(100 + i, LINEN, 20) for i in range(14)),
        items or {LINEN: LINEN_ITEM},
        FAMILY + CREW,
        held if held is not None else {LINEN: 1114},
        casts=(("Totta", 3275, 120), ("Glob", 3275, 81)),
        history=asks(LINEN, 729, 8),
        house=2,
    )


# Cave's rights, as `read_withdrawers` reads them: one row per member and tab.
def right(name, rank, per_day, rights, used=0, tab=0):
    return {
        "name": name,
        "rank_id": rank,
        "tab": tab,
        "rights": rights,
        "per_day": per_day,
        "used": used,
    }


CAVE_RIGHTS = (
    right("Grug", 0, 4294967295, 255),
    right("Og", 1, 0, 3),
)


class TheCommandIsTheModulesGrammar(unittest.TestCase):
    def test_a_stack_and_its_tab(self):
        self.assertEqual(
            "bank withdraw-item guid:9001 tab:0",
            guildbank.format_item_withdraw(item_guid=9001, tab=0),
        )
        self.assertEqual(
            "bank withdraw-item guid:7 tab:3",
            guildbank.format_item_withdraw(item_guid=7, tab=3),
        )

    def test_a_bad_stack_or_tab_is_refused_here(self):
        for guid, tab in ((0, 0), (-1, 0), ("7", 0), (7, 6), (7, -1), (7, "0")):
            with self.assertRaises(ValueError, msg=(guid, tab)):
                guildbank.format_item_withdraw(item_guid=guid, tab=tab)


class WhoMayTakeFromATab(unittest.TestCase):
    """The core's own rule (Guild::_GetMemberRemainingSlots), read from rows."""

    def test_the_guild_master_takes_without_limit(self):
        (grug,) = bf.withdrawers([right("Grug", 0, 4294967295, 255)], {"Grug": 20})
        self.assertIsNone(grug.left(0))
        self.assertEqual(20, grug.free_slots)

    def test_a_rank_with_no_slots_a_day_takes_nothing(self):
        (og,) = bf.withdrawers([right("Og", 1, 0, 3)], {"Og": 20})
        self.assertEqual(0, og.left(0))

    def test_a_rank_takes_what_is_left_of_its_day(self):
        (vet,) = bf.withdrawers([right("Ugga", 2, 5, 1, used=2)], {"Ugga": 20})
        self.assertEqual(3, vet.left(0))

    def test_without_the_view_right_a_daily_allowance_is_nothing(self):
        (vet,) = bf.withdrawers([right("Ugga", 2, 5, 2)], {"Ugga": 20})
        self.assertEqual(0, vet.left(0))

    def test_a_tab_with_no_row_is_nothing_for_a_rank_below_master(self):
        (vet,) = bf.withdrawers([right("Ugga", 2, 5, 1)], {"Ugga": 20})
        self.assertEqual(0, vet.left(1))

    def test_the_guild_master_takes_from_every_tab(self):
        (grug,) = bf.withdrawers([right("Grug", 0, 0, 0)], {"Grug": 20})
        self.assertIsNone(grug.left(4))


class TheStacksToListLeaveTheVault(unittest.TestCase):
    def plan(self, free, **kw):
        return bf.plan_withdrawals(cave(), bf.withdrawers(CAVE_RIGHTS, free), **kw)

    def test_the_guild_master_takes_one_visits_worth_of_linen(self):
        taken = self.plan({"Grug": 30, "Og": 30})
        self.assertEqual(bf.WITHDRAW_VISIT_STACKS, len(taken))
        self.assertEqual({"Grug"}, {w.character for w in taken})
        self.assertEqual(
            "bank withdraw-item guid:100 tab:0",
            taken[0].command,
        )
        self.assertEqual(
            "Grug takes Linen Cloth x20 (guid 100) from tab 0 to list at 5s 46c each",
            taken[0].line,
        )

    def test_a_member_keeps_its_run_room(self):
        keep = bf.WITHDRAW_KEEP_FREE
        self.assertEqual(2, len(self.plan({"Grug": keep + 2, "Og": 30})))
        self.assertEqual((), self.plan({"Grug": keep, "Og": 30}))

    def test_the_run_room_is_the_campaigns_own_floor(self):
        self.assertEqual(bag_pressure.CAMPAIGN_RESUME_FREE_SLOTS, bf.WITHDRAW_KEEP_FREE)

    def test_nobody_without_the_right_takes_anything(self):
        rights = bf.withdrawers([right("Og", 1, 0, 3)], {"Og": 30})
        self.assertEqual((), bf.plan_withdrawals(cave(), rights))

    def test_an_officer_with_an_allowance_takes_what_is_left_of_it(self):
        rights = bf.withdrawers([right("Og", 1, 5, 3, used=3)], {"Og": 30})
        taken = bf.plan_withdrawals(cave(), rights)
        self.assertEqual(["Og", "Og"], [w.character for w in taken])

    def test_an_entry_still_waiting_to_be_listed_is_not_taken_again(self):
        self.assertEqual((), self.plan({"Grug": 30}, pending=frozenset({LINEN})))

    def test_only_a_stack_the_forecast_lists_is_taken(self):
        # A pattern nobody can learn, with no price in the house's history,
        # is a vendor's: the vault's withdrawals are for the house only.
        forecast = cave(
            stacks=(bf.Stack(500, SCORPID.entry, 1),),
            items={SCORPID.entry: SCORPID},
            held={},
        )
        actions = {d.action for d in forecast.decisions()}
        self.assertNotIn(bf.SELL, actions)
        rights = bf.withdrawers(CAVE_RIGHTS, {"Grug": 30})
        self.assertEqual((), bf.plan_withdrawals(forecast, rights))


class AWithdrawnStackIsTheHousesUntilItIsListed(unittest.TestCase):
    def test_the_guids_come_from_the_applied_rows(self):
        self.assertEqual(
            frozenset({100, 7}),
            bf.withdrawn_guids(
                [
                    "bank withdraw-item guid:100 tab:0",
                    "bank withdraw-item guid:7",
                    "bank deposit-item guid:9",
                    "bank withdraw 500",
                    "bank withdraw-item guid:abc tab:0",
                    None,
                ]
            ),
        )

    def test_every_read_is_a_select(self):
        class Cursor:
            def __init__(self):
                self.seen = []

            def execute(self, sql, args=()):
                self.seen.append(sql % tuple(repr(a) for a in args))

            def fetchall(self):
                return []

        cur = Cursor()
        self.assertEqual((), bf.read_withdrawers(cur, ["Grug", "Og"], {}))
        self.assertEqual(frozenset(), bf.read_withdrawn(cur, ["Grug", "Og"]))
        self.assertEqual(2, len(cur.seen))
        for sql in cur.seen:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
            self.assertNotIn("%s", sql)


class TheBridgeTakesAndThenLists(unittest.TestCase):
    SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
        encoding="utf-8"
    )

    def block(self, signature):
        start = self.SOURCE.index(signature)
        rest = self.SOURCE[start:]
        match = re.search(r"\n(    )?(async def |def )", rest[1:])
        return rest[: match.start() + 1]

    def test_the_guild_bank_pass_plans_and_queues_the_withdrawals(self):
        body = self.block("    async def _guild_bank_once(")
        self.assertIn("_plan_guild_withdrawals", body)
        self.assertIn("_queue_guild_withdrawals(", body)
        self.assertIn("if not any((actions, deposits, items, withdrawals)):", body)

    def test_a_withdrawal_is_queued_only_at_the_vault(self):
        body = self.block("    async def _queue_guild_withdrawals(")
        self.assertIn("travel.spawn_in_reach(", body)
        self.assertIn("_recent_guild_bank_keys", body)
        self.assertIn('"guildbank-withdraw"', body)

    def test_the_retry_window_sees_the_withdraw_rows(self):
        self.assertEqual("bank withdraw-item %", bf.WITHDRAW_LIKE)
        self.assertIn(
            "bankforecast.WITHDRAW_LIKE", self.block("def _recent_guild_bank_keys(")
        )

    def test_clearance_lists_what_was_withdrawn(self):
        body = self.block("    async def _clearance_plan(")
        self.assertIn("_fetch_withdrawn_for_sale", body)

    def test_the_keeper_rule_never_banks_it_again(self):
        self.assertIn("_withdrawn_for_sale_routes(", self.block("def _plan_bank("))

    def test_the_forecast_no_longer_says_it_waits_for_a_verb(self):
        self.assertNotIn("wait for an", self.block("    async def _say_bank_forecast("))


if __name__ == "__main__":
    unittest.main()

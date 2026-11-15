"""A gear piece the routing report takes from the guild bank is withdrawn (#2504).

The bank is a label, not a character: it cannot trade or post, so
`gearroutingexec` left each bank route waiting for "a member to withdraw it"
and nothing did. `bank_withdrawals` names the member (the wearer first) and the
guild bank pass queues the existing `bank withdraw-item` row for it.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bankforecast as bf  # noqa: E402
import gearrouting  # noqa: E402
import gearroutingexec as gx  # noqa: E402
import keep  # noqa: E402
from test_bank_withdraw import CAVE_RIGHTS, right  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BANK = gearrouting.BANK_HOLDER


def route(guid=900, wearer="Og", holder=BANK, item="Sunblade"):
    return gearrouting.Route(
        wearer=wearer,
        holder=holder,
        guid=guid,
        entry=1000 + guid,
        item=item,
        slot="weapon",
        worn="",
        worn_entry=0,
        gain=0.4,
        reason="better",
    )


def report(*routes):
    return gearrouting.Report(routes=tuple(routes))


def bank_row(guid=900, tab=1, guild="Cave"):
    return {"item_guid": guid, "tab": tab, "guild": guild, "holder": BANK}


def takers(rights=CAVE_RIGHTS, free=None):
    return bf.withdrawers(rights, free or {"Grug": 30, "Og": 30})


OG_MAY = (right("Grug", 0, 4294967295, 255), right("Og", 1, 5, 1, tab=1))


class TheBankRoutesAreFound(unittest.TestCase):
    def test_a_bank_route_carries_its_tab_and_guild(self):
        got = gx.bank_routes(
            report(route(900), route(901, holder="Grug")), [bank_row(900, tab=2)]
        )
        self.assertEqual([(900, 2, "Cave")], [(r.guid, t, g) for r, t, g in got])

    def test_a_route_with_no_tab_is_left_out_not_guessed(self):
        row = {"item_guid": 900, "guild": "Cave", "tab": None}
        self.assertEqual((), gx.bank_routes(report(route(900)), [row]))

    def test_a_member_route_is_not_a_bank_route(self):
        self.assertEqual(
            (), gx.bank_routes(report(route(900, holder="Grug")), [bank_row(900)])
        )


class TheWearerTakesItOut(unittest.TestCase):
    def routes(self, *guids):
        return tuple((route(g), 1, "Cave") for g in guids)

    def test_a_bank_route_produces_a_withdraw_step_for_the_wearer(self):
        taken, notes = gx.bank_withdrawals(self.routes(900), takers(OG_MAY))
        self.assertEqual(["Og"], [w.character for w in taken])
        self.assertEqual("bank withdraw-item guid:900 tab:1", taken[0].command)
        self.assertEqual(gx.BANK_SOURCE, taken[0].source)
        self.assertIn("to wear", taken[0].line)
        self.assertEqual((), notes)

    def test_a_wearer_who_may_not_has_it_taken_for_it_by_a_member_who_may(self):
        taken, _ = gx.bank_withdrawals(self.routes(900), takers())
        self.assertEqual(["Grug"], [w.character for w in taken])
        self.assertIn("to hand on to Og", taken[0].line)

    def test_nobody_with_the_right_means_a_note_and_no_step(self):
        no_one = (right("Og", 1, 0, 3),)
        taken, notes = gx.bank_withdrawals(self.routes(900), takers(no_one))
        self.assertEqual((), taken)
        self.assertIn("nobody who may take it from tab 1", notes[0])

    def test_a_member_without_a_free_slot_past_the_floor_takes_nothing(self):
        free = {"Grug": bf.WITHDRAW_KEEP_FREE, "Og": bf.WITHDRAW_KEEP_FREE}
        taken, notes = gx.bank_withdrawals(self.routes(900), takers(OG_MAY, free=free))
        self.assertEqual((), taken)
        self.assertEqual(1, len(notes))

    def test_a_kept_piece_is_never_taken(self):
        kept = keep.Reservations(guids=frozenset({("grug", 900)}), entries=frozenset())
        keeper = (route(900, wearer="Grug"),)
        # `_kept` reads the route's holder: the bank has no reservation, so the
        # reservation of the piece's own entry is what stops it.
        reservations = keep.Reservations(
            guids=frozenset(), entries=frozenset({(BANK.lower(), 1900)})
        )
        taken, notes = gx.bank_withdrawals(
            tuple((r, 1, "Cave") for r in keeper), takers(), kept=reservations
        )
        self.assertEqual((), taken)
        self.assertIn("kept (overseer_keep)", notes[0])
        self.assertIsNotNone(kept)

    def test_the_visit_limit_and_daily_allowance_bound_it(self):
        rights = (right("Og", 1, 2, 1, tab=1),)
        many = self.routes(*range(900, 910))
        taken, _ = gx.bank_withdrawals(many, takers(rights, free={"Og": 40}))
        self.assertEqual(2, len(taken))

    def test_withdrawals_already_planned_are_counted_and_not_named_twice(self):
        planned = [bf.Withdrawal("Og", bf.Stack(900, 1900, 1, 1), "Sunblade", 0)]
        taken, _ = gx.bank_withdrawals(
            self.routes(900, 901), takers(OG_MAY), planned=planned
        )
        self.assertEqual([901], [w.stack.guid for w in taken])

    def test_a_gear_withdrawal_is_not_stock_for_sale(self):
        src = (HERE / "bankforecast.py").read_text(encoding="utf-8")
        sql = src[src.index("WITHDRAWN_SQL = (") : src.index("def read_withdrawers")]
        self.assertIn("'guildbank-gear'", sql)


class TheBridgeSendsTheWithdrawalThroughTheGuildBankPass(unittest.TestCase):
    SRC = (HERE / "bridge.py").read_text(encoding="utf-8")

    def test_the_routing_pass_leaves_its_vault_routes_for_the_guild_bank_pass(self):
        body = self.SRC[
            self.SRC.index("    async def _gear_routing_once(") : self.SRC.index(
                "    async def _gear_routing_walks("
            )
        ]
        self.assertIn("self._gear_bank_routes = await self._gear_bank_requests(", body)
        helper = self.SRC[
            self.SRC.index("    async def _gear_bank_requests(") : self.SRC.index(
                "    def _gear_bank_for("
            )
        ]
        # An operator hold stands the wearer's family down for this writer.
        self.assertIn("self._operator_held(", helper)
        self.assertIn('"gear routing"', helper)

    def test_the_guild_bank_pass_plans_them_with_the_other_withdrawals(self):
        self.assertIn(
            "_plan_guild_withdrawals, names, self._gear_bank_for(names))", self.SRC
        )
        body = self.SRC[
            self.SRC.index("def _plan_guild_withdrawals(") : self.SRC.index(
                "def _clearance_sales("
            )
        ]
        self.assertIn("gearroutingexec.bank_withdrawals(", body)
        self.assertIn("and not gear_routes", body)

    def test_the_withdrawal_rides_the_town_slot_walk_and_range_gate(self):
        """`_queue_guild_withdrawals` is the one writer: it writes only for a
        member stood at the vault, through the leader's town slot claim."""
        body = self.SRC[self.SRC.index("    async def _queue_guild_withdrawals(") :][
            :2500
        ]
        self.assertIn("travel.spawn_in_reach", body)
        self.assertIn('getattr(withdrawal, "source"', body)

    def test_the_audit_line_names_who_takes_which_piece(self):
        taken, _ = gx.bank_withdrawals(((route(900), 1, "Cave"),), takers(OG_MAY))
        self.assertEqual(
            "Og takes Sunblade (guid 900) from tab 1 to wear", taken[0].line
        )


if __name__ == "__main__":
    unittest.main()

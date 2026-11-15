"""The loot policy's verdicts reach a destination, not only a refusal.

`lootpolicy` suppresses the vendor sale. These tests follow the same item
through the route that is already live and show it arrives: an upgrade is
written as a hand-over to the guildmate it upgrades (gear routing), uncommon
gear of a raid seat is deposited at a banker (the seat bag loop), a family
head's goes to the guild bank tab or the auction house (the item plan), and a
bound piece nobody can use becomes a disenchant row.
"""

from __future__ import annotations

import unittest
from unittest import mock

import equipscore
import gearrouting as gr
import gearroutingexec as gx
import itemplan
import lootpolicy
import seatbags
import test_gearrouting as fx
import test_guild_seat_bags as seat_fx
import test_itemplan as plan_fx
import test_itemplan_vendor as vendor_fx
from itemplan import AUCTION, BANK_PERSONAL, GUILD_BANK, SELL_VENDOR
from test_guildjobs import only_step, plan
from test_loot_policy import EVERY_CLASS, UNWEARABLE, piece


def policy_row(gear_row, holder_class):
    """The facts the bridge reads for a carried piece, from a gear row."""
    return {
        "item_guid": gear_row["item_guid"],
        "entry": gear_row["entry"],
        "name": gear_row["name"],
        "quality": gear_row["quality"],
        "required_level": gear_row["required_level"],
        "item_class": gear_row["item_class"],
        "subclass": gear_row["item_subclass"],
        "inventory_type": gear_row["inventory_type"],
        "allowable_class": gear_row["allowable_class"],
        "instance_flags": gear_row["instance_flags"],
        "bonding": gear_row["bonding"],
        "holder_class": holder_class,
        "disenchant_id": 60,
    }


class Recorder:
    def __init__(self):
        self.rows = []

    def __call__(self, row):
        self.rows.append(row)
        return 1


class AnUpgradeIsHandedToTheGuildmateItUpgrades(unittest.TestCase):
    def test_the_verdict_and_the_gear_routing_name_the_same_piece_and_wearer(self):
        wearers = [
            fx.tank("Grug"),
            fx.member("Bork", fx.ROGUE, 43, skills=fx.ROGUE_SKILLS),
        ]
        carried = fx.symbolic_breastplate("Bork")
        gear = [fx.old_breastplate("Grug"), carried]
        verdict = lootpolicy.decide(
            policy_row(carried, fx.ROGUE),
            frozenset({fx.WARRIOR, fx.ROGUE}),
            upgrade=lambda row: equipscore.wanted_by(carried, wearers, gear),
        )
        self.assertEqual(verdict.route, lootpolicy.UPGRADE)
        self.assertEqual(verdict.wanted_by, ("Grug",))

        report = gr.plan(wearers, gear)
        (route,) = report.routes
        self.assertEqual((route.holder, route.wearer), ("Bork", "Grug"))
        self.assertEqual(route.guid, carried["item_guid"])

        near = {"map_id": 0, "pos_x": 10.0, "pos_y": 10.0, "instance_id": 0}
        world = gx.World(
            carried={("Bork", carried["item_guid"])},
            positions={"Bork": near, "Grug": near},
            free_slots={"Grug": 3},
        )
        rec = Recorder()
        result = gx.execute(report, world, rec)
        self.assertEqual([s.status for s in result.steps], [gx.WRITTEN])
        (written,) = rec.rows
        self.assertEqual(written.holder, "Bork")
        self.assertIn(written.taker, verdict.wanted_by)
        self.assertEqual(written.command, "guid:%d" % carried["item_guid"])


class AGreenIsBankedByASeat(unittest.TestCase):
    """A seat's uncommon gear is no longer sold: it is deposited at a banker."""

    def setUp(self):
        rows, gear, _worn, _free = vendor_fx.green_cloak()
        for r in rows + gear:
            r["holder"] = seat_fx.SEAT
        self.rows, self.gear = rows, gear
        self.guid = rows[0]["item_guid"]

    def relieve(self):
        extras = seat_fx.extras_for(self.rows)

        def read(names):
            return ("Cave", self.rows, {seat_fx.SEAT: 2}, extras, self.gear, (), ())

        return seatbags.relieve(
            [seat_fx.seat()],
            read,
            lambda maps: [seat_fx.BANKER],
            500,
            0.0,
            seatbags.Memo(),
            {"ITEMPLAN_SELL_VENDOR": "on"},
        )

    def test_the_plan_banks_it_and_the_step_deposits_it(self):
        out, _lines = self.relieve()
        self.assertEqual([c.guid for c in out[0].plan_sales], [])
        self.assertEqual([c.guid for c in out[0].plan_bank], [self.guid])
        step = only_step(plan([out[0]]), seat_fx.SEAT)
        self.assertEqual(step.action, "seat-bank")
        self.assertEqual(
            [(r.kind, r.command) for r in step.rows],
            [("bank", "deposit guid:%d" % self.guid)],
        )

    def test_the_bridge_writes_that_deposit_row(self):
        from test_epic_kept import WriterGateTest

        gate = WriterGateTest("test_an_ordinary_sale_is_untouched")
        gate.setUp()
        self.addCleanup(gate.doCleanups)
        out, _ = self.relieve()
        step = only_step(plan([out[0]]), seat_fx.SEAT)
        wrote = gate.bridge._insert_corps_row(seat_fx.SEAT, step.rows[0])
        self.assertTrue(wrote)
        self.assertEqual(len(gate.inserts()), 1)
        self.assertIn("bank", gate.inserts()[0][1])


class AFamilyHeadsGreenGoesToTheBankOrTheHouse(unittest.TestCase):
    def gear(self, quality=2, entry=80):
        return plan_fx.stack(
            entry=entry,
            item_class=4,
            subclass=0,
            quality=quality,
            sell=900,
            bind=2,
            req_level=20,
            item_level=25,
        )

    def test_a_listing_beats_the_vendor_when_the_market_pays(self):
        ring = self.gear()
        ctx = itemplan.Context(market={80: (40000, 5)}, fire_gear=frozenset())
        d = plan_fx.one([ring], [plan_fx.member()], ring, ctx)
        self.assertEqual(d.route, AUCTION)

    def test_otherwise_the_guild_bank_tab_or_the_personal_bank(self):
        ring = self.gear()
        d = plan_fx.one([ring], [plan_fx.member()], ring)
        self.assertIn(d.route, (GUILD_BANK, BANK_PERSONAL))
        self.assertNotEqual(d.route, SELL_VENDOR)

    def test_a_blue_and_an_epic_are_never_planned_for_the_vendor(self):
        for quality in (3, 4):
            thing = self.gear(quality=quality, entry=90 + quality)
            d = plan_fx.one([thing], [plan_fx.member()], thing)
            self.assertNotEqual(d.route, SELL_VENDOR)


class ABoundPieceNobodyCanUseIsDisenchanted(unittest.TestCase):
    def seam(self):
        from test_itemplan_disenchant import TheBridgeSeam

        seam = TheBridgeSeam("test_it_writes_one_disenchant_row_for_the_holder")
        seam.setUp()
        return seam

    def test_the_disenchant_carry_out_writes_the_row_the_policy_allows(self):
        seam = self.seam()
        b = seam.bridge
        row = piece(item_guid=77, instance_flags=1, quality=2, **UNWEARABLE)
        cursor = mock.MagicMock()
        cursor.fetchone.return_value = {"n": 0}
        cursor.lastrowid = 9
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        with (
            mock.patch.object(b._KEEP, "blocks", return_value=False),
            mock.patch.object(b, "_fetch_epic_facts", return_value=[row]),
            mock.patch.object(b, "_guild_classes", return_value=EVERY_CLASS),
            mock.patch.object(b, "_rare_wanted_by", return_value=()),
            mock.patch.object(b, "_disenchant_facts", return_value=seam.facts),
            mock.patch.object(b, "_family_enchanters", return_value={"Og": 60}),
            mock.patch.object(b, "_connect", return_value=conn),
        ):
            wrote = b._carry_out_itemplan_disenchant((seam.job,))
        self.assertEqual(wrote, 1)
        (call,) = seam.inserts(cursor)
        self.assertEqual(call.args[1][2], "disenchant")

    def test_the_same_job_for_an_upgrade_writes_nothing(self):
        seam = self.seam()
        b = seam.bridge
        with (
            mock.patch.object(b._KEEP, "blocks", return_value=False),
            mock.patch.object(
                b, "_fetch_epic_facts", return_value=[piece(item_guid=77)]
            ),
            mock.patch.object(b, "_guild_classes", return_value=EVERY_CLASS),
            mock.patch.object(b, "_rare_wanted_by", return_value=("Zrog",)),
        ):
            self.assertEqual(b._carry_out_itemplan_disenchant((seam.job,)), 0)


if __name__ == "__main__":
    unittest.main()

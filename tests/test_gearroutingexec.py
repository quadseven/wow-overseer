"""The gear-routing executor (gearroutingexec.py): the report's routes, written
as the same guild hand-over rows `gear.route_plan` produces.

It adds no judge. The routes are gearrouting's, taken unchanged; the only
questions it asks are the world's: is the piece still where the report found
it, and can the holder reach the wearer. A stale route is skipped and said so.
"""

import unittest

import gearrouting as gr
import gearroutingexec as gx
import guildroute
import test_gearrouting as fixtures

NEAR = {"map_id": 0, "pos_x": 10.0, "pos_y": 10.0, "instance_id": 0}
FAR = {"map_id": 1, "pos_x": 900.0, "pos_y": 900.0, "instance_id": 0}


def route(holder="Oz", wearer="Grug", guid=501, gain=0.4, **kw):
    return gr.Route(
        wearer=wearer,
        holder=holder,
        guid=guid,
        entry=7001,
        item=kw.pop("item", "Hauberk of Test"),
        slot="chest",
        worn="Rags",
        worn_entry=1,
        gain=gain,
        reason="beats the worn piece",
    )


def world(**kw):
    base = dict(
        carried={("Oz", 501)},
        positions={"Oz": NEAR, "Grug": NEAR},
        at_mailbox=(),
        free_slots={"Grug": 3},
    )
    base.update(kw)
    return gx.World(**base)


class Recorder:
    def __init__(self):
        self.rows = []

    def __call__(self, row):
        self.rows.append(row)
        return 1


class Execute(unittest.TestCase):
    def test_a_proposed_route_is_written_as_a_trade_row(self):
        report = gr.Report(routes=(route(),))
        rec = Recorder()
        result = gx.execute(report, world(), rec)
        self.assertEqual(len(rec.rows), 1)
        row = rec.rows[0]
        self.assertEqual(row.holder, "Oz")
        self.assertEqual(row.taker, "Grug")
        self.assertEqual(row.verb, "trade")
        self.assertEqual(row.command, "guid:501")
        self.assertEqual(guildroute.source_for(row.gain), "guildroute:40")
        self.assertEqual([s.status for s in result.steps], [gx.WRITTEN])

    def test_the_audit_trail_names_giver_receiver_and_piece(self):
        report = gr.Report(routes=(route(),))
        result = gx.execute(report, world(), Recorder())
        said = result.steps[0].said
        for word in ("Oz", "Grug", "Hauberk of Test"):
            self.assertIn(word, said)

    def test_a_stale_route_is_skipped_and_said(self):
        report = gr.Report(routes=(route(),))
        rec = Recorder()
        result = gx.execute(report, world(carried=set()), rec)
        self.assertEqual(rec.rows, [])
        self.assertEqual(result.steps[0].status, gx.STALE)
        self.assertIn("no longer", result.steps[0].why)

    def test_a_route_out_of_reach_waits_rather_than_forces(self):
        report = gr.Report(routes=(route(),))
        rec = Recorder()
        result = gx.execute(report, world(positions={"Oz": NEAR, "Grug": FAR}), rec)
        self.assertEqual(rec.rows, [])
        self.assertEqual(result.steps[0].status, gx.WAITING)
        self.assertTrue(result.steps[0].why)

    def test_the_guild_bank_is_not_a_holder_that_can_trade(self):
        report = gr.Report(routes=(route(holder=gr.BANK_HOLDER),))
        rec = Recorder()
        result = gx.execute(report, world(carried={(gr.BANK_HOLDER, 501)}), rec)
        self.assertEqual(rec.rows, [])
        self.assertEqual(result.steps[0].status, gx.WAITING)
        self.assertIn("bank", result.steps[0].why)

    def test_dry_run_lists_every_route_in_report_order_and_writes_nothing(self):
        routes = (route(guid=501), route(guid=502, wearer="Zug"), route(guid=503))
        report = gr.Report(routes=routes)
        rec = Recorder()
        w = world(
            carried={("Oz", 501), ("Oz", 502)},
            positions={"Oz": NEAR, "Grug": NEAR, "Zug": NEAR},
            free_slots={"Grug": 3, "Zug": 3},
        )
        dry = gx.execute(report, w, rec, dry_run=True)
        self.assertEqual(rec.rows, [])
        self.assertEqual([s.route for s in dry.steps], list(routes))
        self.assertEqual(
            [s.status for s in dry.steps], [gx.WOULD_WRITE, gx.WOULD_WRITE, gx.STALE]
        )
        live = gx.execute(report, w, Recorder())
        self.assertEqual(
            [s.route for s in live.steps if s.status == gx.WRITTEN],
            [s.route for s in dry.steps if s.status == gx.WOULD_WRITE],
        )

    def test_a_row_the_writer_declines_is_not_counted_as_written(self):
        report = gr.Report(routes=(route(),))
        result = gx.execute(report, world(), lambda row: 0)
        self.assertEqual(result.steps[0].status, gx.DECLINED)
        self.assertEqual(result.written, 0)

    def test_an_empty_report_executes_to_nothing(self):
        result = gx.execute(gr.Report(), world(), Recorder())
        self.assertEqual(result.steps, ())


class TheAdapterBuildsTheRoute(unittest.TestCase):
    def test_guild_route_builds_the_shape_the_writer_takes(self):
        import bag_pressure

        built = bag_pressure.guild_route(
            "Oz", "Grug", 501, 7001, "Hauberk", 40, True, "why"
        )
        self.assertEqual((built.holder, built.taker, built.guid), ("Oz", "Grug", 501))
        self.assertEqual(built.command if not built.verb else "", "guid:501")
        self.assertEqual(guildroute.source_for(built.gain), "guildroute:40")
        self.assertTrue(built.family)


class FromTheRealReport(unittest.TestCase):
    """The executor fed the real routing pass, not a hand-built report."""

    def _report(self, **kw):
        rows = [
            fixtures.tank("Grug"),
            fixtures.member("Bork", fixtures.ROGUE, 43, skills=fixtures.ROGUE_SKILLS),
        ]
        gear = [
            fixtures.old_breastplate("Grug"),
            fixtures.symbolic_breastplate("Bork", **kw),
        ]
        return gr.plan(rows, gear)

    def test_the_proposed_route_executes_unchanged(self):
        report = self._report()
        guid = report.routes[0].guid
        rec = Recorder()
        result = gx.execute(
            report,
            world(carried={("Bork", guid)}, positions={"Bork": NEAR, "Grug": NEAR}),
            rec,
        )
        self.assertEqual([s.route for s in result.steps], list(report.routes))
        self.assertEqual(rec.rows[0].command, "guid:%d" % guid)
        self.assertEqual((rec.rows[0].holder, rec.rows[0].taker), ("Bork", "Grug"))

    def test_a_soulbound_piece_never_reaches_the_executor(self):
        report = self._report(bonding=2, instance_flags=1)
        rec = Recorder()
        result = gx.execute(report, world(), rec)
        self.assertEqual(result.steps, ())
        self.assertEqual(rec.rows, [])


if __name__ == "__main__":
    unittest.main()

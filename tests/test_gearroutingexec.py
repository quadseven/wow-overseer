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


class TheDryRunRead(unittest.TestCase):
    """The read-only view the site serves: what WOULD be written."""

    def _rows(self):
        report = gr.Report(routes=(route(guid=501), route(guid=502)))
        gear = [
            {"holder": "Oz", "item_guid": 501, "equipment_slot": None},
            {"holder": "Oz", "item_guid": 777, "equipment_slot": 4},
        ]
        positions = [
            {"name": "Oz", "map_id": 0, "pos_x": 1.0, "pos_y": 1.0, "instance_id": 0},
            {"name": "Grug", "map_id": 0, "pos_x": 2.0, "pos_y": 2.0, "instance_id": 0},
        ]
        room = [
            {
                "name": "Grug",
                "bag_slot": 0,
                "size": 16,
                "bag_class": 1,
                "bag_subclass": 0,
                "used": 10,
            },
        ]
        return report, gear, positions, room

    def test_the_world_carries_bag_items_only(self):
        _report, gear, positions, room = self._rows()
        w = gx.world_from_rows(gear, positions, room, family=("Grug",))
        self.assertEqual(set(w.carried), {("Oz", 501)})
        self.assertEqual(set(w.positions), {"Oz", "Grug"})
        self.assertGreater(w.free_slots["Grug"], 0)
        self.assertEqual(w.at_mailbox, ())

    def test_the_view_has_one_line_per_route_with_status_and_why(self):
        report, gear, positions, room = self._rows()
        w = gx.world_from_rows(gear, positions, room, family=("Grug",))
        view = gx.dry_run_view(report, w)
        self.assertTrue(view["dry_run"])
        self.assertEqual(len(view["steps"]), 2)
        first, second = view["steps"]
        self.assertEqual(first["status"], gx.WOULD_WRITE)
        self.assertEqual(first["verb"], "trade")
        self.assertEqual((first["holder"], first["wearer"]), ("Oz", "Grug"))
        self.assertEqual(second["status"], gx.STALE)
        self.assertTrue(second["why"])
        self.assertEqual(len(view["lines"]), 2)

    def test_the_view_never_calls_a_writer(self):
        report, gear, positions, room = self._rows()
        w = gx.world_from_rows(gear, positions, room)
        calls = []
        orig = gx.execute
        gx.execute = lambda *a, **k: calls.append(k.get("dry_run")) or orig(*a, **k)
        try:
            gx.dry_run_view(report, w)
        finally:
            gx.execute = orig
        self.assertEqual(calls, [True])


class TheSiteServesTheDryRun(unittest.TestCase):
    def test_the_routing_read_carries_the_execution_view(self):
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[1] / "map_server.py").read_text(
            encoding="utf-8"
        )
        body = src[src.index("def _fetch_guild_routing") :]
        body = body[: body.index("\ndef _fetch_armory")]
        self.assertIn("gearroutingexec.dry_run_view(", body)
        self.assertNotIn("INSERT INTO", body.upper())
        self.assertNotIn("overseer_command", body)


class TheWorldIsWhole(unittest.TestCase):
    def test_members_to_read_include_holders_who_are_not_wearers(self):
        report = gr.Report(
            routes=(
                route(holder="Bork", wearer="Grug"),
                route(holder=gr.BANK_HOLDER, wearer="Zug", guid=502),
            )
        )
        got = gx.members_to_read(report, ["Grug", "Zug"])
        self.assertEqual(got, ["Bork", "Grug", "Zug"])

    def test_the_bank_is_never_a_member_to_read(self):
        report = gr.Report(routes=(route(holder=gr.BANK_HOLDER),))
        self.assertNotIn(gr.BANK_HOLDER, gx.members_to_read(report, []))

    def test_the_site_reads_holders_too(self):
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[1] / "map_server.py").read_text(
            encoding="utf-8"
        )
        body = src[src.index("def _fetch_guild_routing") :]
        self.assertIn("gearroutingexec.members_to_read(", body)


if __name__ == "__main__":
    unittest.main()

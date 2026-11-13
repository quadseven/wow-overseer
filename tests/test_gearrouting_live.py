"""The gear routing executor, live (#2136): the report's routes written by a
bridge pass, so a routed piece actually changes hands.

The executor itself (gearroutingexec.execute) is tested in
test_gearroutingexec. These pin what the live pass adds: an `overseer_keep`
reservation is never moved, a pass writes at most its cap, a letter goes
only from a holder standing at a mailbox to a family wearer, each hand-off
decision is one plain log line, and the bridge runs the pass through the
existing hand-over writer, never a give.
"""

import pathlib
import unittest

import gearrouting as gr
import gearroutingexec as gx
import keep

HERE = pathlib.Path(__file__).resolve().parents[1]

NEAR = {"map_id": 0, "pos_x": 10.0, "pos_y": 10.0, "instance_id": 0}
FAR = {"map_id": 0, "pos_x": 900.0, "pos_y": 900.0, "instance_id": 0}


def route(holder="Oz", wearer="Grug", guid=501, entry=7001, item="Hauberk of Test"):
    return gr.Route(
        wearer=wearer,
        holder=holder,
        guid=guid,
        entry=entry,
        item=item,
        slot="chest",
        worn="Rags",
        worn_entry=1,
        gain=0.4,
        reason="beats the worn piece",
    )


def world(**kw):
    base = dict(
        carried={("Oz", 501), ("Oz", 502), ("Oz", 503)},
        positions={"Oz": NEAR, "Grug": NEAR, "Zug": NEAR, "Og": NEAR},
        at_mailbox=(),
        free_slots={"Grug": 3, "Zug": 3, "Og": 3},
    )
    base.update(kw)
    return gx.World(**base)


class Recorder:
    def __init__(self):
        self.rows = []

    def __call__(self, row):
        self.rows.append(row)
        return 1


def reserved(*rows):
    return keep.from_rows(rows)


class AKeptPieceNeverMoves(unittest.TestCase):
    def test_a_keep_on_the_instance_stops_the_route(self):
        report = gr.Report(routes=(route(),))
        rec = Recorder()
        kept = reserved({"character_name": "Oz", "item_entry": 7001, "item_guid": 501})
        result = gx.execute(report, world(kept=kept), rec)
        self.assertEqual(rec.rows, [])
        self.assertEqual(result.steps[0].status, gx.KEPT)
        self.assertIn("overseer_keep", result.steps[0].why)

    def test_an_entry_wide_keep_stops_it_too_whatever_the_name_case(self):
        report = gr.Report(routes=(route(),))
        rec = Recorder()
        kept = reserved({"character_name": "oz", "item_entry": 7001, "item_guid": 0})
        result = gx.execute(report, world(kept=kept), rec)
        self.assertEqual(rec.rows, [])
        self.assertEqual(result.steps[0].status, gx.KEPT)

    def test_a_keep_on_somebody_else_does_not_stop_it(self):
        report = gr.Report(routes=(route(),))
        rec = Recorder()
        kept = reserved(
            {"character_name": "Grug", "item_entry": 7001, "item_guid": 501}
        )
        result = gx.execute(report, world(kept=kept), rec)
        self.assertEqual(len(rec.rows), 1)
        self.assertEqual(result.steps[0].status, gx.WRITTEN)

    def test_the_dry_run_view_says_kept_as_well(self):
        report = gr.Report(routes=(route(),))
        kept = reserved({"character_name": "Oz", "item_entry": 7001, "item_guid": 501})
        view = gx.dry_run_view(report, world(kept=kept))
        self.assertEqual(view["steps"][0]["status"], gx.KEPT)
        self.assertEqual(view["would_write"], 0)


class APassWritesAtMostItsCap(unittest.TestCase):
    def routes(self):
        return gr.Report(
            routes=(
                route(guid=501, wearer="Grug"),
                route(guid=502, wearer="Zug"),
                route(guid=503, wearer="Og"),
            )
        )

    def test_the_cap_bounds_the_rows_and_the_rest_wait_in_report_order(self):
        rec = Recorder()
        result = gx.execute(self.routes(), world(), rec, per_pass=1)
        self.assertEqual([r.guid for r in rec.rows], [501])
        self.assertEqual(
            [s.status for s in result.steps], [gx.WRITTEN, gx.WAITING, gx.WAITING]
        )
        self.assertIn("limit", result.steps[1].why)

    def test_a_cap_of_zero_writes_nothing(self):
        rec = Recorder()
        result = gx.execute(self.routes(), world(), rec, per_pass=0)
        self.assertEqual(rec.rows, [])
        self.assertEqual(result.written, 0)

    def test_no_cap_is_the_old_behaviour(self):
        rec = Recorder()
        gx.execute(self.routes(), world(), rec)
        self.assertEqual(len(rec.rows), 3)


class ALetterGoesFromAMailbox(unittest.TestCase):
    def test_a_holder_at_a_mailbox_posts_to_a_family_wearer_far_away(self):
        report = gr.Report(routes=(route(),))
        rec = Recorder()
        w = world(
            positions={"Oz": NEAR, "Grug": FAR},
            at_mailbox=("Oz",),
            family={"Grug"},
        )
        result = gx.execute(report, w, rec)
        self.assertEqual(len(rec.rows), 1)
        self.assertEqual(rec.rows[0].verb, "mail")
        self.assertTrue(rec.rows[0].command.startswith("send item:501"))
        self.assertEqual(result.steps[0].status, gx.WRITTEN)

    def test_a_far_wearer_off_the_roster_waits_for_a_trade(self):
        report = gr.Report(routes=(route(),))
        rec = Recorder()
        w = world(positions={"Oz": NEAR, "Grug": FAR}, at_mailbox=("Oz",), family=())
        result = gx.execute(report, w, rec)
        self.assertEqual(rec.rows, [])
        self.assertEqual(result.steps[0].status, gx.WAITING)


class AQueuedHandOffIsNotAskedAgain(unittest.TestCase):
    def test_a_piece_already_queued_waits_and_leaves_the_cap_to_the_next(self):
        report = gr.Report(routes=(route(guid=501), route(guid=502, wearer="Zug")))
        rec = Recorder()
        result = gx.execute(report, world(queued={("Oz", 501)}), rec, per_pass=1)
        self.assertEqual([r.guid for r in rec.rows], [502])
        self.assertEqual(result.steps[0].status, gx.WAITING)
        self.assertIn("already", result.steps[0].why)

    def test_queued_reads_the_guids_the_retry_window_names(self):
        seen = {
            ("Oz", "guid:501"),
            ("Og", "send item:77 subject:Helm"),
            ("Zug", "hello"),
        }
        self.assertEqual(gx.queued(seen), frozenset({("Oz", 501), ("Og", 77)}))


class OneLinePerDecision(unittest.TestCase):
    def test_each_hand_off_decision_is_one_plain_line(self):
        report = gr.Report(
            routes=(
                route(guid=501, wearer="Grug"),
                route(guid=502, wearer="Zug", item="Kept Blade"),
                route(guid=509, wearer="Og", item="Gone Helm"),
            )
        )
        kept = reserved({"character_name": "Oz", "item_entry": 0, "item_guid": 502})
        result = gx.execute(report, world(kept=kept), Recorder())
        lines = gx.decision_lines(result)
        self.assertEqual(len(lines), 2)
        self.assertTrue(
            lines[0].startswith("written: Oz -> Grug by trade, Hauberk of Test")
        )
        self.assertTrue(lines[1].startswith("kept: Oz -> Zug, Kept Blade"))
        for line in lines:
            self.assertNotIn("\n", line)

    def test_the_summary_counts_every_status(self):
        report = gr.Report(routes=(route(guid=501), route(guid=509, wearer="Zug")))
        result = gx.execute(report, world(), Recorder())
        self.assertEqual(gx.summary(result), "1 written, 1 stale of 2 route(s)")


class TheBridgeRunsThePass(unittest.TestCase):
    def bridge(self):
        return (HERE / "bridge.py").read_text(encoding="utf-8")

    def body(self, name):
        text = self.bridge()
        start = text.index(name)
        end = text.find("\n    async def ", start + 1)
        return text[start:end]

    def test_the_pass_reads_the_report_and_writes_through_the_hand_over_writer(self):
        body = self.body("async def _gear_routing_once(")
        for needle in (
            "_read_gear_routing",
            "gearrouting.plan(",
            "gearroutingexec.execute, report, world, _insert_route",
            "_insert_route",
            "_recent_route_keys",
            "gearroutingexec.queued(",
            "_holders_at_mailbox",
            "_fetch_free_slots",
            "_KEEP.now",
            "per_pass=GEAR_ROUTING_PER_PASS",
            "gearroutingexec.decision_lines(",
        ):
            self.assertIn(needle, body)
        self.assertNotIn("'give'", body)
        self.assertNotIn('"give"', body)

    def test_the_report_is_read_through_the_shared_routing_read(self):
        text = self.bridge()
        helper = text[text.index("def _read_gear_routing(") :]
        helper = helper[: helper.index("\n\n\ndef ")]
        self.assertIn("gearroutingread.read(rd, names)", helper)

    def test_the_guild_share_loop_runs_it_guarded(self):
        loop = self.body("async def _guild_share_loop(")
        self.assertIn("await self._gear_routing_once()", loop)
        at = loop.index("await self._gear_routing_once()")
        self.assertIn("try:", loop[at - 80 : at])

    def test_the_cap_has_a_default(self):
        line = (
            'GEAR_ROUTING_PER_PASS = int(os.environ.get("GEAR_ROUTING_PER_PASS", "10"))'
        )
        self.assertTrue(line in self.bridge(), line)


if __name__ == "__main__":
    unittest.main()

"""A routed hand-off to a member with full bags (#2245).

The routing executor checked the wearer's bag room and, when there was none,
left the move waiting: nothing planned room first, the wait carried no reason
a reader could filter on, and nothing ended it. These pin the three halves:

  * a full wearer beside the holder gives its cheapest grey to the holder
    first (the make-room step gear.deliverable already takes, #550), ordered
    ahead of the move;
  * a move blocked for room says so as data, and the dry run returns it;
  * a move blocked for room past the bound is planned again without that
    wearer, with the reason recorded, until the wearer's bags have room.
"""

import unittest

import bag_pressure
import gear
import gearroomwait as rw
import gearrouting as gr
import gearroutingexec as gx
import test_gearrouting as fixtures
from test_gearroutingexec import NEAR, FAR, route, world

GREY = gear.Freeable(guid=9, entry=77, name="Cracked Bone")


class Tape:
    """Both writers on one tape, so the order of the rows is the assertion."""

    def __init__(self, free_answer=1):
        self.rows = []
        self.free_answer = free_answer

    def move(self, row):
        self.rows.append(("move", row))
        return 1

    def free(self, row):
        self.rows.append(("free", row))
        return self.free_answer


def full(**kw):
    base = dict(free_slots={"Grug": 0, "Oz": 2}, freeables={"Grug": (GREY,)})
    base.update(kw)
    return world(**base)


class MakeRoomAheadOfTheMove(unittest.TestCase):
    def test_a_full_wearer_gives_its_cheapest_grey_before_the_move(self):
        tape = Tape()
        report = gr.Report(routes=(route(),))
        result = gx.execute(report, full(), tape.move, insert_free=tape.free)
        self.assertEqual([kind for kind, _row in tape.rows], ["free", "move"])
        free, move = tape.rows[0][1], tape.rows[1][1]
        self.assertEqual((free.holder, free.taker), ("Grug", "Oz"))
        self.assertEqual(free.command, "guid:9")
        self.assertEqual(free.verb, "give")
        self.assertEqual((move.holder, move.taker, move.verb), ("Oz", "Grug", "trade"))
        step = result.steps[0]
        self.assertEqual(step.status, gx.WRITTEN)
        self.assertEqual(step.frees, (free,))
        self.assertEqual(step.blocked, "")

    def test_the_step_that_cannot_be_written_holds_its_move(self):
        tape = Tape(free_answer=0)
        report = gr.Report(routes=(route(),))
        result = gx.execute(report, full(), tape.move, insert_free=tape.free)
        self.assertEqual([kind for kind, _row in tape.rows], ["free"])
        step = result.steps[0]
        self.assertEqual(step.status, gx.WAITING)
        self.assertEqual(step.blocked, gx.BLOCKED_ROOM)
        self.assertIn("make-room", step.why)

    def test_a_declined_move_still_reads_as_its_row(self):
        """The decision line of a declined row is the row's own, with the
        make-room step that was written ahead of it."""
        tape = Tape()
        report = gr.Report(routes=(route(),))
        result = gx.execute(report, full(), lambda _row: 0, insert_free=tape.free)
        step = result.steps[0]
        self.assertEqual(step.status, gx.DECLINED)
        self.assertIn("Cracked Bone", step.said)
        self.assertIn("by trade", step.said)

    def test_no_writer_for_the_step_means_no_step_and_no_move(self):
        """A caller that cannot write the give is not handed a trade that
        needs it: the move waits for room as it did."""
        tape = Tape()
        report = gr.Report(routes=(route(),))
        result = gx.execute(report, full(), tape.move)
        self.assertEqual(tape.rows, [])
        self.assertEqual(result.steps[0].blocked, gx.BLOCKED_ROOM)

    def test_a_wearer_with_room_is_asked_for_no_grey(self):
        tape = Tape()
        report = gr.Report(routes=(route(),))
        w = full(free_slots={"Grug": 1, "Oz": 2})
        gx.execute(report, w, tape.move, insert_free=tape.free)
        self.assertEqual([kind for kind, _row in tape.rows], ["move"])

    def test_one_grey_is_promised_once(self):
        """Two pieces for one full wearer: a receiver takes one item a pass,
        and its one grey frees one slot."""
        tape = Tape()
        report = gr.Report(routes=(route(guid=501), route(guid=502)))
        w = full(carried={("Oz", 501), ("Oz", 502)})
        gx.execute(report, w, tape.move, insert_free=tape.free)
        self.assertEqual([kind for kind, _row in tape.rows], ["free", "move"])

    def test_the_dry_run_lists_the_step_and_writes_nothing(self):
        report = gr.Report(routes=(route(),))
        view = gx.dry_run_view(report, full())
        step = view["steps"][0]
        self.assertEqual(step["status"], gx.WOULD_WRITE)
        self.assertEqual(
            step["frees"],
            [{"holder": "Grug", "taker": "Oz", "guid": 9, "item": "Cracked Bone"}],
        )
        self.assertEqual(step["blocked"], "")
        self.assertIn("frees a slot", view["lines"][0])
        self.assertLess(
            view["lines"][0].index("Cracked Bone"),
            view["lines"][0].index("Hauberk of Test"),
        )


class BlockedForRoomIsAReason(unittest.TestCase):
    def blocked(self, **kw):
        report = gr.Report(routes=(route(),))
        tape = Tape()
        result = gx.execute(report, full(**kw), tape.move, insert_free=tape.free)
        self.assertEqual(tape.rows, [])
        return result.steps[0]

    def test_no_grey_to_give(self):
        step = self.blocked(freeables={})
        self.assertEqual(step.status, gx.WAITING)
        self.assertEqual(step.blocked, gx.BLOCKED_ROOM)
        self.assertIn("Grug has no free bag slot", step.why)
        self.assertIn("carries no grey a vendor would buy", step.why)

    def test_the_holder_has_no_slot_for_the_grey(self):
        step = self.blocked(free_slots={"Grug": 0, "Oz": 0})
        self.assertEqual(step.blocked, gx.BLOCKED_ROOM)
        self.assertIn("Oz has no free slot to take a junk stack", step.why)

    def test_nobody_asked_for_greys_reads_as_before(self):
        """`freeables=None` is nobody asked: the note is the old one."""
        step = self.blocked(freeables=None)
        self.assertEqual(step.blocked, gx.BLOCKED_ROOM)
        self.assertTrue(step.why.endswith("Grug has no free bag slot"))

    def test_a_wait_for_distance_is_not_a_wait_for_room(self):
        report = gr.Report(routes=(route(),))
        w = full(positions={"Oz": NEAR, "Grug": FAR})
        step = gx.execute(report, w, Tape().move).steps[0]
        self.assertEqual(step.status, gx.WAITING)
        self.assertEqual(step.blocked, "")

    def test_the_dry_run_returns_the_reason(self):
        report = gr.Report(routes=(route(),))
        view = gx.dry_run_view(report, full(freeables={}))
        self.assertEqual(view["steps"][0]["blocked"], gx.BLOCKED_ROOM)
        self.assertEqual(view["blocked_for_room"], 1)

    def test_the_adapter_names_the_full_takers(self):
        """The fact the executor reads, at the seam that decides it."""
        row = bag_pressure.guild_route(
            "Oz", "Grug", 501, 7001, "Hauberk of Test", 40, True, "better"
        )
        plan = bag_pressure.guild_route_deliverable(
            [row], {"Oz": NEAR, "Grug": NEAR}, (), {"Grug": 0, "Oz": 2}
        )
        self.assertEqual(plan.grants, ())
        self.assertEqual(plan.crowded, (("Oz", 501, "Grug"),))


BOUND = 60 * 60


def waiting_result():
    report = gr.Report(routes=(route(),))
    return gx.execute(report, full(freeables={}), Tape().move)


class TheWaitEnds(unittest.TestCase):
    KEY = ("Oz", 501, "Grug")

    def barred_clock(self):
        clock, _ = rw.observe({}, waiting_result(), 0.0, BOUND)
        clock, _ = rw.observe(clock, waiting_result(), float(BOUND), BOUND)
        return clock

    def test_the_clock_starts_at_the_first_blocked_pass_and_is_kept(self):
        clock, lines = rw.observe({}, waiting_result(), 1000.0, BOUND)
        self.assertEqual(clock[self.KEY].since, 1000.0)
        self.assertEqual(lines, [])
        clock, lines = rw.observe(clock, waiting_result(), 1900.0, BOUND)
        self.assertEqual(clock[self.KEY].since, 1000.0)
        self.assertEqual(lines, [])
        self.assertEqual(rw.barred(clock), frozenset())

    def test_past_the_bound_the_wearer_is_barred_with_a_recorded_reason(self):
        clock, _ = rw.observe({}, waiting_result(), 1000.0, BOUND)
        clock, lines = rw.observe(clock, waiting_result(), 1000.0 + BOUND, BOUND)
        self.assertEqual(rw.barred(clock), frozenset({("Grug", 501)}))
        self.assertEqual(rw.barred_wearers(clock), ["Grug"])
        self.assertEqual(len(lines), 1)
        for word in ("dropped", "Oz", "Grug", "Hauberk of Test", "60 minutes"):
            self.assertIn(word, lines[0])
        self.assertIn("no free bag slot", lines[0])

    def test_the_bar_is_said_once_and_outlives_the_route(self):
        """Barred, so the next report has no such route: the bar stays."""
        clock, lines = rw.observe(self.barred_clock(), gx.Result(), BOUND + 60.0, BOUND)
        self.assertEqual(lines, [])
        self.assertEqual(rw.barred(clock), frozenset({("Grug", 501)}))
        clock, lines = rw.observe(clock, waiting_result(), BOUND + 120.0, BOUND)
        self.assertEqual(lines, [])

    def test_the_bar_holds_while_the_bags_stay_full(self):
        clock, lines = rw.release(self.barred_clock(), {"Grug": 0})
        self.assertEqual(rw.barred(clock), frozenset({("Grug", 501)}))
        self.assertEqual(lines, [])

    def test_room_in_the_bags_lifts_the_bar_and_says_so(self):
        clock, lines = rw.release(self.barred_clock(), {"Grug": 2})
        self.assertEqual(clock, {})
        self.assertEqual(len(lines), 1)
        self.assertIn("planned again for Grug", lines[0])
        self.assertIn("Hauberk of Test", lines[0])

    def test_a_wearer_nobody_could_read_is_not_barred_for_good(self):
        clock, lines = rw.release(self.barred_clock(), {})
        self.assertEqual(clock, {})
        self.assertIn("could not be read", lines[0])

    def test_release_leaves_a_running_clock_alone(self):
        clock, _ = rw.observe({}, waiting_result(), 0.0, BOUND)
        after, lines = rw.release(clock, {"Grug": 4})
        self.assertEqual(after, clock)
        self.assertEqual(lines, [])

    def test_a_move_that_stops_waiting_for_room_stops_its_clock(self):
        clock, _ = rw.observe({}, waiting_result(), 0.0, BOUND)
        moved = gx.execute(gr.Report(routes=(route(),)), world(), Tape().move)
        clock, lines = rw.observe(clock, moved, 600.0, BOUND)
        self.assertEqual(clock, {})
        self.assertEqual(lines, [])

    def test_a_bound_of_zero_turns_the_bar_off(self):
        clock, _ = rw.observe({}, waiting_result(), 0.0, 0)
        clock, lines = rw.observe(clock, waiting_result(), 9e9, 0)
        self.assertEqual(rw.barred(clock), frozenset())
        self.assertEqual(lines, [])


class PlannedAgainWithoutTheFullWearer(unittest.TestCase):
    """gearrouting.plan with a barred (wearer, guid): the piece goes to the
    next member it is an upgrade for, or to nobody."""

    def rows(self):
        members = [
            fixtures.tank("Grug"),
            fixtures.tank("Krog"),
            fixtures.member("Bork", fixtures.ROGUE, 43, skills=fixtures.ROGUE_SKILLS),
        ]
        piece = fixtures.symbolic_breastplate("Bork", guid=4242)
        gear_rows = [
            fixtures.old_breastplate("Grug"),
            fixtures.old_breastplate("Krog"),
            piece,
        ]
        return members, gear_rows

    def test_unbarred_the_first_wearer_has_it(self):
        members, gear_rows = self.rows()
        report = gr.plan(members, gear_rows)
        self.assertEqual([(r.wearer, r.guid) for r in report.routes], [("Grug", 4242)])

    def test_barred_it_is_planned_for_the_next_wearer(self):
        members, gear_rows = self.rows()
        report = gr.plan(members, gear_rows, barred={("Grug", 4242)})
        self.assertEqual([(r.wearer, r.guid) for r in report.routes], [("Krog", 4242)])
        self.assertTrue(
            any("Grug" in note and "no free bag slot" in note for note in report.notes)
        )

    def test_barred_with_nobody_else_it_is_routed_to_nobody(self):
        members, gear_rows = self.rows()
        report = gr.plan(members, gear_rows, barred={("Grug", 4242), ("Krog", 4242)})
        self.assertEqual(report.routes, ())


if __name__ == "__main__":
    unittest.main()

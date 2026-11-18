"""A Watch order is only "watching" once the Watcher stands on the target.

The module retired kind='gm' for every character, so for weeks each line the
director queued for the Watcher came back `error`, the director counted every
one as a move, spent its budget in three minutes, and the card said "Now
watching" while the camera stood where it logged in. These pin the path from
order to arrival: a refused line is read back and named, it does not spend the
budget, the budget's refill is stated in seconds, and the state the card draws
is `arrived` only when the director has seen the Watcher within range of the
target on the target's own map and instance.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import director as d

W = d.WATCHER_NAME
RFK = 47


def spot(name, map_id=0, inst=0, x=0.0, y=0.0, z=0.0):
    return d.Spot(name, map_id, inst, x, y, z, False, 0)


def row(note, spec="character Crag", target="Crag", ttl=1500):
    return {"spec": spec, "ttl": ttl, "target": target, "note": note}


class TheBootAsksOnlyWhatTheWorldRuns(unittest.TestCase):
    def test_boot_is_the_two_lines_the_module_runs(self):
        self.assertEqual(d.BOOT_COMMANDS, (".gm on", ".gm visible off"))
        self.assertTrue(d.commands_ok(d.BOOT_COMMANDS))


class ARefusedLineIsReadBackAndNamed(unittest.TestCase):
    def test_an_error_row_is_a_failure_with_its_reason(self):
        rows = [
            {"id": 1, "status": "applied", "detail": ""},
            {"id": 2, "status": "error", "detail": "the target is not in the world"},
        ]
        self.assertEqual(d.failure_in(rows), "the target is not in the world")

    def test_pending_and_applied_rows_are_not_a_failure(self):
        for status in ("pending", "claimed", "applied", "verifying", "delivered"):
            self.assertEqual(
                d.failure_in([{"id": 1, "status": status, "detail": ""}]), ""
            )

    def test_an_error_without_a_reason_still_says_so(self):
        self.assertIn(
            "refused", d.failure_in([{"id": 1, "status": "error", "detail": ""}])
        )

    def test_a_failure_refunds_the_moves_and_backs_off(self):
        m = d.Memory()
        m.record_move(100.0)
        m.sent_ids, m.sent_at = [7, 8], 100.0
        rows = [{"id": 7, "status": "error", "detail": "kind='gm' is retired"}]
        failure = m.on_results(rows, now=103.0)
        self.assertEqual(failure, "kind='gm' is retired")
        self.assertEqual(m.moves, [])
        self.assertEqual(m.sent_ids, [])
        self.assertTrue(m.backing_off(110.0))
        self.assertFalse(m.backing_off(103.0 + d.FAIL_BACKOFF + 1))

    def test_rows_not_yet_answered_are_kept_for_the_next_look(self):
        m = d.Memory()
        m.record_move(100.0)
        m.sent_ids, m.sent_at = [7], 100.0
        self.assertEqual(
            m.on_results([{"id": 7, "status": "pending", "detail": ""}], now=101.0), ""
        )
        self.assertEqual(m.sent_ids, [7])
        self.assertEqual(m.moves, [100.0])

    def test_a_later_answered_row_lifts_an_older_refusal(self):
        m = d.Memory()
        m.failure, m.fail_until = "no", 500.0
        m.sent_ids, m.sent_at = [9, 10], 100.0
        m.on_results([{"id": 9, "status": "verifying", "detail": ""}], now=101.0)
        self.assertEqual(m.failure, "")
        self.assertFalse(m.backing_off(101.0))

    def test_answered_rows_are_forgotten(self):
        m = d.Memory()
        m.sent_ids, m.sent_at = [7], 100.0
        m.on_results([{"id": 7, "status": "applied", "detail": ""}], now=101.0)
        self.assertEqual(m.sent_ids, [])

    def test_a_dozen_refused_orders_never_spend_the_budget(self):
        m = d.Memory()
        now = 1000.0
        for _ in range(30):
            m.record_move(now)
            m.sent_ids, m.sent_at = [1], now
            m.on_results([{"id": 1, "status": "error", "detail": "no"}], now=now + 1)
            now += 20
        self.assertTrue(d._budget_left(m.moves, now))


class TheBudgetSaysWhenItRefills(unittest.TestCase):
    def test_spent_budget_names_the_seconds_left(self):
        w, t = spot(W, 0), spot("Crag", RFK, 4, 100.0)
        moves = [10.0 + i for i in range(d.APPEAR_BUDGET[0])]
        got = d.decide(w, t, now=100.0, moves=moves, booted_at=1.0, new_target=True)
        self.assertEqual(got.code, d.R_RATE)
        # The oldest move (t=10) leaves the 600 second window at t=610.
        self.assertIn("refills in 510 seconds", got.reason)

    def test_refill_seconds_helper(self):
        moves = [10.0, 20.0]
        self.assertEqual(d.budget_refill_in(moves, 100.0), 0)
        full = [10.0 + i for i in range(d.APPEAR_BUDGET[0])]
        self.assertEqual(d.budget_refill_in(full, 100.0), 510)


class TheStateTheCardDraws(unittest.TestCase):
    def test_follow_is_arrived(self):
        s = d.spectate_state(row("Crag: follow, within 35 yards of Crag"))
        self.assertEqual(s["state"], "arrived")

    def test_a_move_in_flight_is_moving(self):
        s = d.spectate_state(
            row("Crag: appear, into Crag's instance (stale binds dropped first)")
        )
        self.assertEqual(s["state"], "moving")

    def test_a_hop_is_moving(self):
        s = d.spectate_state(row("Crag: hop, leaving this instance of map 47 first"))
        self.assertEqual(s["state"], "moving")

    def test_ordered_with_no_target_is_waiting(self):
        s = d.spectate_state(row("ordered", target=""))
        self.assertEqual(s["state"], "waiting")

    def test_rate_limit_is_held(self):
        s = d.spectate_state(
            row(
                "Crag: hold, moves are rate limited (budget spent, refills in 40 seconds)"
            )
        )
        self.assertEqual(s["state"], "held")

    def test_a_refusal_is_refused(self):
        s = d.spectate_state(row("Crag: refuse, the target is not in the world"))
        self.assertEqual(s["state"], "refused")

    def test_a_failed_move_is_failed(self):
        s = d.spectate_state(
            row(
                "Crag: failed, the world refused the move: the target is not in the world"
            )
        )
        self.assertEqual(s["state"], "failed")

    def test_inactive_has_no_state(self):
        self.assertEqual(d.spectate_state(None)["state"], "")
        self.assertFalse(d.spectate_state(None)["arrived"])

    def test_only_arrived_sets_the_flag(self):
        self.assertTrue(
            d.spectate_state(row("Crag: follow, within 35 yards of Crag"))["arrived"]
        )
        self.assertFalse(d.spectate_state(row("Crag: appear, into x"))["arrived"])
        self.assertFalse(d.spectate_state(row("ordered", target=""))["arrived"])


class OrderToArrival(unittest.TestCase):
    """The whole path with the world played by hand."""

    def test_into_a_dungeon_instance_then_arrival(self):
        crag = spot("Crag", RFK, 4, 2205.0, 1633.0, 85.0)
        tirisfal = spot(W, 0, 0, 1676.0, 1678.0, 121.0)
        booted = d.decide(tirisfal, crag, now=100.0, booted_at=None)
        self.assertEqual(booted.action, d.BOOT)
        go = d.decide(tirisfal, crag, now=120.0, booted_at=100.0, new_target=True)
        self.assertEqual(go.action, d.APPEAR)
        self.assertEqual(go.commands, (".instance unbind all", ".appear Crag"))
        self.assertEqual(
            d.spectate_state(row("Crag: appear, " + go.reason))["state"], "moving"
        )
        there = spot(W, RFK, 4, 2200.0, 1630.0, 85.0)
        done = d.decide(there, crag, now=124.0, booted_at=100.0)
        self.assertEqual(done.action, d.FOLLOW)
        self.assertEqual(
            d.spectate_state(row("Crag: follow, " + done.reason))["state"], "arrived"
        )

    def test_on_the_right_map_but_another_copy_is_not_arrived(self):
        crag = spot("Crag", RFK, 4, 2205.0, 1633.0, 85.0)
        other = spot(W, RFK, 9, 2205.0, 1633.0, 85.0)
        got = d.decide(other, crag, now=120.0, booted_at=100.0, new_target=True)
        self.assertEqual(got.action, d.HOP)


if __name__ == "__main__":
    unittest.main()


try:
    from test_app_flagship import needs_node
    import test_app_spectate  # noqa: F401
except Exception:  # pragma: no cover - the page tests need the app test helpers

    def needs_node(cls):
        return unittest.skip("app test helpers unavailable")(cls)


def card(**kw):
    import json

    from test_app_spectate import cam as _cam, markup as _markup

    base = dict(
        active=True,
        character="Crag",
        spec="character Crag",
        target="Crag",
        watcher="Watcher",
    )
    base.update(kw)
    return _markup(
        'S.stage(%s, [], {"data": {"enabled": true}}, true)' % json.dumps(_cam(**base))
    )


@needs_node
class TheCardOnlySaysWatchingOnceItIsThere(unittest.TestCase):
    def test_ordered_and_waiting_is_not_watching(self):
        m = card(target="", note="ordered", state="waiting", arrived=False)
        self.assertNotIn("Now watching", m)
        self.assertIn("Waiting to watch", m)

    def test_a_move_in_flight_says_heading_to(self):
        m = card(
            note="Crag: appear, into Crag's instance", state="moving", arrived=False
        )
        self.assertIn("Heading to Crag", m)
        self.assertNotIn("Now watching", m)

    def test_a_held_move_gives_the_refill(self):
        note = (
            "Crag: hold, moves are rate limited (budget spent, refills in 40 seconds)"
        )
        m = card(note=note, state="held", arrived=False)
        self.assertIn("Waiting to move to Crag", m)
        self.assertIn("refills in 40 seconds", m)

    def test_a_refused_move_says_could_not_reach_and_why(self):
        note = (
            "Crag: failed, the world refused the move: the target is not in the world"
        )
        m = card(note=note, state="failed", arrived=False)
        self.assertIn("Could not reach Crag", m)
        self.assertIn("the target is not in the world", m)
        self.assertNotIn("Now watching", m)

    def test_arrived_says_now_watching_and_names_who_it_follows(self):
        m = card(
            character="Cave",
            spec="guild Cave",
            note="Crag: follow, within 35 yards of Crag",
            state="arrived",
            arrived=True,
        )
        self.assertIn("Now watching Cave", m)
        self.assertIn("Following Crag", m)

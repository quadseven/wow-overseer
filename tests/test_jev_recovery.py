"""Run recovery and staging stall, asked of Jev (jev_recovery).

mod-overseer never stops a dungeon campaign on failures now: a failed attempt
writes an overseer_run_recovery row and the coordinator waits a backoff. These
pin the bridge's half: which rows are asked about, what Jev is shown (the
timeline, positions, bags and how earlier recoveries turned out), that Jev
acts only past its floor, that the heuristic is written back otherwise, and
that the pass is wired into both the gateway and the headless bridge. The
tests run the real client over a fake transport and never call the API.
"""

import asyncio
import datetime
import pathlib
import unittest

import jev
import jev_recovery
from test_jev_items import FakeJev

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


def recovery_row(**kw):
    row = {
        "id": 7,
        "family": "Zug",
        "leader_name": "Zug",
        "campaign_id": 11,
        "run_number": 1,
        "kind": "run_recovery",
        "attempt": 3,
        "failure": "staging_failed: GATHERING held for more than 12 minutes "
        "and never opened - Zug (5945y out and 281y above it)",
        "facts": "leader 5945y from the staging point; farthest member 30y",
        "options": "restage_nearer,regroup,replan,one_copy,reset_instance,"
        "wait_for_client,town_for_bags",
        "heuristic": "restage_nearer",
        "heuristic_why": "the leader was far from the door",
    }
    row.update(kw)
    return row


def stall_row(**kw):
    row = recovery_row(
        kind="staging_stall",
        attempt=6,
        failure="the leader's staging errand was taken back 6 times",
        facts="rearms 6; last ended by the terrain drive",
        options="keep_rearming,run_yields,recover_now",
        heuristic="keep_rearming",
    )
    row.update(kw)
    return row


def context():
    return jev_recovery.Context(
        events=[
            {
                "phase": "GATHERING",
                "kind": "staging_rearm",
                "detail": "the leader's staging errand was taken back (6 so far)",
            }
        ],
        positions={
            "Zug": {"map_id": 1, "zone_id": 1637, "pos_x": 1631.0, "pos_y": -4150.3},
            "Oz": {"map_id": 1, "zone_id": 1637, "pos_x": 1630.0, "pos_y": -4151.0},
        },
        free_slots={"Zug": 6, "Oz": 15, "Zork": 6},
    )


def judge(row, fake, environ=None):
    request = jev_recovery.request_from_row(row)
    rule = jev_recovery.policy(request.kind, environ=environ or {})
    client = jev.Client("k", transport=fake)
    return request, asyncio.run(jev_recovery.judge(client, request, context(), rule))


class RowsTest(unittest.TestCase):
    def test_a_recovery_row_becomes_a_request_with_only_known_options(self):
        req = jev_recovery.request_from_row(
            recovery_row(options="restage_nearer,stop_campaign,regroup")
        )
        self.assertEqual(req.options, ("restage_nearer", "regroup"))
        self.assertEqual(req.kind, jev_recovery.KIND_RECOVERY)

    def test_a_row_whose_heuristic_is_not_offered_is_not_asked(self):
        self.assertIsNone(
            jev_recovery.request_from_row(recovery_row(heuristic="stop_campaign"))
        )

    def test_an_unknown_kind_is_not_asked(self):
        self.assertIsNone(jev_recovery.request_from_row(recovery_row(kind="other")))

    def test_stopping_the_campaign_is_never_an_option(self):
        for criteria in (jev_recovery.RECOVERY_CRITERIA, jev_recovery.STALL_CRITERIA):
            self.assertFalse(any("stop" in option for option in criteria))


class HearthRegroupTest(unittest.TestCase):
    """The module's hearth_regroup (2026-09-24) is asked about, and can win.

    Measured on wow-dev: the Horde family's fifth failed Ragefire attempt had
    the leader 5,549 yards from the door, a member 4,289 yards from him, and
    four of five bound at one inn. The module now offers hearth_regroup and
    chooses it; a bridge that does not know the word drops it from the
    options and, with it as the heuristic, never asks at all.
    """

    MEASURED = dict(
        attempt=5,
        failure="staging_failed: GATHERING was closed early: the leader's "
        "staging errand was taken back 7 times",
        facts="leader 5549y from the staging point; farthest member 4289y "
        "from the leader; 4 of 5 bound at one inn (map 1 area 14), 4 can "
        "hearth there now, Zork would walk or fly to it",
        options="restage_nearer,regroup,replan,one_copy,reset_instance,"
        "wait_for_client,town_for_bags,hearth_regroup",
        heuristic="hearth_regroup",
        heuristic_why="the family was spread across zones and most of it is "
        "bound at one inn",
    )

    def test_the_module_heuristic_row_is_asked(self):
        req = jev_recovery.request_from_row(recovery_row(**self.MEASURED))
        self.assertIsNotNone(req)
        self.assertIn("hearth_regroup", req.options)
        self.assertEqual(req.heuristic, "hearth_regroup")

    def test_jev_is_shown_what_it_means(self):
        req = jev_recovery.request_from_row(recovery_row(**self.MEASURED))
        _state, questions = jev_recovery.question(req, context())
        self.assertIn("hearthstone", str(questions["recovery"]))

    def test_jev_can_choose_it_over_a_walk(self):
        row = dict(self.MEASURED, heuristic="restage_nearer")
        _req, judgment = judge(
            recovery_row(**row), FakeJev({"recovery": "hearth_regroup"}, 0.8)
        )
        self.assertEqual(judgment.chosen, "hearth_regroup")
        self.assertEqual(judgment.chosen_by, "jev")

    def test_not_offered_is_not_chosen(self):
        _req, judgment = judge(
            recovery_row(), FakeJev({"recovery": "hearth_regroup"}, 0.9)
        )
        self.assertEqual(judgment.chosen, "restage_nearer")


class StateTest(unittest.TestCase):
    def test_the_state_carries_timeline_positions_bags_and_offline(self):
        req = jev_recovery.request_from_row(recovery_row())
        state = jev_recovery.state_for(req, context())
        self.assertEqual(state["failures_in_a_row"], 3)
        self.assertEqual(state["recent_timeline"][0]["kind"], "staging_rearm")
        self.assertEqual(state["members"]["Zug"]["free_bag_slots"], 6)
        self.assertEqual(state["offline_or_unseen"], ["Zork"])
        self.assertIn("5945y", state["what_happened"])

    def test_the_state_is_extensible_for_perception(self):
        req = jev_recovery.request_from_row(stall_row())
        ctx = context()
        ctx.perception = {"Zug": {"moving": True}}

        def extend(request, _context, state):
            state["extended_for"] = request.leader

        jev_recovery.FACT_EXTENDERS.append(extend)
        try:
            state = jev_recovery.state_for(req, ctx)
        finally:
            jev_recovery.FACT_EXTENDERS.remove(extend)
        self.assertEqual(state["perception"], {"Zug": {"moving": True}})
        self.assertEqual(state["extended_for"], "Zug")
        self.assertEqual(state["times_taken_back"], 6)

    def test_history_says_what_followed_each_recovery(self):
        t0 = datetime.datetime(2026, 9, 24, 1, 0, 0)
        applied = [
            {
                "family": "Zug",
                "campaign_id": 11,
                "failure": "staging_failed: far",
                "applied": "reset_instance",
                "applied_by": "heuristic",
                "applied_at": t0,
            },
            {
                "family": "Zug",
                "campaign_id": 11,
                "failure": "staging_failed: far",
                "applied": "restage_nearer",
                "applied_by": "jev",
                "applied_at": t0 + datetime.timedelta(minutes=30),
            },
        ]
        runs = [
            {
                "campaign_id": 11,
                "started_at": t0 + datetime.timedelta(minutes=5),
                "outcome": "staging_failed",
                "ended_reason": "GATHERING held for more than 12 minutes",
            },
            {
                "campaign_id": 11,
                "started_at": t0 + datetime.timedelta(minutes=45),
                "outcome": "complete",
                "ended_reason": "",
            },
        ]
        history = jev_recovery.recovery_history(applied, runs)
        self.assertEqual(history[0]["recovery"], "reset_instance")
        self.assertTrue(history[0]["then"].startswith("failed again (staging_failed"))
        self.assertEqual(history[1]["then"], "got inside (complete)")


class ActTest(unittest.TestCase):
    def test_a_confident_different_answer_acts(self):
        _req, judgment = judge(recovery_row(), FakeJev({"recovery": "regroup"}, 0.8))
        self.assertEqual(judgment.acted, jev.JEV)
        self.assertEqual(judgment.chosen, "regroup")
        self.assertEqual(judgment.chosen_by, "jev")

    def test_below_the_floor_the_heuristic_is_written_back(self):
        _req, judgment = judge(recovery_row(), FakeJev({"recovery": "regroup"}, 0.4))
        self.assertEqual(judgment.acted, jev.HEURISTIC)
        self.assertEqual(judgment.chosen, "restage_nearer")
        self.assertEqual(judgment.chosen_by, "heuristic")
        self.assertEqual(judgment.jev, "regroup")

    def test_agreement_past_the_floor_is_both(self):
        _req, judgment = judge(
            recovery_row(), FakeJev({"recovery": "restage_nearer"}, 0.9)
        )
        self.assertEqual(judgment.acted, jev.BOTH)
        self.assertEqual(judgment.chosen_by, "jev")

    def test_no_answer_keeps_the_heuristic(self):
        def down(*_a):
            return 503, b""

        _req, judgment = judge(recovery_row(), down)
        self.assertEqual(judgment.chosen, "restage_nearer")
        self.assertEqual(judgment.status, jev.ERROR)

    def test_the_stall_kind_asks_only_its_own_options(self):
        fake = FakeJev({"stall": "run_yields"}, 0.9)
        _req, judgment = judge(stall_row(), fake)
        asked = fake.requests[0]["questions"]["stall"]["criteria"]
        self.assertEqual(set(asked), {"keep_rearming", "run_yields", "recover_now"})
        self.assertEqual(judgment.kind, jev_recovery.KIND_STALL)
        self.assertEqual(judgment.chosen, "run_yields")

    def test_the_mode_switch_can_turn_a_kind_off(self):
        _req, judgment = judge(
            recovery_row(),
            FakeJev({"recovery": "regroup"}, 0.99),
            environ={"JEV_MODE_RUN_RECOVERY": "off"},
        )
        self.assertEqual(judgment.chosen, "restage_nearer")
        self.assertEqual(judgment.status, "off")

    def test_both_kinds_act_by_default(self):
        self.assertEqual(jev_recovery.policy("run_recovery", {}).mode, jev.ACT)
        self.assertEqual(jev_recovery.policy("staging_stall", {}).mode, jev.ACT)
        self.assertEqual(
            jev_recovery.policy("run_recovery", {}).threshold,
            jev_recovery.RECOVERY_THRESHOLD,
        )


class BridgeWiringTest(unittest.TestCase):
    def test_the_loop_runs_under_the_gateway_and_headless(self):
        self.assertEqual(BRIDGE.count("self._run_recovery_loop,"), 2)

    def test_the_answer_only_lands_on_a_pending_row(self):
        self.assertIn("WHERE id = %s AND status = 'pending'", BRIDGE)

    def test_every_judgment_is_recorded(self):
        start = BRIDGE.index("async def _answer_run_recovery")
        body = BRIDGE[start : BRIDGE.index("async def _campaign_queue_loop")]
        self.assertIn("_insert_jev_judgment", body)
        self.assertIn("_answer_recovery_request", body)


if __name__ == "__main__":
    unittest.main()

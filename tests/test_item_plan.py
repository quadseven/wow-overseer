"""The staleness gate, against the rows the live realm actually wrote.

Every fixture here is a real shape taken from `overseer_command` on the dev
realm on 2026-09-05, including the result payloads, so a change that stops
honouring the world's own `retry` word fails here rather than in production.
"""
import unittest

import item_plan
from bag_pressure import ItemForSale, SellCandidate

JUNK = ItemForSale(quality=0, sell_price=12)


def candidate(holder="Ugga", guid=1304881, count=4):
    return SellCandidate(holder=holder, item_guid=guid, count=count, item=JUNK)


def row(command="guid:1304881 count:4", status="error",
        detail="item not carried", result="", holder="Ugga"):
    return {"target_name": holder, "command": command, "status": status,
            "detail": detail, "result": result}


class ParsingTests(unittest.TestCase):
    def test_reads_the_command_shape_the_bridge_writes(self):
        self.assertEqual(item_plan.parse_request("guid:1304881 count:4"),
                         (1304881, 4))

    def test_a_countless_command_parses_with_zero(self):
        self.assertEqual(item_plan.parse_request("guid:77"), (77, 0))

    def test_nonsense_is_not_an_attempt(self):
        self.assertIsNone(item_plan.parse_request("sell everything"))
        self.assertIsNone(item_plan.parse_request(None))
        self.assertIsNone(item_plan.attempt_from_row(row(command="junk")))

    def test_reads_the_worlds_retry_word_and_true_stack(self):
        payload = ('{"outcome":"refused","reason":"count exceeds stack",'
                   '"retry":"never","seller":"Bork",'
                   '"request":"guid:1501282 count:6",'
                   '"item":{"guid":1501282,"entry":2592,"name":"Wool Cloth",'
                   '"count":6,"stack":3}}')
        attempt = item_plan.attempt_from_row(
            row(command="guid:1501282 count:6", holder="Bork",
                detail="count exceeds stack", result=payload))
        self.assertEqual(attempt.retry, "never")
        self.assertEqual(attempt.stack, 3)
        self.assertEqual(attempt.count, 6)

    def test_a_garbled_payload_costs_the_verdict_not_the_row(self):
        attempt = item_plan.attempt_from_row(row(result="{not json"))
        self.assertEqual(attempt.retry, "")
        self.assertIsNone(attempt.stack)
        self.assertEqual(attempt.detail, "item not carried")


class ScopeTests(unittest.TestCase):
    def test_a_delivered_sale_ends_the_item(self):
        attempt = item_plan.attempt_from_row(
            row(status="delivered", detail=""))
        self.assertEqual(item_plan.terminal_scope(attempt), item_plan.ITEM)

    def test_item_not_carried_ends_the_item(self):
        self.assertEqual(
            item_plan.terminal_scope(item_plan.attempt_from_row(row())),
            item_plan.ITEM)

    def test_count_exceeds_stack_ends_only_that_request(self):
        attempt = item_plan.attempt_from_row(row(detail="count exceeds stack"))
        self.assertEqual(item_plan.terminal_scope(attempt), item_plan.REQUEST)

    def test_travelling_refusals_stay_retryable(self):
        for detail in ("vendor not in range", "seller is in flight",
                       "seller is dead", "target not online"):
            attempt = item_plan.attempt_from_row(row(detail=detail))
            self.assertEqual(item_plan.terminal_scope(attempt), "", detail)

    def test_an_unknown_never_literal_is_honoured_narrowly(self):
        # A world image newer than this file refuses with a literal we do not
        # carry. Its `retry` word still stops the retry storm.
        attempt = item_plan.attempt_from_row(
            row(detail="item is enchanted",
                result='{"retry":"never"}'))
        self.assertEqual(item_plan.terminal_scope(attempt), item_plan.REQUEST)

    def test_the_bank_refusal_is_terminal_too(self):
        attempt = item_plan.attempt_from_row(row(detail="item not in bank"))
        self.assertEqual(item_plan.terminal_scope(attempt), item_plan.ITEM)


class PlanTests(unittest.TestCase):
    def test_the_measured_bug_a_sold_item_is_never_re_queued(self):
        # Ugga guid:1304881 count:4 sold at 03:10:10 and was re-queued at
        # 03:15:10, one vendor cycle later, for `item not carried`.
        sold = item_plan.attempt_from_row(row(status="delivered", detail=""))
        plan = item_plan.plan([candidate()], [sold])
        self.assertEqual(plan.write, ())
        self.assertEqual(sum(plan.skipped.values()), 1)

    def test_a_refused_item_is_never_re_queued(self):
        plan = item_plan.plan(
            [candidate()], [item_plan.attempt_from_row(row())])
        self.assertEqual(plan.write, ())
        self.assertEqual(plan.skipped, {"item not carried": 1})

    def test_a_travelling_seller_is_still_retried(self):
        # mod-overseer#209: the whole point of re-issuing while the seller
        # walks to town. This must survive the fix.
        attempt = item_plan.attempt_from_row(row(detail="vendor not in range"))
        plan = item_plan.plan([candidate()], [attempt])
        self.assertEqual(len(plan.write), 1)
        self.assertEqual(plan.skipped, {})

    def test_a_pending_row_is_not_doubled(self):
        attempt = item_plan.attempt_from_row(row(status="pending", detail=""))
        plan = item_plan.plan([candidate()], [attempt])
        self.assertEqual(plan.write, ())
        self.assertEqual(plan.skipped, {"already queued": 1})

    def test_one_pass_never_writes_the_same_stack_twice(self):
        plan = item_plan.plan([candidate(), candidate()], [])
        self.assertEqual(len(plan.write), 1)
        self.assertEqual(plan.skipped, {"duplicate in this pass": 1})

    def test_an_empty_history_writes_everything_once(self):
        wanted = [candidate(guid=1), candidate(guid=2), candidate(guid=3)]
        self.assertEqual(item_plan.plan(wanted, []).write, tuple(wanted))

    def test_the_count_is_corrected_from_the_worlds_own_measurement(self):
        # Bork asked for 6 Wool Cloth, the world answered "stack":3. The next
        # pass must ask for 3, not 6 again and not nothing.
        payload = ('{"retry":"never","item":{"count":6,"stack":3}}')
        attempt = item_plan.attempt_from_row(
            row(command="guid:1501282 count:6", holder="Bork",
                detail="count exceeds stack", result=payload))
        plan = item_plan.plan(
            [candidate(holder="Bork", guid=1501282, count=6)], [attempt])
        self.assertEqual(len(plan.write), 1)
        self.assertEqual(plan.write[0].count, 3)
        self.assertEqual(plan.write[0].holder, "Bork")

    def test_the_corrected_count_is_not_asked_for_twice(self):
        payload = '{"retry":"never","item":{"count":3,"stack":3}}'
        refused = item_plan.attempt_from_row(
            row(command="guid:1501282 count:3", holder="Bork",
                detail="count exceeds stack", result=payload))
        plan = item_plan.plan(
            [candidate(holder="Bork", guid=1501282, count=3)], [refused])
        self.assertEqual(plan.write, ())

    def test_an_emptied_stack_is_dropped_rather_than_asked_for(self):
        payload = '{"retry":"never","item":{"count":2,"stack":0}}'
        attempt = item_plan.attempt_from_row(
            row(command="guid:9 count:2", detail="count exceeds stack",
                result=payload))
        plan = item_plan.plan([candidate(guid=9, count=2)], [attempt])
        self.assertEqual(plan.write, ())
        self.assertEqual(plan.skipped, {"nothing left in the stack": 1})

    def test_a_verdict_about_one_character_never_binds_another(self):
        sold = item_plan.attempt_from_row(
            row(status="delivered", detail="", holder="Ugga"))
        plan = item_plan.plan([candidate(holder="Grug")], [sold])
        self.assertEqual(len(plan.write), 1)

    def test_the_pass_log_says_what_was_held_back(self):
        self.assertEqual(item_plan.reasons({}), "nothing")
        self.assertEqual(
            item_plan.reasons({"item not carried": 12, "already queued": 3}),
            "12 item not carried, 3 already queued")

    def test_an_unreadable_history_does_not_stop_the_pass(self):
        # Fail open: the gate that cannot read its evidence must not become a
        # gate that refuses everything.
        self.assertEqual(len(item_plan.plan([candidate()], []).write), 1)


if __name__ == "__main__":
    unittest.main()

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


class TheWorldSaysWhereAndNotOnlyWhether(unittest.TestCase):
    """The `elsewhere` retry word, which nothing on this side used to read.

    MEASURED ON THE LIVE REALM over three hours on 2026-09-09:

        kind    status      n
        sell    error     1950     <- 1860 of them "vendor not in range"
        sell    delivered   10

    mod-overseer#230 stopped pushing a refused row back to `pending` (twenty
    of them held the head of the queue and livelocked the drain for half an
    hour) and carries the retry class out instead, so that the side which
    DECIDES re-queues a fresh row. `vendor not in range` is classified
    ELSEWHERE: the row can work, but not from where the character is standing.

    `terminal_scope` honoured only `never`, so ELSEWHERE read exactly like
    `later` and the same item was offered again every cycle from the same
    spot. These tests are that word finally being read (infra#3464).
    """

    def _refusals(self, guid, holder="Grug", n=1):
        return [item_plan.attempt_from_row(row(
            command="guid:%d count:4" % guid, holder=holder, status="error",
            detail="vendor not in range",
            result='{"reason":"vendor not in range","retry":"elsewhere"}',
        )) for _ in range(n)]

    def test_the_word_is_the_worlds_own_spelling(self):
        self.assertEqual(item_plan.RETRY_ELSEWHERE, "elsewhere")

    def test_one_refusal_is_a_near_miss_and_is_asked_again(self):
        """A bot drifts in and out of five yards. One refusal is not a wall,
        and treating it as one would strand an item about to sell."""
        got = item_plan.plan([candidate(holder="Grug", guid=5001)],
                             self._refusals(5001))
        self.assertEqual([c.item_guid for c in got.write], [5001])

    def test_the_same_refusal_over_and_over_is_a_wall(self):
        """`GetNPCIfCanInteractWith` refuses an unfriendly vendor with the
        same literal it gives an absent one, so distance and hostility cannot
        be told apart from this side. Only the repetition tells them apart,
        and the counters nearest this family are the other faction's."""
        got = item_plan.plan(
            [candidate(holder="Grug", guid=5001)],
            self._refusals(5001, n=item_plan.ELSEWHERE_GIVE_UP))
        self.assertEqual(got.write, ())
        self.assertIn("for want of a reachable vendor",
                      item_plan.reasons(got.skipped))

    def test_the_hold_is_never_permanent(self):
        """ELSEWHERE means the row would work somewhere else, so the hold has
        to expire. It expires with the caller's memory window, which is what
        `attempts` already is: a party that walks to a vendor which will deal
        with them offers every one of these again."""
        got = item_plan.plan([candidate(holder="Grug", guid=5001)], [])
        self.assertEqual([c.item_guid for c in got.write], [5001])

    def test_it_is_kept_apart_from_the_permanent_refusals(self):
        """`item not carried` is NEVER and reaches the item for good.
        ELSEWHERE is about the place and must not be filed with it."""
        self.assertNotIn(item_plan.RETRY_ELSEWHERE, item_plan.TERMINAL_ITEM)
        self.assertNotIn(item_plan.RETRY_ELSEWHERE, item_plan.TERMINAL_REQUEST)
        stuck = item_plan.refused_here(self._refusals(5001, n=9))
        self.assertEqual(list(stuck), [("Grug", 5001)])

    def test_one_characters_wall_is_not_another_characters(self):
        """The place is a fact about the character. Two of the five can be
        standing in different rooms."""
        attempts = self._refusals(5001, holder="Grug",
                                  n=item_plan.ELSEWHERE_GIVE_UP)
        got = item_plan.plan([candidate(holder="Ugga", guid=5002)], attempts)
        self.assertEqual([c.item_guid for c in got.write], [5002])

    def test_a_row_with_no_retry_word_is_unaffected(self):
        """An older world image writes no `result`. The literals still
        classify it and nothing here may start holding items on a guess."""
        older = [item_plan.attempt_from_row(row(
            command="guid:5001 count:4", holder="Grug", status="error",
            detail="vendor not in range", result="",
        ))] * 9
        got = item_plan.plan([candidate(holder="Grug", guid=5001)], older)
        self.assertEqual([c.item_guid for c in got.write], [5001])


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

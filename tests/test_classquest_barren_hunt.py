"""The class hunt's stall clock follows objective progress (#2188).

Kills show a pack can be reached. Quest counters and loot of the objective's
item keep the hunt there. The module's total includes unrelated loot.
"""

import unittest
from unittest import mock

import classquest
import guildjobs
from test_classquest import book, qrow, who
from test_classquest_tried_memory import HUNTER, PACK_A, PACK_B, hunt, recent, two_packs

STALL_SECONDS = classquest.HUNT_STALL_MINUTES * 60


def barren(rid, age):
    return hunt(rid, "Aa", "applied", age, "timeout", "the clock ran out", 4, 0)


def looted(rid, age, *items):
    return hunt(
        rid,
        "Aa",
        "applied",
        age,
        "timeout",
        "the clock ran out",
        4,
        2,
        loot_items=items,
    )


def hunts_after_a_stall(*rows):
    """Run `_class_move` once to start the hunt clock, then again past the stall
    with these hunt rows, and return the hunts memory."""
    hunts = classquest.Hunts()
    member = who("Aa", **HUNTER)
    book = two_packs()
    guildjobs._class_move(member, book, recent(), hunts, 0.0)
    guildjobs._class_move(member, book, recent(*rows), hunts, float(STALL_SECONDS + 60))
    return hunts


@mock.patch.object(classquest, "TRIED_EPOCH", 0)
class BarrenHunt(unittest.TestCase):
    def test_staggered_kill_rows_cannot_postpone_the_original_deadline(self):
        hunts = classquest.Hunts()
        member = who("Aa", **HUNTER)
        book = two_packs()

        first, _ = guildjobs._class_move(member, book, recent(barren(1, 2)), hunts, 0.0)
        before_deadline, _ = guildjobs._class_move(
            member, book, recent(barren(1, 16)), hunts, 14 * 60.0
        )
        at_deadline, _ = guildjobs._class_move(
            member, book, recent(barren(1, 32), barren(2, 4)), hunts, STALL_SECONDS
        )

        self.assertEqual(first.spot.guid, PACK_A["guid"])
        self.assertEqual(before_deadline.spot, first.spot)
        self.assertEqual(at_deadline.spot.guid, PACK_B["guid"])
        self.assertEqual(len(hunts.get("Aa").tried), 1)

    def test_verified_quest_loot_refreshes_the_clock_only_once(self):
        hunts = classquest.Hunts()
        member = who("Aa", **HUNTER)
        book = two_packs()
        first, _ = guildjobs._class_move(member, book, recent(), hunts, 0.0)
        loot_seen = STALL_SECONDS - 60.0

        guildjobs._class_move(
            member, book, recent(looted(1, 1, 6486)), hunts, loot_seen
        )
        at_old_deadline, _ = guildjobs._class_move(
            member, book, recent(looted(1, 2, 6486)), hunts, STALL_SECONDS
        )

        self.assertEqual(at_old_deadline.spot, first.spot)
        self.assertEqual(hunts.get("Aa").since, loot_seen)
        at_new_deadline, _ = guildjobs._class_move(
            member, book, recent(looted(1, 31, 6486)), hunts, loot_seen + STALL_SECONDS
        )
        self.assertEqual(at_new_deadline.spot.guid, PACK_B["guid"])

    def test_a_run_of_barren_hunts_lets_the_stall_clock_run_out(self):
        hunts = hunts_after_a_stall(barren(1, 20), barren(2, 12), barren(3, 4))
        self.assertEqual(len(hunts.get("Aa").tried), 1)

    def test_two_barren_hunts_also_let_the_stall_clock_run_out(self):
        hunts = hunts_after_a_stall(barren(1, 12), barren(2, 4))
        self.assertEqual(len(hunts.get("Aa").tried), 1)

    def test_grey_loot_does_not_hide_the_run(self):
        # Each row looted something (a grey), the quest's counters never moved.
        hunts = hunts_after_a_stall(looted(1, 20, 2589), looted(2, 12, 64860))
        self.assertEqual(len(hunts.get("Aa").tried), 1)

    def test_a_delayed_kill_row_does_not_undo_a_pack_reroll(self):
        hunts = classquest.Hunts()
        member = who("Aa", **HUNTER)
        book = two_packs()
        first, _ = guildjobs._class_move(member, book, recent(), hunts, 0.0)
        rerolled, _ = guildjobs._class_move(
            member, book, recent(), hunts, float(STALL_SECONDS + 5)
        )
        self.assertNotEqual(first.spot, rerolled.spot)

        next_move, _ = guildjobs._class_move(
            member, book, recent(barren(1, 2)), hunts, float(STALL_SECONDS + 65)
        )
        self.assertEqual(next_move.spot, rerolled.spot)

        advanced = who("Aa", quest_progress={1498: 2}, **HUNTER)
        guildjobs._class_move(
            advanced, book, recent(barren(1, 2)), hunts, float(STALL_SECONDS + 70)
        )
        self.assertEqual(hunts.get("Aa").progress, 2)
        self.assertEqual(hunts.get("Aa").tried, ())

    def test_a_delayed_kill_row_does_not_reopen_a_given_up_quest(self):
        hunts = classquest.Hunts()
        hunts.give_up("Aa", 1498, float(STALL_SECONDS))
        now = float(STALL_SECONDS + 65)
        move, _ = guildjobs._class_move(
            who("Aa", **HUNTER), two_packs(), recent(barren(1, 2)), hunts, now
        )
        self.assertIsNone(move)
        self.assertEqual(hunts.state("Aa", now)[1], frozenset({1498}))

    def test_a_moved_quest_counter_restarts_the_clock_whatever_the_rows_say(self):
        # The criterion's progress half: Hunts.observe sees the counter move and
        # starts the clock over, so three kill rows at one pack are not a stall.
        hunts = classquest.Hunts()
        book = two_packs()
        rows = recent(barren(1, 20), barren(2, 12), barren(3, 4))
        guildjobs._class_move(who("Aa", **HUNTER), book, recent(), hunts, 0.0)
        moved = who("Aa", quest_progress={1498: 2}, **HUNTER)
        guildjobs._class_move(moved, book, rows, hunts, float(STALL_SECONDS + 60))
        self.assertEqual(hunts.get("Aa").tried, ())

    def test_a_loot_row_at_another_pack_does_not_restart_the_clock(self):
        other = hunt(
            5,
            "Aa",
            "applied",
            4,
            "timeout",
            "the clock ran out",
            4,
            1,
            entry=PACK_B["entry"],
            loot_items=(6486,),
        )
        hunts = hunts_after_a_stall(barren(1, 20), barren(2, 12), other)
        self.assertEqual(len(hunts.get("Aa").tried), 1)

    def test_a_newer_refusal_does_not_hide_verified_objective_loot(self):
        refused = hunt(9, "Aa", "error", 2, "refused", "no living creature", 0, 0)
        hunts = hunts_after_a_stall(barren(1, 20), looted(3, 4, 6486), refused)
        self.assertEqual(hunts.get("Aa").tried, ())
        self.assertEqual(hunts.get("Aa").since, STALL_SECONDS + 60)

    def test_a_timeout_without_a_kill_can_still_loot_the_quest_item(self):
        row = dict(looted(1, 4, 6486), status="unchanged")
        row["result"] = row["result"].replace('"kills":4', '"kills":0')
        hunts = hunts_after_a_stall(row)
        self.assertEqual(hunts.get("Aa").tried, ())
        self.assertEqual(hunts.get("Aa").since, STALL_SECONDS + 60)

    def test_the_loot_array_before_a_truncated_result_tail_is_enough(self):
        row = looted(1, 4, 6486)
        row["result"] = (row["result"][:-1] + ',"request":"' + "x" * 400)[:400]
        hunts = hunts_after_a_stall(row)
        self.assertEqual(hunts.get("Aa").tried, ())

    def test_a_quest_kill_credit_restarts_the_clock(self):
        quest = 2000
        kill_book = book(
            quest_rows=[
                qrow(quest, "Cull Lizards", reward=8121, npc1=3130, npc_count1=5)
            ],
            spawn_rows=[PACK_A, dict(PACK_B, entry=PACK_A["entry"])],
            loot_rows=[],
        )
        hunts = classquest.Hunts()
        member = who("Aa", quest_log={quest: 3})
        first, _ = guildjobs._class_move(member, kill_book, recent(), hunts, 0.0)
        credited = who("Aa", quest_log={quest: 3}, quest_progress={quest: 1})

        move, _ = guildjobs._class_move(
            credited, kill_book, recent(), hunts, STALL_SECONDS
        )

        self.assertEqual(move.spot, first.spot)
        self.assertEqual(hunts.get("Aa").progress, 1)
        self.assertEqual(hunts.get("Aa").since, STALL_SECONDS)

    def test_a_barren_run_tries_every_pack_and_then_has_no_move_left(self):
        # With two packs, two stalls try both; the member then has no hunt move
        # and the plan asks for help, as a stalled hunt does.
        hunts = classquest.Hunts()
        member = who("Aa", **HUNTER)
        book = two_packs()
        rows = recent(barren(1, 20), barren(2, 12), barren(3, 4))
        now = 0.0
        guildjobs._class_move(member, book, recent(), hunts, now)
        moves = []
        for _ in range(2):
            now += STALL_SECONDS + 60
            moves.append(guildjobs._class_move(member, book, rows, hunts, now)[0])
        self.assertEqual(len(hunts.get("Aa").tried), 2)
        self.assertIsNotNone(moves[0])
        self.assertIsNone(moves[1])


if __name__ == "__main__":
    unittest.main()

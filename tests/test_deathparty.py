"""A filled death-loop ask seats a two-member party start (#2277).

WHY THIS EXISTS. The death-loop help route (#2277) posts an ask, draws one
yes and marks the ask filled, but nothing yet seats a party from a filled
ask: a looper who escapes alone returns to the same content and loops
again. This piece is the pure planner at that seam: a filled deathloop ask
whose asker still stands in its loop, holding a standing yes from a helper
who is free, becomes one party start - the asker leads, the one helper
follows, and the meeting place is the asker's loop place. Rows in,
decisions out; the bridge runner that walks and forms the party is the
next slice, so no start is emitted for anything this planner cannot prove
from its rows.
"""

import unittest

from test_deathask import ask, loop_of

import deathparty
import guildsocial as gs


def answer(id_, ask_id, member, state=gs.YES):
    return gs.Answer(
        id=id_,
        ask_id=ask_id,
        member=member,
        role=gs.DPS,
        stance=gs.HELPS,
        said="",
        state=state,
    )


def filled_ask(**kw):
    return ask(9, "Looper", state=gs.FILLED, **kw)


class DeathPartyStarts(unittest.TestCase):
    def test_a_filled_ask_with_a_standing_yes_seats_one_party_start(self):
        loops = {"Looper": loop_of()}
        starts = deathparty.plan_starts(
            [filled_ask()],
            [answer(31, 9, "Helper")],
            loops,
            free={"Looper", "Helper"},
        )
        self.assertEqual(len(starts), 1)
        start = starts[0]
        self.assertEqual(start.ask_id, 9)
        self.assertEqual(start.leader, "Looper")
        self.assertEqual(start.helpers, ("Helper",))
        self.assertEqual(start.names(), ("Looper", "Helper"))
        self.assertEqual(start.place, loops["Looper"].place)
        self.assertEqual(start.answers, {"Helper": 31})

    def test_an_open_ask_holding_a_yes_is_not_seated_yet(self):
        starts = deathparty.plan_starts(
            [ask(9, "Looper")],
            [answer(31, 9, "Helper")],
            {"Looper": loop_of()},
            free={"Looper", "Helper"},
        )
        self.assertEqual(starts, ())

    def test_a_filled_ask_whose_asker_left_the_loop_seats_nothing(self):
        starts = deathparty.plan_starts(
            [filled_ask()],
            [answer(31, 9, "Helper")],
            {},
            free={"Looper", "Helper"},
        )
        self.assertEqual(starts, ())

    def test_a_filled_ask_with_a_held_helper_seats_nothing(self):
        starts = deathparty.plan_starts(
            [filled_ask()],
            [answer(31, 9, "Helper")],
            {"Looper": loop_of()},
            free={"Looper"},
        )
        self.assertEqual(starts, ())

    def test_a_filled_ask_with_a_held_asker_seats_nothing(self):
        starts = deathparty.plan_starts(
            [filled_ask()],
            [answer(31, 9, "Helper")],
            {"Looper": loop_of()},
            free={"Helper"},
        )
        self.assertEqual(starts, ())

    def test_a_taken_back_yes_seats_nothing(self):
        starts = deathparty.plan_starts(
            [filled_ask()],
            [answer(31, 9, "Helper", state="withdrawn")],
            {"Looper": loop_of()},
            free={"Looper", "Helper"},
        )
        self.assertEqual(starts, ())

    def test_one_helper_seats_at_most_one_party_a_pass(self):
        other = ask(10, "Other", state=gs.FILLED)
        loops = {"Looper": loop_of(), "Other": loop_of("Other")}
        starts = deathparty.plan_starts(
            [filled_ask(), other],
            [answer(31, 9, "Helper"), answer(32, 10, "Helper")],
            loops,
            free={"Looper", "Other", "Helper"},
        )
        self.assertEqual([s.ask_id for s in starts], [9])

    def test_a_member_already_taken_seats_no_second_party(self):
        starts = deathparty.plan_starts(
            [filled_ask()],
            [answer(31, 9, "Helper")],
            {"Looper": loop_of()},
            free={"Looper", "Helper"},
            taken={"Helper"},
        )
        self.assertEqual(starts, ())

    def test_a_filled_quest_ask_is_not_a_death_party(self):
        quest = ask(9, "Looper", kind="quest", state=gs.FILLED)
        starts = deathparty.plan_starts(
            [quest],
            [answer(31, 9, "Helper")],
            {"Looper": loop_of()},
            free={"Looper", "Helper"},
        )
        self.assertEqual(starts, ())

    def test_the_first_standing_yes_by_answer_id_is_the_helper(self):
        starts = deathparty.plan_starts(
            [filled_ask()],
            [answer(32, 9, "Second"), answer(31, 9, "Helper")],
            {"Looper": loop_of()},
            free={"Looper", "Helper", "Second"},
        )
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0].helpers, ("Helper",))
        self.assertEqual(starts[0].answers, {"Helper": 31})


class DeathPartyBook(unittest.TestCase):
    """The runner's seat book: a seated start is not seated twice, and a
    start is re-checked at act time against the newest reads."""

    def start(self):
        return deathparty.PartyStart(
            ask_id=9, leader="Looper", helpers=("Helper",),
            place=loop_of().place, answers={"Helper": 31})

    def test_a_start_seats_once_per_ask(self):
        book = deathparty.StartBook()
        self.assertTrue(book.seat(self.start()))
        self.assertFalse(book.seat(self.start()))
        self.assertEqual([s.ask_id for s in book.seated()], [9])

    def test_a_released_start_seats_again(self):
        book = deathparty.StartBook()
        book.seat(self.start())
        book.release(9)
        self.assertEqual(book.seated(), ())
        self.assertTrue(book.seat(self.start()))

    def test_a_start_stays_valid_while_the_asker_stands_in_its_loop(self):
        start = self.start()
        self.assertTrue(deathparty.start_still_valid(
            start, {"Looper": loop_of()}, free={"Looper", "Helper"}))

    def test_a_start_dies_when_the_asker_left_the_loop(self):
        self.assertFalse(deathparty.start_still_valid(
            self.start(), {}, free={"Looper", "Helper"}))

    def test_a_start_dies_when_a_member_is_no_longer_free(self):
        self.assertFalse(deathparty.start_still_valid(
            self.start(), {"Looper": loop_of()}, free={"Looper"}))

    def test_a_start_dies_when_the_meeting_place_moved(self):
        import dataclasses

        moved = dataclasses.replace(loop_of(), zone=1)
        self.assertNotEqual(moved.place, loop_of().place)
        self.assertFalse(deathparty.start_still_valid(
            self.start(), {"Looper": moved}, free={"Looper", "Helper"}))


if __name__ == "__main__":
    unittest.main()

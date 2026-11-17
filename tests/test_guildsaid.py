"""A guild member does not say the same sentence twice in one sitting (#1636).

Read on the dev realm on 2026-11-15: 2,958 guild lines in a day, and 126 times
the same member said the same sentence less than 40 minutes after its last
copy ("I'll come help, I know the way." 1,259 seconds apart). The answer pick
skipped a wording the member had said lately, but with every wording of its
small pool used it fell back to the first one, which could be the one said
minutes ago. Now the fallback is the wording said longest ago, and when even
that one is inside the sitting the member joins without a line.
"""

import datetime
import pathlib
import unittest
from dataclasses import replace

import guildsaid
import guildsocial as gs
from test_guildsocial import DEADMINES, NOW, ask, five, plan, yes

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def render(template):
    return template.format(place="The Deadmines", item="")


def said_by(out, member):
    return [r.said for r in out.replies if r.member == member]


def answered(id_, member, line, minutes_ago):
    return replace(
        yes(id_, 3, member, "dps"),
        said=line,
        created_at=NOW - datetime.timedelta(minutes=minutes_ago),
    )


class ThePick(unittest.TestCase):
    POOL = ("one {place}", "two", "three")

    def test_a_wording_not_said_is_taken_from_the_start(self):
        self.assertEqual(guildsaid.pick(self.POOL, render, {}, 1), "two")
        self.assertEqual(guildsaid.pick(self.POOL, render, {"two": 5.0}, 1), "three")

    def test_with_every_wording_said_the_one_said_longest_ago_is_taken(self):
        said = {"one The Deadmines": 200.0, "two": 21.0, "three": 90.0}
        for start in range(3):
            with self.subTest(start=start):
                self.assertEqual(
                    guildsaid.pick(self.POOL, render, said, start), "one {place}"
                )

    def test_inside_the_sitting_nothing_is_said(self):
        said = {"one The Deadmines": 39.0, "two": 21.0, "three": 5.0}
        self.assertIsNone(guildsaid.pick(self.POOL, render, said, 0))
        said["one The Deadmines"] = guildsaid.SAY_AGAIN_MINUTES
        self.assertEqual(guildsaid.pick(self.POOL, render, said, 0), "one {place}")

    def test_the_sitting_is_the_forty_minutes_a_reader_watched(self):
        self.assertGreaterEqual(guildsaid.SAY_AGAIN_MINUTES, 40.0)


class WhatAMemberSaidLately(unittest.TestCase):
    def test_the_latest_copy_of_a_line_is_the_one_that_counts(self):
        answers = [
            answered(1, "Zappy", "I'm in!", 180),
            answered(2, "Zappy", "I'm in!", 12),
            answered(3, "Locky", "I'm in!", 300),
            answered(4, "Zappy", "", 1),
        ]
        said = guildsaid.lately(answers, NOW)
        self.assertEqual(said["Zappy"], {"I'm in!": 12.0})
        self.assertEqual(said["Locky"], {"I'm in!": 300.0})

    def test_an_answer_with_no_time_is_old_not_fresh(self):
        said = guildsaid.lately([replace(yes(1, 3, "Zappy", "dps"), said="Hi")], NOW)
        self.assertGreaterEqual(said["Zappy"]["Hi"], guildsaid.SAY_AGAIN_MINUTES)


class AnAnswerIsNotRepeatedInOneSitting(unittest.TestCase):
    def pool(self):
        return [render(t) for t in gs._ANSWER[(gs.DPS, gs.NEED)]]

    def test_a_member_that_used_every_wording_repeats_the_oldest(self):
        pool = self.pool()
        # Every wording used, the stable first pick only 21 minutes ago.
        first = said_by(plan(five(), asks=[ask(7, "Auren")]), "Zappy")[0]
        ages = {line: 200.0 + i for i, line in enumerate(pool)}
        ages[first] = 21.0
        answers = [
            answered(10 + i, "Zappy", line, age)
            for i, (line, age) in enumerate(ages.items())
        ]
        again = said_by(plan(five(), asks=[ask(7, "Auren")], answers=answers), "Zappy")
        self.assertEqual(len(again), 1)
        self.assertNotEqual(again[0], first)
        self.assertEqual(again[0], max(ages, key=ages.get))

    def test_with_every_wording_said_this_sitting_it_joins_without_a_line(self):
        answers = [
            answered(10 + i, "Zappy", line, 5.0 + i)
            for i, line in enumerate(self.pool())
        ]
        out = plan(five(), asks=[ask(7, "Auren")], answers=answers)
        self.assertEqual(said_by(out, "Zappy"), [""])
        # The yes itself still stands: the seat is taken, only the line is not said.
        self.assertIn("Zappy", [r.member for r in out.replies])

    def test_answer_line_with_a_plain_set_keeps_the_stable_pick(self):
        used = set(self.pool())
        line = gs.answer_line("Zappy", gs.DPS, gs.NEED, DEADMINES, None, avoid=used)
        self.assertIn(line, used)


class EverySeatHasEnoughWordingsForADay(unittest.TestCase):
    def test_six_or_more_wordings_per_seat_and_stance(self):
        for key, pool in gs._ANSWER.items():
            with self.subTest(key=key):
                self.assertGreaterEqual(len(set(pool)), 6)
        self.assertGreaterEqual(len(set(gs._ANSWER_ITEM)), 6)

    def test_every_wording_fits_the_chat_line_and_renders(self):
        pools = [*gs._ANSWER.values(), gs._ANSWER_ITEM]
        for pool in pools:
            for template in pool:
                with self.subTest(template=template):
                    line = template.format(
                        place="Scarlet Monastery (the Graveyard)",
                        item="Albino Crocscale Boots",
                    )
                    self.assertLessEqual(len(line), 120)
                    self.assertTrue(line.isascii())


class TheBridgeSaysNothingForAnEmptyLine(unittest.TestCase):
    def test_the_answers_are_read_with_their_time(self):
        self.assertIn("created_at", gs.ANSWERS_SQL.split("FROM")[0])

    def test_an_answer_without_a_line_writes_no_chat_row(self):
        write = BRIDGE[BRIDGE.index("for reply in social.replies:") :]
        write = write[: write.index("run_id = 0")]
        self.assertIn("if reply.said:", write)
        self.assertLess(
            write.index("if reply.said:"),
            write.index("lines.append((reply.member, reply.said))"),
        )


if __name__ == "__main__":
    unittest.main()

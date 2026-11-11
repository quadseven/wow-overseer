"""A guild member does not answer with a sentence it already said (#1636).

Measured on the dev realm on 2026-11-08: in one day of guild chat the answer
"I'll come carry the group through." was said 243 times by 45 members, and a
reader found 267 repeated sentences inside 40 minutes. The damage seat that
carries had one wording, the tank and healer helper seats one each, so the
shift by ask id that #2028 added had nothing to shift to.
"""

import unittest
from dataclasses import replace

import guildsocial as gs
from test_guildsocial import DOORS, five, ask, plan, yes


def said_by(out, member):
    return [r.said for r in out.replies if r.member == member]


class EveryAnswerSeatHasSeveralWordings(unittest.TestCase):
    def test_no_seat_and_stance_has_one_wording(self):
        for key, pool in gs._ANSWER.items():
            with self.subTest(key=key):
                self.assertGreaterEqual(len(set(pool)), 3)

    def test_a_wording_already_said_is_skipped_for_every_seat(self):
        door = next(iter(DOORS.values())) if isinstance(DOORS, dict) else DOORS[0]
        for (role, stance), pool in gs._ANSWER.items():
            for wording in pool:
                with self.subTest(role=role, stance=stance, wording=wording):
                    first = gs.answer_line("Zappy", role, stance, door, None)
                    again = gs.answer_line(
                        "Zappy", role, stance, door, None, avoid={first}
                    )
                    self.assertNotEqual(first, again)

    def test_with_every_wording_used_the_stable_pick_stays(self):
        door = next(iter(DOORS.values())) if isinstance(DOORS, dict) else DOORS[0]
        pool = gs._ANSWER[(gs.DPS, gs.CARRIES)]
        used = {w.format(place=door.place, item="") for w in pool}
        self.assertIn(
            gs.answer_line("Zappy", gs.DPS, gs.CARRIES, door, None, avoid=used), used
        )


class APassAvoidsWhatTheMemberSaidLately(unittest.TestCase):
    def test_a_member_answers_a_new_ask_in_new_words(self):
        first = plan(five(), asks=[ask(7, "Auren")])
        line = said_by(first, "Zappy")[0]
        earlier = replace(yes(1, 3, "Zappy", "dps"), said=line)
        again = plan(five(), asks=[ask(7, "Auren")], answers=[earlier])
        self.assertNotEqual(said_by(again, "Zappy")[0], line)

    def test_another_members_words_do_not_bar_it(self):
        first = plan(five(), asks=[ask(7, "Auren")])
        line = said_by(first, "Zappy")[0]
        other = replace(yes(1, 3, "Locky", "dps"), said=line)
        again = plan(five(), asks=[ask(7, "Auren")], answers=[other])
        self.assertEqual(said_by(again, "Zappy")[0], line)


if __name__ == "__main__":
    unittest.main()

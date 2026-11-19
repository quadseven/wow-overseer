"""A member bound at another inn is asked to bind where its leader's inn is.

Measured on the dev realm: a family's two newer members were bound in a different
town from the other three, so every exit hearth and every finder stage skipped
them (`bound at another inn`) and each run's end left them 2,600 yards from the
family, held too far to walk back. Another family's fifth member had the same
split. The `bind` verb needs the character standing by an innkeeper, so this
moves nobody: it asks only while a member already stands at the leader's inn, as
it will on a family town errand there. Names and numbers are invented.
"""

import pathlib
import unittest

import rebind
import situation

INN = situation.Point(0, -8950.0, -132.0, 83.0)
OTHER_INN = situation.Point(0, -6240.0, 331.0, 384.0)
AT_INN = {"map_id": 0, "pos_x": -8940.0, "pos_y": -130.0}
IN_TOWN_FAR = {"map_id": 0, "pos_x": -8700.0, "pos_y": -100.0}
ELSEWHERE = {"map_id": 1, "pos_x": -8940.0, "pos_y": -130.0}


def member(bind=OTHER_INN, at=AT_INN, alive=True):
    return rebind.Member(bind=bind, at=at, alive=alive)


class Wants(unittest.TestCase):
    def test_bound_elsewhere_and_standing_at_the_leaders_inn(self):
        self.assertEqual("", rebind.why_not(INN, member()))

    def test_already_bound_there_is_nothing_to_do(self):
        self.assertEqual(rebind.SAME_INN, rebind.why_not(INN, member(bind=INN)))

    def test_bound_a_few_yards_off_counts_as_the_same_inn(self):
        near = situation.Point(0, -8960.0, -140.0, 83.0)
        self.assertEqual(rebind.SAME_INN, rebind.why_not(INN, member(bind=near)))

    def test_not_standing_at_the_inn_moves_nobody(self):
        self.assertEqual(rebind.NOT_AT_INN, rebind.why_not(INN, member(at=IN_TOWN_FAR)))

    def test_on_another_map_is_not_at_the_inn(self):
        self.assertEqual(rebind.NOT_AT_INN, rebind.why_not(INN, member(at=ELSEWHERE)))

    def test_a_member_with_no_fresh_position_is_left_alone(self):
        self.assertEqual(rebind.NOT_AT_INN, rebind.why_not(INN, member(at=None)))

    def test_an_unread_bind_is_left_alone(self):
        self.assertEqual(rebind.UNREAD, rebind.why_not(INN, member(bind=None)))

    def test_a_leader_with_no_bind_asks_nobody(self):
        self.assertEqual(rebind.UNREAD, rebind.why_not(None, member()))

    def test_a_dead_member_is_left_alone(self):
        self.assertEqual(rebind.DEAD, rebind.why_not(INN, member(alive=False)))


class Select(unittest.TestCase):
    def test_picks_only_the_ones_that_qualify_and_skips_the_recently_asked(self):
        members = {
            "Trog": member(),
            "Tork": member(),
            "Ot": member(bind=INN),
            "Utta": member(at=IN_TOWN_FAR),
        }
        asked, skipped = rebind.select(INN, members, recent={"Tork"})
        self.assertEqual(["Trog"], asked)
        self.assertEqual(
            {
                "Tork": rebind.BACKING_OFF,
                "Ot": rebind.SAME_INN,
                "Utta": rebind.NOT_AT_INN,
            },
            dict(skipped),
        )

    def test_constants(self):
        self.assertEqual("rebind", rebind.SOURCE)
        self.assertLess(rebind.NEAR_INN_YARDS, 100.0)
        self.assertGreaterEqual(rebind.BACKOFF_SECONDS, 600)


class Wiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (
            pathlib.Path(__file__).resolve().parent.parent / "bridge.py"
        ).read_text(encoding="utf-8")

    def test_the_strand_loop_runs_it_and_it_writes_a_plain_bind_row(self):
        a = self.text.index("    async def _strand_hearth_loop(self)")
        loop = self.text[a : self.text.index("    async def ", a + 10)]
        self.assertIn("_rebind_at_the_inn(", loop)
        b = self.text.index("    async def _rebind_at_the_inn(")
        body = self.text[b : self.text.index("\n    async def ", b + 10)]
        c = self.text.index("def _insert_rebind(")
        self.assertIn('kind="bind"', self.text[c : self.text.index("\ndef ", c + 5)])
        self.assertIn("rebind.select(", body)
        self.assertNotIn("TeleportTo", body)
        self.assertNotIn("travel_npc", body)


if __name__ == "__main__":
    unittest.main()

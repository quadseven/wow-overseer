"""A bag-room errand's counter is chosen by the members who are with the leader.

Measured on the dev realm 2026-11-17: the leader of one family stood 6,000 to
8,000 yards from its four followers when the errand started, no hearth was
available, and the vendor aim was kept on the followers' stacks. The leader
walked there alone and the followers' bags were never read, so the bag hold
never lifted (#1261, #1983).
"""

import pathlib
import unittest

import townerrand as te

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)


def at(x, y=0.0, map_id=0):
    return {"map_id": map_id, "pos_x": x, "pos_y": y}


NAMES = ["Zug", "Oz", "Uzza"]


class WhoIsWithTheLeader(unittest.TestCase):
    def test_a_follower_thousands_of_yards_off_is_not_here(self):
        pos = {"Zug": at(2500), "Oz": at(-6000), "Uzza": at(2400)}
        self.assertEqual(["Uzza", "Zug"], te.with_leader(NAMES, pos, "Zug"))

    def test_a_follower_on_another_map_is_not_here(self):
        pos = {"Zug": at(0), "Oz": at(0, map_id=1), "Uzza": at(10)}
        self.assertEqual(["Uzza", "Zug"], te.with_leader(NAMES, pos, "Zug"))

    def test_a_member_with_no_reading_is_not_here(self):
        pos = {"Zug": at(0), "Uzza": at(10)}
        self.assertEqual(["Uzza", "Zug"], te.with_leader(NAMES, pos, "Zug"))

    def test_the_stone_bringing_everyone_serves_everyone(self):
        pos = {"Zug": at(2500), "Oz": at(-6000), "Uzza": at(2400)}
        self.assertEqual(
            ["Oz", "Uzza", "Zug"], te.with_leader(NAMES, pos, "Zug", everyone=True)
        )

    def test_an_unread_leader_judges_the_whole_family(self):
        self.assertEqual(sorted(NAMES), te.with_leader(NAMES, {}, "Zug"))

    def test_far_followers_stacks_no_longer_keep_the_vendor(self):
        here = te.with_leader(
            NAMES, {"Zug": at(0), "Oz": at(-6000), "Uzza": at(5)}, "Zug"
        )
        counts = {n: (9 if n == "Oz" else 0) for n in here}
        self.assertTrue(te.bank_first(te.BAG_PRESSURE_WHY, counts, 4))
        everyone = {n: (9 if n == "Oz" else 0) for n in NAMES}
        self.assertFalse(te.bank_first(te.BAG_PRESSURE_WHY, everyone, 4))


class TheBridgeWiresIt(unittest.TestCase):
    def test_the_start_reads_only_the_members_with_the_leader(self):
        start = BRIDGE[BRIDGE.index("async def _town_errand_start(") :]
        start = start[: start.index("async def _town_errand_regroup(")]
        self.assertIn("townerrand.with_leader(", start)
        self.assertIn("bank_reads, list(names), here", start)

    def test_the_reads_count_only_those_members_bank_moves(self):
        body = BRIDGE[BRIDGE.index("def _bank_first_reads(") :]
        body = body[: body.index("\n\n\n")]
        self.assertIn("m.character in here", body)


if __name__ == "__main__":
    unittest.main()

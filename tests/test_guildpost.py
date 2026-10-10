"""The guild's own post, and the hearthstone for a walker the ground refuses (#625).

Measured on wow-dev 2026-10-05: 293 letters with items between guildmates sat
unopened, and both guild tailors' mailbox walks ended "the ground toward the
mailbox does not hold" seven times of seven.
"""

import pathlib
import unittest

import guildpost
import guildroute

BRIDGE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()


def row(receiver, mail_id, guid, **over):
    base = {
        "receiver": receiver,
        "mail_id": mail_id,
        "item_guid": guid,
        "name": "Woolen Bag",
        "delivered": 1,
        "cod": 0,
        "online": 1,
    }
    base.update(over)
    return base


def letters(*rows):
    return [x for x in map(guildpost.letter_from_row, rows) if x]


class TheGuildTakesItsPost(unittest.TestCase):
    def test_a_member_with_letters_walks_and_takes_each_out(self):
        plan, _ = guildpost.visits(
            letters(row("Bodo", 7, 70), row("Bodo", 8, 80)), {"Bodo"}
        )
        self.assertEqual(len(plan), 1)
        self.assertEqual(
            [t.command for t in plan[0].takes],
            ["take-item mail:7 item:70", "take-item mail:8 item:80"],
        )
        self.assertEqual(plan[0].walk_command(), "walk-to-mailbox max:600")

    def test_the_most_letters_go_first_and_the_walks_are_bounded(self):
        rows = [row("Zed", 1, 10)]
        for n in range(guildpost.WALKS_PER_PASS + 1):
            rows += [
                row("M%d" % n, 100 + 2 * n, 1000 + n),
                row("M%d" % n, 101 + 2 * n, 2000 + n),
            ]
        plan, notes = guildpost.visits(
            letters(*rows), {"Zed"} | {"M%d" % n for n in range(9)}
        )
        self.assertEqual(len(plan), guildpost.WALKS_PER_PASS)
        self.assertNotIn("Zed", [v.receiver for v in plan])
        self.assertTrue(any("walks this pass" in n for n in notes))

    def test_the_roster_offline_and_busy_are_left_alone(self):
        rows = letters(row("Og", 1, 10), row("Away", 2, 20), row("Busy", 3, 30))
        plan, _ = guildpost.visits(rows, {"Og", "Busy"}, busy={"Busy"}, roster={"Og"})
        self.assertEqual(plan, [])

    def test_the_takes_fit_the_free_slots(self):
        rows = letters(*[row("Bodo", n, 10 + n) for n in range(1, 5)])
        plan, _ = guildpost.visits(rows, {"Bodo"}, free_slots={"Bodo": 2})
        self.assertEqual(len(plan[0].takes), 2)
        plan, notes = guildpost.visits(rows, {"Bodo"}, free_slots={"Bodo": 0})
        self.assertEqual(plan, [])
        self.assertIn("no free bag slot", notes[0])

    def test_a_letter_in_its_delay_or_on_cash_on_delivery_is_not_taken(self):
        rows = letters(row("Bodo", 1, 10, delivered=0), row("Bodo", 2, 20, cod=500))
        self.assertEqual(guildpost.visits(rows, {"Bodo"})[0], [])

    def test_an_unreadable_row_is_dropped(self):
        self.assertEqual(letters({"receiver": "Bodo", "mail_id": None}), [])

    def test_the_bridge_runs_the_pass_on_its_own_loop(self):
        self.assertEqual(BRIDGE.count('_Pass("_guild_post_loop"),'), 1)
        self.assertIn("guildpost.visits(", BRIDGE)


class AGroundedWalkerHearthsOut(unittest.TestCase):
    ENDED = guildroute.WalkAnswer(
        guildroute.ENDED,
        "Arran cannot walk to a mailbox: the ground toward the mailbox does not hold",
    )

    def test_the_ground_refusal_is_recognized(self):
        self.assertTrue(guildroute.grounded(self.ENDED))
        self.assertFalse(
            guildroute.grounded(
                guildroute.WalkAnswer(guildroute.ENDED, "Arran is in combat")
            )
        )
        self.assertFalse(
            guildroute.grounded(
                guildroute.WalkAnswer(guildroute.WALKING, "does not hold")
            )
        )

    def test_once_an_hour_and_never_for_the_roster(self):
        due = guildroute.hearth_due
        self.assertTrue(due("Arran", {}, 100.0, False))
        self.assertFalse(due("Og", {}, 100.0, True))
        self.assertFalse(due("Arran", {"Arran": 100.0}, 200.0, False))
        self.assertTrue(
            due(
                "Arran",
                {"Arran": 100.0},
                100.0 + guildroute.GROUND_HEARTH_SECONDS,
                False,
            )
        )

    def test_every_guild_walk_reader_hearths_a_grounded_walker(self):
        body = BRIDGE[BRIDGE.index("    async def _await_mail_walk(") :]
        body = body[: body.index("\n    def _guild_walk_cap(")]
        self.assertIn("guildroute.grounded(answer)", body)
        self.assertIn("await self._hearth_grounded(holder)", body)


if __name__ == "__main__":
    unittest.main()

"""Guild chat realism (#1636): the social layer's own lines.

The feed a reader sees should read like people, not a script: an ask that
nobody answered lapses quietly, the same member does not re-ask the same
dungeon in the same sitting, a guild channel is not mostly LFG posts, an
answer names loot only when the answerer would gain it there, and the
finder's bookkeeping is not narrated in guild chat.
"""

import datetime
import pathlib
import unittest
from unittest import mock

import guildpug as gp
import guildsocial as gs
from test_guildsocial import (
    DEADMINES,
    MAGE,
    NOW,
    PRIEST,
    ROGUE,
    WARLOCK,
    ask,
    cape_need,
    mate,
    plan,
    yes,
)
from test_guildsocial_bridge import _Conn, bridge


def robe_need(name):
    return gs.Need(name, "wailing", "Robe", entry=2, gain=6.0, slot="chest")


class ExpiryIsSilent(unittest.TestCase):
    def test_an_unanswered_ask_expires_without_a_guild_line(self):
        old = ask(7, "Auren", expires_at=NOW - datetime.timedelta(seconds=1))
        out = plan(
            [mate("Auren", 20, ROGUE), mate("Zappy", 20, MAGE)],
            asks=[old],
            answers=[yes(1, 7, "Zappy", "dps")],
        )
        self.assertEqual(len(out.expire), 1)
        ask_id, asker, line = out.expire[0]
        self.assertEqual((ask_id, asker), (7, "Auren"))
        self.assertEqual(line, "")


class TheSameDoorStaysQuietForHours(unittest.TestCase):
    def test_an_hour_after_expiry_the_same_door_is_not_asked_again(self):
        old = ask(
            7,
            "Auren",
            state="expired",
            created_at=NOW - datetime.timedelta(minutes=60),
        )
        out = plan(
            [mate("Auren", 20, ROGUE)],
            asks=[old],
            needs={"Auren": [cape_need("Auren")]},
        )
        self.assertEqual(out.posts, ())

    def test_another_door_may_still_be_asked_in_the_same_sitting(self):
        old = ask(
            7,
            "Auren",
            state="expired",
            created_at=NOW - datetime.timedelta(minutes=60),
        )
        out = plan(
            [mate("Auren", 20, ROGUE)],
            asks=[old],
            needs={"Auren": [robe_need("Auren")]},
        )
        self.assertEqual([p.target for p in out.posts], ["wailing"])

    def test_the_door_opens_again_after_the_long_cooldown(self):
        old = ask(
            7,
            "Auren",
            state="expired",
            created_at=NOW
            - datetime.timedelta(minutes=gs.ASK_REPEAT_COOLDOWN_MINUTES + 1),
        )
        out = plan(
            [mate("Auren", 20, ROGUE)],
            asks=[old],
            needs={"Auren": [cape_need("Auren")]},
        )
        self.assertEqual([p.target for p in out.posts], ["deadmines"])

    def test_the_bridge_reads_asks_back_over_the_long_cooldown(self):
        # The per-door bar can only bite if the bridge hands plan_pass the
        # asks that carry it: the read window must cover the repeat cooldown.
        self.assertGreaterEqual(gs.ASKS_READ_MINUTES, gs.ASK_REPEAT_COOLDOWN_MINUTES)
        source = pathlib.Path(bridge.__file__).read_text(encoding="utf-8")
        self.assertIn("guildsocial.ASKS_READ_MINUTES", source)


class FewerOpenAsks(unittest.TestCase):
    def test_three_open_asks_leave_the_channel_to_the_guild(self):
        live = [
            ask(7, "Auren"),
            ask(8, "Bree", target="wailing"),
            ask(9, "Cole", target="stockades"),
        ]
        out = plan(
            [
                mate("Auren", 20, ROGUE),
                mate("Bree", 20, MAGE),
                mate("Cole", 20, WARLOCK),
                mate("Dana", 20, PRIEST),
            ],
            asks=live,
            needs={"Dana": [robe_need("Dana")]},
            room=10,
        )
        self.assertEqual(out.posts, ())
        self.assertLess(gs.MAX_OPEN_ASKS_PER_GUILD, 8)


class AnswersNameOnlyLootTheyGain(unittest.TestCase):
    def test_a_need_at_another_door_is_not_named_here(self):
        line = gs.answer_line("Vugg", "dps", gs.NEED, DEADMINES, robe_need("Vugg"))
        self.assertNotIn("Robe", line)

    def test_a_need_with_no_gain_at_the_door_is_not_named(self):
        flat = gs.Need("Vugg", "deadmines", "Cape of the Black Baron", entry=5193)
        line = gs.answer_line("Vugg", "dps", gs.NEED, DEADMINES, flat)
        self.assertNotIn("Cape of the Black Baron", line)

    def test_a_real_gain_at_the_door_is_named(self):
        line = gs.answer_line("Vugg", "dps", gs.NEED, DEADMINES, cape_need("Vugg"))
        self.assertIn("Cape of the Black Baron", line)


class PugNarrationIsNotGuildChat(unittest.TestCase):
    def joins(self):
        from test_guildpug import call, four_yeses, guild_four, pug, pug_plan

        return pug_plan(
            guild_four(),
            [ask(7, "Auren", created_at=NOW - datetime.timedelta(minutes=6))],
            four_yeses(),
            calls={7: call()},
            pugs=[pug("Mercy")],
        ).joins

    def test_a_join_carries_no_line_for_the_guild(self):
        joins = self.joins()
        self.assertEqual(len(joins), 1)
        self.assertEqual(joins[0].told_guild, "")
        # The pug's own whisper to the asker is still said.
        self.assertIn("Deadmines", joins[0].said)

    def test_the_bridge_speaks_no_guild_line_for_a_join(self):
        sql, said = [], []
        pp = gp.PugPass(joins=tuple(self.joins()))
        with mock.patch.multiple(
            bridge,
            _connect=lambda: _Conn(sql),
            _insert_speak=lambda cmd: said.append(
                (cmd.target_name, cmd.channel, cmd.text, cmd.whisper_to)
            ),
        ):
            bridge._write_guild_pugs(pp)
        self.assertEqual([s for s in said if s[1] == "guild"], [])
        self.assertEqual(len([s for s in said if s[1] == "whisper"]), 1)

    def test_the_bridge_still_speaks_a_told_line_when_one_is_carried(self):
        # Another caller (the class quest escalation) carries its own line
        # on the same Join shape; the writer's change is only to skip an
        # empty one.
        sql, said = [], []
        pp = gp.PugPass(
            joins=(gp.Join(8, "Mercy", "healer", "I can heal, inv", "Bree", "Got a healer"),)
        )
        with mock.patch.multiple(
            bridge,
            _connect=lambda: _Conn(sql),
            _insert_speak=lambda cmd: said.append(
                (cmd.target_name, cmd.channel, cmd.text, cmd.whisper_to)
            ),
        ):
            bridge._write_guild_pugs(pp)
        self.assertIn(("Bree", "guild", "Got a healer", ""), said)


class ARepostIsNotTheSameSentence(unittest.TestCase):
    def test_the_second_ask_for_a_door_reads_differently_from_the_first(self):
        first = gs.ask_line(
            "Auren", DEADMINES, ["tank", "healer", "dps", "dps"], cape_need("Auren")
        )
        old = ask(
            7,
            "Auren",
            state="expired",
            created_at=NOW
            - datetime.timedelta(minutes=gs.ASK_REPEAT_COOLDOWN_MINUTES + 1),
        )
        out = plan(
            [mate("Auren", 20, ROGUE)],
            asks=[old],
            needs={"Auren": [cape_need("Auren")]},
        )
        self.assertEqual(len(out.posts), 1)
        self.assertNotEqual(out.posts[0].said, first)
        self.assertIn("Cape of the Black Baron", out.posts[0].said)


if __name__ == "__main__":
    unittest.main()

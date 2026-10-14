"""A class quest ask nobody in the guild answers goes to the server (#871).

On 2026-10-14 four members had asked the guild 2 to 7 times for Call of Fire
or Redemption over 5 to 14 hours and drawn no yes at all. From
classask.ESCALATE_AFTER_ASKS asks in a row with no party, the ask reaches
farther, is called in the faction's public channel, and a random bot of the
asker's side answers it; every ask still short names who did not come and why.
The fixtures are test_classask.py's: Bigzug of Bonkers, level 20 on Kalimdor,
holding a group quest that wants two helpers.
"""

import asyncio
import datetime
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import classask  # noqa: E402
import classparty  # noqa: E402
import guildjobs  # noqa: E402
import guildpug  # noqa: E402
import guildsocial as gs  # noqa: E402
from test_classask import (  # noqa: E402
    CAVE,
    NEAR,
    asker,
    done_ask,
    group_book,
    qask,
)
from test_guildsocial import NOW, ask, mate, yes  # noqa: E402
from test_guildsocial_bridge import bridge  # noqa: E402

HUMAN, ORC = 1, 2
KALIMDOR = 1
SIDE = {CAVE: "Alliance"}


def at(dx, dy=0.0):
    return (NEAR[0] + dx, NEAR[1] + dy)


def member(name, level=20, where=(0.0, 0.0), map_id=KALIMDOR, **kw):
    return mate(
        name, level, 1, guild=kw.pop("guild", CAVE), at=at(*where), map_id=map_id, **kw
    )


def pug(name, level=20, where=(0.0, 0.0), map_id=KALIMDOR, race=HUMAN, **kw):
    return mate(name, level, 1, guild="", at=at(*where), map_id=map_id, race=race, **kw)


def help_after(tries):
    """Bigzug's help for Group Job once `tries` asks for it came to nothing."""
    asks = [done_ask(20 * (n + 1)) for n in range(tries)]
    (h,) = guildjobs.class_helps(asker(), group_book(), asks=asks)
    return h


def call(ask_id=1, minutes=2):
    return guildpug.Call(
        ask_id,
        "Bigzug",
        (gs.DPS, gs.DPS),
        "",
        NOW - datetime.timedelta(minutes=minutes),
    )


def escalate(helps, mates, pugs=(), held=None, asks=None, answers=(), **kw):
    held = held or {}
    asks = [qask(1)] if asks is None else asks
    quest_pass = classask.plan_pass(helps, mates, held, asks, list(answers), NOW)
    kw.setdefault("factions", SIDE)
    return quest_pass, classask.plan_escalation(
        quest_pass, helps, mates, held, asks, list(answers), NOW, pugs=pugs, **kw
    )


class TheTries(unittest.TestCase):
    def test_the_help_carries_the_asks_in_a_row_that_came_to_no_party(self):
        self.assertEqual(help_after(0).tries, 0)
        self.assertEqual(help_after(2).tries, 2)

    def test_the_ask_escalates_from_the_set_number_of_tries(self):
        self.assertFalse(
            classask.escalated(help_after(classask.ESCALATE_AFTER_ASKS - 1))
        )
        self.assertTrue(classask.escalated(help_after(classask.ESCALATE_AFTER_ASKS)))

    def test_the_server_gets_two_tries_before_the_member_yields(self):
        last = guildjobs.CLASS_ASK_STREAK_MAX - 1
        self.assertTrue(classask.escalated(help_after(last)))
        self.assertEqual(
            guildjobs.CLASS_ASK_STREAK_MAX - classask.ESCALATE_AFTER_ASKS, 2
        )
        asks = [done_ask(10 * (n + 1)) for n in range(guildjobs.CLASS_ASK_STREAK_MAX)]
        self.assertEqual(guildjobs.class_helps(asker(), group_book(), asks=asks), [])


class TheCall(unittest.TestCase):
    def test_an_escalated_ask_is_called_in_the_public_channel_once(self):
        _q, out = escalate([help_after(2)], [member("Bigzug")])
        (made,) = out.calls
        self.assertEqual((made.ask_id, made.asker), (1, "Bigzug"))
        self.assertEqual(made.seats, (gs.DPS, gs.DPS))
        self.assertIn("Group Job", made.said)
        self.assertIn("Thunder Lizard", made.said)
        self.assertTrue(made.said.isascii())
        self.assertLessEqual(len(made.said), 255)
        _q, again = escalate([help_after(2)], [member("Bigzug")], calls={1: call()})
        self.assertEqual(again.calls, ())

    def test_an_ask_short_of_its_tries_is_not_called(self):
        _q, out = escalate([help_after(1)], [member("Bigzug")], pugs=[pug("Rando")])
        self.assertEqual((out.calls, out.joins), ((), ()))
        self.assertIn("server: not asked before try 3", out.silences[0].line)

    def test_with_pick_up_groups_off_nothing_goes_to_the_server(self):
        _q, out = escalate(
            [help_after(2)],
            [member("Bigzug")],
            pugs=[pug("Rando")],
            calls={1: call()},
            pugs_on=False,
        )
        self.assertEqual((out.calls, out.joins), ((), ()))
        self.assertIn("pick-up groups are off", out.silences[0].line)


class TheRandomBots(unittest.TestCase):
    def joins(self, pugs, answers=(), **kw):
        kw.setdefault("calls", {1: call()})
        _q, out = escalate(
            [help_after(2)], [member("Bigzug")], pugs=pugs, answers=answers, **kw
        )
        return out

    def test_the_nearest_free_bot_of_the_side_in_the_band_answers(self):
        out = self.joins([pug("Far", where=(3000.0,)), pug("Near", where=(400.0,))])
        self.assertEqual([j.member for j in out.joins], ["Near", "Far"])
        for j in out.joins:
            self.assertEqual((j.ask_id, j.role, j.asker), (1, gs.DPS, "Bigzug"))
            self.assertIn("Group Job", j.said)
            self.assertIn(j.member, j.told_guild)
        self.assertEqual(out.silences, ())

    def test_a_bot_that_cannot_come_does_not_and_the_line_counts_why(self):
        out = self.joins(
            [
                pug("Horde", race=ORC),
                pug("Away", map_id=0),
                pug("Low", level=12),
                pug("Gone", where=(classask.ESCALATED_REACH_YARDS + 10.0,)),
                pug("Asleep", online=0),
            ]
        )
        self.assertEqual(out.joins, ())
        line = out.silences[0].line
        self.assertIn("server: 5 random bot(s) read", line)
        for why in (
            classask.OTHER_SIDE,
            classask.OTHER_MAP,
            classask.OUT_OF_BAND,
            classask.TOO_FAR,
            "offline",
        ):
            self.assertIn("1 " + why, line)

    def test_a_call_answers_from_the_next_minute(self):
        out = self.joins([pug("Near")], calls={1: call(minutes=0)})
        self.assertEqual(out.joins, ())
        self.assertIn("called, answered from the next minute", out.silences[0].line)

    def test_a_bot_on_another_ask_or_refused_for_this_one_does_not_answer(self):
        dungeon = ask(2, "Auren", guild=CAVE)
        _q, out = escalate(
            [help_after(2)],
            [member("Bigzug")],
            pugs=[pug("Busy"), pug("Nope")],
            asks=[qask(1), dungeon],
            answers=[yes(7, 2, "Busy", "healer", gs.PUG)],
            calls={1: call()},
            refused={1: frozenset({"Nope"})},
        )
        self.assertEqual(out.joins, ())
        line = out.silences[0].line
        self.assertIn("1 " + classask.ANSWERING, line)
        self.assertIn("1 " + classask.REFUSED, line)

    def test_the_guild_answers_first_and_the_server_fills_the_rest(self):
        mates = [member("Bigzug"), member("Chill", where=(50.0,))]
        quest_pass, out = escalate(
            [help_after(2)], mates, pugs=[pug("Rando")], calls={1: call()}
        )
        self.assertEqual([r.member for r in quest_pass.replies], ["Chill"])
        self.assertEqual([j.member for j in out.joins], ["Rando"])

    def test_a_full_ask_goes_nowhere(self):
        answers = [yes(1, 1, "Chill", "dps", "help"), yes(2, 1, "Dread", "dps", "help")]
        mates = [member("Bigzug"), member("Chill"), member("Dread")]
        _q, out = escalate([help_after(2)], mates, pugs=[pug("Rando")], answers=answers)
        self.assertEqual(out, classask.Escalation())


class TheReach(unittest.TestCase):
    def test_an_escalated_ask_reaches_a_guildmate_farther_away(self):
        mates = [member("Bigzug"), member("Across", where=(3000.0,))]
        self.assertGreater(3000.0, classask.HELPER_REACH_YARDS)
        fresh, _o = escalate([help_after(0)], mates)
        self.assertEqual(fresh.replies, ())
        later, _o = escalate([help_after(2)], mates)
        self.assertEqual([r.member for r in later.replies], ["Across"])

    def test_the_wider_reach_is_walked_inside_the_meeting_clock(self):
        # A bot runs about 7 yards a second.
        self.assertLess(classask.ESCALATED_REACH_YARDS / 7.0, classparty.MEET_SECONDS)


class WhoDidNotCome(unittest.TestCase):
    def test_each_guildmate_is_named_with_why_it_did_not_come(self):
        mates = [
            member("Bigzug"),
            member("Sleepy"),
            member("Away", map_id=0),
            member("Low", level=10),
            member("Gone", where=(5000.0,)),
            member("Other", guild="Cave"),
        ]
        _q, out = escalate([help_after(0)], mates, held={"Sleepy": "offline"})
        (silence,) = out.silences
        self.assertEqual((silence.ask_id, silence.short, silence.tries), (1, 2, 0))
        line = silence.line
        self.assertTrue(
            line.startswith(
                "class ask: Bigzug's Group Job ask (ask 1, try 1) is 2 short"
            )
        )
        self.assertIn("offline: Sleepy", line)
        self.assertIn("%s: Away" % classask.OTHER_MAP, line)
        self.assertIn("%s: Low" % classask.OUT_OF_BAND, line)
        self.assertIn("%s: Gone" % classask.TOO_FAR, line)
        self.assertNotIn("Other", line)

    def test_a_guildmate_on_another_ask_says_so(self):
        mates = [member("Bigzug"), member("Ghoul")]
        (ghoul,) = guildjobs.class_helps(asker("Ghoul"), group_book())
        helps = [help_after(0), ghoul]
        _q, out = escalate(helps, mates, asks=[qask(1), qask(2, "Ghoul")])
        self.assertEqual([s.ask_id for s in out.silences], [1, 2])
        self.assertIn("%s: Ghoul" % classask.ANSWERING, out.silences[0].line)

    def test_an_ask_with_nobody_else_in_the_guild_says_so(self):
        _q, out = escalate([help_after(0)], [member("Bigzug")])
        self.assertIn("guild: nobody else read", out.silences[0].line)


class _Realm:
    """The ask and answer tables, kept in memory, for TwoHours."""

    def __init__(self):
        self.asks, self.answers, self.calls = [], [], {}

    def closed_for_streak(self, now):
        return guildjobs.quest_asks_from_rows(
            [
                {
                    "asker": a.asker,
                    "target": a.target,
                    "state": a.state,
                    "age": int((now - a.created_at).total_seconds() // 60),
                    "yeses": sum(1 for w in self.answers if w.ask_id == a.id),
                }
                for a in self.asks
            ]
        )

    def _set(self, ids, state):
        self.asks = [
            gs.Ask(**{**a.__dict__, "state": state}) if a.id in ids else a
            for a in self.asks
        ]

    def write(self, quest_pass, esc, now):
        self._set({e[0] for e in quest_pass.expire}, gs.EXPIRED)
        self._set(set(quest_pass.cancel), gs.CANCELLED)
        self._set(set(quest_pass.filled), gs.FILLED)
        gone = set(quest_pass.withdraw)
        self.answers = [w for w in self.answers if w.id not in gone]
        for post in quest_pass.posts:
            self.asks.append(
                qask(
                    len(self.asks) + 1,
                    post.asker,
                    roles_needed=post.roles_needed,
                    created_at=now,
                    expires_at=now + datetime.timedelta(minutes=post.minutes),
                )
            )
        new = [(r.ask_id, r.member, r.stance) for r in quest_pass.replies]
        new += [(j.ask_id, j.member, gs.PUG) for j in esc.joins]
        for ask_id, name, stance in new:
            self.answers.append(
                yes(len(self.answers) + 100, ask_id, name, "dps", stance)
            )
        for c in esc.calls:
            self.calls[c.ask_id] = guildpug.Call(
                c.ask_id, c.asker, c.seats, c.said, now
            )


class TwoHours(unittest.TestCase):
    """No class quest help ask waits longer than two hours for its party: a
    member nobody in its guild can reach asks, is not answered, asks again,
    then calls the server, and the one random bot of its side in reach makes
    its party, all well inside two hours of the first ask. The realm runs for
    SIMULATED_MINUTES, longer than two hours, so the bound is the test's to
    fail and not the loop's."""

    SIMULATED_MINUTES = 4 * 60

    def run_realm(self, mates, pugs):
        """(minute the party formed or None, its run, first ask's minute, realm)
        for Bigzug asking for Group Job each minute of SIMULATED_MINUTES."""
        realm, board, book = _Realm(), classparty.Board(), group_book()
        first = None
        for minute in range(self.SIMULATED_MINUTES + 1):
            now = NOW + datetime.timedelta(minutes=minute)
            helps = guildjobs.class_helps(
                asker(), book, asks=realm.closed_for_streak(now)
            )
            quest_pass = classask.plan_pass(
                helps, mates + pugs, {}, realm.asks, realm.answers, now
            )
            esc = classask.plan_escalation(
                quest_pass,
                helps,
                mates,
                {},
                realm.asks,
                realm.answers,
                now,
                calls=realm.calls,
                pugs=pugs,
                factions=SIDE,
            )
            free = {m.name: m for m in mates + pugs}
            starts = classparty.plan_starts(
                realm.asks,
                realm.answers,
                quest_pass,
                helps,
                free,
                board,
                now,
                0.0,
                book,
            )
            if starts:
                return minute, starts[0], first, realm
            realm.write(quest_pass, esc, now)
            if first is None and realm.asks:
                first = minute
        return None, None, first, realm

    def test_a_lone_asker_has_a_party_with_a_random_bot_inside_two_hours(self):
        mates = [member("Bigzug"), member("Away", map_id=0)]
        pugs = [pug("Horde", race=ORC), pug("Rando", where=(3200.0,))]
        minute, run, first, realm = self.run_realm(mates, pugs)
        assert minute is not None and run is not None, "no party in four hours"
        self.assertEqual((run.leader, run.helpers), ("Bigzug", ("Rando",)))
        self.assertEqual(first, 0)
        self.assertLessEqual(minute, 120)
        # ESCALATE_AFTER_ASKS asks to the guild alone, then the next try is
        # called to the server and the random bot fills it.
        tries = [a for a in realm.asks if a.asker == "Bigzug"]
        guild_only = tries[: classask.ESCALATE_AFTER_ASKS]
        self.assertEqual(len(tries), classask.ESCALATE_AFTER_ASKS + 1)
        self.assertEqual([a.id for a in guild_only if a.id in realm.calls], [])
        self.assertIn(tries[-1].id, realm.calls)

    def test_every_try_of_a_run_nobody_answers_is_made_inside_two_hours(self):
        """The worst case: no random bot of the side is in reach either. The
        run's CLASS_ASK_STREAK_MAX asks, the server's tries among them, are all
        posted and called inside two hours of the first, and then the member
        yields to levelling for guildjobs.CLASS_STALL_HOLD_MINUTES rather than
        posting a fifth that the next pass cancels."""
        mates = [member("Bigzug"), member("Away", map_id=0)]
        pugs = [pug("Horde", race=ORC), pug("Far", where=(9000.0,))]
        minute, _run, first, realm = self.run_realm(mates, pugs)
        self.assertIsNone(minute)
        self.assertEqual(first, 0)
        tries = [a for a in realm.asks if a.asker == "Bigzug"]
        run = tries[: guildjobs.CLASS_ASK_STREAK_MAX]
        called = [a.id for a in run if a.id in realm.calls]
        self.assertEqual(called, [a.id for a in run[classask.ESCALATE_AFTER_ASKS :]])
        self.assertLessEqual(run[-1].created_at - NOW, datetime.timedelta(hours=2))
        hold = datetime.timedelta(minutes=guildjobs.CLASS_STALL_HOLD_MINUTES)
        for later in tries[guildjobs.CLASS_ASK_STREAK_MAX :]:
            self.assertGreaterEqual(later.created_at - run[-1].created_at, hold)


class TheBridge(unittest.TestCase):
    def facts(self, answers=()):
        return {
            "asks": [qask(1)],
            "answers": list(answers),
            "now": NOW,
            "busy": set(),
            "family": set(),
            "pug_calls": {1: call()},
        }

    def test_the_bridge_hands_the_random_bots_to_the_server_part(self):
        row = {
            "name": "Rando",
            "level": 20,
            "class_id": 1,
            "map_id": KALIMDOR,
            "race": HUMAN,
            "in_combat": 0,
            "health": 300,
            "group_leader": 0,
            "guild_name": "",
            "pos_x": NEAR[0] + 200.0,
            "pos_y": NEAR[1],
            "online": 1,
        }
        _q, _h, _n, _p, esc = bridge._class_ask_pass(
            self.facts(),
            [member("Bigzug")],
            {},
            {},
            [help_after(2)],
            pug_rows=[row],
        )
        self.assertEqual([j.member for j in esc.joins], ["Rando"])

    def test_a_random_bot_that_said_yes_stays_on_the_ask(self):
        row = {
            "name": "Rando",
            "level": 20,
            "class_id": 1,
            "map_id": KALIMDOR,
            "race": HUMAN,
            "in_combat": 0,
            "health": 300,
            "group_leader": 0,
            "guild_name": "",
            "pos_x": NEAR[0] + 200.0,
            "pos_y": NEAR[1],
            "online": 1,
        }
        said = [yes(5, 1, "Rando", "dps", gs.PUG)]
        quest_pass, _h, _n, _p, _e = bridge._class_ask_pass(
            self.facts(said),
            [member("Bigzug")],
            {},
            {},
            [help_after(2)],
            pug_rows=[row],
        )
        self.assertEqual(quest_pass.withdraw, ())
        gone, _h, _n, _p, _e = bridge._class_ask_pass(
            self.facts(said), [member("Bigzug")], {}, {}, [help_after(2)]
        )
        self.assertEqual(gone.withdraw, (5,))

    def test_the_random_bots_are_read_only_for_an_escalated_ask(self):
        reads = []

        def fetch(span, bounds):
            reads.append(span)
            return []

        with mock.patch.object(bridge, "_fetch_guild_pugs", fetch):
            asyncio.run(bridge._class_pug_rows(self.facts(), [help_after(0)], None))
            self.assertEqual(reads, [])
            asyncio.run(bridge._class_pug_rows(self.facts(), [help_after(2)], None))
        band = classask.LEVEL_BAND
        self.assertEqual(reads, [(20 - band, 20 + band)])

    def test_each_short_ask_is_logged_once_until_its_reasons_change(self):
        bridge._CLASS_SILENCES.clear()
        quiet = classask.Silence(1, "Bigzug", "Group Job", 2, 2, (), "x")
        with self.assertLogs(bridge.log, "INFO") as seen:
            bridge._log_class_silences([quiet])
            bridge._log_class_silences([quiet])
            bridge._log_class_silences(
                [classask.Silence(1, "Bigzug", "Group Job", 2, 2, (), "y")]
            )
        self.assertEqual(len(seen.output), 2)
        bridge._log_class_silences([])
        self.assertEqual(bridge._CLASS_SILENCES, {})


if __name__ == "__main__":
    unittest.main()

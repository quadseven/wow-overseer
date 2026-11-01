"""A second, narrower kind of order-giver: report orders only (quadseven/mod-overseer#1238).

THE SHAPE OF THE RISK, BOTH WAYS. The bridge's allowlist was all-or-nothing:
an id on it can whisper any playerbot command, speak through a character,
spend its gold and move it across the world. A report-giver identity exists
so an agent can ask the family how it is - the `stats` lines waiting on
quadseven/mod-overseer#7 are the model - without holding that power. Put the new id on
the ordinary allowlist and the scoping is a promise, not a mechanism: the
first natural-language line it sends goes to the inner voice, which may pick
ANY vocabulary entry, movement included. Leave it off every list and its
lines are refused like any stranger's, which is where this started.

So the scope lives in core.parse_directive, the same seam that already
decides who is answered at all: an id in `report_ids` (and not in
`allowed_ids`), speaking in the dedicated overseer channel, keeps exactly
the decisions that only READ the world - a raw command that is one of the
report entries, a roster, a digest - and every decision that would change
the world is refused with a Reply that says so, rather than silently
dropped: a refused order the giver cannot see reads exactly like a lost
one. Outside that channel the scoped id is not answered at all (slice 7).

THE WIRING HALF IS A SOURCE CONTRACT, for the reason tests/
test_channel_isolation.py gives: bridge.py imports discord and pymysql at
module level, so the stdlib-only suite pins its wiring as text - the
report set is built from its own environment variable, on_message stops
refusing a message solely for being bot-authored when the author is that
giver (a bot identity is a bot; the blanket refusal at the top of
on_message is the other half of why its lines never landed), and the set
is handed to parse_directive.
"""

import pathlib
import unittest

import core
from core import (
    DigestQuery,
    FanoutCommand,
    InsertCommand,
    Reply,
    RosterQuery,
    parse_directive,
)

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

ME = "1000"  # the operator
BOT = "2002"  # the report-only giver
STRANGER = "7777"
ALLOWED = frozenset({ME})
REPORTERS = frozenset({BOT})
BOT_SRC = f"discord:{BOT}"


class AReportOrderIsAnsweredLikeTheOperators(unittest.TestCase):
    """Slice 1: the seam itself. A report order from the scoped id produces
    the same decision the operator's identical line produces, with the
    scoped id as its source so the rows it writes are attributable."""

    def test_stats_from_the_reporter(self):
        out = parse_directive(
            "@Zug stats", BOT, ALLOWED, dedicated=True, report_ids=REPORTERS
        )
        self.assertEqual(out, [InsertCommand("Zug", "stats", BOT_SRC)])

    def test_the_whole_report_vocabulary_from_the_reporter(self):
        for word in ("stats", "quests", "talents", "los"):
            out = parse_directive(
                f"@Zug {word}", BOT, ALLOWED, dedicated=True, report_ids=REPORTERS
            )
            self.assertEqual(out, [InsertCommand("Zug", word, BOT_SRC)], word)

    def test_the_operator_is_untouched_by_the_scope(self):
        out = parse_directive("@Zug stats", ME, ALLOWED, report_ids=REPORTERS)
        self.assertEqual(out, [InsertCommand("Zug", "stats", f"discord:{ME}")])

    def test_case_and_spacing_fold_like_the_operators(self):
        # voice folds case before the raw check, for every giver; the scope
        # folds the same way, so "STATS" from the reporter is the operator's
        # "STATS" - same decision, original case and all.
        out = parse_directive(
            "@Zug  STATS", BOT, ALLOWED, dedicated=True, report_ids=REPORTERS
        )
        self.assertEqual(out, [InsertCommand("Zug", "STATS", BOT_SRC)])


class TheFanoutLinesFromTheTicket(unittest.TestCase):
    """Slice 2: the two orders actually waiting on quadseven/mod-overseer#7 are group
    lines, so a scope that only admitted single-character reports would
    refuse the very orders it exists to accept."""

    def test_a_guild_stats_line(self):
        out = parse_directive(
            '@guild "Rangers of Vengeance" stats',
            BOT,
            ALLOWED,
            dedicated=True,
            report_ids=REPORTERS,
        )
        self.assertEqual(
            out, [FanoutCommand("guild Rangers of Vengeance", "stats", BOT_SRC)]
        )

    def test_a_faction_stats_line(self):
        out = parse_directive(
            "@horde stats", BOT, ALLOWED, dedicated=True, report_ids=REPORTERS
        )
        self.assertEqual(out, [FanoutCommand("horde", "stats", BOT_SRC)])

    def test_the_same_lines_from_the_operator_agree_but_for_source(self):
        mine = parse_directive(
            '@guild "Rangers of Vengeance" stats',
            BOT,
            ALLOWED,
            dedicated=True,
            report_ids=REPORTERS,
        )
        theirs = parse_directive('@guild "Rangers of Vengeance" stats', ME, ALLOWED)
        self.assertEqual(
            [(type(d), d.expression, d.command) for d in mine],
            [(type(d), d.expression, d.command) for d in theirs],
        )


class WhatChangesTheWorldIsRefused(unittest.TestCase):
    """Slice 3: every road to a state change is closed to the scoped id,
    and the refusal is a said Reply, not silence."""

    def assert_refused(self, text, **kw):
        out = parse_directive(
            text, BOT, ALLOWED, dedicated=True, report_ids=REPORTERS, **kw
        )
        self.assertEqual(out, [Reply(core.REPORT_REFUSAL)], text)

    def test_a_raw_movement_order(self):
        self.assert_refused("@Zug follow")

    def test_a_fanned_out_movement_order(self):
        self.assert_refused("@horde grind")

    def test_a_gm_command(self):
        self.assert_refused("@Zug .additem 12345")

    def test_a_spoken_line(self):
        self.assert_refused("@Zug /say hello")

    def test_a_natural_language_order(self):
        # The inner voice may pick any vocabulary entry for one of these,
        # movement included - so no NL line is a report, however read-only
        # its phrasing sounds.
        self.assert_refused("@Zug tell me how you are doing")

    def test_a_report_entry_with_arguments_is_not_the_report(self):
        self.assert_refused("@Zug stats please")

    def test_a_mixed_message_answers_the_report_and_refuses_the_rest(self):
        out = parse_directive(
            "@Zug stats\n@Zug follow",
            BOT,
            ALLOWED,
            dedicated=True,
            report_ids=REPORTERS,
        )
        self.assertEqual(
            out,
            [InsertCommand("Zug", "stats", BOT_SRC), Reply(core.REPORT_REFUSAL)],
        )

    def test_a_stranger_is_still_ignored_entirely(self):
        self.assertEqual(
            parse_directive("@Zug stats", STRANGER, ALLOWED, report_ids=REPORTERS),
            [],
        )
        self.assertEqual(
            parse_directive("@Zug follow", STRANGER, ALLOWED, report_ids=REPORTERS),
            [],
        )

    def test_an_id_in_both_sets_is_the_operator_unscoped(self):
        out = parse_directive(
            "@Zug follow", ME, ALLOWED, report_ids=frozenset({ME, BOT})
        )
        self.assertEqual(out, [InsertCommand("Zug", "follow", f"discord:{ME}")])


class TheUnaddressedQuestions(unittest.TestCase):
    """Slice 4: in the dedicated channel the overseer answers questions
    about itself. The read-only ones (roster, digest) are reports and stay
    open to the scoped id; the unaddressed ORDERS (job, queue, watch)
    change the world and are refused."""

    def test_who_is_in_the_world(self):
        out = parse_directive(
            "who is online", BOT, ALLOWED, dedicated=True, report_ids=REPORTERS
        )
        self.assertEqual(out, [RosterQuery()])

    def test_how_are_they(self):
        out = parse_directive(
            "how are they?", BOT, ALLOWED, dedicated=True, report_ids=REPORTERS
        )
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], DigestQuery)

    def test_a_job_order_is_refused(self):
        out = parse_directive(
            "it's farming time", BOT, ALLOWED, dedicated=True, report_ids=REPORTERS
        )
        self.assertEqual(out, [Reply(core.REPORT_REFUSAL)])

    def test_a_watch_order_is_refused(self):
        out = parse_directive(
            "watch Zug", BOT, ALLOWED, dedicated=True, report_ids=REPORTERS
        )
        self.assertEqual(out, [Reply(core.REPORT_REFUSAL)])

    def test_a_queue_order_is_refused(self):
        out = parse_directive(
            "queue Zug: ragefire 50", BOT, ALLOWED, dedicated=True, report_ids=REPORTERS
        )
        self.assertEqual(out, [Reply(core.REPORT_REFUSAL)])

    def test_in_a_shared_channel_the_scoped_id_gets_the_same_silence(self):
        out = parse_directive(
            "who is online", BOT, ALLOWED, dedicated=False, report_ids=REPORTERS
        )
        self.assertEqual(out, [])


class TheReportSetItself(unittest.TestCase):
    """Slice 5: the set is the scope, so it is pinned against the
    vocabulary it was read from. A new vocabulary entry is state-changing
    until someone argues it onto this list on purpose."""

    def test_every_report_is_a_real_vocabulary_entry(self):
        import voice

        for word in core.REPORT_COMMANDS:
            self.assertIn(word, voice.VOCABULARY, word)
            self.assertTrue(voice.is_raw_command(word), word)

    def test_the_state_changing_entries_are_not_reports(self):
        for word in (
            "follow",
            "stay",
            "grind",
            "attack",
            "summon",
            "repair",
            "sell gray",
            "sell vendor",
            "reset ai",
            "drop quest",
            "leave",
            "nc +grind",
            "nc -loot",
        ):
            self.assertNotIn(word, core.REPORT_COMMANDS, word)


class TheChannelScope(unittest.TestCase):
    """Slice 7: the ticket scopes the giver to THE OVERSEER CHANNEL, which
    is narrower than the bridge's channel rule - that rule also admits the
    chat channel, and admits everywhere when no channel is configured (a
    contract argued for the operator, whose going deaf was the worse
    failure). A scoped identity gets no such contract: outside the
    dedicated channel it is answered nowhere."""

    def test_a_report_in_a_shared_channel_is_ignored(self):
        self.assertEqual(
            parse_directive("@Zug stats", BOT, ALLOWED, report_ids=REPORTERS),
            [],
        )

    def test_a_fanout_report_in_a_shared_channel_is_ignored(self):
        self.assertEqual(
            parse_directive("@horde stats", BOT, ALLOWED, report_ids=REPORTERS),
            [],
        )

    def test_the_operator_in_a_shared_channel_is_unaffected(self):
        out = parse_directive("@Zug follow", ME, ALLOWED, report_ids=REPORTERS)
        self.assertEqual(out, [InsertCommand("Zug", "follow", f"discord:{ME}")])


class TheBridgeWiring(unittest.TestCase):
    """Slice 6: bridge.py's half, pinned as text for the reason the module
    docstring gives - it imports discord and pymysql at module level, so
    the stdlib-only suite cannot import it."""

    @staticmethod
    def _source() -> str:
        return BRIDGE.read_text(encoding="utf-8")

    @staticmethod
    def _on_message(source: str) -> str:
        start = source.index("async def on_message(")
        return source[start : source.index("\n    async def", start + 10)]

    def test_the_report_set_is_built_from_its_own_environment_variable(self):
        src = self._source()
        start = src.index("REPORT_ONLY_IDS = frozenset(")
        block = src[start : src.index("\n)\n", start) + 2]
        self.assertIn("DISCORD_REPORT_USERS", block)
        # And it is NOT the operator's variable: merging the two lists is
        # exactly the failure this ticket exists to prevent.
        self.assertNotIn("DISCORD_ALLOWED_USERS", block)

    def test_on_message_admits_the_report_givers_bot_messages_to_the_parser(self):
        body = self._on_message(self._source())
        self.assertIn("message.author.bot", body)
        self.assertIn("REPORT_ONLY_IDS", body)
        # The exemption runs before the parse, like the channel guard.
        self.assertLess(body.index("REPORT_ONLY_IDS"), body.index("parse_directive"))

    def test_on_message_hands_the_report_set_to_the_parser(self):
        body = self._on_message(self._source())
        self.assertIn("report_ids=REPORT_ONLY_IDS", body)


if __name__ == "__main__":
    unittest.main()

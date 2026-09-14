"""The group grammar as parse_directive sees it (infra#2605).

Two things are being pinned here at once: that "@guild X", "@horde",
"@alliance" and "@everyone" become fan-out decisions, and that a plain
"@Name <order>" is still byte-for-byte the single-character decision it
was before group targeting existed - the devious whisper into a raid is
just an ordinary command, and must stay one.
"""
import unittest

from core import (
    MAX_COMMAND_LEN,
    MAX_COMMANDS_PER_MESSAGE,
    FanoutCommand,
    FanoutDirective,
    InsertCommand,
    NLDirective,
    Reply,
    parse_directive,
)

ME = "1000"
ALLOWED = frozenset({ME})
SRC = "discord:1000"


class GroupGrammarTest(unittest.TestCase):
    def test_guild_order_becomes_a_fanout(self):
        out = parse_directive("@guild Argentum follow", ME, ALLOWED)
        self.assertEqual(out, [FanoutCommand("guild Argentum", "follow", SRC)])

    def test_quoted_guild_name_survives_parsing(self):
        out = parse_directive('@guild "Rangers of Vengeance" stay', ME, ALLOWED)
        self.assertEqual(out, [FanoutCommand("guild Rangers of Vengeance", "stay", SRC)])

    def test_faction_order_becomes_a_fanout(self):
        out = parse_directive("@horde grind", ME, ALLOWED)
        self.assertEqual(out, [FanoutCommand("horde", "grind", SRC)])

    def test_everyone_becomes_a_fanout(self):
        out = parse_directive("@everyone stay", ME, ALLOWED)
        self.assertEqual(out, [FanoutCommand("everyone", "stay", SRC)])

    def test_group_word_case_does_not_matter(self):
        out = parse_directive("@Horde grind", ME, ALLOWED)
        self.assertEqual(out, [FanoutCommand("horde", "grind", SRC)])

    def test_recruits_becomes_a_fanout_with_no_guild_name(self):
        # Unlike "@guild", this head takes no argument: which guild is ours
        # is read off the family at resolve time, never typed.
        out = parse_directive("@recruits nc +stay", ME, ALLOWED)
        self.assertEqual(out, [FanoutCommand("recruits", "nc +stay", SRC)])

    def test_a_character_called_Recruits_would_lose_its_name(self):
        # The deliberate cost of a reserved word, pinned so the trade is
        # visible rather than discovered. Same trade "@horde" already made.
        out = parse_directive("@Recruits follow", ME, ALLOWED)
        self.assertEqual(out, [FanoutCommand("recruits", "follow", SRC)])


class ConjuredEventTest(unittest.TestCase):
    def test_natural_language_at_a_group_is_a_conjured_event(self):
        out = parse_directive("@guild Argentum raid Astranaar tonight", ME, ALLOWED)
        self.assertEqual(
            out, [FanoutDirective("guild Argentum", "raid Astranaar tonight", SRC)]
        )

    def test_a_raw_command_at_a_group_skips_the_voice(self):
        out = parse_directive("@horde co +grind", ME, ALLOWED)
        self.assertEqual(out, [FanoutCommand("horde", "co +grind", SRC)])


class GroupHelpTest(unittest.TestCase):
    def test_a_group_with_no_order_is_asked_for_one(self):
        out = parse_directive("@everyone", ME, ALLOWED)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)

    def test_guild_with_no_name_is_asked_for_one(self):
        out = parse_directive("@guild follow", ME, ALLOWED)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)
        self.assertIn("guild", out[0].text.lower())

    def test_recruits_with_no_order_is_asked_for_one_by_name(self):
        out = parse_directive("@recruits", ME, ALLOWED)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)
        self.assertIn("recruit", out[0].text.lower())

    def test_an_overlong_group_order_is_rejected_with_its_length(self):
        long_cmd = "x" * (MAX_COMMAND_LEN + 1)
        out = parse_directive(f"@horde {long_cmd}", ME, ALLOWED)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)
        self.assertIn(str(MAX_COMMAND_LEN + 1), out[0].text)

    def test_a_flood_of_group_orders_is_capped_like_any_other(self):
        lines = "\n".join(f"@horde order{i}" for i in range(MAX_COMMANDS_PER_MESSAGE + 1))
        out = parse_directive(lines, ME, ALLOWED)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)


class SingleTargetIsUnchangedTest(unittest.TestCase):
    def test_a_named_character_still_gets_a_plain_command(self):
        out = parse_directive("@Grug follow", ME, ALLOWED)
        self.assertEqual(out, [InsertCommand("Grug", "follow", SRC)])

    def test_a_named_character_still_gets_a_plain_nl_directive(self):
        out = parse_directive("@Grug go kill something", ME, ALLOWED)
        self.assertEqual(out, [NLDirective("Grug", "go kill something", SRC)])

    def test_a_whisper_into_a_mustered_band_is_just_a_command(self):
        # The saboteur line: one raider gets a private order mid-raid. It
        # must not become a fan-out just because a fan-out is in flight.
        out = parse_directive("@horde attack\n@Grug flee", ME, ALLOWED)
        self.assertEqual(
            out, [FanoutCommand("horde", "attack", SRC), InsertCommand("Grug", "flee", SRC)]
        )

    def test_an_unaddressed_message_is_still_silence(self):
        self.assertEqual(parse_directive("the horde is restless", ME, ALLOWED), [])

    def test_an_unknown_author_gets_no_muster(self):
        self.assertEqual(parse_directive("@horde grind", "9999", ALLOWED), [])


if __name__ == "__main__":
    unittest.main()

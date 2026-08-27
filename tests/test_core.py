"""Behavioral tests for the bridge decision core: message in, decisions out.

No Discord, no MySQL, no LLM - the core is pure, which is the point.
"""
import unittest

from core import (
    MAX_COMMAND_LEN,
    MAX_COMMANDS_PER_MESSAGE,
    InsertCommand,
    Reply,
    parse_directive,
    report_outcomes,
)

ME = "1000"
ALLOWED = frozenset({ME})


class ParseDirectiveTest(unittest.TestCase):
    def test_simple_directive_becomes_a_command_row(self):
        out = parse_directive("@Grug follow", ME, ALLOWED)
        self.assertEqual(out, [InsertCommand("Grug", "follow", "discord:1000")])

    def test_unknown_author_is_ignored_entirely(self):
        self.assertEqual(parse_directive("@Grug follow", "9999", ALLOWED), [])

    def test_message_without_an_address_is_ignored(self):
        self.assertEqual(parse_directive("what a lovely world", ME, ALLOWED), [])

    def test_invalid_name_gets_help_not_sql(self):
        out = parse_directive("@x;DROP follow", ME, ALLOWED)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)

    def test_missing_command_prompts_for_one(self):
        out = parse_directive("@Grug", ME, ALLOWED)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)
        self.assertIn("Grug", out[0].text)

    def test_overlong_command_is_rejected_with_its_length(self):
        long_cmd = "x" * (MAX_COMMAND_LEN + 1)
        out = parse_directive(f"@Grug {long_cmd}", ME, ALLOWED)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)
        self.assertIn(str(MAX_COMMAND_LEN + 1), out[0].text)

    def test_multiline_message_yields_multiple_commands(self):
        out = parse_directive("@Grug follow\n@Bork stay", ME, ALLOWED)
        self.assertEqual(
            out,
            [
                InsertCommand("Grug", "follow", "discord:1000"),
                InsertCommand("Bork", "stay", "discord:1000"),
            ],
        )

    def test_flood_of_commands_is_capped(self):
        lines = "\n".join(f"@Grug order{i}" for i in range(MAX_COMMANDS_PER_MESSAGE + 1))
        out = parse_directive(lines, ME, ALLOWED)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)

    def test_chatter_lines_between_directives_are_skipped(self):
        out = parse_directive("hello everyone\n@Grug follow\nthanks!", ME, ALLOWED)
        self.assertEqual(out, [InsertCommand("Grug", "follow", "discord:1000")])


class ReportOutcomesTest(unittest.TestCase):
    def _row(self, row_id, status="delivered", detail=""):
        return {
            "id": row_id,
            "target_name": "Grug",
            "command": "follow",
            "status": status,
            "detail": detail,
        }

    def test_delivered_row_is_reported_once_with_its_id(self):
        replies, seen = report_outcomes([self._row(1)], set())
        self.assertEqual(len(replies), 1)
        row_id, reply = replies[0]
        self.assertEqual(row_id, 1)
        self.assertIn("heard the order", reply.text)
        replies2, _ = report_outcomes([self._row(1)], seen)
        self.assertEqual(replies2, [])

    def test_error_row_reports_its_detail(self):
        replies, _ = report_outcomes([self._row(2, "error", "target not online")], set())
        self.assertEqual(len(replies), 1)
        self.assertIn("target not online", replies[0][1].text)

    def test_error_without_detail_still_reads_sanely(self):
        replies, _ = report_outcomes([self._row(3, "error", "")], set())
        self.assertIn("unknown error", replies[0][1].text)

    def test_seen_ids_accumulate_across_polls(self):
        _, seen = report_outcomes([self._row(1)], set())
        replies, seen = report_outcomes([self._row(1), self._row(2)], seen)
        self.assertEqual(len(replies), 1)
        self.assertEqual(seen, {1, 2})

    def test_restart_seeding_suppresses_history(self):
        rows = [self._row(i) for i in range(1, 4)]
        seeded = {r["id"] for r in rows}
        replies, _ = report_outcomes(rows, seeded)
        self.assertEqual(replies, [])


if __name__ == "__main__":
    unittest.main()


class DedicatedChannelTest(unittest.TestCase):
    def test_roster_question_yields_a_roster_query(self):
        from core import RosterQuery
        out = parse_directive("List the souls that are playing", ME, ALLOWED, dedicated=True)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], RosterQuery)

    def test_other_chatter_gets_help_not_silence(self):
        out = parse_directive("what a lovely evening", ME, ALLOWED, dedicated=True)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)

    def test_shared_channel_stays_silent(self):
        self.assertEqual(parse_directive("who is online?", ME, ALLOWED, dedicated=False), [])

    def test_unknown_author_silent_even_in_dedicated(self):
        self.assertEqual(parse_directive("who is online?", "9999", ALLOWED, dedicated=True), [])

    def test_character_directives_still_work_in_dedicated(self):
        out = parse_directive("@Grug follow", ME, ALLOWED, dedicated=True)
        self.assertEqual(out, [InsertCommand("Grug", "follow", "discord:1000")])

    def test_job_order_yields_a_job_directive(self):
        from core import JobDirective
        out = parse_directive("job farm", ME, ALLOWED, dedicated=True)
        self.assertEqual(out, [JobDirective(mode="farm", source="discord:1000")])

    def test_evans_own_sentence_is_recognised(self):
        from core import JobDirective
        out = parse_directive("its farming time", ME, ALLOWED, dedicated=True)
        self.assertEqual(out, [JobDirective(mode="farm", source="discord:1000")])

    def test_job_order_is_not_recognised_in_a_shared_channel(self):
        # A job is family-wide state, not a per-message question - the same
        # "must not answer every message" rule as roster/digest.
        self.assertEqual(parse_directive("job quest", ME, ALLOWED, dedicated=False), [])

    def test_a_bare_mode_word_in_ordinary_chatter_is_not_a_job_order(self):
        out = parse_directive("Grug just finished a quest", ME, ALLOWED, dedicated=True)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Reply)


class FormatRosterTest(unittest.TestCase):
    def _row(self, name, level=5, race=2, map_id=1, combat=0, bot=1):
        return {"name": name, "level": level, "race": race, "map_id": map_id,
                "in_combat": combat, "is_bot": bot}

    def test_census_counts_factions_and_continents(self):
        from core import format_roster
        rows = [self._row("Grug", race=2, map_id=1), self._row("Aldo", race=1, map_id=0),
                self._row("Vely", race=8, map_id=571, combat=1)]
        text = format_roster(rows).text
        self.assertIn("3 souls", text)
        self.assertIn("1 Alliance", text)
        self.assertIn("2 Horde", text)
        self.assertIn("Kalimdor 1", text)
        self.assertIn("1 in combat", text)

    def test_mortals_are_named(self):
        from core import format_roster
        rows = [self._row("Grug", bot=0), self._row("Vely")]
        self.assertIn("Mortals present: Grug", format_roster(rows).text)

    def test_empty_world_reads_honestly(self):
        from core import format_roster
        self.assertIn("empty", format_roster([]).text)

    def test_sample_is_capped(self):
        from core import ROSTER_SAMPLE, format_roster
        rows = [self._row(f"Bot{i:03d}", level=i % 60 + 1) for i in range(200)]
        highest_line = [l for l in format_roster(rows).text.splitlines() if l.startswith("Highest")][0]
        self.assertLessEqual(highest_line.count(","), ROSTER_SAMPLE)

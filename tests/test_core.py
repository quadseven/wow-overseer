"""Behavioral tests for the bridge decision core: message in, decisions out.

No Discord, no MySQL, no LLM - the core is pure, which is the point.
"""

import unittest

from core import (
    MAX_COMMAND_LEN,
    MAX_COMMANDS_PER_MESSAGE,
    InsertCommand,
    Reply,
    ended_by_restart,
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
        lines = "\n".join(
            f"@Grug order{i}" for i in range(MAX_COMMANDS_PER_MESSAGE + 1)
        )
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
        replies, _ = report_outcomes(
            [self._row(2, "error", "target not online")], set()
        )
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

    def test_restart_error_is_recognized_correctly(self):
        self.assertTrue(ended_by_restart("error", "restart: worldserver roll"))
        self.assertFalse(ended_by_restart("error", "target not online"))
        self.assertFalse(ended_by_restart("delivered", "restart: worldserver roll"))
        self.assertFalse(ended_by_restart(None, None))
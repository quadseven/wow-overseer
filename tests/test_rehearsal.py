"""Test the rehearsal configuration and guards."""

import os
import unittest

import rehearsal


class RehearsalConfigTest(unittest.TestCase):
    def test_realms_have_expected_values(self):
        self.assertEqual(rehearsal.REALM_ID, 201)
        self.assertEqual(rehearsal.REALM_NAME, "Rehearsal")

    def test_marker_table_and_row(self):
        self.assertEqual(
            rehearsal.REHEARSAL_MARKER_TABLE, "rehearsal_marker"
        )
        self.assertEqual(
            rehearsal.REHEARSAL_MARKER_ROW, "marker = 'rehearsal'"
        )
        self.assertEqual(
            rehearsal.REHEARSAL_MARKER_VALUE, "rehearsal"
        )

    def test_world_label(self):
        self.assertEqual(
            rehearsal.REHEARSAL_WORLD_LABEL, "rehearsal"
        )

    def test_grants_flag_configuration(self):
        self.assertEqual(
            rehearsal.REHEARSAL_GRANTS_ENABLED_ENV, "REHEARSAL_GRANTS_ENABLED"
        )
        self.assertEqual(
            rehearsal.REHEARSAL_GRANTS_ENABLED_VALUE, "grants: enabled"
        )

    def test_bot_account_prefix(self):
        self.assertEqual(rehearsal.BOT_ACCOUNT_PREFIX, "RPR")
        self.assertEqual(rehearsal.BOT_ACCOUNT_SUFFIX_RE.pattern, "^RPR\\d+$")

    def test_check_grants_flag_passes_with_valid_value(self):
        rehearsal.check_grants_flag("grants: enabled")

    def test_check_grants_flag_raises_for_empty_string(self):
        with self.assertRaises(rehearsal.InvalidGrantFlag) as cm:
            rehearsal.check_grants_flag("")
        self.assertIn(
            "Expected REHEARSAL_GRANTS_ENABLED to be",
            str(cm.exception)
        )

    def test_check_grants_flag_raises_for_invalid_value(self):
        with self.assertRaises(rehearsal.InvalidGrantFlag) as cm:
            rehearsal.check_grants_flag("grants: disabled")
        self.assertIn(
            "Expected REHEARSAL_GRANTS_ENABLED to be",
            str(cm.exception)
        )

    def test_check_grants_flag_raises_for_none(self):
        with self.assertRaises(rehearsal.InvalidGrantFlag) as cm:
            rehearsal.check_grants_flag(None)
        self.assertIn(
            "Expected REHEARSAL_GRANTS_ENABLED to be",
            str(cm.exception)
        )

    def test_check_rehearsal_marker_passes_with_valid_value(self):
        rehearsal.check_rehearsal_marker("rehearsal")

    def test_check_rehearsal_marker_raises_for_invalid_value(self):
        with self.assertRaises(rehearsal.NoRehearsalMarker) as cm:
            rehearsal.check_rehearsal_marker("production")
        self.assertIn(
            "Expected rehearsal marker row to be",
            str(cm.exception)
        )

    def test_validate_bot_account_prefix_passes_for_valid_prefix(self):
        rehearsal.validate_bot_account_prefix("RPR1")
        rehearsal.validate_bot_account_prefix("RPR42")
        rehearsal.validate_bot_account_prefix("RPR99")

    def test_validate_bot_account_prefix_raises_for_invalid_prefix(self):
        with self.assertRaises(ValueError) as cm:
            rehearsal.validate_bot_account_prefix("RABBIT")
        self.assertIn("Bot account prefix must match", str(cm.exception))

    def test_validate_bot_account_prefix_raises_for_number_only(self):
        with self.assertRaises(ValueError) as cm:
            rehearsal.validate_bot_account_prefix("12345")
        self.assertIn("Bot account prefix must match", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

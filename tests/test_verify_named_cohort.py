import importlib.util
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_named_cohort", ROOT / "tools" / "verify_named_cohort.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def character(name, account, race, class_id):
    return {
        "name": name,
        "username": account,
        "race": race,
        "class": class_id,
    }


class VerifierTest(unittest.TestCase):
    def test_expected_bonkers_rows_pass(self):
        rows = [
            character("Blammo", "BLAMMO", 2, 1),
            character("Hexmama", "HEXMAMA", 8, 5),
            character("Moojuice", "MOOJUICE", 6, 11),
            character("Rotgut", "ROTGUT", 5, 4),
            character("Zapzap", "ZAPZAP", 10, 8),
        ]
        self.assertEqual([], MODULE.verify_characters(rows, MODULE.BONKERS))

    def test_wrong_account_and_alliance_race_fail(self):
        rows = [
            character("Blammo", "OTHER", 1, 1),
            character("Hexmama", "HEXMAMA", 8, 5),
            character("Moojuice", "MOOJUICE", 6, 11),
            character("Rotgut", "ROTGUT", 5, 4),
            character("Zapzap", "ZAPZAP", 10, 8),
        ]
        errors = MODULE.verify_characters(rows, MODULE.BONKERS)
        self.assertTrue(any("belongs" in error for error in errors))
        self.assertTrue(any("faction" in error for error in errors))

    def test_duplicate_account_is_rejected(self):
        rows = [
            character("Blammo", "BLAMMO", 2, 1),
            character("Hexmama", "BLAMMO", 8, 5),
            character("Moojuice", "MOOJUICE", 6, 11),
            character("Rotgut", "ROTGUT", 5, 4),
            character("Zapzap", "ZAPZAP", 10, 8),
        ]
        self.assertTrue(
            any(
                "separate accounts" in error
                for error in MODULE.verify_characters(rows, MODULE.BONKERS)
            )
        )

    def test_realm_identity_is_checked(self):
        self.assertEqual(
            [],
            MODULE.verify_realm([{"id": 1, "name": "Homelab-Dev"}], 1, "Homelab-Dev"),
        )
        self.assertTrue(
            MODULE.verify_realm([{"id": 2, "name": "Homelab-Dev"}], 1, "Homelab-Dev")
        )

    def test_guild_count_requires_eligible_random_bots(self):
        rows = [
            {"guild_name": "Cave", "random_bot_members": 50},
            {"guild_name": "Bonkers", "random_bot_members": 49},
        ]
        errors = MODULE.verify_guilds(rows, ["Cave", "Bonkers"], 50)
        self.assertEqual(1, len(errors))
        self.assertIn("Bonkers", errors[0])

    def test_queries_are_select_only(self):
        body = (ROOT / "tools" / "verify_named_cohort.py").read_text()
        writes = re.findall(
            r"execute\(\s*[\"'](INSERT|UPDATE|DELETE)", body, flags=re.IGNORECASE
        )
        self.assertEqual([], writes)


if __name__ == "__main__":
    unittest.main()

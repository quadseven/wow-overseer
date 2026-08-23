"""Keeping Grug from being re-rolled.

RandomPlayerbotMgr re-randomizes an idle bot when its `randomize` event
row has expired: FindEvent drops the row once
`NowSeconds() - time >= validIn`, GetEventValue then returns 0, and the
update loop calls Randomize(). Below level 3 that routes to
RandomizeFirst(), which assigns a level and re-gears - which would erase
the character Evan is actually growing (infra#2656).

Suppression is therefore just: keep a row whose validIn has not elapsed.
This module decides WHICH rows need writing; bridge.py does the writing.
"""
import ast
import pathlib
import re
import unittest

import protect

HORIZON = protect.PROTECT_HORIZON_SECONDS
NOW = 1_800_000_000


class NeedsRefreshTest(unittest.TestCase):
    def test_a_character_with_no_row_needs_one(self):
        self.assertEqual(
            protect.rows_needing_refresh({101: "Grug"}, {}, NOW), [101]
        )

    def test_a_freshly_written_row_is_left_alone(self):
        rows = {101: {"time": NOW - 10, "validIn": HORIZON}}
        self.assertEqual(protect.rows_needing_refresh({101: "Grug"}, rows, NOW), [])

    def test_a_row_nearing_expiry_is_refreshed_before_it_lapses(self):
        # Refresh once less than a third of the horizon remains, so a missed
        # cycle (or ten) cannot let the protection lapse silently.
        rows = {101: {"time": NOW - int(HORIZON * 0.8), "validIn": HORIZON}}
        self.assertEqual(protect.rows_needing_refresh({101: "Grug"}, rows, NOW), [101])

    def test_a_short_validIn_written_by_the_server_is_overwritten(self):
        # The manager's own scheduling uses hours; ours must win.
        rows = {101: {"time": NOW, "validIn": 7200}}
        self.assertEqual(protect.rows_needing_refresh({101: "Grug"}, rows, NOW), [101])

    def test_an_already_expired_row_is_refreshed(self):
        rows = {101: {"time": NOW - HORIZON - 1, "validIn": HORIZON}}
        self.assertEqual(protect.rows_needing_refresh({101: "Grug"}, rows, NOW), [101])

    def test_unprotected_characters_are_never_touched(self):
        # 999 has a long-expired row and is NOT protected; it must never
        # appear in the write list, even though the manager would randomize
        # it (which is correct for an ordinary bot).
        rows = {999: {"time": 0, "validIn": 1}}
        out = protect.rows_needing_refresh({101: "Grug"}, rows, NOW)
        self.assertNotIn(999, out)

    def test_several_protected_characters_are_all_considered(self):
        out = protect.rows_needing_refresh({101: "Grug", 102: "Bork"}, {}, NOW)
        self.assertEqual(sorted(out), [101, 102])

    def test_the_horizon_is_long_enough_to_outlive_a_weekend_outage(self):
        # The manager's slowest natural randomize is 14 days; ours must be
        # comfortably longer or protection is a race we sometimes lose.
        self.assertGreater(HORIZON, 30 * 24 * 3600)


class ReportTest(unittest.TestCase):
    def test_the_report_names_who_is_protected_and_until_when(self):
        line = protect.report({101: "Grug"}, [101], NOW)
        self.assertIn("Grug", line)
        self.assertIn("1", line)

    def test_a_quiet_cycle_still_says_who_is_covered(self):
        # Silence would make a lapsed protection indistinguishable from a
        # working one - the failure mode this repo keeps meeting.
        line = protect.report({101: "Grug"}, [], NOW)
        self.assertIn("Grug", line)


class RosterWiringTest(unittest.TestCase):
    """Protecting a character and never logging it in is a contradiction.

    The whole point of infra#2656 is a character that plays with nobody at the
    keyboard. Protection alone produces a character that is carefully preserved
    and permanently absent - and absent looks exactly like working, because
    nothing errors.

    bridge.py needs pymysql and discord, so this walks its AST.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        fn = next(
            n for n in ast.walk(ast.parse(cls.src))
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_protect_characters"
        )
        # Every bare name in the function, not just callees: the bridge does
        # its blocking work as asyncio.to_thread(_ensure_roster, ...), so the
        # function being called is an ARGUMENT, and a callee-only walk misses
        # it entirely - reporting the wiring absent when it is present.
        cls.called = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}

    def test_the_protect_loop_also_puts_them_on_the_roster(self):
        self.assertIn(
            "_ensure_roster", self.called,
            "nothing seeds overseer_roster, so mod-overseer logs nobody in",
        )

    def test_every_family_member_is_kept_on_a_living_strategy(self):
        """Only the character with an active goal got a strategy back after the
        last worldserver restart. The other four stood still and their levels
        stopped moving, with nothing anywhere reporting it."""
        self.assertIn("_give_them_a_life", self.called)

    def test_a_character_at_the_keyboard_is_not_sent_bot_commands(self):
        """A character Evan is holding has no PlayerbotAI, so every bot command
        aimed at it is refused. Without this the roster loop aimed one every
        cycle at whichever character he happened to be playing, filling the
        command table with errors."""
        import ast
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "_give_them_a_life")
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        self.assertIn("_bot_held_names", names)

    def test_the_roster_comes_from_the_same_list_as_the_protection(self):
        """Two lists drift, and both failures are quiet: protected but not
        rostered never appears, rostered but not protected gets re-rolled."""
        fn = next(
            n for n in ast.walk(ast.parse(self.src))
            if isinstance(n, ast.FunctionDef) and n.name == "_protected_guids"
        )
        env = [
            n.args[0].value for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get" and n.args and isinstance(n.args[0], ast.Constant)
        ]
        self.assertIn("OVERSEER_NOTABLE_NAMES", env)


class RosterManifestTest(unittest.TestCase):
    def test_every_family_member_is_notable(self):
        """A family member missing from OVERSEER_NOTABLE_NAMES is never logged
        in, so they silently never answer a muster - which reads as the bond
        rules being wrong rather than as a character who is not there."""
        import bonds

        manifest = (
            pathlib.Path(__file__).resolve().parents[3]
            / "oke/manifests/wow/70-overseer.yaml"
        ).read_text()
        m = re.search(
            r'name:\s*OVERSEER_NOTABLE_NAMES\s*\n\s*value:\s*"([^"]*)"', manifest
        )
        self.assertIsNotNone(m, "OVERSEER_NOTABLE_NAMES not found in the manifest")
        notable = {n.strip().casefold() for n in m.group(1).split(",") if n.strip()}
        missing = sorted(n for n in bonds.FAMILY if n.casefold() not in notable)
        self.assertEqual(missing, [], "family members not on the notable list: %s" % missing)


class ReservedWordTest(unittest.TestCase):
    """`lead` is a reserved word in MySQL 8 - the LEAD() window function.

    Unquoted it is a syntax error, and AzerothCore treats a malformed query as
    unrecoverable: the worldserver ABORTED on its first roster poll and went
    into a crash loop, taking the game server down. The column name was a bad
    choice; backticking every use of it is the fix, and this stops the next one
    slipping through.
    """

    # MySQL 8 reserved words this codebase plausibly reaches for as identifiers.
    RESERVED = ("lead", "rank", "groups", "system", "window", "first", "last")

    def _sql_strings(self, path):
        import ast
        import re

        for node in ast.walk(ast.parse(pathlib.Path(path).read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.strip()
                # Must START with a SQL verb. Matching anywhere caught prose:
                # a docstring saying "the update loop randomizes" read as SQL.
                # Adjacent string literals are concatenated by the parser, so a
                # multi-line query arrives here as one constant beginning with
                # its verb.
                if re.match(r"(SELECT|UPDATE|INSERT|DELETE|ALTER|CREATE)\b", text, re.I):
                    yield text

    def test_no_reserved_word_is_used_as_a_bare_identifier(self):
        import re

        here = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in sorted(here.glob("*.py")):
            for sql in self._sql_strings(path):
                for word in self.RESERVED:
                    # Bare use: the word with no backtick immediately before it.
                    if re.search(r"(?<![`\w.])%s(?![`\w])" % word, sql, re.I):
                        offenders.append("%s: %s" % (path.name, sql[:70]))
        self.assertEqual(offenders, [], "reserved words used unquoted:\n" + "\n".join(offenders))

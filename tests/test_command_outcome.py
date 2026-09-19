"""What a finished overseer_command row is allowed to CLAIM (infra#2819).

`delivered` was written the instant `PlayerbotAI::HandleCommand` accepted a
row. That says the row was handed over. It says nothing about whether the bot
changed, because a whispered command does not act when it is handed over - it
lands in `PlayerbotAI::chatCommands` and is drained on the bot's next AI tick
(mod_overseer.cpp:2055-2057). Two engineers read `delivered` as "applied", in
writing, all night.

The case that proves it matters: `nc -new rpg` was sent to Ugga twice (rows
4049 and 4184). Both read `delivered`. Her strategy did not change either time,
verified by live probe minutes after each. Three other characters got the
identical command in the identical batch and it worked for both of them, both
times. The worldserver log said nothing at all about either row - the module
logged only the command it HELD, never the one it SENT. Both instruments
reported success and the failure was not merely hard to diagnose, it was
invisible.

This file pins the half of the fix that cannot be unit-tested because it only
compiles on push:

  * the live strategy list is read back off the engines AFTER the hand-off,
    and the success status is written only once that read agrees;
  * a command that was accepted and changed nothing gets its OWN terminal
    status, so its row is visibly different from the rows that worked;
  * the hand-off is logged, not only the hold;
  * the ENUM gains its new values by ALTER and by APPENDING - editing
    `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists,
    and reordering an ENUM silently relabels every existing row, because
    MySQL stores the ordinal and not the string.

and the half that can: the Python that reads `status` back must understand the
new values. The C++ and the Python ship as SEPARATE IMAGES, so both directions
of a split deploy are pinned here too.

NOT tested here, and deliberately: the per-verb throttle's fixed 2s spacing
(mod_overseer.cpp:2077) is a timer rather than a handshake. That is a real and
separate defect. It is NOT the cause of the Ugga case - a race does not fail
twice consecutively on one bot while three others succeed twice - and this
change does not touch it.
"""
import pathlib
import re
import unittest

from core import (
    COMMAND_SUCCESS_STATUSES,
    COMMAND_TERMINAL_STATUSES,
    report_outcomes,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "mod-overseer/src/mod_overseer.cpp"
MIGRATION = (
    ROOT
    / "mod-overseer/data/sql/characters/base"
    / "2026_08_24_04_overseer_outcome.sql"
)
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")
PROBE_TOOL = (ROOT / "tools/probe.py").read_text(encoding="utf-8")

BANNER = "// ------------------------------------------------------- outcome --"

# The one expression that decides which terminal status a verified command
# gets. Pinned as a literal so a refactor that reintroduces an unconditional
# success has to delete a test to do it.
VERDICT = 'holds ? "applied" : "unchanged"'


def _source() -> str:
    return MODULE.read_text(encoding="utf-8")


def _outcome_source() -> str:
    """Everything from the outcome banner to the end of DeliverPendingCommands."""
    src = _source()
    start = src.index(BANNER)
    end = src.index("    // Speak as the character would.")
    assert end > start
    return src[start:end]


def _code(text: str) -> str:
    """The same source with every comment removed.

    Load-bearing: this file's prose NAMES the statuses and the throttle in
    order to explain them, and a substring search over the raw text would find
    the explanation and call it the implementation.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


class SuccessIsReadBackNotAssumed(unittest.TestCase):
    """The defining bug of this project is an action that reports success while
    doing nothing. `sell junk` returned TRUE and sold nothing; `nc -new rpg`
    was `delivered` twice and removed nothing."""

    def test_the_hand_off_no_longer_writes_a_success_status_by_itself(self):
        """The exact line the issue is about: HandleCommand accepting a row
        must not be the thing that ends it."""
        code = _code(_outcome_source())
        handoff = code.index("botAI->HandleCommand(CHAT_MSG_WHISPER, command, player)")
        # Between the hand-off and the end of the bot branch there must be no
        # unconditional success. The only status a checkable command may take
        # there is the in-flight one.
        tail = code[handoff : code.index("else\n                detail = \"target has no bot AI", handoff)]
        self.assertIn('status = "verifying"', tail)

    def test_a_strategy_command_is_parked_in_verifying_not_ended(self):
        code = _code(_outcome_source())
        self.assertIn('status = "verifying"', code)

    def test_the_verdict_is_computed_from_the_read_back_and_nothing_else(self):
        """`holds` may only ever be falsified by the engine disagreeing with
        what was asked for. Any other source would make the new statuses as
        untrustworthy as the old one."""
        code = _code(_outcome_source())
        self.assertEqual(code.count("holds = false"), 1)
        falsify = code.index("holds = false")
        self.assertIn("item.after != item.want", code[falsify - 120 : falsify])

    def test_the_live_strategy_list_is_read_before_and_after_the_hand_off(self):
        code = _code(_outcome_source())
        self.assertIn("ParseStrategyChange", code)
        self.assertIn("StrategyPresent", code)
        before = code.index("item.before = StrategyPresent")
        handoff = code.index("botAI->HandleCommand(CHAT_MSG_WHISPER, command, player)")
        self.assertLess(before, handoff, "the BEFORE read must precede the hand-off")

    def test_the_read_back_uses_the_live_engines_not_the_persisted_copy(self):
        """playerbots_db_store is written on change and can disagree with what
        the bot is running this second - ProbeStrategies exists for the same
        reason (mod_overseer.cpp:2416-2418)."""
        code = _code(_outcome_source())
        self.assertIn("botAI->GetStrategies(BOT_STATE_COMBAT)", code)
        self.assertIn("botAI->GetStrategies(BOT_STATE_NON_COMBAT)", code)

    def test_applied_is_written_only_after_the_read_back_agrees(self):
        code = _code(_outcome_source())
        readback = code.index("item.after = StrategyPresent")
        self.assertGreater(code.index(VERDICT), readback)

    def test_a_command_that_changed_nothing_gets_its_own_terminal_status(self):
        """The Ugga row. It must not be able to read the same as the three
        rows that worked."""
        code = _code(_outcome_source())
        self.assertIn(VERDICT, code)
        # And EVERY mention of it is inside that one expression, so no future
        # path can reach `unchanged` without having done the read-back.
        self.assertEqual(code.count('"unchanged"'), code.count(VERDICT))

    def test_the_unchanged_row_carries_the_live_lists_it_was_judged_against(self):
        """An operator must not have to go and probe to find out what the bot
        actually had - that is the round trip this issue exists to remove."""
        outcome = _outcome_source()
        self.assertIn("ProbeStrategies(bot)", _code(outcome))
        for field in ("outcome", "strategy", "sign", "before", "after", "waited_ms", "live"):
            self.assertIn(r'\"%s\":' % field, outcome, field)

    def test_the_verdict_update_is_conditional_on_still_owning_the_row(self):
        """Same rule the hand-off UPDATE already follows: if the bridge gave up
        and ended the row, writing over it resurrects a command the sender was
        told nothing came of."""
        code = _code(_outcome_source())
        self.assertIn(
            "WHERE id = {} AND status = 'verifying' AND claimed_by = '{}'", code
        )


class TheHandOffIsLogged(unittest.TestCase):
    """The module logged the command it HELD and said nothing about the one it
    SENT, so the worldserver log across the whole Ugga window contained only
    `holding` lines."""

    def test_the_hold_is_still_logged(self):
        self.assertIn("overseer: holding command", _outcome_source())

    def test_the_hand_off_is_logged_too(self):
        code = _code(_outcome_source())
        self.assertIn("overseer: handed command", code)

    def test_a_command_that_changed_nothing_is_logged_as_a_warning(self):
        """INFO is where this would be lost. The whole point is that the next
        person finds it in a minute."""
        code = _code(_outcome_source())
        verdict = code.index(VERDICT)
        window = code[max(0, verdict - 1200) : verdict + 1200]
        self.assertIn("LOG_WARN", window)


class TheThrottleIsNotWhatChanged(unittest.TestCase):
    """The timer-not-handshake gap is real and is a SEPARATE issue. Pinning it
    here is how a later change to it stays a deliberate act rather than a side
    effect of this one."""

    def test_the_per_verb_hold_still_leaves_the_row_pending(self):
        code = _code(_outcome_source())
        self.assertIn('spoken.insert(targetName + "\\n" + verb)', code)
        self.assertIn("continue;", code)

    def test_the_poll_interval_is_untouched(self):
        self.assertIn("constexpr uint32 COMMAND_POLL_MS = 2000;", _source())


class TheEnumNeedsAnAppendingAlter(unittest.TestCase):
    """Two traps in one column. CREATE TABLE IF NOT EXISTS is a no-op against
    an existing table, so it cannot add an ENUM value - that has bitten this
    codebase twice. And MySQL stores an ENUM as the ORDINAL of the value, so
    inserting a new name in the middle silently relabels every row already
    written."""

    def test_the_migration_exists(self):
        self.assertTrue(MIGRATION.is_file(), str(MIGRATION))

    def test_it_alters_rather_than_creating(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("ALTER TABLE `overseer_command`", sql)
        self.assertIn("MODIFY COLUMN `status`", sql)

    def test_the_existing_values_keep_their_ordinals(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        enum = re.search(r"MODIFY COLUMN `status`\s+ENUM\(([^)]*)\)", sql, re.S)
        self.assertIsNotNone(enum, "no status ENUM in the migration")
        values = re.findall(r"'([a-z]+)'", enum.group(1))
        self.assertEqual(
            values[:4],
            ["pending", "claimed", "delivered", "error"],
            "the four existing values must stay in their existing positions",
        )
        self.assertEqual(values[4:], ["verifying", "applied", "unchanged"])

    def test_the_default_is_still_pending(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("DEFAULT 'pending'", sql)


class ThePythonUnderstandsTheNewStatuses(unittest.TestCase):
    """The C++ and the Python deploy as separate images. Two halves of one rule
    split across two artifacts has caused two live regressions here already."""

    def _row(self, row_id, status, detail="", kind="bot"):
        return {
            "id": row_id,
            "target_name": "Ugga",
            "command": "nc -new rpg",
            "kind": kind,
            "status": status,
            "detail": detail,
        }

    def test_the_terminal_set_is_declared_once_and_the_bridge_uses_it(self):
        """Not two literal lists that can drift. The poller's IN-list is built
        from the same tuple this module exports."""
        self.assertIn("COMMAND_TERMINAL_STATUSES", BRIDGE)
        self.assertNotIn("WHERE status IN ('delivered', 'error')", BRIDGE)

    def test_applied_is_a_success_and_delivered_still_is(self):
        self.assertEqual(COMMAND_SUCCESS_STATUSES, ("delivered", "applied"))
        self.assertEqual(
            COMMAND_TERMINAL_STATUSES,
            ("delivered", "applied", "unchanged", "error"),
        )

    def test_verifying_is_not_terminal(self):
        """A row still being read back is in flight. Reporting it would call a
        command that has not finished yet a failure."""
        self.assertNotIn("verifying", COMMAND_TERMINAL_STATUSES)

    def test_delivered_still_reads_exactly_as_it_did(self):
        """Every row written before this change keeps its meaning and its
        wording. That is what makes the rename unnecessary and the deploy
        order harmless."""
        replies, _ = report_outcomes([self._row(1, "delivered")], set())
        self.assertIn("heard the order", replies[0][1].text)

    def test_applied_says_so_and_says_it_differently(self):
        replies, _ = report_outcomes([self._row(2, "applied")], set())
        self.assertIn("applied", replies[0][1].text)
        self.assertNotIn("heard the order", replies[0][1].text)

    def test_unchanged_is_reported_and_is_not_an_error(self):
        replies, _ = report_outcomes([self._row(3, "unchanged")], set())
        text = replies[0][1].text
        self.assertIn("nothing changed", text.lower())
        self.assertNotIn("did not get the order", text)

    def test_unchanged_names_the_row_to_look_at(self):
        """The row id is the whole handle on the evidence - `result` carries
        the live lists."""
        replies, _ = report_outcomes([self._row(4049, "unchanged")], set())
        self.assertIn("4049", replies[0][1].text)

    def test_an_unknown_future_status_is_reported_rather_than_swallowed(self):
        """Forward compatibility in the other direction: the bridge image can
        be older than the worldserver image."""
        replies, _ = report_outcomes([self._row(5, "something-new")], set())
        self.assertEqual(len(replies), 1)
        self.assertIsNotNone(replies[0][1])

    def test_the_stale_claim_reaper_covers_rows_left_mid_read_back(self):
        """A worldserver that dies between the hand-off and the read-back
        leaves the row in 'verifying' with nothing in memory to finish it -
        the same shape as the abandoned 'claimed' rows this already sweeps."""
        self.assertIn("'verifying'", BRIDGE)

    def test_the_probe_tool_waits_out_a_verifying_row(self):
        self.assertIn('"pending", "claimed", "verifying"', PROBE_TOOL)


if __name__ == "__main__":
    unittest.main()

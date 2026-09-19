"""The act of handing a quest over, and the ways it could crash or lie.

The decision lives in questshare.py and is tested there. This file pins the
half that cannot be unit-tested because it only compiles on push to main:

  * the null-master dereference at AcceptQuestAction.cpp:139, which becomes
    REACHABLE - a worldserver segfault - for any implementation that sets a
    masterless bot's divider and then feeds it the share packet. The only
    defence that survives a refactor is that neither call appears at all;
  * every core API member being one that was verified present in the pinned
    Player.h. A field name that did not exist broke the build for three PRs;
  * a refusal that writes nothing back, leaving an 'error' row nobody outside
    the worldserver can diagnose;
  * `delivered` written because the call returned rather than because the
    quest is in the taker's log - the `sell junk` shape this repo keeps
    meeting;
  * an ENUM value added by editing CREATE TABLE IF NOT EXISTS, which does
    nothing at all to a table that already exists.
"""
import pathlib
import re
import unittest

import questshare

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "mod-overseer/src/mod_overseer.cpp"
MIGRATION = (
    ROOT
    / "mod-overseer/data/sql/characters/base"
    / "2026_08_24_03_overseer_share.sql"
)
BRIDGE = ROOT / "bridge.py"

BANNER = "// --------------------------------------------------------------- share --"


def _source() -> str:
    return MODULE.read_text(encoding="utf-8")


def _share_source() -> str:
    """Everything from the share banner to the end of DoShare."""
    src = _source()
    start = src.index(BANNER)
    end = src.index("    void WriteSnapshot()")
    assert end > start
    return src[start:end]


def _code(text: str) -> str:
    """The same source with every comment removed.

    Load-bearing for the crash tests below: this file NAMES SetDivider and
    HandleMasterIncomingPacket in prose, to say why they are not used. A
    substring search over the raw file would find the explanation and call it
    a violation, so the checks have to run against code alone.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


class TheSharePathIsReachable(unittest.TestCase):
    def test_the_command_loop_dispatches_it(self):
        """A DoShare nobody calls is a feature that exists only in the diff."""
        src = _source()
        self.assertIn('kind == "share"', src)
        self.assertIn("DoShare(player, targetArg, command, status, rowResult)", src)

    def test_it_is_exempt_from_the_bot_trigger_hold(self):
        """kind='share' shares no ChatCommandTrigger, so holding it would only
        delay it - the same exemption chat, gm, probe and give have."""
        self.assertIn('&& kind != "share"', _source())

    def test_the_holder_is_target_name_and_the_taker_is_target_arg(self):
        """The same column roles kind='give' already uses."""
        self.assertIn("DoShare(player, targetArg,", _source())


class TheCrashIsUnreachableByConstruction(unittest.TestCase):
    """AcceptQuestShareAction::Execute dereferences a possibly-null master at
    AcceptQuestAction.cpp:139. It is unreachable today only because nothing
    both sets a roster bot's divider AND feeds it the packet."""

    def test_no_divider_is_ever_set(self):
        self.assertNotIn("SetDivider", _code(_source()), "SetDivider is called")

    def test_the_push_handler_is_never_called(self):
        code = _code(_source())
        self.assertNotIn("HandlePushQuestToParty", code, "the push handler is called")
        self.assertNotIn("CMSG_PUSHQUESTTOPARTY", code, "the share packet is built")

    def test_no_packet_is_ever_fed_to_a_bot(self):
        self.assertNotIn("HandleMasterIncomingPacket", _code(_source()),
                         "a packet is fed to a bot")

    def test_the_reason_is_written_down_where_the_next_reader_will_look(self):
        """A rule with no reason beside it gets 'simplified' away."""
        share = _share_source()
        self.assertIn("AcceptQuestAction.cpp:139", share)
        self.assertIn("segfault", share)


class EveryCoreCallWasVerifiedAgainstThePinnedHeaders(unittest.TestCase):
    """The C++ only compiles on push to main. Every member has to have been
    read out of the pinned core, and cited, before it is used."""

    # Player.h and friends at core efe123fab543c5faf3c477674ec17a18fd59f09f.
    VERIFIED = {
        "CanShareQuest": "Player.h:1561",
        "SatisfyQuestStatus": "Player.h:1477",
        "SatisfyQuestLog": "Player.h:1472",
        "CanTakeQuest": "Player.h:1456",
        "CanAddQuest": "Player.h:1457",
        "AddQuestAndCheckCompletion": "Player.h:1462",
        "GetQuestStatus": "Player.h:1492",
        "GetQuestRewardStatus": "Player.h:1491",
        "GetGroup": "Player.h:2520",
        "IsInMap": "Object.h:542",
        "IsMember": "Group.h:238",
    }

    # Members already used elsewhere in this file, which the build has
    # therefore already proven for us.
    ALREADY_PROVEN = {"GetName", "GetGUID", "GetTitle", "GetQuestTemplate"}

    def test_every_member_used_is_on_the_verified_list(self):
        # Comments stripped first: the banner QUOTES upstream code this
        # implementation deliberately does not call, and a member named only
        # in prose is not a member used.
        share = _code(_share_source())
        used = set(re.findall(r"->([A-Z][A-Za-z]+)\(", share))
        unknown = used - set(self.VERIFIED) - self.ALREADY_PROVEN
        self.assertEqual(unknown, set(), "unverified core members: %s" % sorted(unknown))

    def test_each_one_is_cited_with_a_header_and_a_line(self):
        share = _share_source()
        for member, where in self.VERIFIED.items():
            if member not in share:
                continue
            self.assertIn(where, share, "%s is used but not cited" % member)

    def test_the_quest_is_added_with_the_null_safe_call(self):
        """AddQuestAndCheckCompletion fires OnPlayerQuestAccept, auto-completes
        an instantly-satisfiable quest, and returns early on a null quest giver
        (core PlayerQuest.cpp:568-569)."""
        self.assertIn("AddQuestAndCheckCompletion(quest, holder)", _share_source())


class TheCoreEligibilityChecksAreAllThere(unittest.TestCase):
    """The same set WorldSession::HandlePushQuestToParty applies (core
    QuestHandler.cpp:529-603). Skipping them is how a level 10 priest ends up
    holding a level 20 quest she can never finish."""

    def test_sharability_and_holding_are_checked_together(self):
        self.assertIn("holder->CanShareQuest(questId)", _share_source())

    def test_the_takers_state_level_log_and_bags_are_all_checked(self):
        share = _share_source()
        for call in (
            "taker->SatisfyQuestStatus(quest, false)",
            "taker->SatisfyQuestLog(false)",
            "taker->CanTakeQuest(quest, false)",
            "taker->CanAddQuest(quest, false)",
        ):
            self.assertIn(call, share, call)

    def test_they_all_run_before_anything_is_added(self):
        share = _share_source()
        add = share.index("AddQuestAndCheckCompletion(quest, holder)")
        for call in (
            "CanShareQuest(questId)",
            "SatisfyQuestStatus(quest, false)",
            "SatisfyQuestLog(false)",
            "CanTakeQuest(quest, false)",
            "CanAddQuest(quest, false)",
        ):
            self.assertLess(share.index(call), add, call)

    def test_the_party_and_the_map_are_checked_too(self):
        share = _share_source()
        self.assertIn("group->IsMember(taker->GetGUID())", share)
        self.assertIn("taker->IsInMap(holder)", share)


class NoRefusalIsSilent(unittest.TestCase):
    """A row that ends without a result is a row nobody can diagnose from
    outside the worldserver."""

    def _returns(self):
        """Every `return "...";` in DoShare, with the code since the previous
        one - which is the window a `describe()` for THAT exit has to be in."""
        share = _share_source()
        body = share[share.index("static char const* DoShare"):]
        out = []
        cursor = 0
        for match in re.finditer(r'return "((?:[^"\\]|\\.)*)";', body, re.S):
            out.append((body[cursor:match.start()], match.group(1)))
            cursor = match.end()
        return out

    def test_every_exit_writes_a_result_first(self):
        """Not "somewhere above" - in the window since the PREVIOUS exit. A
        refusal that reuses the last one's result reports the wrong reason,
        which is worse than reporting none."""
        found = self._returns()
        self.assertGreaterEqual(len(found), 13, "expected the full refusal set")
        for window, text in found:
            self.assertIn("describe(", window, text or "(the success path)")

    def test_the_refusals_are_distinguishable_from_each_other(self):
        """'not eligible', 'log full' and 'already held' need different
        answers from an operator, so they must not read the same."""
        share = _share_source()
        for reason in (
            "malformed request",
            "no taker",
            "taker offline",
            "same character",
            "no such quest",
            "holder cannot share it",
            "not in the same party",
            "not on the same map",
            "taker already turned it in",
            "taker already holds it",
            "taker quest log is full",
            "taker is not eligible",
            "no bag space",
        ):
            self.assertIn(reason, share, reason)

    def test_no_detail_literal_carries_a_quote_character(self):
        """`detail` is embedded straight into the UPDATE that reports the
        outcome, so an apostrophe there is a broken statement."""
        for _before, text in self._returns():
            self.assertNotIn("'", text, text)

    def test_the_result_json_names_both_characters_and_the_quest(self):
        # The JSON is built inside C++ string literals, so the quotes around
        # each key are escaped in the source and the needle carries them too.
        share = _share_source()
        for field in ("outcome", "reason", "from", "to", "quest_id", "taker_status"):
            self.assertIn(r'\"%s\":' % field, share, field)


class DeliveredMeansItIsInTheLog(unittest.TestCase):
    """The defining bug of this project is an action that reports success while
    doing nothing. `sell junk` returned TRUE and sold nothing."""

    def test_success_is_written_once_and_only_once(self):
        self.assertEqual(_share_source().count('status = "delivered"'), 1)

    def test_the_takers_log_is_read_back_after_the_add(self):
        share = _share_source()
        add = share.index("AddQuestAndCheckCompletion(quest, holder)")
        readback = share.index("QuestStatus const after = taker->GetQuestStatus(questId)")
        self.assertGreater(readback, add)

    def test_and_the_success_is_written_after_that_read(self):
        share = _share_source()
        readback = share.index("QuestStatus const after")
        self.assertGreater(share.index('status = "delivered"'), readback)

    def test_a_quest_that_did_not_land_is_an_error_not_a_delivery(self):
        share = _share_source()
        self.assertIn("if (after == QUEST_STATUS_NONE)", share)
        self.assertIn("the quest did not land in the taker log", share)


class TheEnumNeedsAnAlter(unittest.TestCase):
    """CREATE TABLE IF NOT EXISTS is a no-op against an existing table, so it
    cannot add an ENUM value. This trap has bitten the codebase twice."""

    def _sql(self) -> str:
        return MIGRATION.read_text(encoding="utf-8")

    def _statements(self) -> str:
        """The SQL with its `--` commentary removed.

        The commentary EXPLAINS the CREATE TABLE trap, so a substring search
        over the whole file would find the explanation and call it the
        mistake.
        """
        return re.sub(r"^--.*$", "", self._sql(), flags=re.M)

    def test_the_migration_exists_and_alters(self):
        self.assertIn("ALTER TABLE", self._statements())
        self.assertIn("MODIFY COLUMN `kind`", self._statements())

    def test_it_adds_share_without_dropping_what_is_already_there(self):
        sql = self._statements()
        for value in ("'bot'", "'chat'", "'gm'", "'probe'", "'give'", "'share'"):
            self.assertIn(value, sql, value)

    def test_it_does_not_try_to_do_it_with_a_create(self):
        self.assertNotIn("CREATE TABLE", self._statements(),
                         "an ENUM value cannot be added by a CREATE")

    def test_the_default_survives(self):
        self.assertIn("NOT NULL DEFAULT 'bot'", self._statements())


class TheBridgeAsksForWhatTheDecisionNeeds(unittest.TestCase):
    def _bridge(self) -> str:
        return BRIDGE.read_text(encoding="utf-8")

    def test_the_catalog_read_carries_the_sharable_flag(self):
        """questshare fails CLOSED without Flags, so a missing column would
        mean a pass that silently shares nothing."""
        self.assertIn("t.Flags", self._bridge())

    def test_the_command_is_inserted_with_the_share_kind(self):
        self.assertIn("'share'", self._bridge())
        self.assertIn("grant.holder, grant.command, grant.taker", self._bridge())

    def test_the_pass_is_actually_scheduled(self):
        """A loop nobody registers is a feature that exists only in the diff -
        and asyncio drops a task with no other referent, silently."""
        bridge = self._bridge()
        self.assertIn("self._share_quests_loop,", bridge)
        self.assertIn("async def _share_quests_loop", bridge)

    def test_the_decision_is_not_reimplemented_next_to_the_insert(self):
        """Every eligibility rule must come from questshare/questbook, or the
        two halves will describe different families."""
        bridge = self._bridge()
        share = bridge[bridge.index("def _share_quests("):bridge.index("def _choose_drive_quest")]
        for smell in ("allowable_classes", "prev_quest_id", "1101", "class_bit"):
            self.assertNotIn(smell, share, smell)
        self.assertIn("questshare.plan(members, catalog)", share)

    def test_it_says_what_it_did_even_when_it_did_nothing(self):
        bridge = self._bridge()
        self.assertIn("questshare.say(plan)", bridge)


# Spark-authored: qwen3-coder-next:q8_0 on an on-prem DGX Spark, 2026-09-02; the
# reason-aware split and the backoff were added by hand after two Codex rounds.
class TheShareRetryLogic(unittest.TestCase):
    """The pass backs off a share the worldserver keeps refusing for a
    PERMANENT reason (infra#2892), doubling the wait up to a cap.

    These pin source text, like the rest of this file; the SQL runs only
    against the real characters database. Which refusals count, and the
    arithmetic, is questshare.backed_off(), tested behaviorally in
    test_questshare.py.
    """

    def _bridge(self) -> str:
        return BRIDGE.read_text(encoding="utf-8")

    def _share_quests_body(self) -> str:
        bridge = self._bridge()
        start = bridge.index("def _share_quests()")
        return bridge[start : bridge.index("def _choose_drive_quest")]

    def test_it_is_a_backoff_not_a_rolling_window_threshold(self):
        """Two shapes died before this one. The first counted errors inside
        SHARE_RETRY_MINUTES, the window that already admits one row per
        triple, so no threshold above one was reachable. The second counted
        inside a longer rolling window, and Codex showed that only pauses
        the loop: once the window is full, every row that ages out admits a
        fresh hourly retry. The bridge hands the rows and their ages to
        questshare and applies whatever it says."""
        body = self._share_quests_body()
        self.assertIn(
            "questshare.backed_off(\n"
            "        _answered_share_rows(\n"
            "            SHARE_REFUSAL_MEMORY_DAYS,\n"
            "            questshare.history_depth(SHARE_RETRY_MINUTES, SHARE_BACKOFF_CAP_HOURS),\n"
            "        ),\n"
            "        SHARE_RETRY_MINUTES,\n"
            "        SHARE_BACKOFF_CAP_HOURS,\n"
            "    )",
            body,
        )
        self.assertNotIn("SHARE_GIVE_UP_HOURS", self._bridge())
        self.assertNotIn("SHARE_RETRY_MAX_FAILURES", self._bridge())

    def test_the_bridge_does_not_decide_which_refusals_are_permanent(self):
        """The Codex review of the draft found that five 'taker offline' rows
        would suppress a share for a day. The bridge fetches (holder, taker,
        command, status, result, age) rows and nothing more; questshare reads the
        worldserver's reason and keeps that decision under real tests. The
        age comes from the database's clock, not the container's."""
        bridge = self._bridge()
        helper = bridge[bridge.index("def _answered_share_rows") : bridge.index("def _insert_share")]
        self.assertIn("SELECT target_name, target_arg, command, status, result, ", helper)
        # the answer's age, not the ask's: a row can sit pending or claimed
        # before the worldserver reaches it, and measured from created_at a
        # queue delay would eat the quiet time (Codex, round 4)
        self.assertIn("TIMESTAMPDIFF(SECOND, updated_at, NOW()) AS age_s", helper)
        self.assertIn("updated_at > NOW() - INTERVAL %s DAY", helper)
        self.assertNotIn("created_at >", helper)
        self.assertNotIn("TIMESTAMPDIFF(SECOND, created_at", helper)
        # delivered rows too: a delivery resets the streak (Codex, round 3)
        self.assertIn("status IN ('delivered', 'error')", helper)
        self.assertIn("INTERVAL %s DAY", helper)
        self.assertNotIn("GROUP BY", helper)
        self.assertNotIn("HAVING", helper)
        # and no reason literal: the SQL windows per reason without knowing
        # what any of them means
        for reason in questshare.PERMANENT_REFUSALS:
            self.assertNotIn(reason, helper)

    def test_the_read_is_bounded_by_triples_not_by_history(self):
        """Codex, round 5: read whole, the ninety-day window is every hourly
        transient retry of every triple - a party split for a season is two
        hundred thousand rows every five minutes, and the read timeout would
        then stop EVERY share. The SQL keeps the youngest history_depth()
        rows per (triple, status, reason), which questshare proves decides
        identically (test_questshare's random-history property), and the
        reason is extracted behind JSON_VALID because JSON_EXTRACT on a
        non-JSON result is an error rather than a NULL."""
        bridge = self._bridge()
        helper = bridge[bridge.index("def _answered_share_rows") : bridge.index("def _insert_share")]
        self.assertIn("def _answered_share_rows(days: int, depth: int)", helper)
        self.assertIn("ROW_NUMBER() OVER (", helper)
        self.assertIn("PARTITION BY target_name, target_arg, command, status, ", helper)
        self.assertIn("CASE WHEN JSON_VALID(result) ", helper)
        self.assertIn("THEN JSON_UNQUOTE(JSON_EXTRACT(result, '$.reason')) END", helper)
        self.assertIn("ORDER BY updated_at DESC) AS rn", helper)
        self.assertIn("WHERE rn <= %s", helper)
        self.assertIn("(int(days), int(depth))", helper)

    def test_the_read_has_an_index_shaped_like_it(self):
        """overseer_command is never pruned and shipped with idx_status only;
        a five-minute read of kind + status + updated_at range would walk
        every answered row the table ever held. The migration's key must
        match the predicate, columns in that order."""
        sql = (MIGRATION.parent / "2026_09_02_00_overseer_share_backoff.sql").read_text(encoding="utf-8")
        self.assertIn("ADD KEY `idx_kind_status_updated` (`kind`, `status`, `updated_at`)", sql)

    def test_the_index_ships_in_the_image_that_is_built(self):
        """Codex, round 6: the worldserver image is built from
        UPSTREAM-PINS.env's AC_OVERSEER_SHA, and its workflow is triggered by
        that file - not by the submodule gitlink the source-reading tests
        look at. A branch that bumps the gitlink and leaves the pin behind
        ships the bridge's read without its index. The two must name the
        same commit, and that commit must carry the migration."""
        import subprocess

        pins = (ROOT / "UPSTREAM-PINS.env").read_text(encoding="utf-8")
        pinned = re.search(r"^AC_OVERSEER_SHA=([0-9a-f]{40})$", pins, re.MULTILINE)
        self.assertIsNotNone(pinned, "AC_OVERSEER_SHA missing from UPSTREAM-PINS.env")
        gitlink = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-s", "--", "mod-overseer"],
            capture_output=True, text=True, check=True,
        ).stdout.split()
        self.assertEqual(gitlink[:1], ["160000"], "mod-overseer is not a gitlink here")
        self.assertEqual(pinned.group(1), gitlink[1])
        checked_out = subprocess.run(
            ["git", "-C", str(MIGRATION.parents[4]), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(checked_out, gitlink[1], "the submodule checkout is not at the gitlink")
        self.assertTrue((MIGRATION.parent / "2026_09_02_00_overseer_share_backoff.sql").is_file())

    def test_the_constants_are_environment_overridable(self):
        bridge = self._bridge()
        self.assertIn('os.environ.get("SHARE_BACKOFF_CAP_HOURS", "168")', bridge)
        self.assertIn('os.environ.get("SHARE_REFUSAL_MEMORY_DAYS", "90")', bridge)

    def test_the_pass_skips_held_shares_and_says_so(self):
        body = self._share_quests_body()
        self.assertIn("in held", body)
        self.assertIn("questshare: holding off", body)

    def test_the_pass_still_inserts_new_shares(self):
        """A new share (not in seen or held) still gets inserted."""
        self.assertIn("if _insert_share(grant):", self._share_quests_body())


if __name__ == "__main__":
    unittest.main()

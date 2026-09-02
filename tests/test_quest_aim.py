"""The council decided, the decision was persisted, and nobody read it.

#2776 threaded a council quest decision from `quests.focus()` through
`council.Plan.quest_id` into `overseer_roster.drive_quest`. Then it stopped.
`DriveQuests()` never mentioned the column: it went on picking the first
eligible quest in the party leader's own log, which is why the family could
agree in party chat to fetch Ugga's last Large Candle and then stand still -
measured at 0.0 yards in 45 seconds, eleven yards from the kobolds that drop it.

The C++ in this repo is only compiled on push to `main`, never on a PR, and a
field name that did not exist once broke the build for three PRs' worth of work.
So these are contract tests over the source text, in the pattern
test_quest_share.py established: they assert the shape of the change and that
every core and module member it touches was read out of the pinned headers and
cited in place.

Pins (production/docker/azerothcore-playerbots/UPSTREAM-PINS.env):
    core   efe123fab543c5faf3c477674ec17a18fd59f09f
    module 8d9f6aa6bc6d45f9ae0ee0675b9b1f8aa6937312
Neither is vendored here. Every line number below was read from those two.
"""
import pathlib
import re
import unittest

MODULE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
)
MIGRATION = (
    pathlib.Path(__file__).resolve().parents[3]
    / "docker/azerothcore-playerbots/mod-overseer/data/sql/characters/base"
    / "2026_08_24_00_overseer_roster_drive_quest.sql"
)


def _function(name: str) -> str:
    """The whole of a member function, braces balanced."""
    src = MODULE.read_text(encoding="utf-8")
    start = src.index(name)
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("%s has no closing brace" % name)


def _code(text: str) -> str:
    """The same text with // comments stripped.

    Searching the raw source is not a reachability test: the comments here
    quote upstream code this implementation deliberately does not call, and a
    member named only in prose is not a member used.
    """
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _drive() -> str:
    return _function("void DriveQuests()")


def _chosen() -> str:
    return _function("bool DriveChosenQuest(")


def _clear() -> str:
    return _function("void ClearAim(")


class TheColumnIsActuallyRead(unittest.TestCase):
    """It was written by the bridge and read by nobody. That was the bug."""

    def test_the_query_selects_the_aim(self):
        """Read by LoadQuestAims since infra#2846, not inline in the drive's own
        roster query - a `drive_quest` the schema does not have would otherwise
        null that query and take the leader's own-log fallback down with it. The
        property that matters here is unchanged: the aim is READ."""
        self.assertIn("LoadQuestAims()", _code(_drive()))
        self.assertIn("drive_quest", _code(_function("std::map<std::string, uint32> LoadQuestAims()")))

    def test_only_the_leader_free_roams_its_own_quest_log(self):
        """The lesson this guard encodes has NOT changed; where it is enforced
        has (infra#2801, "quest together").

        `new rpg` acts at relevance 3.0-11.0 against follow's 1.0, so a bot
        holding both wanders every tick: 937 yards of spread before it was
        taken off the followers, three yards after. What scatters a party is
        each member pursuing a DIFFERENT objective, and the first-eligible walk
        below picks out of each character's OWN log - which is divergent by
        construction.

        So every enabled member is now considered, because a follower that
        cannot be aimed can never hand a quest in (turn-in is reachable only
        through the rpg strategy) - but ONLY the leader may fall through to
        that divergent walk. An aimed follower goes where the rest of the
        family goes; an unaimed one stays put.
        """
        body = _code(_drive())
        self.assertIn("enabled = 1", body)
        self.assertNotIn("`lead` = 1", body,
                         "a leader-only query makes a follower's aim unreadable")
        guard = body.index("if (!isLead)")
        walk = body.index("MAX_QUEST_LOG_SIZE")
        self.assertLess(guard, walk,
                        "the divergent log walk must stay behind the leader gate")

    def test_the_column_the_module_reads_is_the_one_the_migration_adds(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN `drive_quest`", sql)
        self.assertIn("overseer_roster", _code(_drive()))

    def test_the_two_columns_are_fetched_by_index_not_by_one_getter(self):
        body = _code(_function("std::map<std::string, uint32> LoadQuestAims()"))
        self.assertIn("fields[0]", body)
        self.assertIn("fields[1]", body)


class TheAimIsPreferredAndTheFallbackSurvives(unittest.TestCase):
    def test_the_aim_is_consulted_before_the_leaders_own_log(self):
        body = _code(_drive())
        self.assertLess(
            body.index("DriveChosenQuest("), body.index("GetQuestSlotQuestId"),
            "the log walk runs before the aim is considered, so the aim is decoration",
        )

    def test_zero_means_no_opinion_and_falls_back(self):
        """A stale or unreachable aim must degrade to today's behaviour, not to
        standing still - which is the failure this whole epic is about."""
        body = _code(_drive())
        self.assertIn("bool const aimed = aim != 0;", body)
        self.assertIn("GetQuestSlotQuestId", body)
        self.assertIn("ChangeToDoQuest", body)

    def test_the_fallback_still_only_takes_a_quest_worth_working(self):
        body = _code(_drive())
        self.assertIn("QUEST_STATUS_INCOMPLETE", body)
        self.assertIn("QUEST_STATUS_COMPLETE", body)

    def test_a_refused_aim_returns_false_rather_than_aiming_anyway(self):
        self.assertIn("return false;", _code(_chosen()))


class TheLeaseIsReasserted(unittest.TestCase):
    """RPG_DO_QUEST self-expires after statusDoQuestDuration = 30 minutes
    (NewRpgAction.h:68, checked at NewRpgAction.cpp:288) and the bot then
    re-rolls its own status, including a RANDOM quest out of its log. Set the
    aim once and walk away and the party silently reverts half an hour later."""

    def test_being_on_a_quest_no_longer_short_circuits_the_aim(self):
        """The old code skipped any bot in RPG_DO_QUEST before looking at
        anything else. Leave that in front of the aim and the lease can never
        be corrected, only lost."""
        body = _code(_drive())
        self.assertLess(
            body.index("DriveChosenQuest("), body.index("if (onQuest)\n                continue;"),
            "the RPG_DO_QUEST skip runs before the aim, so a drifted lease is never re-asserted",
        )

    def test_the_quest_currently_being_worked_is_read_back(self):
        """Re-asserting blind would restart the travel every twenty seconds -
        a character that walks toward an objective forever and never arrives.
        So the current DoQuest questId has to be compared, not assumed."""
        body = _code(_drive())
        self.assertIn("RPG_DO_QUEST", body)
        self.assertIn("std::get_if<NewRpgInfo::DoQuest>", body)
        self.assertIn("questId", body)

    def test_an_unchanged_lease_is_left_alone(self):
        self.assertIn("if (working == questId)", _code(_chosen()))
        self.assertIn("return true;", _code(_chosen()))

    def test_the_variant_header_is_included(self):
        """std::get_if needs <variant>. NewRpgInfo.h uses std::variant without
        including it, so relying on the transitive include is how this breaks
        on a header reshuffle we do not control."""
        self.assertIn("#include <variant>", MODULE.read_text(encoding="utf-8"))


class TheLeaderMustHoldTheQuest(unittest.TestCase):
    """NewRpgDoQuestAction dispatches only on QUEST_STATUS_INCOMPLETE and
    QUEST_STATUS_COMPLETE and otherwise calls info.ChangeToIdle(). Aiming a bot
    at a quest it does not carry is a silent no-op - exactly the "delivered but
    nothing happened" failure this epic keeps hitting."""

    def test_the_hold_is_checked_before_the_aim_is_applied(self):
        body = _code(_chosen())
        self.assertLess(body.index("GetQuestStatus"), body.index("ChangeToDoQuest"))

    def test_both_workable_statuses_are_accepted_and_nothing_else(self):
        body = _code(_chosen())
        self.assertIn("QUEST_STATUS_INCOMPLETE", body)
        self.assertIn("QUEST_STATUS_COMPLETE", body)

    def test_a_quest_the_world_does_not_know_is_refused_too(self):
        body = _code(_chosen())
        self.assertIn("GetQuestTemplate", body)
        self.assertIn("if (!quest)", body)

    def test_not_holding_it_is_reported(self):
        self.assertIn("does not hold it", _chosen())


class NoPathIsSilent(unittest.TestCase):
    """The defining bug of this epic is an action that reports success while
    doing nothing. #2787 gave `module.overseer` a real appender, so there is no
    longer any excuse for an aim that lands or fails to land in silence."""

    LOG = 'LOG_INFO("module.overseer"'

    def test_every_refusal_logs_before_it_returns(self):
        body = _chosen()
        for match in re.finditer(r"return false;", body):
            before = body[max(0, match.start() - 900):match.start()]
            self.assertIn(self.LOG, before,
                          "a refusal at offset %d says nothing" % match.start())

    def test_every_aim_that_is_applied_logs_first(self):
        for body in (_drive(), _chosen()):
            for match in re.finditer(r"ChangeToDoQuest\(", body):
                before = body[max(0, match.start() - 700):match.start()]
                self.assertIn(self.LOG, before,
                              "a quest is aimed with nothing written down")

    def test_the_paths_a_reader_has_to_tell_apart_are_all_distinct(self):
        """No aim (picked), aim applied, aim refused because the quest is not
        held, aim re-asserted after the lease lapsed, aim re-asserted after
        drift, aim cleared externally, a turn-in of the WRONG quest, the aim
        released on its own quest's reward, the aim given up as unreachable.
        Nine outcomes, nine different sentences - because "a quest got turned
        in while an aim was set" is not evidence the aim did anything."""
        both = _drive() + _chosen()
        phrases = [
            "picked from its own",
            "chosen by the council",
            "does not hold it",
            "lease had lapsed",
            "had drifted onto quest",
            "quest aim cleared",
            "opportunistic turn-in",
            "the errand is done",
            "releasing the aim as unreachable",
        ]
        for phrase in phrases:
            self.assertIn(phrase, both, "no log line covers %r" % phrase)
        self.assertEqual(len(set(phrases)), len(phrases))

    def test_a_standing_complaint_is_not_repeated_three_times_a_minute(self):
        """The poll is 20 seconds. An unchanged aim that cannot land has to be
        said once, or the log it is written to becomes unreadable."""
        self.assertIn("aimChanged", _code(_drive()))
        self.assertIn("if (aimChanged)", _code(_chosen()))


def _backstop_comment() -> str:
    src = MODULE.read_text(encoding="utf-8")
    start = src.index("constexpr uint32 QUEST_POLL_MS")
    return src[start:src.index("DRIVE_AIM_BACKSTOP_SECONDS = ") + 80]


class TheAimIsReleasedOnItsOwnQuestsReward(unittest.TestCase):
    """Measured in the dev world: a bot given `new rpg` and left alone walked
    79 yards, handed in the ONE parked quest whose giver it happened to path
    past, then re-rolled and stalled for eight minutes with two still parked.
    rpg is opportunistic, not systematic. So the aim has to be released by the
    AIMED quest being handed in - one errand per parked quest - and a blanket
    "flip them to rpg for a while" clears roughly one and leaves the rest,
    non-deterministically. That is why the blanket toggle was rejected."""

    def test_the_release_reads_the_reward_of_the_aimed_quest(self):
        body = _code(_drive())
        self.assertIn("GetQuestRewardStatus(aim)", body)

    def test_the_release_actually_writes_the_column_back_to_zero(self):
        """Left standing, a finished aim is re-offered every twenty seconds
        forever and refused every time."""
        body = _code(_drive())
        self.assertIn("ClearAim(name)", body)
        clear = _code(_clear())
        self.assertIn("SET drive_quest = 0", clear)
        self.assertIn("overseer_roster", clear)

    def test_the_release_is_not_triggered_by_just_any_quest(self):
        """`observed a reward` is not `observed THIS reward`. The reward test
        has to name the aim."""
        body = _code(_drive())
        for match in re.finditer(r"GetQuestRewardStatus\(([^)]*)\)", body):
            self.assertIn(match.group(1), ("aim", "state.lastWorking"),
                          "a reward check that names neither the aim nor the "
                          "quest being worked: %r" % match.group(1))

    def test_a_turn_in_of_a_different_quest_says_so(self):
        body = _drive()
        self.assertIn("GetQuestRewardStatus(state.lastWorking)", _code(body))
        self.assertIn("opportunistic turn-in", body)

    def test_the_backstop_exists_and_is_a_backstop_not_the_release(self):
        src = MODULE.read_text(encoding="utf-8")
        self.assertIn("DRIVE_AIM_BACKSTOP_SECONDS", _code(src))
        body = _code(_drive())
        self.assertLess(
            body.index("GetQuestRewardStatus(aim)"), body.index("DRIVE_AIM_BACKSTOP_SECONDS"),
            "the timer is consulted before the reward, which makes it the release",
        )

    def test_the_backstop_outlives_the_thirty_minute_rpg_lease(self):
        """Release an aim merely because RPG_DO_QUEST lapsed and you have built
        the 30-minute re-roll back in by hand. Re-assertion handles that; the
        backstop is for an aim that can never land at all."""
        src = _code(MODULE.read_text(encoding="utf-8"))
        match = re.search(r"DRIVE_AIM_BACKSTOP_SECONDS = ([^;]+);", src)
        self.assertIsNotNone(match)
        seconds = eval(match.group(1), {"__builtins__": {}}, {})  # noqa: S307
        self.assertGreater(seconds, 30 * 60)

    def test_a_released_aim_falls_back_rather_than_standing_still(self):
        body = _code(_drive())
        self.assertIn("stillAimed", body)
        self.assertLess(body.index("stillAimed = false"), body.index("if (stillAimed)"))


class EveryMemberUsedWasVerifiedAgainstThePinnedSources(unittest.TestCase):
    """The C++ only compiles on push to main. Every member has to have been
    read at the pin, and cited where it is used, before it is used."""

    VERIFIED = {
        # core efe123fab543c5faf3c477674ec17a18fd59f09f - the dungeon gate.
        # A quest aim inside an instance cannot be satisfied or abandoned and
        # overwrites the rpgInfo the dungeon run needs, so the drive stands
        # down there. Read at the PINNED FORK, not upstream azerothcore.
        "GetMap": "Object.h:631",
        "IsDungeon": "Map.h:298",
        "GetMapId": "Position.h:281",
        # core efe123fab543c5faf3c477674ec17a18fd59f09f
        "GetQuestStatus": "Player.h:1492",
        "GetQuestSlotQuestId": "Player.h:1510",
        "GetQuestRewardStatus": "Player.h:1491",
        # core efe123fab543c5faf3c477674ec17a18fd59f09f - the repick ratchet.
        # "Abandoned without moving" is now measured as a straight-line
        # distance from where the quest was picked, fed to
        # OverseerDecisions::RatchetProgressed, rather than compared by hand
        # against the squared form. Public via `struct Position` (Position.h:26).
        "GetExactDist2d": "Position.h:170",
        # module 8d9f6aa6bc6d45f9ae0ee0675b9b1f8aa6937312
        "rpgInfo": "PlayerbotAI.h:603",
        "GetStatus": "NewRpgInfo.h:99",
        "ChangeToDoQuest": "NewRpgInfo.h:106",
        "data": "NewRpgInfo.h:97",
        "DoQuest": "NewRpgInfo.h:47-54",
    }

    # Members already used elsewhere in this file, which the build has
    # therefore already proven for us.
    ALREADY_PROVEN = {"Fetch", "NextRow", "Get", "GetTitle", "GetQuestTemplate",
                      "FindPlayerByName",
                      # infra#2801 reads the traveller's position in DriveQuests
                      # to tell "abandoned without moving" from "travelling".
                      # The snapshot writer in this same file has called these
                      # since long before, so the build has proven them. Z is
                      # deliberately absent: the diff does not use it.
                      "GetPositionX", "GetPositionY"}

    def test_every_arrow_member_used_is_on_the_verified_list(self):
        body = _code(_drive() + _chosen())
        used = set(re.findall(r"->([A-Za-z_][A-Za-z0-9_]*)\(", body))
        unknown = used - set(self.VERIFIED) - self.ALREADY_PROVEN
        self.assertEqual(unknown, set(), "unverified members: %s" % sorted(unknown))

    def test_the_rpg_state_is_reached_through_the_verified_members_only(self):
        body = _code(_drive() + _chosen())
        used = set(re.findall(r"rpgInfo\.([A-Za-z_][A-Za-z0-9_]*)", body))
        unknown = used - set(self.VERIFIED)
        self.assertEqual(unknown, set(), "unverified rpgInfo members: %s" % sorted(unknown))

    def test_each_one_is_cited_with_a_header_and_a_line(self):
        both = _drive() + _chosen()
        for member, where in self.VERIFIED.items():
            if member not in both:
                continue
            self.assertIn(where, both, "%s is used but not cited" % member)

    def test_the_expiry_that_makes_this_a_lease_is_cited_too(self):
        self.assertIn("NewRpgAction.h:68", _drive() + _backstop_comment())


class NothingElseWasQuietlyChanged(unittest.TestCase):
    def test_the_driver_is_still_on_the_quest_poll(self):
        src = _code(MODULE.read_text(encoding="utf-8"))
        self.assertIn("DriveQuests();", src)
        self.assertIn("QUEST_POLL_MS", src)

    def test_no_follower_is_given_new_rpg_here(self):
        """The one change that would scatter the family again."""
        body = _code(_drive() + _chosen())
        self.assertNotIn("+new rpg", body)
        self.assertNotIn("HandleCommand", body)

    def test_the_remembered_aim_is_the_only_state_kept(self):
        """The roster row stays the memory. This map exists to keep the log
        readable and nothing reads a decision out of it."""
        src = MODULE.read_text(encoding="utf-8")
        self.assertIn("std::map<std::string, AimState> _lastAim;", src)


if __name__ == "__main__":
    unittest.main()


class TheSecondErrandOnTheSameBot(unittest.TestCase):
    """Measured in dev on 2026-08-24, and it is why this class exists.

    Ymrossi drifted onto quest 233 by itself, was re-asserted onto the council's
    3109, handed 3109 in, and its rpg then re-rolled back onto 233. Aiming it at
    233 for a SECOND errand did nothing at all: `working == questId` was already
    true, so DriveChosenQuest returned early and silently. The bot sat holding a
    DoQuest state for 233 whose objective pointer belonged to its own earlier
    pursuit - and 233 was already COMPLETE, so there was no objective left to
    walk to and it never advanced to the hand-in.

    Nothing detected it. The bot held the aimed quest, the aim was set, the
    roster row was right, and every check passed. The only symptom was the
    ABSENCE of a log line, which is the second time in one session that absence
    was the diagnostic.

    The guard is correct for the steady state - re-issuing every twenty seconds
    resets objectiveIdx/pos/lastReachPOI and walks toward an objective forever -
    and wrong for the transition, which is the one moment the state behind the
    lease belongs to a different, self-chosen pursuit.
    """

    def test_the_steady_state_guard_is_gated_on_the_aim_not_having_changed(self):
        code = _code(_function("bool DriveChosenQuest"))
        self.assertIn("working == questId && !aimChanged", code)
        self.assertNotRegex(
            code,
            r"if\s*\(\s*working == questId\s*\)\s*\n\s*return true;",
            "an ungated `working == questId` early return swallows every second "
            "errand on a bot that had already chosen that quest itself",
        )

    def test_a_new_errand_reissues_even_when_the_id_already_matches(self):
        code = _code(_function("bool DriveChosenQuest"))
        tail = code.split("working == questId && !aimChanged", 1)[1]
        self.assertIn("ChangeToDoQuest", tail,
                      "the aim-changed path must reset the objective pointer")

    def test_that_reissue_is_announced_rather_than_being_a_third_silent_branch(self):
        body = _function("bool DriveChosenQuest")
        self.assertIn("by its own choice", body)
        self.assertIn("re-issuing for the new errand", body)

    def test_the_measurement_that_found_it_is_recorded_in_place(self):
        body = _function("bool DriveChosenQuest")
        for needle in ("Ymrossi", "233", "3109", "COMPLETE"):
            self.assertIn(needle, body, needle)

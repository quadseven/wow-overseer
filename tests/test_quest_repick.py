"""The leader re-picked the same unreachable quest every twenty seconds, forever.

infra#2801. Measured on the live realm over a twelve-minute window:

    38 x  'Grug' now working quest 109

Only Grug, only quest 109, and 0.0 yards travelled. `DriveQuests()` already
guards against blind re-issue (`if (onQuest) continue;`), so for that line to
fire every poll the bot must be falling OUT of `RPG_DO_QUEST` inside each
twenty-second window on its own - `NewRpgDoQuestAction` idles when it cannot
proceed. `DriveQuests()` then walks the quest log, takes the first eligible
entry, and picks the same one again. Nothing remembers that it just failed.

Quest 109's turn-in is Gryan Stoutmantle in WESTFALL; Grug is in Elwynn. All
three of his completed quests turn in outside the zone (109 Westfall, 1097 and
1638 Stormwind), so advancing past one lands on another - which is why the
first-eligible-forever half has to be fixed with MEMORY and not merely with a
cursor that moves on.

What this change does NOT do is teach the bot to cross a zone. That is the
other half of #2801 and it lives in upstream `NewRpgDoQuestAction`. This makes
the wedge stop and makes it VISIBLE, which is what acceptance criteria 1, 2 and
3 ask for ("stops re-picking one it cannot reach", "a quest that has just
failed is not re-picked in preference to an untried one", "giving up is
recorded, not silent").

The C++ in this repo is only compiled on push to `main`, never on a PR, and a
field name that did not exist once broke the build for three PRs' worth of
work. So these are contract tests over the source text, in the pattern
test_quest_share.py established and test_quest_aim.py continued.

Pins (production/UPSTREAM-PINS.env):
    core   efe123fab543c5faf3c477674ec17a18fd59f09f
    module 8d9f6aa6bc6d45f9ae0ee0675b9b1f8aa6937312

This change introduces exactly ONE new upstream member, `lowPriorityQuest`
(PlayerbotAI.h:605), and it is the safest kind: `rpgInfo` sits two lines above
it at :603 in the same `public:` block (opened at :386) and `mod_overseer.cpp`
already calls that, so a build which has already succeeded proves the block's
accessibility. Everything else it reads - `GetQuestSlotQuestId`,
`GetQuestStatus`, `GetQuestRewardStatus`, `GetPositionX`/`GetPositionY` - was
already being called from this file before #2801. That matters because the
compiler cannot be run on a PR.
"""
import pathlib
import re
import unittest

MODULE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "mod-overseer/src/mod_overseer.cpp"
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

    Searching the raw source is not a reachability test: a member named only in
    prose is not a member used.
    """
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _walks_before_the_leader_gate_are_leader_only(body: str) -> None:
    """The leader gate used to be the first thing before the ONLY slot walk.
    Module 89878284 (the leader serves the youngest) added a second walk in
    front of it: the leader looks over its own log for a quest the youngest
    still needs. That walk is leader-only by its own condition, so the
    property is unchanged: no follower ever walks its own log. Assert it
    directly rather than by string order."""
    gate = body.index("if (!isLead)")
    before = body[:gate]
    for m in re.finditer(r"MAX_QUEST_LOG_SIZE", before):
        head = before[max(0, m.start() - 600):m.start()]
        assert "isLead &&" in head, (
            "a slot walk before the leader gate is not itself leader-gated; "
            "every follower would free-roam its own log")
    assert "MAX_QUEST_LOG_SIZE" in body[gate:], (
        "the fallback slot walk must still sit behind the leader gate")


def _drive() -> str:
    # mod-overseer#552 split DriveQuests into a census and dispatch plus the
    # per-family body it always had. The drive these tests describe is both.
    return (_function("void DriveQuests()")
            + _function("void DriveFamilyQuests("))


def _aimstate() -> str:
    return _function("struct AimState")


class UpstreamsOwnGiveUpSetIsHonoured(unittest.TestCase):
    """The first and better half of the fix.

    mod-playerbots already maintains `lowPriorityQuest` (PlayerbotAI.h:605) and
    its OWN quest picker already skips it - NewRpgBaseAction.cpp:1149 and :1241
    both pass over a quest found in that set. `DriveQuests()` consulted
    nothing, so it was re-picking quests upstream had already written off two
    feet away. Honouring the existing set is smaller and better founded than
    any parallel bookkeeping of our own.
    """

    def test_the_slot_walk_consults_lowpriorityquest(self):
        body = _code(_drive())
        self.assertIn("lowPriorityQuest", body,
                      "upstream's picker skips these; ours must too, or we "
                      "hand back the quest it just rejected")

    def test_it_is_cited_against_the_pin(self):
        self.assertIn("PlayerbotAI.h:605", _drive(),
                      "a member the build cannot check on a PR has to be "
                      "cited where it is used")


class TheFailureIsRemembered(unittest.TestCase):
    """The second half: the gap `lowPriorityQuest` does not cover.

    Grug idles at NewRpgAction.cpp:580 - "can't find a poi pos to reward" -
    which does NOT insert into `lowPriorityQuest`. Upstream only records a
    give-up at :622, after sitting within ten yards of the reward POI for five
    minutes, and he never reaches Westfall to start that clock. So upstream's
    memory stays empty for exactly his failure and we need our own for it.

    The existing `AimState` is the right home: already per-name, already
    world-thread-only, already holds `lastWorking`.
    """

    def test_aimstate_records_the_quest_that_was_last_picked(self):
        self.assertIn("lastPicked", _aimstate(),
                      "AimState must remember which quest it last chose, or a "
                      "repeat pick is indistinguishable from a first one")

    def test_aimstate_counts_consecutive_failures(self):
        self.assertIn("strikes", _aimstate(),
                      "one idle-out is normal (combat, death, an objective "
                      "completing); a wedge is the SAME quest failing again "
                      "and again, so it has to be counted")

    def test_aimstate_holds_the_quests_it_has_given_up_on(self):
        state = _aimstate()
        self.assertIn("givenUp", state)
        self.assertRegex(state, r"(map|set)<uint32",
                         "the given-up quests are quest ids")


class AQuestThatJustFailedIsNotPickedAgain(unittest.TestCase):
    """Acceptance criterion 2, and the half that unwedges the leader."""

    def test_the_slot_walk_skips_a_given_up_quest(self):
        body = _code(_drive())
        self.assertRegex(
            body, r"givenUp\.(count|find)\(",
            "the fallback walk has to consult the given-up set, or it will "
            "pick quest 109 again on the very next poll")

    def test_a_repeat_pick_of_the_same_quest_is_detected(self):
        body = _code(_drive())
        self.assertIn("lastPicked", body,
                      "DriveQuests has to compare what it is about to pick "
                      "against what it picked last time")

    def test_the_strike_count_gates_the_give_up(self):
        body = _code(_drive())
        self.assertRegex(
            body, r"strikes\s*(\+\+|\+=|>=)",
            "strikes must be incremented and compared, so one ordinary "
            "idle-out does not condemn a healthy quest")

    def test_a_strike_requires_the_bot_to_have_NOT_MOVED(self):
        """The discriminator, and the reason a bare counter is wrong.

        The idle-out sites mean different things: NewRpgAction.cpp:580 is
        "cannot reach the reward POI" (Grug), but :444 is simply "the quest
        left the log" and is entirely healthy. Position separates them - a bot
        that gave up without trying has not moved, while one legitimately
        travelling has. Measured: a dev bot on a distant-but-reachable quest
        stayed quiet and covered ~150 yards in bursts over fourteen minutes,
        and must never be condemned for being slow.
        """
        body = _code(_drive())
        self.assertRegex(
            body, r"fromX|movedSincePick|GetPositionX",
            "a strike has to be gated on the bot not having moved since the "
            "quest was chosen, or slow-but-working quests get given up on")

    def test_there_is_a_named_threshold_rather_than_a_bare_number(self):
        src = _code(MODULE.read_text(encoding="utf-8"))
        self.assertRegex(
            src, r"constexpr\s+\w+\s+QUEST_REPICK_STRIKES\s*=",
            "the number of strikes is a policy decision and belongs at the "
            "top with QUEST_POLL_MS, not buried in the loop")


class GivingUpIsRecordedNotSilent(unittest.TestCase):
    """Acceptance criterion 3.

    The loop was only ever visible because #2787 gave `module.overseer` a
    working appender. A give-up that logs nothing would recreate exactly the
    condition that hid this bug for a day.
    """

    def test_the_give_up_is_logged(self):
        body = _code(_drive())
        gaveup = [ln for ln in body.splitlines() if "gave up" in ln.lower()]
        self.assertTrue(gaveup, "giving up on a quest must log a line")

    def test_the_give_up_line_names_the_quest_and_the_reason(self):
        body = _drive()
        idx = body.lower().index("gave up")
        window = body[idx - 200:idx + 400]
        self.assertIn("{}", window, "the log line has to interpolate the quest")
        self.assertRegex(
            window, r"(strike|without progress|never got|idled)",
            "a bare 'gave up' is not a named reason; say what was observed")

    def test_the_all_given_up_case_says_so_once(self):
        body = _code(_drive())
        self.assertRegex(
            body, r"(every|all).{0,60}(quest|log)",
            "Grug's whole backlog is cross-zone, so the case where EVERY "
            "eligible quest has been given up is his actual state and must "
            "not be a silent no-op")


class TheMemorySurvivesAnAimBeingReleased(unittest.TestCase):
    """The hole that would have silently defeated the whole fix.

    Both aim-release paths did `state = AimState()`, which wipes `givenUp`,
    `strikes` and `lastPicked` along with the aim bookkeeping. The BACKSTOP
    release fires precisely when an aim could not be landed - the unreachable
    case - and the fallback walk runs in the same iteration, so the quest just
    given up on was immediately eligible again. Resetting the aim must not
    reset the memory of what cannot be reached.
    """

    def test_no_release_path_wholesale_resets_the_state(self):
        body = _code(_drive())
        self.assertNotIn(
            "state = AimState();", body,
            "a wholesale reset takes givenUp/strikes/lastPicked with it; clear "
            "the aim fields explicitly instead")

    def test_the_aim_fields_are_cleared_individually(self):
        body = _code(_drive())
        self.assertRegex(body, r"state\.questId\s*=\s*0",
                         "the aim itself still has to be forgotten on release")


class TheStrikeWindowIsWiderThanTheFailurePathsOwnNudge(unittest.TestCase):
    """A wedged bot MOVES, which is why a tight threshold masks the wedge.

    When `MoveFarTo` fails, upstream does not stand still - it calls
    `MoveRandomNear(10.0f)` (NewRpgAction.cpp:342, :357, :513, :607) as a nudge
    so the next tick starts from a different spot. The AI ticks many times
    inside one twenty-second poll, so a random walk of several ten-yard steps
    routinely covers more than a dozen yards while going nowhere. A threshold
    at or near the nudge radius therefore resets the strike count on exactly
    the bot it is supposed to catch, and the feature becomes a silent no-op
    that looks like it is working.

    Generosity is nearly free here: the check's only job is to avoid striking a
    bot that is demonstrably travelling, and `!onQuest` already does most of
    that work - a bot crawling a long route stays IN RPG_DO_QUEST and can never
    accrue a strike at all.
    """

    def test_the_threshold_clears_the_ten_yard_nudge_by_a_margin(self):
        src = _code(MODULE.read_text(encoding="utf-8"))
        match = re.search(r"QUEST_PROGRESS_YARDS\s*=\s*([0-9.]+)f?;", src)
        self.assertIsNotNone(match, "QUEST_PROGRESS_YARDS must be a literal")
        yards = float(match.group(1) if match else 0)
        self.assertGreaterEqual(
            yards, 40.0,
            "MoveRandomNear(10.0f) is the failure path's own nudge; a random "
            "walk of those inside one poll will clear a small threshold")

    def test_the_nudge_is_cited_so_the_number_is_not_mistaken_for_arbitrary(self):
        src = MODULE.read_text(encoding="utf-8")
        self.assertRegex(src, r"MoveRandomNear|NewRpgAction\.cpp:342")

    def test_the_baseline_is_the_start_of_the_streak_not_the_last_poll(self):
        """Rewriting the origin every poll shrinks the window to twenty
        seconds, and drift wins over twenty seconds. Anchoring it to the start
        of the streak lets genuine directional travel separate itself from a
        bounded random walk over the full sixty."""
        body = _code(_drive())
        pick = body.index("repick.lastPicked = questId")
        window = body[pick - 400:pick + 400]
        self.assertRegex(
            window, r"if\s*\(\s*questId\s*!=\s*repick\.lastPicked\s*\)[\s\S]{0,400}fromX",
            "pickedX/pickedY must be set only when the chosen quest CHANGES")


class AnUntriedQuestIsPreferredImmediately(unittest.TestCase):
    """Acceptance criterion 2, which has no 'or' branch.

    "A quest that has just failed to progress is not re-picked immediately in
    preference to an untried one." Strikes alone do not satisfy that: they let
    the failed quest be handed back on the next poll, and the one after, before
    the cooldown blocks it. The strike count decides when to give up for
    fifteen minutes; it must not decide whether to try something else NOW.
    """

    def test_the_walk_can_defer_the_quest_that_just_failed(self):
        body = _code(_drive())
        self.assertRegex(
            body, r"(deferred|justFailed|fallbackQuest)",
            "the walk needs to hold back the quest that just failed and take "
            "an untried one first, using the failed one only if nothing else "
            "is eligible")

    def test_the_deferred_quest_is_status_checked_before_it_is_played(self):
        """The deferral `continue`s past the walk's own status check, so the
        retry path has to make it again. Without it the quest reaches
        ChangeToDoQuest validated only for template existence, and
        NewRpgDoQuestAction::Execute hits its `default:` and idles at once
        (NewRpgAction.cpp:444) - a burnt poll and a strike for a reason that is
        not the quest's real problem."""
        body = _code(_drive())
        retry = body.index("deferred)")
        window = body[retry:retry + 700]
        self.assertRegex(
            window, r"GetQuestStatus\(\s*deferred\s*\)",
            "the deferred quest must be re-checked for an actionable status")

    def test_the_failed_quest_is_still_used_when_it_is_the_only_option(self):
        """Never picking it at all would be worse than the bug: a leader with
        one quest would stop questing entirely."""
        body = _code(_drive())
        self.assertRegex(body, r"(deferred|fallbackQuest)\b[\s\S]{0,600}ChangeToDoQuest",
                         "the deferred quest is still played if nothing else is")


class TheStrikeOnlyCountsAgainstAQuestStillWorthStriking(unittest.TestCase):
    """A quest that has left the log is not a wedge.

    `lastPicked` is assessed before the slot walk, so a quest abandoned or
    turned in out from under us would otherwise take three strikes and be
    logged with a reason that is not true of it.
    """

    def test_the_strike_checks_the_quest_is_still_in_the_log(self):
        body = _code(_drive())
        # The strike itself is `++repick.strikes`; the preemption block that
        # module 89878284 put in front of it resets the counter but never
        # increments it, so the increment is what the status check must precede.
        strike = body.index("++repick.strikes")
        check = re.search(r"GetQuestStatus\(\s*repick\.lastPicked\s*\)", body)
        self.assertIsNotNone(
            check, "only strike a quest the bot still holds in an actionable state")
        self.assertLess(check.start(), strike,
                        "the status check has to come before the strike is counted")


class TheThresholdsAreSaneAndNotJustPresent(unittest.TestCase):
    """A constant that exists but is absurd passes a presence check.

    The earlier version of this file asserted only that the constexpr was
    there, which a value of 1000 would have satisfied while the wedge ran
    forever.
    """

    def test_the_strike_count_is_small_enough_to_notice_a_wedge_quickly(self):
        src = _code(MODULE.read_text(encoding="utf-8"))
        match = re.search(r"QUEST_REPICK_STRIKES\s*=\s*(\d+)", src)
        self.assertIsNotNone(match)
        strikes = int(match.group(1) if match else 0)
        self.assertGreaterEqual(strikes, 2, "one idle-out is ordinary churn")
        self.assertLessEqual(
            strikes, 4,
            "at a twenty-second poll, more than four strikes is more than a "
            "minute of a character doing nothing before anything is noticed")

    def test_the_cooldown_is_long_enough_to_stop_churn_and_short_enough_to_retry(self):
        src = _code(MODULE.read_text(encoding="utf-8"))
        match = re.search(r"QUEST_GIVE_UP_COOLDOWN_SECONDS\s*=\s*(\d+)", src)
        self.assertIsNotNone(match)
        seconds = int(match.group(1) if match else 0)
        self.assertGreaterEqual(seconds, 300)
        self.assertLessEqual(seconds, 3600)


class TheNestedTypeIsNotNamedUnqualified(unittest.TestCase):
    """This one actually broke the build on main, so it gets a test.

    `RepickMemory` is nested inside `AimState`. Writing `RepickMemory& repick`
    in a member function of the OUTER class does not compile - the unqualified
    name is not in scope - and clang says so only on `main`, because that is
    the only place this file is ever compiled:

        fatal error: unknown type name 'RepickMemory';
                     did you mean 'AimState::RepickMemory'?

    `auto&` is the robust form: it binds the same reference, needs no
    qualification, and survives the struct being moved or renamed.
    """

    def test_the_repick_reference_does_not_name_the_nested_type_unqualified(self):
        body = _code(_drive())
        self.assertNotRegex(
            body, r"(?<!::)\bRepickMemory&",
            "name it `auto&` or `AimState::RepickMemory&`; the bare nested "
            "name does not compile from the outer class")

    def test_the_reference_is_still_taken_by_reference_not_by_value(self):
        """A copy would silently drop every strike and give-up on return."""
        body = _code(_drive())
        self.assertRegex(body, r"auto&\s+repick\s*=\s*state\.repick",
                         "a by-value copy would discard the memory each poll")


class TheLogLineCannotBreakTheBuild(unittest.TestCase):
    """This file is only compiled on push to `main`.

    So the log line is written to the conventions the build has already
    proven, not to whatever fmt probably supports. The training log at the
    `spec_tab` site casts its uint8 before passing it; fmt renders an unsigned
    char as a CHARACTER in some configurations, and a PR cannot find that out.
    """

    def test_the_strike_count_is_cast_before_it_is_logged(self):
        body = _code(_drive())
        self.assertRegex(
            body, r"static_cast<uint32>\(\s*repick\.strikes\s*\)",
            "uint8 goes through static_cast<uint32> before fmt sees it, as "
            "the spec_tab log already does")

    def test_no_float_format_spec_was_introduced(self):
        """There was no precedent for one in this file before #2801."""
        body = _code(_drive())
        self.assertNotRegex(
            body, r"\{:\.\d+f\}",
            "positions are logged as cast integers; every other argument in "
            "this file is an integer or a string")


class TheGiveUpExpires(unittest.TestCase):
    """Giving up forever is its own bug.

    A quest unreachable from Elwynn is reachable from Goldshire; the world
    moves, the bot moves, and a permanent refusal would outlive its reason.
    """

    def test_the_given_up_set_has_a_cooldown(self):
        src = _code(MODULE.read_text(encoding="utf-8"))
        self.assertRegex(
            src, r"constexpr\s+\w+\s+QUEST_GIVE_UP_COOLDOWN\w*\s*=",
            "a give-up has to expire, or one bad poll condemns a quest for "
            "the lifetime of the process")

    def test_the_cooldown_is_actually_consulted(self):
        body = _code(_drive())
        self.assertIn("QUEST_GIVE_UP_COOLDOWN", body)


class NoNewUpstreamMemberWasIntroduced(unittest.TestCase):
    """The cheapest possible change against a compiler we cannot run.

    Every member this touches is one `DriveQuests()` already called before
    #2801, so the build has proven all of them. If this list ever grows, the
    new member has to be read at the pin and cited in place first.
    """

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
        # The one member #2801 adds. Upstream's own give-up set; its picker
        # skips it at NewRpgBaseAction.cpp:1149 and :1241.
        "lowPriorityQuest": "PlayerbotAI.h:605",
    }
    # Members the build has already proven by using them elsewhere in this file.
    ALREADY_PROVEN = {"Fetch", "NextRow", "Get", "GetTitle", "GetQuestTemplate",
                      "FindPlayerByName",
                      # the snapshot writer already reads these
                      "GetPositionX", "GetPositionY",
                      # module 89878284: the leader-serves-the-youngest log
                      # line names the youngest and its level. Both are used
                      # dozens of times elsewhere in this file (58 and 14
                      # call sites), so the build has long since proven them.
                      "GetName", "GetLevel"}

    def test_the_new_member_is_cited_where_it_is_used(self):
        self.assertIn("PlayerbotAI.h:605", _drive())

    def test_no_unverified_member_appears(self):
        body = _code(_drive())
        used = set(re.findall(r"->([A-Za-z_][A-Za-z0-9_]*)\(", body))
        unknown = used - set(self.VERIFIED) - self.ALREADY_PROVEN
        self.assertEqual(unknown, set(), "unverified members: %s" % sorted(unknown))

    def test_the_rpg_state_is_still_reached_only_through_verified_members(self):
        body = _code(_drive())
        used = set(re.findall(r"rpgInfo\.([A-Za-z_][A-Za-z0-9_]*)", body))
        unknown = used - set(self.VERIFIED)
        self.assertEqual(unknown, set(), "unverified rpgInfo members: %s" % sorted(unknown))


class NothingElseWasQuietlyChanged(unittest.TestCase):
    """The aim path is proven working (#2798/#2799) and is not in scope here."""

    def test_the_aim_is_still_preferred_over_the_fallback(self):
        body = _code(_drive())
        self.assertIn("DriveChosenQuest", body,
                      "the council's aim still outranks the bot's own log")

    def test_the_onquest_guard_survives(self):
        body = _code(_drive())
        self.assertRegex(
            body, r"if\s*\(onQuest(?:\s*&&\s*!preempted)?\)\s*\n?\s*continue;",
            "removing this reinstates the every-poll re-issue that #2798 and "
            "#2799 exist to prevent")

    def test_the_driver_is_still_on_the_quest_poll(self):
        src = _code(MODULE.read_text(encoding="utf-8"))
        self.assertRegex(src, r"_questTimer\s*>=\s*QUEST_POLL_MS")
        self.assertIn("DriveQuests();", src)


if __name__ == "__main__":
    unittest.main()


class TheWholeFamilyCanBeAimed(unittest.TestCase):
    """infra#2801 / "quest together": every member acts on its own aim.

    Handing a quest in is reachable ONLY through the rpg strategy -
    SearchQuestGiverAndAcceptOrReward is a NewRpgBaseAction method called only
    from NewRpgAction.cpp - so a follower without `new rpg` cannot turn a quest
    in even standing on the questgiver. That is why the four hoarded completed
    quests: they hold `+quest`, so they finish objectives, and the last step is
    structurally closed to them.

    Letting them quest means letting them carry `new rpg`, and `new rpg` at
    relevance 3.0-11.0 buries `follow` at 1.0. So cohesion can no longer come
    from following. It comes from the SHARED DESTINATION instead: quest sharing
    (#2793) already keeps their logs aligned - all five hold quest 109 and all
    five hold 1097 - and five characters sent to hand in the same quest walk to
    the same NPC. They converge because they want the same thing, not because
    they are leashed.

    The 937-yard scatter came from bots pursuing DIFFERENT objectives. An aim is
    what makes the objective common, so DriveQuests has to honour one for every
    member and not only for the leader.
    """

    def test_the_aim_query_is_not_restricted_to_the_leader(self):
        body = _code(_drive())
        self.assertNotRegex(
            body, r"WHERE enabled = 1 AND `lead` = 1",
            "a leader-only query means a follower's aim is written and never "
            "read - the same unread-column failure this epic started with")

    def test_every_enabled_member_is_considered(self):
        body = _code(_drive())
        self.assertRegex(body, r"WHERE enabled = 1",
                         "all enabled roster members, aimed or not")

    def test_the_leader_flag_is_still_selected_because_the_fallback_needs_it(self):
        """Only the leader may free-roam its own quest log. A follower without
        an aim must stay put: an unaimed follower carrying `new rpg` is exactly
        the 937-yard scatter, and the aim is the only thing holding the party
        to one destination."""
        body = _code(_drive())
        self.assertRegex(body, r"SELECT name, `lead`",
                         "the query has to bring back who leads")
        self.assertIn("isLead", body)

    def test_the_first_eligible_fallback_is_leader_only(self):
        """The guard has to sit BEFORE the walk, not merely somewhere in the
        function - order is the whole property."""
        body = _code(_drive())
        _walks_before_the_leader_gate_are_leader_only(body)


class AFollowerWithoutAnAimDoesNotRoam(unittest.TestCase):
    """The safety property that makes questing-together survivable.

    With `new rpg` on a follower, the ONLY thing keeping the party together is
    a live aim. If the supervisor cannot find a shared quest, the honest
    behaviour is to leave the follower alone rather than let it wander.
    """

    def test_an_unaimed_follower_reaches_no_movement_call(self):
        body = _code(_drive())
        self.assertRegex(
            body, r"if\s*\(\s*!\s*isLead\s*\)\s*\n?\s*continue;",
            "an unaimed non-leader has to fall out before the log walk")

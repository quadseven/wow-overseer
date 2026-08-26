"""The family could walk to a quest objective and nowhere else.

infra#2783. No trainer, no vendor, no repair, no bank, no guild-charter
petitioner, no tabard designer - and not because those NPCs were disallowed.
mod-playerbots' allowed-RPG-target list is one unconditional block containing
every one of them (PossibleRpgTargetsValue.cpp:23-46). The gap was that the
only public way into RPG_WANDER_NPC took no argument:

    void ChangeToDoQuest(uint32 questId, const Quest* quest);   // aimable
    void ChangeToWanderNpc();                                   // takes nothing

so the bot always chose its own NPC. One missing parameter blocked #2757,
#2829, #2830, #2831 and the `town run` / `train` modes of #2834 at once.

The C++ in this repo is only compiled on a push to `main`, never on a PR, and a
field name that did not exist once broke the build for three PRs' worth of work.
So the module and patch tests below are contract tests over the source text, in
the pattern test_quest_aim.py established. What they pin is the set of ways this
change could be shipped and still move nobody:

  * an aim that resolves a guid and hands it to MoveWorldObjectTo, which finds a
    creature only while its grid is loaded - so the bot shuffles in a circle;
  * an aim re-issued on every poll, which resets the travel state and produces a
    bot that oscillates instead of arriving (the #2799 failure);
  * an aim consumed by the eight-second stay-timer, so the errand undoes itself
    eight seconds after it succeeds;
  * an aim with no bound, pinning a character to a target it cannot reach;
  * an aim set on a character that does not carry `new rpg`, which no action
    will ever read;
  * a keyword this side accepts and the module silently ignores - written and
    unread, exactly #2776.

Pins (production/docker/azerothcore-playerbots/UPSTREAM-PINS.env):
    core   efe123fab543c5faf3c477674ec17a18fd59f09f
    module 8d9f6aa6bc6d45f9ae0ee0675b9b1f8aa6937312
Neither is vendored here. Every line number quoted was read from those two.
"""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
PATCH = (
    ROOT
    / "docker/azerothcore-playerbots/patches/mod-playerbots"
    / "0005-wander-npc-can-be-aimed.patch"
)
MIGRATION = (
    ROOT
    / "docker/azerothcore-playerbots/mod-overseer/data/sql/characters/base"
    / "2026_08_25_00_overseer_roster_travel_npc.sql"
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import travel  # noqa: E402


def _source() -> str:
    return MODULE.read_text(encoding="utf-8")


def _function(signature: str) -> str:
    """The whole of a member function, braces balanced."""
    src = _source()
    start = src.index(signature)
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("%s has no closing brace" % signature)


def _code(text: str) -> str:
    """The same text with // comments stripped.

    Searching the raw source is not a reachability test: the comments here
    quote upstream code this implementation deliberately does not call, and a
    member named only in prose is not a member used.
    """
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _drive() -> str:
    return _function("void DriveTravel()")


def _quests() -> str:
    return _function("void DriveQuests()")


def _wheel() -> str:
    return _function("bool TravelHoldsTheWheel(")


def _clear() -> str:
    return _function("void ClearTravelAim(")


def _resolve() -> str:
    return _function("bool ResolveTravelTarget(")


def _index() -> str:
    return _function("void BuildTravelIndex()")


def _aims() -> str:
    return _function("std::map<std::string, std::string> LoadTravelAims()")


def _patch() -> str:
    return PATCH.read_text(encoding="utf-8")


def _patch_added() -> str:
    """Only the lines the patch ADDS, without its prose header.

    The header argues at length about the code it is replacing, so searching
    the whole file would let a claim in the argument pass for an implementation.
    """
    return "\n".join(
        line[1:] for line in _patch().splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _cpp_roles() -> dict:
    """The module's own keyword -> NPC flag table."""
    body = _function("static std::vector<TravelRole> const& TravelRoles()")
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r'\{"([^"]+)",\s*(UNIT_NPC_FLAG_[A-Z_]+)\}', body)
    }


class TheVocabularyIsSharedBetweenPythonAndTheModule(unittest.TestCase):
    """A keyword one side accepts and the other ignores is #2776 again.

    There is no shared schema between a compiled worldserver module and a
    Python process, so the table genuinely exists twice. The only defence is to
    compare them, in both directions, on every test run.
    """

    def test_the_module_has_a_role_table_at_all(self):
        self.assertTrue(_cpp_roles(), "TravelRoles() parsed as empty")

    def test_every_python_keyword_is_one_the_module_accepts(self):
        missing = sorted(set(travel.ROLES) - set(_cpp_roles()))
        self.assertEqual([], missing,
                         "travel.py offers keywords mod_overseer.cpp will "
                         "ignore: %s" % missing)

    def test_every_module_keyword_is_one_python_can_produce(self):
        missing = sorted(set(_cpp_roles()) - set(travel.ROLES))
        self.assertEqual([], missing,
                         "mod_overseer.cpp accepts keywords nothing can "
                         "write: %s" % missing)

    def test_the_two_tables_agree_on_which_npc_flag_each_keyword_means(self):
        self.assertEqual(travel.ROLES, _cpp_roles())

    def test_every_alias_resolves_to_a_real_role(self):
        for alias, canonical in travel.ALIASES.items():
            self.assertIn(canonical, travel.ROLES, alias)

    def test_no_keyword_overflows_the_column(self):
        """VARCHAR(32). A keyword that does not fit is one the module can never
        read back, and a silently truncated row looks like a typo nobody made."""
        for keyword in travel.ROLES:
            self.assertLessEqual(len(keyword), travel.COLUMN_WIDTH, keyword)

    def test_the_epic_blocking_targets_are_all_reachable(self):
        """The specific NPCs the blocked issues need to stand in front of."""
        for keyword in ("profession trainer", "class trainer", "vendor",
                        "repair", "banker", "guild banker", "petitioner",
                        "tabard designer"):
            self.assertIn(keyword, travel.ROLES, keyword)


class TheTargetVocabulary(unittest.TestCase):
    def test_a_canonical_keyword_resolves_to_itself(self):
        self.assertEqual("profession trainer",
                         travel.resolve("profession trainer"))

    def test_case_and_spacing_do_not_matter(self):
        self.assertEqual("tabard designer",
                         travel.resolve("  Tabard   Designer "))

    def test_the_way_a_person_says_it_resolves(self):
        self.assertEqual("petitioner", travel.resolve("guild charter"))
        self.assertEqual("vendor", travel.resolve("merchant"))
        self.assertEqual("banker", travel.resolve("bank"))
        self.assertEqual("auctioneer", travel.resolve("AH"))

    def test_a_creature_entry_is_a_target(self):
        self.assertEqual("5511", travel.resolve("5511"))

    def test_entry_zero_is_refused(self):
        """0 is the worldserver's own sentinel for "no creature", so an aim at
        it would resolve to nothing and read as an aim that merely did not
        work."""
        self.assertIsNone(travel.resolve("0"))

    def test_nonsense_is_refused_rather_than_guessed(self):
        self.assertIsNone(travel.resolve("the moon"))
        self.assertIsNone(travel.resolve(""))
        self.assertIsNone(travel.resolve(None))

    def test_is_target_rejects_the_cleared_state(self):
        self.assertFalse(travel.is_target(travel.NONE))
        self.assertTrue(travel.is_target("vendor"))
        self.assertFalse(travel.is_target("merchant"),
                         "an alias is not what gets stored; resolve() first")

    def test_describe_says_it_out_loud(self):
        self.assertEqual("the nearest profession trainer",
                         travel.describe("professions"))
        self.assertEqual("creature 5511", travel.describe("5511"))
        self.assertEqual("nowhere", travel.describe(""))


class TheAimIsWrittenAndEveryoneElseIsCleared(unittest.TestCase):
    def test_the_chosen_are_aimed(self):
        stmts = travel.aim_statements(["Grug"], "profession trainer")
        self.assertIn("SET travel_npc", stmts[0][0])
        self.assertIn("profession trainer", stmts[0][1])
        self.assertIn("Grug", stmts[0][1])

    def test_everyone_else_is_cleared_in_the_same_pass(self):
        """A stale aim is a character sent to a trainer nobody asked about,
        days later, and a party that spreads while he goes."""
        stmts = travel.aim_statements(["Grug"], "vendor")
        self.assertEqual(2, len(stmts))
        self.assertIn("NOT IN", stmts[1][0])

    def test_an_empty_target_clears_everybody(self):
        stmts = travel.aim_statements(["Grug"], "")
        self.assertEqual(1, len(stmts))
        self.assertIn("travel_npc <> ", stmts[0][0])

    def test_naming_nobody_clears_everybody(self):
        stmts = travel.aim_statements([], "vendor")
        self.assertEqual(1, len(stmts))

    def test_an_unresolvable_target_raises_rather_than_writing_junk(self):
        with self.assertRaises(ValueError):
            travel.aim_statements(["Grug"], "the moon")

    def test_names_are_bound_and_never_interpolated(self):
        for sql, params in travel.aim_statements(["Grug", "Ugga"], "vendor"):
            self.assertNotIn("Grug", sql)
            self.assertIn("Grug", params)


class ThePatchExistsAndIsTheThingThatMakesAimingPossible(unittest.TestCase):
    """Without it, ChangeToWanderNpc takes no argument and none of this runs."""

    def test_the_patch_is_carried(self):
        self.assertTrue(PATCH.exists(), "patch 0005 is missing")

    def test_it_targets_the_pinned_module_and_says_so(self):
        self.assertIn("8d9f6aa6bc6d45f9ae0ee0675b9b1f8aa6937312", _patch())

    def test_it_adds_the_aimable_overload(self):
        self.assertIn("void ChangeToWanderNpc(uint32 npcEntry, WorldPosition pos)",
                      _patch_added())

    def test_the_overload_sets_the_status_clock(self):
        """`startT` is what HasStatusPersisted measures the five-minute lease
        against. Writing the variant without it leaves the lease measured from
        whenever the PREVIOUS status began."""
        added = _patch_added()
        self.assertIn("startT = getMSTime();", added)

    def test_the_aim_is_carried_as_an_entry_and_a_position(self):
        added = _patch_added()
        self.assertIn("uint32 npcEntry{0};", added)
        self.assertIn("WorldPosition pos{};", added)

    def test_the_long_walk_goes_through_movefarto_and_not_the_guid(self):
        """THE WHOLE POINT. MoveWorldObjectTo resolves the guid through
        ObjectAccessor (NewRpgBaseAction.cpp:205), which finds a creature only
        while its grid is loaded - so a guid-only aim moves a bot exactly as far
        as it can already see, then falls to MoveRandomNear(15.0f) and shuffles
        in a circle. Position pathing has no such requirement."""
        added = _code(_patch_added())
        self.assertIn("return MoveFarTo(data.pos);", added)

    def test_the_guid_is_resolved_only_on_arrival(self):
        added = _code(_patch_added())
        self.assertIn("FindNearestCreature(data.npcEntry", added)
        self.assertIn("data.npcOrGo = aimedNpc->GetGUID();", added)

    def test_an_unaimed_wander_is_untouched(self):
        """The block is skipped entirely when npcEntry is 0, which is every
        wander the bot chose for itself. A patch that changed those too would be
        a behaviour change to every bot on the realm, not a new verb."""
        self.assertIn("if (data.npcEntry && data.pos != WorldPosition())",
                      _code(_patch_added()))

    def test_the_patch_never_clears_the_entry(self):
        """The eight-second stay-timer clears `npcOrGo` so a wandering bot moves
        on. If it cleared `npcEntry` too, the errand would undo itself eight
        seconds after succeeding - and "the target is empty" would once again
        mean both "never aimed" and "arrived", which is the ambiguity that made
        #2799 hard."""
        added = _code(_patch_added())
        self.assertNotIn("npcEntry = 0", added)
        self.assertNotIn("npcEntry = ObjectGuid()", added)

    def test_it_says_out_loud_that_it_delivers_travel_and_not_transaction(self):
        """Upstream's only interaction on arrival is its quest-giver branch. A
        reader must not take "can reach a trainer" for "can train"."""
        self.assertIn("TRAVEL, NOT TRANSACTION", _patch())


class TheModuleActuallyReadsTheColumn(unittest.TestCase):
    """It was written by the bridge and read by nobody. That was #2776."""

    def test_the_query_selects_the_column(self):
        """The read moved into LoadTravelAims (infra#2846) so the quest drive
        could share it without sharing its failure. It is still a read of this
        column and DriveTravel still runs off it."""
        self.assertIn("travel_npc", _code(_aims()))
        self.assertIn("LoadTravelAims()", _code(_drive()))

    def test_only_enabled_characters_with_an_aim_are_considered(self):
        code = _code(_aims())
        self.assertIn("enabled = 1", code)
        self.assertIn("travel_npc <> ''", code)

    def test_the_world_loop_dispatches_it(self):
        """A DriveTravel nobody calls is a feature that exists only in the
        diff."""
        code = _code(_source())
        self.assertIn("DriveTravel();", code)
        self.assertIn("_travelTimer >= TRAVEL_POLL_MS", code)
        self.assertIn("_travelTimer += diff;", code)

    def test_the_poll_is_faster_than_the_lease_it_renews(self):
        """RPG_WANDER_NPC self-expires after FIVE minutes
        (statusWanderNpcDuration, NewRpgAction.h:65) - six times shorter than
        the thirty-minute quest lease. A poll slower than that means the
        traveller spends part of every five minutes wandering off alone."""
        poll = int(re.search(r"TRAVEL_POLL_MS = (\d+);", _source()).group(1))
        self.assertLess(poll, 5 * 60 * 1000)

    def test_it_aims_through_the_patched_overload(self):
        self.assertIn("ChangeToWanderNpc(entry, pos)", _code(_drive()))

    def test_it_does_not_reach_for_setmovefarto(self):
        """SetMoveFarTo only RECORDS a destination for stuck-tracking; the
        walking is done by NewRpgBaseAction::MoveFarTo in the action layer
        (NewRpgBaseAction.cpp:40-48). Setting it from here would store a
        destination nobody walks to."""
        self.assertNotIn("SetMoveFarTo", _code(_drive()))


class TheTargetIsResolvedWhereTheAnswerIsKnown(unittest.TestCase):
    def test_the_nearest_spawn_is_chosen_from_the_characters_own_position(self):
        code = _code(_resolve())
        self.assertIn("GetDistance2d", code)
        self.assertIn("bestDist", code)

    def test_only_the_map_the_character_is_standing_on(self):
        """MoveFarTo paths through PathGenerator and there is no navmesh across
        an ocean or into an instance - the same refusal patch 0003 keeps."""
        code = _code(_resolve())
        self.assertIn("bot->GetMapId()", code)
        self.assertIn("spawn.mapId != mapId", code)

    def test_a_bare_creature_entry_is_accepted_too(self):
        self.assertIn("wantedEntry", _code(_resolve()))

    def test_the_index_reads_members_the_pinned_trees_already_use(self):
        """A guessed member name costs the whole team a 45-minute compile on
        main to discover. Every one of these is read by mod-playerbots itself at
        the pin (TravelMgr.cpp:4648-4661)."""
        code = _code(_index())
        for member in ("data.id", "data.mapid", "data.posX", "data.posY",
                       "data.posZ", "GetAllCreatureData()",
                       "GetCreatureTemplate("):
            self.assertIn(member, code, member)

    def test_a_per_spawn_npcflag_override_wins_over_the_template(self):
        """`creature.npcflag` is a per-spawn override; 0 means "use the
        template". Reading only the template would index a spawn deliberately
        stripped of the flag and send somebody to it."""
        self.assertIn("data.npcflag ? data.npcflag : creatureTemplate->npcflag",
                      _code(_index()))

    def test_the_index_is_built_once_and_not_per_poll(self):
        """A quarter of a million spawns, on the world thread, to answer a
        question whose answer never changes."""
        code = _code(_index())
        self.assertIn("_travelIndexBuilt", code)


class TheEightSecondConsumeDidNotEatTheErrand(unittest.TestCase):
    """npcStayTime is 8s (NewRpgAction.h:99). After it, upstream clears the
    target and picks another NPC - which for an errand means wandering off eight
    seconds after arriving."""

    def test_the_aim_is_not_re_issued_while_the_bot_already_holds_it(self):
        """Case 1, and the one that breaks loudly. ChangeToWanderNpc rebuilds
        the variant, resetting `lastReach` and `startT`; doing that every poll
        gives a bot that oscillates instead of arriving - the failure MoveFarTo's
        own comment warns about and #2799 had to fix for the quest aim."""
        code = _code(_drive())
        self.assertIn("RPG_WANDER_NPC", code)
        self.assertIn("wander->npcEntry == entry", code)
        self.assertRegex(code, r"wander->npcEntry == entry\s*\)?\s*\n\s*continue;")

    def test_a_lapsed_lease_falls_through_to_a_fresh_aim(self):
        """Case 3. Once the five-minute lease expires the status is no longer
        RPG_WANDER_NPC, so the guard cannot match and the write happens."""
        code = _code(_drive())
        aim = code.index("ChangeToWanderNpc(entry, pos)")
        guard = code.index("GetStatus() == RPG_WANDER_NPC")
        self.assertLess(guard, aim, "the guard must precede the aim")


class TheErrandIsBounded(unittest.TestCase):
    def test_arriving_releases_it(self):
        code = _code(_drive())
        self.assertIn("TRAVEL_ARRIVED_YARDS", code)
        self.assertIn("ClearTravelAim(name)", code)

    def test_arrival_is_measured_by_distance_and_not_by_bot_state(self):
        """The bot's own state stops naming the target eight seconds after it
        gets there, so it cannot be asked "did you arrive". Distance can be, and
        it is what the errand actually means."""
        self.assertIn("GetDistance2d(pos.GetPositionX(), pos.GetPositionY())",
                      _code(_drive()))

    def test_an_unreachable_target_is_given_up_on(self):
        code = _code(_drive())
        self.assertIn("TRAVEL_BACKSTOP_SECONDS", code)

    def test_the_backstop_outlasts_more_than_one_rpg_lease(self):
        """An aim must never be released merely because the five-minute lease
        lapsed - that is what renewal is for."""
        seconds = re.search(r"TRAVEL_BACKSTOP_SECONDS = (\d+) \* 60;", _source())
        self.assertIsNotNone(seconds)
        self.assertGreater(int(seconds.group(1)) * 60, 2 * 5 * 60)

    def test_a_target_that_does_not_exist_here_releases_rather_than_pins(self):
        code = _code(_drive())
        # The call carries `wantSkill` since infra#2757, which narrows a
        # trainer role to trainers that can teach the skill being learned.
        # The behaviour this test is about is unchanged: a target that
        # resolves to nothing releases the errand instead of pinning it.
        self.assertIn("!ResolveTravelTarget(bot, target, entry, pos, wantSkill)", code)

    def test_the_clear_escapes_the_name(self):
        """The name came out of a table a person edits by hand."""
        self.assertIn("Esc(name)", _code(_function("void ClearTravelAim(")))


class AnAimNothingCanActOnIsSaidOutLoud(unittest.TestCase):
    """The one failure that looks exactly like success from outside: the column
    is set, the module read it, and nobody moves."""

    def test_a_character_without_new_rpg_is_reported_not_papered_over(self):
        """Only `new rpg` runs NewRpgWanderNpcAction - it owns the `wander npc
        status` trigger (NewRpgStrategy.cpp) - and the family deliberately carry
        it on the LEADER alone, because five characters free-roaming is the
        937-yard scatter. So a follower cannot be sent anywhere; it arrives by
        following."""
        self.assertIn("CanBeSentToNpc(botAI)", _code(_drive()))
        self.assertIn('HasStrategy("new rpg", BOT_STATE_NON_COMBAT)',
                      _code(_function("bool CanBeSentToNpc(")))

    def test_it_logs_rather_than_silently_skipping(self):
        drive = _drive()
        self.assertIn("does not carry `new rpg`", drive)

    def test_every_release_path_says_why(self):
        """Four ways an errand ends - arrival, no such spawn, the backstop, and
        a character that cannot act - and an operator has to tell them apart
        from the log alone."""
        drive = _drive()
        for phrase in ("errand done", "no such spawn", "as unreachable",
                       "does not carry"):
            self.assertIn(phrase, drive, phrase)


class TheTwoDriversDoNotFightOverTheWheel(unittest.TestCase):
    """PR #2840 review, P1. DriveQuests re-issues ChangeToDoQuest every 20s and
    DriveTravel re-issues ChangeToWanderNpc every 15s. With a travel errand on a
    character that also carries a quest aim - which the dev roster has, on Junmu
    - the rpg status flips every poll, each flip resets the other errand's
    movement state, and the bot goes nowhere while looking busy.

    Travel wins while an errand is outstanding: it is bounded (it releases on
    arrival, and at worst after TRAVEL_BACKSTOP_SECONDS), while a quest aim is
    renewed by the bridge and its fallback picks from the log forever - so
    "quest wins" starves travel without limit AND releases the untried errand
    with a false diagnosis ("never arrived"), which is the one thing this epic
    is not allowed to do.

    Three moments, all pinned here: the errand outstanding, the errand ending,
    and no errand at all."""

    def test_the_quest_drive_can_see_the_travel_aims(self):
        """Through the shared loader, NOT through its own SELECT. Selecting the
        column here is what infra#2846 was: a `travel_npc` the schema does not
        have nulled the quest query and stopped the family questing entirely,
        for a feature it has nothing to do with."""
        quests = _code(_quests())
        self.assertIn("LoadTravelAims()", quests)
        self.assertIn("travelTarget", quests)
        self.assertNotIn("travel_npc", quests)

    def test_the_decision_has_exactly_one_home(self):
        """Two functions each checking the other is how the NEXT oscillation
        gets built. DriveTravel knows nothing about quests; DriveQuests asks one
        predicate and obeys it."""
        travel = _code(_drive())
        self.assertNotIn("drive_quest", travel)
        self.assertNotIn("DriveChosenQuest", travel)
        self.assertNotIn("ChangeToDoQuest", travel)
        self.assertNotIn("TravelHoldsTheWheel", travel)
        quests = _code(_quests())
        self.assertNotIn("ChangeToWanderNpc", quests)
        self.assertEqual(1, quests.count("TravelHoldsTheWheel("))

    def test_the_quest_drive_stands_down_before_it_can_aim_anything(self):
        """Moment 1. The stand-down has to precede EVERY path that writes a
        quest state - the chosen-quest path and the own-log fallback alike."""
        quests = _code(_quests())
        wheel = quests.index("TravelHoldsTheWheel(")
        self.assertLess(wheel, quests.index("DriveChosenQuest("))
        self.assertLess(wheel, quests.index("ChangeToDoQuest("))
        self.assertIn("continue;", quests[wheel:wheel + 900])

    def test_standing_down_is_logged_once_per_transition_not_once_per_poll(self):
        quests = _quests()
        self.assertIn("state.travelHeld", _code(quests))
        self.assertIn("stands down", quests)

    def test_the_quest_backstop_does_not_run_while_the_quest_drive_is_stood_down(self):
        """Otherwise the arbitration re-creates the very bug P2 fixes: a quest
        aim held through a long errand would be released as unreachable on the
        first poll after the hand-back, without a step having been walked for
        it."""
        self.assertIn("state.since += ", _code(_quests()))

    def test_the_hand_back_cannot_land_in_the_same_tick_the_errand_ends(self):
        """Moment 2, and the one nobody thinks to ask about. DriveQuests runs
        before DriveTravel inside one OnUpdate, so without a grace the tick that
        releases the errand is followed immediately by a ChangeToDoQuest that
        stomps the wander state the bot is still standing in (upstream needs
        npcStayTime = 8s at the NPC to count it as arrived). A one-tick
        oscillation is the steady-state bug in miniature - it happens once and
        stops, which makes it harder to find, not better."""
        self.assertRegex(_source(), r"TRAVEL_HANDBACK_SECONDS = \d+")
        self.assertIn("TRAVEL_HANDBACK_SECONDS", _code(_wheel()))
        self.assertIn("_travelHandback", _code(_clear()))

    def test_the_grace_outlasts_a_whole_quest_poll_and_the_arrival_dwell(self):
        seconds = int(re.search(r"TRAVEL_HANDBACK_SECONDS = (\d+)",
                                _source()).group(1))
        poll = int(re.search(r"QUEST_POLL_MS = (\d+)", _source()).group(1))
        self.assertGreater(seconds, poll // 1000 + 8)

    def test_the_grace_expires_rather_than_holding_the_wheel_forever(self):
        """A refusal that outlives its reason is its own bug - the give-up set
        in the repick memory is swept for exactly this reason (infra#2801)."""
        self.assertIn("_travelHandback.erase(", _code(_wheel()))

    def test_with_no_errand_the_quest_drive_is_unchanged_and_unaware(self):
        """Moment 3. An empty column and no recent release means the predicate
        is false and DriveQuests behaves exactly as it did before."""
        code = _code(_wheel())
        self.assertIn("travelTarget.empty()", code)
        self.assertIn("return false;", code)

    def test_an_errand_nothing_can_act_on_does_not_freeze_the_questing(self):
        """A follower's row is left set by design when it does not carry `new
        rpg`. Travel is NOT driving that character, so the quest drive must not
        stand down for it - that would take an unaimable follower out of the
        family's questing until somebody noticed the column."""
        self.assertIn("CanBeSentToNpc(botAI)", _code(_wheel()))


class TheErrandStateIsNotOutlivedByItsClock(unittest.TestCase):
    """PR #2840 review, P2. _travelState.since is the 20-minute backstop clock.
    Left behind on a release, a LATER errand at the same target inherits it and
    is released as unreachable on its first poll, having walked nowhere."""

    def test_releasing_an_errand_erases_its_state(self):
        self.assertIn("_travelState.erase(name)", _code(_clear()))

    def test_every_release_path_goes_through_the_one_that_erases(self):
        """Three releases inside DriveTravel - arrival, no such spawn, the
        backstop - and none of them may erase, or forget to erase, on its own."""
        code = _code(_drive())
        self.assertEqual(3, code.count("ClearTravelAim(name)"))
        self.assertNotIn("_travelState.erase(name)", code)

    def test_a_row_cleared_bridge_side_mid_walk_is_noticed(self):
        """The bridge clears the column itself when it re-aims the family. That
        row simply stops coming back from the query, so nothing inside the loop
        can see it go."""
        code = _code(_drive())
        self.assertEqual(2, code.count("PruneTravelState("))
        prune = _code(_function("void PruneTravelState("))
        self.assertIn("_travelState.erase(", prune)
        self.assertIn("_travelHandback", prune)


class TheResolvedSpawnIsPinnedForTheLifeOfTheErrand(unittest.TestCase):
    """PR #2840 review, minor. Re-picking the nearest same-role spawn from where
    the bot NOW stands can hand back a different spawn mid-walk, which re-issues
    the aim, resets the five-minute lease, and prints "sent to" again."""

    def test_the_spawn_is_remembered_on_the_errand(self):
        self.assertIn("state.pinned", _code(_drive()))

    def test_the_pin_is_dropped_when_the_target_changes(self):
        code = _code(_drive())
        reset = code.index("state.target = target")
        self.assertIn("state.pinned = false", code[reset:reset + 400])

    def test_a_pinned_errand_does_not_resolve_again(self):
        code = _code(_drive())
        self.assertLess(code.index("state.pinned"),
                        code.index("!ResolveTravelTarget(bot, target, entry, pos, wantSkill)"))


class TheMigrationMatchesWhatTheModuleReads(unittest.TestCase):
    def test_the_migration_exists(self):
        self.assertTrue(MIGRATION.exists())

    def test_it_adds_the_column_the_module_selects(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN `travel_npc`", sql)

    def test_the_width_matches_the_python_side(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("VARCHAR(%d)" % travel.COLUMN_WIDTH, sql)

    def test_the_cleared_state_is_a_sentinel_and_not_null(self):
        """Every other column on this table uses a sentinel: the module reads
        these with Field::Get and a nullable column would put a NULL check in
        front of every read for no gain."""
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("NOT NULL DEFAULT ''", sql)
        self.assertEqual(travel.NONE, "")

    def test_it_alters_rather_than_recreating_the_table(self):
        """overseer_roster already holds live rows; a CREATE TABLE here would
        take the family off the roster.

        Comments stripped first: the prose above the statement argues about
        CREATE TABLE at length, and an argument is not a statement."""
        sql = "\n".join(
            line for line in MIGRATION.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("--")
        )
        self.assertIn("ALTER TABLE", sql)
        self.assertNotIn("CREATE TABLE", sql)
        self.assertNotIn("DROP TABLE", sql)


if __name__ == "__main__":
    unittest.main()

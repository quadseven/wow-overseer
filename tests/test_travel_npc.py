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

Pins (production/UPSTREAM-PINS.env):
    core   efe123fab543c5faf3c477674ec17a18fd59f09f
    module 8d9f6aa6bc6d45f9ae0ee0675b9b1f8aa6937312
Neither is vendored here. Every line number quoted was read from those two.
"""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "mod-overseer/src/mod_overseer.cpp"
DECISIONS = ROOT / "mod-overseer/src/overseer_decisions.cpp"
PATCH = (
    ROOT
    / "patches/mod-playerbots"
    / "0005-wander-npc-can-be-aimed.patch"
)
PINS = ROOT / "UPSTREAM-PINS.env"
MIGRATION = (
    ROOT
    / "mod-overseer/data/sql/characters/base"
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
    """The one release path. It used to be a free ClearTravelAim(); it is
    TravelAimBook::Release now, on the book that also owns the errand memory
    and the hand-back clock (mod_overseer.cpp, `class TravelAimBook`)."""
    return _function("void Release(std::string const& name)")


def _book() -> str:
    """The whole TravelAimBook class, so a test can see what is private."""
    return _function("class TravelAimBook")


def _prune() -> str:
    return _function("void PruneVanished(std::set<std::string> const& stillAimed)")


def _end_travel_poll() -> str:
    return _function("void EndTravelPoll(std::set<std::string> const& stillAimed)")


def _grace() -> str:
    return _function("bool WithinHandbackGrace(std::string const& name)")


def _ratchet() -> str:
    """The backstop's rule, which four drives now share instead of each
    carrying a copy (OverseerDecisions::Ratchet, overseer_decisions.cpp)."""
    src = DECISIONS.read_text(encoding="utf-8")
    out = []
    for signature in ("bool RatchetProgressed(", "RatchetVerdict Ratchet("):
        start = src.index(signature)
        depth = 0
        for i in range(src.index("{", start), len(src)):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append(src[start:i + 1])
                    break
    return "\n".join(out)


def _resolve() -> str:
    return _function("bool ResolveTravelTarget(")


def _index() -> str:
    return _function("void BuildTravelIndex()")


def _aims() -> str:
    """The travel column's one reader, TravelAimBook::Load (reached from the
    drives as `_travelAims.Load()`). It was a free LoadTravelAims() until
    the book gathered the read, the release and the memory together."""
    return _function("std::map<std::string, std::string> Load() const")


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
        """Read the pin rather than repeat it. This assertion used to carry a
        literal SHA, which meant every module bump failed here for the one
        reason that is not a defect - the pin moved and the patch header moved
        with it. What is worth pinning is that the header names the CURRENT
        module pin, which is what the test is called."""
        pinned = re.search(
            r"^AC_MODULE_SHA=([0-9a-f]{40})$",
            PINS.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        self.assertIsNotNone(pinned, "no AC_MODULE_SHA in UPSTREAM-PINS.env")
        self.assertIn(pinned.group(1), _patch())

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
        """The read moved into one loader (infra#2846) so the quest drive
        could share it without sharing its failure, and that loader now lives
        on TravelAimBook. It is still a read of this column and DriveTravel
        still runs off it."""
        self.assertIn("travel_npc", _code(_aims()))
        self.assertIn("_travelAims.Load()", _code(_drive()))

    def test_only_enabled_characters_with_an_aim_are_considered(self):
        code = _code(_aims())
        self.assertIn("enabled = 1", code)
        self.assertIn("travel_npc <> ''", code)

    def test_the_world_loop_dispatches_it(self):
        """A DriveTravel nobody calls is a feature that exists only in the
        diff."""
        code = _code(_source())
        self.assertIn("DriveTravel();", code)
        # The threshold is a local since mod-overseer#122: the drive polls at
        # the dungeon coordinator's cadence only while a run is escorting, and
        # at TRAVEL_POLL_MS - exactly as before - whenever it is not.
        self.assertIn("_travelTimer >= travelPoll", code)
        self.assertRegex(
            code, r"travelPoll =\s*_dungeonEscorts\.empty\(\) \? TRAVEL_POLL_MS")
        self.assertIn("_travelTimer += diff;", code)

    def test_the_poll_is_faster_than_the_lease_it_renews(self):
        """RPG_WANDER_NPC self-expires after FIVE minutes
        (statusWanderNpcDuration, NewRpgAction.h:65) - six times shorter than
        the thirty-minute quest lease. A poll slower than that means the
        traveller spends part of every five minutes wandering off alone."""
        poll = int(re.search(r"TRAVEL_POLL_MS = (\d+);", _source()).group(1))
        self.assertLess(poll, 5 * 60 * 1000)

    def test_it_aims_through_the_patched_overload(self):
        """The two-argument overload is patch 0012's; what matters is that the
        module reaches it. The second argument stopped being the raw `pos` in
        mod-overseer#138: a place aim is now walked to through GroundedStep,
        which hands back a terrain-checked step, because a raw point with no
        reachable navmesh polygon is splined to in a straight line and walks
        the character off whatever is in between. So this pins the call and
        the fact that a place aim is grounded first, not the variable name.

        And it now keeps that promise. It used to say "not the variable
        name" and then assert the variable name, so mod-overseer#316 broke it
        by doing exactly what the docstring said was allowed: the second
        argument became a ROUTE LEG, a nearer waypoint chosen so the greedy
        step chooser can walk round terrain instead of into it, falling back
        to the errand's own destination when no route is planned. That is a
        better second argument, not a violation.

        What must stay true is the invariant, so that is what is asserted:
        whatever gets walked to is GROUNDED first, and it ORIGINATES from the
        errand's own destination rather than from somewhere unrelated. A raw
        point with no reachable navmesh polygon is splined to in a straight
        line and walks the character off whatever is in between, and a
        grounded point that came from somewhere else would walk it safely to
        the wrong place."""
        code = _code(_drive())
        self.assertRegex(code, r"ChangeToWanderNpc\(entry, \w+\)")
        self.assertIn("ChangeToWanderNpc(entry, aimAt)", code)
        grounded = re.search(r"GroundedStep\(bot, (\w+), aimAt\)", code)
        self.assertIsNotNone(
            grounded, "a place aim must be grounded before it is walked to")
        walked = grounded.group(1)
        # No regex here on purpose: the point is that the grounded position is
        # ASSIGNED FROM the errand destination, and a line carrying all three
        # of the name, an assignment and `pos` is the whole of that claim.
        origin = [line for line in code.splitlines()
                  if walked in line and "=" in line and "pos" in line]
        self.assertTrue(
            origin,
            "what is grounded must originate from the errand destination")

    def test_it_does_not_reach_for_setmovefarto(self):
        """SetMoveFarTo only RECORDS a destination for stuck-tracking; the
        walking is done by NewRpgBaseAction::MoveFarTo in the action layer
        (NewRpgBaseAction.cpp:40-48). Setting it from here would store a
        destination nobody walks to."""
        self.assertNotIn("SetMoveFarTo", _code(_drive()))


class TheTargetIsResolvedWhereTheAnswerIsKnown(unittest.TestCase):
    def test_the_choice_is_made_from_the_characters_own_position(self):
        """NEAREST IS NO LONGER THE RULE, and that is mod-overseer#250.

        Choosing by distance alone aimed an Alliance family at Zargh, a
        Horde vendor 15 yards from two level 40 Horde Guards, who would
        never trade with them. It produced 180 refused sales in an
        afternoon, the deaths on the way there, and the graveyard loop
        that followed. The distance is still measured from the character's
        own position, which is what this test was originally protecting,
        but it is now one input to ChooseTravelTarget rather than the
        whole decision.
        """
        code = _code(_resolve())
        self.assertIn("GetDistance2d", code)
        self.assertIn("ChooseTravelTarget(candidates)", code)
        self.assertIn("candidate.mayInteract", code)
        self.assertNotIn("bestDist", code)

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
        # A position aim (`at:`, `trigger:`) has no entry to match on, so the
        # held aim also has to be at the same place before the poll stands
        # down (mod-overseer#121). For a creature aim `samePlace` is simply
        # true and the guard is what it always was.
        self.assertIn("bool const samePlace = entry ||", code)
        # mod-overseer#293 gave the guard its missing third input. Removing a
        # strategy does not touch rpgInfo, so a character that had `new rpg`
        # taken off it by the goal supervisor still READ as walking to exactly
        # this destination, and the guard continued past the only code that
        # could hand the walk back. One character stood still for nineteen
        # minutes that way. So "already walking there" now also asks whether
        # the character can act on the walk at all: it cannot have one in
        # flight if it cannot act, whatever its own state says.
        self.assertIn("atSameDestination = wander->npcEntry == entry && samePlace", code)
        self.assertRegex(
            code,
            r"WalkAlreadyInFlight\([^;]*?atSameDestination[^;]*?\)\s*\)?\s*\n\s*continue;")

    def test_a_lapsed_lease_falls_through_to_a_fresh_aim(self):
        """Case 3. Once the five-minute lease expires the status is no longer
        RPG_WANDER_NPC, so the guard cannot match and the write happens."""
        code = _code(_drive())
        aim = code.index("ChangeToWanderNpc(entry, aimAt)")
        guard = code.index("GetStatus() == RPG_WANDER_NPC")
        self.assertLess(guard, aim, "the guard must precede the aim")


class TheErrandIsBounded(unittest.TestCase):
    def test_arriving_releases_it(self):
        code = _code(_drive())
        self.assertIn("TRAVEL_ARRIVED_YARDS", code)
        self.assertIn("_travelAims.Release(name)", code)

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

    def test_the_backstop_is_restarted_by_getting_nearer(self):
        """The backstop is there to catch a character STANDING STILL, and it
        used to approximate that as "twenty minutes have passed". Those come
        apart on any long walk: measured on wow-dev, a character aimed at the
        Deadmines portal from Elwynn walked 2347 of 2933 yards and was released
        586 yards out, about five minutes from arriving, with the log calling it
        unreachable while it was visibly reaching it."""
        # The rule itself now lives in OverseerDecisions::Ratchet, which the
        # drive feeds the distance, the clock and TRAVEL_RATCHET - the bundle
        # of TRAVEL_PROGRESS_YARDS and TRAVEL_BACKSTOP_SECONDS. So the test
        # follows the rule to where it is: the drive has to call it with the
        # travel limits, the limits have to carry the yardage, and beating the
        # mark has to restart the clock.
        code = _code(_drive())
        self.assertRegex(code, r"OverseerDecisions::Ratchet\(\s*state\.progress,"
                               r"\s*distance,\s*std::time\(nullptr\),\s*limits\)")
        self.assertRegex(_code(_source()),
                         r"RatchetLimits TRAVEL_RATCHET\{\s*"
                         r"OverseerDecisions::RatchetReading::DistanceToTarget,\s*"
                         r"TRAVEL_PROGRESS_YARDS, TRAVEL_BACKSTOP_SECONDS\}")
        ratchet = _code(_ratchet())
        progressed = ratchet.index("if (verdict.progressed)")
        self.assertIn("state.since = now;", ratchet[progressed:progressed + 200])

    def test_progress_is_measured_against_the_best_ever_not_the_last_poll(self):
        """What makes a small threshold safe. `closest` only ratchets DOWNWARD,
        so beating it means getting nearer than the character has ever been on
        this errand - which a bot circling or jammed against scenery cannot keep
        doing, and a walking bot does every poll. Against the previous poll
        instead, a bot shuffling back and forth would renew the clock forever
        and the backstop would never fire."""
        ratchet = _code(_ratchet())
        # DistanceToTarget: nearer than the best ever, by the margin.
        #
        # `!seen` rather than `!best` since mod-overseer#191. The guarantee this
        # test protects is unchanged and the change strengthens it: zero is a
        # REAL reading, because WorldObject::GetDistance2d clamps arrival-range
        # distances to zero, so a traveller standing on its target used to look
        # "never measured" on every poll and restart the patience clock forever.
        # An explicit seen bit separates "no reading yet" from "a reading of
        # zero", which `!best` could not.
        self.assertIn("return !seen || reading < best - limits.margin;", ratchet)
        # ...and `best` only moves when that is true, so it ratchets downward.
        progressed = ratchet.index("if (verdict.progressed)")
        best = ratchet.index("state.best =")
        self.assertGreater(best, progressed)
        self.assertLess(best, ratchet.index("return verdict;"))

    def test_an_unreachable_target_is_still_released_eventually(self):
        """The progress check must not become a way to never give up. The clock
        still runs from the last improvement, so a character that closes to
        whatever range it can manage and then stops is released on the same
        twenty minutes it always was."""
        ratchet = _code(_ratchet())
        self.assertIn("now - state.since > limits.patienceSeconds", ratchet)
        code = _code(_drive())
        stalled = code.index("if (progress.stalled)")
        self.assertIn("_travelAims.Release(name)", code[stalled:stalled + 600])

    def test_the_best_distance_is_forgotten_when_the_errand_changes(self):
        """A closest approach carried into the NEXT errand is a clock that never
        starts: the new target is further away than the old best, so nothing
        ever beats it and the character is released on its first poll having
        walked nowhere. Same lesson as `since` in PR #2840's review."""
        code = _code(_drive())
        reset = code.index("state.target = target")
        # The window is generous on purpose: this block gains a line whenever
        # the errand grows a new piece of per-errand state, and a window sized
        # to today's block turns every such addition into a failure about
        # something else. mod-overseer#293 added two and broke it at 600.
        self.assertIn("state.progress.best = 0.f", code[reset:reset + 1400])

    def test_a_target_that_does_not_exist_here_releases_rather_than_pins(self):
        code = _code(_drive())
        # The call carries `wantSkill` since infra#2757, which narrows a
        # trainer role to trainers that can teach the skill being learned,
        # and `&said` since mod-overseer#250, which lets the resolver name
        # what it turned down when the only vendor in reach is one this
        # character cannot trade with. The behaviour this test is about is
        # unchanged: a target that resolves to nothing releases the errand
        # instead of pinning it.
        self.assertIn("!ResolveTravelTarget(bot, target, entry, pos, wantSkill, &said)", code)

    def test_the_clear_escapes_the_name(self):
        """The name came out of a table a person edits by hand."""
        self.assertIn("Esc(name)", _code(_clear()))


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
        self.assertIn("_travelAims.Load()", quests)
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
        # The clock is the book's now: the predicate asks it, the release
        # stamps it, and the constant is compared inside it.
        self.assertIn("_travelAims.WithinHandbackGrace(name)", _code(_wheel()))
        self.assertIn("TRAVEL_HANDBACK_SECONDS", _code(_grace()))
        self.assertIn("_handback[name] = std::time(nullptr);", _code(_clear()))

    def test_the_grace_outlasts_a_whole_quest_poll_and_the_arrival_dwell(self):
        seconds = int(re.search(r"TRAVEL_HANDBACK_SECONDS = (\d+)",
                                _source()).group(1))
        poll = int(re.search(r"QUEST_POLL_MS = (\d+)", _source()).group(1))
        self.assertGreater(seconds, poll // 1000 + 8)

    def test_the_grace_expires_rather_than_holding_the_wheel_forever(self):
        """A refusal that outlives its reason is its own bug - the give-up set
        in the repick memory is swept for exactly this reason (infra#2801)."""
        self.assertIn("_handback.erase(it)", _code(_grace()))

    def test_with_no_errand_the_quest_drive_is_unchanged_and_unaware(self):
        """Moment 3. An empty column and no recent release means the predicate
        is false and DriveQuests behaves exactly as it did before."""
        code = _code(_wheel())
        self.assertIn("travelTarget.empty()", code)
        self.assertIn("return _travelAims.WithinHandbackGrace(name);", code)
        self.assertRegex(_code(_grace()),
                         r"if \(it == _handback\.end\(\)\)\s*\n\s*return false;")

    def test_an_errand_nothing_can_act_on_does_not_freeze_the_questing(self):
        """A follower's row is left set by design when it does not carry `new
        rpg`. Travel is NOT driving that character, so the quest drive must not
        stand down for it - that would take an unaimable follower out of the
        family's questing until somebody noticed the column."""
        self.assertIn("CanBeSentToNpc(botAI)", _code(_wheel()))


class TheErrandStateIsNotOutlivedByItsClock(unittest.TestCase):
    """PR #2840 review, P2. The errand's `progress.since` is the 20-minute
    backstop clock. Left behind on a release, a LATER errand at the same target
    inherits it and is released as unreachable on its first poll, having walked
    nowhere."""

    def test_releasing_an_errand_erases_its_state(self):
        self.assertIn("_state.erase(name)", _code(_clear()))

    def test_every_release_path_goes_through_the_one_that_erases(self):
        """Ten releases inside DriveTravel - arrival, no such spawn, the
        backstop, stepping through a doorway, the death-rate breaker's two, and
        mod-overseer#388's flight-discovery pair - and none of them may erase,
        or forget to erase, on its own.

        The ninth and tenth are #388's deliberate flight-discovery errand
        (`flight master:<nodeId>`), and they are two for the same reason the
        breaker above is two rather than one: they answer different questions.
        The ninth fires once the hold-and-learn transaction is resolved,
        whether or not the node was actually learned - a deliberate errand
        that reached its flight master and tried is done either way, and
        `LearnFlightNodeDeliberately`'s own log line already said which. The
        tenth is #402's rule applied here: the spawn this errand was sent to
        is gone (despawned, dead, or phased) by the time the character
        arrives, so nothing is left to learn from and the aim is handed back
        to whatever wrote it rather than held open forever.

        The doorway release is why the count is a census rather than a
        constant: a `trigger:` aim ends by GOING somewhere, not by standing
        somewhere, so it releases on a different line from arrival even though
        both are successes. Raise this number only when a genuinely new release
        exists, and name it here - the assertion below is the one that actually
        protects the invariant, and it is why the count may move at all.

        The two newest are mod-overseer#272's breaker, and they are two rather
        than one for a reason worth keeping: the first calls an errand off
        because it has killed its traveller, and the second clears the column
        AGAIN on a later poll because something outside this module writes it
        too and has re-armed a called-off errand within five minutes. A single
        release could not do both, because the second one has to keep happening
        while the first must not repeat its own log line.

        The seventh is mod-overseer#300, the route gate. It is a release and
        not a refusal-in-place because a walk this character cannot survive
        has no shorter version: the destination gate can pick a farther safe
        candidate, but once every candidate is behind lethal ground there is
        nothing left to aim at, so the errand ends rather than waits. It is
        also the one release that can fire before the character has taken a
        single step.

        The eighth is mod-overseer#312, the footing refusal's own bound. It
        is a release rather than a wait because the thing it gives up on is
        not a moment of bad luck: the character has been refused every
        bearing toward its aim on eight consecutive polls without moving a
        yard, which is what standing at the foot of a mountain with the
        destination behind it looks like from inside a greedy step chooser.
        Waiting cannot fix terrain. It is also the release that had to exist
        before the ratchet above could bind at all, because the ratchet is
        anchored to a target and a catch-up walk rewrites its target every
        poll with the leader's live position, so the twenty-minute clock was
        restarted before it could ever run out. This one is anchored to a
        PLACE, which is why it fires."""
        code = _code(_drive())
        self.assertEqual(11, code.count("_travelAims.Release(name)"))
        self.assertNotIn("_state.erase(", code)
        # Stronger than "the drive does not erase": it cannot. The memory is a
        # private member of the book, so the only way out is Release.
        book = _code(_book())
        self.assertLess(book.index("private:"),
                        book.index("std::map<std::string, TravelState> _state;"))

    def test_a_row_cleared_bridge_side_mid_walk_is_noticed(self):
        """The bridge clears the column itself when it re-aims the family. That
        row simply stops coming back from the query, so nothing inside the loop
        can see it go."""
        code = _code(_drive())
        # #166 put both of DriveTravel's ways out behind a single verb, so the
        # count that protects "every exit prunes" now counts the verb. What the
        # verb does is asserted immediately below, so the indirection cannot
        # hide a prune that went missing.
        self.assertEqual(2, code.count("EndTravelPoll("))
        end = _code(_end_travel_poll())
        self.assertIn("_travelAims.PruneVanished(stillAimed)", end)
        self.assertIn("SweepTravelFocus(stillAimed)", end)
        prune = _code(_prune())
        self.assertIn("_state.erase(", prune)
        self.assertIn("_handback[", prune)


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
                        code.index("!ResolveTravelTarget(bot, target, entry, pos, wantSkill, &said)"))


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

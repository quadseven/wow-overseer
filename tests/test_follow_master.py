"""`follow` was on all five and had never moved anybody (infra#2818).

Not because the strategy is broken. Because `follow` resolves through a
formation, every formation resolves through the MASTER, and the family has no
master and cannot acquire one.

    FormationValue's default is ChaosFormation (Formations.cpp:506-507).
    ChaosFormation is a MoveAheadFormation and does not override
    GetTargetName, so it inherits the base's `return ""` (Formations.h:23) -
    which sends FollowAction::Execute down the location branch
    (FollowActions.cpp:218). That branch calls formation->GetLocation(), which
    opens `Player* master = GetMaster(); if (!ValidateTargetContext(master,
    bot)) return Formation::NullLocation;` (Formations.cpp:50-54, and again in
    ChaosFormation::GetLocationInternal at Formations.cpp:140-143). A null
    master is a null location and Execute returns false
    (FollowActions.cpp:219-220).

Upstream would assign one. UpdateAIGroupMaster() runs unconditionally from
UpdateAI every tick (PlayerbotAI.cpp:397) and rechecks the master at
PlayerbotAI.cpp:437 - but it only ever assigns what FindNewMaster() hands back,
and FindNewMaster returns the group leader only when the leader is not a bot or
is a selfbot (PlayerbotAI.cpp:4420), a member on the same test
(PlayerbotAI.cpp:4431), and otherwise nullptr (PlayerbotAI.cpp:4450). Five bots,
none of them a selfbot while nobody is logged in, so it returns nullptr, and
`if (newMaster)` at PlayerbotAI.cpp:440 assigns nothing and clears nothing.

That same nullptr is what makes the fix hold: an explicitly set master is
rechecked every tick and left alone every tick.

THE OBSERVER EFFECT. With SelfBotLevel = 3, a human logging in as the leader IS
a selfbot, IsSelfBot(groupLeader) goes true, every follower is handed him and
given `+follow` on the spot (PlayerbotAI.cpp:440-448). Every in-game check
passed for exactly as long as somebody was watching. Nothing asserted below may
depend on anyone being logged in.

The C++ in this repo is only compiled on push to `main`, never on a PR, so
these are contract tests over the source text, in the pattern
test_quest_aim.py and test_quest_share.py established: they assert the shape of
the change and that every module member it touches was read out of the pinned
headers and cited in place.

Pins (production/UPSTREAM-PINS.env):
    core   efe123fab543c5faf3c477674ec17a18fd59f09f
    module 8d9f6aa6bc6d45f9ae0ee0675b9b1f8aa6937312
Neither is vendored here. Every line number above and below was read from those
two trees at those SHAs.
"""
import pathlib
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

    Searching the raw source is not a reachability test: the comments here
    quote upstream code this implementation deliberately does not call, and a
    member named only in prose is not a member used.
    """
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _following() -> str:
    return _function("void KeepRosterFollowing(")


def _grouped() -> str:
    return _function("void KeepRosterGrouped()")


class SomebodyIsActuallyAssignedAMaster(unittest.TestCase):
    """The whole bug in one sentence: nothing ever called SetMaster."""

    def test_the_pass_exists(self):
        self.assertIn("void KeepRosterFollowing(", MODULE.read_text(encoding="utf-8"))

    def test_it_sets_a_master(self):
        """SetMaster is public - PlayerbotAI.h:571, inside the `public:` block
        opened at PlayerbotAI.h:386 - so the module may call it without any
        patch to the pinned tree."""
        self.assertIn("SetMaster(", _code(_following()))

    def test_the_master_is_the_party_leader_the_group_actually_has(self):
        """Not present.front(), which is the roster's preferred leader and is
        not necessarily the leader the group is currently under: leadership
        drifts when a character logs out and KeepRosterGrouped corrects it
        afterwards. Following anyone but the real leader splits the party in
        two."""
        body = _code(_following())
        self.assertIn("GetLeaderGUID()", body)
        self.assertIn("ObjectAccessor::FindPlayer(", body)

    def test_it_runs_from_the_poll_that_already_holds_the_group(self):
        self.assertIn("KeepRosterFollowing(", _code(_grouped()))

    def test_it_runs_after_leadership_has_been_corrected(self):
        """ChangeLeader is called in the same pass. Handing out a master before
        that lands means a poll's worth of the family following the character
        that is about to stop being leader."""
        body = _code(_grouped())
        self.assertLess(
            body.index("ChangeLeader("), body.index("KeepRosterFollowing("),
            "the follow pass runs before the leadership correction, so it can "
            "hand out a master that is about to be replaced",
        )


class AHumanAtTheKeyboardWins(unittest.TestCase):
    """The observer effect cuts both ways. When a person logs in,
    RandomPlayerbotMgr::OnPlayerLogin sweeps every bot grouped with them and
    takes the master away from a bot to give it to the arrival
    (RandomPlayerbotMgr.cpp:2582-2586). These five are in that map, because
    KeepRosterOnline logs them in through sRandomPlayerbotMgr.AddPlayerBot.

    A poll that reasserts the bot leader unconditionally would take it straight
    back off the person playing, every thirty seconds, forever."""

    def test_a_client_driven_master_is_left_alone(self):
        """The guard is IsRealPlayer on the follower's master (null-safe,
        PlayerbotAI.cpp:4394). It used to be HasGameClientMaster(), which is
        `IsRealPlayer(master) || IsSelfBot(master)`; since module 3e1e85f7 the
        leader IS a selfbot (its own master, so it can issue the dungeon-clear
        command), and that wider test would have skipped every follower whose
        master is the leader. Only a real person at the keyboard wins now."""
        self.assertIn("IsRealPlayer(botAI->GetMaster())", _code(_following()))

    def test_a_character_with_no_bot_ai_is_skipped(self):
        """A person seated at one of these characters has no PlayerbotAI at
        all, and there is nothing to set."""
        body = _code(_following())
        self.assertIn("GET_PLAYERBOT_AI(", body)
        self.assertIn("continue;", body)

    def test_an_already_correct_master_is_not_rewritten(self):
        """Not for tidiness: it keeps the log line meaningful. A pass that
        reassigns every thirty seconds says "now follows" forever and stops
        being evidence of anything."""
        self.assertIn("GetMaster()", _code(_following()))


class TheLeaderFollowsNobody(unittest.TestCase):
    """RandomPlayerbotMgr::OnPlayerLogin will give the LEADER a master too if a
    grouped character logs in while his own master is null or a bot
    (RandomPlayerbotMgr.cpp:2582-2586). A leader following one of his own
    followers is a cohesion loop with no fixed point - the party converges on
    nothing and drifts as a clump."""

    def test_the_leader_is_its_own_master(self):
        """Its own master, not nobody. Module 3e1e85f7: the dungeon module only
        accepts a command from a member that passes the core's IsSelfBot,
        which is `GetMaster() == player`, and a cleared master failed that
        test on every poll, so the dungeon brain never armed. A leader whose
        master is itself follows nobody, which keeps the fixed point this
        class is about, and can issue the command."""
        body = _code(_following())
        self.assertIn("leaderAI->SetMaster(leader)", body)
        self.assertIn("IsSelfBot(leader)", body)
        self.assertNotIn("SetMaster(nullptr)", body)


class AMasterNobodyWalksTowardIsNotCohesion(unittest.TestCase):
    """The half-a-fix trap, and the routine trigger for it.

    Upstream treats "set the master" and "add +follow" as ONE act: its own
    assignment does `botAI->SetMaster(newMaster)` at PlayerbotAI.cpp:443 and
    `botAI->ChangeStrategy("+follow", BOT_STATE_NON_COMBAT)` at
    PlayerbotAI.cpp:448. Nothing adds the strategy on the path where the MODULE
    sets the master, so a module that only sets the master has done half of an
    atomic thing.

    The routine trigger: every time the person playing the leader logs out,
    RandomPlayerbotMgr::OnPlayerLogout clears the followers' master
    (RandomPlayerbotMgr.cpp:2515) and calls ResetStrategies on each of them
    (RandomPlayerbotMgr.cpp:2518). That is the precise moment this feature
    exists to cover, so whatever it leaves behind has to be assumed, not hoped
    for.

    What it actually leaves behind - verified, because the answer is the
    difference between a nuisance and a re-run of the 937-yard scatter:

      * `follow` SURVIVES. ResetStrategies rebuilds from AiFactory
        (PlayerbotAI.cpp:1872-1874) and `follow` is in the default non-combat
        set for every non-battleground bot (AiFactory.cpp:584).
      * `new rpg` does NOT come back. It is added only for a bot that is
        ungrouped or is the group leader (AiFactory.cpp:602), behind an
        IsRandomBot gate (AiFactory.cpp:591). A grouped follower passes
        neither.

    So the strategy is not expected to go missing - which is exactly why the
    module must not ASSUME it. If it ever does go missing, the alternative is a
    master assigned to a bot that will not walk toward it, under a log line
    reading "now follows"."""

    def test_the_follow_strategy_is_granted_not_assumed(self):
        body = _code(_following())
        self.assertIn('HasStrategy("follow", BOT_STATE_NON_COMBAT)', body)
        self.assertIn('ChangeStrategy("+follow", BOT_STATE_NON_COMBAT)', body)

    def test_the_strategy_is_checked_even_when_the_master_is_already_right(self):
        """The silently-inert case is a CORRECT master with no follow strategy.
        Gate the check behind the assignment and it can never be seen: the log
        said "now follows" once, months ago, and looked fine ever after."""
        body = _code(_following())
        assign = body.index("SetMaster(leader)")
        check = body.index('HasStrategy("follow"')
        self.assertLess(assign, check)
        # ...and the check must not be nested inside the assignment branch.
        between = body[assign:check]
        self.assertIn("}", between,
                      "the follow check sits inside the `master is wrong` branch, "
                      "so a correct master with no follow strategy is never noticed")

    def test_a_missing_strategy_is_reported_distinguishably(self):
        """Not the same line as a healthy assignment. `follow` is an AiFactory
        default, so its absence is a fact about the world worth seeing, not a
        detail to paper over."""
        body = _code(_following())
        grant = body.index('ChangeStrategy("+follow"')
        warn = body.rindex("LOG_WARN", 0, grant)
        self.assertIn("no follow strategy", body[warn:grant])

    def test_the_module_never_resets_strategies(self):
        """A reset would discard every other strategy the bridge has applied and
        rebuild from class defaults. Only the master was missing."""
        self.assertNotIn("ResetStrategies", _code(MODULE.read_text(encoding="utf-8")))

    def test_a_character_a_human_is_driving_is_left_entirely_alone(self):
        """Master AND strategies. The client-master guard has to come before
        both, or the poll starts editing the strategies of a character somebody
        is playing."""
        body = _code(_following())
        guard = body.index("IsRealPlayer(botAI->GetMaster())")
        self.assertLess(
            guard, body.index("botAI->SetMaster(leader)"),
            "the poll assigns a master before checking whether a human owns this "
            "character",
        )
        self.assertLess(
            guard, body.index('HasStrategy("follow"'),
            "the poll edits strategies before checking whether a human owns this "
            "character",
        )


class NoDanglingMaster(unittest.TestCase):
    """`master` is a raw Player*. Held across a logout it is a use-after-free
    on the very next FollowAction tick, which dereferences it
    (FollowActions.cpp:104).

    It is not one here, and the reason is upstream, not this module:
    WorldSession::LogoutPlayer calls OnPlayerbotLogout for any player
    (WorldSession.cpp:721 - ahead of the `redirecting` guard that gates the
    other logout hook at WorldSession.cpp:850-857), which reaches
    RandomPlayerbotMgr::OnPlayerLogout (Playerbots.cpp:457), which clears the
    master of every bot in its PlayerBotMap that pointed at the departing
    player (RandomPlayerbotMgr.cpp:2509-2515).

    These five are in that map: AddPlayerBot with masterAccountId 0 routes the
    login callback to RandomPlayerbotMgr::instance()
    (PlayerbotMgr.cpp:186), OnBotLoginOperation resolves the same holder
    (PlayerbotOperations.h:499) and OnBotLogin inserts them
    (PlayerbotMgr.cpp:468). Bot logouts take the same road: LogoutPlayerBot
    calls botWorldSessionPtr->LogoutPlayer(true) (PlayerbotMgr.cpp:408).

    So this module must NOT keep a Player* of its own between polls - the
    guarantee above covers PlayerbotAI::master and nothing else."""

    def test_no_player_pointer_is_stored_across_polls(self):
        """A cached master would outlive the guarantee that clears the real
        one."""
        src = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("Player* _", src)
        self.assertNotIn("std::vector<Player*> _", src)

    def test_the_reasoning_is_written_down_next_to_the_call(self):
        """This is the one claim a reader cannot re-derive from the module, and
        the one whose failure mode is a crashed worldserver rather than a wrong
        answer. It has to be cited where the SetMaster lives, not in a PR."""
        prose = MODULE.read_text(encoding="utf-8")
        head = prose.index("Give the followers somebody to follow")
        tail = prose.index("void KeepRosterFollowing(")
        block = prose[head:tail]
        self.assertIn("RandomPlayerbotMgr.cpp:2509-2515", block)
        self.assertIn("WorldSession.cpp:721", block)


class ItIsScopedToTheRoster(unittest.TestCase):
    """500 random bots share this world and none of them is ours."""

    def test_only_roster_characters_are_touched(self):
        body = _code(_following())
        self.assertTrue(
            "present" in body or "OnRoster(" in body,
            "the pass must iterate the roster, not the whole group or the world",
        )


if __name__ == "__main__":
    unittest.main()

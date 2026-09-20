"""Pace and turn for the guild recruit sweep (infra#3651).

WHAT THESE TESTS ARE PROTECTING, because it is not "the planner returns the
right verb". It is that a sweep which does nothing SAYS WHY. infra#3651's
whole complaint about the manual path is that a quiet day and a broken loop
are indistinguishable from the outside, so every wait below asserts on the
reason as well as on the verb.

AND THAT THE JUDGEMENT STAYS IN THE MODULE. Nothing here scores a candidate,
compares two of them, or reorders a shortlist. Who is worth asking is
mod-overseer's `RecruitVerdictFor` against the guild's real holes; this file
decides only whether it is this name's turn and whether it is too soon. If
somebody later adds a sort by level, or by gear, or by class, the shape of
these tests is what should make it look out of place.
"""
import ast
import pathlib
import unittest

import recruit

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
DOCKERFILE = (
    pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"
)

# The family, as the planner sees them: names that are online and in the guild.
ACTORS = ["Grug", "Ugga"]


def plan(**kw):
    """A sweep with nothing in its way, overridden one field at a time."""
    base = dict(
        actors=list(ACTORS),
        shortlist=["Cogwin", "Sprout", "Mirelle"],
        shortlist_age_minutes=1.0,
        shortlist_asked_minutes_ago=1.0,
        asked=set(),
        minutes_since_last_invite=None,
        member_count=5,
        target_size=40,
    )
    base.update(kw)
    return recruit.plan_recruit(**base)


class ASweepWithNothingInItsWayInvites(unittest.TestCase):

    def test_the_top_of_the_shortlist_is_asked(self):
        action = plan()
        self.assertEqual(action.verb, "invite")
        self.assertEqual(action.target_arg, "Cogwin")

    def test_the_name_goes_in_target_arg_because_that_is_what_the_module_reads(self):
        """DoGuild's invite branch refuses an empty target_arg outright.

        This is the bug that made every Python-issued invite impossible: the
        2026_09_11 guild migration reserves `target_arg` for exactly this and
        `_insert_guild` could not write it, so an invite row would have come
        back 'no character to invite (put the name in target_arg)'.
        """
        self.assertTrue(plan().target_arg)

    def test_the_command_carries_the_name_too(self):
        """So the command log reads as a sentence, and so infra#3650's own
        `command LIKE 'invite %'` query matches as that issue wrote it.

        ParseGuildRequest ignores what follows the verb on purpose, so saying
        it twice is not a contradiction.
        """
        self.assertEqual(plan().command, "invite Cogwin")

    def test_the_actor_is_one_of_the_online_guild_members(self):
        self.assertIn(plan().actor, ACTORS)

    def test_the_actor_is_stable_across_identical_passes(self):
        """Two passes over the same world pick the same carrier. Nothing here
        can tell two online members apart, so the tie is broken the one way
        that makes a re-run give the same answer - the same admission
        RecruitShortlist makes about its own name ordering."""
        self.assertEqual(plan().actor, plan(actors=list(reversed(ACTORS))).actor)


class EveryRefusalSaysWhichOneItWas(unittest.TestCase):

    def test_nobody_online_is_not_the_same_as_nobody_to_recruit(self):
        action = plan(actors=[])
        self.assertEqual(action.verb, "wait")
        self.assertIn("online", action.reason)

    def test_a_full_roster_says_so_with_the_numbers(self):
        action = plan(member_count=40, target_size=40)
        self.assertEqual(action.verb, "wait")
        self.assertIn("40", action.reason)

    def test_an_empty_shortlist_is_named_as_a_policy_question(self):
        """The failure infra#3744 spent a day on looked exactly like this, and
        the loop must not present it as its own fault."""
        action = plan(shortlist=[])
        self.assertEqual(action.verb, "wait")
        self.assertIn("nobody", action.reason)

    def test_too_soon_says_how_long_ago_and_how_long_is_required(self):
        action = plan(minutes_since_last_invite=1.0)
        self.assertEqual(action.verb, "wait")
        self.assertIn("invite", action.reason)

    def test_a_shortlist_of_names_already_asked_says_that_and_not_nobody(self):
        action = plan(asked={"Cogwin", "Sprout", "Mirelle"})
        self.assertEqual(action.verb, "wait")
        self.assertIn("already asked", action.reason)

    def test_every_outcome_carries_a_reason(self):
        for action in (
            plan(),
            plan(actors=[]),
            plan(member_count=40),
            plan(shortlist=[]),
            plan(shortlist_age_minutes=None),
            plan(minutes_since_last_invite=0.0),
            plan(asked={"Cogwin", "Sprout", "Mirelle"}),
        ):
            self.assertTrue(action.reason, action)


class WhenAFreshShortlistIsAskedFor(unittest.TestCase):

    def test_a_world_that_has_never_been_shortlisted_asks_for_one(self):
        action = plan(shortlist_age_minutes=None, shortlist_asked_minutes_ago=None)
        self.assertEqual(action.verb, "shortlist")
        self.assertEqual(action.command, f"shortlist {recruit.SHORTLIST_SIZE}")

    def test_a_stale_shortlist_is_re_asked_rather_than_acted_on(self):
        """A candidate on an old list may have joined another guild, levelled
        out of the band or been deleted; an invite drawn from it comes back
        refused for a reason that looks like a fault in this loop."""
        action = plan(
            shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES + 1,
            shortlist_asked_minutes_ago=recruit.SHORTLIST_FRESH_MINUTES + 1,
        )
        self.assertEqual(action.verb, "shortlist")

    def test_a_shortlist_inside_the_window_is_used(self):
        self.assertEqual(
            plan(shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES - 1).verb,
            "invite",
        )

    def test_a_shortlist_is_never_asked_for_while_a_FRESH_roster_is_full(self):
        """Half of the gate order is still the design, and this is the half.

        A full guild whose numbers are CURRENT has no question to ask the
        world, and a sweep that shortlisted anyway would keep asking for names
        it can never use. infra#4215 moved freshness above roster-full; it did
        not remove roster-full, and this is what says so. Written with an
        explicitly fresh shortlist, because the same assertion against a stale
        one would pass for the opposite reason.
        """
        action = plan(
            member_count=40,
            target_size=40,
            shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES - 1,
            shortlist_asked_minutes_ago=recruit.SHORTLIST_WAIT_MINUTES + 1,
        )
        self.assertEqual(action.verb, "wait")
        self.assertIn("target size", action.reason)


class AShortlistNobodyAnswersIsNotReAskedEveryPass(unittest.TestCase):
    """The unbounded-loop shape this project keeps being burned by.

    A shortlist row that never reaches 'delivered' - worldserver down, mid
    rollout, or every row coming back 'error' - reads to the planner as "there
    has never been a shortlist". Without backpressure it writes a fresh one
    every pass for as long as the fault lasts, each row individually
    reasonable. The guild-bank pass answers the same hazard the same way.
    """

    def test_a_question_still_in_flight_is_waited_on_and_not_repeated(self):
        action = plan(
            shortlist_age_minutes=None,
            shortlist_asked_minutes_ago=recruit.SHORTLIST_WAIT_MINUTES - 1,
        )
        self.assertEqual(action.verb, "wait")
        self.assertIn("not come back", action.reason)

    def test_a_question_that_has_been_ignored_long_enough_is_asked_again(self):
        self.assertEqual(
            plan(
                shortlist_age_minutes=None,
                shortlist_asked_minutes_ago=recruit.SHORTLIST_WAIT_MINUTES,
            ).verb,
            "shortlist",
        )

    def test_backpressure_never_blocks_an_invite(self):
        """It gates only the ASK. A usable delivered shortlist is still acted
        on while a newer request is in flight, or a stuck worldserver would
        also stop recruiting from a list that is perfectly good."""
        self.assertEqual(
            plan(shortlist_age_minutes=1.0, shortlist_asked_minutes_ago=0.0).verb,
            "invite",
        )

    def test_the_stale_path_is_gated_too_and_not_only_the_never_asked_one(self):
        self.assertEqual(
            plan(
                shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES + 1,
                shortlist_asked_minutes_ago=0.0,
            ).verb,
            "wait",
        )


class AStaleRosterCountCannotSuppressTheRefreshThatWouldDisproveIt(unittest.TestCase):
    """infra#4215, and the self-sealing gate it measured on wow-dev.

    BOTH ROSTER NUMBERS RIDE IN ON THE SHORTLIST. `roster_from_shortlist`
    lifts `member_count` and `target_size` off the newest delivered one,
    because the target is worldserver configuration this process does not
    hold. So while roster-full was asked FIRST, a cached "40 of 40" returned
    before the freshness check that would have asked for the shortlist
    carrying the new number - the only thing that could have refreshed it.
    Raising `Overseer.Recruit.TargetSize` to 71 therefore changed nothing: the
    loop logged "the roster is at its target size (40 of 40)" every five
    minutes for forty-five minutes and issued no rows at all.

    The fix is an ordering, not a deletion, so these tests come in pairs: the
    stale case must refresh AND the fresh case must still refuse. A suite that
    only asserted the first half would go green if somebody deleted the
    roster-full gate outright, which is the failure this class is shaped to
    make impossible.
    """

    def test_a_stale_full_roster_asks_for_a_fresh_shortlist(self):
        """The reported bug, exactly: cached 40 of 40, nothing in flight."""
        action = plan(
            member_count=40,
            target_size=40,
            shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES + 1,
            shortlist_asked_minutes_ago=recruit.SHORTLIST_WAIT_MINUTES + 1,
        )
        self.assertEqual(action.verb, "shortlist")
        self.assertEqual(action.command, f"shortlist {recruit.SHORTLIST_SIZE}")

    def test_a_stale_roster_over_its_cached_target_refreshes_too(self):
        """Not only the `==` case. A target LOWERED under the live roster is
        the same cache with the sign flipped, and it must not wedge either."""
        self.assertEqual(
            plan(
                member_count=71,
                target_size=40,
                shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES + 1,
                shortlist_asked_minutes_ago=recruit.SHORTLIST_WAIT_MINUTES + 1,
            ).verb,
            "shortlist",
        )

    def test_a_FRESH_full_roster_still_waits_and_still_says_roster_full(self):
        """THE NEGATIVE CASE, and the reason this fix is not just a deletion.

        A guild that really is at its target, on numbers minutes old, has no
        question for the world. Break the fix by removing the roster-full gate
        and this test fails: the verb becomes `invite`, not `wait`.
        """
        action = plan(
            member_count=71,
            target_size=71,
            shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES - 1,
            shortlist_asked_minutes_ago=recruit.SHORTLIST_WAIT_MINUTES + 1,
        )
        self.assertEqual(action.verb, "wait")
        self.assertIn("71 of 71", action.reason)
        self.assertEqual(action.target_arg, "")
        self.assertEqual(action.command, "")

    def test_the_line_between_the_two_is_the_published_constant(self):
        """Asserted against SHORTLIST_FRESH_MINUTES rather than against 30, so
        moving the constant moves the behaviour instead of breaking this."""
        full = dict(
            member_count=71,
            target_size=71,
            shortlist_asked_minutes_ago=recruit.SHORTLIST_WAIT_MINUTES + 1,
        )
        self.assertEqual(
            plan(shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES, **full).verb,
            "wait",
        )
        self.assertEqual(
            plan(shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES + 0.1, **full).verb,
            "shortlist",
        )

    def test_backpressure_still_holds_over_a_stale_full_roster(self):
        """The refresh is now reachable from roster-full, which means the
        unbounded-ask hazard is reachable from it too. A shortlist already
        asked for and not yet back must still hold, or a full guild with a
        stuck worldserver writes a row every pass for as long as the fault
        lasts - the exact shape infra#3650 was written about."""
        action = plan(
            member_count=40,
            target_size=40,
            shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES + 1,
            shortlist_asked_minutes_ago=0.0,
        )
        self.assertEqual(action.verb, "wait")
        self.assertIn("not come back", action.reason)

    def test_a_raised_target_on_a_fresh_shortlist_actually_recruits(self):
        """The end the whole issue is about: once the refresh lands and says
        40 of 71, the sweep invites instead of reporting itself full."""
        action = plan(member_count=40, target_size=71, shortlist_age_minutes=1.0)
        self.assertEqual(action.verb, "invite")
        self.assertEqual(action.target_arg, "Cogwin")

    def test_the_full_roster_reason_says_how_old_its_numbers_are(self):
        """infra#4215's log line was true about its own cache and useless
        about the world: "40 of 40" read identically at one minute and at four
        hours, and forty-five minutes of it told nobody anything. The age is
        in the reason now, and the reason is what gets logged."""
        action = plan(member_count=40, target_size=40, shortlist_age_minutes=3.0)
        self.assertEqual(action.verb, "wait")
        self.assertIn("3 minutes old", action.reason)

    def test_nobody_online_still_outranks_everything(self):
        """The first gate did not move. A pass with no carrier writes nothing,
        including no shortlist, however stale the numbers are."""
        action = plan(
            actors=[],
            member_count=40,
            target_size=40,
            shortlist_age_minutes=recruit.SHORTLIST_FRESH_MINUTES + 1,
            shortlist_asked_minutes_ago=recruit.SHORTLIST_WAIT_MINUTES + 1,
        )
        self.assertEqual(action.verb, "wait")
        self.assertIn("online", action.reason)


class AlreadyAskedIsSkippedAndNotBlocked(unittest.TestCase):

    def test_the_next_unasked_name_is_taken(self):
        self.assertEqual(plan(asked={"Cogwin"}).target_arg, "Sprout")

    def test_several_asked_names_are_walked_past(self):
        self.assertEqual(plan(asked={"Cogwin", "Sprout"}).target_arg, "Mirelle")

    def test_the_shortlist_order_is_not_re_sorted(self):
        """The module ranked these by which hole each one closes. Reordering
        them here would replace a rule that reads the guild's real gaps with
        one that does not."""
        self.assertEqual(plan(shortlist=["Zed", "Abe"]).target_arg, "Zed")


class TheRateLimitIsAboutInvitesAndNotAboutPasses(unittest.TestCase):

    def test_a_first_ever_invite_is_not_held_back(self):
        self.assertEqual(plan(minutes_since_last_invite=None).verb, "invite")

    def test_the_gap_is_the_published_constant(self):
        self.assertEqual(
            plan(minutes_since_last_invite=recruit.MIN_MINUTES_BETWEEN_INVITES).verb,
            "invite",
        )
        self.assertEqual(
            plan(minutes_since_last_invite=recruit.MIN_MINUTES_BETWEEN_INVITES - 0.1).verb,
            "wait",
        )

    def test_a_held_back_pass_does_not_also_spend_the_shortlist(self):
        """Asked before the pick, so the same top name is still there next
        pass rather than having been walked past by a pass that wrote
        nothing."""
        self.assertEqual(plan(minutes_since_last_invite=0.0).target_arg, "")

    def test_the_rate_reaches_a_forty_man_roster_inside_an_evening(self):
        """The argument against infra#3650's one-a-day, asserted rather than
        left in prose: 35 seats at this gap is a few hours, at one a day it is
        over a month."""
        seats = 40 - 5
        hours = seats * recruit.MIN_MINUTES_BETWEEN_INVITES / 60.0
        self.assertLess(hours, 12)


class ANoSizeGateIsTrustedRatherThanSecondGuessed(unittest.TestCase):

    def test_a_target_size_of_zero_never_reads_as_full(self):
        """0 means the worldserver was configured with no size gate. Inventing
        a ceiling here would be a second place deciding when the roster is
        full, and the two would disagree the day one of them changed."""
        self.assertEqual(plan(member_count=999, target_size=0).verb, "invite")


class AResultThisLoopCannotReadMeansNoCandidates(unittest.TestCase):
    """Not a traceback. The JSON is written by another process, and a shape
    this loop does not understand must cost one quiet pass rather than the
    whole sweep."""

    def test_names_come_out_in_rank_order(self):
        result = {"shortlist": [{"name": "Cogwin"}, {"name": "Sprout"}]}
        self.assertEqual(recruit.names_from_shortlist(result), ["Cogwin", "Sprout"])

    def test_a_missing_shortlist_key_is_empty_and_not_an_error(self):
        self.assertEqual(recruit.names_from_shortlist({"outcome": "read"}), [])

    def test_junk_in_the_list_is_stepped_over(self):
        result = {"shortlist": [None, {"name": ""}, {"level": 20}, {"name": "Mirelle"}]}
        self.assertEqual(recruit.names_from_shortlist(result), ["Mirelle"])

    def test_a_non_dict_result_is_empty(self):
        self.assertEqual(recruit.names_from_shortlist([]), [])

    def test_the_roster_numbers_come_off_the_module_answer(self):
        self.assertEqual(
            recruit.roster_from_shortlist({"members": 5, "target_size": 40}), (5, 40)
        )

    def test_missing_roster_numbers_read_as_zero_and_not_as_full(self):
        """Zero member_count against zero target_size means "no size gate",
        which lets the sweep proceed. The opposite default would make a
        missing key silently stop recruiting for ever."""
        self.assertEqual(recruit.roster_from_shortlist({}), (0, 0))
        self.assertEqual(recruit.roster_from_shortlist({"members": "five"}), (0, 0))


class TheLoopIsActuallyWired(unittest.TestCase):
    """bridge.py imports discord and pymysql, so it is read rather than
    imported. AST where a comment could otherwise match."""

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _names_in(self, fn_name):
        fn = next(
            n for n in ast.walk(self.tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == fn_name
        )
        return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)
        }

    def test_the_loop_is_registered_in_both_lists(self):
        """setup_hook and the headless driver. A loop in only one runs only
        under Discord, and wow-dev runs headless."""
        self.assertEqual(self.source.count("self._recruit_loop,"), 2)

    def test_the_pass_asks_the_pure_planner(self):
        self.assertIn("plan_recruit", self._names_in("_recruit_once"))

    def test_the_pass_reads_the_shortlist_and_the_memory(self):
        names = self._names_in("_recruit_once")
        self.assertIn("_latest_guild_shortlist", names)
        self.assertIn("_guild_invites_asked", names)
        self.assertIn("_minutes_since_last_guild_invite", names)
        self.assertIn("_minutes_since_shortlist_asked", names)

    def test_the_backpressure_read_has_no_status_filter(self):
        """Its whole job is to see rows that never reached 'delivered'. A
        status filter here would make it a duplicate of the other read and
        restore the re-ask loop it exists to stop."""
        fn = next(
            n for n in ast.walk(self.tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_minutes_since_shortlist_asked"
        )
        self.assertNotIn("status", ast.get_source_segment(self.source, fn).split('"""')[-1])

    def test_the_pass_writes_through_insert_guild(self):
        self.assertIn("_insert_guild", self._names_in("_recruit_once"))

    def test_insert_guild_can_write_target_arg(self):
        """Without this column no invite this bridge writes can ever run."""
        fn = next(
            n for n in ast.walk(self.tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_insert_guild"
        )
        self.assertIn("target_arg", {a.arg for a in fn.args.args})
        self.assertIn("target_arg", ast.get_source_segment(self.source, fn))

    def test_insert_guild_is_guarded_like_its_siblings(self):
        """A realm whose `kind` ENUM has no 'guild' value must cost a pass,
        not a loop. 1265 truncated ENUM, 1146 missing table, 1054 missing
        column - the same three codes _insert_bank catches."""
        fn = next(
            n for n in ast.walk(self.tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_insert_guild"
        )
        body = ast.get_source_segment(self.source, fn)
        self.assertIn("1265", body)
        self.assertIn("MySQLError", body)


class TheModuleShipsInTheImage(unittest.TestCase):

    def test_recruit_is_copied_into_the_image(self):
        """test_ship_manifest checks this generically; named here too so a
        failure points at the module that moved rather than at a list."""
        self.assertIn("recruit.py", DOCKERFILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

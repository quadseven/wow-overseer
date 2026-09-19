"""The six roster reads that ask what the whole family is currently doing.

infra#4221, and the sibling of tests/test_cohort_scope_reads.py. The read-only
audit on that epic classified twelve `FROM overseer_roster` reads
`NEEDS_COHORT_SCOPE`. The other suite covers the six where a NAME comes out and
something acts on it. These six ask a question about the STANDING STATE of every
enabled row, and each one is answered wrongly, in its own way, once a second
cohort has rows:

    _crafting_roster        who is on job='craft'. A candidate pool: one name is
                            picked out of it and sent walking.
    _standing_jobs          name -> job for the whole roster, fed to
                            craft_rhythm.standing_mode() - a SECOND unanimity
                            function shaped exactly like family_mode, which the
                            epic never named. Two cohorts are a permanent
                            disagreement, so it returns '' for ever.
    _standing_travel_aims   name -> travel_npc for the whole roster. Reads only,
                            and its result is handed to
                            townslot.stranded_nonleader_aims and then to
                            _release_trade_errand, so it is a read that becomes
                            a write into somebody else's column.
    _activate_training      name -> job again, and it fails in BOTH directions:
                            trainjob.should_activate needs unanimous 'quest'
                            across the dict, and if it passes, the loop inserts
                            a job command for every name in it.
    _roster_jobs            name -> job for chat.mid_run's gating.
    _forge_errands          which smelters have a forge recipe outstanding.

None of them has ever misbehaved, because `overseer_roster` has never held a
second cohort's rows. That is the difficulty: there is no production symptom to
reproduce, no log line, nothing in a dashboard. A `standing_mode` of `''` is
indistinguishable from a family that is genuinely between modes, and a released
travel aim writes nothing at all - the character simply stops walking.

So this suite builds the second cohort the live table does not have and runs
both shapes against it in SQLite:

  * the shape each read had BEFORE this change, spelled out below as historical
    constants, to show the contamination is real and not theoretical;
  * the shape `bridge.py` emits NOW, lifted out of its own source and evaluated
    with its own `scope` expression, to show it is gone.

THE SECOND HALF IS WHAT MAKES THIS A TEST AND NOT A DEMONSTRATION, the same
discipline tests/test_cohort_scope.py established: reverting any one of the six
WHERE clauses makes the matching "leaves the other cohort alone" test fail,
because the SQL under test is read out of `bridge.py` rather than restated here.
Nothing below asserts against a string this file made up.

THE UNANIMITY FUNCTIONS ARE CALLED FOR REAL, not imitated. `craft_rhythm` and
`trainjob` are importable here (only `bridge.py` is not, because it imports
discord), so the two tests that matter most run the actual
`craft_rhythm.standing_mode` and `trainjob.should_activate` over the rows each
statement returns. A test that re-implemented "do the values agree" would pass
even if those functions had changed their minds about what agreement is.

THE HARNESS IS IMPORTED, NOT COPIED. `test_cohort_scope` already owns the AST
lifting, the MySQL-to-SQLite translation and the two cohort names, and a second
copy would be a second place for the rule to drift - the exact argument
infra#4221 makes for one cohort column over a forked schema. Importing one test
module from another is the precedent test_raidcraft.py sets.

WHAT THIS DOES NOT COVER, on purpose. `_aimed_names` and `_travelling_names`
are deliberately NOT scoped - the audit is explicit that scoping them
reintroduces infra#3423, the nineteen-minutes-motionless bug - and a test below
asserts they stay that way. Whether one bridge process should serve both
cohorts or one each is still open on infra#4221; it decides whether
`overseer_trade` and `overseer_goal` need columns of their own, and it does not
change whether these six reads are right.
"""
import sqlite3
import unittest

import craft
import craft_rhythm
import trainjob
from test_cohort_scope import (
    CAVE,
    OTHER,
    _assigned,
    _function_code,
    _sqlite,
    _statement,
)

# ---------------------------------------------------------------------------
# The six statements as they stood before this change.
#
# Verbatim. They are here to be RUN, not compared against prose: the tests
# below execute them against a two-cohort table and assert they do the damage
# the audit said they would.

HISTORIC_CRAFTING_ROSTER = (
    "SELECT name FROM overseer_roster WHERE enabled = 1 AND job = %s"
)
HISTORIC_STANDING_JOBS = "SELECT name, job FROM overseer_roster WHERE enabled = 1"
HISTORIC_STANDING_TRAVEL_AIMS = (
    "SELECT name, travel_npc FROM overseer_roster WHERE enabled = 1"
)
HISTORIC_ACTIVATE_TRAINING = HISTORIC_STANDING_JOBS
HISTORIC_ROSTER_JOBS = HISTORIC_STANDING_JOBS
HISTORIC_FORGE_ERRANDS = (
    "SELECT name, craft_spell FROM overseer_roster "
    "WHERE enabled = 1 AND job = %s AND craft_spell > 0"
)


def _emit(func: str, index: int = 0, cohort=CAVE, **extra):
    """The SQL and bound params `bridge.py` emits for `func`, at `cohort`.

    `scope` and `scope_args` are READ OUT OF bridge.py rather than supplied,
    which is the whole point: a test that handed in its own " AND family = %s"
    would keep passing against a bridge that had stopped choosing one.

    `cohort` is the one local NOT read back, because reading it would run
    `_cohort_of` and that needs a database. It is supplied instead, which is
    also how both cohorts and the degraded case are reached.
    """
    names = dict(extra)
    names["cohort"] = cohort
    names["scope"] = _assigned(func, "scope", names)
    names["scope_args"] = _assigned(func, "scope_args", names)
    return _statement(func, index, **names)


# ---------------------------------------------------------------------------
# The two-cohort roster.
#
# CAVE is the value every row in the live table will carry, because
# mod-overseer#506's column is NOT NULL DEFAULT 'Grug' and the ALTER backfills
# every existing row in one pass. OTHER is a second cohort no database has yet.
# Who is in it is deliberately not the point and is explicitly out of scope on
# infra#4221 - all that matters is that a second family's rows exist.
#
# THIS FAMILY IS UNANIMOUS AND THE OTHER ONE IS NOT, which is the fixture's
# whole job. Both unanimity functions under test answer "do the values agree",
# so a mixed fixture that happened to agree across cohorts would prove nothing.
#
# The job keywords come from the modules that own them rather than being spelled
# out here: `_forge_errands` binds `craft.MODE` and the test evaluates that same
# expression, so a rename would otherwise move the code and leave the fixture
# agreeing with a string nothing uses any more.

CRAFT = craft.MODE
QUEST = craft_rhythm.MODE_GATHER

# name, enabled, job, travel_npc, craft_spell, family
_TWO_COHORTS = (
    ("Grug",     1, QUEST, "",       0,     CAVE),
    ("Ugga",     1, QUEST, "",       0,     CAVE),
    ("Grog",     1, QUEST, "vendor", 0,     CAVE),
    ("Bork",     1, QUEST, "",       0,     CAVE),
    ("Og",       1, QUEST, "",       0,     CAVE),
    # Disabled, and in this cohort: proves `enabled = 1` is still doing its own
    # job and has not been quietly replaced by the cohort predicate.
    ("Snik",     0, QUEST, "",       0,     CAVE),
    ("Blammo",   1, CRAFT, "",       3304,  OTHER),
    ("Hexmama",  1, "raid prep", "banker", 0, OTHER),
    ("Moojuice", 1, "gather", "",    0,     OTHER),
)

_ONE_COHORT = tuple(row for row in _TWO_COHORTS if row[5] == CAVE)

# A crafter and a smelter in THIS cohort, so the candidate-pool tests have
# something to find rather than asserting against an empty set both ways.
_WITH_OWN_CRAFTER = _ONE_COHORT + (
    ("Thok", 1, CRAFT, "", 2660, CAVE),
) + tuple(row for row in _TWO_COHORTS if row[5] == OTHER)

_CAVE_ENABLED = sorted(r[0] for r in _TWO_COHORTS if r[5] == CAVE and r[1])


def _roster(rows=None) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE overseer_roster ("
        "  name TEXT PRIMARY KEY,"
        "  enabled INTEGER NOT NULL DEFAULT 1,"
        "  job TEXT NOT NULL DEFAULT '',"
        "  travel_npc TEXT NOT NULL DEFAULT '',"
        "  craft_spell INTEGER NOT NULL DEFAULT 0,"
        # NOT NULL DEFAULT 'Grug', exactly as mod-overseer#506 declares it.
        "  family TEXT NOT NULL DEFAULT 'Grug')"
    )
    db.executemany(
        "INSERT INTO overseer_roster "
        "(name, enabled, job, travel_npc, craft_spell, family) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        _TWO_COHORTS if rows is None else rows,
    )
    return db


class RosterCase(unittest.TestCase):
    """A two-cohort roster per test, closed when the test ends.

    Closed explicitly rather than left to the collector: an unclosed connection
    is a ResourceWarning on every run, and a suite whose output has warnings in
    it is a suite whose output stops being read.
    """

    def roster(self, rows=None) -> sqlite3.Connection:
        db = _roster(rows)
        self.addCleanup(db.close)
        return db

    def names(self, db, sql, params=()) -> list:
        return sorted(str(row[0]) for row in db.execute(sql, params))

    def pairs(self, db, sql, params=()) -> dict:
        return {str(row[0]): row[1] for row in db.execute(sql, params)}


class TheCraftCandidatePoolUsedToCrossCohorts(RosterCase):
    """`WHERE enabled = 1 AND job = 'craft'`.

    A candidate pool, and `craft_rhythm.errand` picks one name out of it.
    `_craft_once` then writes that character's `craft_spell`, which sends it
    walking to a `travel_npc` this family's leader logic never accounted for.
    """

    def test_the_old_statement_puts_the_other_guilds_crafter_in_the_pool(self):
        db = self.roster(_WITH_OWN_CRAFTER)

        got = self.names(db, _sqlite(HISTORIC_CRAFTING_ROSTER), (CRAFT,))

        self.assertEqual(
            ["Blammo", "Thok"], got,
            "the unscoped read was supposed to pool both cohorts' crafters - if "
            "it no longer does, this reproduction has stopped reproducing",
        )

    def test_the_statement_the_bridge_emits_pools_only_this_cohort(self):
        sql, params = _emit("_crafting_roster")
        db = self.roster(_WITH_OWN_CRAFTER)

        got = self.names(db, _sqlite(sql), params)

        self.assertEqual(["Thok"], got)
        self.assertNotIn(
            "Blammo", got,
            "a character in the other guild was a candidate for this family's "
            "craft errand",
        )

    def test_the_job_predicate_is_still_bound_and_still_applies(self):
        """The cohort clause is added to `job = %s`, not instead of it. A pool
        that had stopped filtering on the job would aim a character DriveCraft
        refuses to act for, which is a walk paid for by the gathering trip it
        replaced."""
        sql, params = _emit("_crafting_roster")
        db = self.roster(_WITH_OWN_CRAFTER)

        self.assertEqual((CRAFT, CAVE), params)
        self.assertNotIn("Grug", self.names(db, _sqlite(sql), params))


class TheStandingModeUsedToCrossCohorts(RosterCase):
    """`craft_rhythm.standing_mode` is a second `family_mode` nobody named.

    This function exists BECAUSE a family half on craft and half on quest must
    be distinguishable from a family wholly on craft. Two cohorts are a
    permanent disagreement, so the answer becomes `''` for ever and craft
    supply, the craft rhythm and the skill-goal pass all stand down - for THIS
    family, with nothing logged that names the cause.

    `standing_mode` is CALLED, not imitated. A test that re-implemented "do the
    values agree" would pass even after that function changed its mind about
    what agreement is.
    """

    def test_the_old_statement_makes_the_standing_mode_permanently_empty(self):
        db = self.roster()

        jobs = self.pairs(db, _sqlite(HISTORIC_STANDING_JOBS))

        self.assertEqual(
            "", craft_rhythm.standing_mode(jobs),
            "the unscoped read was supposed to mix jobs across cohorts, which "
            "is what makes standing_mode refuse - if it no longer does, this "
            "reproduction has stopped reproducing",
        )

    def test_the_statement_the_bridge_emits_yields_an_agreed_mode(self):
        sql, params = _emit("_standing_jobs")
        db = self.roster()

        jobs = self.pairs(db, _sqlite(sql), params)

        self.assertEqual(QUEST, craft_rhythm.standing_mode(jobs))
        self.assertEqual(_CAVE_ENABLED, sorted(jobs))

    def test_a_genuine_disagreement_inside_this_cohort_still_refuses(self):
        """Scoping must not have turned the unanimity check into a formality.
        A family that really is half on craft still gets '' - that is the whole
        behaviour this read exists to make possible."""
        sql, params = _emit("_standing_jobs")
        db = self.roster(_WITH_OWN_CRAFTER)

        jobs = self.pairs(db, _sqlite(sql), params)

        self.assertIn("Thok", jobs)
        self.assertEqual("", craft_rhythm.standing_mode(jobs))


class TheStandingTravelAimsUsedToCrossCohorts(RosterCase):
    """A read that becomes a write.

    `_release_stranded_ground_errands` hands what this returns to
    `townslot.stranded_nonleader_aims` along with `_head_now()`, and calls
    `_release_trade_errand` on every name that comes back. "Stranded" is
    "holding a ground aim and not being the leader", and every row in another
    cohort is by construction not this family's leader - so every legitimate
    economy aim the other guild holds looks stranded and is blanked, every 90
    seconds, for ever, with nothing written down about it.
    """

    def test_the_old_statement_exposes_the_other_cohorts_live_aim(self):
        db = self.roster()

        aims = self.pairs(db, _sqlite(HISTORIC_STANDING_TRAVEL_AIMS))

        self.assertEqual(
            "banker", aims.get("Hexmama"),
            "the unscoped read was supposed to expose the other cohort's live "
            "errand to this family's stranded-aim sweep",
        )

    def test_the_statement_the_bridge_emits_cannot_see_it(self):
        sql, params = _emit("_standing_travel_aims")
        db = self.roster()

        aims = self.pairs(db, _sqlite(sql), params)

        self.assertNotIn(
            "Hexmama", aims,
            "the other cohort's town errand was about to be released by this "
            "cohort's sweep, and nothing would have said so",
        )
        self.assertEqual(
            "vendor", aims["Grog"],
            "this cohort's own stranded aim must still be visible - a sweep "
            "that can see nothing releases nothing",
        )


class TheTrainingPromotionUsedToCrossCohorts(RosterCase):
    """Both halves of `_activate_training` are unscoped, and they fail in
    opposite directions.

    `trainjob.should_activate` needs unanimous 'quest' across the whole dict, so
    one foreign row on any other job means this family can never auto-promote.
    And if it did pass, the loop inserts a `job train` command for every name in
    the same dict - the other guild's whole roster ordered to train by a process
    that does not drive it.
    """

    def test_the_old_statement_blocks_the_promotion_for_ever(self):
        db = self.roster()

        jobs = self.pairs(db, _sqlite(HISTORIC_ACTIVATE_TRAINING))

        self.assertFalse(
            trainjob.should_activate(jobs, True),
            "the unscoped read was supposed to make should_activate refuse - if "
            "it no longer does, this reproduction has stopped reproducing",
        )

    def test_the_statement_the_bridge_emits_lets_the_promotion_happen(self):
        sql, params = _emit("_activate_training")
        db = self.roster()

        jobs = self.pairs(db, _sqlite(sql), params)

        self.assertTrue(trainjob.should_activate(jobs, True))

    def test_the_fan_out_half_only_covers_this_cohort(self):
        """The same dict is iterated to insert one job command per name. This
        is the permissive failure the restrictive one was hiding: had the
        unanimity check ever passed, every row here would have been ordered to
        train."""
        sql, params = _emit("_activate_training")
        db = self.roster()

        jobs = self.pairs(db, _sqlite(sql), params)

        self.assertEqual(_CAVE_ENABLED, sorted(jobs))
        for name in ("Blammo", "Hexmama", "Moojuice"):
            self.assertNotIn(name, jobs)

    def test_one_read_serves_both_halves(self):
        """Scoped in the QUERY rather than by filtering `jobs` afterwards,
        which is why one predicate fixes both failures at once. A Python-side
        filter would have to be applied twice and could be forgotten once."""
        code = _function_code("_activate_training")
        self.assertIn("_cohort_of", code)
        self.assertEqual(
            1, code.count("FROM overseer_roster"),
            "the promotion must read the roster once and serve both halves "
            "from that read; a second read is a second place to forget the "
            "cohort",
        )


class TheChatJobGateUsedToCrossCohorts(RosterCase):
    """The lowest blast radius of the twelve, and scoped with the rest anyway.

    `chat.mid_run` looks names up in this dict, so foreign rows are names it
    never asks about and cost nothing today. It is scoped because the
    alternative is a rule with an exception in it, and the next person to add a
    caller inherits whichever of the two this function actually is.
    """

    def test_the_old_statement_returns_both_guilds(self):
        db = self.roster()

        self.assertIn("Moojuice", self.pairs(db, _sqlite(HISTORIC_ROSTER_JOBS)))

    def test_the_statement_the_bridge_emits_returns_one(self):
        sql, params = _emit("_roster_jobs")
        db = self.roster()

        self.assertEqual(_CAVE_ENABLED, sorted(self.pairs(db, _sqlite(sql), params)))


class TheForgeDemandSignalUsedToCrossCohorts(RosterCase):
    """Demand-driven, and a second cohort is demand this family never signalled.

    The forge pass is strictly demand-driven so that it does not compete for the
    single travel column unless somebody is actually smelting. A foreign miner
    with `craft_spell > 0` puts a character the other guild drives into that
    contention - the half-hour-in-a-shop failure this function was written to
    avoid, arriving through the door the design closed.
    """

    def test_the_old_statement_finds_the_other_guilds_smelter(self):
        db = self.roster(_WITH_OWN_CRAFTER)

        got = self.names(db, _sqlite(HISTORIC_FORGE_ERRANDS), (CRAFT,))

        self.assertEqual(
            ["Blammo", "Thok"], got,
            "the unscoped read was supposed to see both cohorts' outstanding "
            "craft errands",
        )

    def test_the_statement_the_bridge_emits_finds_only_ours(self):
        sql, params = _emit("_forge_errands", craft=craft)
        db = self.roster(_WITH_OWN_CRAFTER)

        self.assertEqual(["Thok"], self.names(db, _sqlite(sql), params))

    def test_it_is_still_empty_when_this_cohort_has_no_demand(self):
        """The whole point of the pass. A cohort with nothing outstanding must
        still aim nobody, or the fix would have turned a demand signal into a
        standing one."""
        sql, params = _emit("_forge_errands", craft=craft)
        db = self.roster()

        self.assertEqual([], self.names(db, _sqlite(sql), params))


class AgainstTheOnlyCohortThatExistsTodayNothingChangesAtAll(RosterCase):
    """The regression risk this change has to answer, measured rather than
    argued.

    Every row in the live table will carry the same `family` value, because the
    column is NOT NULL DEFAULT 'Grug' and the ALTER backfills in one pass. On
    such a table a predicate that selects that one value selects everything, so
    the scoped read and the read it replaced must return exactly the same rows.
    These run both and compare.
    """

    CASES = (
        ("_crafting_roster", HISTORIC_CRAFTING_ROSTER, (CRAFT,), {}),
        ("_standing_jobs", HISTORIC_STANDING_JOBS, (), {}),
        ("_standing_travel_aims", HISTORIC_STANDING_TRAVEL_AIMS, (), {}),
        ("_activate_training", HISTORIC_ACTIVATE_TRAINING, (), {}),
        ("_roster_jobs", HISTORIC_ROSTER_JOBS, (), {}),
        ("_forge_errands", HISTORIC_FORGE_ERRANDS, (CRAFT,), {"craft": craft}),
    )

    def test_each_read_returns_the_same_rows_as_before(self):
        rows = _ONE_COHORT + (("Thok", 1, CRAFT, "", 2660, CAVE),)
        for func, historic, historic_params, extra in self.CASES:
            with self.subTest(func=func):
                old = self.roster(rows)
                before = list(old.execute(_sqlite(historic), historic_params))

                sql, params = _emit(func, **extra)
                new = self.roster(rows)

                self.assertEqual(before, list(new.execute(_sqlite(sql), params)))
                self.assertTrue(before, "the fixture must return rows at all")


class UntilTheColumnShipsTheStatementsAreUnchangedCharacterForCharacter(
        unittest.TestCase):
    """NO RUNNING WORLD HAS THE `family` COLUMN YET.

    mod-overseer#506 is merged and infra#4234 has pinned a submodule gitlink
    that carries its SQL. Neither of those is a deployment: `worldserver` and
    `db-import` are absent from `deploy.wow-image-tags.yml`, so the migration
    ships inert with nothing red until the image is rebuilt and the running
    digest is checked by hand.

    So the path that actually executes in production today is the degraded one,
    and "degraded" has to mean today's statement exactly - not a narrower one,
    and above all not no read at all. A craft pool that came back empty, a
    standing mode that could never be agreed, or a travel-aim sweep that could
    see nothing to release would each be a far worse outcome than the
    cross-cohort bug this change closes, and would be the price of a schema that
    has not shipped rather than of anything anyone did wrong.

    `_cohort_of` returns None on 1054/1146. These assert what each read then
    emits, character for character. Six of them, one per site: the negative case
    matters as much as the positive one and there is no reason to prove it for
    only some of the change.
    """

    DEGRADED = (
        ("_crafting_roster", HISTORIC_CRAFTING_ROSTER, (CRAFT,), {}),
        ("_standing_jobs", HISTORIC_STANDING_JOBS, (), {}),
        ("_standing_travel_aims", HISTORIC_STANDING_TRAVEL_AIMS, (), {}),
        ("_activate_training", HISTORIC_ACTIVATE_TRAINING, (), {}),
        ("_roster_jobs", HISTORIC_ROSTER_JOBS, (), {}),
        ("_forge_errands", HISTORIC_FORGE_ERRANDS, (CRAFT,), {"craft": craft}),
    )

    def test_each_read_falls_back_to_the_statement_it_replaced(self):
        for func, historic, params, extra in self.DEGRADED:
            with self.subTest(func=func):
                sql, got = _emit(func, 0, None, **extra)
                self.assertEqual(historic, sql)
                self.assertEqual(params, got)

    def test_a_degraded_standing_read_still_returns_the_whole_family(self):
        """The assertions above are on the text. This one runs it: an empty
        result on a world without the column would stand the craft rhythm, the
        craft supply and the skill-goal pass all down, which is the failure
        mode this degradation exists to avoid."""
        sql, params = _emit("_standing_jobs", 0, None)
        db = _roster(_ONE_COHORT)
        self.addCleanup(db.close)

        jobs = {str(row[0]): row[1] for row in db.execute(_sqlite(sql), params)}

        self.assertEqual(_CAVE_ENABLED, sorted(jobs))
        self.assertEqual(QUEST, craft_rhythm.standing_mode(jobs))


class TheCohortKeyIsReadOffTheRowAndNeverHardcoded(unittest.TestCase):
    """mod-overseer#506's migration insists on this in its own comments, and it
    is the one way to get this wrong that a two-cohort table would not catch.

    The column's DEFAULT is the literal 'Grug'. A validation world renames the
    cast (cast.py), so the head of the family there is spelled differently, and
    a statement pinned to the literal would match NO row in that world - which
    is the unscoped bug's mirror image and exactly as silent.
    """

    SCOPED = (
        "_crafting_roster",
        "_standing_jobs",
        "_standing_travel_aims",
        "_activate_training",
        "_roster_jobs",
        "_forge_errands",
    )

    def test_every_one_of_the_six_asks_which_cohort_it_is_in(self):
        """A helper nothing calls is the shape of fix that ships and does
        nothing."""
        for name in self.SCOPED:
            self.assertIn("_cohort_of", _function_code(name), name)

    def test_every_one_of_the_six_resolves_it_from_the_head_of_the_family(self):
        """One identity, one rule. The head is the one name this process is
        certain is on the roster, and it is the same identity `_aim_traveller`
        already binds - so if the one-process-per-cohort question resolves the
        other way there is exactly one expression to change."""
        for name in self.SCOPED:
            self.assertIn("head_of_family", _function_code(name), name)

    def test_no_cohort_literal_is_written_into_any_of_the_six(self):
        for name in self.SCOPED:
            self.assertNotIn("'%s'" % CAVE, _function_code(name), name)
            self.assertNotIn("'%s'" % OTHER, _function_code(name), name)

    def test_the_two_deferred_reads_are_left_exactly_as_they_were(self):
        """`_aimed_names` and `_travelling_names` are NEEDS_COHORT_SCOPE and
        deliberately not scoped. Both are pure membership sets consumed by
        `name in <set>`, so extra names are inert - but scoping them means a
        character on an errand stops counting as aimed, and the strategy pass
        takes `new rpg` straight back off it. That is verbatim infra#3423, the
        nineteen-minutes-motionless bug. Asserted rather than left to a comment:
        a later sweep of "the remaining roster reads" would otherwise scope them
        for tidiness and reintroduce it.

        Matched on the CLAUSE and on the helper, not on the word "family":
        `_aimed_names` already says "the family falls back to leader-only
        travel" in its own 1054 warning, and an assertion that tripped on prose
        would have to be loosened by the next person to touch it."""
        for name in ("_aimed_names", "_travelling_names"):
            code = _function_code(name)
            self.assertNotIn("_cohort_of", code, name)
            self.assertNotIn("family = ", code, name)


if __name__ == "__main__":
    unittest.main()

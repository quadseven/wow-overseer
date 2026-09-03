"""A column a later migration adds must not be able to take an older drive off
the air.

infra#2846. PR #2840 added `travel_npc` to the quest drive's own query:

    SELECT name, drive_quest, `lead`, travel_npc FROM overseer_roster ...
    if (!result) return;

MySQL fails a SELECT naming a column the table does not have WHOLE - error
1054, no partial rows - and CharacterDatabase.Query hands that back as a null
QueryResult, indistinguishable from "no rows matched". So on any world whose
schema predates `travel_npc`, `DriveQuests` returned early on EVERY poll and
the family stopped questing, silently, for a feature it has nothing to do with.

The comment that justified having no degrade said the DDL and the reader "ship
in the same image ... so the two cannot disagree". They do not and they can.
mod-overseer's SQL is applied by the `db-upgrade` initContainer running the
DB-IMPORT image; this file is compiled into the WORLDSERVER image; the two are
pinned by separate digests in the same manifest and bumped independently.
30-db-import.yaml says the worldserver has no SQL at all, in as many words.

The C++ here is compiled only on a push to `main`, never on a PR, so these are
contract tests over the source text in the pattern test_quest_aim.py and
test_travel_npc.py established - plus two that read the k8s manifests, so the
citations in the corrected comment cannot rot into the same kind of confident
falsehood they replace.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
DB_IMPORT = ROOT / "oke/manifests/wow/30-db-import.yaml"
WORLDSERVER = ROOT / "oke/manifests/wow/50-worldserver.yaml"


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

    Searching the raw source is not a reachability test: the comments in this
    file quote SQL and upstream members it deliberately does not use, and a
    column named only in prose is not a column selected.
    """
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _quests() -> str:
    return _function("void DriveQuests()")


def _travel() -> str:
    return _function("void DriveTravel()")


def _end_travel_poll() -> str:
    return _function("void EndTravelPoll(std::set<std::string> const& stillAimed)")


def _load_quest_aims() -> str:
    return _function("std::map<std::string, uint32> LoadQuestAims()")


def _load_travel_aims() -> str:
    """The travel column's one reader. It moved from a free LoadTravelAims()
    onto TravelAimBook (`_travelAims.Load()`, mod_overseer.cpp) when the
    errand memory, the release and the prune were gathered into one book;
    the loader's contract - one SELECT, guarded, read-only - did not move."""
    return _function("std::map<std::string, std::string> Load() const")


def _handback_grace() -> str:
    """The hand-back clock, which TravelHoldsTheWheel used to read inline and
    now asks the book for (`TravelAimBook::WithinHandbackGrace`)."""
    return _function("bool WithinHandbackGrace(std::string const& name)")


def _selects(column: str) -> int:
    """How many SELECT statements in the whole file name this column.

    Counted over the SELECT text rather than over the column name, because
    `travel_npc` legitimately appears in an UPDATE (the release) and in prose.
    """
    return len([
        stmt for stmt in re.findall(r'"SELECT[^;]*?"\s*\)', _code(_source()),
                                    re.S)
        if column in stmt
    ])


class TheQuestDriveCannotBeKilledByATravelColumn(unittest.TestCase):
    """The defect, stated as a property. `travel_npc` is read for exactly one
    reason - to decide whether the quest drive should stand down - and a
    decision input that can silence the whole drive when it is unavailable is
    worse than no decision at all."""

    def test_the_quest_drives_own_query_does_not_name_the_travel_column(self):
        self.assertNotIn("travel_npc", _code(_quests()),
                         "a missing travel_npc nulls this query and the family "
                         "stops questing (infra#2846)")

    def test_the_quest_drive_still_gets_the_travel_aims(self):
        """Not fixed by deleting the arbitration's input. It has to still know."""
        self.assertIn("_travelAims.Load()", _code(_quests()))

    def test_a_character_with_no_errand_reads_as_an_empty_target(self):
        """Absent from the map has to mean the same as an empty column, or the
        arbitration's `travelTarget.empty()` case changes meaning."""
        self.assertRegex(_code(_quests()), r"std::string\(\)")

    def test_the_early_return_is_still_there_for_the_roster_itself(self):
        """This is not "guard everything". A roster query that comes back null
        means there is no roster, and there is nothing to drive."""
        self.assertIn("if (!result)", _code(_quests()))


class TheQuestAimHasTheSameExposureAndIsHandledTheSameWay(unittest.TestCase):
    """`drive_quest` (2026_08_24_00) is younger than the fallback it would take
    down with it. The leader's own-log walk and the repick memory predate the
    council aim entirely, and they are what "the family plays badly" instead of
    "the family stands still" is made of. A missing `drive_quest` must cost the
    aim and nothing else."""

    def test_the_quest_drives_own_query_does_not_name_the_aim_column(self):
        self.assertNotIn("drive_quest", _code(_quests()))

    def test_the_aim_is_read_by_its_own_guarded_loader(self):
        self.assertIn("LoadQuestAims()", _code(_quests()))
        self.assertIn("drive_quest", _code(_load_quest_aims()))

    def test_an_absent_aim_is_zero_which_is_the_columns_own_sentinel(self):
        """0 = "no opinion" is what the migration defines, and what the
        fallback already keys on."""
        code = _code(_quests())
        self.assertRegex(code, r"aims\.end\(\)\s*\?\s*0")
        self.assertIn("bool const aimed = aim != 0;", code)

    def test_the_leader_only_fallback_is_still_reachable(self):
        code = _code(_quests())
        self.assertIn("if (!isLead)", code)
        self.assertIn("MAX_QUEST_LOG_SIZE", code)


class EachLateColumnIsReadOnceAndGuardedOnItsOwn(unittest.TestCase):
    """The fix is a shape, not a patch on one call site. One SELECT per
    late-added column, each returning that column's "no opinion" value when the
    read comes back null - which is the same answer the empty result set wants,
    so no 1054 test is needed anywhere."""

    def test_the_travel_column_is_selected_in_exactly_one_place(self):
        self.assertEqual(1, _selects("travel_npc"))

    def test_the_aim_column_is_selected_in_exactly_one_place(self):
        self.assertEqual(1, _selects("drive_quest"))

    def test_both_loaders_return_the_empty_map_rather_than_propagating(self):
        for name, body in (("LoadQuestAims", _code(_load_quest_aims())),
                           ("TravelAimBook::Load", _code(_load_travel_aims()))):
            self.assertIn("if (!result)", body, name)
            guard = body.index("if (!result)")
            tail = body[guard:guard + 120]
            self.assertIn("return aims;", tail,
                          "%s propagates the failure instead of degrading" % name)

    def test_neither_loader_filters_on_anything_but_the_column_and_enabled(self):
        for body in (_code(_load_quest_aims()), _code(_load_travel_aims())):
            self.assertIn("enabled = 1", body)

    def test_the_loaders_only_ever_read(self):
        """A loader that also writes is a second decision-maker."""
        for body in (_code(_load_quest_aims()), _code(_load_travel_aims())):
            self.assertNotIn("Execute", body)
            self.assertNotIn("UPDATE", body)

    def test_the_roster_query_keeps_only_columns_older_than_this_drive(self):
        """`name` and `enabled` are the CREATE TABLE (2026_08_23_00); `lead` is
        2026_08_23_01 and is read unguarded by KeepRosterGrouped too. If those
        are missing the roster feature is not installed at all, and there is
        nothing for this drive to degrade to."""
        self.assertRegex(_code(_quests()),
                         r"SELECT name, `lead` FROM overseer_roster")


class TheTravelDriveReadsThroughTheSameLoader(unittest.TestCase):
    """Two queries for the same fact in the same 20 seconds can disagree. One
    reader means the arbitration and the errand loop can only ever be looking
    at the same rows."""

    def test_the_travel_drive_has_no_query_of_its_own(self):
        self.assertNotIn("SELECT", _code(_travel()))

    def test_it_gets_its_errands_from_the_loader(self):
        self.assertIn("_travelAims.Load()", _code(_travel()))

    def test_no_errands_still_prunes_and_returns(self):
        """A null result used to mean this; an empty map means it now. The
        prune is the only place a row cleared bridge-side is visible."""
        code = _code(_travel())
        self.assertIn("aims.empty()", code)
        prune = code.index("aims.empty()")
        self.assertIn("EndTravelPoll(std::set<std::string>())",
                      code[prune:prune + 300])
        # The prune moved behind a named verb in #166, which ends the errand
        # memory and the stood-down strategies together. Assert that verb still
        # prunes, or this test would pass on a rename that quietly dropped the
        # prune, which is the one failure it exists to catch.
        self.assertIn("_travelAims.PruneVanished(stillAimed)",
                      _code(_end_travel_poll()))

    def test_the_filter_the_errand_loop_relied_on_moved_with_it(self):
        """DriveTravel never had to skip an empty target because the WHERE
        clause did it. That clause has to still exist somewhere."""
        self.assertIn("travel_npc <> ''", _code(_load_travel_aims()))


class TheArbitrationIsNotRegressed(unittest.TestCase):
    """PR #2840's review argued this out at length and its properties are
    load-bearing. This change moves where the target comes from and nothing
    else."""

    def test_the_decision_still_has_exactly_one_home(self):
        quests = _code(_quests())
        self.assertEqual(1, quests.count("TravelHoldsTheWheel("))
        travel = _code(_travel())
        self.assertNotIn("TravelHoldsTheWheel", travel)
        self.assertNotIn("drive_quest", travel)
        self.assertNotIn("DriveChosenQuest", travel)

    def test_the_stand_down_still_precedes_every_path_that_aims(self):
        quests = _code(_quests())
        wheel = quests.index("TravelHoldsTheWheel(")
        self.assertLess(wheel, quests.index("DriveChosenQuest("))
        self.assertLess(wheel, quests.index("ChangeToDoQuest("))

    def test_the_hand_back_grace_and_its_carry_forward_survive(self):
        quests = _code(_quests())
        self.assertIn("state.travelHeld", quests)
        self.assertIn("state.since += ", quests)
        wheel = _code(_function("bool TravelHoldsTheWheel("))
        # The grace clock is kept by the book now, so the predicate asks it
        # rather than reading the map itself; the constant has to still be
        # what the book compares against, or the grace is a different length.
        self.assertIn("_travelAims.WithinHandbackGrace(name)", wheel)
        self.assertIn("TRAVEL_HANDBACK_SECONDS", _code(_handback_grace()))
        self.assertIn("CanBeSentToNpc(botAI)", wheel)
        self.assertIn("travelTarget.empty()", wheel)

    def test_the_two_drives_are_still_read_at_their_own_cadence(self):
        """A single snapshot taken once per OnUpdate would be stale for one of
        them: the drives are on separate timers and do not share a tick."""
        code = _code(_source())
        self.assertIn("_questTimer >= QUEST_POLL_MS", code)
        # The travel drive's threshold is a local now, because it polls faster
        # only while a dungeon run is escorting (mod-overseer#122): outside an
        # escort it is TRAVEL_POLL_MS exactly as before. Still its own timer,
        # still its own cadence.
        self.assertIn("_travelTimer >= travelPoll", code)
        self.assertRegex(code, r"travelPoll =\s*_dungeonEscorts\.empty\(\) \? TRAVEL_POLL_MS")
        self.assertEqual(1, _code(_quests()).count("_travelAims.Load()"))
        self.assertEqual(1, _code(_travel()).count("_travelAims.Load()"))


class TheCommentThatCausedThisIsCorrected(unittest.TestCase):
    """The false claim is the actual defect - the query was written the way it
    was BECAUSE of it, and it was cited as the reason no 1054 handling was
    needed. Softening it is not enough: a reader has to come away knowing the
    two ship separately."""

    FALSE = "ship in the same image"

    def test_the_false_claim_is_gone(self):
        self.assertNotIn(self.FALSE, _source())

    def test_it_says_which_image_carries_which_half(self):
        # Comment markers dropped and whitespace collapsed: these sentences
        # are wrapped across comment lines, and a reflow is not a change of
        # claim.
        src = " ".join(_source().replace("//", " ").split())
        self.assertIn("30-db-import.yaml", src)
        self.assertIn("the worldserver has no SQL", src)
        self.assertIn("db-upgrade", src)
        self.assertIn("DIFFERENT IMAGES", src)

    def test_the_citation_points_at_the_line_that_says_it(self):
        """A file:line in a comment is a claim, and this one is the whole
        argument. Check it against the manifest itself."""
        cited = re.search(r"30-db-import\.yaml:(\d+)", _source())
        self.assertIsNotNone(cited, "the manifest is cited without a line")
        lines = DB_IMPORT.read_text(encoding="utf-8").splitlines()
        self.assertIn("only db-import gets `COPY data data`",
                      lines[int(cited.group(1)) - 1])


class TheTwoImagesReallyAreBumpedIndependently(unittest.TestCase):
    """The premise of the whole fix, checked against the manifest rather than
    asserted in prose. If this ever stops being true the fix is merely
    unnecessary; while it is true, the old comment was a live hazard."""

    def _images(self):
        """Host-agnostic on purpose. The premise these tests protect is that the
        manifest runs TWO different images pinned SEPARATELY, which is a fact
        about the images and not about where they are hosted. The pattern used
        to require a literal `registry.` prefix, so when production moved to
        ghcr it matched nothing at all and both assertions below failed about a
        hostname instead of about the premise."""
        return re.findall(
            r"image: \S*?(ac-playerbots-[a-z-]+)@(sha256:[0-9a-f]{64})",
            WORLDSERVER.read_text(encoding="utf-8"))

    def test_the_worldserver_manifest_runs_two_different_images(self):
        repos = {repo for repo, _ in self._images()}
        self.assertIn("ac-playerbots-db-import", repos)
        self.assertIn("ac-playerbots-worldserver", repos)

    def test_the_sql_is_applied_by_the_db_import_image_not_the_worldserver(self):
        text = WORLDSERVER.read_text(encoding="utf-8")
        upgrade = text.index("name: db-upgrade")
        after = text[upgrade:upgrade + 400]
        self.assertIn("ac-playerbots-db-import", after)
        self.assertNotIn("ac-playerbots-worldserver", after)

    def test_they_are_pinned_by_separate_digests(self):
        digests = {repo: digest for repo, digest in self._images()}
        self.assertNotEqual(
            digests["ac-playerbots-db-import"],
            digests["ac-playerbots-worldserver"],
            "two independently bumped pins is the reason the schema and the "
            "reader can disagree")


if __name__ == "__main__":
    unittest.main()

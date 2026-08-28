"""The RimWorld-style job schedule (infra#2834), C++ half.

The C++ in this repo is only compiled on a push to `main`, never on a PR
(see test_travel_npc.py's own header for the fuller version of this
argument), so this is a contract test over the source text, in the same
pattern: it pins the ways this change could be shipped and still do nothing,
without needing a worldserver build to check them against.

wow-dev is offline as of this writing (physical RAM swap on its host), so
NONE of this has been run against a live worldserver. What follows is
reasoned from the source, not observed - stated here rather than left
implicit, per the epic's own rule about `delivered` meaning nothing was
verified.
"""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
MIGRATION = (
    ROOT
    / "docker/azerothcore-playerbots/mod-overseer/data/sql/characters/base"
    / "2026_08_26_01_overseer_roster_job.sql"
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import jobs  # noqa: E402


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
                return src[start : i + 1]
    raise AssertionError("%s has no closing brace" % signature)


def _code(text: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _drive_quests() -> str:
    return _function("void DriveQuests()")


def _load_jobs() -> str:
    return _function("std::map<std::string, std::string> LoadJobs()")


def _do_job() -> str:
    return _function(
        "static char const* DoJob(Player* player, std::string const& command, "
        "char const*& status)"
    )


def _cpp_modes() -> set:
    """The module's own list of valid job-mode names."""
    body = _function("static std::vector<std::string> const& JobModes()")
    return set(re.findall(r'"([^"]+)"', _code(body)))


class TheVocabularyMatchesPython(unittest.TestCase):
    """A mode this side accepts and the module silently rejects (or vice
    versa) is the written-and-unread failure of #2776 wearing a new hat -
    exactly what tests/test_travel_npc.py already guards for travel.ROLES."""

    def test_every_python_mode_is_known_to_the_module(self):
        cpp = _cpp_modes()
        missing = set(jobs.MODES) - cpp
        self.assertFalse(missing, f"jobs.py names modes the module rejects: {missing}")

    def test_the_module_names_nothing_python_does_not(self):
        cpp = _cpp_modes()
        extra = cpp - set(jobs.MODES)
        self.assertFalse(extra, f"the module accepts modes jobs.py never named: {extra}")


class TheGateStandsDownEverythingButQuest(unittest.TestCase):
    def test_drive_quests_reads_the_job_map(self):
        self.assertIn("LoadJobs()", _drive_quests())

    def test_drive_quests_stands_down_a_non_quest_job(self):
        body = _drive_quests()
        self.assertIn("jobIt", body)
        self.assertIn("continue", _code(body))

    def test_the_gate_runs_before_any_quest_aim_is_read(self):
        body = _code(_drive_quests())
        gate = body.index("jobIt")
        aim = body.index("aimIt")
        self.assertLess(gate, aim, "the job gate must run before the quest aim is consulted")

    def test_load_jobs_excludes_quest_from_the_result(self):
        # LoadJobs only returns characters NOT on 'quest' - see its own
        # comment for why. A query that also returned 'quest' rows would
        # still be correct if handled, but the whole point of the shape is
        # that absence already means "drive as normal".
        self.assertIn("job <> 'quest'", _code(_load_jobs()))

    def test_load_jobs_is_read_on_its_own_like_the_older_aim_columns(self):
        body = _load_jobs()
        self.assertIn("if (!result)", body)
        self.assertIn("return jobs;", body)


class TheCommandKindIsDispatchedNotForwarded(unittest.TestCase):
    """job commands must NOT reach PlayerbotAI::HandleCommand - "job quest" is
    not a mod-playerbots chat command, and forwarding it would be accepted
    and do nothing, exactly the voice.py 'sell junk' failure."""

    def test_job_is_excluded_from_the_bot_command_trigger_path(self):
        src = _code(_source())
        self.assertIn('kind != "job"', src)

    def test_job_is_dispatched_to_do_job(self):
        src = _code(_source())
        self.assertIn('kind == "job"', src)
        self.assertIn("DoJob(player, command, status)", src)

    def test_do_job_validates_against_the_known_modes(self):
        body = _do_job()
        self.assertIn("JobModes()", body)
        self.assertIn("unknown job mode", body)

    def test_do_job_writes_the_roster_column_not_a_strategy(self):
        body = _code(_do_job())
        self.assertIn("UPDATE overseer_roster SET job", body)
        self.assertNotIn("ChangeStrategy", body)
        self.assertNotIn("HandleCommand", body)


class TheMigrationMatchesWhatTheModuleReads(unittest.TestCase):
    def test_the_migration_exists(self):
        self.assertTrue(MIGRATION.exists(), MIGRATION)

    def test_it_adds_the_column_the_module_selects(self):
        # infra#2981 then infra#2983: a redaction-only comment edit changed
        # this file's hash without changing the statement, and AzerothCore's
        # updater reapplied an unconditional ADD COLUMN against a database
        # that already had it - crash-looping db-import. `ADD COLUMN IF NOT
        # EXISTS` was tried first and confirmed LIVE to be a genuine MySQL
        # syntax error on this exact pipeline's server (8.4.11) despite
        # documentation suggesting it should be supported - so the guard is
        # now the version-independent INFORMATION_SCHEMA + PREPARE/EXECUTE
        # idiom instead, and this asserts the unconditional ALTER text is
        # still in there (inside the dynamic-SQL string), not gone missing.
        text = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("INFORMATION_SCHEMA.COLUMNS", text)
        self.assertIn("PREPARE add_job_column_stmt FROM", text)
        self.assertIn("ALTER TABLE `overseer_roster` ADD COLUMN `job`", text)

    def test_the_default_matches_the_python_side(self):
        text = MIGRATION.read_text(encoding="utf-8")
        self.assertIn(f"DEFAULT '{jobs.DEFAULT}'", text)

    def test_the_width_matches_the_python_side(self):
        text = MIGRATION.read_text(encoding="utf-8")
        self.assertIn(f"VARCHAR({jobs.COLUMN_WIDTH})", text)

    def test_it_alters_rather_than_recreating_the_table(self):
        text = MIGRATION.read_text(encoding="utf-8")
        self.assertTrue(text.strip().upper().startswith("--"))
        self.assertIn("ALTER TABLE `overseer_roster`", text)


if __name__ == "__main__":
    unittest.main()

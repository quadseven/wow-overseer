"""infra#2912: a death recorded with its context, at the moment it happens.

`acore_characters` is saved every fifteen minutes (PlayerSaveInterval=900000).
Twice on 2026-08-26 the family drifted into a lethal zone with nothing
pointing there, and by the time anyone looked at the database the state that
would have explained it - what was steering the character, how its health had
been trending, who actually killed it - was already gone. mod_overseer.cpp
answers this with `overseer_death`: one un-coalesced row per death, built
entirely from state the module's other drives were already computing, written
by the world thread only.

The C++ here is compiled only on a push to `main`, so - same as
test_schema_degrade.py, test_quest_aim.py and test_travel_npc.py before it -
this is a contract test over the source TEXT, checked against the actual
pinned core (mod-playerbots/azerothcore-wotlk, Playerbot branch,
efe123fab543c5faf3c477674ec17a18fd59f09f) rather than asserted from memory.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
MIGRATION = (ROOT / "docker/azerothcore-playerbots/mod-overseer/data/sql/characters"
             "/base/2026_08_26_02_overseer_death.sql")


def _source() -> str:
    return MODULE.read_text(encoding="utf-8")


def _migration() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _migrations() -> str:
    """Every migration that touches `overseer_death`, concatenated.

    The base file creates the table; later files ALTER it. #235 added sixteen
    attribution columns in `2026_09_05_02_overseer_death_context.sql`, and a
    check that read only the base CREATE TABLE would report them missing from
    a schema that in fact has them. Globbing rather than listing means the
    next migration is covered without editing this test."""
    return chr(10).join(
        path.read_text(encoding="utf-8")
        for path in sorted(MIGRATION.parent.glob("*overseer_death*.sql")))


def _function(signature: str) -> str:
    """The whole of a function or method, braces balanced, starting from the
    first occurrence of `signature`. `signature` only needs to be enough text
    to be unique in the file - it does not need to be the whole declaration,
    which is useful here because several of these span more than one line."""
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
    """The same text with // comments stripped, so a column or call named
    only in prose does not read as a column selected or a function called."""
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _record_death():
    return _function("void RecordDeath(Player* player)")


def _remember_killer():
    return _function("void RememberKiller(")


def _remember_health():
    return _function("void RememberHealth(")


def _remember_aim():
    return _function("void RememberAim(")


def _flush_deaths():
    return _function("void FlushDeaths()")


def _on_player_just_died():
    return _function("void OnPlayerJustDied(Player* player) override")


def _on_pvp_kill():
    return _function("void OnPlayerPVPKill(Player* killer, Player* killed) override")


def _on_killed_by_creature():
    return _function(
        "void OnPlayerKilledByCreature(Creature* killer, Player* killed) override")


# Every function this module lets a death HOOK reach must have none of these
# in its own body. A missing one here is the exact failure mode #2891/#2819
# already taught this codebase to fear: a query from the map thread is a
# stall and a race (DatabaseWorkerPool::EscapeString has no lock of its own -
# see the file header), and this table's whole reason to exist is not to make
# the thing it was built to diagnose worse.
_DB_CALLS = ("CharacterDatabase.Execute", "CharacterDatabase.Query")


class DeathHooksDoNoDatabaseWork(unittest.TestCase):
    """RecordDeath and the two kill-capture hooks run on whatever thread
    Unit::Kill / Player::Update happen to be on for the dying character - a
    map-update thread, per this file's own threading discipline (see the
    file header comment: event hooks "do NO database work... the world
    thread does the INSERT"). This is the property that keeps a bad hook in
    the death path from being able to make the worldserver's segfault
    problem (infra#2891) worse."""

    def test_record_death_touches_no_database(self):
        body = _code(_record_death())
        for call in _DB_CALLS:
            self.assertNotIn(call, body, "RecordDeath must not query or write")

    def test_remember_killer_touches_no_database(self):
        body = _code(_remember_killer())
        for call in _DB_CALLS:
            self.assertNotIn(call, body)

    def test_remember_health_touches_no_database(self):
        body = _code(_remember_health())
        for call in _DB_CALLS:
            self.assertNotIn(call, body)

    def test_remember_aim_touches_no_database(self):
        body = _code(_remember_aim())
        for call in _DB_CALLS:
            self.assertNotIn(call, body)

    def test_the_pvp_kill_hook_only_remembers(self):
        body = _code(_on_pvp_kill())
        self.assertIn("RememberKiller(", body)
        for call in _DB_CALLS:
            self.assertNotIn(call, body)

    def test_the_killed_by_creature_hook_only_remembers(self):
        body = _code(_on_killed_by_creature())
        self.assertIn("RememberKiller(", body)
        for call in _DB_CALLS:
            self.assertNotIn(call, body)

    def test_none_of_the_hooks_can_null_deref(self):
        """Every capture point takes a raw pointer handed in by the core.
        Conservative means null-checked before use, on every one - see the
        PR's own "must fail silently, never crash the death handler" rule."""
        for body in (_code(_record_death()), _code(_remember_killer()),
                     _code(_on_pvp_kill()), _code(_on_killed_by_creature())):
            self.assertIn("if (!", body)


class OnlyTheWorldThreadWritesTheTable(unittest.TestCase):
    """FlushDeaths is the one function allowed to know overseer_death exists
    as a table, and it must only ever be reachable from OnUpdate - the world
    thread - on its own timer, the same shape as FlushEvents and FlushChat."""

    def test_flush_deaths_does_the_insert(self):
        self.assertIn("INSERT INTO overseer_death", _code(_flush_deaths()))

    def test_only_flush_deaths_inserts_into_the_table(self):
        self.assertEqual(
            1, _code(_source()).count("INSERT INTO overseer_death"),
            "overseer_death must have exactly one writer")

    def test_flush_deaths_is_called_exactly_once_and_from_on_update(self):
        code = _code(_source())
        self.assertEqual(1, code.count("FlushDeaths();"))
        on_update = _function("void OnUpdate(uint32 diff) override")
        self.assertIn("FlushDeaths();", _code(on_update))

    def test_flush_deaths_runs_on_its_own_timer_not_piggybacked(self):
        """A death must not be able to wait behind the event queue's own
        cadence - see DEATH_FLUSH_MS's own comment for why."""
        code = _code(_source())
        self.assertIn("_deathTimer += diff;", code)
        self.assertIn("_deathTimer >= DEATH_FLUSH_MS", code)

    def test_record_death_never_calls_flush_deaths_directly(self):
        """The hook pushes to a queue and leaves; only OnUpdate drains it.
        A hook that flushed its own queue would be a hook doing database
        work under a different name."""
        self.assertNotIn("FlushDeaths", _code(_record_death()))


class TheKillerCaptureAnswersWho(unittest.TestCase):
    """OnPlayerJustDied's own signature has no killer parameter - by design,
    verified against the pinned core - so the two PVP-kill / killed-by-
    creature hooks exist purely to capture a name while Unit::Kill still has
    one, for OnPlayerJustDied to pick up moments later."""

    def test_both_kill_hooks_are_registered(self):
        ctor = _function('OverseerEventScript() : PlayerScript("OverseerEventScript", {')
        self.assertIn("PLAYERHOOK_ON_PVP_KILL", ctor)
        self.assertIn("PLAYERHOOK_ON_PLAYER_KILLED_BY_CREATURE", ctor)
        self.assertIn("PLAYERHOOK_ON_PLAYER_JUST_DIED", ctor)

    def test_creature_killer_carries_a_template_entry(self):
        """killer_entry is what lets a report GROUP BY "which mob" rather
        than text-matching a name that can collide across zones."""
        body = _code(_on_killed_by_creature())
        self.assertIn("killer->GetEntry()", body)
        self.assertIn('"creature"', body)

    def test_player_killer_carries_no_entry(self):
        body = _code(_on_pvp_kill())
        self.assertIn('"player"', body)

    def test_on_player_just_died_records_both_the_count_and_the_context(self):
        """overseer_event's hourly-bucketed 'death' count and overseer_death's
        per-death context are deliberately independent tables answering
        different questions - see the migration's own header - and this hook
        is the one place both get written, so they can never drift apart on
        which deaths either one saw."""
        body = _code(_on_player_just_died())
        self.assertIn('RecordEvent(player, "death"', body)
        self.assertIn("RecordDeath(player)", body)


class HealthAtDeathIsNeverTheLiveZero(unittest.TestCase):
    """Verified against the pinned core: Unit::setDeathState sets health to 0
    (called from Unit::Kill, itself called before every death hook this file
    uses can fire), so reading Player::GetHealth() inside any death hook
    always returns zero. RecordDeath must read the SAMPLED cache instead."""

    def test_record_death_reads_the_cached_reading_not_the_live_health(self):
        body = _code(_record_death())
        self.assertNotIn("player->GetHealth()", body)
        self.assertIn("g_hpHistory", body)

    def test_the_health_cache_is_fed_from_write_snapshot_not_a_new_poll(self):
        """No new per-tick hook was added to sample health; the existing
        five-second snapshot walk (WriteSnapshot, which already visits every
        online player) is reused instead."""
        snapshot = _code(_function("void WriteSnapshot()"))
        self.assertIn("RememberHealth(", snapshot)

    def test_the_aim_cache_is_fed_from_drive_quests_not_a_new_query(self):
        quests = _code(_function("void DriveQuests()"))
        self.assertIn("RememberAim(", quests)


class TheMigrationMatchesWhatTheCodeWrites(unittest.TestCase):
    """The classic trap this module has hit twice already (travel_npc,
    infra#2846; the enum-width traps in overseer_command/overseer_goal): the
    DDL and the C++ reader ship in different images and can disagree. Every
    column FlushDeaths' INSERT names must exist in the migration's CREATE
    TABLE, checked against the file rather than asserted."""

    INSERT_COLUMNS = (
        "character_name", "character_guid", "level", "map", "zone",
        "pos_x", "pos_y", "pos_z", "killer_type", "killer_name",
        "killer_entry", "health_at_death", "max_health_at_death",
        "seconds_since_full_health", "job", "quest_aim", "travel_target",
        "grouped", "group_size", "group_leader",
        # mod-overseer#235: what was actually moving the character. Added by
        # a SECOND migration rather than the base one, which is why
        # _migrations() below reads both - the base CREATE TABLE has no
        # opinion about these and never will.
        "driver", "movement_generator", "in_combat", "last_seen_seconds",
        "last_pos_x", "last_pos_y", "last_pos_z", "yards_fallen",
        "leader_seen", "leader_map", "leader_pos_x", "leader_pos_y",
        "leader_pos_z", "recovery_rung", "recovery_prev_rung",
        "recovery_seconds",
        # mod-overseer#281: WHY the fall baseline guard declined to look, as a
        # bitmask of every input that stood it down, plus how old that reading
        # is. The guard was proved not to be RUNNING rather than not working:
        # it polls once a second, so a baseline it had rebased could never be
        # more than one second of movement from the feet, and these deaths need
        # 69 or more yards. A mask of 0 means it looked and nothing declined it,
        # which is the reading that would refute that, and -1 in either column
        # means NOT SAMPLED rather than zero.
        "fall_guard_standdown", "fall_guard_seconds",
    )

    def test_migration_file_exists(self):
        self.assertTrue(MIGRATION.exists(), MIGRATION)

    def test_the_insert_names_exactly_these_columns_in_order(self):
        # The INSERT is built from several adjacent C++ string literals
        # (line-wrapped for readability), so the raw source still has the
        # closing/opening quote of each literal sitting between columns -
        # `"map, zone, ..."` becomes `" "map` once newlines are flattened.
        # Strip quotes before splitting, exactly as the compiler's own string
        # literal concatenation would.
        flush = _code(_flush_deaths()).replace("\n", " ").replace('"', "")
        match = re.search(r"INSERT INTO overseer_death \(([^)]*)\)", flush)
        self.assertIsNotNone(match)
        columns = tuple(c.strip() for c in match.group(1).split(","))
        self.assertEqual(self.INSERT_COLUMNS, columns)

    def test_every_inserted_column_exists_in_the_create_table(self):
        migration = _migrations()
        for column in self.INSERT_COLUMNS:
            self.assertIn("`%s`" % column, migration,
                          "%s is written by FlushDeaths but missing from the "
                          "migration" % column)

    def test_the_create_table_has_no_if_not_exists(self):
        """Matching overseer_event's own reasoning verbatim: dbimport tracks
        applied files by content hash, so IF NOT EXISTS would make a later
        edit to this file a silent no-op against a database that already ran
        it once."""
        migration = _migration()
        self.assertIn("CREATE TABLE `overseer_death` (", migration)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS `overseer_death`", migration)

    def test_retention_is_swept_on_its_own_schedule(self):
        code = _code(_source())
        self.assertIn("DELETE FROM overseer_death", code)
        self.assertIn("DEATH_RETENTION_DAYS", code)


class OutOfScopeIsStatedNotJustTrue(unittest.TestCase):
    """This slice ships the recording mechanism in the module every realm's
    worldserver already runs; wiring it into the isolated hardcore realm or
    the live `wow` family's deployment is explicitly a separate change. The
    comment saying so has to actually be there, not merely be true."""

    def test_the_migration_states_the_deployment_is_out_of_scope(self):
        migration = _migration()
        self.assertIn("OUT OF SCOPE", migration)
        self.assertIn("live", migration.lower())

    def test_the_recording_path_names_no_namespace(self):
        """Database-level concern, not a k8s one: nothing in the capture or
        flush path should be gated on a namespace or realm name."""
        for body in (_record_death(), _remember_killer(), _flush_deaths()):
            code = _code(body)
            self.assertNotIn("namespace ==", code)
            self.assertNotIn("wow-hardcore", code)


if __name__ == "__main__":
    unittest.main()

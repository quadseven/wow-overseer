"""Guild-scale goals: a count or a drop-table item set (#1476, decided on #94).

WHERE THE FIXTURE ROWS COME FROM. overseer_goal rows are written here by
bridge._queue_guild_goal itself, the code that writes them in production. The
loot chain below (creature 10438 and Plans: Hammer of the Titans as a direct
row, Pattern: Mooncloth Leggings behind references 1085663 -> 1080003) and the
overseer_dungeon_run shape are a read-only read of the dev realm on 2026-10-31.
Character names are stand-ins; guild_member, character_spell and
character_inventory keep their real columns.
"""

import asyncio
import pathlib
import re
import sqlite3
import sys
import types
import unittest
from unittest import mock

import achievements
import agenda
import council
import goals
import priorities

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()

RECIPE = 9
RARE = 3
HAMMER, HAMMER_SPELL = 12833, 16988
LEGGINGS, LEGGINGS_SPELL = 14497, 18440
STRATHOLME = 329
BRD = 230


class _Cursor:
    """A DictCursor over sqlite, taking MySQL's %s placeholders."""

    def __init__(self, db):
        self.cur = db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args=()):
        self.cur.execute(sql.replace("%s", "?"), args)

    def fetchone(self):
        row = self.cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(row) for row in self.cur.fetchall()]

    @property
    def lastrowid(self):
        return self.cur.lastrowid

    @property
    def rowcount(self):
        return self.cur.rowcount


class _Conn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.db.commit()
        return False

    def cursor(self):
        return _Cursor(self.db)


def _world(db):
    """The drop tables, holding what the realm holds for these rows."""
    db.execute("ATTACH DATABASE ':memory:' AS acore_world")
    db.execute(
        "CREATE TABLE acore_world.creature_loot_template (Entry, Item, Reference)"
    )
    db.execute(
        "CREATE TABLE acore_world.reference_loot_template (Entry, Item, Reference)"
    )
    db.execute("CREATE TABLE acore_world.creature_template (entry, lootid)")
    db.execute("CREATE TABLE acore_world.creature (guid, id, map)")
    db.execute(
        "CREATE TABLE acore_world.item_template "
        "(entry, name, class, Quality, spellid_2)"
    )
    db.executemany(
        "INSERT INTO acore_world.creature_template VALUES (?, ?)",
        [(10438, 10438), (9999, 9999)],
    )
    db.executemany(
        "INSERT INTO acore_world.creature VALUES (?, ?, ?)",
        [(54240, 10438, STRATHOLME), (1, 9999, BRD)],
    )
    db.executemany(
        "INSERT INTO acore_world.creature_loot_template VALUES (?, ?, ?)",
        [
            (10438, HAMMER, 0),  # direct
            (10438, 3, 1085663),  # behind two references
            (10438, 11111, 0),  # the wrong quality
            (10438, 22222, 0),  # the wrong class
            (9999, 33333, 0),  # the right kind, another dungeon
        ],
    )
    db.executemany(
        "INSERT INTO acore_world.reference_loot_template VALUES (?, ?, ?)",
        [(1085663, 3, 1080003), (1080003, LEGGINGS, 0)],
    )
    db.executemany(
        "INSERT INTO acore_world.item_template VALUES (?, ?, ?, ?, ?)",
        [
            (HAMMER, "Plans: Hammer of the Titans", RECIPE, RARE, HAMMER_SPELL),
            (LEGGINGS, "Pattern: Mooncloth Leggings", RECIPE, RARE, LEGGINGS_SPELL),
            (11111, "A green recipe", RECIPE, 2, 1),
            (22222, "A rare sword", 2, RARE, 2),
            (33333, "Another dungeon's recipe", RECIPE, RARE, 3),
        ],
    )


def _characters(db):
    db.execute("CREATE TABLE guild (guildid, name)")
    db.execute("CREATE TABLE guild_member (guildid, guid)")
    db.execute("CREATE TABLE characters (guid, name)")
    db.execute("CREATE TABLE character_spell (guid, spell)")
    db.execute("CREATE TABLE character_inventory (guid, item)")
    db.execute("CREATE TABLE item_instance (guid, itemEntry)")
    db.execute(
        "CREATE TABLE overseer_dungeon_run "
        "(id INTEGER PRIMARY KEY, leader_name, map_id, outcome, ended_at)"
    )
    db.execute(
        "CREATE TABLE overseer_goal (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "character_name, kind, skill_name, target, quest_id DEFAULT 0, "
        "status DEFAULT 'active', channel_id DEFAULT '', last_report, "
        "guild DEFAULT '', item_set, started_at, completed_at)"
    )
    db.executemany("INSERT INTO guild VALUES (?, ?)", [(1, "Cave"), (2, "Other")])
    db.executemany(
        "INSERT INTO characters VALUES (?, ?)",
        [(1, "Alpha"), (2, "Beta"), (3, "Gamma")],
    )
    db.executemany("INSERT INTO guild_member VALUES (?, ?)", [(1, 1), (1, 2), (2, 3)])


def _db():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.create_function("NOW", 0, lambda: "2026-10-31 12:00:00")
    _world(db)
    _characters(db)
    return db


class _Store(unittest.TestCase):
    """bridge's own store adapters, over sqlite."""

    def setUp(self):
        self.db = _db()
        patcher = mock.patch.object(bridge, "_connect", lambda: _Conn(self.db))
        patcher.start()
        self.addCleanup(patcher.stop)

    def queue(self, text, name="Alpha"):
        return bridge._queue_guild_goal(name, goals.parse_goal(text), "7")

    def status(self, goal_id):
        return self.db.execute(
            "SELECT status FROM overseer_goal WHERE id = ?", (goal_id,)
        ).fetchone()["status"]

    def active(self, goal_id):
        return next(r for r in bridge._fetch_active_goals() if r["id"] == goal_id)


class ParseGuildGoal(unittest.TestCase):
    def test_a_count_sentence(self):
        self.assertEqual(
            goals.parse_goal("run BRD 50 times"),
            goals.GuildGoal(goals.GUILD_COUNT, "blackrock depths", target=50),
        )

    def test_an_item_set_sentence(self):
        self.assertEqual(
            goals.parse_goal("every rare recipe from Stratholme"),
            goals.GuildGoal(
                goals.GUILD_ITEMS, "stratholme", item_class=RECIPE, quality=RARE
            ),
        )

    def test_the_maps_own_sentences_name_their_guild(self):
        count = goals.parse_goal(
            "split the Cave guild into groups of five and run BRD 50 times"
        )
        self.assertEqual((count.guild, count.target), ("Cave", 50))
        items = goals.parse_goal(
            "make the Horde guild farm Stratholme until they have all the rare recipes"
        )
        self.assertEqual(
            (items.guild, items.instance, items.item_class, items.quality),
            ("Horde", "stratholme", RECIPE, RARE),
        )

    def test_a_sentence_naming_no_guild_leaves_it_to_the_store(self):
        self.assertEqual(goals.parse_goal("the guild runs strat").__class__, type(None))
        self.assertEqual(
            goals.parse_goal("the guild should run strat 3 times").guild, ""
        )

    def test_what_it_does_not_recognise_falls_through(self):
        for text in (
            "run to town 3 times",  # not an instance
            "run BRD 0 times",
            "every rare recipe from the auction house",
            "every shiny recipe from Stratholme",  # not a quality
            "what drops in Stratholme?",
            "hello there",
        ):
            self.assertIsNone(goals.parse_goal(text), text)

    def test_per_character_sentences_are_untouched(self):
        self.assertEqual(goals.parse_goal("reach level 20"), goals.Goal("level", 20))
        self.assertIsInstance(goals.parse_goal("forget the goal"), goals.CancelGoal)

    def test_every_instance_is_named_as_the_site_names_it(self):
        for map_id in goals.INSTANCE_MAPS.values():
            self.assertIn(map_id, achievements.MAP_NAMES)
        for name in achievements.MAP_NAMES.values():
            bare = name.lower().removeprefix("the ")
            self.assertIn(bare, goals.INSTANCE_MAPS)


class ItemSetQuery(_Store):
    def rows(self, map_id=STRATHOLME, item_class=RECIPE, quality=RARE):
        cur = _Cursor(self.db)
        cur.execute(bridge._GUILD_ITEM_SET_SQL, (map_id, item_class, quality, map_id))
        return cur.fetchall()

    def test_direct_and_nested_reference_drops_filtered_by_class_and_quality(self):
        self.assertEqual(
            self.rows(),
            [
                {"item": HAMMER, "spell": HAMMER_SPELL},
                {"item": LEGGINGS, "spell": LEGGINGS_SPELL},
            ],
        )

    def test_only_a_recipe_carries_a_spell_to_know(self):
        """spellid_2 on a weapon is a proc: knowing it proves nothing."""
        self.assertEqual(self.rows(item_class=2), [{"item": 22222, "spell": 0}])

    def test_the_named_instance_bounds_it(self):
        self.assertEqual([r["item"] for r in self.rows(map_id=BRD)], [33333])

    def test_queueing_stores_the_set_and_its_size_as_the_target(self):
        goal_id, goal = self.queue("every rare recipe from Stratholme")
        row = dict(
            self.db.execute(
                "SELECT * FROM overseer_goal WHERE id = ?", (goal_id,)
            ).fetchone()
        )
        self.assertEqual(goal.guild, "Cave")
        self.assertEqual((row["guild"], row["target"]), ("Cave", 2))
        self.assertEqual(
            goals.decode_item_set(row["item_set"]),
            {HAMMER: HAMMER_SPELL, LEGGINGS: LEGGINGS_SPELL},
        )

    def test_an_empty_set_is_refused_rather_than_met_at_once(self):
        goal_id, goal = self.queue("every epic weapon from Stratholme")
        self.assertEqual(goal_id, 0)
        self.assertIn("no epic weapon", goals.guild_refusal_text("Alpha", goal))
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) AS n FROM overseer_goal").fetchone()["n"],
            0,
        )

    def test_a_guild_that_does_not_exist_is_refused(self):
        goal_id, goal = self.queue("the Nobody guild should run BRD 5 times")
        self.assertEqual(goal_id, 0)
        self.assertIn("Nobody", goals.guild_refusal_text("Alpha", goal))

    def test_an_addressee_in_no_guild_is_refused(self):
        goal_id, goal = self.queue("run BRD 5 times", name="Stranger")
        self.assertEqual(goal_id, 0)
        self.assertIn("Stranger", goals.guild_refusal_text("Stranger", goal))


class Progress(_Store):
    def test_an_item_counts_when_any_one_member_knows_or_holds_it(self):
        self.assertEqual(
            goals.items_done(
                {1: 10, 2: 20, 3: 0, 4: 40},
                known_spells={10},  # one member knows the first
                held_items={2, 3},  # another holds the next two
            ),
            frozenset({1, 2, 3}),
        )

    def test_a_set_partly_known_by_different_members(self):
        goal_id, _ = self.queue("every rare recipe from Stratholme")
        bridge._admit_queued_goals()
        self.db.execute("INSERT INTO character_spell VALUES (1, ?)", (HAMMER_SPELL,))
        self.assertEqual(bridge._observe_goal(self.active(goal_id)), 1)

        self.db.execute("INSERT INTO character_inventory VALUES (2, 500)")
        self.db.execute("INSERT INTO item_instance VALUES (500, ?)", (LEGGINGS,))
        row = self.active(goal_id)
        self.assertEqual(bridge._observe_goal(row), 2)
        self.assertIsInstance(goals.reconcile(row, 2)[-1], goals.MarkComplete)

    def test_someone_outside_the_guild_counts_for_nothing(self):
        goal_id, _ = self.queue("every rare recipe from Stratholme")
        bridge._admit_queued_goals()
        self.db.execute("INSERT INTO character_spell VALUES (3, ?)", (HAMMER_SPELL,))
        self.db.execute("INSERT INTO character_inventory VALUES (3, 501)")
        self.db.execute("INSERT INTO item_instance VALUES (501, ?)", (LEGGINGS,))
        self.assertEqual(bridge._observe_goal(self.active(goal_id)), 0)

    def test_a_count_reads_finished_runs_since_the_goal_started(self):
        goal_id, _ = self.queue("run BRD 50 times")
        bridge._admit_queued_goals()
        before, after = "2026-10-31 11:00:00", "2026-10-31 12:30:00"
        self.db.executemany(
            "INSERT INTO overseer_dungeon_run "
            "(leader_name, map_id, outcome, ended_at) VALUES (?, ?, ?, ?)",
            [
                ("Alpha", BRD, "complete", after),  # counts
                ("Beta", BRD, "complete", after),  # counts
                ("Alpha", BRD, "complete", before),  # before the goal
                ("Alpha", BRD, "wipe", after),  # did not finish
                ("Alpha", STRATHOLME, "complete", after),  # elsewhere
                ("Gamma", BRD, "complete", after),  # another guild
            ],
        )
        self.assertEqual(bridge._observe_goal(self.active(goal_id)), 2)


class Queueing(_Store):
    def test_a_second_goal_for_a_busy_member_waits(self):
        first, _ = self.queue("run BRD 50 times", name="Alpha")
        second, _ = self.queue("every rare recipe from Stratholme", name="Beta")
        self.assertEqual(self.status(first), "queued")

        bridge._admit_queued_goals()
        self.assertEqual(self.status(first), "active")
        self.assertEqual(self.status(second), "queued")
        self.assertEqual([r["id"] for r in bridge._fetch_active_goals()], [first])

        bridge._admit_queued_goals()
        self.assertEqual(self.status(second), "queued")

    def test_the_queue_moves_when_the_running_goal_ends(self):
        first, _ = self.queue("run BRD 50 times")
        second, _ = self.queue("every rare recipe from Stratholme")
        bridge._admit_queued_goals()
        bridge._complete_goal(first)
        bridge._admit_queued_goals()
        self.assertEqual(self.status(second), "active")

    def test_another_guilds_goal_does_not_wait(self):
        first, _ = self.queue("run BRD 50 times", name="Alpha")
        other, _ = self.queue("run BRD 50 times", name="Gamma")
        bridge._admit_queued_goals()
        self.assertEqual({self.status(first), self.status(other)}, {"active"})

    def test_cancelling_reaches_a_goal_still_in_the_queue(self):
        goal_id, _ = self.queue("run BRD 50 times")
        self.assertEqual(bridge._cancel_goals("Alpha"), 1)
        self.assertEqual(self.status(goal_id), "cancelled")

    def test_first_come_first_served(self):
        rows = [
            {"id": 2, "guild": "Cave", "status": "queued"},
            {"id": 1, "guild": "Cave", "status": "queued"},
        ]
        self.assertEqual(goals.goals_to_start(rows, {"Cave": {"Alpha"}}), [1])

    def test_an_earlier_waiting_goal_keeps_its_place(self):
        """A goal behind a waiting one is not let past it on overlap alone."""
        rows = [
            {"id": 1, "guild": "Cave", "status": "active"},
            {"id": 2, "guild": "Cave", "status": "queued"},
            {"id": 3, "guild": "Other", "status": "queued"},
        ]
        members = {"Cave": {"Alpha", "Beta"}, "Other": {"Beta", "Gamma"}}
        self.assertEqual(goals.goals_to_start(rows, members), [])

    def test_the_supervisor_admits_before_it_reads_the_active_rows(self):
        src = pathlib.Path(bridge.__file__).read_text(encoding="utf-8")
        body = src.split("async def _supervise_goals", 1)[1].split("async def ", 1)[0]
        self.assertLess(
            body.index("_admit_queued_goals"), body.index("_fetch_active_goals")
        )


def _row(**over):
    row = {
        "id": 12,
        "character_name": "Alpha",
        "kind": goals.GUILD_COUNT,
        "skill_name": "blackrock depths",
        "target": 50,
        "quest_id": 0,
        "status": "active",
        "guild": "Cave",
        "item_set": None,
        "last_report": None,
    }
    row.update(over)
    return row


class Release(unittest.TestCase):
    def test_the_timeout_is_the_quest_drives_half_hour_at_the_goal_cadence(self):
        self.assertEqual(goals.QUEST_HOLD_SECONDS, 1800)
        self.assertEqual(bridge.LEVEL_AIM_SECONDS, goals.QUEST_HOLD_SECONDS)
        self.assertEqual(
            goals.GUILD_HOLD_CYCLES * bridge.GOAL_INTERVAL, goals.QUEST_HOLD_SECONDS
        )

    def test_no_progress_short_of_the_timeout_only_counts(self):
        last = goals.GUILD_HOLD_CYCLES - 2
        self.assertEqual(
            goals.reconcile(_row(last_report="3/%d" % last), 3),
            [goals.RecordProgress(12, 3, last + 1)],
        )

    def test_no_progress_past_the_timeout_releases_the_goal(self):
        last = goals.GUILD_HOLD_CYCLES - 1
        actions = goals.reconcile(_row(last_report="3/%d" % last), 3)
        self.assertIsInstance(actions[0], goals.Report)
        self.assertIsInstance(actions[-1], goals.ReleaseGoal)
        self.assertEqual(actions[-1].goal_id, 12)
        self.assertIn("Cave", actions[-1].reason)
        self.assertIn("blackrock depths", actions[-1].reason)
        self.assertIn("no progress", actions[-1].reason)

    def test_progress_clears_the_counter_and_is_said(self):
        actions = goals.reconcile(_row(last_report="3/9"), 4)
        self.assertEqual(actions[-1], goals.RecordProgress(12, 4, 0))
        self.assertIsInstance(actions[0], goals.MilestoneThought)
        self.assertIn("4 of 50", actions[0].text)

    def test_a_fall_is_not_progress(self):
        self.assertEqual(
            goals.reconcile(_row(last_report="3/9"), 2),
            [goals.RecordProgress(12, 2, 10)],
        )

    def test_the_goal_commands_nobody_until_a_drive_exists(self):
        """Running it unattended is the rest of map #88."""
        kinds = {type(a) for a in goals.reconcile(_row(), 0)}
        self.assertEqual(kinds, {goals.RecordProgress})

    def test_completion(self):
        actions = goals.reconcile(_row(last_report="49"), 50)
        self.assertIsInstance(actions[-1], goals.MarkComplete)
        self.assertIn("Cave", actions[1].text)

    def test_the_release_is_applied_and_logged_on_a_named_line(self):
        db = _db()
        db.execute(
            "INSERT INTO overseer_goal (id, character_name, kind, target) "
            "VALUES (12, 'Alpha', ?, 50)",
            (goals.GUILD_COUNT,),
        )
        action = goals.ReleaseGoal(12, "Cave, blackrock depths: no progress")
        with (
            mock.patch.object(bridge, "_connect", lambda: _Conn(db)),
            self.assertLogs(bridge.log, level="WARNING") as logs,
        ):
            asyncio.run(bridge.Bridge._goal_release(None, {"id": 12}, action))
        self.assertIn(
            "goal 12 released: Cave, blackrock depths: no progress", logs.output[0]
        )
        self.assertEqual(
            db.execute("SELECT status FROM overseer_goal").fetchone()["status"],
            "released",
        )


class _Schema:
    """The MySQL statements _ensure_goal_store sends, played against a table
    held as {column: type}. sqlite cannot read ENUM, ENGINE or AUTO_INCREMENT,
    so this applies the three statement shapes the store can emit."""

    def __init__(self, table=None):
        self.table = table
        self.ran = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, sql, args=()):
        self.ran.append(sql)
        if sql.startswith("CREATE TABLE IF NOT EXISTS"):
            if self.table is None:
                self.table = self._created(sql)
        elif sql.startswith("ALTER TABLE overseer_goal MODIFY "):
            column, kind = sql.split(" MODIFY ", 1)[1].split(" ", 1)
            self.table[column] = kind
        elif sql.startswith("ALTER TABLE overseer_goal ADD COLUMN "):
            column, kind = sql.split(" ADD COLUMN ", 1)[1].split(" ", 1)
            self.table[column] = kind

    def fetchall(self):
        wanted = re.findall(r"'(\w+)'", self.ran[-1].split("COLUMN_NAME IN", 1)[1])
        return [
            {"c": name, "t": kind}
            for name, kind in (self.table or {}).items()
            if name in wanted
        ]

    @staticmethod
    def _created(sql):
        body = sql.split("(", 1)[1].rsplit(") ENGINE", 1)[0]
        columns = re.split(r",\s(?=\w+ [A-Z])", body)
        table = {}
        for column in columns:
            name, kind = column.strip().split(" ", 1)
            if name not in ("PRIMARY", "KEY"):
                table[name] = kind.split(", PRIMARY KEY")[0]
        return table


class Migration(unittest.TestCase):
    LEGACY = {
        "id": "INT UNSIGNED",
        "kind": "enum('level','skill','quest','dungeon')",
        "quest_id": "int unsigned",
        "status": "enum('active','completed','cancelled')",
    }

    def ensure(self, schema):
        with mock.patch.object(bridge, "_connect", lambda: schema):
            bridge._ensure_goal_store()
        return schema

    def alters(self, schema):
        return [s for s in schema.ran if s.startswith("ALTER")]

    def test_from_scratch_the_create_alone_holds_everything(self):
        schema = self.ensure(_Schema())
        self.assertEqual(self.alters(schema), [])
        self.assertEqual(schema.table["kind"].split(" NOT")[0], goals.KIND_COLUMN[:-9])
        for kind in goals.GUILD_KINDS:
            self.assertIn("'%s'" % kind, schema.table["kind"])
        for status in ("queued", "released"):
            self.assertIn("'%s'" % status, schema.table["status"])
        for column in goals.GUILD_COLUMNS:
            self.assertIn(column, schema.table)

    def test_a_table_from_before_this_reaches_the_same_shape_once(self):
        schema = self.ensure(_Schema(dict(self.LEGACY)))
        self.assertEqual(len(self.alters(schema)), 5)
        for kind in goals.GUILD_KINDS:
            self.assertIn("'%s'" % kind, schema.table["kind"])
        self.assertIn("'released'", schema.table["status"])
        self.assertLessEqual(set(goals.GUILD_COLUMNS), set(schema.table))

        schema.ran.clear()
        self.ensure(schema)
        self.assertEqual(self.alters(schema), [])

    def test_new_enum_values_are_appended_so_stored_rows_keep_their_meaning(self):
        self.assertEqual(goals.GOAL_KINDS[:4], ("level", "skill", "quest", "dungeon"))
        self.assertEqual(goals.GOAL_STATUSES[:3], ("active", "completed", "cancelled"))

    def test_no_table_yet_means_nothing_to_alter(self):
        self.assertEqual(goals.guild_goal_migrations({}), [])


class Consumers(unittest.TestCase):
    def test_every_guild_kind_serves_a_priority(self):
        for kind in goals.GUILD_KINDS:
            self.assertIn(kind, priorities.GOAL_PRIORITY)

    def test_the_council_is_not_credited_with_a_guild_goal(self):
        guild = {"status": "active", "kind": goals.GUILD_COUNT, "character_name": "A"}
        level = {"status": "active", "kind": "level", "character_name": "A"}
        self.assertEqual(council._active([guild, level], None), [level])

    def test_the_banner_does_not_credit_the_council_with_a_guild_goal(self):
        row = _row(created_at=None)
        self.assertIsNone(agenda.orders([row], {}, None))

    def test_the_site_says_a_stored_guild_goal(self):
        self.assertEqual(
            goals._describe(goals.GUILD_COUNT, "blackrock depths", 50),
            "blackrock depths, 50 runs",
        )
        self.assertEqual(
            goals._describe(goals.GUILD_ITEMS, "stratholme", 19),
            "19 listed items from stratholme",
        )

    def test_the_acknowledgement_names_the_queue(self):
        goal = goals.GuildGoal(goals.GUILD_COUNT, "blackrock depths", 50, guild="Cave")
        text = goals.ack_text("Alpha", goal)
        self.assertIn("Cave", text)
        self.assertIn("queue", text)


if __name__ == "__main__":
    unittest.main()

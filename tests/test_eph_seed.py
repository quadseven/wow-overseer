"""The seed compiler and its guard: a decree becomes SQL that can only reach the world's own local database."""

import copy
import pathlib
import re
import unittest

from ephemeral import anchors as anchors_mod
from ephemeral import dbschema, guard, lint, resolve, sqlgen
from ephemeral.compiler import compile_seed
from ephemeral.miniyaml import loads
from ephemeral.sqlgen import Builder, NowPlus, SeedError, verify_statement

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = dbschema.Schema.load()
ANCHORS = anchors_mod.Anchors(
    {
        "good-spot": {
            "map": 1,
            "zone": 17,
            "x": 10.5,
            "y": -20.25,
            "z": 30.0,
            "o": 1.5,
            "provenance": {
                "source": "overseer_death",
                "ref": "row 1",
                "observed": "2026-01-01",
            },
        },  # fmt: skip
        "pending-spot": {"pending": True, "todo": "copy it"},
    }
)


class FakeResolver(resolve.Resolver):
    """A small in-memory world. Override the dicts per test."""

    def __init__(self):
        self.chars = {"Grug": 1, "Ugga": 2, "Zork": 3, "Uzza": 4}
        self.fam = {
            "grug": [(1, "Grug", True), (2, "Ugga", False)],
            "zug": [(4, "Uzza", True), (3, "Zork", False)],
        }
        self.guild = {("Cave", 164): [(2, "Ugga")]}
        self.creatures = {
            "Plugger Spazzring": [{"guid": 47703, "map": 230, "zone": 0, "x": 888.5, "y": -177.9, "z": -42.9, "o": 1.0}],
            "Twin": [{"guid": 1, "map": 0, "zone": 1, "x": 1.0, "y": 1.0, "z": 1.0, "o": 0.0}] * 2,
        }  # fmt: skip
        self.gameobjects = {}
        self.items_by_name = {
            "Copper Bar": [{"entry": 2840, "stackable": 20, "max_durability": 0}]
        }
        self.quest_titles = {"Lost Tools": [123]}
        self.yards = {
            0: [
                {"id": 5, "x": 0.0, "y": 0.0, "z": 5.0},
                {"id": 6, "x": 100.0, "y": 100.0, "z": 5.0},
            ]
        }
        self.used = {2: {23, 24}}
        self.flags = {}

    def characters(self, name):
        return [(self.chars[name], name)] if name in self.chars else []

    def family(self, family):
        return self.fam.get(family, [])

    def guild_role(self, guild, skill_id):
        return self.guild.get((guild, skill_id), [])

    def creature_spawns(self, name):
        return self.creatures.get(name, [])

    def gameobject_spawns(self, name):
        return self.gameobjects.get(name, [])

    def areatrigger(self, trigger_id):
        return (
            {"map": 0, "x": 4.0, "y": 5.0, "z": 6.0, "o": 0.0}
            if trigger_id == 9
            else None
        )

    def graveyard(self, graveyard_id):
        return None

    def graveyards_on_map(self, map_id):
        return self.yards.get(map_id, [])

    def items(self, name):
        return self.items_by_name.get(name, [])

    def quests(self, title):
        return self.quest_titles.get(title, [])

    def maxhealth(self, guid):
        return 4000

    def character(self, guid):
        return {"money": 5, "player_flags": self.flags.get(guid, 0)}

    def used_backpack_slots(self, guid):
        return self.used.get(guid, set())

    def backpack_items(self, guid):
        return [
            (slot, 9000 + slot)
            for slot in sorted(self.used.get(guid, set()))
            if 23 <= slot <= 38
        ]

    def max_item_guid(self):
        return 1000

    def max_instance_id(self):
        return 50

    def max_group_guid(self):
        return 7


BASE = """
decree: v1
id: seed-sample
proves:
  - {repo: owner/repo, issue: 5, criterion: "works"}
fix: {repo: owner/repo, commit: abcdef1}
world: {class: lean, image: follow-dev, bridge: off, random_bots: 0, config: {}}
runs: {control: 3, treatment: 3}
duration: 20m
cast:
  - who: Grug
    set: {at: {captured: good-spot}}
observe:
  - name: reached
    role: precondition
    when: end
    sql: "SELECT COUNT(*) FROM characters WHERE guid = @cast0"
    expect: {scalar: ">= 1"}
  - name: quiet
    role: check
    when: end
    sql: "SELECT character_name FROM overseer_death WHERE created_at >= @t0"
    expect: {rows: 0}
"""


def doc():
    return copy.deepcopy(loads(BASE))


def compile_(d, resolver=None):
    return compile_seed(d, resolver or FakeResolver(), SCHEMA, ANCHORS)


def sql_of(plan):
    return [s.sql for s in plan.statements]


class BuilderTest(unittest.TestCase):
    b = Builder(SCHEMA)

    def test_shapes(self):
        self.assertEqual(
            self.b.update("characters", {"level": 5}, {"guid": 1}).sql,
            "UPDATE `acore_characters`.`characters` SET `level` = 5 WHERE `guid` = 1",
        )
        self.assertEqual(
            self.b.delete("group_member", {"memberGuid": [1, 2]}).sql,
            "DELETE FROM `acore_characters`.`group_member` WHERE `memberGuid` IN (1, 2)",
        )
        self.assertIn(
            "UNIX_TIMESTAMP() + 60",
            self.b.insert("corpse", {"guid": 1, "time": NowPlus(60)}).sql,
        )

    def test_unknown_column_and_table(self):
        with self.assertRaises(SeedError):
            self.b.update("characters", {"levl": 5}, {"guid": 1})
        with self.assertRaises(SeedError):
            self.b.insert("no_such_table", {"a": 1})

    def test_roster_and_command_tables_are_never_written(self):
        for table in ("overseer_roster", "overseer_command"):
            with self.assertRaises(SeedError):
                self.b.update(table, {"job": "quest"}, {"name": "Grug"})
            with self.assertRaises(SeedError):
                verify_statement(
                    f"UPDATE `acore_characters`.`{table}` SET `job` = 'quest' WHERE `name` = 'Grug'",  # noqa: S608 - a statement the verifier must refuse
                    SCHEMA,
                )

    def test_no_where_refused(self):
        with self.assertRaises(SeedError):
            self.b.delete("characters", {})

    def test_string_values_are_restricted(self):
        for bad in ("x'; DROP TABLE characters; --", "a\\b", 'q"q'):
            with self.assertRaises(SeedError):
                sqlgen.quote(bad)

    def test_floats_never_use_exponents(self):
        self.assertNotIn("e", sqlgen.quote(0.00001))


class VerifyStatementTest(unittest.TestCase):
    def refused(self, sql):
        with self.assertRaises(SeedError):
            verify_statement(sql, SCHEMA)

    def test_good(self):
        self.assertTrue(
            verify_statement(
                "UPDATE `acore_characters`.`characters` SET `level` = 5 WHERE `guid` = 1",
                SCHEMA,
            )
        )

    def test_other_database_refused(self):
        self.refused(
            "UPDATE `acore_world`.`creature` SET `curhealth` = 1 WHERE `guid` = 1"
        )
        self.refused("DELETE FROM `acore_auth`.`account` WHERE `id` = 1")
        self.refused("UPDATE `mysql`.`user` SET `x` = 1 WHERE `y` = 1")

    def test_unqualified_or_odd_heads_refused(self):
        self.refused("UPDATE characters SET level = 5 WHERE guid = 1")
        self.refused("GRANT ALL ON *.* TO 'x'")
        self.refused("SELECT * FROM `acore_characters`.`characters` ")
        self.refused("DROP TABLE `acore_characters`.`characters` ")

    def test_stacked_commented_and_variable_refused(self):
        base = "UPDATE `acore_characters`.`characters` SET `level` = 5 WHERE `guid` = 1"
        self.refused(
            base + "; DELETE FROM `acore_characters`.`characters` WHERE `guid` = 2"  # noqa: S608 - a stacked statement the verifier must refuse
        )
        self.refused(base + " -- x")
        self.refused(base + " /* x */")
        self.refused(
            "UPDATE `acore_characters`.`characters` SET `level` = @x WHERE `guid` = 1"
        )

    def test_subselect_and_functions_refused(self):
        self.refused(
            "UPDATE `acore_characters`.`characters` SET `level` = (SELECT 1) WHERE `guid` = 1"
        )
        self.refused(
            "UPDATE `acore_characters`.`characters` SET `level` = SLEEP(9) WHERE `guid` = 1"
        )
        self.refused(
            "UPDATE `acore_characters`.`characters` SET `money` = LOAD_FILE('x') WHERE `guid` = 1"
        )

    def test_update_and_delete_need_where(self):
        self.refused("UPDATE `acore_characters`.`characters` SET `level` = 5 ")
        self.refused("DELETE FROM `acore_characters`.`characters` ")

    def test_unknown_column_refused(self):
        self.refused(
            "UPDATE `acore_characters`.`characters` SET `levl` = 5 WHERE `guid` = 1"
        )

    def test_quote_in_a_string_cannot_escape(self):
        self.refused(
            "UPDATE `acore_characters`.`characters` SET `name` = 'a' OR 1=1 -- ' WHERE `guid` = 1"
        )


class FakeConn:
    def __init__(self, marker_rows=1):
        self.marker_rows = marker_rows
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.connect_kwargs = None

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        if sql == guard.MARKER_SQL:
            self._row = (self.conn.marker_rows,)
        else:
            self.conn.executed.append(sql)

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []

    def close(self):
        pass


GOOD_INPUTS = guard.GuardInputs("127.0.0.1", "ephemeral", "grants: enabled")


class GuardTest(unittest.TestCase):
    def open(self, inputs=GOOD_INPUTS, conn=None):
        conn = conn or FakeConn()
        seen = {}

        def connect(**kw):
            seen.update(kw)
            return conn

        return guard.open_guarded(inputs, connect, SCHEMA), conn, seen

    def test_passes_and_connects_to_loopback(self):
        g, conn, seen = self.open()
        self.assertIsInstance(g, guard.GuardedConnection)
        self.assertEqual(seen["host"], "127.0.0.1")

    def test_every_non_loopback_host_is_refused_before_connecting(self):
        for host in (
            "localhost",
            "mysql",
            "mysql.example.invalid",
            "192.0.2.5",
            "127.0.0.2",
            "0.0.0.0",  # noqa: S104 - a host the guard must refuse
            "::1",
            "",
            "127.0.0.1 ",
        ):
            called = []
            with self.assertRaises(guard.GuardError, msg=host):
                guard.open_guarded(
                    guard.GuardInputs(host, "ephemeral", "grants: enabled"),
                    lambda *, _c=called, **kw: _c.append(kw),
                    SCHEMA,
                )
            self.assertEqual(called, [], host)

    def test_any_other_local_port_is_refused(self):
        for port in (3307, 33060, 0, 8085):
            called = []
            with self.assertRaises(guard.GuardError, msg=port):
                guard.open_guarded(
                    guard.GuardInputs(
                        "127.0.0.1", "ephemeral", "grants: enabled", port
                    ),
                    lambda *, _c=called, **kw: _c.append(kw),
                    SCHEMA,
                )
            self.assertEqual(called, [], port)

    def test_wrong_namespace_label_refused(self):
        for label in ("rehearsal", "", "dev"):
            with self.assertRaises(guard.GuardError):
                guard.open_guarded(
                    guard.GuardInputs("127.0.0.1", label, "grants: enabled"),
                    lambda **kw: FakeConn(),
                    SCHEMA,
                )

    def test_harness_must_enable_grants(self):
        with self.assertRaises(guard.GuardError):
            guard.open_guarded(
                guard.GuardInputs("127.0.0.1", "ephemeral", "grants: disabled"),
                lambda **kw: FakeConn(),
                SCHEMA,
            )

    def test_every_failure_is_reported_together(self):
        with self.assertRaises(guard.GuardError) as ctx:
            guard.open_guarded(
                guard.GuardInputs("mysql", "dev", ""), lambda **kw: FakeConn(), SCHEMA
            )
        self.assertEqual(str(ctx.exception).count(";"), 2)

    def test_marker_must_be_exactly_one_row(self):
        for rows in (0, 2):
            conn = FakeConn(rows)
            with self.assertRaises(guard.GuardError):
                guard.open_guarded(
                    GOOD_INPUTS, lambda *, _conn=conn, **kw: _conn, SCHEMA
                )
            self.assertTrue(conn.closed)

    def test_a_cursor_close_failure_cannot_report_failure_after_a_commit(self):
        class CloseBoom(FakeConn):
            armed = False

            def cursor(self):
                cur = super().cursor()

                def close():
                    if self.armed:
                        raise OSError("close failed")

                cur.close = close
                return cur

        conn = CloseBoom()
        g = guard.open_guarded(GOOD_INPUTS, lambda **kw: conn, SCHEMA)
        conn.armed = True
        conn.committed = False
        with self.assertRaises(OSError):
            g.run([Builder(SCHEMA).update("characters", {"level": 5}, {"guid": 1})])
        self.assertFalse(
            conn.committed, "a failure to close must come before any commit"
        )
        self.assertTrue(conn.rolled_back)

    def test_a_rollback_failure_does_not_mask_the_original_error(self):
        class RollbackBoom(FakeConn):
            def rollback(self):
                raise OSError("rollback failed")

        conn = RollbackBoom()
        g = guard.open_guarded(GOOD_INPUTS, lambda **kw: conn, SCHEMA)
        evil = sqlgen.Stmt(
            "update",
            "characters",
            "UPDATE `acore_characters`.`characters` SET `level` = 5 WHERE `guid` = 1",
        )
        conn.cursor = lambda: type(
            "C",
            (),
            {
                "execute": lambda s, q, p=(): (_ for _ in ()).throw(ValueError("boom")),
                "close": lambda s: None,
            },
        )()
        with self.assertRaises(ValueError):
            g.run([evil])

    def test_the_old_exposed_token_is_gone(self):
        self.assertFalse(hasattr(guard.GuardedConnection, "_token"))

    def test_a_hand_wrapped_connection_is_refused_everywhere(self):
        bare = object.__new__(guard.GuardedConnection)
        bare._conn = FakeConn()
        bare._schema = SCHEMA
        self.assertEqual(bare._conn.executed, [])
        with self.assertRaises(guard.GuardError):
            guard.apply_plan(compile_(doc()), bare)
        with self.assertRaises(guard.GuardError):
            bare.query("SELECT 1")
        self.assertEqual(bare._conn.executed, [])

    def test_the_minting_token_is_not_reachable_from_the_class(self):
        with self.assertRaises(guard.GuardError):
            guard.GuardedConnection(
                FakeConn(), SCHEMA, getattr(guard.GuardedConnection, "_mint", object())
            )

    def test_query_refuses_a_select_with_side_effects(self):
        g, _, _ = self.open()
        for sql in (
            "SELECT 1 INTO OUTFILE 'x'",
            "SELECT 1; SELECT 2",
            "SELECT SLEEP(5)",
            "SELECT 1 -- x",
            "SELECT guid FROM characters FOR UPDATE",
        ):
            with self.assertRaises(guard.GuardError, msg=sql):
                g.query(sql)

    def test_query_allows_the_fixed_templates(self):
        g, _, _ = self.open()
        for sql in resolve.QUERIES.values():
            g.query(sql, ("x",) * sql.count("%s"))

    def test_a_connection_cannot_be_built_by_hand(self):
        with self.assertRaises(guard.GuardError):
            guard.GuardedConnection(FakeConn(), SCHEMA, object())

    def test_apply_plan_needs_a_guarded_connection(self):
        with self.assertRaises(guard.GuardError):
            guard.apply_plan(compile_(doc()), FakeConn())

    def test_run_reverifies_a_hand_built_statement(self):
        g, conn, _ = self.open()
        evil = sqlgen.Stmt(
            "update",
            "creature",
            "UPDATE `acore_world`.`creature` SET `curhealth` = 1 WHERE `guid` = 1",
        )
        with self.assertRaises(SeedError):
            g.run([evil])
        self.assertEqual(conn.executed, [])

    def test_apply_executes_in_one_commit(self):
        g, conn, _ = self.open()
        plan = compile_(doc())
        self.assertEqual(guard.apply_plan(plan, g), len(plan.statements))
        self.assertEqual(conn.executed, sql_of(plan))
        self.assertTrue(conn.committed)

    def test_query_is_select_only(self):
        g, _, _ = self.open()
        with self.assertRaises(guard.GuardError):
            g.query("DELETE FROM x")

    def test_no_decree_can_change_where_sql_goes(self):
        """Whatever a decree says, every compiled statement passes the verifier."""
        d = doc()
        d["cast"][0]["set"].update(
            level=58,
            money=5,
            alive=True,
            health_pct=50,
            items=[{"name": "Copper Bar", "count": 45}],
        )
        d["cast"][0]["ceiling"] = "granted for the test"
        for stmt in compile_(d).statements:
            self.assertTrue(verify_statement(stmt.sql, SCHEMA))
            self.assertTrue(
                stmt.sql.startswith(
                    (
                        "INSERT INTO `acore_characters`.",
                        "REPLACE INTO `acore_characters`.",
                        "UPDATE `acore_characters`.",
                        "DELETE FROM `acore_characters`.",
                    )
                )
            )


class ResolverQueriesTest(unittest.TestCase):
    def test_every_template_names_real_tables_and_columns(self):
        for name, sql in resolve.QUERIES.items():
            self.assertEqual(
                dbschema.check_select(sql.replace("%s", "'x'"), SCHEMA), [], name
            )


class CompileTest(unittest.TestCase):
    def test_position_and_level(self):
        d = doc()
        d["cast"][0]["set"].update(level=58)
        d["cast"][0]["ceiling"] = "levels 56 to 60"
        plan = compile_(d)
        u = plan.statements[0].sql
        self.assertIn("`level` = 58", u)
        self.assertIn("`map` = 1", u)
        self.assertIn("`position_x` = 10.500000", u)
        self.assertIn("`zone` = 17", u)
        self.assertIn("WHERE `guid` = 1", u)

    def test_a_decree_that_does_not_lint_never_seeds(self):
        d = doc()
        d["cast"][0]["set"]["at"] = {"x": 1, "y": 2, "z": 3}
        with self.assertRaises(SeedError) as ctx:
            compile_(d)
        self.assertIn("does not lint", str(ctx.exception))

    def test_pending_anchor_is_refused(self):
        d = doc()
        d["cast"][0]["set"]["at"] = {"captured": "pending-spot"}
        with self.assertRaises(SeedError) as ctx:
            compile_(d)
        self.assertIn("pending", str(ctx.exception))

    def test_name_resolving_to_zero_or_several_is_invalid(self):
        d = doc()
        d["cast"][0]["set"]["at"] = {"creature": "Nobody"}
        with self.assertRaises(SeedError):
            compile_(d)
        d["cast"][0]["set"]["at"] = {"creature": "Twin"}
        with self.assertRaises(SeedError) as ctx:
            compile_(d)
        self.assertIn("2 rows", str(ctx.exception))

    def test_unknown_character_is_invalid(self):
        d = doc()
        d["cast"][0]["who"] = "Nobody"
        with self.assertRaises(SeedError):
            compile_(d)

    def test_instance_position_needs_an_arranged_instance(self):
        d = doc()
        d["cast"][0]["set"]["at"] = {"creature": "Plugger Spazzring"}
        with self.assertRaises(SeedError) as ctx:
            compile_(d)
        self.assertIn("arranges no instance", str(ctx.exception))

    def test_instance_group_and_bind(self):
        d = doc()
        d["cast"] = [
            {"who": "family:grug", "set": {"at": {"creature": "Plugger Spazzring"}}}
        ]
        d["arrange"] = [
            {
                "instance": {
                    "map": "Blackrock Depths",
                    "as": "brd",
                    "bind": "family:grug",
                }
            },
            {"group": {"members": "family:grug", "leader": "Grug"}},
        ]
        plan = compile_(d)
        sql = sql_of(plan)
        self.assertEqual(plan.variables["brd"], 51)
        self.assertTrue(any("`instance`" in s and "(51, 230" in s for s in sql))
        self.assertEqual(sum("`character_instance`" in s for s in sql), 2)
        self.assertTrue(
            any(
                "INSERT INTO `acore_characters`.`groups`" in s and "`leaderGuid`" in s
                for s in sql
            )
        )
        self.assertEqual(
            sum("`group_member`" in s and s.startswith("INSERT") for s in sql), 2
        )
        updates = [
            s for s in sql if s.startswith("UPDATE `acore_characters`.`characters`")
        ]
        self.assertTrue(
            all("`instance_id` = 51" in s and "`map` = 230" in s for s in updates)
        )
        self.assertEqual(plan.variables["cast"], "1, 2")
        self.assertEqual(plan.variables["Ugga"], 2)

    def test_a_repeated_instance_alias_is_invalid_even_if_lint_is_bypassed(self):
        d = doc()
        d["cast"][0]["set"] = {}
        d["arrange"] = [
            {"instance": {"map": "Blackrock Depths", "as": "brd"}},
            {"instance": {"map": "Molten Core", "as": "brd"}},
        ]
        with self.assertRaises(SeedError):
            compile_(d)

    def test_creature_dead_state_in_arrange(self):
        d = doc()
        d["cast"][0]["set"] = {}
        d["arrange"] = [
            {"instance": {"map": "Blackrock Depths", "as": "brd"}},
            {"creature": {"name": "Plugger Spazzring", "in": "brd", "state": "dead"}},
        ]
        sql = sql_of(compile_(d))
        self.assertTrue(
            any(
                s.startswith("REPLACE INTO `acore_characters`.`creature_respawn`")
                and "47703" in s
                and "`instanceId`" in s
                for s in sql
            )
        )

    def test_dead_member_gets_a_corpse_and_ghost_flag(self):
        d = doc()
        d["cast"][0]["who"] = "Zork"
        d["cast"][0]["set"] = {
            "alive": False,
            "corpse_at": {"captured": "good-spot"},
            "at": {"graveyard": "nearest"},
        }
        d["cast"][0]["ceiling"] = "nothing granted"
        sql = sql_of(compile_(d, self.fake_with_map1_yard()))
        self.assertTrue(
            any("`health` = 0" in s and "`playerFlags` = 16" in s for s in sql)
        )
        self.assertTrue(
            any(
                s.startswith("INSERT INTO `acore_characters`.`corpse`")
                and "`corpseType`" in s
                for s in sql
            )
        )
        self.assertTrue(
            any(s.startswith("DELETE FROM `acore_characters`.`corpse`") for s in sql)
        )

    @staticmethod
    def fake_with_map1_yard():
        r = FakeResolver()
        r.yards[1] = [{"id": 9, "x": 11.0, "y": -20.0, "z": 30.0}]
        return r

    def test_health_pct_uses_maxhealth(self):
        d = doc()
        d["cast"][0]["set"]["health_pct"] = 50
        self.assertIn("`health` = 2000", sql_of(compile_(d))[0])

    def test_a_previously_rewarded_quest_is_cleared_for_other_states(self):
        d = doc()
        d["cast"][0]["set"]["quests"] = {"Lost Tools": "incomplete", 55: "complete"}
        sql = sql_of(compile_(d))
        for qid in (123, 55):
            self.assertTrue(
                any(
                    s.startswith("DELETE")
                    and "`character_queststatus_rewarded`" in s
                    and f"`quest` = {qid}" in s
                    for s in sql
                )
            )

    def test_a_quoted_numeric_quest_key_is_an_id(self):
        d = doc()
        d["cast"][0]["set"]["quests"] = {"55": "rewarded"}
        sql = sql_of(compile_(d))
        self.assertTrue(
            any(
                "`character_queststatus_rewarded`" in s
                and "55" in s
                and s.startswith("REPLACE")
                for s in sql
            )
        )

    def test_skills_spells_quests_homebind(self):
        d = doc()
        d["cast"][0]["set"].update(
            skills={"Blacksmithing": {"value": 75, "max": 75}, "Mining": 10},
            spells_add=[2018],
            spells_remove=[99],
            quests={"Lost Tools": "incomplete", 55: "rewarded"},
            homebind={"captured": "good-spot"},
        )
        d["cast"][0]["ceiling"] = "test grants"
        plan = compile_(d)
        sql = sql_of(plan)
        self.assertTrue(
            any(
                "`character_skills`" in s
                and "`skill` = 164" not in s
                and "164, 75, 75" in s
                for s in sql
            )
        )
        self.assertTrue(
            any("`character_skills`" in s and "186, 10, 10" in s for s in sql)
        )
        self.assertTrue(any("`character_spell`" in s and "2018" in s for s in sql))
        self.assertTrue(
            any(
                s.startswith("DELETE FROM `acore_characters`.`character_spell`")
                for s in sql
            )
        )
        self.assertTrue(
            any("`character_queststatus`" in s and "123, 3" in s for s in sql)
        )
        self.assertTrue(
            any("`character_queststatus_rewarded`" in s and "55" in s for s in sql)
        )
        self.assertTrue(
            any("`character_homebind`" in s and "`zoneId`" in s for s in sql)
        )
        self.assertEqual(plan.variables["seed_skill_value"], 75)
        self.assertEqual(plan.variables["skill_blacksmithing"], 164)

    def test_items_split_stacks_and_take_free_slots(self):
        d = doc()
        d["cast"][0]["who"] = "Ugga"
        d["cast"][0]["set"]["items"] = [{"name": "Copper Bar", "count": 45}]
        d["cast"][0]["ceiling"] = "test grants"
        sql = sql_of(compile_(d))
        inst = [s for s in sql if "`item_instance`" in s]
        inv = [s for s in sql if "`character_inventory`" in s]
        self.assertEqual(len(inst), 3)  # 20 + 20 + 5
        self.assertTrue(inst[0].count("1001") == 1 and "2840" in inst[0])
        self.assertTrue(
            "`slot`" in inv[0] and ", 25, 1001)" in inv[0]
        )  # slots 23 and 24 are taken

    def test_no_free_slot_is_invalid(self):
        d = doc()
        d["cast"][0]["set"]["items"] = [{"name": "Copper Bar", "count": 1}]
        d["cast"][0]["ceiling"] = "test grants"
        r = FakeResolver()
        r.used[1] = set(range(23, 39))
        with self.assertRaises(SeedError):
            compile_(d, r)

    def test_free_backpack_slots_makes_room_from_the_top_and_then_the_grant_fits(self):
        d = doc()
        d["cast"][0]["set"]["free_backpack_slots"] = 2
        d["cast"][0]["set"]["items"] = [{"name": "Copper Bar", "count": 1}]
        d["cast"][0]["ceiling"] = "test grants"
        r = FakeResolver()
        r.used[1] = set(range(23, 39))  # a full backpack
        sql = sql_of(compile_(d, r))
        inv_del = [
            s
            for s in sql
            if s.startswith("DELETE FROM `acore_characters`.`character_inventory`")
        ]
        inst_del = [
            s
            for s in sql
            if s.startswith("DELETE FROM `acore_characters`.`item_instance`")
        ]
        self.assertEqual(len(inv_del), 2)
        self.assertIn("`slot` = 38", inv_del[0])
        self.assertIn("`slot` = 37", inv_del[1])
        self.assertIn("9038", inst_del[0])
        self.assertIn("9037", inst_del[1])
        # the grant lands in one of the slots just freed, not on top of an item
        grant = [
            s
            for s in sql
            if s.startswith("INSERT INTO `acore_characters`.`character_inventory`")
        ]
        self.assertTrue(any(", 37, " in g or ", 38, " in g for g in grant))
        # deletes come before the inserts
        self.assertLess(sql.index(inv_del[0]), sql.index(grant[0]))

    def test_free_backpack_slots_with_room_already_deletes_nothing(self):
        d = doc()
        d["cast"][0]["set"]["free_backpack_slots"] = 2
        d["cast"][0]["ceiling"] = "test world"
        sql = sql_of(compile_(d))
        self.assertFalse(
            [
                s
                for s in sql
                if s.startswith("DELETE FROM `acore_characters`.`character_inventory`")
            ]
        )

    def test_unknown_item_is_invalid(self):
        d = doc()
        d["cast"][0]["set"]["items"] = [{"name": "Nothing Real", "count": 1}]
        d["cast"][0]["ceiling"] = "test grants"
        with self.assertRaises(SeedError):
            compile_(d)

    def test_guild_role_picks_best_skill_and_says_so(self):
        d = doc()
        d["cast"][0]["who"] = "guild:Cave:blacksmith"
        plan = compile_(d)
        self.assertEqual(plan.members[0].name, "Ugga")
        self.assertTrue(any("resolved to Ugga" in n for n in plan.notes))

    def test_with_anchor_copies_another_members_position(self):
        d = doc()
        d["cast"] = [
            {"who": "Grug", "set": {"at": {"captured": "good-spot"}}},
            {"who": "Ugga", "set": {"at": {"with": "Grug"}}},
        ]
        sql = [s for s in sql_of(compile_(d)) if s.startswith("UPDATE")]
        self.assertEqual(len(sql), 2)
        self.assertIn("`position_x` = 10.500000", sql[1])

    def test_member_twice_in_cast_is_invalid(self):
        d = doc()
        d["cast"] = [
            {"who": "family:grug", "set": {"at": {"captured": "good-spot"}}},
            {"who": "family:grug", "set": {"alive": True}},
        ]
        with self.assertRaises(SeedError):
            compile_(d)

    def test_named_character_overrides_the_same_one_in_a_family(self):
        d = doc()
        d["cast"] = [
            {"who": "family:zug", "set": {"at": {"captured": "good-spot"}}},
            {"who": "Zork", "set": {"alive": True}},
        ]
        plan = compile_(d)
        self.assertEqual(
            [(m.cast_index, m.name) for m in plan.members], [(0, "Uzza"), (1, "Zork")]
        )

    def test_no_shipped_decree_plan_writes_a_roster_or_a_realm_id(self):
        d = doc()
        d["act"] = [{"at": "0s", "roster": {"who": "Grug", "job": "quest"}}]
        for s in sql_of(compile_(d)):
            self.assertNotIn("overseer_roster", s)
            self.assertNotIn("realm", s.lower())

    def test_render_is_plain_sql(self):
        text = compile_(doc()).render()
        self.assertTrue(text.rstrip().endswith(";"))


class ExampleDecreesTest(unittest.TestCase):
    """The shipped decrees compile against a world that has what they name."""

    def load(self, name):
        return loads((ROOT / "data" / "decrees" / name).read_text(encoding="utf-8"))

    def test_guzzler_compiles_and_does_not_seed_plugger_dead(self):
        plan = compile_seed(
            self.load("brd-guzzler-exit-zero-patron-deaths.yaml"),
            FakeResolver(),
            SCHEMA,
            anchors_mod.Anchors.load(),
        )
        sql = sql_of(plan)
        self.assertFalse(any("`creature_respawn`" in s for s in sql))
        self.assertTrue(any("`instance`" in s for s in sql))
        self.assertEqual(plan.variables["brd"], 51)

    def test_void_death_is_refused_while_its_anchors_are_pending(self):
        with self.assertRaises(SeedError) as ctx:
            compile_seed(
                self.load("void-death-recovers.yaml"),
                FakeResolver(),
                SCHEMA,
                anchors_mod.Anchors.load(),
            )
        self.assertIn("pending", str(ctx.exception))

    def test_profession_decree_is_refused_until_the_trainer_is_named(self):
        with self.assertRaises(SeedError):
            compile_seed(
                self.load("profession-rank-up-at-75.yaml"),
                FakeResolver(),
                SCHEMA,
                anchors_mod.Anchors.load(),
            )

    def test_profession_decree_compiles_with_a_real_trainer(self):
        d = self.load("profession-rank-up-at-75.yaml")
        d["cast"][0]["set"]["at"] = {"creature": "Twin Trainer"}
        r = FakeResolver()
        r.creatures["Twin Trainer"] = [
            {"guid": 9, "map": 0, "zone": 12, "x": 1.0, "y": 2.0, "z": 3.0, "o": 0.0}
        ]
        plan = compile_seed(d, r, SCHEMA, anchors_mod.Anchors.load())
        self.assertEqual(plan.variables["money_start"], 20000)
        self.assertEqual(plan.variables["seed_skill_max"], 75)
        self.assertTrue(any("`item_instance`" in s for s in sql_of(plan)))


class LintCoversTheWholeLoopTest(unittest.TestCase):
    def test_lint_sees_the_same_rules_the_compiler_relies_on(self):
        d = doc()
        d["cast"][0]["who"] = "guild:Cave:wizard"
        self.assertTrue(
            [f for f in lint.lint_document(d, ANCHORS, SCHEMA) if f.level == "error"]
        )


if __name__ == "__main__":
    unittest.main()


class ScriptedConn:
    """A connection that answers the seed step's own reads."""

    def __init__(self):
        self.executed = []
        self.commits = 0

    def cursor(self):
        return ScriptedCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


class ScriptedCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def execute(self, sql, params=()):
        from ephemeral import seedrun

        if sql == guard.MARKER_SQL:
            self.rows = [(1,)]
        elif sql == seedrun.LIVE_SCHEMA_SQL:
            self.rows = [
                (db, t, c)
                for db, ts in SCHEMA.tables.items()
                for t, cols in ts.items()
                for c in cols
            ]
        elif sql == resolve.QUERIES["characters"]:
            self.rows = [(1, "Grug")]
        elif sql == resolve.QUERIES["character"]:
            self.rows = [(5, 0)]
        elif sql.startswith(("INSERT", "REPLACE", "UPDATE", "DELETE")):
            self.conn.executed.append(sql)
        else:
            self.rows = []

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class SeedRunTest(unittest.TestCase):
    ENV = {
        "EPH_MYSQL_HOST": "127.0.0.1",
        "EPH_WORLD_LABEL": "ephemeral",
        "EPH_HARNESS_GRANTS": "grants: enabled",
    }

    def files(self, tmp):
        d = pathlib.Path(tmp)
        (d / "decree.yaml").write_text(BASE, encoding="utf-8")
        (d / "anchors.yaml").write_text(
            "anchors:\n  good-spot:\n    map: 1\n    zone: 17\n    x: 10.5\n    y: -20.25\n    z: 30.0\n    o: 1.5\n"
            "    provenance: {source: overseer_death, ref: row 1, observed: 2026-01-01}\n",
            encoding="utf-8",
        )
        return str(d / "decree.yaml"), str(d / "anchors.yaml")

    def run_seed(self, env, dry_run=False):
        import tempfile

        from ephemeral import seedrun

        out = []
        conn = ScriptedConn()
        calls = []

        def connect(**kw):
            calls.append(kw)
            return conn

        with tempfile.TemporaryDirectory() as tmp:
            decree, anchors = self.files(tmp)
            rc = seedrun.run(
                decree,
                env,
                dry_run=dry_run,
                anchors_path=anchors,
                connect=connect,
                out=out.append,
            )
        return rc, conn, calls, "\n".join(out)

    def test_applies_through_the_guard(self):
        rc, conn, calls, text = self.run_seed(self.ENV)
        self.assertEqual(rc, 0, text)
        self.assertEqual(calls[0]["host"], "127.0.0.1")
        self.assertEqual(len(conn.executed), 1)
        self.assertEqual(conn.commits, 1)

    def test_a_real_run_leaves_the_judge_its_handoff(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "handoff.json"
            rc, _, _, text = self.run_seed({**self.ENV, "EPH_VARS_FILE": str(path)})
            self.assertEqual(rc, 0, text)
            doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("cast", doc["variables"])
        self.assertEqual(doc["members"][0]["name"], "Grug")

    def test_a_dry_run_leaves_no_handoff(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "handoff.json"
            self.run_seed({**self.ENV, "EPH_VARS_FILE": str(path)}, dry_run=True)
            self.assertFalse(path.exists())

    def test_dry_run_applies_nothing(self):
        rc, conn, _, _ = self.run_seed(self.ENV, dry_run=True)
        self.assertEqual((rc, conn.executed, conn.commits), (0, [], 0))

    def test_foreign_host_is_invalid_and_never_connected(self):
        for host in ("mysql", "localhost", "198.51.100.7"):
            rc, conn, calls, text = self.run_seed({**self.ENV, "EPH_MYSQL_HOST": host})
            self.assertEqual(rc, 3, host)
            self.assertEqual(calls, [], host)
            self.assertIn("guard refused", text)

    def test_a_refused_connection_is_invalid_not_a_traceback(self):
        import tempfile

        from ephemeral import seedrun

        def refuse(**kw):
            raise ConnectionRefusedError("secret-password-must-not-print")

        out = []
        with tempfile.TemporaryDirectory() as tmp:
            decree, anchors = self.files(tmp)
            rc = seedrun.run(
                decree, self.ENV, anchors_path=anchors, connect=refuse, out=out.append
            )
        text = chr(10).join(out)
        self.assertEqual(rc, 3)
        self.assertIn("ConnectionRefusedError", text)
        self.assertNotIn("secret-password", text)

    def test_a_database_error_mid_seed_is_invalid_and_rolls_back(self):
        import tempfile

        from ephemeral import seedrun

        class Boom(ScriptedConn):
            def cursor(self):
                cur = super().cursor()
                real = cur.execute

                def execute(sql, params=()):
                    if sql.startswith("UPDATE"):
                        raise OSError("lost connection")
                    return real(sql, params)

                cur.execute = execute
                return cur

        conn = Boom()
        conn.rolled_back = False
        conn.rollback = lambda: setattr(conn, "rolled_back", True)
        out = []
        with tempfile.TemporaryDirectory() as tmp:
            decree, anchors = self.files(tmp)
            rc = seedrun.run(
                decree,
                self.ENV,
                anchors_path=anchors,
                connect=lambda **kw: conn,
                out=out.append,
            )
        self.assertEqual(rc, 3)
        self.assertTrue(conn.rolled_back)
        self.assertEqual(conn.commits, 0)
        self.assertIn("OSError", chr(10).join(out))

    def run_with(self, conn):
        import tempfile

        from ephemeral import seedrun

        out = []
        with tempfile.TemporaryDirectory() as tmp:
            decree, anchors = self.files(tmp)
            rc = seedrun.run(
                decree,
                self.ENV,
                anchors_path=anchors,
                connect=lambda **kw: conn,
                out=out.append,
            )
        return rc, chr(10).join(out)

    def test_a_close_failure_after_a_clean_run_is_invalid_not_a_traceback(self):
        class CloseBoom(ScriptedConn):
            def close(self):
                raise OSError("close failed")

        rc, text = self.run_with(CloseBoom())
        self.assertEqual(rc, 3)
        self.assertIn("OSError", text)
        self.assertNotIn("Traceback", text)

    def test_a_close_failure_after_a_refusal_is_still_invalid(self):
        class CloseBoom(ScriptedConn):
            def close(self):
                raise OSError("close failed")

        rc, text = self.run_with(CloseBoom())
        self.assertEqual(rc, 3)

    def test_a_rollback_failure_mid_seed_is_invalid_and_commits_nothing(self):
        class Boom(ScriptedConn):
            def cursor(self):
                cur = super().cursor()
                real = cur.execute

                def execute(sql, params=()):
                    if sql.startswith("UPDATE"):
                        raise OSError("lost connection")
                    return real(sql, params)

                cur.execute = execute
                return cur

            def rollback(self):
                raise OSError("rollback failed")

        conn = Boom()
        rc, text = self.run_with(conn)
        self.assertEqual(rc, 3)
        self.assertEqual(conn.commits, 0)
        self.assertIn("OSError", text)

    def test_a_junk_port_is_invalid_not_a_crash(self):
        rc, _, calls, text = self.run_seed({**self.ENV, "EPH_MYSQL_PORT": "not-a-port"})
        self.assertEqual((rc, calls), (3, []))
        self.assertIn("EPH_MYSQL_PORT", text)

    def test_missing_label_is_invalid(self):
        env = {k: v for k, v in self.ENV.items() if k != "EPH_WORLD_LABEL"}
        rc, _, calls, _ = self.run_seed(env)
        self.assertEqual((rc, calls), (3, []))


class NoDeploymentNamesTest(unittest.TestCase):
    def test_no_internal_hostname_in_the_package_example_or_tests(self):
        words = ["wow" + "-dev", "\." + "svc\b", "e" + "humps", "cluster" + "\.local"]
        bad = re.compile("|".join(words))
        files = [
            *(ROOT / "ephemeral").glob("*.py"),
            *(ROOT / "tests").glob("test_eph_*.py"),
        ]
        files.append(ROOT / "data" / "ephemeral" / "config.example.env")
        files.append(ROOT / "docs" / "EPHEMERAL.md")
        for path in files:
            self.assertIsNone(bad.search(path.read_text(encoding="utf-8")), path.name)

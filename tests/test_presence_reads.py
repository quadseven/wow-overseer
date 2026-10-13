"""Presence-facing SQL must derive online state from the fresh snapshot."""

import ast
import pathlib
import re
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

from apiv2 import presence  # noqa: E402
import guildjobs  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "bridge.py",
    *sorted((ROOT / "apiv2").glob("*.py")),
    ROOT / "map_server.py",
]


def sql_literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if re.search(r"\b(?:SELECT|FROM|JOIN)\b", value, re.I):
                yield value


class TestPresenceReads(unittest.TestCase):
    def test_character_online_columns_are_not_selected(self):
        for path in FILES:
            with self.subTest(path=path.name):
                for sql in sql_literals(path):
                    self.assertNotRegex(sql, r"\b[a-z][a-z0-9_]*\.online\b")

    def test_shared_join_defines_the_snapshot_window(self):
        join = presence.snapshot_join("c", "p")
        self.assertIn("p.name = c.name", join)
        self.assertIn(f"INTERVAL {presence.FRESH_SECONDS} SECOND", join)
        self.assertIn(
            "(s.name IS NOT NULL) AS online", (ROOT / "bridge.py").read_text()
        )

    def test_guild_jobs_snapshot_member_is_eligible_for_gear(self):
        source = (ROOT / "bridge.py").read_text(encoding="utf-8")
        sql = source[
            source.index("_JOB_MEMBERS_SQL = (") : source.index("_JOB_SKILLS_SQL = (")
        ]
        self.assertIn("(s.name IS NOT NULL) AS online", sql)
        self.assertIn('v2_presence.snapshot_join("c", "s")', sql)
        # Every job decision, including gear, consumes the projected snapshot
        # value on the member row.
        gear_candidates = (ROOT / "guildjobs.py").read_text(encoding="utf-8")
        body = gear_candidates[gear_candidates.index("def gear_candidates(") :]
        body = body[: body.index("\ndef ", 1)]
        self.assertIn("if m.online", body)
        self.assertIn("guildjobs.gear_candidates(members, recent)", source)

        # This models the SQL result row: the snapshot projection says online
        # even when the saved characters.online value would be zero.
        member = guildjobs.Member(
            name="Member",
            guild="Guild",
            role=guildjobs.MAINTENANCE,
            online=True,
            map_id=0,
            x=1.0,
            y=1.0,
        )
        step = types.SimpleNamespace(said="buys gear")
        with mock.patch.object(guildjobs, "gear_step", return_value=(step, "")) as gear:
            selected = guildjobs.gear_candidates([member], [])
            self.assertEqual(selected, [member])
            result = guildjobs._gear_first(member, ({}, []), [], 500)
        gear.assert_called_once()
        self.assertIs(result[0], step)


def _bridge_function(name):
    tree = ast.parse((ROOT / "bridge.py").read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
    )
    ns = {}
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
    return ns[name]


class TestWorldCounts(unittest.TestCase):
    def test_fresh_snapshot_members_count_in_the_world(self):
        world_counts = _bridge_function("_world_counts")

        def member(name, guild, online):
            return guildjobs.Member(
                name=name,
                guild=guild,
                role=guildjobs.MAINTENANCE,
                online=online,
                map_id=0,
                x=1.0,
                y=1.0,
            )

        members = [
            member("Fresh", "Cave", True),
            member("Stale", "Cave", False),
            member("Other", "Bonkers", True),
        ]
        self.assertEqual(world_counts(members), {"Cave": [1, 2], "Bonkers": [1, 1]})
        self.assertIn(
            "sorted(_world_counts(members).items())",
            (ROOT / "bridge.py").read_text(encoding="utf-8"),
        )

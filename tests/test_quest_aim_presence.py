"""A quest goal does not aim a family that is not in the world here (#56).

The failure: a family moved to another realm and left its roster rows behind
on this one. The quest goal's lease kept writing drive_quest onto those rows
every renewal, because `_holders_of` reads character_queststatus, which a
logged-out character keeps forever. The aim "landed" and no bot ever read it.

These tests run the bridge's own functions (extracted from bridge.py by name)
against fakes; none touches a database.
"""

import ast
import asyncio
import pathlib
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _load(names, namespace):
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = info


class _MySQLError(Exception):
    pass


_PYMYSQL = types.SimpleNamespace(err=types.SimpleNamespace(MySQLError=_MySQLError))


def _drive(holders, present, quest_id=14, beneficiary="Hero"):
    """Run _goal_drive_quest once; (aim calls, log lines)."""
    aims, log = [], _Log()
    ns = _load(
        ["_goal_drive_quest"],
        {
            "asyncio": asyncio,
            # No campaign owns the job: the quest goal path proper.
            "_cohort_of": lambda name: None,
            "_queue_owns_job": lambda family, dungeon: False,
            "_aim_family_quest": lambda *a: (_ for _ in ()).throw(
                AssertionError("the campaign stand-down ran with no campaign")
            ),
            "_holders_of": lambda qid: set(holders),
            "_in_world_of": lambda names: present,
            "_aim_traveller": lambda qid: aims.append(qid) or len(holders),
            "log": log,
        },
    )
    asyncio.run(
        ns["_goal_drive_quest"](
            types.SimpleNamespace(),
            {"id": 1},
            types.SimpleNamespace(quest_id=quest_id, beneficiary=beneficiary),
        )
    )
    return aims, log.lines


class AQuestGoalAimsOnlyAFamilyThatIsHere(unittest.TestCase):
    HOLDERS = {"Hero", "Sidekick", "Healer"}

    def test_holders_who_are_all_away_are_not_aimed(self):
        aims, lines = _drive(self.HOLDERS, present=set())
        self.assertNotIn(14, aims, "quest 14 was aimed at a family not in the world")

    def test_their_stale_aim_is_cleared_instead(self):
        aims, lines = _drive(self.HOLDERS, present=set())
        self.assertEqual([0], aims)
        self.assertTrue(any("stands down" in line for line in lines), lines)
        self.assertFalse(
            any("aiming the party at quest 14" in line for line in lines), lines
        )

    def test_one_holder_in_the_world_keeps_the_aim_as_before(self):
        aims, lines = _drive(self.HOLDERS, present={"Sidekick"})
        self.assertEqual([14], aims)
        self.assertTrue(
            any("aiming the party at quest 14" in line for line in lines), lines
        )

    def test_unread_presence_carries_on_exactly_as_before(self):
        aims, _ = _drive(self.HOLDERS, present=None)
        self.assertEqual([14], aims)

    def test_no_holders_is_left_to_the_aim_itself(self):
        # _aim_traveller already clears everyone when nobody holds the quest.
        aims, _ = _drive(set(), present=set())
        self.assertEqual([14], aims)


class _Cursor:
    def __init__(self, rows=(), error=None):
        self.rows, self.error, self.calls = list(rows), error, []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), list(params)))
        if self.error is not None:
            raise self.error

    def fetchall(self):
        return list(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _in_world(names, rows=(), error=None):
    cur = _Cursor(rows, error)
    ns = _load(["_in_world_of"], {"_connect": lambda: _Conn(cur), "pymysql": _PYMYSQL})
    return ns["_in_world_of"](names), cur.calls


class ReadingWhoIsInTheWorld(unittest.TestCase):
    def test_presence_is_a_fresh_snapshot_row(self):
        got, calls = _in_world(["Healer", "Hero"], rows=[{"name": "Hero"}])
        self.assertEqual({"Hero"}, got)
        sql, params = calls[0]
        self.assertIn("FROM overseer_snapshot", sql)
        self.assertIn("updated_at > NOW() - INTERVAL 60 SECOND", sql)
        self.assertNotIn("online", sql)
        self.assertEqual(["Healer", "Hero"], params)

    def test_nobody_fresh_is_an_empty_set(self):
        got, _ = _in_world(["Hero"], rows=[])
        self.assertEqual(set(), got)

    def test_no_names_asks_nothing(self):
        got, calls = _in_world([])
        self.assertEqual(set(), got)
        self.assertEqual([], calls)

    def test_a_missing_table_is_unread_not_absent(self):
        got, _ = _in_world(["Hero"], error=_MySQLError(1146, "no such table"))
        self.assertIsNone(got)

    def test_any_other_database_error_is_raised(self):
        with self.assertRaises(_MySQLError):
            _in_world(["Hero"], error=_MySQLError(2013, "lost connection"))


if __name__ == "__main__":
    unittest.main()

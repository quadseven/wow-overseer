"""A class asker's refused road survives a bridge restart (#2071).

Board.refuse_road keeps (quest, level, map) so a member whose road was refused
for good is not asked for again until the road changes. That memory was only in
the bridge process, so every deploy cost one more ask for each such member.
`bridge._PersistentRoads` keeps it in the bridge memo store. These tests run its
real source against a fake store, the way test_bridge_clock_memos does.
"""

import ast
import json
import pathlib
import types
import unittest

import classparty

SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
TREE = ast.parse(SOURCE)


class Store:
    def __init__(self):
        self.rows = {}

    def upsert(self, kind, subject, value, since, expires):
        self.rows[kind, subject] = (json.loads(json.dumps(value)), since, expires)

    def read(self, kind):
        return {s: (v[0], v[1]) for (k, s), v in self.rows.items() if k == kind}

    def delete(self, kind, subject):
        self.rows.pop((kind, subject), None)


def _roads_class(store):
    names = ("_memo_job", "_PersistentRoads", "ROAD_MEMO_SECONDS")
    nodes = [
        n
        for n in TREE.body
        if getattr(n, "name", None) in names
        or (
            isinstance(n, ast.Assign)
            and any(getattr(t, "id", None) in names for t in n.targets)
        )
    ]
    ns = {
        "time": types.SimpleNamespace(time=lambda: 1_000_000.0),
        "log": types.SimpleNamespace(exception=lambda *a: None),
        "_memo_upsert": store.upsert,
        "_memo_read": store.read,
        "_memo_delete": store.delete,
        "_MEMO_WRITER": types.SimpleNamespace(submit=lambda fn, *a: fn(*a)),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
    return ns["_PersistentRoads"]


def _run(level=20, map_id=1, quest=1476):
    return types.SimpleNamespace(
        leader="Bigzug",
        quest=quest,
        level=level,
        map_id=map_id,
        route_context={},
    )


def _help(level=20, map_id=1, quest=1476):
    return types.SimpleNamespace(
        member="Bigzug",
        level=level,
        map_id=map_id,
        move=types.SimpleNamespace(quest=quest),
    )


def _mate(name="Chill", level=19, map_id=1):
    return types.SimpleNamespace(
        name=name,
        member=types.SimpleNamespace(level=level, map_id=map_id),
    )


def _process(store):
    """A new bridge process: a board whose roads are restored from the store."""
    roads = _roads_class(store)()
    roads.restore()
    return classparty.Board(roads=roads)


class ARefusedRoadSurvivesARestart(unittest.TestCase):
    def test_a_refused_road_is_written_to_the_memo_store(self):
        store = Store()
        _process(store).refuse_road(_run())
        self.assertEqual(store.rows["class_road", "Bigzug"][0], [1476, 20, 1])

    def test_a_new_process_still_holds_the_member_back(self):
        store = Store()
        _process(store).refuse_road(_run())
        self.assertEqual(_process(store).road_refused([_help()]), {"Bigzug"})

    def test_a_helper_road_refusal_is_restored_after_restart(self):
        store = Store()
        run = _run()
        run.route_context = {"Chill": (19, 1)}
        _process(store).refuse_road(run, ("Chill",))

        self.assertEqual(store.rows["class_road", "Chill"][0], [1476, 19, 1])
        self.assertEqual(
            _process(store).road_refused_helpers([_mate()]),
            {1476: frozenset({"Chill"})},
        )

    def test_a_new_level_after_the_restart_lets_the_member_ask(self):
        store = Store()
        _process(store).refuse_road(_run())
        board = _process(store)
        self.assertEqual(board.road_refused([_help(level=21)]), set())
        self.assertEqual(store.rows, {})

    def test_a_new_map_or_quest_after_the_restart_lets_the_member_ask(self):
        store = Store()
        _process(store).refuse_road(_run())
        self.assertEqual(_process(store).road_refused([_help(map_id=0)]), set())
        _process(store).refuse_road(_run())
        self.assertEqual(_process(store).road_refused([_help(quest=1)]), set())

    def test_the_same_road_refused_again_writes_nothing_new(self):
        store = Store()
        board = _process(store)
        board.refuse_road(_run())
        store.rows.clear()
        board.refuse_road(_run())
        self.assertEqual(store.rows, {})

    def test_a_board_with_no_store_still_works(self):
        board = classparty.Board()
        board.refuse_road(_run())
        self.assertEqual(board.road_refused([_help()]), {"Bigzug"})

    def test_the_bridge_gives_the_board_the_persistent_roads_and_restores_them(self):
        self.assertIn("roads=self._class_roads", SOURCE)
        self.assertIn('"_class_roads"', SOURCE)


if __name__ == "__main__":
    unittest.main()

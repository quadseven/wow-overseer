"""GET /api/v2/run?id=N: one guild run by id, whenever it ran.

The run page only looked among the runs /api/guildruns answers (out now, and
the last thirty back), so every older run the chronicle links to said "Not
found". This reads the one row, shaped as /api/guildruns shapes a run.
"""

import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
from apiv2._context import Context  # noqa: E402

ROW = {
    "id": 398,
    "guild": "Cave",
    "band": "20-25",
    "composition": "1-1-3",
    "keyword": "deadmines",
    "tank": "Grug",
    "members": "Grug:tank:warrior:24,Ugga:healer:priest:23,Og:damage:mage:23",
    "state": "ended",
    "outcome": "cleared",
    "why": "",
    "deaths": 2,
    "seconds_inside": 3300,
    "bosses_done": 7,
    "bosses_total": 7,
    "loot_items": 9,
    "loot_notable": 2,
    "ilvl_gained": 14,
    "levels_gained": 3,
    "created_at": "2026-10-08 10:00:00",
    "ended_at": "2026-10-08 11:00:00",
}


class Server:
    """The two map server helpers the endpoint uses, recorded."""

    def __init__(self, rows):
        self.rows = rows
        self.sql = []
        self.storied = []

    def _wide_guarded(self, cur, sql, params, _fallback, _what):
        self.sql.append((sql, params))
        return self.rows

    def _guild_run_stories(self, cur, runs):
        self.storied.extend(r["id"] for r in runs)
        for r in runs:
            r["story"] = "a story"
        return runs


class Conn:
    def __init__(self):
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        self.closed = True


def ask(value, rows=(ROW,)):
    server = Server(list(rows))
    conns = []

    def connect():
        conns.append(Conn())
        return conns[-1]

    code, payload = apiv2.handle(
        "/api/v2/run",
        {"id": [value]} if value is not None else {},
        Context(connect=connect, server=server),
    )
    return code, payload, server, conns


class OneRun(unittest.TestCase):
    def test_an_old_run_is_read_by_its_id_and_shaped_like_the_list(self):
        code, payload, server, conns = ask("398")
        self.assertEqual(code, 200)
        run = payload["run"]
        self.assertEqual(run["id"], 398)
        self.assertEqual(run["guild"], "Cave")
        self.assertEqual([m["name"] for m in run["members"]], ["Grug", "Ugga", "Og"])
        self.assertEqual(
            run["members"][0],
            {"name": "Grug", "seat": "tank", "class": "warrior", "level": 24},
        )
        self.assertEqual(run["story"], "a story")
        self.assertEqual(server.sql[0][1], (398,))
        self.assertIn("WHERE id = %s LIMIT 1", server.sql[0][0])
        self.assertTrue(conns[0].closed)

    def test_a_run_still_inside_has_no_story_read(self):
        inside = dict(ROW, state="inside", outcome="")
        code, payload, server, _ = ask("398", rows=(inside,))
        self.assertEqual(code, 200)
        self.assertEqual(server.storied, [])

    def test_an_unknown_id_is_a_404(self):
        code, payload, _, conns = ask("12345", rows=())
        self.assertEqual(code, 404)
        self.assertTrue(conns[0].closed)

    def test_anything_but_a_positive_number_is_refused_before_a_query(self):
        for bad in (
            None,
            "",
            "0",
            "-1",
            "1e3",
            "12a",
            "398; DROP",
            "12345678901",
            chr(0x663) + chr(0x669) + chr(0x668),  # Arabic-Indic digits
        ):
            code, _payload, server, conns = ask(bad)
            self.assertEqual(code, 400, bad)
            self.assertEqual(conns, [], bad)
            self.assertEqual(server.sql, [], bad)


class TheRunPageAsksForIt(unittest.TestCase):
    def test_the_run_view_falls_back_to_the_one_run_read(self):
        src = (HERE / "app" / "views" / "run.js").read_text(encoding="utf-8")
        self.assertIn('"/api/v2/run?id=" + encodeURIComponent(', src)


if __name__ == "__main__":
    unittest.main()

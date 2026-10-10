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


class Conn:
    """A connection whose cursor answers the run read with `rows` and every
    story read (deaths, bosses) with none, recording each statement."""

    def __init__(self, rows):
        self.rows = rows
        self.sql = []
        self.closed = False
        self._last = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.sql.append((sql, tuple(params)))
        self._last = self.rows if "FROM overseer_guild_run" in sql else []

    def fetchall(self):
        return [dict(r) for r in self._last]

    def close(self):
        self.closed = True

    def reads(self, table):
        return [s for s in self.sql if "FROM " + table in s[0]]


def ask(value, rows=(ROW,)):
    conns = []

    def connect():
        conns.append(Conn(list(rows)))
        return conns[-1]

    code, payload = apiv2.handle(
        "/api/v2/run",
        {"id": [value]} if value is not None else {},
        Context(connect=connect, server=None),
    )
    return code, payload, conns


class OneRun(unittest.TestCase):
    def test_an_old_run_is_read_by_its_id_and_shaped_like_the_list(self):
        code, payload, conns = ask("398")
        self.assertEqual(code, 200)
        run = payload["run"]
        self.assertEqual(run["id"], 398)
        self.assertEqual(run["guild"], "Cave")
        self.assertEqual([m["name"] for m in run["members"]], ["Grug", "Ugga", "Og"])
        self.assertEqual(
            run["members"][0],
            {"name": "Grug", "seat": "tank", "class": "warrior", "level": 24},
        )
        self.assertTrue(run["story"].startswith("Cleared The Deadmines"))
        self.assertEqual(run["run_state"], "cleared")
        ((sql, params),) = conns[0].reads("overseer_guild_run")
        self.assertEqual(params, (398, 1))
        self.assertIn("WHERE id IN (%s) ORDER BY id DESC LIMIT %s", sql)
        self.assertTrue(conns[0].closed)

    def test_a_run_still_inside_has_no_story_read(self):
        inside = dict(ROW, state="inside", outcome="")
        code, payload, conns = ask("398", rows=(inside,))
        self.assertEqual(code, 200)
        self.assertEqual(conns[0].reads("overseer_death"), [])
        self.assertNotIn("story", payload["run"])

    def test_an_unknown_id_is_a_404(self):
        code, payload, conns = ask("12345", rows=())
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
            code, _payload, conns = ask(bad)
            self.assertEqual(code, 400, bad)
            self.assertEqual(conns, [], bad)


class TheRunPageAsksForIt(unittest.TestCase):
    def test_the_run_view_falls_back_to_the_one_run_read(self):
        src = (HERE / "app" / "views" / "run.js").read_text(encoding="utf-8")
        self.assertIn('"/api/v2/run?id=" + encodeURIComponent(', src)


if __name__ == "__main__":
    unittest.main()

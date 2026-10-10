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
import guildrun  # noqa: E402
import realmread  # noqa: E402
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


def ask(value, rows=(ROW,)):
    """The handler over a reader that knows the run read and the story's
    reads (deaths, bosses, their levels) and nothing else."""
    rd = realmread.Memory(
        {
            guildrun._RUN_SQL: list(rows),
            guildrun._DEATHS_SQL: [],
            guildrun.BOSSES_SQL: [],
            guildrun.BOSS_LEVELS_SQL: [],
        }
    )
    code, payload = apiv2.handle(
        "/api/v2/run",
        {"id": [value]} if value is not None else {},
        Context(read=rd, server=None),
    )
    return code, payload, rd


def reads(rd, table):
    return [(sql, params) for sql, params in rd.asked if "FROM " + table in sql]


class OneRun(unittest.TestCase):
    def test_an_old_run_is_read_by_its_id_and_shaped_like_the_list(self):
        code, payload, rd = ask("398")
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
        ((sql, params),) = reads(rd, "overseer_guild_run")
        self.assertEqual(params, (398, 1))
        self.assertIn("WHERE id IN (%s) ORDER BY id DESC LIMIT %s", sql)

    def test_a_run_still_inside_has_no_story_read(self):
        inside = dict(ROW, state="inside", outcome="")
        code, payload, rd = ask("398", rows=(inside,))
        self.assertEqual(code, 200)
        self.assertEqual(reads(rd, "overseer_death"), [])
        self.assertNotIn("story", payload["run"])

    def test_an_unknown_id_is_a_404(self):
        code, payload, rd = ask("12345", rows=())
        self.assertEqual(code, 404)
        self.assertEqual(len(rd.asked), 1)

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
            code, _payload, rd = ask(bad)
            self.assertEqual(code, 400, bad)
            self.assertEqual(rd.asked, [], bad)


class TheRunPageAsksForIt(unittest.TestCase):
    def test_the_run_view_falls_back_to_the_one_run_read(self):
        src = (HERE / "app" / "views" / "run.js").read_text(encoding="utf-8")
        self.assertIn('"/api/v2/run?id=" + encodeURIComponent(', src)


if __name__ == "__main__":
    unittest.main()

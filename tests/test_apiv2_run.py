"""GET /api/v2/run?id=N: one guild run by id, whenever it ran.

The run page only looked among the runs /api/guildruns answers (out now, and
the last thirty back), so every older run the chronicle links to said "Not
found". This reads the one row, shaped as /api/guildruns shapes a run.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
import guildrun  # noqa: E402
from apiv2 import run as run_api  # noqa: E402
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


# The Deadmines' kill-credit rows as acore_world.instance_encounters and
# creature_template answer them: seven encounters, Sneed's Shredder not one.
DEADMINES_WORLD = [
    {"encounter": 161, "entry": 644, "name": "Rhahk'Zor"},
    {"encounter": 162, "entry": 643, "name": "Sneed"},
    {"encounter": 163, "entry": 1763, "name": "Gilnid"},
    {"encounter": 164, "entry": 646, "name": "Mr. Smite"},
    {"encounter": 165, "entry": 645, "name": "Cookie"},
    {"encounter": 166, "entry": 647, "name": "Captain Greenskin"},
    {"encounter": 167, "entry": 639, "name": "Edwin VanCleef"},
]
BLACKFATHOM_WORLD = [
    {"encounter": 219, "entry": 4887, "name": "Ghamoo-ra"},
    {"encounter": 220, "entry": 4831, "name": "Lady Sarevess"},
    {"encounter": 221, "entry": 6243, "name": "Gelihast"},
    {"encounter": 222, "entry": 12902, "name": "Lorgus Jett"},
    {"encounter": 224, "entry": 4830, "name": "Old Serra'kis"},
    {"encounter": 225, "entry": 4832, "name": "Twilight Lord Kelris"},
    {"encounter": 226, "entry": 4829, "name": "Aku'mai"},
]


def _answer(rows):
    """`rows` as a list, or a schema gap code (an int) as it is."""
    return rows if isinstance(rows, int) else list(rows)


def ask(
    value,
    rows=(ROW,),
    event_rows=(),
    council_rows=(),
    boss_kill_rows=(),
    death_rows=(),
    boss_list_rows=DEADMINES_WORLD,
):
    """The handler over a reader that knows the run read and the story's
    reads (deaths, bosses, their levels) and nothing else."""
    rd = realmread.Memory(
        {
            guildrun._RUN_SQL: list(rows),
            guildrun._DEATHS_SQL: [],
            guildrun.BOSSES_SQL: [],
            guildrun.BOSS_LEVELS_SQL: [],
            run_api._EVENT_GEAR_SQL.format(names="%s, %s, %s"): _answer(event_rows),
            run_api._COUNCIL_GEAR_SQL.format(names="%s, %s, %s"): _answer(council_rows),
            run_api._BOSS_KILLS_SQL.format(names="%s, %s, %s"): _answer(boss_kill_rows),
            run_api._BOSS_DEATHS_SQL.format(names="%s, %s, %s"): _answer(death_rows),
            run_api._BOSS_LIST_SQL: _answer(boss_list_rows),
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


def boss_list_reads(rd):
    """The endpoint's own boss list reads (the story reads the table too)."""
    return [(sql, params) for sql, params in rd.asked if "ie.entry IN" in sql]


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
        self.assertEqual(run["gear"], [])
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

    def test_gear_reads_only_seats_on_the_dungeon_map_and_inside_the_run(self):
        _code, payload, rd = ask("398")
        self.assertEqual(payload["run"]["gear"], [])
        event_sql, event_params = next(
            (sql, params) for sql, params in rd.asked if "FROM overseer_event" in sql
        )
        self.assertIn("character_name IN (%s, %s, %s)", event_sql)
        self.assertIn("map = %s", event_sql)
        self.assertIn("last_seen >= %s", event_sql)
        self.assertIn("last_seen <= COALESCE(%s, NOW())", event_sql)
        self.assertEqual(
            event_params,
            ("Grug", "Ugga", "Og", 36, "2026-10-08 10:00:00", "2026-10-08 11:00:00"),
        )
        council_sql, council_params = next(
            (sql, params)
            for sql, params in rd.asked
            if "FROM overseer_loot_council" in sql
        )
        self.assertIn("recipient IN (%s, %s, %s)", council_sql)
        self.assertEqual(
            council_params,
            (
                "Grug",
                "Ugga",
                "Og",
                "deadmines",
                "2026-10-08 10:00:00",
                "2026-10-08 11:00:00",
            ),
        )

    def test_seated_items_are_shaped_newest_first_with_their_source(self):
        events = [
            {
                "member": "Grug",
                "entry": 100,
                "name": "Old Blade",
                "quality": 3,
                "kind": "item_loot",
                "at": "2026-10-08 10:10:00",
            },
            {
                "member": "Ugga",
                "entry": 101,
                "name": "New Staff",
                "quality": 4,
                "kind": "item_equip",
                "at": "2026-10-08 10:50:00",
            },
        ]
        awards = [
            {
                "member": "Og",
                "entry": 102,
                "name": "Council Ring",
                "quality": 3,
                "outcome": "given",
                "at": "2026-10-08 10:30:00",
            },
        ]
        _code, payload, _rd = ask("398", event_rows=events, council_rows=awards)
        self.assertEqual(
            [(g["member"], g["name"], g["source"]) for g in payload["run"]["gear"]],
            [
                ("Ugga", "New Staff", "equipped"),
                ("Og", "Council Ring", "won by loot council"),
                ("Grug", "Old Blade", "looted"),
            ],
        )

    def test_an_event_row_without_kind_reads_as_looted_not_a_crash(self):
        bare = {"member": "Grug", "entry": 100, "name": "Old Blade", "quality": 3}
        code, payload, _rd = ask("398", event_rows=[bare])
        self.assertEqual(code, 200)
        self.assertEqual(
            [(g["name"], g["source"]) for g in payload["run"]["gear"]],
            [("Old Blade", "looted")],
        )

    def test_a_run_without_a_keyword_answers_no_gear_and_reads_none(self):
        for keyword in (None, ""):
            _code, payload, rd = ask("398", rows=(dict(ROW, keyword=keyword),))
            self.assertEqual(payload["run"]["gear"], [])
            self.assertEqual(reads(rd, "overseer_event"), [])
            self.assertEqual(reads(rd, "overseer_loot_council"), [])

    def test_a_bare_view_without_a_keyword_answers_no_gear(self):
        view = {"members": [{"name": "Grug"}], "created_at": "", "ended_at": ""}
        self.assertEqual(run_api._gear(realmread.Memory({}), view), [])

    def test_a_realm_without_the_gear_tables_or_columns_answers_no_gear(self):
        for gap in (realmread.MISSING_TABLE, realmread.MISSING_COLUMN):
            with self.subTest(gap=gap):
                code, payload, _rd = ask("398", event_rows=gap, council_rows=gap)
                self.assertEqual(code, 200)
                self.assertEqual(payload["run"]["gear"], [])

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


class TheBosses(unittest.TestCase):
    def test_the_run_lists_bosses_in_order_with_kill_state_and_time(self):
        kills = [
            {
                "member": "Grug",
                "entry": 644,
                "name": "Rhahk'Zor",
                "at": "2026-10-08 10:12:00",
            },
            {
                "member": "Ugga",
                "entry": 643,
                "name": "Sneed",
                "at": "2026-10-08 10:28:00",
            },
        ]
        two_down = dict(ROW, outcome="wiped", bosses_done=2)
        code, payload, _rd = ask("398", rows=(two_down,), boss_kill_rows=kills)
        self.assertEqual(code, 200)
        bosses = payload["run"]["bosses"]
        self.assertEqual(
            [b["name"] for b in bosses],
            [
                "Rhahk'Zor",
                "Sneed",
                "Gilnid",
                "Mr. Smite",
                "Cookie",
                "Captain Greenskin",
                "Edwin VanCleef",
            ],
        )
        self.assertEqual(
            [(b["killed"], b["at"], b["by"]) for b in bosses[:3]],
            [
                (True, "2026-10-08 10:12:00", "Grug"),
                (True, "2026-10-08 10:28:00", "Ugga"),
                (False, None, None),
            ],
        )

    def test_the_list_is_the_dungeons_own_from_the_world_database(self):
        # #1130: only the Deadmines had a boss list, so a Blackfathom run
        # answered none.
        bfd = dict(ROW, keyword="blackfathom", bosses_done=0, outcome="wiped")
        code, payload, rd = ask("398", rows=(bfd,), boss_list_rows=BLACKFATHOM_WORLD)
        self.assertEqual(code, 200)
        self.assertEqual(
            [b["name"] for b in payload["run"]["bosses"]],
            [row["name"] for row in BLACKFATHOM_WORLD],
        )
        self.assertFalse(any(b["killed"] for b in payload["run"]["bosses"]))
        ((_sql, params),) = boss_list_reads(rd)
        self.assertEqual(params, tuple(range(219, 227)))

    def test_a_cleared_run_without_kill_rows_does_not_say_every_boss_lived(self):
        # #1130: a cleared 7 of 7 Deadmines run listed every boss killed=false,
        # because nothing writes boss_kill rows yet.
        code, payload, _rd = ask("398")
        self.assertEqual(code, 200)
        self.assertEqual(payload["run"]["bosses_done"], 7)
        self.assertEqual(payload["run"]["bosses"], [])

    def test_a_cleared_run_counted_at_nothing_lists_no_boss_as_alive(self):
        # Run 3607: Zul'Farrak finished at 0 of 7, and all eight bosses read
        # "not killed" because no kill row and no count disagreed.
        finished = dict(ROW, outcome="cleared", bosses_done=0)
        code, payload, _rd = ask("398", rows=(finished,))
        self.assertEqual(code, 200)
        self.assertEqual(payload["run"]["bosses"], [])

    def test_kill_rows_short_of_the_count_leave_the_list_empty(self):
        kills = [
            {
                "member": "Grug",
                "entry": 644,
                "name": "Rhahk'Zor",
                "at": "2026-10-08 10:12:00",
            }
        ]
        code, payload, _rd = ask("398", boss_kill_rows=kills)
        self.assertEqual(payload["run"]["bosses"], [])

    def test_a_kill_row_without_a_time_is_still_a_kill(self):
        kills = [{"member": "Grug", "entry": 644, "name": "Rhahk'Zor", "at": ""}]
        one_down = dict(ROW, outcome="wiped", bosses_done=1)
        code, payload, _rd = ask("398", rows=(one_down,), boss_kill_rows=kills)
        self.assertEqual(code, 200)
        first = payload["run"]["bosses"][0]
        self.assertEqual(
            (first["killed"], first["at"], first["by"]), (True, None, "Grug")
        )

    def test_a_world_without_the_tables_falls_back_to_the_frozen_list(self):
        none_down = dict(ROW, outcome="wiped", bosses_done=0)
        code, payload, _rd = ask(
            "398", rows=(none_down,), boss_list_rows=realmread.MISSING_TABLE
        )
        self.assertEqual(
            [b["entry"] for b in payload["run"]["bosses"]],
            [entry for entry, _ in run_api.achievements.DUNGEONS[36]["bosses"]],
        )

    def test_a_wing_map_has_no_boss_list(self):
        library = dict(ROW, keyword="scarlet-library", bosses_done=0)
        code, payload, rd = ask("398", rows=(library,))
        self.assertEqual(payload["run"]["bosses"], [])
        self.assertEqual(boss_list_reads(rd), [])

    def test_a_kill_without_a_killer_name_is_still_a_kill(self):
        kills = [
            {
                "member": "",
                "entry": 644,
                "name": "Rhahk'Zor",
                "at": "2026-10-08 10:12:00",
            }
        ]
        one_down = dict(ROW, outcome="wiped", bosses_done=1)
        code, payload, _rd = ask("398", rows=(one_down,), boss_kill_rows=kills)
        self.assertTrue(payload["run"]["bosses"][0]["killed"])
        self.assertEqual(payload["run"]["bosses"][0]["by"], "")

    def test_an_unknown_dungeon_has_no_boss_list(self):
        code, payload, _rd = ask("398", rows=(dict(ROW, keyword="unknown"),))
        self.assertEqual(payload["run"]["bosses"], [])
        self.assertEqual(payload["run"]["wipes"], [])

    def test_a_run_without_seats_has_no_bosses(self):
        code, payload, _rd = ask("398", rows=(dict(ROW, members=""),))
        self.assertEqual(payload["run"]["bosses"], [])
        self.assertEqual(payload["run"]["wipes"], [])


class TheWipes(unittest.TestCase):
    def test_a_cluster_of_deaths_to_a_boss_is_a_wipe(self):
        deaths = [
            {
                "character_name": "Grug",
                "killer_name": "Sneed's Shredder",
                "killer_entry": 642,
                "created_at": "2026-10-08 10:30:00",
            },
            {
                "character_name": "Ugga",
                "killer_name": "Sneed's Shredder",
                "killer_entry": 642,
                "created_at": "2026-10-08 10:30:05",
            },
            {
                "character_name": "Og",
                "killer_name": "Sneed's Shredder",
                "killer_entry": 642,
                "created_at": "2026-10-08 10:30:10",
            },
        ]
        code, payload, _rd = ask("398", death_rows=deaths)
        self.assertEqual(code, 200)
        self.assertEqual(
            payload["run"]["wipes"],
            [
                {
                    "entry": 642,
                    "name": "Sneed's Shredder",
                    "at": "2026-10-08 10:30:00",
                    "deaths": 3,
                }
            ],
        )

    def test_deaths_spread_out_are_separate_wipes(self):
        deaths = [
            {
                "character_name": "Grug",
                "killer_name": "Rhahk'Zor",
                "killer_entry": 644,
                "created_at": "2026-10-08 10:15:00",
            },
            {
                "character_name": "Ugga",
                "killer_name": "Rhahk'Zor",
                "killer_entry": 644,
                "created_at": "2026-10-08 10:15:05",
            },
            {
                "character_name": "Grug",
                "killer_name": "Sneed's Shredder",
                "killer_entry": 642,
                "created_at": "2026-10-08 10:35:00",
            },
            {
                "character_name": "Ugga",
                "killer_name": "Sneed's Shredder",
                "killer_entry": 642,
                "created_at": "2026-10-08 10:35:05",
            },
        ]
        code, payload, _rd = ask("398", death_rows=deaths)
        self.assertEqual(
            [(w["name"], w["deaths"]) for w in payload["run"]["wipes"]],
            [("Rhahk'Zor", 2), ("Sneed's Shredder", 2)],
        )

    def test_a_single_death_to_a_boss_is_not_a_wipe(self):
        deaths = [
            {
                "character_name": "Grug",
                "killer_name": "Rhahk'Zor",
                "killer_entry": 644,
                "created_at": "2026-10-08 10:15:00",
            },
        ]
        code, payload, _rd = ask("398", death_rows=deaths)
        self.assertEqual(payload["run"]["wipes"], [])

    def test_deaths_to_trash_are_not_wipes(self):
        deaths = [
            {
                "character_name": "Grug",
                "killer_name": "Defias Miner",
                "killer_entry": 598,
                "created_at": "2026-10-08 10:15:00",
            },
            {
                "character_name": "Ugga",
                "killer_name": "Defias Miner",
                "killer_entry": 598,
                "created_at": "2026-10-08 10:15:05",
            },
        ]
        code, payload, _rd = ask("398", death_rows=deaths)
        self.assertEqual(payload["run"]["wipes"], [])

    def test_a_run_still_inside_has_no_wipe_read(self):
        inside = dict(ROW, state="inside", outcome="")
        code, payload, rd = ask(
            "398",
            rows=(inside,),
            death_rows=[
                {
                    "character_name": "Grug",
                    "killer_name": "Rhahk'Zor",
                    "killer_entry": 644,
                    "created_at": "2026-10-08 10:15:00",
                }
            ],
        )
        self.assertEqual(code, 200)
        self.assertEqual(payload["run"]["wipes"], [])
        self.assertEqual(reads(rd, "overseer_death"), [])


def timeline_events(run):
    """bossEvents and bossRows, run under node on one run."""
    uri = (HERE / "app" / "views" / "run.js").as_uri()
    code = (
        "globalThis.window = {setTimeout: (f) => f(), addEventListener() {},"
        " matchMedia: () => ({matches: false})};\n"
        "globalThis.location = {hash: ''};\n"
        "globalThis.document = {querySelector: () => null, addEventListener() {}};\n"
        "const V = await import(%s);\n"
        "const run = %s;\n"
        "console.log(JSON.stringify({events: V.bossEvents(run).map((e) => e.text),"
        " rows: String(V.bossRows(run).s), timeline: String(V.timeline(run).s),"
        " missing: V.readFailed({error: new Error('HTTP 404')}),"
        " down: V.readFailed({error: new Error('HTTP 502')}),"
        " answered: V.readFailed({error: null})}));\n"
    ) % (json.dumps(uri), json.dumps(run))
    out = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheRunPageSaysWhatTheRowsHold(unittest.TestCase):
    def test_a_cluster_of_deaths_is_told_as_deaths_and_not_a_wipe(self):
        run = {
            "wipes": [{"at": "2026-11-01 10:00:00", "name": "Ragnaros", "deaths": 2}]
        }
        self.assertEqual(timeline_events(run)["events"], ["2 deaths to Ragnaros."])

    def test_a_death_with_no_killer_name_does_not_leave_a_hole(self):
        run = {"wipes": [{"at": "2026-11-01 10:00:00", "name": "", "deaths": 3}]}
        self.assertEqual(timeline_events(run)["events"], ["3 deaths to a boss."])

    def test_a_boss_with_no_kill_row_is_not_said_to_have_lived(self):
        run = {"bosses": [{"name": "Hogger", "killed": False}]}
        rows = timeline_events(run)["rows"]
        self.assertIn("no kill recorded", rows)
        self.assertNotIn("not killed", rows)

    def test_a_run_the_server_does_not_have_is_not_an_outage(self):
        got = timeline_events({})
        self.assertEqual(
            (got["missing"], got["down"], got["answered"]), (False, True, False)
        )

    def test_a_council_award_is_not_called_looted(self):
        run = {
            "gear": [
                {
                    "at": "2026-11-01 10:00:00",
                    "member": "Grug",
                    "name": "Destiny",
                    "source": "won by loot council",
                }
            ]
        }
        got = timeline_events(run)["timeline"]
        self.assertIn("was awarded Destiny by the loot council.", got)
        self.assertNotIn("looted Destiny", got)


class TheRunPageAsksForIt(unittest.TestCase):
    def test_the_run_view_falls_back_to_the_one_run_read(self):
        src = (HERE / "app" / "views" / "run.js").read_text(encoding="utf-8")
        self.assertIn('"/api/v2/run?id=" + encodeURIComponent(', src)
        self.assertIn("function gearRows(r)", src)
        self.assertIn('"looted " + g.name', src)


if __name__ == "__main__":
    unittest.main()

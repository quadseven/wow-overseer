"""The campaign planner: the next dungeon for a family whose queue ran out.

What the operator asked for: both families keep running dungeons that suit
their level, every door the overseer has, with nobody writing the next order.
The families here are the dev realm's as read on 2026-09-23: the Horde five at
22 to 25 standing in Ragefire Chasm (Kalimdor), the Alliance five at 60 on
Kalimdor. Every test runs on fake rows; none touches a database.
"""

import ast
import asyncio
import pathlib
import types
import unittest
from unittest import mock

from test_campaign_queue import _load  # sets up the pymysql stub
from test_jev_items import FakeJev

import campaignplan  # noqa: E402
import campaignqueue  # noqa: E402
import dungeonpath  # noqa: E402
import jev  # noqa: E402
import jev_choices  # noqa: E402
import jobs  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")

EASTERN_KINGDOMS, KALIMDOR, RAGEFIRE = 0, 1, 389

HORDE = (
    ("Zug", 25, 2),
    ("Oz", 24, 8),
    ("Uzza", 22, 8),
    ("Zork", 22, 6),
    ("Zrog", 23, 2),
)
ALLIANCE = (
    ("Grug", 60, 1),
    ("Ugga", 60, 1),
    ("Og", 60, 1),
    ("Bork", 60, 7),
    ("Grog", 60, 3),
)

# The Crescent Key in a member's bags, which opens Dire Maul West and North.
CRESCENT = frozenset({18249})


def rows(family=HORDE, map_id=RAGEFIRE, level=None):
    return tuple(
        {
            "name": n,
            "level": lvl if level is None else level,
            "race": race,
            "map_id": map_id,
            "lead": int(i == 0),
        }
        for i, (n, lvl, race) in enumerate(family)
    )


def facts(family=HORDE, map_id=RAGEFIRE, level=None, done=None, quests=None, **kw):
    return campaignplan.Facts(
        family=family[0][0],
        level_rows=rows(family, map_id, level),
        done=dict(done or {}),
        failed={},
        quests=quests,
        **kw,
    )


def keywords(opts):
    return [o.keyword for o in opts]


class EveryDoorIsCovered(unittest.TestCase):
    def test_every_portal_is_a_run_or_a_second_door_into_one(self):
        self.assertEqual(campaignplan.portal_coverage(), set(jobs.PORTAL_KEYWORDS))
        self.assertFalse(set(campaignplan.BY_KEYWORD) & set(campaignplan.ALTERNATES))

    def test_a_second_door_opens_the_same_map_as_its_run(self):
        for door, run in campaignplan.ALTERNATES.items():
            self.assertEqual(
                dungeonpath.PORTAL_MAPS[door], dungeonpath.PORTAL_MAPS[run], door
            )

    def test_every_band_is_a_band(self):
        for run in campaignplan.RUNS:
            self.assertLessEqual(run.floor, run.ceiling, run.keyword)
            self.assertLessEqual(run.ceiling, campaignplan.LEVEL_CAP, run.keyword)


class WhatAFamilyIsOffered(unittest.TestCase):
    def test_the_horde_at_22_on_kalimdor(self):
        opts = campaignplan.options(facts())
        self.assertEqual(keywords(opts), ["wailing", "blackfathom"])
        wailing, blackfathom = opts
        self.assertTrue(wailing.ready)
        self.assertFalse(blackfathom.ready)
        refused = campaignplan.refusals(facts())
        self.assertIn("outgrown", refused["ragefire"])
        self.assertIn("Eastern Kingdoms", refused["deadmines"])
        self.assertIn("Uzza is level 22", refused["razorfen-kraul"])

    def test_the_alliance_at_60_on_kalimdor_runs_dire_maul(self):
        opts = campaignplan.options(facts(ALLIANCE, KALIMDOR, keys=CRESCENT))
        self.assertEqual(
            keywords(opts),
            ["dire-maul-east-east", "dire-maul-west-north", "dire-maul-north"],
        )
        refused = campaignplan.refusals(facts(ALLIANCE, KALIMDOR))
        self.assertIn("outgrown", refused["zulfarrak"])
        self.assertIn("other faction", refused["ragefire"])

    def test_the_alliance_at_60_on_the_eastern_kingdoms_runs_the_rest(self):
        opts = campaignplan.options(facts(ALLIANCE, EASTERN_KINGDOMS))
        self.assertEqual(
            keywords(opts),
            [
                "sunken-temple",
                "blackrock-depths",
                "lower-blackrock-spire",
                "scholomance",
            ],
        )

    def test_stratholme_joins_once_it_is_no_longer_withheld(self):
        with mock.patch.dict(dungeonpath.WITHHELD_DOORS, {}, clear=True):
            opts = campaignplan.options(facts(ALLIANCE, EASTERN_KINGDOMS))
        self.assertIn("stratholme-live", keywords(opts))
        self.assertIn("stratholme-undead", keywords(opts))

    def test_nothing_is_offered_without_a_level(self):
        self.assertEqual(campaignplan.options(facts(level=0)), [])
        self.assertIn("nobody's level", campaignplan.nothing_line(facts(level=0)))


class HowManyRuns(unittest.TestCase):
    def test_a_levelling_family_runs_it_until_it_is_outgrown(self):
        wailing = campaignplan.options(facts())[0]
        self.assertEqual(wailing.target, (24 - 22 + 1) * campaignplan.RUNS_PER_LEVEL)
        self.assertEqual(wailing.runs, 12)
        self.assertFalse(wailing.capped)
        self.assertIn("outgrows it at 24", wailing.why)

    def test_open_quests_add_a_quest_pass(self):
        wailing = campaignplan.options(facts(quests={718: 5}))[0]
        self.assertEqual(wailing.runs, 12 + campaignplan.QUEST_PASS_RUNS)
        self.assertIn("quest pass for its 5 open quests", wailing.why)

    def test_runs_already_done_count_against_it_and_a_done_run_is_gone(self):
        self.assertEqual(
            campaignplan.options(facts(done={"wailing": 5}))[0].runs, 12 - 5
        )
        opts = campaignplan.options(facts(done={"wailing": 12}))
        self.assertEqual(keywords(opts), ["blackfathom"])

    def test_one_entry_is_never_more_than_the_cap(self):
        at_24 = campaignplan.options(facts(level=24))
        blackfathom = next(o for o in at_24 if o.keyword == "blackfathom")
        self.assertEqual(blackfathom.target, (32 - 24 + 1) * 4)
        self.assertEqual(blackfathom.runs, campaignplan.MAX_RUNS)

    def test_a_capped_family_farms_in_rounds(self):
        first = campaignplan.options(facts(ALLIANCE, KALIMDOR, keys=CRESCENT))
        self.assertEqual({o.runs for o in first}, {campaignplan.AT_CAP_RUNS})
        self.assertTrue(all(o.capped for o in first))
        one_left = campaignplan.options(
            facts(
                ALLIANCE,
                KALIMDOR,
                done={"dire-maul-east-east": 10, "dire-maul-west-north": 10},
                keys=CRESCENT,
            )
        )
        self.assertEqual(keywords(one_left), ["dire-maul-north"])
        round_two = campaignplan.options(
            facts(
                ALLIANCE,
                KALIMDOR,
                done={
                    "dire-maul-east-east": 10,
                    "dire-maul-west-north": 10,
                    "dire-maul-north": 10,
                },
                keys=CRESCENT,
            )
        )
        self.assertEqual(len(round_two), 3)
        self.assertEqual({o.target for o in round_two}, {20})


class WhichOne(unittest.TestCase):
    def test_ready_before_carried(self):
        pick = campaignplan.heuristic(campaignplan.options(facts()))
        self.assertEqual(pick.keyword, "wailing")

    def test_the_soonest_outgrown_first(self):
        opts = campaignplan.options(facts(level=36, map_id=KALIMDOR))
        self.assertEqual(
            keywords(opts)[:3], ["razorfen-kraul", "razorfen-downs", "zulfarrak"]
        )
        self.assertEqual(campaignplan.heuristic(opts).keyword, "razorfen-kraul")

    def test_at_the_cap_the_least_run_first(self):
        opts = campaignplan.options(
            facts(ALLIANCE, KALIMDOR, done={"dire-maul-east-east": 4}, keys=CRESCENT)
        )
        self.assertEqual(campaignplan.heuristic(opts).keyword, "dire-maul-west-north")

    def test_nothing_to_choose_is_none(self):
        self.assertIsNone(campaignplan.heuristic([]))


class WhenToPlan(unittest.TestCase):
    def q(self, keyword="wailing", runs=12, status="active", source="web:overseer"):
        return {
            "id": 7,
            "family": "Zug",
            "position": 0,
            "keyword": keyword,
            "runs_wanted": runs,
            "status": status,
            "source": source,
        }

    def test_an_empty_queue(self):
        self.assertEqual(
            campaignplan.due([], None, list(rows())).reason, "the queue is empty"
        )

    def test_an_operators_order_in_progress_is_left_alone(self):
        leader = {"dungeon_runs_done": 3}
        self.assertEqual(campaignplan.due([self.q()], leader, list(rows())).reason, "")
        self.assertEqual(
            campaignplan.due([self.q(), self.q("blackfathom")], leader, []).reason, ""
        )
        self.assertEqual(
            campaignplan.due([self.q(status="queued")], leader, []).reason, ""
        )

    def test_the_last_entry_done(self):
        due = campaignplan.due([self.q()], {"dungeon_runs_done": 12}, list(rows()))
        self.assertIn("done at 12 of 12", due.reason)
        self.assertEqual(due.finish, 0)

    def test_its_own_entry_outgrown_ends_early_and_an_operators_does_not(self):
        at_26 = list(rows(level=26))
        own = campaignplan.due(
            [self.q(source=campaignplan.SOURCE)], {"dungeon_runs_done": 2}, at_26
        )
        self.assertIn("outgrown Wailing Caverns", own.reason)
        self.assertEqual(own.finish, 7)
        theirs = campaignplan.due([self.q()], {"dungeon_runs_done": 2}, at_26)
        self.assertEqual(theirs.reason, "")

    def test_the_queue_read_carries_the_source(self):
        self.assertIn("source", campaignqueue.SELECT_PENDING_SQL)


class TheReads(unittest.TestCase):
    def test_the_ledger_counts_completed_runs_by_wing(self):
        ledger = [
            {
                "leader_name": "Zug",
                "map_id": 43,
                "portal_keyword": "wailing",
                "outcome": "complete",
            },
            {"leader_name": "Oz", "map_id": 43, "outcome": "complete"},
            {"leader_name": "Zug", "map_id": 43, "outcome": "staging_failed"},
            {"leader_name": "Grug", "map_id": 43, "outcome": "complete"},
            {
                "leader_name": "Zug",
                "map_id": 429,
                "portal_keyword": "dire-maul-east-south",
                "outcome": "complete",
            },
            {"leader_name": "Zug", "map_id": 189, "outcome": "complete"},
        ]
        done, failed = campaignplan.ledger(ledger, [n for n, _, _ in HORDE])
        self.assertEqual(done, {"wailing": 2, "dire-maul-east-east": 1, "scarlet": 1})
        self.assertEqual(failed, {"wailing": 1})

    def test_open_quests_by_race_level_and_reward(self):
        quests = [
            {"quest": 1, "zone": 718, "min_level": 10, "races": 0},
            {"quest": 2, "zone": 718, "min_level": 10, "races": 1101},  # Alliance
            {"quest": 3, "zone": 718, "min_level": 30, "races": 0},
            {"quest": 4, "zone": 718, "min_level": 10, "races": 690},  # Horde
            {"quest": 5, "zone": 2437, "min_level": 9, "races": 0},
        ]
        rewarded = [{"name": n, "quest": 5} for n, _, _ in HORDE]
        rewarded.append({"name": "Zug", "quest": 4})
        self.assertEqual(
            campaignplan.open_quests(quests, rewarded, list(rows())), {718: 2}
        )

    def test_gear_and_loot(self):
        self.assertEqual(
            campaignplan.gear([{"name": "Oz", "item_level": 7.24, "worn": 6}]),
            {"Oz": (7.2, len(campaignplan.GEAR_SLOTS) - 6)},
        )
        self.assertEqual(
            campaignplan.loot([{"map_id": 43, "item_level": 22.6}]), {43: 23}
        )

    def test_the_quest_read_names_every_run_zone(self):
        for run in campaignplan.RUNS:
            self.assertIn(str(run.zone), campaignplan.QUESTS_SQL, run.keyword)


class TheForecast(unittest.TestCase):
    """The planned order for both families today, as the report quotes it."""

    def test_the_horde_levels_through_kalimdor(self):
        ahead = campaignplan.sequence(facts())
        self.assertEqual(
            [o.keyword for o, _ in ahead][:6],
            [
                "wailing",
                "blackfathom",
                "razorfen-kraul",
                "razorfen-downs",
                "zulfarrak",
                "maraudon-orange",
            ],
        )
        levels = [level for _, level in ahead]
        self.assertEqual(levels, sorted(levels))

    def test_the_alliance_rotates_dire_maul(self):
        ahead = campaignplan.sequence(facts(ALLIANCE, KALIMDOR, keys=CRESCENT), count=6)
        self.assertEqual(
            [o.keyword for o, _ in ahead],
            ["dire-maul-east-east", "dire-maul-west-north", "dire-maul-north"] * 2,
        )

    def test_a_queue_is_run_before_the_plan(self):
        ahead = campaignplan.sequence(facts(), [("wailing", 12)], count=1)
        self.assertEqual(ahead[0][0].keyword, "blackfathom")


class ThePage(unittest.TestCase):
    def test_now_and_next_planned(self):
        view = campaignqueue.view(
            [{"keyword": "wailing", "runs_wanted": 12, "status": "active"}], 4, "Zug"
        )
        self.assertEqual(view["done"], 4)
        page = campaignplan.page_view(view, facts(), 4)
        self.assertEqual(page["now"], "Now: Wailing Caverns, 4 of 12.")
        self.assertTrue(page["next"].startswith("Next planned: Blackfathom Deeps, "))

    def test_a_queued_second_entry_is_next(self):
        view = campaignqueue.view(
            [
                {"keyword": "ragefire", "runs_wanted": 50, "status": "active"},
                {"keyword": "wailing", "runs_wanted": 50, "status": "queued"},
            ],
            0,
            "Zug",
        )
        page = campaignplan.page_view(view, facts(), 0)
        self.assertEqual(
            page["line"],
            "Now: Ragefire Chasm, 0 of 50. Next: Wailing Caverns, 50 runs, as queued.",
        )

    def test_an_empty_queue_and_nothing_in_range(self):
        page = campaignplan.page_view(
            campaignqueue.view([], None, "Zug"), facts(level=0), None
        )
        self.assertEqual(page["now"], "Now: no dungeon; the family quests.")
        self.assertIn("nothing in range", page["next"])

    def test_the_server_and_the_page_draw_it(self):
        self.assertIn("campaignplan.page_view(", SERVER)
        self.assertIn("f.plan.line", PAGE)


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = info


class TheBridgePass(unittest.TestCase):
    """_plan_campaigns and _plan_campaign, run on fakes."""

    def run_pass(self, pending, jev_pick=None, confidence=0.9, key="k"):
        log = _Log()
        written, recorded = [], []

        def append(family, rows_, finish, option, source):
            written.append((family, finish, option.keyword, option.runs))
            self.sources.append(source)
            return 1

        self.sources = []

        ns = _load(
            ["_plan_campaigns", "_plan_campaign"],
            {
                "asyncio": asyncio,
                "time": __import__("time"),
                "campaignplan": campaignplan,
                "campaignqueue": campaignqueue,
                "jev": jev,
                "jev_choices": jev_choices,
                "log": log,
                "_queue_level_rows": lambda fam: list(rows()),
                "_planner_facts": lambda key, fam, level_rows: facts(),
                "_append_planned": append,
                "_insert_jev_judgment": recorded.append,
            },
        )
        fake = FakeJev(
            picks={"dungeon": jev_pick} if jev_pick else {}, confidence=confidence
        )
        me = types.SimpleNamespace(
            _jev=jev.Client(key, transport=fake), _planner_said={}
        )
        me._plan_campaign = types.MethodType(ns["_plan_campaign"], me)

        async def no_situation(*_args):
            return None

        # The movement picture is read by the bridge (situation.py); these
        # passes run without one, which asks the question as it always was.
        me._situation_for = no_situation
        fams = {
            "Zug": {"leader": {"name": "Zug", "dungeon_runs_done": 0}, "names": ["Zug"]}
        }
        with mock.patch.dict("os.environ", {}, clear=False):
            wrote = asyncio.run(ns["_plan_campaigns"](me, pending, fams))
        return wrote, written, recorded, log.lines, me

    def test_an_empty_queue_gets_the_heuristics_run_and_the_record(self):
        wrote, written, recorded, lines, _me = self.run_pass({}, confidence=0.5)
        self.assertTrue(wrote)
        self.assertEqual(written, [("Zug", 0, "wailing", 12)])
        [judgment] = recorded
        self.assertEqual(
            (judgment.kind, judgment.acted), ("dungeon_choice", jev.HEURISTIC)
        )
        self.assertTrue(any("chosen by the heuristic" in line for line in lines))
        self.assertEqual(self.sources, [campaignplan.SOURCE])

    def test_a_confident_jev_chooses(self):
        _w, written, recorded, lines, _me = self.run_pass({}, jev_pick="blackfathom")
        self.assertEqual(written[0][2], "blackfathom")
        self.assertEqual(recorded[0].acted, jev.JEV)
        self.assertTrue(any("chosen by Jev" in line for line in lines))
        # THE ENTRY SAYS JEV CHOSE IT, in the queue's own row.
        self.assertEqual(self.sources, [campaignplan.SOURCE_JEV])
        self.assertTrue(any("source=overseer:jev" in line for line in lines))

    def test_jev_agreeing_with_the_heuristic_is_still_jevs_entry(self):
        _w, written, recorded, lines, _me = self.run_pass({}, jev_pick="wailing")
        self.assertEqual(written[0][2], "wailing")
        self.assertEqual(recorded[0].acted, jev.BOTH)
        self.assertEqual(self.sources, [campaignplan.SOURCE_JEV])
        self.assertTrue(any("chosen by Jev" in line for line in lines))

    def test_without_a_key_the_heuristic_still_plans(self):
        _w, written, recorded, _lines, _me = self.run_pass({}, key="")
        self.assertEqual(written[0][2], "wailing")
        self.assertEqual(recorded, [])
        self.assertEqual(self.sources, [campaignplan.SOURCE])

    def test_an_order_in_progress_is_not_touched(self):
        pending = {
            "Zug": [
                {
                    "id": 1,
                    "keyword": "ragefire",
                    "runs_wanted": 50,
                    "status": "active",
                    "position": 0,
                    "source": "web:overseer",
                },
                {
                    "id": 2,
                    "keyword": "wailing",
                    "runs_wanted": 50,
                    "status": "queued",
                    "position": 1,
                    "source": "web:overseer",
                },
            ]
        }
        wrote, written, recorded, _lines, _me = self.run_pass(pending)
        self.assertFalse(wrote)
        self.assertEqual((written, recorded), ([], []))

    def test_the_switch_turns_it_off(self):
        with mock.patch.dict("os.environ", {"CAMPAIGN_PLANNER": "off"}):
            self.assertFalse(campaignplan.enabled())
        self.assertTrue(campaignplan.enabled({}))

    def test_the_queue_pass_plans_before_it_steps(self):
        body = ast.get_source_segment(BRIDGE, _node("_campaign_queue_once"))
        self.assertLess(
            body.index("await self._plan_campaigns(pending, fams)"),
            body.index("if not pending:"),
        )

    def test_the_judgment_is_recorded_before_the_entry_is_written(self):
        body = ast.get_source_segment(BRIDGE, _node("_plan_campaign"))
        self.assertLess(
            body.index("_insert_jev_judgment"), body.index("_append_planned")
        )


def _node(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(name)


if __name__ == "__main__":
    unittest.main()

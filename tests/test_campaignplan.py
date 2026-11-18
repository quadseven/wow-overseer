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

from test_campaign_queue import _load
from test_jev_items import FakeJev

import campaignplan  # noqa: E402
import campaignqueue  # noqa: E402
import preraid  # noqa: E402
import dungeonpath  # noqa: E402
import jev  # noqa: E402
import jev_choices  # noqa: E402
import jobs  # noqa: E402
import priorities  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")

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
SHADOWFORGE = frozenset({11000})
KEY_TO_THE_CITY = frozenset({12382})


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
        opts = campaignplan.options(facts(ALLIANCE, EASTERN_KINGDOMS, keys=SHADOWFORGE))
        self.assertEqual(
            keywords(opts),
            [
                "blackrock-depths",
                "lower-blackrock-spire",
                "scholomance",
            ],
        )

    def test_sunken_temple_is_outgrown_once_the_weakest_passes_its_band(self):
        """A family whose weakest member is 59 has outgrown a dungeon whose
        bosses top out in the low 50s: it is refused as outgrown and the
        pick is a level-appropriate run instead (#2715)."""
        family = (
            ("Grug", 60, 1),
            ("Ugga", 60, 1),
            ("Og", 59, 1),
            ("Bork", 60, 7),
            ("Grog", 60, 3),
        )
        refused = campaignplan.refusals(facts(family, EASTERN_KINGDOMS))
        self.assertIn("outgrown", refused["sunken-temple"])
        opts = campaignplan.options(facts(family, EASTERN_KINGDOMS))
        self.assertNotIn("sunken-temple", keywords(opts))
        pick = campaignplan.heuristic(opts)
        self.assertIsNotNone(pick)
        self.assertGreaterEqual(pick.ceiling, 59)

    def test_sunken_temple_ceiling_matches_its_boss_band(self):
        run = campaignplan.BY_KEYWORD["sunken-temple"]
        self.assertEqual(run.ceiling, 55)

    def test_blackrock_depths_is_offered_without_the_shadowforge_key(self):
        """The Shadowforge Key's one source is the quest Dark Iron Legacy,
        inside Blackrock Depths, so locking the run on it kept every family out
        of the place it is earned (#1964). The keyless run clears up to the
        Shadowforge gates."""
        for keys in (None, frozenset()):
            opts = campaignplan.options(facts(ALLIANCE, EASTERN_KINGDOMS, keys=keys))
            self.assertIn("blackrock-depths", keywords(opts), keys)
            kinds = campaignplan.refusal_kinds(
                facts(ALLIANCE, EASTERN_KINGDOMS, keys=keys)
            )
            self.assertNotIn("blackrock-depths", kinds, keys)

    def test_a_key_from_another_wing_still_locks(self):
        """The Scarlet Key, the Crescent Key and the Key to the City come from
        another wing, so their doors stay locked without them."""
        with mock.patch.dict(dungeonpath.WITHHELD_DOORS, {}, clear=True):
            kinds = campaignplan.refusal_kinds(
                facts(ALLIANCE, EASTERN_KINGDOMS, keys=frozenset())
            )
        self.assertEqual(kinds["stratholme-undead"][0], campaignplan.REFUSED_LOCKED)
        for keyword in (
            "scarlet-armory",
            "scarlet-cathedral",
            "dire-maul-west-north",
            "dire-maul-north",
            "stratholme-undead",
        ):
            self.assertIsNotNone(campaignplan.door_lock(keyword), keyword)
        self.assertIsNone(campaignplan.door_lock("blackrock-depths"))

    def test_stratholme_joins_once_it_is_no_longer_withheld(self):
        with mock.patch.dict(dungeonpath.WITHHELD_DOORS, {}, clear=True):
            opts = campaignplan.options(
                facts(ALLIANCE, EASTERN_KINGDOMS, keys=KEY_TO_THE_CITY)
            )
            self.assertIn("stratholme-live", keywords(opts))
            self.assertIn("stratholme-undead", keywords(opts))
            keyless = campaignplan.options(facts(ALLIANCE, EASTERN_KINGDOMS))
            self.assertNotIn(
                "stratholme-undead",
                keywords(keyless),
                "the Service Entrance Gate wants the Key to the City",
            )

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

    def test_a_door_the_family_is_outgrowing_gives_way(self):
        """Measured 2026-11-01: a family at 45 to 49 made about 2,100 xp a
        member-hour in Razorfen Downs and about 6,300 in Uldaman. Uldaman is
        across the sea from Kalimdor, so Zul'Farrak is the next door here."""
        family = (
            ("Grug", 49, 1),
            ("Grog", 47, 3),
            ("Bork", 46, 7),
            ("Ugga", 46, 1),
            ("Og", 45, 1),
        )
        opts = campaignplan.options(facts(family, KALIMDOR))
        self.assertIn("razorfen-downs", keywords(opts))
        pick = campaignplan.heuristic(opts)
        self.assertEqual(pick.keyword, "zulfarrak")
        self.assertIn("not already outgrowing", campaignplan.heuristic_why(pick))

    ZUG = (
        ("Zug", 47, 2),
        ("Uzza", 46, 8),
        ("Zrog", 46, 2),
        ("Oz", 45, 8),
        ("Zork", 45, 6),
    )

    def test_a_door_that_rarely_clears_does_not_win(self):
        """Measured 2026-11-01: Zul'Farrak cleared 2 of 11 guild runs in a day
        and neither family has ever cleared it."""
        opts = campaignplan.options(
            facts(self.ZUG, KALIMDOR, door_record={"zulfarrak": (2, 11)})
        )
        self.assertNotIn("zulfarrak", keywords(opts))
        self.assertTrue(opts)

    def test_a_sound_record_keeps_the_door(self):
        opts = campaignplan.options(
            facts(self.ZUG, KALIMDOR, door_record={"zulfarrak": (4, 11)})
        )
        self.assertIn("zulfarrak", keywords(opts))

    def test_too_few_runs_say_nothing_about_a_door(self):
        opts = campaignplan.options(
            facts(self.ZUG, KALIMDOR, door_record={"zulfarrak": (0, 7)})
        )
        self.assertIn("zulfarrak", keywords(opts))

    def test_a_family_that_has_cleared_the_door_keeps_it(self):
        opts = campaignplan.options(
            facts(
                self.ZUG,
                KALIMDOR,
                done={"zulfarrak": 1},
                door_record={"zulfarrak": (2, 11)},
            )
        )
        self.assertIn("zulfarrak", keywords(opts))

    def test_a_poor_door_stays_when_nothing_sound_is_left(self):
        """The family still runs something: no door is better than a poor one
        only when a sound one is there to take."""
        record = {run.keyword: (0, 20) for run in campaignplan.RUNS}
        opts = campaignplan.options(facts(self.ZUG, KALIMDOR, door_record=record))
        self.assertTrue(opts)
        self.assertTrue(all(o.poor for o in opts))

    def test_a_door_well_inside_its_band_keeps_the_old_order(self):
        family = (("Zug", 41, 2), ("Oz", 40, 8), ("Uzza", 40, 8))
        opts = campaignplan.options(facts(family, KALIMDOR))
        self.assertEqual(campaignplan.heuristic(opts).keyword, "razorfen-downs")

    def test_at_the_cap_the_least_run_first(self):
        opts = campaignplan.options(
            facts(ALLIANCE, KALIMDOR, done={"dire-maul-east-east": 4}, keys=CRESCENT)
        )
        self.assertEqual(campaignplan.heuristic(opts).keyword, "dire-maul-west-north")

    # The bosses' levels as read for these doors, by map: Sunken Temple
    # tops out five under a capped family's weakest member, the Spire is
    # its band.
    CAP_BOSSES = {109: (50, 55), 229: (56, 60), 230: (52, 58), 289: (57, 60)}

    def test_at_the_cap_a_run_below_the_band_loses_to_one_in_it(self):
        """A capped family with empty slots scores a loot-dense low dungeon
        highest on raw expected gain, because an empty slot counts any drop
        as all gain. While a level-appropriate run is unfinished the pick
        is in the family's band; the low run stays offered, because its
        loot still upgrades somebody (#2715)."""
        upgrades = {
            "sunken-temple": (preraid.Gain("Grug", 3, 0.6, 30.0, "a helm"),),
            "lower-blackrock-spire": (preraid.Gain("Grug", 1, 0.2, 10.0, "a helm"),),
        }
        opts = campaignplan.options(
            facts(
                ALLIANCE,
                EASTERN_KINGDOMS,
                keys=SHADOWFORGE,
                bosses=self.CAP_BOSSES,
                upgrades=upgrades,
            )
        )
        self.assertIn("sunken-temple", keywords(opts))
        pick = campaignplan.heuristic(opts)
        self.assertEqual(pick.keyword, "lower-blackrock-spire")

    def test_at_the_cap_a_fire_piece_still_wins_from_below_the_band(self):
        """The band rule excepts a fire-resistance need: a low run that
        drops a planned fire piece for a tank is still the pick (#2715)."""
        upgrades = {
            "sunken-temple": (
                preraid.Gain(
                    "Grug", 3, 0.6, 30.0, "a helm", 10.0, "Emberplate Armguards"
                ),
            ),
            "lower-blackrock-spire": (preraid.Gain("Grug", 1, 0.2, 10.0, "a helm"),),
        }
        opts = campaignplan.options(
            facts(
                ALLIANCE,
                EASTERN_KINGDOMS,
                keys=SHADOWFORGE,
                bosses=self.CAP_BOSSES,
                upgrades=upgrades,
            )
        )
        pick = campaignplan.heuristic(opts)
        self.assertEqual(pick.keyword, "sunken-temple")

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
            ["_plan_campaigns", "_plan_campaign", "_planner_due"],
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
                "_planner_dry": lambda names: None,
                "_finish_planned": lambda finish: 0,
                "dataclasses": __import__("dataclasses"),
                "priorities": priorities,
            },
        )
        fake = FakeJev(
            picks={"dungeon": jev_pick} if jev_pick else {}, confidence=confidence
        )
        me = types.SimpleNamespace(
            _jev=jev.Client(key, transport=fake),
            _planner_said={},
            _planner_loot_read={},
        )
        me._plan_campaign = types.MethodType(ns["_plan_campaign"], me)

        async def default_priorities():
            return priorities.DEFAULT_ORDER

        # The family's priorities (#1559): never set on this realm.
        me._priority_order = default_priorities

        async def no_situation(*_args):
            return None

        # The movement picture is read by the bridge (situation.py); these
        # passes run without one, which asks the question as it always was.
        me._situation_for = no_situation

        async def no_attunement(*_args):
            return set()

        # The attunement step (attunestep.py) holds no family here.
        me._attunement_pass = no_attunement

        async def no_hydraxian(*_args, **_kwargs):
            return set()

        # Hydraxian quest errands are optional and hold only their own walk.
        me._hydraxian_pass = no_hydraxian
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


class ADoorThatTeachesNothing(unittest.TestCase):
    """#1400: Zug's family, all five at 35, on run 20 of 27 at Gnomeregan
    (ceiling 38), gained about six hundred experience a member a run."""

    GNOMEREGAN_MAP = campaignplan.BY_KEYWORD["gnomeregan"].map_id

    def head(self, source=campaignplan.SOURCE):
        return {
            "id": 50,
            "family": "Zug",
            "position": 5,
            "keyword": "gnomeregan",
            "runs_wanted": 27,
            "status": "active",
            "source": source,
        }

    def dry(self, n):
        return campaignplan.dry_doors([{"map_id": self.GNOMEREGAN_MAP, "n": n}])

    def test_the_planned_entry_ends_after_the_dry_runs(self):
        due = campaignplan.due(
            [self.head()],
            {"dungeon_runs_done": 20},
            list(rows(level=35)),
            self.dry(campaignplan.DRY_RUNS),
        )
        self.assertIn("teaches nothing", due.reason)
        self.assertEqual(due.finish, 50)
        self.assertTrue(due.dry)

    def test_fewer_runs_or_no_read_leave_it_running(self):
        for dry in (self.dry(campaignplan.DRY_RUNS - 1), None, {}):
            due = campaignplan.due(
                [self.head()], {"dungeon_runs_done": 20}, list(rows(level=35)), dry
            )
            self.assertEqual(due.reason, "", dry)

    def test_an_operators_order_runs_to_its_count(self):
        due = campaignplan.due(
            [self.head(source="web:overseer")],
            {"dungeon_runs_done": 20},
            list(rows(level=35)),
            self.dry(9),
        )
        self.assertEqual(due.reason, "")

    def test_the_dry_door_is_not_offered_again(self):
        f = facts(
            level=35, map_id=EASTERN_KINGDOMS, dry=self.dry(campaignplan.DRY_RUNS)
        )
        kinds = campaignplan.refusal_kinds(f)
        self.assertEqual(kinds["gnomeregan"][0], campaignplan.REFUSED_DRY)
        self.assertNotIn("gnomeregan", keywords(campaignplan.options(f)))

    def test_a_shared_map_names_no_door(self):
        armory = campaignplan.BY_KEYWORD["scarlet-armory"].map_id
        self.assertEqual(campaignplan.dry_doors([{"map_id": armory, "n": 9}]), {})

    def test_at_the_cap_nothing_is_dry(self):
        self.assertEqual(
            campaignplan._dry(self.dry(9), "gnomeregan", campaignplan.LEVEL_CAP), ""
        )

    def test_the_bridge_reads_it_and_ends_the_entry_with_nothing_to_follow(self):
        self.assertIn('_planner_dry, list(fam["names"])', BRIDGE)
        self.assertIn("if pick is None and due.dry:", BRIDGE)


class ADoorPastItsCeilingAtTheCap(unittest.TestCase):
    """#2207: a capped family stayed on a planned Maraudon entry (ceiling 55).

    Below the cap `due` ends a planned entry once the weakest member passes
    the ceiling. At the cap it never read the loot, so an entry for a door the
    plan itself refuses as outgrown (`_outgrown_run`) ran to its count.
    """

    SPIRE = (preraid.Gain("Grug", 1, 0.2, 10.0, "a helm"),)

    def head(self, source=campaignplan.SOURCE, keyword="maraudon-orange"):
        return {
            "id": 61,
            "family": "Grug",
            "position": 0,
            "keyword": keyword,
            "runs_wanted": 10,
            "status": "active",
            "source": source,
        }

    def due(self, upgrades, level=None, **head):
        return campaignplan.due(
            [self.head(**head)],
            {"dungeon_runs_done": 2},
            list(rows(ALLIANCE, KALIMDOR, level)),
            None,
            upgrades,
        )

    def test_the_planned_entry_ends_once_its_loot_holds_no_upgrade(self):
        upgrades = {"lower-blackrock-spire": self.SPIRE}
        due = self.due(upgrades)
        self.assertIn("outgrown Maraudon (the orange wing)", due.reason)
        self.assertIn("tops out at 55", due.reason)
        self.assertIn("holds no upgrade for anyone", due.reason)
        self.assertEqual(due.finish, 61)
        self.assertFalse(due.dry)
        # ... and the next door is chosen: the plan over the same loot does
        # not offer Maraudon again.
        opts = campaignplan.options(
            facts(ALLIANCE, EASTERN_KINGDOMS, keys=SHADOWFORGE, upgrades=upgrades)
        )
        self.assertNotIn("maraudon-orange", keywords(opts))
        self.assertEqual(campaignplan.heuristic(opts).keyword, "lower-blackrock-spire")

    def test_a_piece_that_drops_nothing_worth_wearing_is_no_upgrade(self):
        nothing = (preraid.Gain("Grug", 0, 0.0, 0.0, ""),)
        due = self.due({"maraudon-orange": nothing})
        self.assertEqual(due.finish, 61)

    def test_a_wanted_drop_keeps_it(self):
        wanted = (preraid.Gain("Grug", 1, 0.3, 12.0, "a ring"),)
        self.assertEqual(self.due({"maraudon-orange": wanted}), campaignplan.Due())

    def test_unread_loot_leaves_it_running(self):
        self.assertEqual(self.due(None), campaignplan.Due())

    def test_an_operators_order_runs_to_its_count(self):
        self.assertEqual(self.due({}, source="web:overseer"), campaignplan.Due())

    def test_a_door_of_the_cap_is_never_past_its_ceiling(self):
        self.assertEqual(
            self.due({}, keyword="lower-blackrock-spire"), campaignplan.Due()
        )

    def test_below_the_cap_the_ceiling_alone_still_ends_it(self):
        due = self.due(None, level=57)
        self.assertIn("the weakest is 57, it tops out at 55", due.reason)
        self.assertEqual(due.finish, 61)

    def test_only_a_capped_family_on_a_lower_door_needs_the_loot_read(self):
        capped = list(rows(ALLIANCE, KALIMDOR))
        need = campaignplan.needs_loot
        self.assertTrue(need([self.head()], capped))
        self.assertFalse(need([self.head(keyword="scholomance")], capped))
        self.assertFalse(need([self.head(source="web:overseer")], capped))
        self.assertFalse(need([self.head()], list(rows(ALLIANCE, KALIMDOR, 57))))
        self.assertFalse(need([self.head(), self.head()], capped))
        self.assertFalse(need([dict(self.head(), status="queued")], capped))
        self.assertFalse(need([], capped))

    def test_the_campaign_line_says_why_a_door_is_kept_past_its_ceiling(self):
        wanted = (preraid.Gain("Grug", 1, 0.3, 12.0, "a ring"),)
        f = facts(
            ALLIANCE,
            KALIMDOR,
            upgrades={"maraudon-orange": wanted, "dire-maul-east-east": self.SPIRE},
        )
        [kept] = [o for o in campaignplan.options(f) if o.keyword == "maraudon-orange"]
        said = (
            "kept past its ceiling of 55 for the 12.0 expected item levels "
            "a run its loot still holds"
        )
        self.assertIn(said, kept.why)
        self.assertIn(said, campaignplan.planned_line(kept, "x", "the heuristic"))
        [at_cap] = [
            o for o in campaignplan.options(f) if o.keyword == "dire-maul-east-east"
        ]
        self.assertEqual(at_cap.why, "a round at the level cap")

    def test_the_now_line_says_why_the_running_door_is_kept(self):
        wanted = (preraid.Gain("Grug", 1, 0.3, 12.0, "a ring"),)
        view = campaignqueue.view(
            [{"keyword": "maraudon-orange", "runs_wanted": 10, "status": "active"}],
            2,
            "Grug",
        )
        page = campaignplan.page_view(
            view, facts(ALLIANCE, KALIMDOR, upgrades={"maraudon-orange": wanted}), 2
        )
        self.assertEqual(
            page["now"],
            "Now: Maraudon (the orange wing), 2 of 10, kept past its ceiling "
            "of 55 for the 12.0 expected item levels a run its loot still holds.",
        )
        plain = campaignplan.page_view(view, facts(ALLIANCE, KALIMDOR), 2)
        self.assertEqual(plain["now"], "Now: Maraudon (the orange wing), 2 of 10.")


class TheBridgeReadsTheLootForADoorPastItsCeiling(unittest.TestCase):
    """#2207: `_plan_campaign` hands `due` the preraid upgrades, which it used
    to read only after `due` had already said nothing was due."""

    SPIRE = (preraid.Gain("Grug", 1, 0.2, 10.0, "a helm"),)

    def run_pass(self, upgrades, head=None, level_rows=None, passes=1):
        log = _Log()
        written, reads = [], []
        levels = list(level_rows or rows(ALLIANCE, EASTERN_KINGDOMS))

        def append(family, rows_, finish, option, source):
            written.append((family, finish, option.keyword))
            return 1

        def preraid_read(names, level_rows_):
            reads.append(tuple(names))
            return upgrades, None

        ns = _load(
            ["_plan_campaign", "_planner_due"],
            {
                "asyncio": asyncio,
                "time": __import__("time"),
                "campaignplan": campaignplan,
                "campaignqueue": campaignqueue,
                "jev": jev,
                "jev_choices": jev_choices,
                "log": log,
                "_queue_level_rows": lambda fam: levels,
                "_planner_facts": lambda key, fam, level_rows_: facts(
                    ALLIANCE,
                    EASTERN_KINGDOMS,
                    keys=SHADOWFORGE,
                    upgrades={"lower-blackrock-spire": self.SPIRE},
                ),
                "_planner_preraid": preraid_read,
                "_append_planned": append,
                "_insert_jev_judgment": lambda judgment: None,
                "_planner_dry": lambda names: None,
                "_finish_planned": lambda finish: 0,
                "dataclasses": __import__("dataclasses"),
                "priorities": priorities,
            },
        )
        me = types.SimpleNamespace(
            _jev=jev.Client("", transport=FakeJev()),
            _planner_said={},
            _planner_loot_read={},
        )
        fam = {"leader": {"name": "Grug", "dungeon_runs_done": 2}, "names": ["Grug"]}
        queue = [
            head
            or {
                "id": 61,
                "keyword": "maraudon-orange",
                "runs_wanted": 10,
                "status": "active",
                "position": 0,
                "source": campaignplan.SOURCE,
            }
        ]
        wrote = [
            asyncio.run(ns["_plan_campaign"](me, "Grug", fam, queue))
            for _ in range(passes)
        ]
        return wrote, written, reads, log.lines

    def test_the_outgrown_entry_is_finished_and_the_next_door_queued(self):
        wrote, written, reads, lines = self.run_pass({})
        self.assertEqual(wrote, [True])
        self.assertEqual(written, [("Grug", 61, "lower-blackrock-spire")])
        self.assertEqual(reads, [("Grug",)])
        self.assertTrue(
            any("outgrown Maraudon (the orange wing)" in line for line in lines), lines
        )

    def test_a_wanted_drop_leaves_the_entry_and_the_read_waits_its_turn(self):
        wanted = (preraid.Gain("Grug", 1, 0.3, 12.0, "a ring"),)
        wrote, written, reads, _lines = self.run_pass(
            {"maraudon-orange": wanted}, passes=3
        )
        self.assertEqual(wrote, [False, False, False])
        self.assertEqual(written, [])
        # Read once, then not again inside campaignplan.IDLE_SECONDS.
        self.assertEqual(reads, [("Grug",)])

    def test_unread_loot_ends_nothing(self):
        wrote, written, _reads, _lines = self.run_pass(None)
        self.assertEqual((wrote, written), ([False], []))

    def test_no_read_for_a_family_still_levelling(self):
        wrote, written, reads, _lines = self.run_pass(
            {}, level_rows=rows(ALLIANCE, EASTERN_KINGDOMS, 50)
        )
        self.assertEqual((wrote, written, reads), ([False], [], []))

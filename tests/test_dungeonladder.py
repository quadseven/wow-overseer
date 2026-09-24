"""The dungeon ladder, and Jev choosing the next campaign from it.

What the operator asked for: once the operator's own orders finish, each
family runs amok through every dungeon before Molten Core its faction can
reach, the level 60 Alliance family for upgrades and the Horde family for
levels and upgrades, with Jev choosing the next campaign the way a guild
would: by what the loot is worth, how the levels fit, and where the family
keeps dying. The operator's orders come first and are never replaced, and at
most one chosen campaign waits in the queue at a time. The families are the
dev realm's as read on 2026-09-24: the Horde five at 26 to 29 on Kalimdor,
the Alliance five at 60 on Kalimdor, fresh from four Zul'Farrak bosses that
handed nine pieces to members. Every test runs on fake rows.
"""

import asyncio
import pathlib
import unittest
from unittest import mock

from test_campaignplan import ALLIANCE, CRESCENT, HORDE, KALIMDOR, facts
from test_jev_items import FakeJev
from test_preraid import (
    ANCHORS,
    DROPS,
    ITEMS,
    REWARDS,
    TEXTS,
    drop,
    family,
    item_row,
    STA,
    DEF,
)

import campaignplan  # noqa: E402
import campaignqueue  # noqa: E402
import crossing  # noqa: E402
import dungeonladder  # noqa: E402
import jev  # noqa: E402
import jev_choices  # noqa: E402
import preraid  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")

# The bosses' levels as the dev realm's encounter credits give them.
BOSSES = {
    389: (16, 16),
    43: (20, 20),
    48: (23, 24),
    47: (26, 27),
    209: (46, 46),
    349: (44, 48),
    429: (57, 62),
}


def horde(level=26, **kw):
    return facts(HORDE, KALIMDOR, level=level, bosses=BOSSES, **kw)


def alliance(**kw):
    return facts(ALLIANCE, KALIMDOR, bosses=BOSSES, **kw)


def rung(view, keyword):
    return next(r for r in view["rungs"] if r["keyword"] == keyword)


def worth(**levels):
    """Upgrades as preraid.run_gains shapes them: every place preraid reads,
    with `levels` item levels a run at the named ones and nothing elsewhere."""
    out = {place: () for place in preraid.PLACES}
    for place, value in levels.items():
        out[place] = (preraid.Gain("Grug", 1, 0.2, value, "a helm"),)
    return out


class TheLadderIsPerFactionAndPerLevel(unittest.TestCase):
    def test_the_horde_at_26_on_kalimdor(self):
        view = dungeonladder.view(horde())
        self.assertEqual(view["title"], "The Horde ladder, with Oz the weakest at 26")
        self.assertEqual(
            [r["keyword"] for r in view["rungs"]],
            [r.keyword for r in campaignplan.RUNS],
        )
        states = {r["keyword"]: r["state"] for r in view["rungs"]}
        self.assertEqual(states["ragefire"], dungeonladder.OUTGROWN)
        self.assertEqual(states["stockades"], dungeonladder.OTHER_SIDE)
        self.assertEqual(states["deadmines"], dungeonladder.ACROSS)
        self.assertEqual(states["blackfathom"], dungeonladder.OPEN)
        self.assertEqual(states["razorfen-kraul"], dungeonladder.AHEAD)
        self.assertTrue(view["line"].startswith("Open now: Blackfathom Deeps."))

    def test_ragefire_is_the_hordes_and_not_the_alliances(self):
        young = dict(zip(("Grug", "Ugga", "Og", "Bork", "Grog"), [15] * 5))
        low = campaignplan.Facts(
            family="Grug",
            level_rows=tuple(
                {"name": n, "level": lvl, "race": 1, "map_id": KALIMDOR, "lead": 0}
                for n, lvl in young.items()
            ),
            done={},
            failed={},
        )
        self.assertEqual(
            rung(dungeonladder.view(low), "ragefire")["state"],
            dungeonladder.OTHER_SIDE,
        )
        self.assertEqual(
            rung(dungeonladder.view(horde(level=15)), "ragefire")["state"],
            dungeonladder.OPEN,
        )

    def test_the_bosses_levels_are_the_worlds_and_the_fit_is_said(self):
        view = dungeonladder.view(horde())
        blackfathom = rung(view, "blackfathom")
        self.assertEqual(blackfathom["bosses"], "23 to 24")
        self.assertIn("its bosses 23 to 24", blackfathom["detail"])
        self.assertIn("about right for a weakest of 26", blackfathom["line"])
        self.assertEqual(
            campaignplan.bosses([{"map_id": 48, "low": 23, "high": 24}]),
            {48: (23, 24)},
        )

    def test_a_crossing_opens_the_far_side_when_crossing_py_says_so(self):
        """Reachability is read, not written here: the day crossing.py can
        make the crossing, the Eastern Kingdoms rungs open with no change to
        this module or the planner."""
        shut = rung(dungeonladder.view(horde(level=28)), "scarlet")
        self.assertEqual(shut["state"], dungeonladder.ACROSS)
        with mock.patch.object(crossing, "first_blocked_leg", return_value=None):
            view = dungeonladder.view(horde(level=28))
        self.assertEqual(rung(view, "scarlet")["state"], dungeonladder.OPEN)
        self.assertEqual(rung(view, "shadowfang")["state"], dungeonladder.OPEN)

    def test_nothing_read_is_said(self):
        self.assertEqual(dungeonladder.view(None)["rungs"], [])
        self.assertIn("Nobody's level", dungeonladder.view(horde(level=0))["line"])


class ALevel60FamilyGearsInTheLowerDungeons(unittest.TestCase):
    def test_zulfarrak_stays_open_while_its_loot_upgrades_somebody(self):
        opts = campaignplan.options(
            alliance(upgrades=worth(zulfarrak=18.0, **{"dire-maul-east-east": 9.0}))
        )
        self.assertIn("zulfarrak", [o.keyword for o in opts])
        pick = campaignplan.heuristic(opts)
        self.assertEqual(pick.keyword, "zulfarrak")
        self.assertTrue(pick.capped)
        self.assertEqual(pick.runs, campaignplan.AT_CAP_RUNS)

    def test_zulfarrak_is_outgrown_once_it_holds_nothing(self):
        refused = campaignplan.refusals(alliance(upgrades=worth()))
        self.assertIn("holds no upgrade for anyone", refused["zulfarrak"])

    def test_unread_loot_is_not_claimed_empty(self):
        refused = campaignplan.refusals(alliance(upgrades=worth()))
        self.assertEqual(refused["wailing"], "outgrown: it tops out at 24")
        self.assertEqual(
            campaignplan.refusals(alliance())["zulfarrak"],
            "outgrown: it tops out at 54",
        )

    def test_a_levelling_family_still_outgrows_by_level(self):
        refused = campaignplan.refusals(horde(level=29, upgrades=worth(wailing=5.0)))
        self.assertIn("outgrown", refused["wailing"])


class KeyDoorsWaitForTheirKey(unittest.TestCase):
    def test_dire_maul_west_and_north_wait_for_the_crescent_key(self):
        refused = campaignplan.refusal_kinds(alliance(keys=frozenset()))
        kind, why = refused["dire-maul-west-north"]
        self.assertEqual(kind, campaignplan.REFUSED_LOCKED)
        self.assertIn("the Crescent Key", why)
        self.assertIn("Dire Maul (the East wing, east door)", why)
        self.assertIn("nobody carries one", why)
        self.assertIn("dire-maul-north", refused)
        self.assertNotIn("dire-maul-east-east", refused)

    def test_an_unread_key_is_not_assumed(self):
        why = campaignplan.refusals(alliance())["dire-maul-north"]
        self.assertIn("nothing says anybody carries one", why)

    def test_the_key_in_a_bag_opens_them(self):
        refused = campaignplan.refusals(alliance(keys=CRESCENT))
        self.assertNotIn("dire-maul-west-north", refused)
        self.assertNotIn("dire-maul-north", refused)
        self.assertEqual(campaignplan.keys_held([{"entry": 18249}]), CRESCENT)

    def test_the_ladder_says_locked(self):
        view = dungeonladder.view(alliance(keys=frozenset()))
        self.assertEqual(rung(view, "dire-maul-north")["state"], dungeonladder.LOCKED)


class DeathsAndWipesCount(unittest.TestCase):
    RUNS = [
        {"leader_name": "Zug", "map_id": 48, "outcome": "wipe"},
        {"leader_name": "Zug", "map_id": 48, "outcome": "wipe"},
        {"leader_name": "Zug", "map_id": 48, "outcome": "staging_failed"},
        {"leader_name": "Zug", "map_id": 47, "outcome": "complete"},
        {"leader_name": "Stranger", "map_id": 47, "outcome": "wipe"},
    ]

    def test_the_ledger_is_tallied_by_outcome(self):
        tally = campaignplan.outcomes(self.RUNS, [n for n, _l, _r in HORDE])
        self.assertEqual(tally["blackfathom"], {"wipe": 2, "staging_failed": 1})
        self.assertEqual(tally["razorfen-kraul"], {"complete": 1})

    def test_a_dungeon_that_keeps_wiping_the_family_goes_last(self):
        names = [n for n, _l, _r in HORDE]
        done, failed = campaignplan.ledger(self.RUNS, names)
        calm = campaignplan.heuristic(campaignplan.options(horde(level=30)))
        self.assertEqual(calm.keyword, "blackfathom")
        wiped = horde(
            level=30,
            done=done,
            outcomes=campaignplan.outcomes(self.RUNS, names),
        )
        wiped = campaignplan.Facts(**{**wiped.__dict__, "failed": failed})
        opts = campaignplan.options(wiped)
        blackfathom = next(o for o in opts if o.keyword == "blackfathom")
        self.assertEqual((blackfathom.wipes, blackfathom.staged), (2, 1))
        self.assertTrue(blackfathom.troubled)
        self.assertIn("2 wiped", blackfathom.history)
        self.assertIn("1 never got in", blackfathom.history)
        self.assertEqual(campaignplan.heuristic(opts).keyword, "razorfen-kraul")

    def test_deaths_on_its_map_count_too(self):
        died = horde(level=30, deaths={48: campaignplan.TROUBLE_DEATHS})
        pick = campaignplan.heuristic(campaignplan.options(died))
        self.assertEqual(pick.keyword, "razorfen-kraul")
        self.assertEqual(campaignplan.per_map([{"map_id": 48, "n": 3}]), {48: 3})

    def test_when_every_run_is_troubled_it_says_so(self):
        died = horde(deaths={48: 12})
        pick = campaignplan.heuristic(campaignplan.options(died))
        self.assertEqual(pick.keyword, "blackfathom")
        self.assertIn("has cost the family", campaignplan.heuristic_why(pick))

    def test_jev_is_told_the_record(self):
        f = alliance(
            keys=CRESCENT,
            deaths={429: 4},
            won={209: 9},
            upgrades=worth(zulfarrak=18.0, **{"dire-maul-east-east": 9.0}),
        )
        opts = campaignplan.options(f)
        fake = FakeJev(picks={"dungeon": "zulfarrak"}, confidence=0.9)
        judgment = asyncio.run(
            jev_choices.dungeon_ask(
                jev.Client("k", transport=fake),
                f,
                opts,
                campaignplan.heuristic(opts),
                jev_choices.policy(jev_choices.KIND_DUNGEON, {}),
                "Zul'Farrak is done at 50 of 50",
            )
        )
        [request] = fake.requests
        zf = next(d for d in request["state"]["dungeons"] if d["door"] == "zulfarrak")
        self.assertEqual(zf["boss_levels"], "46 to 46")
        self.assertIn("below a weakest of 60", zf["level_fit"])
        self.assertEqual(zf["pieces_the_loot_council_gave_a_member_there"], 9)
        east = next(
            d
            for d in request["state"]["dungeons"]
            if d["door"] == "dire-maul-east-east"
        )
        self.assertEqual(east["family_deaths_there_in_the_last_week"], 4)
        self.assertIn("keep dying", request["questions"]["dungeon"]["instructions"])
        self.assertIn("died 4", judgment.facts)
        self.assertTrue(jev_choices.dungeon_by_jev(judgment))


class TheOperatorFirstAndOneJevCampaignAtATime(unittest.TestCase):
    def q(self, source="web:overseer", status="active", runs=50, id_=1):
        return {
            "id": id_,
            "family": "Grug",
            "position": id_,
            "keyword": "zulfarrak",
            "runs_wanted": runs,
            "status": status,
            "source": source,
        }

    def test_the_source_says_who_chose(self):
        self.assertEqual(campaignplan.source_for(True), "overseer:jev")
        self.assertEqual(campaignplan.source_for(False), "overseer:planner")
        self.assertIsNone(jev_choices.dungeon_by_jev(None) or None)

    def test_nothing_is_planned_while_an_operator_entry_waits(self):
        rows = list(alliance().level_rows)
        waiting = [self.q(), self.q(status="queued", id_=2)]
        self.assertEqual(
            campaignplan.due(waiting, {"dungeon_runs_done": 50}, rows).reason, ""
        )
        self.assertEqual(
            campaignplan.due([self.q(status="queued")], None, rows).reason, ""
        )

    def test_nothing_is_planned_while_jevs_entry_runs(self):
        rows = list(alliance(upgrades=worth(zulfarrak=5.0)).level_rows)
        mine = [self.q(source=campaignplan.SOURCE_JEV, runs=10)]
        self.assertEqual(
            campaignplan.due(mine, {"dungeon_runs_done": 3}, rows).reason, ""
        )

    def test_the_operators_order_finishing_is_when_jev_plans(self):
        rows = list(alliance().level_rows)
        due = campaignplan.due([self.q()], {"dungeon_runs_done": 50}, rows)
        self.assertEqual(due.reason, "Zul'Farrak is done at 50 of 50")
        self.assertEqual(due.finish, 0)

    def test_jevs_outgrown_entry_ends_early_like_the_planners(self):
        wailing = dict(self.q(source=campaignplan.SOURCE_JEV), keyword="wailing")
        due = campaignplan.due(
            [wailing], {"dungeon_runs_done": 3}, list(horde(level=26).level_rows)
        )
        self.assertIn("outgrown Wailing Caverns", due.reason)
        self.assertEqual(due.finish, 1)

    def test_the_queue_line_marks_jevs_entry(self):
        rows = [
            dict(self.q(), keyword="ragefire", runs_wanted=50),
            dict(
                self.q(status="queued", id_=2, source=campaignplan.SOURCE_JEV),
                keyword="blackfathom",
                runs_wanted=30,
            ),
        ]
        line = campaignqueue.progress_line(rows, 50)
        self.assertEqual(
            line, "Ragefire Chasm 50 of 50, then Blackfathom Deeps 30 (Jev's choice)"
        )
        view = campaignqueue.view(rows, 50, "Zug")
        self.assertEqual([e["by"] for e in view["entries"]], ["", "Jev's choice"])
        planned = dict(rows[1], source=campaignplan.SOURCE)
        self.assertIn("(planned)", campaignqueue.progress_line([planned], None))


class JevsReasonsOnThePage(unittest.TestCase):
    ROW = {
        "heuristic": "maraudon-orange",
        "heuristic_why": "it gives the most expected upgrades",
        "jev": "zulfarrak",
        "confidence": 0.82,
        "probabilities": '{"zulfarrak":0.82,"maraudon-orange":0.12}',
        "acted": "jev",
        "status": "answered",
        "item_name": "Zul'Farrak is done at 50 of 50",
        "age_seconds": 600,
    }

    def test_jevs_choice_and_the_heuristics_reason(self):
        line = campaignplan.choice_line(self.ROW)
        self.assertIn("10 minutes ago", line)
        self.assertIn("asked because Zul'Farrak is done at 50 of 50", line)
        self.assertIn("Jev chose Zul'Farrak (sure at 0.82", line)
        self.assertIn("next Maraudon (the orange wing) at 0.12", line)
        self.assertIn("over the heuristic's Maraudon (the orange wing)", line)
        self.assertIn("Jev's choice was queued", line)

    def test_agreement_short_answers_and_no_answer(self):
        both = campaignplan.choice_line(dict(self.ROW, acted="both"))
        self.assertIn("as the heuristic did", both)
        short = campaignplan.choice_line(dict(self.ROW, acted="heuristic"))
        self.assertIn("short of its floor", short)
        none = campaignplan.choice_line(dict(self.ROW, jev="", status="no_key"))
        self.assertIn("Jev gave no answer (no_key)", none)
        self.assertEqual(campaignplan.choice_line(None), "")

    def test_the_page_view_carries_it(self):
        view = campaignqueue.view([], None, "Grug")
        page = campaignplan.page_view(view, alliance(), None, self.ROW)
        self.assertIn("Jev chose Zul'Farrak", page["jev"])


class TheLowerDungeonsLoot(unittest.TestCase):
    """preraid reads Zul'Farrak, Maraudon, Uldaman, Razorfen Downs and the
    Scarlet wings too, so a level 60 family's upgrades there count."""

    def test_a_zulfarrak_drop_is_placed_at_its_door(self):
        helm = item_row(201, "Bad Mojo Mask", 51, 1, stats=((STA, 14), (DEF, 8)))
        found = preraid.catalog(
            DROPS + [drop(201, 7271, 209, 20, name="Witch Doctor Zum'rah")],
            ANCHORS,
            REWARDS,
            ITEMS + [helm],
            TEXTS,
        )
        self.assertEqual([s.place for s in found[201].sources], ["zulfarrak"])
        gains = preraid.run_gains([preraid.plan(m, found) for m in family()])
        self.assertGreater(preraid.expected_levels(gains["zulfarrak"]), 0)

    def test_inner_maraudon_counts_for_both_wings(self):
        chest = item_row(202, "Princess's Chestguard", 55, 5, stats=((STA, 30),))
        anchors = ANCHORS + [
            {"entry": 12201, "map_id": 349, "x": 0.0, "y": 0.0, "z": -120.0},
            {"entry": 13282, "map_id": 349, "x": 1100.0, "y": -190.0, "z": -80.0},
            {"entry": 12236, "map_id": 349, "x": 750.0, "y": -220.0, "z": -48.0},
        ]
        found = preraid.catalog(
            DROPS + [drop(202, 12201, 349, 30, name="Princess Theradras")],
            anchors,
            REWARDS,
            ITEMS + [chest],
            TEXTS,
        )
        self.assertEqual(
            [s.place for s in found[202].sources], [preraid.MARAUDON_INNER]
        )
        gains = preraid.run_gains([preraid.plan(m, found) for m in family()])
        orange = preraid.expected_levels(gains["maraudon-orange"])
        self.assertGreater(orange, 0)
        self.assertEqual(orange, preraid.expected_levels(gains["maraudon-purple"]))
        self.assertTrue(
            preraid.reachable_place(preraid.MARAUDON_INNER, {"maraudon-purple"})
        )
        self.assertEqual(preraid.place_name(preraid.MARAUDON_INNER), "inner Maraudon")

    def test_the_lower_maps_are_read(self):
        for map_id in (209, 349, 70, 129, 189):
            self.assertIn(map_id, preraid.MAPS)
            self.assertIn("%d" % map_id, preraid.DROPS_SQL)


class TheBridgeAndTheSiteReadIt(unittest.TestCase):
    def test_the_bridge_reads_the_record_and_marks_the_source(self):
        for read in (
            "campaignplan.DEATHS_SQL",
            "campaignplan.WON_SQL",
            "campaignplan.KEYS_SQL",
            "campaignplan.BOSSES_SQL",
            "campaignplan.outcomes(runs, names)",
        ):
            self.assertIn(read, BRIDGE, read)
        self.assertIn("campaignplan.source_for(by_jev)", BRIDGE)
        self.assertIn("due.finish, chosen, source)", BRIDGE)

    def test_the_site_draws_the_ladder_and_jevs_reasons(self):
        self.assertIn("dungeonladder.view(facts)", SERVER)
        self.assertIn("campaignplan.CHOICE_SQL", SERVER)
        self.assertIn("f.plan.jev", PAGE)
        self.assertIn("f.ladder", PAGE)
        for key in ("r.head", "r.detail", "r.line", "ladder.title", "ladder.line"):
            self.assertIn(key, PAGE, key)

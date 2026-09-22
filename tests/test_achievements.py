"""Achievements builder tests: three tables in, a timeline out.

The judgements that matter here are the ones a plausible simplification
would quietly get wrong: which run a piece of loot belongs to (the run row
opens hours before the clear and closes minutes after it), what a boss chip
is allowed to claim before boss kills are recorded, which reward a turn-in
actually paid, and what order the cards run in.

Every row here is shaped like the live one it stands for: the Deadmines run
of 2026-09-02 (overseer_dungeon_run id 18392), its loot, and its deaths.

Tickets: mod-overseer#88, mod-overseer#152.
"""

import unittest
from datetime import datetime, timedelta

import achievements as ach

T = datetime(2026, 9, 2, 15, 0, 0)
NOW = datetime(2026, 9, 2, 18, 0, 0)
ROSTER = ["Grug", "Ugga", "Og", "Grog", "Bork"]

# The live run row, verbatim in shape. Opened by the first heartbeat at the
# door at 08:47, closed by the cold one at 16:08; the clear itself ran
# 15:20 to 16:06.
RUN = {
    "id": 18392,
    "leader_name": "Og",
    "map_id": 36,
    "state": "ended",
    "started_at": datetime(2026, 9, 2, 8, 47, 57),
    "last_progress_at": datetime(2026, 9, 2, 16, 6, 47),
    "ended_at": datetime(2026, 9, 2, 16, 8, 55),
    "ended_reason": "heartbeat cold - nobody from the roster seen on the map",
}

ITEMS = {
    7230: {
        "entry": 7230,
        "name": "Smite's Mighty Hammer",
        "Quality": 3,
        "ItemLevel": 23,
        "displayid": 19610,
    },
    2169: {
        "entry": 2169,
        "name": "Buzzer Blade",
        "Quality": 3,
        "ItemLevel": 21,
        "displayid": 20347,
    },
    5199: {
        "entry": 5199,
        "name": "Smelting Pants",
        "Quality": 3,
        "ItemLevel": 21,
        "displayid": 1,
    },
    12052: {
        "entry": 12052,
        "name": "Ring of the Moon",
        "Quality": 2,
        "ItemLevel": 21,
        "displayid": 9837,
    },
    5191: {
        "entry": 5191,
        "name": "Cruel Barb",
        "Quality": 3,
        "ItemLevel": 22,
        "displayid": 2,
    },
    3663: {
        "entry": 3663,
        "name": "Recipe: Fish Stew",
        "Quality": 1,
        "ItemLevel": 20,
        "displayid": 3,
    },
    1200: {
        "entry": 1200,
        "name": "Choice A",
        "Quality": 2,
        "ItemLevel": 20,
        "displayid": 4,
    },
    1201: {
        "entry": 1201,
        "name": "Choice B",
        "Quality": 2,
        "ItemLevel": 20,
        "displayid": 5,
    },
    9000: {
        "entry": 9000,
        "name": "Purple Thing",
        "Quality": 4,
        "ItemLevel": 60,
        "displayid": 6,
    },
}
ICONS = {19610: "inv_hammer_09", 20347: "inv_weapon_shortblade_05"}
# creature_loot_template, rare and up, for the Deadmines bosses.
DROPS = {
    644: {872, 5187},
    642: {1937, 2169},
    643: {5194, 5195},
    1763: {1156, 5199},
    646: {5192, 5196, 7230},
    645: {5197, 5198},
    647: {5200, 5201, 10403},
    639: {5193, 5202, 10399, 5191},
}


def ev(
    kind,
    who="Ugga",
    subject_id=0,
    subject_name="",
    detail="",
    level=20,
    map_id=36,
    at=T,
    **extra,
):
    row = {
        "character_name": who,
        "kind": kind,
        "subject_id": subject_id,
        "subject_name": subject_name,
        "detail": detail,
        "level": level,
        "map": map_id,
        "zone": 1581,
        "first_seen": at,
        "last_seen": at,
        "occurrences": 1,
    }
    row.update(extra)
    return row


def equip(entry, who="Ugga", at=T, map_id=36, level=20):
    return ev(
        ach.ITEM_EQUIP,
        who,
        entry,
        ITEMS.get(entry, {}).get("name", ""),
        "slot 15",
        level,
        map_id,
        at,
    )


def death(who="Grug", at=T, map_id=36, killer=""):
    return {
        "character_name": who,
        "map": map_id,
        "zone": 1581,
        "killer_name": killer or who,
        "killer_type": "player",
        "created_at": at,
    }


def build(runs=(), events=(), deaths=(), quest_rewards=None, now=NOW, items=ITEMS):
    return ach.build_achievements(
        list(runs),
        list(events),
        list(deaths),
        items,
        ICONS,
        DROPS,
        quest_rewards or {},
        ROSTER,
        now,
    )


def run_card(payload, run_id=18392):
    return next(
        c for c in payload["cards"] if c["kind"] == ach.RUN and c["id"] == run_id
    )


class BindingLootToARun(unittest.TestCase):
    """The rule the whole tab rests on: map AND time, never one alone."""

    def test_an_equip_on_the_map_inside_the_window_is_the_runs_loot(self):
        card = run_card(build([RUN], [equip(7230, "Grog", T)]))
        self.assertEqual(
            [(x["who"], x["name"]) for x in card["loot"]],
            [("Grog", "Smite's Mighty Hammer")],
        )

    def test_time_alone_is_not_enough(self):
        """The run row was open for seven hours; a green equipped in Redridge
        at noon is not Deadmines loot however long the row stayed open."""
        card = run_card(
            build([RUN], [equip(12052, "Ugga", T, map_id=0)], [death("Grug")])
        )
        self.assertEqual(card["loot"], [])

    def test_map_alone_is_not_enough(self):
        """Last week's Deadmines loot belongs to last week's run."""
        stale = equip(2169, "Ugga", RUN["started_at"] - timedelta(days=3))
        card = run_card(build([RUN], [stale], [death("Grug")]))
        self.assertEqual(card["loot"], [])

    def test_the_window_edges_are_inclusive(self):
        first = equip(2169, "Ugga", RUN["started_at"])
        last = equip(7230, "Grog", RUN["ended_at"])
        card = run_card(build([RUN], [first, last]))
        self.assertEqual(len(card["loot"]), 2)

    def test_an_active_run_binds_up_to_now(self):
        """No ended_at yet: the loot is still landing, so the window runs to
        the moment of the read rather than collapsing to nothing."""
        live = dict(RUN, state="active", ended_at=None)
        card = run_card(
            build([live], [equip(7230, "Grog", NOW - timedelta(minutes=1))])
        )
        self.assertEqual(len(card["loot"]), 1)
        self.assertEqual(card["state"], "active")
        self.assertIsNone(card["ended_at"])

    def test_deaths_bind_by_the_same_rule(self):
        inside = death("Grug", T)
        elsewhere = death("Bork", T, map_id=0)
        before = death("Og", RUN["started_at"] - timedelta(hours=1))
        card = run_card(build([RUN], [equip(7230)], [inside, elsewhere, before]))
        self.assertEqual([d["who"] for d in card["deaths"]], ["Grug"])

    def test_loot_is_sorted_by_when_it_dropped(self):
        later = equip(7230, "Grog", T + timedelta(minutes=10))
        earlier = equip(2169, "Ugga", T)
        card = run_card(build([RUN], [later, earlier]))
        self.assertEqual(
            [x["name"] for x in card["loot"]], ["Buzzer Blade", "Smite's Mighty Hammer"]
        )


class WhatARunCardSays(unittest.TestCase):
    def test_the_activity_span_is_separate_from_the_row_span(self):
        """The row says 7h 20m; the fight was 46 minutes. Both are shown and
        neither pretends to be the other."""
        events = [equip(2169, "Ugga", datetime(2026, 9, 2, 15, 41, 34))]
        deaths = [
            death("Grug", datetime(2026, 9, 2, 15, 20, 43)),
            death("Ugga", datetime(2026, 9, 2, 16, 6, 55)),
        ]
        card = run_card(build([RUN], events, deaths))
        self.assertEqual(card["duration"], "7h 20m")
        self.assertEqual(card["active_from"], "2026-09-02T15:20:43")
        self.assertEqual(card["active_to"], "2026-09-02T16:06:55")
        self.assertEqual(card["active_duration"], "46m")

    def test_members_are_whoever_the_tables_place_inside_plus_the_leader(self):
        events = [equip(2169, "Ugga"), equip(7230, "Grog")]
        card = run_card(build([RUN], events, [death("Grug")]))
        # Roster order, not order of appearance, and the leader (Og) is
        # there though nothing else places him.
        self.assertEqual(card["members"], ["Grug", "Ugga", "Og", "Grog"])
        self.assertFalse(card["all_together"])

    def test_all_five_seen_inside_is_the_family_together(self):
        events = [equip(2169, "Ugga"), equip(7230, "Grog"), equip(5199, "Bork")]
        card = run_card(build([RUN], events, [death("Grug")]))
        self.assertEqual(card["members"], ROSTER)
        self.assertTrue(card["all_together"])

    def test_a_visit_with_nothing_inside_is_counted_but_not_a_card(self):
        """Twenty-two rows for nine real runs: the door-heartbeat rows are
        visits, not achievements."""
        empty = dict(
            RUN,
            id=1,
            started_at=T - timedelta(days=1),
            ended_at=T - timedelta(days=1, minutes=-3),
        )
        payload = build([RUN, empty], [equip(7230)])
        self.assertEqual(payload["visits"], 2)
        self.assertEqual(payload["runs"], 1)
        self.assertEqual(payload["attempts"], 0)
        self.assertEqual(
            [c["id"] for c in payload["cards"] if c["kind"] == ach.RUN], [18392]
        )

    def test_level_ups_and_quests_inside_are_listed(self):
        events = [
            equip(7230, "Grog"),
            ev(ach.LEVEL_UP, "Ugga", 21, "", "from 20", 21, 36, T),
            ev(ach.QUEST_REWARD, "Bork", 166, "The Defias Brotherhood", "", 22, 36, T),
            ev(ach.QUEST_COMPLETE, "Og", 373, "Underground Assault", "", 22, 36, T),
        ]
        card = run_card(build([RUN], events))
        self.assertEqual(
            card["level_ups"],
            [{"who": "Ugga", "level": 21, "at": "2026-09-02T15:00:00"}],
        )
        self.assertEqual(
            [(q["title"], q["turned_in"]) for q in card["quests"]],
            [("The Defias Brotherhood", True), ("Underground Assault", False)],
        )

    def test_a_visit_that_gained_nothing_is_an_attempt(self):
        """A death at the door and nothing else: honest, and on the timeline,
        but not on the same footing as a run that took four bosses."""
        payload = build([RUN], [], [death("Ugga", T, killer="Defias Overseer")])
        card = run_card(payload)
        self.assertEqual(card["title"], "Dungeon attempt: The Deadmines")
        self.assertFalse(card["gained"])
        self.assertEqual(
            (payload["runs"], payload["attempts"], payload["visits"]), (0, 1, 1)
        )
        run = run_card(build([RUN], [equip(12052, "Ugga")]))
        self.assertEqual(run["title"], "Dungeon run: The Deadmines")
        self.assertTrue(run["gained"])

    def test_an_unknown_map_still_gets_a_card(self):
        odd = dict(RUN, id=2, map_id=999)
        card = run_card(build([odd], [equip(7230, map_id=999)]), 2)
        self.assertEqual(card["title"], "Dungeon run: map 999")
        self.assertEqual(card["bosses"]["total"], 0)

    def test_an_item_the_world_no_longer_knows_still_renders(self):
        card = run_card(build([RUN], [equip(424242)]))
        line = card["loot"][0]
        self.assertEqual(line["name"], "item 424242")
        self.assertEqual(line["quality_name"], ach.UNKNOWN_QUALITY)
        self.assertIsNone(line["icon"])
        self.assertEqual(line["wowhead"], "https://www.wowhead.com/wotlk/item=424242")

    def test_an_icon_comes_from_the_frozen_book_by_displayid(self):
        card = run_card(build([RUN], [equip(7230)]))
        self.assertEqual(card["loot"][0]["icon"], "inv_hammer_09")
        self.assertEqual(card["loot"][0]["quality_name"], "rare")


class InferringBosses(unittest.TestCase):
    """Until boss_kill exists, a boss is 'confirmed by loot' or 'unconfirmed';
    it is never 'not killed'."""

    def test_a_signature_drop_confirms_its_boss(self):
        card = run_card(build([RUN], [equip(7230, "Grog")]))
        known = card["bosses"]["known"]
        self.assertEqual(
            [(b["name"], b["how"]) for b in known], [("Mr. Smite", ach.BY_LOOT)]
        )
        self.assertEqual(card["bosses"]["how"], ach.BY_LOOT)
        self.assertIn(
            "Edwin VanCleef", [b["name"] for b in card["bosses"]["unconfirmed"]]
        )

    def test_a_green_confirms_nothing(self):
        card = run_card(build([RUN], [equip(12052)]))
        self.assertEqual(card["bosses"]["known"], [])

    def test_bosses_keep_the_dungeons_order_not_the_loot_order(self):
        events = [equip(7230, "Grog", T), equip(2169, "Ugga", T + timedelta(minutes=1))]
        card = run_card(build([RUN], events))
        self.assertEqual(
            [b["name"] for b in card["bosses"]["known"]],
            ["Sneed's Shredder", "Mr. Smite"],
        )

    def test_the_final_boss_is_what_makes_a_clear(self):
        four = run_card(build([RUN], [equip(7230), equip(2169), equip(5199)]))
        self.assertFalse(four["cleared"])
        self.assertFalse(four["bosses"]["final"])
        last = run_card(build([RUN], [equip(5191, "Bork")]))
        self.assertTrue(last["cleared"])

    def test_a_boss_kill_event_wins_over_loot_and_flips_the_label(self):
        """The event kind the module does not write yet. The day it does,
        the card must not still say 'inferred from loot'."""
        events = [ev(ach.BOSS_KILL, "Og", 639, "Edwin VanCleef", "", 22, 36, T)]
        card = run_card(build([RUN], events))
        self.assertEqual(card["bosses"]["how"], ach.BY_EVENT)
        self.assertEqual(
            [(b["name"], b["how"]) for b in card["bosses"]["known"]],
            [("Edwin VanCleef", ach.BY_EVENT)],
        )
        self.assertTrue(card["cleared"])

    def test_events_and_loot_combine(self):
        events = [ev(ach.BOSS_KILL, "Og", 644, "Rhahk'Zor", "", 22, 36, T), equip(7230)]
        card = run_card(build([RUN], events))
        self.assertEqual(
            [(b["name"], b["how"]) for b in card["bosses"]["known"]],
            [("Rhahk'Zor", ach.BY_EVENT), ("Mr. Smite", ach.BY_LOOT)],
        )

    def test_the_payload_says_whether_kills_are_recorded_at_all(self):
        self.assertFalse(build([RUN], [equip(7230)])["boss_kills_recorded"])
        kill = ev(ach.BOSS_KILL, "Og", 644, "Rhahk'Zor", "", 22, 36, T)
        self.assertTrue(build([RUN], [kill])["boss_kills_recorded"])


class QuestCards(unittest.TestCase):
    REWARDS = {
        127: {"items": [(3663, 1)], "choices": []},
        500: {"items": [], "choices": [1200, 1201]},
    }

    def quest(self, payload, who, qid):
        return next(
            c
            for c in payload["cards"]
            if c["kind"] == ach.QUEST and c["who"] == who and c["quest"] == qid
        )

    def test_a_turn_in_is_a_card_with_its_fixed_rewards(self):
        events = [ev(ach.QUEST_REWARD, "Bork", 127, "Selling Fish", "", 23, 0, T)]
        card = self.quest(build([], events, quest_rewards=self.REWARDS), "Bork", 127)
        self.assertEqual(card["title"], "Quest: Selling Fish")
        self.assertTrue(card["turned_in"])
        self.assertEqual(
            [(r["name"], r["count"], r["chosen"]) for r in card["rewards"]],
            [("Recipe: Fish Stew", 1, False)],
        )
        self.assertFalse(card["choice_unknown"])
        self.assertIsNone(card["level_gained"])

    def test_the_chosen_reward_is_the_equip_that_follows(self):
        events = [
            ev(ach.QUEST_REWARD, "Og", 500, "Pick One", "", 22, 0, T),
            equip(1201, "Og", T + timedelta(seconds=20), map_id=0),
        ]
        card = self.quest(build([], events, quest_rewards=self.REWARDS), "Og", 500)
        self.assertEqual(
            [(r["name"], r["chosen"]) for r in card["rewards"]], [("Choice B", True)]
        )
        self.assertFalse(card["choice_unknown"])

    def test_an_equip_outside_the_window_or_not_on_the_list_is_not_the_choice(self):
        events = [
            ev(ach.QUEST_REWARD, "Og", 500, "Pick One", "", 22, 0, T),
            equip(7230, "Og", T + timedelta(seconds=20), map_id=0),
            equip(1200, "Og", T + ach.CHOICE_WINDOW + timedelta(seconds=1), map_id=0),
            equip(1201, "Ugga", T + timedelta(seconds=5), map_id=0),
        ]
        card = self.quest(build([], events, quest_rewards=self.REWARDS), "Og", 500)
        self.assertEqual(card["rewards"], [])
        self.assertTrue(card["choice_unknown"])

    def test_a_level_in_the_next_two_minutes_is_credited_to_the_turn_in(self):
        events = [
            ev(ach.QUEST_REWARD, "Grug", 128, "Blackrock Bounty", "", 25, 0, T),
            ev(
                ach.LEVEL_UP, "Grug", 26, "", "from 25", 26, 0, T + timedelta(seconds=1)
            ),
            ev(
                ach.LEVEL_UP, "Bork", 23, "", "from 22", 23, 0, T + timedelta(seconds=1)
            ),
        ]
        card = self.quest(build([], events), "Grug", 128)
        self.assertEqual(card["level_gained"], 26)

    def test_a_completion_without_a_turn_in_is_its_own_honest_card(self):
        events = [ev(ach.QUEST_COMPLETE, "Ugga", 127, "Selling Fish", "", 21, 0, T)]
        card = self.quest(build([], events, quest_rewards=self.REWARDS), "Ugga", 127)
        self.assertFalse(card["turned_in"])

    def test_a_completion_followed_by_a_turn_in_is_one_card_not_two(self):
        events = [
            ev(ach.QUEST_COMPLETE, "Bork", 127, "Selling Fish", "", 23, 0, T),
            ev(
                ach.QUEST_REWARD,
                "Bork",
                127,
                "Selling Fish",
                "",
                23,
                0,
                T + timedelta(minutes=3),
            ),
        ]
        payload = build([], events, quest_rewards=self.REWARDS)
        cards = [c for c in payload["cards"] if c["kind"] == ach.QUEST]
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0]["turned_in"])

    def test_the_same_quest_by_two_characters_is_two_cards(self):
        events = [
            ev(ach.QUEST_REWARD, "Bork", 127, "Selling Fish", "", 23, 0, T),
            ev(ach.QUEST_REWARD, "Ugga", 127, "Selling Fish", "", 21, 0, T),
        ]
        payload = build([], events, quest_rewards=self.REWARDS)
        self.assertEqual(
            sorted(c["who"] for c in payload["cards"] if c["kind"] == ach.QUEST),
            ["Bork", "Ugga"],
        )


class LevelCards(unittest.TestCase):
    def test_only_milestone_levels_get_their_own_card(self):
        events = [
            ev(ach.LEVEL_UP, "Grug", 24, "", "from 23", 24, 0, T),
            ev(ach.LEVEL_UP, "Grug", 25, "", "from 24", 25, 0, T + timedelta(hours=1)),
        ]
        payload = build([], events)
        levels = [c for c in payload["cards"] if c["kind"] == ach.LEVEL]
        self.assertEqual(
            [(c["title"], c["who"], c["milestone"]) for c in levels],
            [("Level 25!", "Grug", True)],
        )

    def test_every_level_up_is_still_in_level_cards(self):
        events = [ev(ach.LEVEL_UP, "Grug", 24, "", "from 23", 24, 0, T)]
        self.assertEqual([c["level"] for c in ach.level_cards(events)], [24])


class Firsts(unittest.TestCase):
    def firsts(self, payload):
        return {f["key"]: f for f in payload["firsts"]}

    def test_the_first_run_is_the_earliest_that_gained_anything(self):
        older = dict(
            RUN,
            id=1,
            leader_name="Ugga",
            started_at=T - timedelta(days=2),
            ended_at=T - timedelta(days=2, hours=-1),
        )
        events = [
            equip(7230, "Grog", T),
            equip(12052, "Ugga", T - timedelta(days=2, minutes=-5)),
        ]
        f = self.firsts(build([RUN, older], events))
        self.assertEqual(f["dungeon_run"]["at"], "2026-08-31T15:05:00")
        self.assertIn("led by Ugga", f["dungeon_run"]["detail"])

    def test_an_attempt_before_the_first_run_is_not_the_first_run(self):
        wipe = dict(
            RUN,
            id=1,
            leader_name="Ugga",
            started_at=T - timedelta(days=2),
            ended_at=T - timedelta(days=2, hours=-1),
        )
        deaths = [death("Ugga", T - timedelta(days=2, minutes=-5))]
        f = self.firsts(build([RUN, wipe], [equip(7230, "Grog", T)], deaths))
        self.assertEqual(f["dungeon_run"]["at"], "2026-09-02T15:00:00")

    def test_a_clear_needs_the_final_boss(self):
        f = self.firsts(build([RUN], [equip(7230)]))
        self.assertNotIn("dungeon_clear", f)
        f = self.firsts(build([RUN], [equip(5191, "Bork")]))
        self.assertEqual(f["dungeon_clear"]["title"], "First dungeon clear")

    def test_all_five_in_one_instance(self):
        events = [equip(2169, "Ugga"), equip(7230, "Grog"), equip(5199, "Bork")]
        self.assertNotIn("all_together", self.firsts(build([RUN], events)))
        f = self.firsts(build([RUN], events, [death("Grug")]))
        self.assertEqual(f["all_together"]["title"], "All 5 in one instance")
        self.assertEqual(f["all_together"]["who"], ROSTER)

    def test_first_rare_and_first_epic_are_by_quality_not_by_run(self):
        events = [
            equip(12052, "Ugga", T - timedelta(days=5), map_id=0),
            equip(2169, "Ugga", T - timedelta(days=1), map_id=0),
            equip(7230, "Grog", T),
            equip(9000, "Og", T + timedelta(hours=1), map_id=0),
        ]
        f = self.firsts(build([], events))
        self.assertEqual(
            (f["rare_item"]["who"], f["rare_item"]["detail"]), ("Ugga", "Buzzer Blade")
        )
        self.assertEqual(f["epic_item"]["detail"], "Purple Thing")

    def test_first_to_a_level_is_the_earliest_at_or_above_it(self):
        events = [
            ev(ach.LEVEL_UP, "Grug", 25, "", "from 24", 25, 0, T),
            ev(ach.LEVEL_UP, "Ugga", 25, "", "from 24", 25, 0, T + timedelta(days=1)),
            ev(ach.LEVEL_UP, "Grug", 20, "", "from 19", 20, 0, T - timedelta(days=4)),
        ]
        f = self.firsts(build([], events))
        self.assertEqual(f["level_25"]["who"], "Grug")
        self.assertEqual(f["level_20"]["who"], "Grug")
        self.assertNotIn("level_30", f)

    def test_first_flight_waits_for_the_event_kind(self):
        self.assertNotIn("flight", self.firsts(build([], [equip(7230, map_id=0)])))
        events = [ev(ach.FLIGHT, "Og", 0, "Stormwind to Lakeshire", "", 22, 0, T)]
        f = self.firsts(build([], events))
        self.assertEqual(f["flight"]["detail"], "Stormwind to Lakeshire")

    def test_firsts_are_cards_on_the_timeline_too(self):
        payload = build([RUN], [equip(7230)])
        self.assertIn("first:dungeon_run", [c["id"] for c in payload["cards"]])


class TheTimeline(unittest.TestCase):
    def test_newest_first(self):
        events = [
            ev(ach.LEVEL_UP, "Grug", 25, "", "from 24", 25, 0, T - timedelta(days=1)),
            ev(
                ach.QUEST_REWARD,
                "Bork",
                127,
                "Selling Fish",
                "",
                23,
                0,
                T + timedelta(days=1),
            ),
        ]
        payload = build([RUN], events + [equip(7230, "Grog", T)])
        kinds = [(c["kind"], c["at"]) for c in payload["cards"]]
        self.assertEqual(kinds[0], (ach.QUEST, "2026-09-03T15:00:00"))
        self.assertEqual(
            [k for k, _ in kinds if k != ach.FIRST], [ach.QUEST, ach.RUN, ach.LEVEL]
        )
        ats = [c["at"] for c in payload["cards"]]
        self.assertEqual(ats, sorted(ats, reverse=True))

    def test_on_the_same_second_the_bigger_fact_leads(self):
        cards = [
            {"kind": ach.LEVEL, "at": "2026-09-02T16:08:55"},
            {"kind": ach.QUEST, "at": "2026-09-02T16:08:55"},
            {"kind": ach.RUN, "at": "2026-09-02T16:08:55"},
            {"kind": ach.FIRST, "at": "2026-09-02T16:08:55"},
        ]
        self.assertEqual(
            [c["kind"] for c in ach.timeline(cards)],
            [ach.RUN, ach.FIRST, ach.QUEST, ach.LEVEL],
        )

    def test_the_timeline_is_capped_but_the_firsts_are_not(self):
        events = [
            ev(
                ach.QUEST_REWARD,
                "Bork",
                i,
                "Q%d" % i,
                "",
                23,
                0,
                T - timedelta(hours=i),
            )
            for i in range(ach.MAX_CARDS + 50)
        ]
        events.append(equip(2169, "Ugga", T - timedelta(days=400), map_id=0))
        payload = build([], events)
        self.assertEqual(len(payload["cards"]), ach.MAX_CARDS)
        self.assertEqual(self_first(payload, "rare_item")["at"], "2025-07-29T15:00:00")

    def test_undated_cards_are_dropped_rather_than_sorted_first(self):
        cards = [
            {"kind": ach.FIRST, "at": None},
            {"kind": ach.RUN, "at": "2026-09-02T16:08:55"},
        ]
        self.assertEqual(len(ach.timeline(cards)), 1)


def self_first(payload, key):
    return next(f for f in payload["firsts"] if f["key"] == key)


class ReadingTheWorldTables(unittest.TestCase):
    def test_quest_rewards_from_template_rows(self):
        rows = [
            {
                "ID": 127,
                "RewardItem1": 3663,
                "RewardAmount1": 1,
                "RewardItem2": 0,
                "RewardAmount2": 0,
                "RewardItem3": 0,
                "RewardAmount3": 0,
                "RewardItem4": 100,
                "RewardAmount4": 0,
                "RewardChoiceItemID1": 1200,
                "RewardChoiceItemID2": 0,
                "RewardChoiceItemID3": 1201,
                "RewardChoiceItemID4": 0,
                "RewardChoiceItemID5": 0,
                "RewardChoiceItemID6": 0,
            }
        ]
        self.assertEqual(
            ach.quest_rewards_from_rows(rows),
            {127: {"items": [(3663, 1), (100, 1)], "choices": [1200, 1201]}},
        )

    def test_boss_drops_from_loot_rows(self):
        rows = [
            {"creature": 646, "item": 7230},
            {"creature": 646, "item": 5192},
            {"creature": 639, "item": 5191},
        ]
        self.assertEqual(
            ach.boss_drops_from_rows(rows), {646: {7230, 5192}, 639: {5191}}
        )

    def test_wanted_entries_cover_loot_rewards_and_drops(self):
        events = [equip(7230), ev(ach.QUEST_REWARD, "Bork", 127, "Selling Fish")]
        rewards = {127: {"items": [(3663, 1)], "choices": [1200]}}
        drops = {639: {5191}}
        self.assertEqual(
            ach.wanted_entries(events, rewards, drops), [1200, 3663, 5191, 7230]
        )
        self.assertEqual(ach.wanted_quests(events), [127])

    def test_wanted_bosses_follow_the_runs_maps(self):
        self.assertEqual(ach.wanted_bosses([RUN]), sorted(ach.boss_creatures(36)))
        self.assertEqual(ach.wanted_bosses([dict(RUN, map_id=999)]), [])

    def test_the_dungeon_table_names_the_final_boss_last(self):
        self.assertEqual(ach.DUNGEONS[36]["bosses"][-1], (639, "Edwin VanCleef"))
        self.assertEqual(ach.dungeon_name(36), "The Deadmines")


class TheCardBringsItsOwnWords(unittest.TestCase):
    """The Chronicle's furniture (infra#2597).

    Every sentence on a card used to be assembled in JavaScript: "led by Og,
    46m in the instance (the run row stayed open 7h 20m)" was three ternaries
    in the page. That is judgement, it lived where no test here could reach
    it, and it was free to drift from what this module believed. It is now
    built here, which is what these assertions are for.
    """

    def payload(self):
        return build(
            [RUN],
            [
                equip(7230, "Og", T.replace(hour=15, minute=30)),
                ev(
                    ach.LEVEL_UP,
                    "Bork",
                    25,
                    "",
                    "",
                    25,
                    36,
                    T.replace(hour=15, minute=40),
                ),
            ],
            [death("Grug", T.replace(hour=15, minute=35))],
        )

    def test_a_run_that_gained_something_is_a_run_and_one_that_did_not_is_an_attempt(
        self,
    ):
        """Calling a wipe at the door a dungeon run flatters the family, and
        the word is the only thing on the card that says which it was."""
        card = run_card(self.payload())
        self.assertEqual("DUNGEON RUN", ach.card_word(card))
        attempt = dict(card, gained=False)
        self.assertEqual(ach.ATTEMPT_WORD, ach.card_word(attempt))
        self.assertNotEqual(ach.card_hue(card), ach.card_hue(attempt))

    def test_every_kind_carries_a_hue_that_is_a_name_and_not_a_colour(self):
        """index.html owns what a colour looks like, and owns it twice - once
        per theme. A hex here would be right on one ground and wrong on the
        other."""
        for card in self.payload()["cards"]:
            hue = ach.card_hue(card)
            self.assertTrue(hue.isalpha(), hue)
            self.assertNotIn("#", hue)

    def test_the_body_reports_both_spans_when_they_disagree(self):
        """The run ROW and the time anything actually happened are different
        questions: this row was open seven hours and the family was inside for
        under one. A body that showed only the row would say the family spent
        an afternoon in a dungeon they walked through."""
        body = ach.card_body(run_card(self.payload()))
        self.assertIn("led by Og", body)
        self.assertIn("in the instance", body)
        self.assertIn("the run row stayed open", body)

    def test_the_body_reports_one_span_when_they_agree(self):
        """No parenthetical when there is nothing to reconcile."""
        card = dict(run_card(self.payload()))
        card["duration"] = card["active_duration"]
        self.assertNotIn("stayed open", ach.card_body(card))

    def test_a_run_still_open_says_so_in_the_body(self):
        card = dict(run_card(self.payload()), state="active")
        self.assertIn("still inside", ach.card_body(card))

    def test_every_card_gets_a_body_and_the_payload_carries_it(self):
        for card in self.payload()["cards"]:
            self.assertIn("body", card)
            self.assertTrue(card["body"], card["kind"])
            self.assertEqual(card["body"], ach.card_body(card))

    def test_the_line_is_said_by_somebody_and_names_a_fact_on_the_card(self):
        """An unattributed quote reads as the site talking, and a quote that
        invents an event is the one thing this page must never do."""
        card = run_card(self.payload())
        line = ach.card_line(card)
        self.assertEqual(card["leader"], line["who"])
        self.assertIn(card["dungeon"], line["text"])

    def test_a_run_nobody_survived_is_said_by_somebody_who_died_in_it(self):
        card = dict(run_card(self.payload()), gained=False)
        self.assertEqual(card["deaths"][0]["who"], ach.card_line(card)["who"])

    def test_a_level_card_says_the_level_it_reached(self):
        card = next(c for c in self.payload()["cards"] if c["kind"] == ach.LEVEL)
        self.assertIn(str(card["level"]), ach.card_line(card)["text"])
        self.assertEqual(card["who"], ach.card_line(card)["who"])

    def test_a_first_with_nobody_to_attribute_it_to_gets_no_line(self):
        """None, and the page draws nothing. Better than a voice belonging to
        no one."""
        self.assertIsNone(ach.card_line({"kind": ach.FIRST, "who": [], "detail": ""}))

    def test_the_strip_counts_what_the_payload_counted(self):
        payload = self.payload()
        strip = {t["label"]: t["value"] for t in payload["strip"]}
        self.assertEqual(str(payload["runs"]), strip["RUNS"])
        self.assertEqual(str(payload["attempts"]), strip["ATTEMPTS"])
        self.assertEqual(str(payload["visits"]), strip["VISITS"])
        self.assertEqual(str(len(payload["firsts"])), strip["FIRSTS"])

    def test_the_boss_tile_is_a_word_because_the_number_would_be_a_guess(self):
        """Boss kills are inferred from loot somebody equipped. A count there
        would present a guess as a measurement, and the day the module writes
        boss_kill events the tile turns into RECORDED on its own."""
        strip = {t["label"]: t["value"] for t in self.payload()["strip"]}
        self.assertEqual("INFERRED", strip["BOSS KILLS"])
        recorded = ach.strip(1, 1, 1, 1, True)
        self.assertEqual("RECORDED", recorded[-1]["value"])

    def test_the_provenance_sentence_goes_away_when_it_stops_being_true(self):
        self.assertIn("inferred", ach.provenance(False))
        self.assertEqual("", ach.provenance(True))

    def test_the_payload_carries_the_strip_and_the_sentence(self):
        payload = self.payload()
        self.assertEqual(5, len(payload["strip"]))
        self.assertTrue(payload["provenance"])


class WithoutTheRunTable(unittest.TestCase):
    """The live realm's schema predates overseer_dungeon_run. Quests and
    levels must still make a timeline out of nothing but events."""

    def test_no_runs_no_problem(self):
        events = [
            ev(ach.QUEST_REWARD, "Bork", 127, "Selling Fish", "", 23, 0, T),
            ev(ach.LEVEL_UP, "Grug", 25, "", "from 24", 25, 0, T),
        ]
        payload = build([], events)
        self.assertEqual(payload["visits"], 0)
        self.assertEqual(
            sorted(set(c["kind"] for c in payload["cards"])),
            [ach.FIRST, ach.LEVEL, ach.QUEST],
        )


class TheStory(unittest.TestCase):
    """The same rows told as sentences (#135): what happened together is one
    line naming everyone in it, and a run keeps its whole card."""

    def quest(self, who, qid, name, at, kind=ach.QUEST_REWARD, level=60):
        return ev(kind, who, qid, name, level=level, map_id=1, at=at)

    def test_three_characters_turning_in_together_is_one_sentence(self):
        a = T
        events = [
            self.quest(w, 1, "Enraged Wildkin", a + timedelta(seconds=i))
            for i, w in enumerate(["Bork", "Og", "Grog"])
        ]
        told = build(events=events)["story"]
        self.assertEqual(len(told), 1)
        self.assertEqual(
            told[0]["text"], "Og, Grog and Bork turned in Enraged Wildkin."
        )
        self.assertEqual(told[0]["who"], ["Og", "Grog", "Bork"])
        self.assertEqual(told[0]["word"], "QUEST")

    def test_two_quests_by_the_same_people_are_listed_in_one_sentence(self):
        events = [
            self.quest("Grog", 1, "Enraged Wildkin", T),
            self.quest("Grog", 2, "The Ruins of Kel'Theril", T),
        ]
        told = build(events=events)["story"]
        self.assertEqual(
            [e["text"] for e in told],
            ["Grog turned in Enraged Wildkin and The Ruins of Kel'Theril."],
        )

    def test_moments_further_apart_than_the_window_stay_apart(self):
        events = [
            self.quest("Og", 1, "A Little Luck", T),
            self.quest(
                "Bork", 1, "A Little Luck", T + ach.STORY_WINDOW + timedelta(minutes=1)
            ),
        ]
        told = build(events=events)["story"]
        self.assertEqual(
            [e["text"] for e in told],
            ["Bork turned in A Little Luck.", "Og turned in A Little Luck."],
        )

    def test_objectives_without_a_turn_in_say_it_is_still_owed(self):
        events = [
            self.quest("Og", 3, "Samophlange", T, kind=ach.QUEST_COMPLETE),
            self.quest("Bork", 3, "Samophlange", T, kind=ach.QUEST_COMPLETE),
        ]
        told = build(events=events)["story"]
        self.assertEqual(
            told[0]["text"],
            "Og and Bork finished the objectives of Samophlange, "
            "and still have to hand it in.",
        )

    def test_every_level_is_in_the_story_not_only_the_milestones(self):
        # 7: no milestone card and no "first to level 10" either.
        events = [ev(ach.LEVEL_UP, w, level=7, at=T) for w in ("Og", "Grug")]
        result = build(events=events)
        self.assertEqual(result["cards"], [])
        self.assertEqual(
            [e["text"] for e in result["story"]], ["Grug and Og reached level 7."]
        )

    def test_several_levels_in_one_moment_report_the_highest(self):
        events = [
            ev(ach.LEVEL_UP, "Og", level=lv, at=T + timedelta(seconds=lv))
            for lv in (2, 3, 4)
        ]
        told = build(events=events)["story"]
        self.assertEqual([e["text"] for e in told], ["Og reached level 4."])

    def test_a_long_quest_list_is_counted_rather_than_printed(self):
        events = [self.quest("Og", i, "Quest %d" % i, T) for i in range(1, 7)]
        told = build(events=events)["story"]
        self.assertEqual(
            told[0]["text"], "Og turned in Quest 1, Quest 2, Quest 3 and 3 more."
        )

    def test_a_run_keeps_its_whole_card(self):
        told = build(runs=[RUN], events=[equip(7230, at=T + timedelta(minutes=30))])[
            "story"
        ]
        runs = [e for e in told if e["kind"] == ach.RUN]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["card"]["dungeon"], "The Deadmines")
        self.assertIn("word", runs[0]["card"])

    def test_newest_first(self):
        events = [
            ev(ach.LEVEL_UP, "Og", level=7, at=T),
            self.quest("Og", 1, "Later", T + timedelta(hours=2)),
        ]
        told = build(events=events)["story"]
        self.assertEqual([e["kind"] for e in told], [ach.QUEST, ach.LEVEL])

    def test_a_card_with_no_date_is_left_out_rather_than_sorted(self):
        dated = {
            "at": "2026-09-02T15:00:00",
            "who": "Og",
            "turned_in": True,
            "title": "Quest: A",
            "quest_name": "A",
        }
        undated = dict(dated, at=None, who="Bork")
        told = ach.story(
            [], [dated, undated], [{"at": None, "who": "Og", "level": 7}], [], ROSTER
        )
        self.assertEqual([e["text"] for e in told], ["Og turned in A."])


class TheChapters(unittest.TestCase):
    def test_a_family_whose_read_failed_says_so(self):
        ch = ach.unread_chapter("Zug")
        self.assertEqual(ch["story"], [])
        self.assertEqual(ch["empty"], ach.UNREAD_CHAPTER)
        self.assertEqual(ch["heading"], "Zug's family")

    def test_the_faction_is_read_from_the_races(self):
        self.assertEqual(ach.faction_of([1, 3, 7]), ach.ALLIANCE)
        self.assertEqual(ach.faction_of([2, 5, 6, 8]), ach.HORDE)
        self.assertEqual(ach.faction_of([1, 2]), "")
        self.assertEqual(ach.faction_of([]), "")

    def test_the_heading_names_the_family_and_its_side(self):
        self.assertEqual(ach.chapter_heading("Zug", ach.HORDE), "Zug's family, Horde")
        self.assertEqual(ach.chapter_heading("", ""), "The family")

    def test_a_chapter_carries_its_story_and_strip(self):
        built = build(events=[ev(ach.LEVEL_UP, "Og", level=11, at=T)])
        ch = ach.chapter(built, "Grug", ach.ALLIANCE)
        self.assertEqual(ch["heading"], "Grug's family, Alliance")
        self.assertEqual(ch["story"], built["story"])
        self.assertEqual(ch["strip"], built["strip"])
        self.assertEqual(ch["empty"], "")
        self.assertTrue(ach.chapter(build(), "Zug", ach.HORDE)["empty"])


if __name__ == "__main__":
    unittest.main()

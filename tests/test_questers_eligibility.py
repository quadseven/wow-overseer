"""A quester takes only a quest the world will give it (#1732, #1716).

The worldserver answers a take with Player::CanTakeQuest and CanAddQuest; the
bridge's mirror of it (questers.open_to) read race, class, level, PrevQuestID
and a positive exclusive group only. Everything else it missed made a quester
walk to a giver, be refused "not eligible (level, race, class, prerequisite or
exclusive group)" three times, and file a working quest as broken. Each test
below is one rule the mirror missed, on the world's own rows for a quest the
realm log shows refused that way (2026-10-30 to 2026-11-03).
"""

import contextlib
import unittest
from unittest import mock

import classquest
import questers
from test_guildsocial_bridge import bridge
from test_questers import ended, giver, started

WESTFALL, TIRISFAL, DEATHKNELL = 40, 85, 154
ASHENVALE, STONETALON, DESOLACE, LOCH_MODAN, WETLANDS = 331, 406, 405, 38, 11
REDRIDGE = 44
ALLIANCE, HORDE = 1101, 690
DWARF, NIGHT_ELF, GNOME, TAUREN, ORC, HUMAN = 3, 4, 7, 6, 2, 1
WARSONG_OUTRIDERS = 889


def row(qid, title, sort, level, min_level, races=0, **extra):
    """A QUESTS_SQL row: the world's quest_template and quest_template_addon
    columns for one quest, as the bridge reads them."""
    out = {
        "id": qid,
        "title": title,
        "sort": sort,
        "zone": sort,
        "level": level,
        "info": 0,
        "min_level": min_level,
        "races": races,
        "classes": 0,
        "prev_signed": extra.pop("prev", 0),
        "prev": 0,
        "exclusive": extra.pop("exclusive", 0),
        "reward": 0,
        "display": 0,
        "grp": 0,
    }
    out.update(extra)
    out["prev"] = out["prev_signed"]
    return out


def catalogue(rows, links=(), conditions=()):
    """The quester catalogue of these rows, each quest given and taken by one
    creature spawned in Kalimdor or the Eastern Kingdoms."""
    givers, starts, ends = [], [], []
    for n, r in enumerate(rows):
        guid, entry = 5000 + n, 900 + n
        for role in ("start", "end"):
            givers.append(giver(r["id"], role, guid, entry, 10.0 * n, 0.0, map_id=1))
        starts.append(started(r["id"], entry))
        ends.append(ended(r["id"], entry))
    return questers.catalogue(
        rows, givers, [], [], starts, ends, links, condition_rows=conditions
    )


def member(name, race, level, zone, class_id=1, **kw):
    return questers.Member(
        name=name,
        level=level,
        race=race,
        class_id=class_id,
        map_id=1,
        x=0.0,
        y=0.0,
        zone_id=zone,
        online=True,
        **kw,
    )


def link(qid, next_id=0, breadcrumb_for=0, exclusive=0, chain_next=0):
    """A LINKS_SQL row."""
    return {
        "id": qid,
        "next": next_id,
        "crumb_for": breadcrumb_for,
        "exclusive": exclusive,
        "chain_next": chain_next,
    }


class AProvidedItemNeedsABagSlot(unittest.TestCase):
    """CanAddQuest: a quest that hands over an item (StartItem) cannot be
    taken while the item cannot be stored. Every quester of #1732 and #1716
    stood with 0 free bag slots (Bromli 0/22, Kellan 0/16, Hulani 0/16)."""

    def test_westfall_stew_waits_for_a_free_slot(self):
        cat = catalogue(
            [row(36, "Westfall Stew", WESTFALL, 10, 9, ALLIANCE, provided0=2832)]
        )
        full = member("Bromli", DWARF, 29, WESTFALL, free_slots=0)
        self.assertNotIn(36, questers.in_reach(cat, full, WESTFALL))
        room = member("Bromli", DWARF, 29, WESTFALL, free_slots=1)
        self.assertIn(36, questers.in_reach(cat, room, WESTFALL))

    def test_a_rogues_deal_waits_for_a_free_slot(self):
        cat = catalogue(
            [row(8, "A Rogue's Deal", DEATHKNELL, 5, 1, HORDE, provided0=7628)]
        )
        full = member("Hulani", TAUREN, 5, TIRISFAL, free_slots=0)
        self.assertNotIn(8, questers.in_reach(cat, full, TIRISFAL))
        self.assertIn(
            8,
            questers.in_reach(
                cat, member("Hulani", TAUREN, 5, TIRISFAL, free_slots=4), TIRISFAL
            ),
        )

    def test_bag_room_not_read_is_no_reason_to_hold_back(self):
        cat = catalogue(
            [row(36, "Westfall Stew", WESTFALL, 10, 9, ALLIANCE, provided0=2832)]
        )
        self.assertIn(
            36, questers.in_reach(cat, member("Bromli", DWARF, 29, WESTFALL), WESTFALL)
        )

    def test_a_quest_with_no_provided_item_needs_no_slot(self):
        cat = catalogue([row(36, "Westfall Stew", WESTFALL, 10, 9, ALLIANCE)])
        full = member("Bromli", DWARF, 29, WESTFALL, free_slots=0)
        self.assertIn(36, questers.in_reach(cat, full, WESTFALL))


class AProvidedObjectiveCanBeTurnedIn(unittest.TestCase):
    """The ticket snapshot has one RequiredItem that is the quest's StartItem.

    `row` uses the questers.QUESTS_SQL fields; `catalogue` supplies fixture-only
    giver and ender rows, and the holder models the counters from LOG_SQL.
    """

    def test_quest_333_can_be_taken_and_handed_in(self):
        cloth_request = 2724
        cat = catalogue(
            [
                row(
                    333,
                    "Harlan Needs a Resupply",
                    1519,
                    2,
                    1,
                    provided0=cloth_request,
                    item1=cloth_request,
                    item_count1=1,
                )
            ]
        )
        quester = member("Quester A", HUMAN, 2, 1519)

        self.assertIn(333, questers.in_reach(cat, quester, 1519))
        take_plan = questers.plan(cat, quester, questers.Clock(), 0.0)
        self.assertEqual(take_plan.broken, ())
        take = take_plan.move
        self.assertEqual((take.kind, take.quest), (classquest.TAKE, 333))

        holder = member(
            "Quester A",
            HUMAN,
            2,
            1519,
            quest_log={333: questers.STATUS_INCOMPLETE},
            quest_progress={333: 1},
            quest_item_objectives={333: {cloth_request: 1}},
        )
        turn_in = questers.plan(cat, holder, questers.Clock(), 0.0).move
        self.assertEqual((turn_in.kind, turn_in.quest), (classquest.TURN_IN, 333))


class AQuestNamedAsNextIsAPrerequisite(unittest.TestCase):
    """ObjectMgr: a quest whose NextQuestID names X is one of X's previous
    quests, beside X's own PrevQuestID. Any one rewarded opens X, unless that
    quest's exclusive group is negative: then every quest of its group must
    be rewarded (SatisfyQuestPreviousQuest)."""

    def test_broken_tears_needs_one_of_the_quests_that_name_it(self):
        cat = catalogue(
            [row(1369, "Broken Tears", DESOLACE, 33, 30)],
            [
                link(1367, next_id=1369, chain_next=1369),
                link(1386, next_id=1369, chain_next=1369),
            ],
        )
        fizzik = member("Fizzik", GNOME, 32, DESOLACE)
        self.assertNotIn(1369, questers.in_reach(cat, fizzik, DESOLACE))
        done = member("Fizzik", GNOME, 32, DESOLACE, quests_done=frozenset({1386}))
        self.assertIn(1369, questers.in_reach(cat, done, DESOLACE))

    def test_update_for_sentinel_thenysil_needs_its_whole_negative_group(self):
        cat = catalogue(
            [row(1082, "Update for Sentinel Thenysil", STONETALON, 22, 17, ALLIANCE)],
            [
                link(1083, next_id=1082, exclusive=-1083),
                link(1084, next_id=1082, exclusive=-1083),
            ],
        )
        pindle = member("Pindle", NIGHT_ELF, 29, STONETALON)
        self.assertNotIn(1082, questers.in_reach(cat, pindle, STONETALON))
        one = member("Pindle", NIGHT_ELF, 29, STONETALON, quests_done=frozenset({1083}))
        self.assertNotIn(1082, questers.in_reach(cat, one, STONETALON))
        both = member(
            "Pindle", NIGHT_ELF, 29, STONETALON, quests_done=frozenset({1083, 1084})
        )
        self.assertIn(1082, questers.in_reach(cat, both, STONETALON))


class ARewardConditionIsAPrerequisite(unittest.TestCase):
    """Quest-available condition rows (SourceType 19) are part of the core's
    take gate, even when a quest has no objective rows or NextQuestID links.
    The condition values here are synthetic and test the reader path only."""

    def test_a_no_objective_quest_waits_for_its_reward_condition(self):
        quest_id, prerequisite = 90001, 90002
        cat = catalogue(
            [row(quest_id, "Conditional quest", ASHENVALE, 30, 20)],
            links=[link(90005, next_id=quest_id)],
            conditions=[
                {
                    "quest": quest_id,
                    "grp": 0,
                    "kind": 47,
                    "value1": prerequisite,
                    "value2": classquest.QUEST_STATE_REWARDED,
                    "negative": 0,
                }
            ],
        )
        waiting = member("Quester", ORC, 30, ASHENVALE)
        ready = member(
            "Quester", ORC, 30, ASHENVALE, quests_done=frozenset({prerequisite})
        )

        self.assertNotIn(quest_id, questers.in_reach(cat, waiting, ASHENVALE))
        self.assertIn(quest_id, questers.in_reach(cat, ready, ASHENVALE))


class ABreadcrumbClosesWithItsTarget(unittest.TestCase):
    """SatisfyQuestBreadcrumb: a breadcrumb cannot be taken once its target
    is held or rewarded, and the target cannot be taken while one of its
    breadcrumbs is held."""

    def test_deliveries_to_sven_closes_once_svens_revenge_is_done(self):
        cat = catalogue(
            [row(164, "Deliveries to Sven", WETLANDS, 23, 17, ALLIANCE, crumb_for=95)],
            [link(164, breadcrumb_for=95)],
        )
        durga = member("Durga", DWARF, 26, WETLANDS, quests_done=frozenset({95}))
        self.assertNotIn(164, questers.in_reach(cat, durga, WETLANDS))
        self.assertIn(
            164, questers.in_reach(cat, member("Durga", DWARF, 26, WETLANDS), WETLANDS)
        )

    def test_the_target_waits_while_its_breadcrumb_is_held(self):
        cat = catalogue(
            [
                row(95, "Sven's Revenge", WETLANDS, 25, 20, ALLIANCE),
                row(
                    164, "Deliveries to Sven", WETLANDS, 23, 17, ALLIANCE, crumb_for=95
                ),
            ],
            [link(164, breadcrumb_for=95)],
        )
        holding = member("Durga", DWARF, 26, WETLANDS, quest_log={164: 3})
        self.assertNotIn(95, questers.in_reach(cat, holding, WETLANDS))


class AChainClosesBehindItself(unittest.TestCase):
    """SatisfyQuestNextChain / SatisfyQuestPrevChain: a quest cannot be taken
    once the quest its RewardNextQuest names is held or rewarded, nor while a
    quest whose RewardNextQuest names it is held."""

    def test_mountaineer_stormpikes_task_closes_once_stormpikes_order_is_done(self):
        cat = catalogue(
            [
                row(
                    1339,
                    "Mountaineer Stormpike's Task",
                    LOCH_MODAN,
                    15,
                    9,
                    ALLIANCE,
                    chain_next=1338,
                )
            ]
        )
        mirra = member("Mirra", HUMAN, 18, LOCH_MODAN, quests_done=frozenset({1338}))
        self.assertNotIn(1339, questers.in_reach(cat, mirra, LOCH_MODAN))

    def test_broken_tears_waits_while_magram_alliance_is_held(self):
        cat = catalogue(
            [row(1369, "Broken Tears", DESOLACE, 33, 30)],
            [
                link(1367, next_id=1369, chain_next=1369),
                link(1386, next_id=1369, chain_next=1369),
            ],
        )
        held = member(
            "Fizzik",
            GNOME,
            32,
            DESOLACE,
            quests_done=frozenset({1386}),
            quest_log={1367: 3},
        )
        self.assertNotIn(1369, questers.in_reach(cat, held, DESOLACE))


class AReputationGateHolds(unittest.TestCase):
    """SatisfyQuestReputation: RequiredMinRepFaction / RequiredMinRepValue."""

    def test_outrider_care_package_needs_honored_warsong_outriders(self):
        cat = catalogue(
            [
                row(
                    7866,
                    "Outrider Basic Care Package",
                    ASHENVALE,
                    34,
                    25,
                    HORDE,
                    exclusive=7866,
                    min_rep_faction=WARSONG_OUTRIDERS,
                    min_rep_value=3000,
                )
            ]
        )
        gorvash = member(
            "Gorvash", ORC, 33, ASHENVALE, reputation={WARSONG_OUTRIDERS: 0}
        )
        self.assertNotIn(7866, questers.in_reach(cat, gorvash, ASHENVALE))
        honored = member(
            "Gorvash", ORC, 33, ASHENVALE, reputation={WARSONG_OUTRIDERS: 3000}
        )
        self.assertIn(7866, questers.in_reach(cat, honored, ASHENVALE))


class TheBridgeReadsWhatTheRulesNeed(unittest.TestCase):
    def test_the_quest_read_carries_the_columns(self):
        for column in (
            "StartItem",
            "RewardNextQuest",
            "BreadcrumbForQuestId",
            "RequiredMinRepFaction",
            "RequiredMinRepValue",
            "RequiredMaxRepFaction",
        ):
            self.assertIn(column, questers.QUESTS_SQL)

    def test_the_links_read_names_every_relation(self):
        for column in (
            "NextQuestID",
            "BreadcrumbForQuestId",
            "ExclusiveGroup",
            "RewardNextQuest",
        ):
            self.assertIn(column, questers.LINKS_SQL)

    def test_the_condition_read_uses_the_worlds_quest_available_rows(self):
        self.assertIn("SourceTypeOrReferenceId = 19", classquest.CONDITIONS_SQL)
        self.assertIn("ConditionTypeOrReference", classquest.CONDITIONS_SQL)

    def test_reputation_rows_become_the_members_standing(self):
        rows = [{"guid": 7, "name": "Gorvash", "level": 33, "race": ORC, "class_id": 1}]
        rep = [{"guid": 7, "faction": WARSONG_OUTRIDERS, "standing": 2500}]
        (m,) = questers.members_from_rows(rows, [], [], rep)
        self.assertEqual(m.reputation, {WARSONG_OUTRIDERS: 2500})
        (unread,) = questers.members_from_rows(rows, [], [])
        self.assertIsNone(unread.reputation)


class TheBridgeHandsTheQuesterItsRoom(unittest.TestCase):
    """bridge._fetch_quester_facts gives each quester its free bag slots and
    its reputation, so the rules above are judged on the live realm."""

    def test_free_slots_and_reputation_reach_the_member(self):
        def rows_for(sql):
            if sql.startswith("SELECT c.guid, c.name"):
                return [
                    {
                        "guid": 7,
                        "name": "Bromli",
                        "level": 29,
                        "race": DWARF,
                        "class_id": 2,
                    }
                ]
            if "character_reputation" in sql:
                return [{"guid": 7, "faction": WARSONG_OUTRIDERS, "standing": 10}]
            return []

        class Cur:
            def execute(self, sql, args=()):
                self.rows = rows_for(sql)

            def fetchall(self):
                return self.rows

        class Conn:
            def cursor(self):
                return contextlib.nullcontext(Cur())

        with mock.patch.multiple(
            bridge,
            _connect=lambda: contextlib.nullcontext(Conn()),
            _fetch_free_slots=lambda names: {"Bromli": 0},
            _hunts_open=lambda cur: None,
        ):
            members = bridge._fetch_quester_facts(["Bromli"])[0]
        self.assertEqual([(m.name, m.free_slots) for m in members], [("Bromli", 0)])
        self.assertEqual(members[0].reputation, {WARSONG_OUTRIDERS: 10})

    def test_the_catalogue_reads_the_links(self):
        quest = row(1082, "Update for Sentinel Thenysil", STONETALON, 22, 17, ALLIANCE)

        def rows_for(sql):
            if sql == questers.QUESTS_SQL:
                return [quest]
            if sql == questers.LINKS_SQL:
                return [
                    link(1083, next_id=1082, exclusive=-1083),
                    link(1084, next_id=1082, exclusive=-1083),
                ]
            if "creature_queststarter" in sql:
                return [started(1082, 900)]
            return []

        class Cur:
            def execute(self, sql, args=()):
                self.rows = rows_for(sql)

            def fetchall(self):
                return self.rows

        class Conn:
            def cursor(self):
                return contextlib.nullcontext(Cur())

        spawned = [giver(1082, "start", 5000, 900, 0.0, 0.0, map_id=1)]
        with (
            mock.patch.multiple(
                bridge,
                _QUESTER_CATALOGUE=None,
                _connect=lambda: contextlib.nullcontext(Conn()),
                _class_rows=lambda *a: [],
            ),
            mock.patch.object(bridge, "_job_read") as read,
        ):
            read.side_effect = lambda cur, what, sql, params=(): (
                spawned if what == "quester quest givers" else rows_for(sql)
            )
            cat = bridge._quester_catalogue()
        self.assertEqual(cat.facts[1082].before, ((1083, 1084),))

    def test_the_catalogue_reads_and_applies_quest_available_conditions(self):
        quest_id, prerequisite = 90003, 90004
        quest = row(quest_id, "Conditional quest", ASHENVALE, 30, 20)
        condition_row = {
            "quest": quest_id,
            "grp": 0,
            "kind": 47,
            "value1": prerequisite,
            "value2": classquest.QUEST_STATE_REWARDED,
            "negative": 0,
        }

        def rows_for(sql):
            if sql == questers.QUESTS_SQL:
                return [quest]
            if sql == questers.LINKS_SQL:
                return []
            if sql == classquest.CONDITIONS_SQL.format(quests=str(quest_id)):
                return [condition_row]
            if "creature_queststarter" in sql:
                return [started(quest_id, 900)]
            return []

        class Cur:
            def execute(self, sql, args=()):
                self.rows = rows_for(sql)

            def fetchall(self):
                return self.rows

        class Conn:
            def cursor(self):
                return contextlib.nullcontext(Cur())

        spawned = [giver(quest_id, "start", 5000, 900, 0.0, 0.0, map_id=1)]
        with (
            mock.patch.multiple(
                bridge,
                _QUESTER_CATALOGUE=None,
                _connect=lambda: contextlib.nullcontext(Conn()),
                _class_rows=lambda *a: [],
            ),
            mock.patch.object(bridge, "_job_read") as read,
        ):
            read.side_effect = lambda cur, what, sql, params=(): (
                spawned if what == "quester quest givers" else rows_for(sql)
            )
            cat = bridge._quester_catalogue()

        waiting = member("Quester", ORC, 30, ASHENVALE)
        self.assertNotIn(quest_id, questers.in_reach(cat, waiting, ASHENVALE))
        self.assertIn(
            quest_id,
            questers.in_reach(
                cat,
                member(
                    "Quester",
                    ORC,
                    30,
                    ASHENVALE,
                    quests_done=frozenset({prerequisite}),
                ),
                ASHENVALE,
            ),
        )


class Quest120MessengerToStormwind(unittest.TestCase):
    """A take refused as not eligible keeps the core's words: a member in
    reach already meets the quest's MinLevel, so MinLevel is never the cause."""

    def test_a_refusal_in_reach_names_no_minlevel_cause(self):
        # The QUESTS_SQL row exposes QuestLevel as `level` and MinLevel as
        # `min_level`; the worldserver enforces MinLevel when accepting.
        cat = catalogue(
            [row(120, "Messenger to Stormwind", REDRIDGE, 14, 15, ALLIANCE)]
        )
        level_14 = member("Quester", HUMAN, 14, REDRIDGE)
        level_15 = member("Quester", HUMAN, 15, REDRIDGE)

        self.assertNotIn(120, questers.in_reach(cat, level_14, REDRIDGE))
        self.assertIn(120, questers.in_reach(cat, level_15, REDRIDGE))
        reason = questers._giver_failure(
            cat,
            level_15,
            120,
            gone=frozenset(),
            refused={
                ("take", 120): (
                    3,
                    "not eligible (level, race, class, prerequisite or exclusive group)",
                )
            },
        )
        self.assertEqual(
            "the quest giver would not give it: not eligible "
            "(level, race, class, prerequisite or exclusive group)",
            reason,
        )

    def test_the_ledger_row_stores_the_core_words(self):
        # The quester's take pass finds the refusals and the bridge writes the
        # broken quest into the ledger (BROKEN_SQL): the explanation must reach
        # the reason column, not only the pure seam above.
        cat = catalogue(
            [row(120, "Messenger to Stormwind", REDRIDGE, 14, 15, ALLIANCE)]
        )
        quester = member("Durga", HUMAN, 15, REDRIDGE)
        words = "not eligible (level, race, class, prerequisite or exclusive group)"
        tried = [
            questers.Attempt(
                "Durga", "take quest:120", "refused", reason=words, age_minutes=n
            )
            for n in range(questers.FAILS_BEFORE_BROKEN)
        ]
        _takes, never_held = questers._takes(cat, quester, set(), frozenset(), tried)
        self.assertEqual([120], [b.quest for b in never_held])

        executed = []

        class Cursor:
            def execute(self, sql, args=()):
                executed.append((sql, args))

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def cursor(self):
                return contextlib.nullcontext(Cursor())

        with mock.patch.object(bridge, "_connect", return_value=Conn()):
            self.assertTrue(bridge._record_quest_broken(never_held[0]))
        self.assertEqual([questers.BROKEN_SQL], [sql for sql, _args in executed])
        self.assertEqual(
            (
                120,
                False,
                "the quest giver would not give it: " + words,
                "Durga",
            ),
            executed[0][1],
        )


class Quest131DeliveringDaffodils(unittest.TestCase):
    """SatisfyQuestLevel: the world refuses a take over the quest's MaxLevel
    (quest_template_addon.MaxLevel, 0 for no cap) as it refuses one under its
    MinLevel. The mirror read MinLevel only, so a quester over the cap walked
    to the giver, was refused "not eligible" three times, and filed Delivering
    Daffodils broken. The level 25 cap below is a fixture value, not read off
    the live world row."""

    def test_a_quester_over_the_max_level_does_not_walk_to_the_giver(self):
        cat = catalogue(
            [row(131, "Delivering Daffodils", REDRIDGE, 15, 13, ALLIANCE, max_level=25)]
        )
        over = member("Bromli", DWARF, 26, REDRIDGE)
        self.assertNotIn(131, questers.in_reach(cat, over, REDRIDGE))
        at_cap = member("Bromli", DWARF, 25, REDRIDGE)
        self.assertIn(131, questers.in_reach(cat, at_cap, REDRIDGE))

    def test_no_max_level_is_no_cap(self):
        cat = catalogue([row(131, "Delivering Daffodils", REDRIDGE, 15, 13, ALLIANCE)])
        self.assertIn(
            131, questers.in_reach(cat, member("Bromli", DWARF, 60, REDRIDGE), REDRIDGE)
        )

    def test_the_quest_read_carries_max_level(self):
        self.assertIn("a.MaxLevel, 0) AS max_level", questers.QUESTS_SQL)


if __name__ == "__main__":
    unittest.main()

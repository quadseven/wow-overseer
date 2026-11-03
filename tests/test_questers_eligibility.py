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


def catalogue(rows, links=()):
    """The quester catalogue of these rows, each quest given and taken by one
    creature spawned in Kalimdor or the Eastern Kingdoms."""
    givers, starts, ends = [], [], []
    for n, r in enumerate(rows):
        guid, entry = 5000 + n, 900 + n
        for role in ("start", "end"):
            givers.append(giver(r["id"], role, guid, entry, 10.0 * n, 0.0, map_id=1))
        starts.append(started(r["id"], entry))
        ends.append(ended(r["id"], entry))
    return questers.catalogue(rows, givers, [], [], starts, ends, links)


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


if __name__ == "__main__":
    unittest.main()

"""Westfall Stew (quest 38, #1745): a quester can finish it, a stall held from
before the item-dropper hunt is retried once and never again, and an abandon
carries a reason in the ledger.

The world rows are shaped as questers.QUESTS_SQL, classquest.LOOT_SQL and
classquest.SPAWNS_SQL read them; the quest log row as questers.LOG_SQL reads
character_queststatus (itemcount1..6 beside each RequiredItemId). The item and
creature ids are illustrative, not read from a world database: the test proves
the rule, not the world's rows.
"""

import unittest
from unittest import mock

import classquest
import questers
import questledger
from test_guildsocial_bridge import bridge
from test_questers import HUMAN, PRIEST, WESTFALL, giver, quest, spawn, world

STEW = 38
# Four ingredients, three of each; each dropped by its own creature.
INGREDIENTS = {729: 1109, 730: 515, 731: 157, 732: 454}
WANTED = 3


def stew_world():
    stew = quest(STEW, WESTFALL, 13, title="Westfall Stew")
    for i, item in enumerate(INGREDIENTS, start=1):
        stew.update({"item%d" % i: item, "item_count%d" % i: WANTED})
    return world(
        extra_quests=[stew],
        extra_givers=[
            giver(STEW, "start", 5038, 235, 0, 0),
            giver(STEW, "end", 5038, 235, 0, 0),
        ],
        extra_spawns=[
            spawn(6000 + i, entry, 100.0 * i, 0, level=12)
            for i, entry in enumerate(INGREDIENTS.values(), start=1)
        ],
        extra_loot=[
            {"item": item, "entry": entry} for item, entry in INGREDIENTS.items()
        ],
    )


def log_row(counts, status=questers.STATUS_INCOMPLETE):
    """A questers.LOG_SQL row for quest 38 with these ingredient counts."""
    row = {"guid": 8, "quest": STEW, "status": status}
    row["progress"] = sum(counts.get(item, 0) for item in INGREDIENTS)
    for i in range(1, 7):
        item = list(INGREDIENTS)[i - 1] if i <= len(INGREDIENTS) else 0
        row["item%d" % i] = item
        row["itemcount%d" % i] = counts.get(item, 0)
    for i in range(1, 5):
        row["npc%d" % i] = 0
        row["mobcount%d" % i] = 0
    return row


def holder(counts, status=questers.STATUS_INCOMPLETE):
    """Mirra in Westfall at level 13, holding quest 38, read off LOG_SQL."""
    member_row = {
        "guid": 8,
        "name": "Mirra",
        "level": 13,
        "race": HUMAN,
        "class_id": PRIEST,
        "online": 1,
        "map_id": 0,
        "pos_x": 0.0,
        "pos_y": 0.0,
        "zone_id": WESTFALL,
    }
    (member,) = questers.members_from_rows(
        [member_row],
        [log_row(counts, status)],
        [{"guid": 8, "quest": q} for q in (20, 21)],
    )
    return member


class AQuesterCanFinishWestfallStew(unittest.TestCase):
    def test_each_hunt_is_for_an_ingredient_still_short(self):
        cat = stew_world()
        counts = {}
        hunted = []
        for _ in INGREDIENTS:
            move = questers.plan(cat, holder(counts), questers.Clock(), 0.0).move
            self.assertEqual((move.kind, move.quest), (classquest.HUNT, STEW))
            item = next(i for i, e in INGREDIENTS.items() if e == move.spot.entry)
            self.assertLess(counts.get(item, 0), WANTED)
            hunted.append(move.spot.entry)
            counts[item] = WANTED
        self.assertEqual(sorted(hunted), sorted(INGREDIENTS.values()))

    def test_the_full_stew_is_handed_in(self):
        full = {item: WANTED for item in INGREDIENTS}
        member = holder(full, status=questers.STATUS_COMPLETE)
        move = questers.plan(stew_world(), member, questers.Clock(), 0.0).move
        self.assertEqual((move.kind, move.quest), (classquest.TURN_IN, STEW))


class AStallFromBeforeTheHuntIsRetriedOnce(unittest.TestCase):
    def test_a_stall_nobody_judged_is_retried(self):
        member = holder({729: WANTED})
        retry = questers.stalled_holds_with_actionable_objectives(
            stew_world(), member, {STEW: questers.STALLED}
        )
        self.assertEqual(retry, frozenset({STEW}))

    def test_a_judged_stall_is_not_retried(self):
        member = holder({729: WANTED})
        retry = questers.stalled_holds_with_actionable_objectives(
            stew_world(), member, {STEW: questers.STALLED}, judged=frozenset({STEW})
        )
        self.assertEqual(retry, frozenset())

    def test_a_retried_stall_is_judged(self):
        member = holder({729: WANTED})
        judged = questers.judged_stalls(frozenset(), {STEW}, (), {}, member.quest_log)
        self.assertEqual(judged, frozenset({STEW}))

    def test_a_stall_found_now_is_judged(self):
        member = holder({729: WANTED})
        found = (questers.Broken("Mirra", STEW, "Westfall Stew", questers.STALLED),)
        judged = questers.judged_stalls(
            frozenset(), (), found, {STEW: questers.STALLED}, member.quest_log
        )
        self.assertEqual(judged, frozenset({STEW}))

    def test_a_quest_neither_held_nor_logged_is_forgotten(self):
        judged = questers.judged_stalls(frozenset({STEW, 99}), (), (), {99: "x"}, {})
        self.assertEqual(judged, frozenset({99}))

    def test_another_broken_reason_is_not_judged(self):
        found = (questers.Broken("Mirra", STEW, "", questers.ENDER_MISSING),)
        judged = questers.judged_stalls(
            frozenset(), (), found, {STEW: questers.ENDER_MISSING}, {}
        )
        self.assertEqual(judged, frozenset())


class TheJudgedStallsOutliveARestart(unittest.TestCase):
    def test_a_written_memo_reads_back(self):
        written = []
        with mock.patch.object(bridge, "_memo_upsert", lambda *a: written.append(a)):
            bridge._quester_judged_write({"Mirra": frozenset({STEW, 20})}, 1.0)
        (row,) = written
        self.assertEqual(row[0], bridge.QUESTER_JUDGED_MEMO)
        stored = {"Mirra": (row[2], 1.0)}
        read = lambda kind: stored if kind == bridge.QUESTER_JUDGED_MEMO else {}  # noqa: E731
        with mock.patch.object(bridge, "_memo_read", read):
            judged = bridge._quester_judged()
        self.assertEqual(judged, {"Mirra": frozenset({20, STEW})})

    def test_an_empty_set_deletes_its_memo(self):
        deleted = []
        with (
            mock.patch.object(bridge, "_memo_upsert"),
            mock.patch.object(bridge, "_memo_delete", lambda *a: deleted.append(a)),
        ):
            bridge._quester_judged_write({"Mirra": frozenset()}, 1.0)
        self.assertEqual(deleted, [(bridge.QUESTER_JUDGED_MEMO, "Mirra")])


class AnAbandonSaysWhy(unittest.TestCase):
    def test_an_abandon_nobody_recorded_broken_is_explained(self):
        taken = {
            "quest": STEW,
            "guid": 8,
            "character_name": "Mirra",
            "state": questledger.TAKEN,
            "first_taken": None,
            "finished": None,
            "reason": "",
        }
        (entry,) = questledger.changes({8: "Mirra"}, [taken], [], [], "now")
        self.assertEqual(entry.state, questledger.ABANDONED)
        self.assertEqual(entry.reason, questledger.ABANDONED_REASON)
        self.assertTrue(entry.reason)


if __name__ == "__main__":
    unittest.main()

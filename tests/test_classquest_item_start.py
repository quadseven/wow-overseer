"""Redemption's chain starts a quest from an item, and the world says what each
quest needs (wow-overseer#2297).

The class book wrote `take quest:1647` (dwarf) or `take quest:1643` (human) and
the world refused each as not eligible. The rows below are acore_world's.

The chain is 1645 (Tiza Battleforge; its reward is item 6916) -> item 6916 starts
1646 -> hand 1646 in at Tiza -> 1647 -> 1648 (reward 7328/7329). The human chain
is 1641 (item 6775) -> item starts 1642 -> 1643 -> 1644. No creature or object
gives 1646 or 1642. 2997, 2999 and 3000 (the "see Tiza" errands) name 1647 as
their NextQuestID, so #1282 treated any of them rewarded as opening 1647, but the
world's `conditions` rows (SourceTypeOrReferenceId 19, ConditionTypeOrReference
47, state 64 = rewarded) say 1647 needs 1646 rewarded and 1643 needs 1642, and
1645 is offered once one of the errands is rewarded (ConditionTypeOrReference 8,
one ElseGroup each).
"""

import pathlib
import sqlite3
import unittest

import classquest
import guildjobs
from test_classquest import EASTERN, who
from test_classquest_opened_by import (
    BRANDUR,
    BROMOS,
    DWARF,
    GRAYSON,
    HUMAN,
    JOHN,
    PALADIN,
    TIZA,
    tome,
)

HUMAN_MASK = 1
DUTHORIAN = dict(
    guid=1790, entry=6171, map_id=0, x=-5015.0, y=-1054.0, name="Duthorian Rall"
)
TOME_DWARF, TOME_HUMAN = 6916, 6775


def rows():
    return [
        tome(1645, "The Tome of Divinity", ritem1=TOME_DWARF),
        tome(1646, "The Tome of Divinity", next=1647),
        tome(2997, "Tome of Divinity", next=1647, exclusive=2997),
        tome(2999, "Tome of Divinity", next=1647, exclusive=2997),
        tome(3000, "Tome of Divinity", next=1647, exclusive=2997),
        tome(1647, "The Tome of Divinity"),
        tome(1648, "The Tome of Divinity", prev=1647, reward=7328, display=7329),
        tome(1641, "The Tome of Divinity", races=HUMAN_MASK, ritem1=TOME_HUMAN),
        tome(1642, "The Tome of Divinity", races=HUMAN_MASK, next=1643),
        tome(1643, "The Tome of Divinity", races=HUMAN_MASK),
        tome(
            1644,
            "The Tome of Divinity",
            races=HUMAN_MASK,
            prev=1643,
            reward=7328,
            display=7329,
        ),
        tome(2998, "Tome of Divinity", races=HUMAN_MASK, next=1643, exclusive=2998),
    ]


def givers():
    out = []
    for quest, role, spawn in (
        (2997, "start", BROMOS),
        (2997, "end", TIZA),
        (2999, "start", BRANDUR),
        (2999, "end", TIZA),
        (3000, "start", GRAYSON),
        (3000, "end", TIZA),
        (1645, "start", TIZA),
        (1645, "end", TIZA),
        (1646, "end", TIZA),
        (1647, "start", TIZA),
        (1647, "end", JOHN),
        (1648, "start", JOHN),
        (1648, "end", JOHN),
        (1641, "start", DUTHORIAN),
        (1641, "end", DUTHORIAN),
        (1642, "end", DUTHORIAN),
        (1643, "start", DUTHORIAN),
        (1643, "end", JOHN),
        (1644, "start", JOHN),
        (1644, "end", JOHN),
        (2998, "start", JOHN),
        (2998, "end", DUTHORIAN),
    ):
        out.append(dict(spawn, quest=quest, role=role))
    return out


def condition(quest, kind, value1, value2=0, group=0):
    return {
        "quest": quest,
        "grp": group,
        "kind": kind,
        "value1": value1,
        "value2": value2,
        "negative": 0,
    }


# acore_world.conditions, SourceTypeOrReferenceId 19, for the chain.
CONDITIONS = [
    condition(1641, 47, 1642, 1),
    condition(1643, 47, 1642, 64),
    condition(1645, 8, 2997, group=1),
    condition(1645, 8, 2999, group=2),
    condition(1645, 8, 3000, group=3),
    condition(1647, 47, 1646, 64),
]
STARTS = [
    {"quest": 1646, "kind": "item", "entry": TOME_DWARF},
    {"quest": 1642, "kind": "item", "entry": TOME_HUMAN},
]


def book(conditions=CONDITIONS):
    return classquest.build(
        quest_rows=rows(),
        giver_rows=givers(),
        spawn_rows=[],
        loot_rows=[],
        start_rows=STARTS,
        condition_rows=conditions,
    )


def paladin(race=DWARF, **over):
    base = dict(
        name="Dwarf",
        class_id=PALADIN,
        race=race,
        level=38,
        map_id=EASTERN,
        x=-4620.0,
        y=-920.0,
        zone_id=1537,
    )
    base.update(over)
    return who(**base)


def tome_in_bags(entry):
    return (guildjobs.Carried(guid=77, entry=entry, count=1),)


class TheWorldsConditions(unittest.TestCase):
    def test_a_quest_needs_what_the_conditions_rows_say(self):
        quests = book().quests
        self.assertEqual(quests[1647].needs, ((1646,),))
        self.assertEqual(quests[1643].needs, ((1642,),))
        self.assertEqual(quests[1645].needs, ((2997,), (2999,), (3000,)))

    def test_a_condition_the_book_cannot_model_is_left_out(self):
        # 1641 is offered while 1642 is NOT taken (state 1): no rewarded-quest
        # rule, so it keeps the old reading.
        self.assertEqual(book().quests[1641].needs, ())

    def test_a_reward_item_that_starts_a_quest_links_the_two(self):
        self.assertEqual(book().quests[1646].item_from, ((TOME_DWARF, 1645),))
        self.assertEqual(book().quests[1642].item_from, ((TOME_HUMAN, 1641),))


class TheDwarfChain(unittest.TestCase):
    def test_a_dwarf_with_an_errand_rewarded_is_not_sent_to_1647(self):
        move, _blocked = classquest.next_move(
            book(), paladin(quests_done=frozenset({2997}))
        )
        self.assertEqual(move.kind, classquest.TAKE)
        self.assertNotEqual(move.quest, 1647)
        self.assertEqual(move.quest, 1645)
        self.assertEqual(move.spot.name, "Tiza Battleforge")

    def test_the_book_never_takes_1647_while_1646_is_unrewarded(self):
        for done in (
            frozenset(),
            frozenset({2997}),
            frozenset({2999}),
            frozenset({3000}),
            frozenset({2997, 1645}),
        ):
            move, _blocked = classquest.next_move(book(), paladin(quests_done=done))
            self.assertFalse(
                move is not None
                and move.kind == classquest.TAKE
                and move.quest == 1647,
                "taking 1647 with %s rewarded" % sorted(done),
            )

    def test_the_errand_comes_first_for_a_member_that_did_none(self):
        move, _blocked = classquest.next_move(book(), paladin())
        self.assertEqual(move.kind, classquest.TAKE)
        self.assertIn(move.quest, (2997, 2999, 3000))

    def test_the_tome_in_the_bags_is_taken_with_no_walk(self):
        move, blocked = classquest.next_move(
            book(),
            paladin(
                quests_done=frozenset({2997, 1645}), carried=tome_in_bags(TOME_DWARF)
            ),
        )
        self.assertEqual(blocked, [])
        self.assertEqual(move.kind, classquest.TAKE)
        self.assertEqual(move.quest, 1646)
        self.assertIsNone(move.spot)
        self.assertEqual(move.blocker, "")

    def test_the_item_quest_is_handed_in_at_tiza(self):
        move, _blocked = classquest.next_move(
            book(),
            paladin(
                quests_done=frozenset({2997, 1645}),
                quest_log={1646: classquest.STATUS_COMPLETE},
            ),
        )
        self.assertEqual(move.kind, classquest.TURN_IN)
        self.assertEqual(move.quest, 1646)
        self.assertEqual(move.spot.name, "Tiza Battleforge")

    def test_1647_is_taken_once_1646_is_rewarded(self):
        move, _blocked = classquest.next_move(
            book(), paladin(quests_done=frozenset({2997, 1645, 1646}))
        )
        self.assertEqual(move.kind, classquest.TAKE)
        self.assertEqual(move.quest, 1647)

    def test_a_lost_tome_is_named_not_taken(self):
        move, blocked = classquest.next_move(
            book(), paladin(quests_done=frozenset({2997, 1645}))
        )
        self.assertIsNone(move)
        self.assertEqual(len(blocked), 1)
        self.assertIn("item %d" % TOME_DWARF, blocked[0])


class TheHumanChain(unittest.TestCase):
    def test_a_human_is_not_sent_to_1643(self):
        move, _blocked = classquest.next_move(
            book(), paladin(race=HUMAN, name="Human", quests_done=frozenset({2998}))
        )
        self.assertEqual(move.kind, classquest.TAKE)
        self.assertEqual(move.quest, 1641)

    def test_the_human_tome_is_taken_with_no_walk(self):
        move, _blocked = classquest.next_move(
            book(),
            paladin(
                race=HUMAN,
                quests_done=frozenset({2998, 1641}),
                carried=tome_in_bags(TOME_HUMAN),
            ),
        )
        self.assertEqual((move.kind, move.quest), (classquest.TAKE, 1642))
        self.assertIsNone(move.spot)

    def test_1643_is_taken_once_1642_is_rewarded(self):
        move, _blocked = classquest.next_move(
            book(),
            paladin(race=HUMAN, quests_done=frozenset({2998, 1641, 1642})),
        )
        self.assertEqual((move.kind, move.quest), (classquest.TAKE, 1643))


class TheStepTheBridgeWrites(unittest.TestCase):
    def test_a_take_with_no_walk_is_one_quest_row(self):
        m = paladin(
            quests_done=frozenset({2997, 1645}), carried=tome_in_bags(TOME_DWARF)
        )
        step, _doing, _note = guildjobs.class_step(m, book(), [], None)
        self.assertIsNotNone(step)
        self.assertEqual([r.command for r in step.rows], ["take quest:1646"])
        self.assertIsNone(step.walk)


class TheItemTakeObeysTheGuardsOfEveryTake(unittest.TestCase):
    """wow-overseer#2325: the take with no walk skipped _class_held, so a dead
    paladin carrying the tome got a refused row every pass."""

    def carrying(self, **over):
        return paladin(
            quests_done=frozenset({2997, 1645}),
            carried=tome_in_bags(TOME_DWARF),
            **over,
        )

    def plan(self, m, recent):
        return guildjobs.class_step(m, book(), recent, None)[0]

    def test_a_dead_member_carrying_the_tome_gets_no_take_row(self):
        step, _doing, note = guildjobs.class_step(
            self.carrying(alive=False), book(), [], None
        )
        self.assertIsNone(step)

    def test_a_take_the_module_refused_is_not_asked_again_in_the_cooldown(self):
        refused = guildjobs.Recent(
            name="Dwarf",
            action=classquest.ACTION,
            age_minutes=2,
            status="refused",
            refusal="not eligible",
        )
        self.assertIsNone(self.plan(self.carrying(), [refused]))

    def test_a_take_is_asked_again_after_the_cooldown(self):
        old = guildjobs.Recent(
            name="Dwarf",
            action=classquest.ACTION,
            age_minutes=guildjobs.COOLDOWN_MINUTES[classquest.ACTION] + 1,
            status="refused",
            refusal="not eligible",
        )
        step = self.plan(self.carrying(), [old])
        self.assertEqual([r.command for r in step.rows], ["take quest:1646"])

    def test_a_take_that_went_through_is_not_taken_twice_in_its_settle_window(self):
        took = guildjobs.Recent(
            name="Dwarf",
            action=classquest.ACTION,
            age_minutes=3,
            status="ok",
            taken=1646,
        )
        step = self.plan(self.carrying(), [took])
        self.assertTrue(
            step is None or "take quest:1646" not in [r.command for r in step.rows]
        )

    def test_a_far_walk_slot_is_not_asked_of_a_take_with_no_walk(self):
        class Far:
            def take(self, name):
                raise AssertionError("a take with no walk needs no slot")

        step = guildjobs.class_step(self.carrying(), book(), [], None, far=Far())[0]
        self.assertIsNotNone(step)


class TheConditionsRead(unittest.TestCase):
    def test_the_sql_runs_against_the_worlds_columns(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("ATTACH ':memory:' AS acore_world")
        db.execute(
            "CREATE TABLE acore_world.conditions (SourceTypeOrReferenceId INT, "
            "SourceEntry INT, ElseGroup INT, ConditionTypeOrReference INT, "
            "ConditionValue1 INT, ConditionValue2 INT, NegativeCondition INT)"
        )
        db.execute(
            "INSERT INTO acore_world.conditions VALUES (19, 1647, 0, 47, 1646, 64, 0)"
        )
        db.execute(
            "INSERT INTO acore_world.conditions VALUES (9, 1647, 0, 47, 1, 64, 0)"
        )
        rows = [
            dict(r)
            for r in db.execute(classquest.CONDITIONS_SQL.format(quests="1647, 1643"))
        ]
        self.assertEqual(
            rows,
            [
                {
                    "quest": 1647,
                    "grp": 0,
                    "kind": 47,
                    "value1": 1646,
                    "value2": 64,
                    "negative": 0,
                }
            ],
        )
        self.assertEqual(book(rows).quests[1647].needs, ((1646,),))

    def test_a_book_without_conditions_is_reported_on_every_pass(self):
        src = (
            pathlib.Path(__file__)
            .resolve()
            .parent.parent.joinpath("bridge.py")
            .read_text()
        )
        body = src[src.index("def _class_book()") :]
        body = body[: body.index("def _class_member_reads")]
        cached = body[: body.index("with _connect()")]
        self.assertIn("_CLASS_BOOK_NO_CONDITIONS", cached)
        self.assertIn("log.error", cached)
        self.assertIn("log.error", body[body.index("with _connect()") :])


if __name__ == "__main__":
    unittest.main()

"""Scripted events are skipped by the guild and solo quest picks."""

import unittest
from unittest import mock

import classquest
import guildlevel
import questers
from test_guildsocial_bridge import bridge
from test_questers_eligibility import HUMAN, REDRIDGE, WESTFALL, catalogue, member, row

QUEST = 219
REASON = "the quest completes only by a scripted event no lone quester drives"


def quest_row(special=2, area_trigger=0):
    # The ticket's read-only world snapshot gives quest 219's level, flags,
    # absence of area triggers, and zero required item/NPC/object objectives.
    # The other flag/trigger combinations are synthetic controls.
    return row(
        QUEST,
        "Missing In Action",
        REDRIDGE,
        25,
        19,
        special=special,
        area_trigger=area_trigger,
    )


def open_quests(quest):
    facts = dict(quest, quest=QUEST, given=1, group_size=0)
    world = guildlevel.world([facts], [], fact_rows=[facts])
    return guildlevel.member_opens(world, HUMAN, 25, frozenset())


def quest_plan(quest, zone=REDRIDGE):
    return questers.plan(
        catalogue([quest]), member("Quester", HUMAN, 25, zone), questers.Clock(), 0
    )


class EventQuests(unittest.TestCase):
    def test_the_world_reads_include_flags_and_area_triggers(self):
        for sql in (guildlevel.QUEST_FACTS_SQL, questers.QUESTS_SQL):
            self.assertIn("COALESCE(a.SpecialFlags, 0) AS special", sql)
            self.assertIn(
                "(SELECT quest FROM acore_world.areatrigger_involvedrelation) AS area_trigger",
                sql,
            )

    def test_missing_in_action_is_not_open_in_the_hub(self):
        self.assertNotIn(REDRIDGE, open_quests(quest_row()))

    def test_missing_in_action_is_never_offered(self):
        for zone in (REDRIDGE, WESTFALL):
            with self.subTest(zone=zone):
                self.assertIsNone(quest_plan(quest_row(), zone).move)

    def test_a_quest_with_an_area_trigger_remains_available(self):
        quest = quest_row(area_trigger=1)
        self.assertEqual(open_quests(quest), {REDRIDGE: 1})
        plan = quest_plan(quest)
        self.assertEqual((plan.move.kind, plan.move.quest), (classquest.TAKE, QUEST))
        self.assertEqual(plan.broken, ())

    def test_repeatable_quests_keep_their_treatment(self):
        quest = quest_row(special=1)
        self.assertNotIn(REDRIDGE, open_quests(quest))
        plan = quest_plan(quest)
        self.assertEqual((plan.move.kind, plan.move.quest), (classquest.TAKE, QUEST))
        self.assertEqual(plan.broken, ())

    def test_scripted_event_reason_reaches_the_ledger(self):
        (broken,) = quest_plan(quest_row()).broken
        connection = mock.MagicMock()
        cursor = (
            connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        )
        with mock.patch.object(bridge, "_connect", return_value=connection):
            self.assertTrue(bridge._record_quest_broken(broken))
        cursor.execute.assert_called_once_with(
            questers.BROKEN_SQL, (QUEST, False, REASON, "Quester")
        )

"""A class quest with a help party holds the member, so the party reaches the
objective (#1001, regressed).

Measured on 2026-10-15: a member's Call of Fire had drawn yes answers 20 times
and "the last party did not reach the objective". Its walks toward the
objective creature ended "character is held by another verb", and in the same
hours it asked the guild for Ragefire Chasm 24 times. Two plans owned one
character: the class quest ask held its asker and its helpers from nothing
until the party was on the board, so the dungeon asks and the guild jobs took
them in between, and the quest's walks lost to whatever verb held them. And a
walk that ended that way left only "did not reach the objective" behind.
"""

import asyncio
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import classask  # noqa: E402
import classparty  # noqa: E402
import guildroute  # noqa: E402
from test_classask import friends, qask  # noqa: E402
from test_classask_party_forms import TWO_YES, helps_read, settled  # noqa: E402
from test_classparty import FORMED, _Bridge, a_run, answer, drive  # noqa: E402
from test_guildsocial import NOW, yes  # noqa: E402
from test_guildsocial_bridge import bridge  # noqa: E402

HELD = "character is held by another verb"


def refused(holder):
    """A walk the module refused because another verb holds the walker."""
    return guildroute.WalkAnswer(
        guildroute.ENDED, "%s cannot walk to Lizard: %s" % (holder, HELD)
    )


def class_pass(answers, mates=None, held=None):
    """bridge._class_ask_pass over Bigzug's ask for its group quest."""
    facts = {
        "asks": [qask(1)],
        "answers": list(answers),
        "now": NOW,
        "busy": set(),
        "family": set(),
    }
    return bridge._class_ask_pass(
        facts, friends() if mates is None else mates, dict(held or {}), {}, helps_read()
    )


class TheDungeonPassLeavesAHelpPartyAlone(unittest.TestCase):
    def test_an_ask_with_a_yes_holds_its_asker_and_its_helper(self):
        # One yes of the two asked for, two minutes old, and Dread on a job:
        # no party yet, and Ghoul says the second yes this pass.
        _q, held, _n, parties, _e = class_pass(
            [yes(11, 1, "Chill", "dps", "help")], held={"Dread": "on a guild job"}
        )
        self.assertEqual(parties, ())
        self.assertEqual(held["Bigzug"], bridge._QUEST_GATHER_WHY)
        self.assertEqual(held["Chill"], bridge._QUEST_GATHER_WHY)
        self.assertEqual(held["Ghoul"], bridge._QUEST_GATHER_WHY)
        self.assertEqual(held["Dread"], "on a guild job")

    def test_fighting_members_stay_reserved_for_the_quest_ask(self):
        _q, held, _n, parties, _e = class_pass(
            [yes(11, 1, "Chill", "dps", "help")],
            held={"Bigzug": "in combat", "Chill": "in combat"},
        )
        self.assertEqual(parties, ())
        self.assertEqual(held["Bigzug"], bridge._QUEST_GATHER_WHY)
        self.assertEqual(held["Chill"], bridge._QUEST_GATHER_WHY)

    def test_two_yeses_hold_the_party_as_it_forms(self):
        _q, held, needs, parties, _e = class_pass(TWO_YES)
        self.assertEqual(len(parties), 1)
        self.assertTrue({"Bigzug", "Chill", "Dread"} <= set(held))
        self.assertFalse({"Bigzug", "Chill", "Dread"} & set(needs))

    def test_an_ask_nobody_answered_holds_nobody(self):
        alone = [m for m in friends() if m.name == "Bigzug"]
        _q, held, _n, _p, _e = class_pass([], mates=alone)
        self.assertEqual(held, {})

    def test_a_yes_taken_back_this_pass_holds_nobody(self):
        # Bigzug's help is gone, so the pass cancels the ask and its yeses.
        facts = {
            "asks": [qask(1)],
            "answers": TWO_YES,
            "now": NOW,
            "busy": set(),
            "family": set(),
        }
        quest_pass, held, _n, _p, _e = bridge._class_ask_pass(
            facts, friends(), {}, {}, []
        )
        self.assertEqual(quest_pass.cancel, (1,))
        self.assertEqual(held, {})


class TheGatheringNames(unittest.TestCase):
    def test_a_yes_said_this_pass_holds_its_helper_and_the_asker(self):
        quest_pass = classask.plan_pass(helps_read(), friends(), {}, [qask(1)], [], NOW)
        self.assertTrue(quest_pass.replies)
        names = classask.gathering(quest_pass, [qask(1)], [])
        self.assertIn("Bigzug", names)
        self.assertTrue({r.member for r in quest_pass.replies} <= names)

    def test_a_dungeon_ask_is_not_a_help_party(self):
        dungeon = qask(1, kind="dungeon")
        quest_pass = classask.plan_pass([], friends(), {}, [], [], NOW)
        self.assertEqual(classask.gathering(quest_pass, [dungeon], TWO_YES), set())


class TheGuildJobsLeaveAHelpPartyAlone(unittest.TestCase):
    def test_a_step_planned_before_the_party_was_reserved_does_not_start(self):
        async def run_step(_step, _cap):
            return None

        owner = types.SimpleNamespace(
            _guild_run_names={"Bigzug"},
            _job_steps={},
            _mail_walk_tasks=set(),
            _run_job_step=run_step,
            _mail_walk_task_done=lambda task: None,
        )
        step = types.SimpleNamespace(holder="Bigzug", walk=None, action="farm")
        plan = types.SimpleNamespace(steps=(step,))

        async def start():
            return bridge.Bridge._start_guild_job_steps(owner, plan, 1.0, 100.0, True)

        self.assertEqual(asyncio.run(start()), 0)
        self.assertEqual(owner._job_steps, {})

    def names(self, rows):
        cur = mock.MagicMock()
        cur.fetchall.return_value = rows
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cur
        with mock.patch.object(bridge, "_connect", return_value=conn):
            return bridge._guild_social_names()

    def test_a_quest_ask_with_a_yes_holds_its_asker_and_its_helper(self):
        rows = [
            {"kind": "dungeon", "asker": "Auren", "member": None},
            {"kind": "dungeon", "asker": "Tanky", "member": "Healy"},
            {"kind": "quest", "asker": "Bigzug", "member": "Chill"},
            {"kind": "quest", "asker": "Lonely", "member": None},
        ]
        self.assertEqual(
            self.names(rows), {"Auren", "Tanky", "Healy", "Bigzug", "Chill"}
        )

    def test_a_party_on_the_board_is_held_from_the_jobs_at_once(self):
        run = a_run(meeting=True)
        this = types.SimpleNamespace(
            _class_board=classparty.Board(),
            _class_party_tasks=set(),
            _guild_run_names={"Auren"},
        )

        async def party(_run):
            return None

        this._run_class_party = party

        async def begin():
            bridge.Bridge._begin_class_parties(this, [run])
            await asyncio.gather(*this._class_party_tasks)

        asyncio.run(begin())
        self.assertEqual(this._guild_run_names, {"Auren", "Bigzug", "Chill", "Dread"})


class AWalkTheWorldRefusedNamesWhy(unittest.TestCase):
    def follow(self, answers, run, **kw):
        this, outcomes = _Bridge(answers, **kw), []
        drive(this, run, _class_party_settle=settled(this, outcomes))
        return this, outcomes

    def test_the_leaders_meeting_walk_held_by_another_verb_is_named(self):
        this, outcomes = self.follow(
            [FORMED], a_run(meeting=True), meet={"Bigzug": refused("Bigzug")}
        )
        self.assertEqual(this.settled, [(1, False, False)])
        self.assertIn("Bigzug did not reach Lizard", outcomes[0])
        self.assertIn(HELD, outcomes[0])

    def test_a_helper_held_by_another_verb_is_named(self):
        this, outcomes = self.follow(
            [FORMED],
            a_run(meeting=True),
            meet={"Chill": refused("Chill"), "Dread": refused("Dread")},
        )
        self.assertIn("Chill did not reach Lizard", outcomes[0])
        self.assertIn(HELD, outcomes[0])
        self.assertNotIn("Chill cannot walk", outcomes[0])

    def test_the_party_walk_held_by_another_verb_is_named(self):
        this, outcomes = self.follow(
            [FORMED, answer("applied", phase="ended")],
            a_run(),
            walk=refused("Bigzug"),
        )
        self.assertEqual(this.settled, [(1, True, False)])
        self.assertIn("party did not reach the objective", outcomes[0])
        self.assertIn(HELD, outcomes[0])


if __name__ == "__main__":
    unittest.main()

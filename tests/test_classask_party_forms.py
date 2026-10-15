"""A class quest ask with yes answers forms its party, or names the step that
stopped it (#1001).

Live on 2026-10-15 a member had asked the guild seven times for Call of Fire
over 15.9 hours; two said yes and no party formed. The yes is not where it
broke: the guild jobs pass read the asker in combat, dropped its help for the
quest, and the next social pass cancelled the ask with its yeses, even under a
party that was meeting or up. And a party that did not form left nothing
behind but "no party formed".
"""

import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import classask  # noqa: E402
import classparty  # noqa: E402
import guildsocial as gs  # noqa: E402
from apiv2 import members  # noqa: E402
from test_classask import asker, friends, group_book, qask  # noqa: E402
from test_classparty import (  # noqa: E402
    FORMED,
    LOST,
    THERE,
    _Bridge,
    a_run,
    answer,
    at,
    drive,
    free_of,
)
from test_classquest import class_plan  # noqa: E402
from test_guildsocial import NOW, yes  # noqa: E402
from test_guildsocial_bridge import bridge  # noqa: E402

TWO_YES = [yes(11, 1, "Chill", "dps", "help"), yes(12, 1, "Dread", "dps", "help")]


def helps_read(**over):
    """The helps the guild jobs pass reads for Bigzug's group quest."""
    return list(class_plan([asker(**over)], b=group_book()).helps)


def settled(this, outcomes):
    """_class_party_settle stubbed to keep each run's outcome in `outcomes`."""

    def settle(run, formed, gave_up, done=False):
        this.settled.append((run.ask_id, formed, gave_up))
        outcomes.append(run.outcome)

    return settle


class TwoYesesFormAPartyThatTravels(unittest.TestCase):
    def test_a_help_read_while_the_asker_fights_still_stands(self):
        (help_,) = helps_read(in_combat=True)
        self.assertEqual((help_.member, help_.move.quest), ("Bigzug", 2000))

    def test_two_yeses_form_the_party_and_walk_it_to_the_objective(self):
        # The jobs pass read Bigzug fighting; the social pass reads it free.
        helps = helps_read(in_combat=True)
        quest_pass = classask.plan_pass(helps, friends(), {}, [qask(1)], TWO_YES, NOW)
        self.assertEqual((quest_pass.cancel, quest_pass.withdraw), ((), ()))
        board = classparty.Board()
        starts = classparty.plan_starts(
            [qask(1)],
            TWO_YES,
            quest_pass,
            helps,
            free_of(friends()),
            board,
            NOW,
            0.0,
        )
        self.assertEqual(len(starts), 1)
        run = starts[0]
        self.assertEqual((run.leader, run.helpers), ("Bigzug", ("Chill", "Dread")))
        self.assertTrue(run.meeting)
        this = _Bridge([FORMED, answer("applied", phase="ended")])
        drive(this, run)
        commands = [r[2] for r in this.rows if r[0] == "Bigzug"]
        self.assertEqual(
            commands,
            [
                classparty.meet_command(run.spot, 20000.0),
                "party-up Chill Dread",
                classparty.walk_command(run.spot, 20000.0),
                "party-disband",
            ],
        )
        self.assertEqual(this.settled, [(1, True, False)])

    def test_an_ask_with_its_party_up_outlives_a_help_that_went_unread(self):
        out = classask.plan_pass(
            [], friends(), {}, [qask(1)], TWO_YES, NOW, frozenset({1})
        )
        self.assertEqual((out.cancel, out.withdraw, out.expire), ((), (), ()))

    def test_an_ask_with_its_party_up_still_ends_when_its_asker_leaves(self):
        held = {"Bigzug": "offline"}
        out = classask.plan_pass(
            [], friends(), held, [qask(1)], TWO_YES, NOW, frozenset({1})
        )
        self.assertEqual(out.cancel, (1,))

    def test_an_ask_with_no_party_still_ends_when_its_help_is_gone(self):
        out = classask.plan_pass([], friends(), {}, [qask(1)], TWO_YES, NOW)
        self.assertEqual(out.cancel, (1,))


class APartyThatCannotFormNamesTheStep(unittest.TestCase):
    def follow(self, answers, run, **kw):
        """(the bridge stub, the outcome each settled run carried)."""
        this, outcomes = _Bridge(answers, **kw), []
        drive(this, run, _class_party_settle=settled(this, outcomes))
        return this, outcomes

    def test_a_refused_invite_is_named(self):
        refused = answer("error", "'Chill': a helper is in combat", "refused")
        this, outcomes = self.follow([refused], a_run())
        self.assertEqual(this.settled, [(1, False, False)])
        self.assertIn("invite", outcomes[0])
        self.assertIn("'Chill': a helper is in combat", outcomes[0])

    def test_a_party_formed_after_a_leader_refusal_carries_no_stop(self):
        busy = answer("error", "the leader is in combat", "refused")
        this, outcomes = self.follow(
            [busy, FORMED, answer("applied", phase="ended")],
            a_run(),
            states=[classparty.INCOMPLETE],
            ask_live=False,
        )
        self.assertEqual(this.settled, [(1, True, False)])
        self.assertEqual(outcomes, [""])

    def test_an_invite_nobody_answered_is_named(self):
        this, outcomes = self.follow([None, answer("unchanged", phase="none")], a_run())
        self.assertIn("invite", outcomes[0])
        self.assertIn("not answered", outcomes[0])

    def test_helpers_too_far_from_the_leader_are_named(self):
        far = {"Bigzug": THERE, "Chill": at(800), "Dread": at(500)}
        this, outcomes = self.follow([FORMED], a_run(meeting=True), stands=[far])
        self.assertIn("meeting", outcomes[0])
        self.assertIn("Chill stood too far from Bigzug", outcomes[0])
        self.assertIn("Dread stood too far from Bigzug", outcomes[0])

    def test_a_helper_that_never_arrived_is_named(self):
        this, outcomes = self.follow(
            [FORMED], a_run(meeting=True), meet={"Chill": LOST, "Dread": LOST}
        )
        self.assertIn("Chill did not reach Lizard", outcomes[0])

    def test_a_helper_called_away_before_the_party_is_named(self):
        held = {"Chill": "on a guild job"}
        out = classask.plan_pass(helps_read(), friends(), held, [qask(1)], TWO_YES, NOW)
        self.assertEqual(out.withdraw, (11,))
        self.assertEqual(out.reasons, ((1, "stopped: Chill was busy: on a guild job"),))

    def test_a_helper_no_longer_read_is_named_too(self):
        unread = [m for m in friends() if m.name != "Chill"]
        out = classask.plan_pass(helps_read(), unread, {}, [qask(1)], TWO_YES, NOW)
        self.assertEqual(
            out.reasons,
            ((1, "stopped: Chill was busy: %s" % classask.NOT_READ),),
        )

    def test_a_helper_only_fighting_names_nothing(self):
        held = {"Chill": "in combat"}
        out = classask.plan_pass(helps_read(), friends(), held, [qask(1)], TWO_YES, NOW)
        self.assertEqual((out.withdraw, out.reasons), ((), ()))


class TheStepIsKeptOnTheAsk(unittest.TestCase):
    def rows(self, run, formed, gave_up):
        cur = mock.MagicMock()
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cur
        with mock.patch.object(bridge, "_connect", return_value=conn):
            bridge._class_party_settle(run, formed, gave_up)
        return [c.args for c in cur.execute.call_args_list]

    def test_a_party_that_did_not_form_writes_its_step_to_the_ask(self):
        run = a_run()
        run.outcome = "the invite was refused: 'Chill' is in another group"
        (only,) = self.rows(run, False, False)
        self.assertIn("reason", only[0])
        self.assertEqual(
            only[1],
            ("stopped: the invite was refused: 'Chill' is in another group", 1),
        )

    def test_a_party_given_up_keeps_its_step_too(self):
        run = a_run()
        run.outcome = "the invite was not answered"
        written = self.rows(run, False, True)
        self.assertIn(
            ("stopped: the invite was not answered", 1), [w[1] for w in written]
        )

    def test_the_pass_writes_the_step_of_a_helper_called_away(self):
        social = gs.Pass(reasons=((1, "stopped: Chill was busy: on a guild job"),))
        cur = mock.MagicMock()
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cur
        with mock.patch.object(bridge, "_connect", return_value=conn):
            bridge._write_guild_social(social)
        args = [c.args[1] for c in cur.execute.call_args_list if len(c.args) > 1]
        self.assertIn(("stopped: Chill was busy: on a guild job", 1), args)

    def test_the_class_pass_carries_its_reasons_to_the_writer(self):
        quest_pass = gs.Pass(reasons=((1, "stopped: x"),))
        merged = bridge._with_class_asks(gs.Pass(), quest_pass)
        self.assertEqual(merged.reasons, ((1, "stopped: x"),))


class TheMembersPageSaysTheStep(unittest.TestCase):
    NOW_AT = 1_800_000_000

    def ask(self, ago, state="expired", reason="", yeses=0):
        return {
            "asker": "Ashfang",
            "target": "quest:1526",
            "target_label": "Call of Fire",
            "state": state,
            "reason": reason,
            "yeses": yeses,
            "at": self.NOW_AT - ago,
        }

    def test_the_step_that_stopped_the_party_replaces_no_party_formed(self):
        run = [
            self.ask(3600),
            self.ask(1800, reason="stopped: Chill stood too far from Ashfang", yeses=2),
            self.ask(300, state="open"),
        ]
        found = members.ask_blocker(run, self.NOW_AT)
        self.assertIn(
            "2 said yes, the party stopped: Chill stood too far from Ashfang",
            found["blocker"],
        )
        self.assertNotIn("no party formed", found["blocker"])

    def test_the_page_reads_the_prefix_the_bridge_writes(self):
        self.assertEqual(members.STOPPED, classask.STOPPED)

    def test_with_no_step_kept_it_still_says_no_party_formed(self):
        found = members.ask_blocker([self.ask(300, yeses=1)], self.NOW_AT)
        self.assertIn("1 said yes, no party formed", found["blocker"])


if __name__ == "__main__":
    unittest.main()

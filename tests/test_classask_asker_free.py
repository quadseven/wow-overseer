"""A member asking the guild for help with a class quest is given no other step.

Health #1072: a warlock asked the guild for help with its class quest 2 times
in 2.6 hours, 0 said yes, and no party formed. The guild jobs pass listed the
member's help for the social pass to ask for AND started an ordinary step for
it in the same pass (a mailbox walk, a sale, a farm). The bridge holds a
member with a step in hand "on a guild job" until the step ends, up to
guildroute.GUILD_STEP_SECONDS, and the social pass cancels a live ask whose
asker is not free (classask._ended) and posts none for it. So the asks came
45 minutes or more apart rather than ASK_COOLDOWN_MINUTES, the run never
reached the third try (classask.ESCALATE_AFTER_ASKS), which is the first that
goes to the server, and the quest's hold-off ran out first.
"""

import unittest

import classask
import guildjobs
from test_classquest import book, class_plan, qrow, who

GROUP_JOB = 2000
MAIL = {"Bigzug": ("take-money mail:42",)}


def group_book():
    return book(
        quest_rows=[
            qrow(
                GROUP_JOB,
                "Group Job",
                reward=8121,
                grp=3,
                npc1=3130,
                npc_count1=1,
                min_level=12,  # inside the #1094 solo gap of the level 20 asker
            )
        ]
    )


def asker():
    return who(quest_log={GROUP_JOB: 3})


def run_of(n):
    """`n` asks for the group quest that came to nothing, a quarter hour apart."""
    return tuple(
        guildjobs.QuestAsk("Bigzug", GROUP_JOB, "expired", 10 + 15 * i)
        for i in range(n)
    )


class AnAskerStaysFreeForItsAsk(unittest.TestCase):
    def test_an_asker_is_given_no_other_step(self):
        plan = class_plan([asker()], b=group_book(), mail=MAIL)
        self.assertEqual([h.member for h in plan.helps], ["Bigzug"])
        self.assertEqual([s.holder for s in plan.steps], [])

    def test_its_line_says_it_waits_for_help(self):
        plan = class_plan([asker()], b=group_book(), mail=MAIL)
        self.assertIn("help with Group Job", plan.lines["Bigzug"])

    def test_the_social_pass_reads_it_free(self):
        # A line naming the class quest is read as one on it (class_held), and
        # the social pass holds such a member out of the asks too.
        plan = class_plan([asker()], b=group_book(), mail=MAIL)
        self.assertNotIn("Bigzug", guildjobs.class_held(plan.lines))

    def test_the_next_tries_still_reach_the_server(self):
        # Free, the member asks again: the third ask is the server's.
        plan = class_plan(
            [asker()],
            b=group_book(),
            mail=MAIL,
            asks=run_of(classask.ESCALATE_AFTER_ASKS),
        )
        self.assertEqual([s.holder for s in plan.steps], [])
        self.assertTrue(classask.escalated(plan.helps[0]))

    def test_a_quest_that_yields_to_levelling_frees_the_member_for_work(self):
        plan = class_plan(
            [asker()],
            b=group_book(),
            mail=MAIL,
            asks=run_of(guildjobs.CLASS_ASK_STREAK_MAX),
        )
        self.assertEqual(plan.helps, ())
        self.assertEqual([s.action for s in plan.steps], ["collect"])


if __name__ == "__main__":
    unittest.main()

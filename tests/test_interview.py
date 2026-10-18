"""One interview exchange with a shortlisted recruit, before the guild invite.

The interview step gives a shortlisted candidate one real "interview" moment
through the repo's existing inner-voice/chat machinery instead of inventing a
new LLM system.

WHAT THESE TESTS ARE PROTECTING, because it is not "the question reads
nicely". It is that the judgement never moves: who is worth asking is
RecruitVerdictFor's call in mod-overseer's pure layer, and the LLM is never
asked for a verdict of any kind here. The question is deterministic - asking
the model to write its own interview question would put verdict-shaped
language one prompt edit away - and the model only answers it in character.

Rows in, one exchange out: every test below runs against a fake store and a
fake voice. No live model call, no database.
"""

import pathlib
import re
import unittest

import interview

DOCKERFILE = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"


def snapshot(**kw):
    """A shortlisted candidate's grounding, as the caller resolves it."""
    base = {
        "level": 24,
        "race_name": "Gnome",
        "class_name": "Mage",
        "zone": "Stormwind City",
    }
    base.update(kw)
    return base


# Verdict-shaped language, which must never appear in the question the
# model is given. Matched on word boundaries so "bring" does not trip "rank".
VERDICT_WORDS = re.compile(
    r"\b(verdict|score|scored|rating|rate|rank|ranked|grade|pass|fail|accepted|"
    r"rejected|out of 10|/10)\b",
    re.IGNORECASE,
)


class AnOnlineCandidateIsAskedOneQuestion(unittest.TestCase):
    def test_the_question_names_the_candidate(self):
        plan = interview.plan(name="Ziblop", snapshot=snapshot())
        self.assertIsNotNone(plan)
        self.assertIn("Ziblop", plan.question)

    def test_the_question_is_grounded_in_who_they_are(self):
        plan = interview.plan(name="Ziblop", snapshot=snapshot())
        self.assertIn("24", plan.question)
        self.assertIn("Gnome", plan.question)
        self.assertIn("Mage", plan.question)
        self.assertIn("Stormwind City", plan.question)

    def test_the_question_is_guild_appropriate(self):
        """An officer's question - why this guild, and what they bring - not
        small talk and not an interrogation."""
        plan = interview.plan(name="Ziblop", snapshot=snapshot())
        self.assertIn("guild", plan.question.lower())

    def test_the_question_is_deterministic(self):
        """The model never writes its own interview question."""
        first = interview.plan(name="Ziblop", snapshot=snapshot()).question
        second = interview.plan(name="Ziblop", snapshot=snapshot()).question
        self.assertEqual(first, second)

    def test_the_exchange_carries_candidate_question_and_reply(self):
        exchange = interview.InterviewExchange(
            candidate="Ziblop",
            question=interview.plan(name="Ziblop", snapshot=snapshot()).question,
            reply="I want a guild that runs dungeons together.",
            reason="shortlisted and online",
        )
        self.assertEqual(exchange.candidate, "Ziblop")
        self.assertTrue(exchange.question)
        self.assertEqual(exchange.reply, "I want a guild that runs dungeons together.")


class AnOfflineCandidateIsSkipped(unittest.TestCase):
    def test_no_snapshot_means_no_question(self):
        """None is the skip signal: the caller tries the next shortlisted
        name rather than blocking on this one."""
        self.assertIsNone(interview.plan(name="Ziblop", snapshot=None))


class TheModelIsNeverAskedForAVerdict(unittest.TestCase):
    def test_the_question_carries_no_verdict_shaped_language(self):
        plan = interview.plan(name="Ziblop", snapshot=snapshot())
        self.assertIsNone(
            VERDICT_WORDS.search(plan.question),
            f"verdict-shaped language in the interview question: {plan.question!r}",
        )

    def test_the_plan_is_data_not_a_judgement(self):
        """The plan records what to ask, never whether the candidate is
        worth asking - that stays RecruitVerdictFor's call."""
        plan = interview.plan(name="Ziblop", snapshot=snapshot())
        self.assertFalse(hasattr(plan, "verdict"))
        self.assertFalse(hasattr(plan, "score"))


class TheModuleShipsInTheImage(unittest.TestCase):
    def test_interview_py_is_in_the_dockerfile_copy_list(self):
        """A module the bridge imports must be COPYed into the image or the
        container crashes on import - the failure mode test_recruit.py guards
        for recruit.py."""
        self.assertIn("interview.py", DOCKERFILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

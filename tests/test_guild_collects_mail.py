"""A guild member opens its post: walk to a mailbox, then every take.

wow-dev 2026-10-04: the family's cloth and gear sat unopened in guild members'
mailboxes for up to 157 hours (Aalall 33 letters, Argam 25, Bezki and Cigtek
24 each), every one still carrying its items, because nothing ever sent a
guild member to collect its mail.
"""

import pathlib
import unittest

import guildjobs

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _member(**kw):
    base = dict(
        name="Argam",
        guild="Bonkers",
        role=guildjobs.MAINTENANCE,
        level=17,
        class_id=1,
        online=True,
        map_id=1,
        x=0.0,
        y=0.0,
        money=5000,
        eligible=True,
    )
    base.update(kw)
    return guildjobs.Member(**base)


TAKES = ("take-item mail:41 item:777", "take-money mail:42")


class AMemberOpensItsPost(unittest.TestCase):
    def test_a_collect_step_walks_then_takes(self):
        plan = guildjobs.plan([_member()], mail={"Argam": TAKES})
        self.assertEqual(["collect"], [s.action for s in plan.steps])
        step = plan.steps[0]
        self.assertTrue(step.walk.command.startswith("walk-to-mailbox"))
        self.assertEqual(TAKES, tuple(r.command for r in step.rows))
        self.assertTrue(all(r.kind == "mail" for r in step.rows))
        self.assertEqual("guildjobs:collect:Argam", step.rows[0].source)

    def test_not_twice_in_an_hour(self):
        recent = [guildjobs.Recent("Argam", "collect", 10, status="delivered")]
        plan = guildjobs.plan([_member()], mail={"Argam": TAKES}, recent=recent)
        self.assertNotIn("collect", [s.action for s in plan.steps])

    def test_no_post_no_step(self):
        plan = guildjobs.plan([_member()], mail={})
        self.assertNotIn("collect", [s.action for s in plan.steps])

    def test_an_unnatural_member_does_not(self):
        plan = guildjobs.plan([_member(eligible=False)], mail={"Argam": TAKES})
        self.assertEqual((), plan.steps)

    def test_the_bridge_reads_the_members_post(self):
        source = (ROOT / "bridge.py").read_text(encoding="utf-8")
        self.assertIn(
            "mail=await asyncio.to_thread(_job_mail_commands, members)", source
        )
        body = source[source.index("def _job_mail_commands(") :]
        body = body[: body.index("\ndef ")]
        self.assertIn("mailrun.plan(", body)


if __name__ == "__main__":
    unittest.main()

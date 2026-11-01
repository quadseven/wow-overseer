"""The Now card says what the character is doing, read from the live page.

Each case is a card the dev realm served on 2026-11-01.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agenda  # noqa: E402
import campaignqueue  # noqa: E402
import nowstatus  # noqa: E402

NOW = 1_000_000
STANDIN = (
    "standin: Grug's family: Og has too little to craft with (Og holds 1 Wool "
    "Cloth against 3 per cast of spell 2964, which is 0 more cast(s) - short of "
    "the 3 it takes to be worth staying put), so it rejoins its family, whose "
    "roaming and runs gather it"
)
ORGRIMMAR = "at:1:1633.0,-4439.0,15.0"
ROSTER = [
    {
        "name": "Grug",
        "family": "Grug",
        "enabled": 1,
        "lead": 1,
        "job": "dungeon:uldaman",
        "dungeon_runs_done": 0,
        "dungeon_runs_wanted": 30,
    },
    {
        "name": "Og",
        "family": "Grug",
        "enabled": 1,
        "lead": 0,
        "job": "dungeon:uldaman",
        "dungeon_runs_done": 0,
        "dungeon_runs_wanted": 30,
    },
    {
        "name": "Zug",
        "family": "Zug",
        "enabled": 1,
        "lead": 1,
        "job": "quest",
        "travel_npc": ORGRIMMAR,
    },
]
NAMES = ["Grug", "Og", "Zug"]


def stored(step, age=30):
    return {
        "subject": step.subject,
        "scope": step.scope,
        "kind": step.kind,
        "doing": step.doing,
        "waiting": step.waiting,
        "occurrences": 1,
        "first_at": NOW - age,
        "last_at": NOW - age,
        "now_at": NOW,
    }


def card(name, steps=(), intents=()):
    facts = nowstatus.build_facts(NAMES, ROSTER, list(intents), list(steps), NOW)
    return nowstatus.compose(
        {"name": name, "present": True, "condition": "ok"}, facts[name]
    )


class StandInNotes(unittest.TestCase):
    def test_a_stand_in_note_is_not_the_head_s_activity(self):
        step = stored(nowstatus.classify(STANDIN)[0])
        got = card("Grug", [step])
        self.assertEqual(got["doing"], "On the Uldaman campaign (run 1 of 30)")

    def test_the_note_stays_on_the_sheet_without_saying_short_handed(self):
        step = nowstatus.classify(STANDIN)[0]
        self.assertNotIn("short-handed", step.doing)
        self.assertEqual(step.doing[:9], "Stand-in:")

    def test_an_empty_seat_is_said_as_short_handed(self):
        step = nowstatus.classify(
            "standin: Grug's family: no guest at uldaman; the family runs four-handed"
        )[0]
        self.assertTrue(step.doing.startswith("Running short-handed: "))

    def test_a_note_carrying_a_spell_id_loses_it(self):
        step = nowstatus.classify(
            "standin: Grug's family: Og holds 3 bolts, enough for 1 bag(s) "
            "for the guild (spell 12065)"
        )[0]
        self.assertNotIn("spell", step.doing)

    def test_the_reason_names_no_spell_id(self):
        path = os.path.join(os.path.dirname(__file__), "..", "craft_rhythm.py")
        with open(path, encoding="utf-8") as handle:
            self.assertNotIn("per cast of spell", handle.read())


class EndedWalks(unittest.TestCase):
    PREV = {
        "leader_name": "Zug",
        "current_kind": "errand",
        "current_owner": "travel column",
        "current_target": ORGRIMMAR,
        "current_for": 40,
    }
    GONE = dict(PREV, current_kind="none", current_owner="", current_target="")

    def ended(self):
        return nowstatus.intent_steps(self.PREV, self.GONE)[0]

    def test_an_ended_walk_reads_as_a_past_event(self):
        self.assertEqual(
            self.ended().doing,
            "the errand walk ended (it was walking to Orgrimmar on a town errand)",
        )

    def test_an_ended_walk_is_not_the_current_activity(self):
        got = card("Zug", [stored(self.ended())])
        self.assertNotIn("ended", got["doing"])

    def test_a_travel_aim_is_said_when_nothing_else_is(self):
        got = card("Zug", [stored(self.ended())])
        self.assertEqual(got["doing"], "Walking to Orgrimmar")

    def test_a_parked_aim_on_a_campaign_is_not_a_walk(self):
        row = dict(ROSTER[0], travel_npc=ORGRIMMAR)
        facts = nowstatus.build_facts(["Grug"], [row], [], [], NOW)
        got = nowstatus.compose(
            {"name": "Grug", "present": True, "condition": "ok"}, facts["Grug"]
        )
        self.assertEqual(got["doing"], "On the Uldaman campaign (run 1 of 30)")


class MemberStates(unittest.TestCase):
    def state(self, word):
        intent = {
            "leader_name": "Grug",
            "family": "Grug",
            "current_kind": "none",
            "members_state": "Og|%s|" % word,
            "module_age": 0,
        }
        return card("Og", intents=[intent])["doing"]

    def test_every_word_the_module_writes_reads_plainly(self):
        for word in (
            "held off a walk that kept killing it",
            "held where it stands, too far to walk back",
            "walking back to the leader",
            "walking to the inn",
            "held still",
            "fighting",
            "not in the world",
            "dead",
        ):
            self.assertNotIn("In state", self.state(word), word)


class Counts(unittest.TestCase):
    ROW = {
        "keyword": "uldaman",
        "runs_wanted": 30,
        "status": "active",
        "source": "overseer:planner",
    }

    def test_the_queue_counts_closed_runs_and_says_so(self):
        self.assertEqual(
            campaignqueue.view([self.ROW], 0)["line"],
            "Queue: Uldaman 0 of 30 done (the planner's choice).",
        )


class Leader(unittest.TestCase):
    RUN = {"leader_name": "Bork", "members": "Bork,Grog,Grug,Og,Ugga"}
    NAMES = ["Grug", "Bork", "Grog", "Og", "Ugga"]

    def test_the_head_leads_whoever_crossed_first(self):
        self.assertEqual(
            agenda._members_line(self.RUN, self.NAMES, "Grug"),
            "Led by Grug, with Bork, Grog, Og, Ugga.",
        )

    def test_a_head_alone_inside_reads_as_a_sentence(self):
        self.assertEqual(
            agenda._members_line({"members": "Grug"}, ["Grug"], "Grug"),
            "Led by Grug.",
        )

    def test_a_head_still_outside_is_not_with_the_party(self):
        self.assertEqual(
            agenda._members_line(
                {"members": "Bork,Og"}, ["Grug", "Bork", "Og"], "Grug"
            ),
            "Inside: Bork, Og. Not inside: Grug.",
        )


if __name__ == "__main__":
    unittest.main()

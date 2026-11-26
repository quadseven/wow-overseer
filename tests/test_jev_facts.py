"""Every judged kind records the facts it was asked with.

An independent judge reads overseer_jev_judgment.facts to say whether Jev or
the rules chose better where they disagreed. Five kinds left it empty
(guild_recipient, item_disposition, weapon_choice, loot_council, quest_pick),
so none of their disagreements could be judged. Each now records the options
it offered and the state it asked with, as compact JSON within the column's
1000 characters, the shape the guild door and keep kinds already use.

The guild recipient question also stops asking with one candidate: OpenAI's
decisions endpoint answers HTTP 400 to a Choice with fewer than two options,
and with one there is nothing to choose, so the heuristic's route stands.
"""

import asyncio
import json
import unittest

import gear
import jev
import jev_choices
import jev_items
import lootcouncil
import questbook
from test_jev_act import DESTINY, FakePick, guild_pass, ranked, route
from test_jev_choices import HELD, LEDGER
from test_jev_items import FakeJev, carried, run
from test_lootcouncil import council, outcome, rule


class FactsLine(unittest.TestCase):
    def test_options_lead_and_the_state_follows(self):
        line = jev_items.facts_line({"item": {"name": "Destiny"}}, {"keep": "k"})
        self.assertEqual(
            json.loads(line), {"options": {"keep": "k"}, "item": {"name": "Destiny"}}
        )
        self.assertTrue(line.startswith('{"options"'))

    def test_a_long_state_is_cut_to_the_column(self):
        line = jev_items.facts_line({"x": "y" * 5000}, {"a": "b"})
        self.assertEqual(len(line), 1000)
        self.assertTrue(line.endswith("..."))
        self.assertTrue(line.startswith('{"options":{"a":"b"}'))


class ItemKinds(unittest.TestCase):
    def test_disposition_and_weapon_choice_record_their_facts(self):
        judgments = run([carried()], FakeJev())
        kinds = {j.kind for j in judgments}
        self.assertIn(jev_items.KIND_DISPOSITION, kinds)
        self.assertIn(jev_items.KIND_WEAPON, kinds)
        for j in judgments:
            self.assertTrue(j.facts, j.kind)
            self.assertTrue(j.facts.startswith('{"options":{'), j.facts[:80])
        weapon = next(j for j in judgments if j.kind == jev_items.KIND_WEAPON)
        self.assertIn(jev_items.CARRIED, weapon.facts)
        self.assertIn("Destiny", weapon.facts)
        disposition = next(j for j in judgments if j.kind == jev_items.KIND_DISPOSITION)
        self.assertIn(jev_items.KEEP, disposition.facts)


class GuildRecipient(unittest.TestCase):
    def test_the_recipient_judgment_records_its_facts(self):
        _plan, [judgment], _fake = guild_pass("Grog")
        facts = json.loads(judgment.facts)
        self.assertEqual(list(facts["options"]), ["Grug", "Grog"])
        self.assertEqual(len(facts["candidates"]), 2)

    def test_one_candidate_is_not_asked_and_the_route_stands(self):
        grants = (route("Grug", 27),)
        asks = jev_items.recipient_asks(
            [DESTINY], [], grants, lambda h, c: (ranked("Grug", 27, True),)
        )
        fake = FakePick("Grug")
        client = jev.Client("k", transport=fake)
        judgments = asyncio.run(
            jev_items.recipient_pass(client, asks, lambda e: None, {}, jev.ACT)
        )
        self.assertEqual(fake.requests, [])
        self.assertEqual(judgments, [])
        plan = gear.Plan(grants=grants)
        out, marked = jev_items.reroute(plan, judgments, jev_items.guild_policy({}))
        self.assertEqual((out, marked), (plan, ()))


class LootCouncil(unittest.TestCase):
    def test_the_council_judgment_records_its_facts(self):
        d = lootcouncil.decide(council(), outcome("Og", 0.9), rule())
        # A council's candidates run past the column; the options lead, so
        # the cut falls in the state and every offered name survives it.
        facts = d.judgment.facts
        self.assertLessEqual(len(facts), jev_items.FACTS_LIMIT)
        self.assertTrue(facts.startswith('{"options":{'), facts[:40])
        options_end = facts.index('"item":')
        for name in ("Og", "Grug", lootcouncil.NOBODY):
            self.assertIn('"%s":' % name, facts[:options_end])


class QuestPick(unittest.TestCase):
    def test_the_quest_judgment_records_its_facts(self):
        candidates = questbook.drive_candidates(
            LEDGER, held_by_traveller={60, 61, 62}, beneficiary="Ugga"
        )
        client = jev.Client("k", transport=FakeJev(picks={"quest": "q62"}))
        judgment = asyncio.run(
            jev_choices.quest_shadow(
                client, candidates, 60, "Ugga", HELD, {"Ugga": 12}, jev.SHADOW
            )
        )
        facts = json.loads(judgment.facts)
        self.assertEqual(list(facts["options"]), ["q60", "q61", "q62"])
        self.assertEqual(facts["beneficiary"], "Ugga")


if __name__ == "__main__":
    unittest.main()

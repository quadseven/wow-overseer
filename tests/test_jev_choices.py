"""The planner's dungeon (act) and the quest aim (shadow), asked of Jev (#95).

Jev is shown exactly the options the heuristic chose from (the runs
campaignplan.options offers, the quests questbook.drive_target considers) and
its answer is recorded beside the heuristic's. The dungeon's answer acts past
its confidence floor; the quest aim's never does. The tests run the real
client over a fake transport and never call the API.
"""

import asyncio
import pathlib
import unittest

import campaignplan
import council
import jev
import jev_choices
import questbook
from test_jev_items import FakeJev

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
NAMES = ("Grug", "Ugga", "Grog", "Bork", "Og")
EASTERN_KINGDOMS = 0
KALIMDOR = 1


def rows(level=41):
    return [{"name": n, "level": level, "map_id": EASTERN_KINGDOMS} for n in NAMES]


def members(level=41):
    return [
        council.Member(name=n, level=level, class_name="Warrior", gold=999999, trades=5)
        for n in NAMES
    ]


class DoorsTest(unittest.TestCase):
    def test_the_pick_is_the_proposals_own_door(self):
        doors, pick = council.dungeon_doors(rows(), [], None)
        proposal = council._dungeon_proposal(members(), rows(), [])
        self.assertEqual(pick.keyword, proposal.keyword)
        self.assertIn(pick, doors)

    def test_every_door_offered_is_one_the_council_would_send_them_through(self):
        doors, _pick = council.dungeon_doors(rows(), [], {"scarlet": 3})
        self.assertGreaterEqual(len(doors), 2)
        for door in doors:
            self.assertEqual(council.door_refusal(door.keyword, rows()), "", door)

    def test_no_level_rows_is_no_door(self):
        self.assertEqual(council.dungeon_doors([], [], None), ((), None))


class DungeonChoiceTest(unittest.TestCase):
    """The planner's dungeon, asked of Jev over campaignplan's own runs."""

    def facts(self, level=60, map_id=KALIMDOR):
        return campaignplan.Facts(
            family="Grug",
            level_rows=tuple(
                {"name": n, "level": level, "race": 1, "map_id": map_id, "lead": 0}
                for n in NAMES
            ),
            done={},
            failed={},
            quests={2557: 4},
            gear={n: (44.0, 2) for n in NAMES},
            loot={429: 60},
            # The Crescent Key, so Dire Maul West and North are open too.
            keys=frozenset({18249}),
        )

    def ask(self, fake, key="k", environ=None):
        facts = self.facts()
        opts = campaignplan.options(facts)
        pick = campaignplan.heuristic(opts)
        rule = jev_choices.policy(jev_choices.KIND_DUNGEON, environ or {})
        client = jev.Client(key, transport=fake)
        judgment = asyncio.run(
            jev_choices.dungeon_ask(
                client, facts, opts, pick, rule, "the queue is empty"
            )
        )
        return judgment, opts, pick

    def test_the_choice_is_over_the_planners_runs_with_the_facts_it_needs(self):
        fake = FakeJev(picks={"dungeon": "dire-maul-north"}, confidence=0.9)
        judgment, opts, pick = self.ask(fake)
        [request] = fake.requests
        offered = list(request["questions"]["dungeon"]["criteria"])
        self.assertEqual(offered, [o.keyword for o in opts])
        self.assertEqual(pick.keyword, "dire-maul-east-east")
        dungeon = request["state"]["dungeons"][0]
        for fact in (
            "levels",
            "completed_runs",
            "failed_attempts",
            "open_quests",
            "boss_gear_item_level",
            "members_whose_gear_is_below_it",
        ):
            self.assertIn(fact, dungeon)
        self.assertEqual(dungeon["open_quests"], 4)
        self.assertEqual(len(dungeon["members_whose_gear_is_below_it"]), 5)
        self.assertIn("worn_item_level", request["state"]["family"][0])
        self.assertEqual(judgment.kind, jev_choices.KIND_DUNGEON)
        self.assertEqual(judgment.mode, jev.ACT)
        self.assertEqual(judgment.item_name, "the queue is empty")
        self.assertIn("dire-maul-north", judgment.facts)

    def test_a_confident_answer_acts(self):
        fake = FakeJev(picks={"dungeon": "dire-maul-north"}, confidence=0.9)
        judgment, opts, pick = self.ask(fake)
        self.assertEqual(judgment.acted, jev.JEV)
        chosen = jev_choices.dungeon_carried(opts, pick, judgment)
        self.assertEqual(chosen.keyword, "dire-maul-north")

    def test_below_the_floor_the_heuristic_acts(self):
        fake = FakeJev(picks={"dungeon": "dire-maul-north"}, confidence=0.5)
        judgment, opts, pick = self.ask(fake)
        self.assertEqual(judgment.acted, jev.HEURISTIC)
        self.assertIs(jev_choices.dungeon_carried(opts, pick, judgment), pick)

    def test_agreement_is_recorded_as_both(self):
        fake = FakeJev(picks={"dungeon": "dire-maul-east-east"}, confidence=0.9)
        judgment, _opts, _pick = self.ask(fake)
        self.assertEqual(judgment.acted, jev.BOTH)

    def test_no_key_keeps_the_heuristic(self):
        fake = FakeJev()
        judgment, opts, pick = self.ask(fake, key="")
        self.assertEqual(fake.requests, [])
        self.assertEqual((judgment.status, judgment.jev), (jev.NO_KEY, ""))
        self.assertIs(jev_choices.dungeon_carried(opts, pick, judgment), pick)

    def test_off_or_a_single_run_asks_nothing(self):
        fake = FakeJev()
        judgment, _, _ = self.ask(fake, environ={"JEV_MODE_DUNGEON_CHOICE": "off"})
        self.assertIsNone(judgment)
        facts = self.facts()
        opts = campaignplan.options(facts)
        one = asyncio.run(
            jev_choices.dungeon_ask(
                jev.Client("k", transport=fake),
                facts,
                opts[:1],
                opts[0],
                jev_choices.policy(jev_choices.KIND_DUNGEON, {}),
            )
        )
        self.assertIsNone(one)
        self.assertEqual(fake.requests, [])

    def test_the_dungeon_acts_by_default_and_the_quest_aim_does_not(self):
        rule = jev_choices.policy(jev_choices.KIND_DUNGEON, {})
        self.assertEqual((rule.mode, rule.threshold), (jev.ACT, 0.7))
        shadow = jev_choices.policy(
            jev_choices.KIND_DUNGEON,
            {
                "JEV_MODE_DUNGEON_CHOICE": "shadow",
                "JEV_THRESHOLD_DUNGEON_CHOICE": "0.9",
            },
        )
        self.assertEqual((shadow.mode, shadow.threshold), (jev.SHADOW, 0.9))
        with self.assertLogs("wow-overseer.jev", "WARNING"):
            rule = jev_choices.policy(
                jev_choices.KIND_QUEST, {"JEV_MODE_QUEST_PICK": "act"}
            )
        self.assertEqual(rule.mode, jev.SHADOW)

    def test_the_record_line_says_who_chose(self):
        fake = FakeJev(picks={"dungeon": "dire-maul-north"}, confidence=0.9)
        judgment, _opts, _pick = self.ask(fake)
        line = judgment.line()
        self.assertIn("chose dire-maul-north", line)
        self.assertIn("acted=jev", line)
        self.assertEqual(judgment.agree, False)
        self.assertTrue(judgment.probabilities_json().startswith('{"dire-maul-north"'))


def quest(qid, title, level=10):
    return questbook.Quest(id=qid, title=title, quest_level=level)


LEDGER = questbook.Ledger(
    plans={"Ugga": (quest(60, "Candles"), quest(61, "Kobolds"), quest(64, "Unheld"))},
    behind={"Ugga": (quest(62, "Wolves"), quest(60, "Candles"))},
)
HELD = {"Ugga": frozenset({60, 61, 62}), "Grog": frozenset({60}), "Og": frozenset()}


class QuestCandidatesTest(unittest.TestCase):
    def test_the_first_candidate_is_drive_targets_answer(self):
        for wanted in (0, 61, 99):
            kw = dict(held_by_traveller={60, 61, 62}, wanted=wanted, beneficiary="Ugga")
            candidates = questbook.drive_candidates(LEDGER, **kw)
            self.assertEqual(candidates[0].id, questbook.drive_target(LEDGER, **kw))

    def test_only_held_quests_each_once_in_the_plans_order(self):
        candidates = questbook.drive_candidates(
            LEDGER, held_by_traveller={60, 61, 62}, wanted=61, beneficiary="Ugga"
        )
        self.assertEqual([q.id for q in candidates], [61, 60, 62])

    def test_nothing_held_is_no_candidate(self):
        self.assertEqual(
            questbook.drive_candidates(
                LEDGER, held_by_traveller=(), beneficiary="Ugga"
            ),
            (),
        )
        self.assertEqual(
            questbook.drive_target(LEDGER, held_by_traveller=(), beneficiary="Ugga"), 0
        )


class QuestShadowTest(unittest.TestCase):
    def test_the_choice_is_over_the_candidates_and_recorded_beside_the_aim(self):
        candidates = questbook.drive_candidates(
            LEDGER, held_by_traveller={60, 61, 62}, beneficiary="Ugga"
        )
        fake = FakeJev(picks={"quest": "q62"})
        client = jev.Client("k", transport=fake)
        judgment = asyncio.run(
            jev_choices.quest_shadow(
                client, candidates, 60, "Ugga", HELD, {"Ugga": 12}, jev.SHADOW
            )
        )
        [request] = fake.requests
        self.assertEqual(
            list(request["questions"]["quest"]["criteria"]), ["q60", "q61", "q62"]
        )
        candles = request["state"]["quests"][0]
        self.assertEqual(candles["held_by"], ["Grog", "Ugga"])
        self.assertEqual((judgment.heuristic, judgment.jev), ("q60", "q62"))
        self.assertEqual((judgment.subject, judgment.acted), ("Ugga", jev.HEURISTIC))

    def test_one_candidate_or_no_aim_asks_nothing(self):
        fake = FakeJev()
        client = jev.Client("k", transport=fake)
        one = (quest(60, "Candles"),)
        for candidates, chosen in ((one, 60), (one + (quest(61, "K"),), 0)):
            self.assertIsNone(
                asyncio.run(
                    jev_choices.quest_shadow(
                        client, candidates, chosen, "Ugga", HELD, {}, jev.SHADOW
                    )
                )
            )
        self.assertEqual(fake.requests, [])


class BridgeWiringTest(unittest.TestCase):
    """bridge.py is read as text: it imports discord and cannot be imported."""

    def body(self, name):
        start = BRIDGE.index(name)
        return BRIDGE[start : BRIDGE.index("\n    async def ", start + 10)]

    def test_the_council_no_longer_asks_which_door(self):
        body = self.body("    async def _council_once(")
        self.assertNotIn("_jev_council_shadow", BRIDGE)
        self.assertNotIn("dungeon_shadow", body)
        self.assertNotIn("await self._jev_quest_shadow", BRIDGE)

    def test_the_quest_shadow_reads_the_choice_that_was_just_made(self):
        body = self.body("    async def _council_once(")
        self.assertIn(
            "await asyncio.to_thread(_persist_council_plan, held.plan, seen)", body
        )
        self.assertIn("self._jev_quest_shadow(held.plan, seen, level_rows)", body)
        choose = BRIDGE[BRIDGE.index("def _choose_drive_quest(") :]
        choose = choose[: choose.index("\n\n\n")]
        self.assertIn(
            "seen.update(ledger=ledger, held=held, driveable=driveable", choose
        )
        persist = BRIDGE[BRIDGE.index("def _persist_council_plan(") :]
        self.assertIn("quest_id = _choose_drive_quest(plan, seen)", persist)

    def test_the_shadows_write_only_the_record(self):
        for name in (
            "    def _jev_quest_shadow(",
            "    def _jev_hold(",
        ):
            start = BRIDGE.index(name)
            body = BRIDGE[start : BRIDGE.index("\n    def ", start + 10)]
            self.assertNotIn("_insert_", body, name)
            self.assertNotIn("overseer_command", body, name)
            self.assertNotIn("UPDATE", body, name)


if __name__ == "__main__":
    unittest.main()

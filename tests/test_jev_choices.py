"""The council's dungeon and the quest aim, asked of Jev in shadow (#95).

Jev is shown exactly the options the heuristic chose from (the doors
council.door_refusal allows, the quests questbook.drive_target considers),
its answer is recorded beside the heuristic's, and nothing acts on it. The
tests run the real client over a fake transport and never call the API.
"""

import asyncio
import pathlib
import unittest

import council
import jev
import jev_choices
import questbook
from test_jev_items import FakeJev

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
NAMES = ("Grug", "Ugga", "Grog", "Bork", "Og")
EASTERN_KINGDOMS = 0


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


class DungeonShadowTest(unittest.TestCase):
    def ask(self, fake, key="k", mode=jev.SHADOW):
        doors, pick = council.dungeon_doors(rows(), [], None)
        client = jev.Client(key, transport=fake)
        return (
            asyncio.run(
                jev_choices.dungeon_shadow(client, doors, pick, rows(), {}, mode)
            ),
            doors,
        )

    def test_the_choice_is_over_the_allowed_doors_and_recorded_beside_the_pick(self):
        fake = FakeJev(picks={"dungeon": "uldaman"})
        judgment, doors = self.ask(fake)
        [request] = fake.requests
        offered = list(request["questions"]["dungeon"]["criteria"])
        self.assertEqual(offered, [d.keyword for d in doors])
        self.assertEqual(judgment.kind, jev_choices.KIND_DUNGEON)
        self.assertEqual(
            (judgment.heuristic, judgment.jev), ("scarlet-cathedral", "uldaman")
        )
        self.assertEqual(judgment.acted, jev.HEURISTIC)
        self.assertEqual(judgment.mode, jev.SHADOW)

    def test_no_key_asks_nothing(self):
        fake = FakeJev()
        judgment, _doors = self.ask(fake, key="")
        self.assertEqual(fake.requests, [])
        self.assertEqual((judgment.status, judgment.jev), (jev.NO_KEY, ""))

    def test_off_or_a_single_door_asks_nothing(self):
        fake = FakeJev()
        judgment, _ = self.ask(fake, mode=jev.OFF)
        self.assertIsNone(judgment)
        doors, pick = council.dungeon_doors(rows(), [], None)
        client = jev.Client("k", transport=fake)
        one = asyncio.run(
            jev_choices.dungeon_shadow(client, doors[:1], pick, rows(), {}, jev.SHADOW)
        )
        self.assertIsNone(one)
        self.assertEqual(fake.requests, [])

    def test_act_is_not_built_and_says_so(self):
        with self.assertLogs("wow-overseer.jev", "WARNING"):
            rule = jev_choices.policy(
                jev_choices.KIND_DUNGEON, {"JEV_MODE_DUNGEON_CHOICE": "act"}
            )
        self.assertEqual(rule.mode, jev.SHADOW)
        self.assertEqual(
            jev_choices.policy(jev_choices.KIND_QUEST, {}).mode, jev.SHADOW
        )


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

    def test_the_council_asks_which_door_before_it_holds_and_never_waits(self):
        body = self.body("    async def _council_once(")
        ask = body.index("self._jev_council_shadow(level_rows, completed_runs)")
        self.assertLess(ask, body.index("held = council.hold("))
        self.assertNotIn("await self._jev_council_shadow", BRIDGE)
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
            "    def _jev_council_shadow(",
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

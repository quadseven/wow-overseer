"""Every family chooses, declares and walks to its own professions (#211).

Measured on wow-dev 2026-09-23 (read-only): the Horde family (Zug warrior 20,
Oz mage 19, Uzza priest 17, Zrog shaman 17, Zork druid 16) held no primary
profession, while `professions.ROSTER`, `_write_declared_professions` and the
learn-aim reconcile served only the Alliance family. mod-overseer had written a
`learn_skill` for all five from a hand-seeded permission, and nothing walked
any of them to a trainer.

Pinned here: which pairs a character may be offered, the class heuristic, Jev
choosing in act mode with the heuristic as the fallback (no key, no answer,
low confidence, shadow, off), that a held profession is never changed, the
rows the bridge writes, who leads the family to a trainer, and that the
bridge runs it for every other family. Jev is the real client over a fake
transport; no test touches a database or the Jev API.
"""

import asyncio
import json
import pathlib
import unittest

import jev
import learnaim
import professions
import tradechoice

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()

HORDE = [
    {"name": "Zug", "class_name": "Warrior", "level": 20},
    {"name": "Oz", "class_name": "Mage", "level": 19},
    {"name": "Uzza", "class_name": "Priest", "level": 17},
    {"name": "Zrog", "class_name": "Shaman", "level": 17},
    {"name": "Zork", "class_name": "Druid", "level": 16},
]
# What the Horde held on wow-dev: secondaries only.
SECONDARIES = {"first aid": 1, "cooking": 1, "fishing": 1}


def horde(skills=None, trades=()):
    skills = skills or {}
    return tradechoice.members_from(
        HORDE,
        {m["name"]: dict(SECONDARIES, **skills.get(m["name"], {})) for m in HORDE},
        list(trades),
    )


class FakeJev:
    """A transport answering the pair question with `picks[name]`, else the first option."""

    def __init__(self, picks=None, confidence=0.8, status=200):
        self.picks = picks or {}
        self.confidence = confidence
        self.status = status
        self.requests = []

    def __call__(self, url, body, headers, timeout):
        request = json.loads(body)
        self.requests.append(request)
        if self.status != 200:
            return self.status, b"{}"
        name = request["state"]["character"]["name"]
        options = list(request["questions"]["pair"]["criteria"])
        pick = self.picks.get(name, options[0])
        rest = 0.2 / max(1, len(options) - 1)
        answer = {
            "type": "choice",
            "choice": pick,
            "probabilities": {o: (0.8 if o == pick else rest) for o in options},
            "confidence": self.confidence,
        }
        return 200, json.dumps(
            {"model": "jev-test", "answers": {"pair": answer}}
        ).encode()


def choose(members, fake=None, key="k", mode=jev.ACT, floor=0.5):
    client = jev.Client(key, transport=fake or FakeJev())
    return asyncio.run(tradechoice.choose(client, members, mode_now=mode, floor=floor))


def pairs(decisions):
    return {d.character: tradechoice.key_of(d.pair) for d in decisions}


class TheOptions(unittest.TestCase):
    def member(self, name):
        return next(m for m in horde() if m.name == name)

    def test_a_warrior_is_never_offered_cloth_or_leather_crafts(self):
        offered = tradechoice.options(self.member("Zug"), ())
        self.assertTrue(offered)
        for key in offered:
            self.assertNotIn("tailoring", key)
            self.assertNotIn("leatherworking", key)

    def test_a_mage_is_offered_tailoring_and_not_blacksmithing(self):
        offered = tradechoice.options(self.member("Oz"), ())
        self.assertIn("enchanting+tailoring", offered)
        self.assertFalse(any("blacksmithing" in k for k in offered))

    def test_inscription_and_jewelcrafting_are_left_to_the_guild(self):
        for m in horde():
            for key in tradechoice.options(m, ()):
                self.assertNotIn("inscription", key)
                self.assertNotIn("jewelcrafting", key)

    def test_every_pair_crafts_something(self):
        for key in tradechoice.options(self.member("Zork"), ()):
            self.assertTrue(set(key.split("+")) & professions.CRAFTING, key)

    def test_a_craft_the_family_already_has_is_not_offered_again(self):
        offered = tradechoice.options(self.member("Uzza"), (), frozenset({"tailoring"}))
        self.assertFalse(any("tailoring" in k for k in offered))
        self.assertIn("herbalism+alchemy", offered)

    def test_when_every_fitting_craft_is_taken_doubling_is_allowed(self):
        taken = frozenset({"alchemy", "enchanting", "engineering", "tailoring"})
        offered = tradechoice.options(self.member("Zrog"), (), taken)
        self.assertIn("mining+engineering", offered)

    def test_a_held_primary_is_in_every_offer(self):
        offered = tradechoice.options(self.member("Oz"), ("tailoring",))
        self.assertTrue(offered)
        for key in offered:
            self.assertIn("tailoring", key.split("+"))

    def test_two_held_primaries_leave_nothing_to_choose(self):
        self.assertEqual(
            {}, tradechoice.options(self.member("Oz"), ("mining", "tailoring"))
        )


class TheHeuristic(unittest.TestCase):
    def test_the_horde_gets_a_complementary_set_that_suits_each_class(self):
        got = pairs(choose(horde(), key=""))
        self.assertEqual(
            {
                "Zug": "mining+blacksmithing",
                "Oz": "enchanting+tailoring",
                "Uzza": "herbalism+alchemy",
                "Zrog": "mining+engineering",
                "Zork": "skinning+leatherworking",
            },
            got,
        )

    def test_no_craft_is_doubled(self):
        crafts = [
            s
            for d in choose(horde(), key="")
            for s in d.pair
            if s in professions.CRAFTING
        ]
        self.assertEqual(len(crafts), len(set(crafts)))


class JevDecides(unittest.TestCase):
    def test_in_act_mode_jevs_confident_pick_is_used(self):
        fake = FakeJev(picks={"Zug": "mining+engineering"})
        got = choose(horde(), fake)
        zug = next(d for d in got if d.character == "Zug")
        self.assertEqual(("mining", "engineering"), zug.pair)
        self.assertEqual(tradechoice.JEV, zug.source)
        self.assertEqual("mining+blacksmithing", zug.judgment.heuristic)
        self.assertEqual("mining+engineering", zug.judgment.jev)
        self.assertFalse(zug.judgment.agree)
        self.assertEqual(tradechoice.KIND, zug.judgment.kind)

    def test_the_family_so_far_is_in_each_question(self):
        fake = FakeJev(picks={"Zug": "mining+engineering"})
        choose(horde(), fake)
        oz = next(r for r in fake.requests if r["state"]["character"]["name"] == "Oz")
        family = {f["name"]: f["professions"] for f in oz["state"]["family"]}
        self.assertEqual(["mining", "engineering"], family["Zug"])
        self.assertEqual("not chosen yet", family["Zork"])

    def test_a_later_character_is_not_offered_a_craft_jev_already_gave(self):
        fake = FakeJev(picks={"Zug": "mining+engineering"})
        choose(horde(), fake)
        oz = next(r for r in fake.requests if r["state"]["character"]["name"] == "Oz")
        self.assertFalse(
            any("engineering" in k for k in oz["questions"]["pair"]["criteria"])
        )

    def test_below_the_minimum_confidence_the_heuristic_acts(self):
        fake = FakeJev(picks={"Zug": "mining+engineering"}, confidence=0.3)
        zug = next(d for d in choose(horde(), fake) if d.character == "Zug")
        self.assertEqual(("mining", "blacksmithing"), zug.pair)
        self.assertEqual(tradechoice.HEURISTIC, zug.source)
        self.assertEqual("mining+engineering", zug.judgment.jev)

    def test_in_shadow_mode_jev_is_recorded_and_the_heuristic_acts(self):
        fake = FakeJev(picks={"Zug": "mining+engineering"})
        zug = next(
            d for d in choose(horde(), fake, mode=jev.SHADOW) if d.character == "Zug"
        )
        self.assertEqual(("mining", "blacksmithing"), zug.pair)
        self.assertEqual(jev.SHADOW, zug.judgment.mode)
        self.assertEqual("mining+engineering", zug.judgment.jev)

    def test_off_asks_nothing(self):
        fake = FakeJev()
        got = choose(horde(), fake, mode=jev.OFF)
        self.assertEqual([], fake.requests)
        self.assertTrue(all(d.judgment is None for d in got))

    def test_without_a_key_the_heuristic_decides_and_says_why(self):
        got = choose(horde(), key="")
        zug = next(d for d in got if d.character == "Zug")
        self.assertEqual(("mining", "blacksmithing"), zug.pair)
        self.assertEqual(jev.NO_KEY, zug.judgment.status)
        self.assertIsNone(zug.judgment.agree)

    def test_when_jev_is_down_the_heuristic_decides(self):
        got = choose(horde(), FakeJev(status=503))
        self.assertEqual("mining+blacksmithing", pairs(got)["Zug"])
        self.assertTrue(all(d.source == tradechoice.HEURISTIC for d in got))


class NothingHeldIsChanged(unittest.TestCase):
    def test_a_trained_profession_is_kept_and_only_the_empty_slot_is_filled(self):
        members = horde(skills={"Oz": {"alchemy": 40}})
        oz = next(d for d in choose(members, key="") if d.character == "Oz")
        self.assertIn("alchemy", oz.pair)
        self.assertEqual(1, len(oz.learn))
        self.assertNotIn("alchemy", oz.learn)

    def test_a_character_with_both_slots_held_is_not_asked(self):
        fake = FakeJev()
        members = horde(skills={"Zug": {"mining": 30, "herbalism": 5}})
        got = choose(members, fake)
        self.assertNotIn("Zug", pairs(got))
        self.assertFalse(
            any(r["state"]["character"]["name"] == "Zug" for r in fake.requests)
        )

    def test_a_choice_already_recorded_is_not_made_again(self):
        trades = [
            {
                "character_name": "Zug",
                "verb": "learn",
                "skill_name": s,
                "skill_id": 0,
                "status": "planned",
            }
            for s in ("mining", "blacksmithing")
        ]
        got = choose(horde(trades=trades), key="")
        self.assertNotIn("Zug", pairs(got))
        self.assertIn(
            "blacksmithing",
            tradechoice.taken_crafts(
                {m.name: tradechoice.kept(m) for m in horde(trades=trades)}, "Oz"
            ),
        )


class WhatTheBridgeWrites(unittest.TestCase):
    def test_the_permission_is_the_kept_primaries_as_sorted_ids(self):
        members = tradechoice.with_decisions(horde(), choose(horde(), key=""))
        got = dict((n, ids) for ids, n in tradechoice.declarations(members, {}))
        self.assertEqual("164,186", got["Zug"])
        self.assertEqual("197,333", got["Oz"])

    def test_an_unchanged_permission_is_not_rewritten(self):
        members = tradechoice.with_decisions(horde(), choose(horde(), key=""))
        current = {n: ids for ids, n in tradechoice.declarations(members, {})}
        self.assertEqual([], tradechoice.declarations(members, current))

    def test_no_secondary_ever_reaches_the_permission(self):
        members = tradechoice.with_decisions(horde(), choose(horde(), key=""))
        secondary = {str(professions.skill_id(s)) for s in professions.SECONDARY}
        for ids, _name in tradechoice.declarations(members, {}):
            self.assertFalse(set(ids.split(",")) & secondary)

    def test_the_reason_names_the_chooser(self):
        zug = next(d for d in choose(horde(), key="") if d.character == "Zug")
        self.assertIn(
            "Zug takes mining + blacksmithing, chosen by heuristic", zug.reason()
        )

    def test_the_record_fits_its_columns(self):
        fake = FakeJev()
        for d in choose(horde(), fake):
            j = d.judgment
            self.assertLessEqual(len(j.heuristic), 40)
            self.assertLessEqual(len(j.jev), 40)
            self.assertLessEqual(len(j.probabilities_json()), 1000)
            self.assertEqual(j.subject, j.holder)


def row(name, lead=0, learn=0, travel="", professions_=""):
    return learnaim.Row(
        character=name,
        learn_skill=learn,
        travel_npc=travel,
        leads=bool(lead),
        wanted=(learn,) if learn else (),
    )


class WhoLeadsToTheTrainer(unittest.TestCase):
    def test_a_trainee_borrows_the_lead_from_an_idle_head(self):
        rows = [row("Zug", lead=1), row("Oz", learn=197)]
        self.assertEqual("Oz", tradechoice.next_lead(rows, leader="Zug", head="Zug"))

    def test_a_leader_with_its_own_errand_keeps_the_lead(self):
        rows = [row("Zug", lead=1, learn=186), row("Oz", learn=197)]
        self.assertEqual("Zug", tradechoice.next_lead(rows, leader="Zug", head="Zug"))

    def test_a_leader_on_a_journey_is_not_stranded(self):
        rows = [row("Zug", lead=1, travel="vendor"), row("Oz", learn=197)]
        self.assertEqual("Zug", tradechoice.next_lead(rows, leader="Zug", head="Zug"))

    def test_the_head_takes_the_lead_back_when_no_errand_is_left(self):
        rows = [row("Zug"), row("Oz", lead=1)]
        self.assertEqual("Zug", tradechoice.next_lead(rows, leader="Oz", head="Zug"))

    def test_a_borrower_past_its_bound_is_skipped(self):
        rows = [row("Zug", lead=1), row("Oz", learn=197), row("Uzza", learn=171)]
        got = tradechoice.next_lead(
            rows, leader="Zug", head="Zug", expired=frozenset({"Oz"})
        )
        self.assertEqual("Uzza", got)

    def test_the_bound_outlives_a_return_of_the_lead(self):
        rows = [row("Zug", lead=1), row("Oz", learn=197)]
        since = tradechoice.borrow_clock({}, rows, "Oz", "Zug", now=0.0)
        self.assertEqual({"Oz": 0.0}, since)
        since = tradechoice.borrow_clock(since, rows, "Zug", "Zug", now=10.0)
        self.assertEqual({"Oz": 0.0}, since)
        self.assertEqual(frozenset({"Oz"}), tradechoice.expired(since, 7.0, 6.0))
        done = [row("Zug", lead=1), row("Oz")]
        self.assertEqual({}, tradechoice.borrow_clock(since, done, "Zug", "Zug", 20.0))

    def test_the_new_leader_is_aimed_at_a_trainer(self):
        rows = tradechoice.led_by([row("Zug", lead=1), row("Oz", learn=197)], "Oz")
        plan = learnaim.plan(rows)
        self.assertEqual("Oz", plan.aim)
        self.assertEqual(197, plan.skill)

    def test_learn_rows_take_the_new_permission(self):
        roster = [
            {
                "name": "Oz",
                "lead": 0,
                "professions": "202,755",
                "travel_npc": "",
                "learn_skill": 202,
            }
        ]
        rows = tradechoice.learn_rows(roster, [], {"Oz": "197,333"})
        self.assertEqual((197, 333), rows[0].wanted)
        self.assertEqual(learnaim.UNASSIGNED, learnaim.finished(rows[0]))


class TheModeSwitch(unittest.TestCase):
    def test_unset_means_act(self):
        self.assertEqual(jev.ACT, tradechoice.mode({}))

    def test_the_operator_can_turn_it_to_shadow_or_off(self):
        self.assertEqual(jev.SHADOW, tradechoice.mode({tradechoice.MODE_ENV: "shadow"}))
        self.assertEqual(jev.OFF, tradechoice.mode({tradechoice.MODE_ENV: "off"}))

    def test_the_switch_is_named_for_the_kind(self):
        self.assertEqual("JEV_MODE_PROFESSION_CHOICE", tradechoice.MODE_ENV)

    def test_the_minimum_confidence_is_read_and_clamped(self):
        env = tradechoice.MIN_CONFIDENCE_ENV
        self.assertEqual(0.5, tradechoice.min_confidence({}))
        self.assertEqual(0.7, tradechoice.min_confidence({env: "0.7"}))
        self.assertEqual(1.0, tradechoice.min_confidence({env: "3"}))
        self.assertEqual(0.5, tradechoice.min_confidence({env: "high"}))
        self.assertEqual(0.5, tradechoice.min_confidence({env: "nan"}))
        self.assertEqual(0.5, tradechoice.min_confidence({env: "inf"}))


def _block(start: str, end: str) -> str:
    body = BRIDGE[BRIDGE.index(start) :]
    return body[: body.index(end)]


class TheBridgeRunsItForEveryFamily(unittest.TestCase):
    def test_the_protect_cycle_runs_it_after_this_familys_own_learn_aims(self):
        cycle = _block(
            "async def _protect_characters(self)", "async def _share_quests_loop"
        )
        own = cycle.index("await self._reconcile_learn_aims()")
        self.assertGreater(cycle.index("await self._trades_for_every_family()"), own)

    def test_every_other_family_is_passed_and_guarded_on_its_own(self):
        body = _block(
            "async def _trades_for_every_family(self)", "async def _family_trades_once"
        )
        self.assertIn("_other_cohorts, own", body)
        self.assertIn("await self._family_trades_once(cohort)", body)
        self.assertIn("except Exception:", body)

    def test_the_choice_is_recorded_before_the_permission_is_written(self):
        body = _block(
            "async def _family_trades_once(self, cohort)",
            "async def _family_learn_aims",
        )
        self.assertIn("tradechoice.choose(", body)
        self.assertIn("_insert_jev_judgment, decision.judgment", body)
        self.assertLess(
            body.index("_record_family_choice, decision"),
            body.index("_declare_family_professions, changes"),
        )
        self.assertIn('_settle_trades, state["skills"]', body)

    def test_the_lead_and_the_aim_use_the_familys_own_rows_and_slot(self):
        body = _block(
            "async def _family_learn_aims(self, cohort",
            "async def _bag_purchase_and_trip",
        )
        self.assertIn("_mark_party_leader, lead", body)
        self.assertIn("learnaim.statements(learn_plan)", body)
        self.assertIn("self._cohort_town_slot(cohort.key).adopt(", body)
        self.assertIn("ERRAND_LEAD_HOURS", body)

    def test_the_family_read_is_scoped_and_fails_closed(self):
        body = _block(
            "def _family_trade_state(family: str)", "def _record_family_choice"
        )
        self.assertIn("(1054, 1146)", body)
        self.assertIn("AND family = %s", _block("_FAMILY_TRADE_ROSTER_SQL = (", ")\n"))

    def test_a_recorded_choice_is_never_overwritten(self):
        body = _block(
            "def _record_family_choice(decision)", "def _declare_family_professions"
        )
        self.assertIn("INSERT IGNORE INTO overseer_trade", body)


if __name__ == "__main__":
    unittest.main()

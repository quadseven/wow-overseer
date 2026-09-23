"""Jev acts where its kind's policy says it may, through the heuristic's own rows (#95, #184).

Every case runs the real client over a fake transport (test_jev_items.FakeJev)
or builds judgments by hand; nothing here calls the API. What is asserted:

  * who acts is the policy's answer (mode, threshold, the agreement rule), and
    it is recorded on the judgment as `acted`;
  * acting reaches the world only as the equip pass's `e Hitem:` row, a piece
    left in the bags, or a hand-off withheld, and a guild route reordered
    among its own receivers;
  * a slow, absent or unsure Jev changes nothing.
"""

import asyncio
import json
import unittest
from dataclasses import replace

import bag_pressure
import gear
import jev
import jev_items
from test_jev_items import CARDS, NAMES, WORN, FakeJev, carried, chest, run

PROC_BLADE = 9001
CARDS[PROC_BLADE] = {
    "name": "Proc Blade",
    "item_level": 45,
    "slot": "One-Hand",
    "effects": ["Chance on hit: Wounds the target for 50 damage."],
}


def proc_blade(holder, guid):
    """A one-hand sword with an on-hit effect, bind on equip."""
    return carried(
        holder=holder,
        item_guid=guid,
        entry=PROC_BLADE,
        name="Proc Blade",
        inventory_type=13,
        item_level=45,
        required_level=40,
        quality=2,
        item_subclass=7,
    )


def policies(**modes):
    env = {"JEV_MODE_" + k.upper(): v for k, v in modes.items()}
    return jev_items.policies(env)


def plan_for(rows, fake, rules=None):
    judgments = run(rows, fake)
    routes = {g: r for g, (r, _why) in jev_items.heuristic(rows, WORN, NAMES).items()}
    return jev_items.act_plan(judgments, rules or policies(), routes)


def of(plan, kind, subject):
    [j] = [j for j in plan.judgments if j.kind == kind and j.subject == subject]
    return j


class PolicyTest(unittest.TestCase):
    def test_the_defaults_are_the_operators(self):
        rules = policies()
        self.assertEqual(rules[jev_items.KIND_WEAPON].mode, jev.ACT)
        self.assertEqual(rules[jev_items.KIND_WEAPON].threshold, 0.85)
        self.assertEqual(rules[jev_items.KIND_DISPOSITION].mode, jev.ACT)
        self.assertEqual(rules[jev_items.KIND_DISPOSITION].threshold, 0.80)
        self.assertTrue(rules[jev_items.KIND_DISPOSITION].on_agreement)
        guild = jev_items.guild_policy({})
        self.assertEqual((guild.mode, guild.threshold), (jev.ACT, 0.80))

    def test_the_environment_overrides_each_kind(self):
        env = {"JEV_MODE_WEAPON_CHOICE": "shadow", "JEV_THRESHOLD_WEAPON_CHOICE": "0.9"}
        rule = jev_items.policies(env)[jev_items.KIND_WEAPON]
        self.assertEqual((rule.mode, rule.threshold), (jev.SHADOW, 0.9))

    def test_an_unreadable_threshold_or_mode_is_the_safe_reading(self):
        with self.assertLogs("wow-overseer.jev", "WARNING"):
            self.assertEqual(jev.threshold("k", {"JEV_THRESHOLD_K": "1.5"}, 0.85), 0.85)
        with self.assertLogs("wow-overseer.jev", "WARNING"):
            self.assertEqual(
                jev.threshold("k", {"JEV_THRESHOLD_K": "high"}, 0.85), 0.85
            )
        with self.assertLogs("wow-overseer.jev", "WARNING"):
            self.assertEqual(
                jev.mode("k", {"JEV_MODE_K": "yes"}, default=jev.ACT), jev.SHADOW
            )
        self.assertEqual(jev.mode("k", {}, default=jev.ACT), jev.ACT)
        self.assertEqual(jev.mode("k", {}), jev.SHADOW)

    def test_who_acts(self):
        rule = jev.Policy("k", jev.ACT, 0.85)
        self.assertEqual(rule.acted("a", "b", 0.9), jev.JEV)
        self.assertEqual(rule.acted("a", "b", 0.84), jev.HEURISTIC)
        self.assertEqual(rule.acted("a", "a", 0.9), jev.BOTH)
        self.assertEqual(rule.acted("a", "a", 0.5), jev.HEURISTIC)
        self.assertEqual(rule.acted("a", "b", 0.9, can_act=False), jev.HEURISTIC)
        self.assertEqual(rule.acted("a", "", None), jev.HEURISTIC)
        agreeing = jev.Policy("k", jev.ACT, 0.8, on_agreement=True)
        self.assertEqual(agreeing.acted("a", "a", 0.4), jev.BOTH)
        self.assertEqual(agreeing.acted("a", "b", 0.79), jev.HEURISTIC)
        shadow = jev.Policy("k", jev.SHADOW, 0.0)
        self.assertEqual(shadow.acted("a", "b", 1.0), jev.HEURISTIC)


class WeaponActTest(unittest.TestCase):
    def test_a_sure_carried_is_put_on_through_the_equip_row(self):
        """Grog wields Moon Cleaver (52); a Proc Blade (45) never beats it by
        item level, so the heuristic leaves it. Jev at 0.9 puts it on."""
        rows = [proc_blade("Grog", 777)]
        plan = plan_for(rows, FakeJev(picks={"better": "carried"}, confidence=0.9))
        judgment = of(plan, jev_items.KIND_WEAPON, "Grog")
        self.assertEqual((judgment.heuristic, judgment.jev), ("worn", "carried"))
        self.assertEqual(judgment.acted, jev.JEV)
        self.assertIn(777, plan.equip)
        self.assertIn(777, plan.no_give)
        wanted = bag_pressure.holder_equips(rows, WORN, NAMES)
        self.assertEqual(wanted, ())
        [equip] = bag_pressure.jev_equips(wanted, rows, WORN, NAMES, plan)
        self.assertEqual(equip.command, "e Hitem:%d:0" % PROC_BLADE)
        self.assertEqual(equip.holder, "Grog")
        self.assertIn("Jev judged", equip.reason)

    def test_below_the_threshold_nothing_changes(self):
        rows = [proc_blade("Grog", 777)]
        rules = policies(item_disposition="shadow")
        fake = FakeJev(picks={"better": "carried"}, confidence=0.84)
        plan = plan_for(rows, fake, rules)
        self.assertEqual(of(plan, jev_items.KIND_WEAPON, "Grog").acted, jev.HEURISTIC)
        self.assertFalse(plan.changes)

    def test_shadow_changes_nothing(self):
        rows = [proc_blade("Grog", 777)]
        rules = policies(weapon_choice="shadow", item_disposition="shadow")
        plan = plan_for(
            rows, FakeJev(picks={"better": "carried"}, confidence=0.99), rules
        )
        self.assertFalse(plan.changes)
        self.assertEqual({j.acted for j in plan.judgments}, {jev.HEURISTIC})

    def test_no_key_changes_nothing(self):
        rows = [proc_blade("Grog", 777)]
        judgments = run(rows, key="")
        plan = jev_items.act_plan(judgments, policies(), {777: jev_items.KEEP})
        self.assertFalse(plan.changes)
        self.assertEqual({j.acted for j in plan.judgments}, {jev.HEURISTIC})

    def test_a_sure_worn_leaves_the_heuristics_equip_in_the_bags(self):
        """Grug (main hand 30) would put a Proc Blade (45) on by item level."""
        rows = [proc_blade("Grug", 778)]
        wanted = bag_pressure.holder_equips(rows, WORN, NAMES)
        self.assertEqual([e.guid for e in wanted], [778])
        plan = plan_for(rows, FakeJev(picks={"better": "worn"}, confidence=0.9))
        self.assertEqual(of(plan, jev_items.KIND_WEAPON, "Grug").acted, jev.JEV)
        self.assertEqual(plan.no_equip, frozenset({778}))
        self.assertEqual(
            bag_pressure.jev_equips(wanted, rows, WORN, NAMES, plan),
            (),
        )

    def test_a_question_about_somebody_else_never_acts(self):
        """A hand-off Jev prefers that the heuristic did not name has no row
        of its own; the heuristic stands."""
        rows = [proc_blade("Grog", 777)]
        plan = plan_for(rows, FakeJev(picks={"better": "worn"}, confidence=0.99))
        grug = of(plan, jev_items.KIND_WEAPON, "Grug")
        self.assertNotEqual(grug.heuristic, grug.jev)
        self.assertEqual(grug.acted, jev.HEURISTIC)

    def test_a_piece_bound_for_a_sale_is_never_put_on(self):
        judgment = jev_items.Judgment(
            kind=jev_items.KIND_WEAPON,
            subject="Grog",
            holder="Grog",
            item_guid=5,
            item_entry=PROC_BLADE,
            item_name="Proc Blade",
            heuristic="worn",
            heuristic_why="",
            mode=jev.ACT,
            status=jev.ANSWERED,
            jev="carried",
            confidence=0.99,
        )
        plan = jev_items.act_plan([judgment], policies(), {5: jev_items.VENDOR})
        self.assertFalse(plan.changes)
        self.assertEqual(plan.judgments[0].acted, jev.HEURISTIC)

    def test_the_owners_mark_is_never_put_on(self):
        rows = [proc_blade("Grog", 777)]
        plan = jev_items.ActPlan(
            equip={777: "why"}, no_equip=frozenset(), no_give=frozenset(), judgments=()
        )
        picks = bag_pressure.jev_equips(
            (), rows, WORN, NAMES, plan, keep_names=("Proc Blade",)
        )
        self.assertEqual(picks, ())
        self.assertEqual(len(bag_pressure.jev_equips((), rows, WORN, NAMES, plan)), 1)

    def test_no_plan_leaves_the_heuristics_equips(self):
        rows = [proc_blade("Grug", 778)]
        wanted = bag_pressure.holder_equips(rows, WORN, NAMES)
        self.assertEqual(
            bag_pressure.jev_equips(wanted, rows, WORN, NAMES, None), wanted
        )


class DispositionActTest(unittest.TestCase):
    def judgment(self, heuristic, answer, confidence, status=jev.ANSWERED):
        return jev_items.Judgment(
            kind=jev_items.KIND_DISPOSITION,
            subject="Grog",
            holder="Grog",
            item_guid=9,
            item_entry=7527,
            item_name="Cabalist Chestpiece",
            heuristic=heuristic,
            heuristic_why="",
            mode=jev.ACT,
            status=status,
            jev=answer,
            confidence=confidence,
        )

    def act(self, *judgments):
        return jev_items.act_plan(judgments, policies(), {9: judgments[0].heuristic})

    def test_agreement_at_any_confidence_is_recorded_as_both(self):
        plan = self.act(self.judgment("equip", "equip", 0.36))
        self.assertEqual(plan.judgments[0].acted, jev.BOTH)
        self.assertFalse(plan.changes)

    def test_a_difference_below_point_eight_is_the_heuristics(self):
        plan = self.act(self.judgment("equip", "keep", 0.79))
        self.assertEqual(plan.judgments[0].acted, jev.HEURISTIC)
        self.assertFalse(plan.changes)

    def test_a_sure_keep_withholds_the_equip_or_the_hand_off(self):
        plan = self.act(self.judgment("equip", "keep", 0.8))
        self.assertEqual(plan.judgments[0].acted, jev.JEV)
        self.assertEqual(plan.no_equip, frozenset({9}))
        plan = self.act(self.judgment("give:Grug", "keep", 0.9))
        self.assertEqual(plan.no_give, frozenset({9}))

    def test_a_sure_equip_puts_it_on_instead_of_handing_it_off(self):
        plan = self.act(self.judgment("give:Grug", "equip", 0.9))
        self.assertEqual(plan.judgments[0].acted, jev.JEV)
        self.assertIn(9, plan.equip)
        self.assertEqual(plan.no_give, frozenset({9}))

    def test_routes_with_no_act_path_are_the_heuristics(self):
        for heuristic, answer in (
            ("vendor", "keep"),
            ("auction", "equip"),
            ("keep", "vendor"),
            ("keep", "give:Grug"),
        ):
            plan = self.act(self.judgment(heuristic, answer, 0.99))
            self.assertEqual(plan.judgments[0].acted, jev.HEURISTIC, answer)
            self.assertFalse(plan.changes)

    def test_a_late_answer_is_the_heuristics(self):
        [late] = jev_items.heuristic_acted([self.judgment("equip", "keep", 0.99)])
        self.assertEqual(late.acted, jev.HEURISTIC)

    def test_a_withheld_hand_off_becomes_a_note(self):
        grant = gear.Grant(
            holder="Grog",
            taker="Grug",
            entry=7527,
            name="Cabalist Chestpiece",
            guid=9,
            reason="",
            said="",
        )
        plan = gear.Plan(grants=(grant,))
        act = self.act(self.judgment("give:Grug", "keep", 0.9))
        kept = jev_items.withhold_gifts(plan, act)
        self.assertEqual(kept.grants, ())
        self.assertIn("Jev acted", kept.notes[0])
        self.assertIs(jev_items.withhold_gifts(plan, None), plan)

    def test_the_record_line_says_who_acted(self):
        [marked] = self.act(self.judgment("equip", "keep", 0.9)).judgments
        self.assertIn("acted=jev", marked.line())
        self.assertNotEqual(
            marked.signature, self.judgment("equip", "keep", 0.9).signature
        )

    def test_a_real_pass_agrees_and_acts_on_nothing_new(self):
        rows = [chest()]
        plan = plan_for(rows, FakeJev(picks={"route": "equip"}, confidence=0.4))
        self.assertEqual(of(plan, jev_items.KIND_DISPOSITION, "Grog").acted, jev.BOTH)
        self.assertFalse(plan.changes)


# ---------------------------------------------------------------------------
# WHO IN THE GUILD GAINS MOST (#184)


class FakeScores:
    """A transport answering each Score question from `scores[name]`, found
    by the candidate's name in the question's instructions."""

    def __init__(self, scores, confidence=0.9):
        self.scores = scores
        self.confidence = confidence
        self.requests = []

    def __call__(self, url, body, headers, timeout):
        request = json.loads(body)
        self.requests.append(request)
        answers = {}
        for qid, question in request["questions"].items():
            name = next(
                n for n in self.scores if "is %s," % n in question["instructions"]
            )
            value = self.scores[name]
            levels = [str(n) for n in range(len(question["criteria"]))]
            answers[qid] = {
                "type": "score",
                "score": value,
                "probabilities": {k: (1.0 if int(k) == value else 0.0) for k in levels},
                "confidence": self.confidence,
            }
        return 200, json.dumps({"model": "jev-1.13.0", "answers": answers}).encode()


def ranked(name, gain, family=False):
    return gear.Ranked(
        name=name, gain=gain, family=family, fills_weakest=False, sure=True, reason="r"
    )


DESTINY = gear.Holding(
    holder="Avenah",
    guid=4909901,
    entry=647,
    name="Destiny",
    quality=4,
    item_level=57,
    required_level=52,
    allowable_class=-1,
    inventory_type=17,
    item_class=2,
)


def route(taker, gain, alternates=()):
    return gear.Route(
        holder="Avenah",
        taker=taker,
        guid=4909901,
        entry=647,
        name="Destiny",
        gain=gain,
        family=True,
        fills_weakest=False,
        reason="r",
        alternates=alternates,
    )


def guild_pass(scores, confidence=0.9, routes=None, key="k"):
    grants = (
        routes
        if routes is not None
        else (route("Grug", 27, alternates=(route("Grog", 5),)),)
    )
    ranking = (ranked("Grug", 27, True), ranked("Grog", 5, True))
    asks = jev_items.recipient_asks([DESTINY], [], grants, lambda h, c: ranking)
    fake = FakeScores(scores, confidence)
    client = jev.Client(key, transport=fake)
    judgments = asyncio.run(
        jev_items.recipient_pass(client, asks, lambda e: CARDS.get(e), {}, jev.ACT)
    )
    return gear.Plan(grants=tuple(grants)), judgments, fake


class GuildRecipientTest(unittest.TestCase):
    def test_one_request_per_item_one_score_per_candidate(self):
        _plan, [judgment], fake = guild_pass({"Grug": 1, "Grog": 3})
        [request] = fake.requests
        self.assertEqual(sorted(request["questions"]), ["c0", "c1"])
        self.assertEqual({q["type"] for q in request["questions"].values()}, {"score"})
        self.assertEqual(len(request["state"]["candidates"]), 2)
        self.assertEqual((judgment.heuristic, judgment.jev), ("Grug", "Grog"))
        self.assertEqual(judgment.probabilities, {"Grug": 1 / 3, "Grog": 1.0})

    def test_a_sure_pick_among_the_routes_receivers_leads_the_route(self):
        plan, judgments, _ = guild_pass({"Grug": 1, "Grog": 3}, confidence=0.9)
        out, [marked] = jev_items.reroute(plan, judgments, jev_items.guild_policy({}))
        self.assertEqual(marked.acted, jev.JEV)
        [first] = out.grants
        self.assertEqual(first.taker, "Grog")
        self.assertEqual([a.taker for a in first.alternates], ["Grug"])
        self.assertEqual(first.command, "guid:4909901")

    def test_an_unsure_pick_leaves_the_ranking(self):
        plan, judgments, _ = guild_pass({"Grug": 1, "Grog": 3}, confidence=0.7)
        out, [marked] = jev_items.reroute(plan, judgments, jev_items.guild_policy({}))
        self.assertEqual(marked.acted, jev.HEURISTIC)
        self.assertEqual(out.grants[0].taker, "Grug")

    def test_a_pick_outside_the_routes_receivers_never_moves_it(self):
        """Grog is ranked but under the clear gain, so not on the route."""
        plan, judgments, _ = guild_pass(
            {"Grug": 1, "Grog": 3}, routes=(route("Grug", 27),)
        )
        out, [marked] = jev_items.reroute(plan, judgments, jev_items.guild_policy({}))
        self.assertEqual(marked.acted, jev.HEURISTIC)
        self.assertEqual(out, plan)

    def test_a_tie_at_the_top_is_no_pick(self):
        _plan, [judgment], _ = guild_pass({"Grug": 2, "Grog": 2})
        self.assertEqual(judgment.jev, jev_items.NOBODY)

    def test_an_item_the_ranking_does_not_move_is_asked_and_never_moved(self):
        plan, [judgment], _ = guild_pass({"Grug": 1, "Grog": 3}, routes=())
        self.assertEqual(judgment.heuristic, jev_items.NOBODY)
        out, [marked] = jev_items.reroute(plan, [judgment], jev_items.guild_policy({}))
        self.assertEqual(out.grants, ())
        self.assertEqual(marked.acted, jev.HEURISTIC)

    def test_no_key_leaves_every_route(self):
        plan, judgments, fake = guild_pass({"Grug": 1, "Grog": 3}, key="")
        self.assertEqual(fake.requests, [])
        out, [marked] = jev_items.reroute(plan, judgments, jev_items.guild_policy({}))
        self.assertEqual(out, plan)
        self.assertEqual((marked.status, marked.acted), (jev.NO_KEY, jev.HEURISTIC))

    def test_off_asks_nothing(self):
        client = jev.Client("k", transport=FakeScores({}))
        self.assertEqual(
            asyncio.run(
                jev_items.recipient_pass(client, [object()], None, {}, jev.OFF)
            ),
            [],
        )


class MergeTest(unittest.TestCase):
    def equip(self, guid, slot, holder="Grog"):
        return gear.Equip(holder, guid, guid, "x", slot, 50, 40, "r")

    def test_a_chosen_two_hander_displaces_the_hands(self):
        wanted = (
            self.equip(1, "main_hand"),
            self.equip(2, "off_hand"),
            self.equip(3, "chest"),
        )
        out = gear.merge_equips(wanted, (), (self.equip(4, "two_hand"),))
        self.assertEqual(sorted(e.guid for e in out), [3, 4])

    def test_withheld_pieces_are_dropped(self):
        out = gear.merge_equips((self.equip(1, "chest"),), {1}, ())
        self.assertEqual(out, ())

    def test_chosen_equip_refuses_somebody_elses_piece(self):
        [grug] = [c for c in gear.characters_from_rows(WORN, NAMES) if c.name == "Grug"]
        holding = gear.holdings_from_rows([proc_blade("Grog", 5)])[0]
        self.assertIsNone(gear.chosen_equip(holding, grug, "r"))
        self.assertIsNotNone(
            gear.chosen_equip(replace(holding, holder="Grug"), grug, "r")
        )


if __name__ == "__main__":
    unittest.main()

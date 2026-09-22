"""Whose bags a reagent should end up in, and only there (infra#2830).

Pure unit tests against synthetic Holdings - this suite proves the DECISION
is right for the inputs given. It does not, and cannot, prove that
bridge.py's SQL produces those inputs correctly against a live server:
`wow-dev` was mid-RAM-swap when this landed, so that half is unverified and
materials.py's own docstring says so. See tests/test_give.py for what IS
proven about the mechanism the decision here is turned into (kind='give').
"""

import unittest

import chat
import materials
import professions


def _holding(holder, material, count, guid):
    return materials.Holding(holder=holder, material=material, count=count, guid=guid)


# The family exactly as #2830 measured it live 2026-08-24.
def _measured_holdings():
    return [
        _holding("Bork", "Linen Cloth", 19, 101),
        _holding("Bork", "Silverleaf", 19, 102),
        _holding("Bork", "Bolt of Linen Cloth", 2, 103),
        _holding("Ugga", "Linen Cloth", 13, 201),
        _holding("Ugga", "Silverleaf", 18, 202),
        _holding("Ugga", "Bolt of Linen Cloth", 1, 203),
        _holding("Og", "Linen Cloth", 15, 301),
        _holding("Og", "Silverleaf", 13, 302),
        _holding("Og", "Peacebloom", 7, 303),
        _holding("Grog", "Linen Cloth", 18, 401),
        _holding("Grug", "Linen Cloth", 19, 501),
        _holding("Grug", "Silver Ore", 2, 502),
        _holding("Grug", "Malachite", 4, 503),
    ]


class CrafterForTest(unittest.TestCase):
    def test_every_measured_reagent_resolves_to_its_assigned_crafter(self):
        self.assertEqual(materials.crafter_for("Linen Cloth"), "Og")
        self.assertEqual(materials.crafter_for("Bolt of Linen Cloth"), "Og")
        self.assertEqual(materials.crafter_for("Silverleaf"), "Ugga")
        self.assertEqual(materials.crafter_for("Peacebloom"), "Ugga")
        self.assertEqual(materials.crafter_for("Silver Ore"), "Grug")

    def test_a_material_whose_trade_is_now_unassigned_has_no_crafter(self):
        """Malachite feeds jewelcrafting, which moved to professions.UNASSIGNED
        when Grog's assignment changed to mining + engineering (#2831 update).
        It used to resolve to Grog; it must now honestly resolve to nobody
        rather than keep naming him."""
        self.assertEqual(materials.crafter_for("Malachite"), "")

    def test_an_unlisted_material_has_no_opinion(self):
        self.assertEqual(materials.crafter_for("Hearthstone"), "")


class PlanTest(unittest.TestCase):
    def test_every_stack_in_the_wrong_hands_becomes_a_grant(self):
        plan = materials.plan(_measured_holdings())
        moved = {(g.holder, g.material) for g in plan.grants}
        # Linen Cloth and the Bolts move to Og from everyone but him.
        self.assertIn(("Bork", "Linen Cloth"), moved)
        self.assertIn(("Bork", "Bolt of Linen Cloth"), moved)
        self.assertIn(("Ugga", "Linen Cloth"), moved)
        self.assertIn(("Ugga", "Bolt of Linen Cloth"), moved)
        self.assertIn(("Grog", "Linen Cloth"), moved)
        self.assertIn(("Grug", "Linen Cloth"), moved)
        # Silverleaf and Peacebloom move to Ugga from everyone but her.
        self.assertIn(("Bork", "Silverleaf"), moved)
        self.assertIn(("Og", "Silverleaf"), moved)
        # Malachite feeds jewelcrafting, which is UNASSIGNED (#2831 update) -
        # nobody is a jewelcrafting crafter any more, so it must NOT move and
        # must produce a note instead (see
        # test_an_unassigned_trades_material_is_a_note_not_a_grant below).
        self.assertNotIn(("Grug", "Malachite"), moved)

    def test_an_unassigned_trades_material_is_a_note_not_a_grant(self):
        """Said, not silently skipped, same reason professions._notes exists.
        Malachite still exists in Grug's bags; it just has nowhere to go."""
        plan = materials.plan(_measured_holdings())
        self.assertIn(
            "Malachite feeds jewelcrafting, and nobody is assigned "
            "jewelcrafting - see professions.UNASSIGNED.",
            plan.notes,
        )

    def test_a_stack_already_in_the_crafters_own_hands_is_not_regranted(self):
        plan = materials.plan(_measured_holdings())
        moved = {(g.holder, g.material) for g in plan.grants}
        self.assertNotIn(("Og", "Linen Cloth"), moved)

    def test_silver_ore_stays_with_grug_because_he_is_assigned_blacksmithing(self):
        """Grug is the family's assigned blacksmithing, so his own Silver Ore
        is already in the right hands - it must not be handed to himself."""
        plan = materials.plan(_measured_holdings())
        moved = {(g.holder, g.material) for g in plan.grants}
        self.assertNotIn(("Grug", "Silver Ore"), moved)

    def test_grants_name_the_right_taker_and_carry_the_guid(self):
        plan = materials.plan([_holding("Bork", "Linen Cloth", 19, 101)])
        self.assertEqual(len(plan.grants), 1)
        grant = plan.grants[0]
        self.assertEqual(grant.holder, "Bork")
        self.assertEqual(grant.taker, "Og")
        self.assertEqual(grant.count, 19)
        self.assertEqual(grant.guid, 101)
        self.assertEqual(grant.skill, "tailoring")

    def test_the_give_command_addresses_the_guid_not_the_name(self):
        """DoGive (infra#2597) parses `guid:<item_instance.guid>` - a name or
        a count in this field would be a malformed spec it refuses outright."""
        grant = materials.plan([_holding("Bork", "Linen Cloth", 19, 101)]).grants[0]
        self.assertEqual(grant.command, "guid:101")

    def test_an_unmapped_material_is_left_alone(self):
        plan = materials.plan([_holding("Bork", "Hearthstone", 1, 999)])
        self.assertEqual(plan.grants, ())
        self.assertEqual(plan.notes, ())

    def test_the_plan_is_deterministic(self):
        holdings = _measured_holdings()
        first = materials.plan(holdings)
        second = materials.plan(list(reversed(holdings)))
        self.assertEqual(first.grants, second.grants)

    def test_the_reason_is_never_empty(self):
        """A Grant carries a reason and no `said`: what is spoken is a
        Handover, which is one sentence over however many stacks share an
        intent (infra#3197)."""
        for grant in materials.plan(_measured_holdings()).grants:
            self.assertTrue(grant.reason.strip())
            self.assertFalse(hasattr(grant, "said"))

    def test_an_empty_holdings_list_plans_nothing(self):
        self.assertEqual(materials.plan([]), materials.Plan())


class LinesTest(unittest.TestCase):
    def test_lines_are_spoken_by_the_holder_giving_it_up(self):
        plan = materials.plan([_holding("Bork", "Linen Cloth", 19, 101)])
        said = materials.lines(plan, held={"Og": {"tailoring": 1}})
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("Bork: "))
        self.assertIn("Og", said[0])

    def test_five_stacks_of_cloth_are_four_lines_and_not_six(self):
        """The whole measured family in one pass: four people hand Og their
        linen, and each of them says it once."""
        said = materials.lines(
            materials.plan(_measured_holdings()), held={"Og": {"tailoring": 1}}
        )
        cloth = [line for line in said if "Linen Cloth" in line and "Bolt" not in line]
        self.assertEqual(len(cloth), 4)
        self.assertEqual(len({line.split(":")[0] for line in cloth}), 4)


# Og as `character_skills` actually has him, read live 2026-09-02: herbalism
# and nothing else. ROSTER assigns him tailoring; `overseer_trade` has held
# that learn at 'planned' since 2026-08-26 (mod-overseer#160, #167, #168).
LIVE_SKILLS = {
    "Og": {"herbalism": 30},
    "Ugga": {"herbalism": 117, "alchemy": 1},
    "Grug": {"herbalism": 15},
    "Grog": {"herbalism": 34},
    "Bork": {"herbalism": 7},
}


class HandoverTest(unittest.TestCase):
    """One thing said per intent, however many stacks it takes (infra#3197)."""

    def test_two_stacks_of_one_material_are_one_sentence(self):
        """What Evan watched: 20 and then 19, a minute apart, which reads as
        a loop re-evaluating rather than as a bundle changing hands."""
        grants = materials.plan(
            [
                _holding("Grug", "Linen Cloth", 20, 501),
                _holding("Grug", "Linen Cloth", 19, 502),
            ]
        ).grants
        self.assertEqual(len(grants), 2)
        said = materials.handovers(grants, held=LIVE_SKILLS)
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0].count, 39)
        self.assertEqual(said[0].guids, (501, 502))

    def test_both_stacks_still_move_even_though_one_line_is_said(self):
        """The world's half stays exact: DoGive moves one guid at a time."""
        grants = materials.plan(
            [
                _holding("Grug", "Linen Cloth", 20, 501),
                _holding("Grug", "Linen Cloth", 19, 502),
            ]
        ).grants
        self.assertEqual([g.command for g in grants], ["guid:501", "guid:502"])

    def test_different_materials_are_different_things_to_say(self):
        said = materials.handovers(
            materials.plan(
                [
                    _holding("Grug", "Linen Cloth", 20, 501),
                    _holding("Grug", "Silverleaf", 4, 503),
                ]
            ).grants,
            held=LIVE_SKILLS,
        )
        self.assertEqual(len(said), 2)

    def test_different_holders_are_different_things_to_say(self):
        said = materials.handovers(
            materials.plan(
                [
                    _holding("Grug", "Linen Cloth", 20, 501),
                    _holding("Grog", "Linen Cloth", 18, 401),
                ]
            ).grants,
            held=LIVE_SKILLS,
        )
        self.assertEqual({h.holder for h in said}, {"Grug", "Grog"})

    def test_the_key_is_the_intent_and_survives_a_changed_count(self):
        """The count drifting from 20 to 19 must not defeat the dedupe."""
        first = materials.handovers(
            materials.plan([_holding("Grug", "Linen Cloth", 20, 501)]).grants,
            held=LIVE_SKILLS,
        )[0]
        second = materials.handovers(
            materials.plan([_holding("Grug", "Linen Cloth", 19, 777)]).grants,
            held=LIVE_SKILLS,
        )[0]
        self.assertNotEqual(first.said, second.said)
        self.assertEqual(first.key, second.key)

    def test_the_key_is_holder_material_and_taker(self):
        hand = materials.handovers(
            materials.plan([_holding("Grug", "Linen Cloth", 20, 501)]).grants,
            held=LIVE_SKILLS,
        )[0]
        self.assertEqual(
            hand.key, chat.say_key(speaker="Grug", subject="Linen Cloth", listener="Og")
        )

    def test_no_grants_is_nothing_to_say(self):
        self.assertEqual(materials.handovers((), held=LIVE_SKILLS), ())


class HonestHandoverTest(unittest.TestCase):
    """ "Og need it for tailoring" was a fact about ROSTER, not about Og."""

    def _said(self, held):
        return materials.handovers(
            materials.plan([_holding("Grug", "Linen Cloth", 20, 501)]).grants,
            held=held,
        )[0].said

    def test_a_trade_the_taker_holds_explains_the_handover(self):
        said = self._said({"Og": {"tailoring": 1}})
        self.assertIn("Og need it for tailoring", said)

    def test_a_trade_that_is_only_planned_is_said_as_a_plan(self):
        said = self._said(LIVE_SKILLS)
        self.assertNotIn("need it for tailoring", said)
        self.assertIn("learning tailoring", said)

    def test_a_trade_nobody_is_getting_is_not_mentioned_at_all(self):
        """The stack still moves - ROSTER is what makes it the right bag -
        and the sentence simply stops short of a claim.

        Built by hand, because `plan` cannot produce this case: it only ever
        names a taker ROSTER has assigned the trade to, so every taker it
        picks is at least LEARNING. The branch still has to be right - a
        future REAGENTS entry, or a roster edit, reaches it.
        """
        grant = materials.Grant(
            holder="Grug",
            taker="Bork",
            material="Mystery Powder",
            count=4,
            guid=503,
            skill="cooking",
            reason="constructed",
        )
        said = materials.handovers([grant], held={"Bork": {"herbalism": 7}})[0].said
        self.assertEqual(said, "Grug give Bork 4 Mystery Powder.")
        self.assertNotIn("cooking", said)

    def test_a_taker_the_plan_picks_is_always_at_least_learning_the_trade(self):
        """ROSTER is where a taker comes from, so the quiet branch above is
        unreachable through `plan` - said as an assertion rather than left as
        an assumption."""
        for hand in materials.handovers(
            materials.plan(_measured_holdings()).grants, held={}
        ):
            with self.subTest(taker=hand.taker, material=hand.material):
                self.assertIn(hand.skill, professions.assigned(hand.taker))
                self.assertIn("learning " + hand.skill, hand.said)

    def test_every_spoken_line_passes_the_honesty_gate(self):
        for held in ({"Og": {"tailoring": 1}}, LIVE_SKILLS, {}):
            with self.subTest(held=sorted(held)):
                hand = materials.handovers(
                    materials.plan([_holding("Grug", "Linen Cloth", 20, 501)]).grants,
                    held=held,
                )[0]
                state = chat.skill_state(
                    "Og",
                    "tailoring",
                    held=held,
                    planned={"Og": ("tailoring", "enchanting")},
                )
                self.assertTrue(
                    chat.honest_claim(hand.said, skill="tailoring", state=state)
                )

    def test_an_absent_skills_reading_never_claims_the_trade(self):
        """A failed read must degrade to the quiet line, never to a boast."""
        self.assertNotIn("need it for tailoring", self._said({}))


class StuckTest(unittest.TestCase):
    """A refusal the world keeps repeating (mod-overseer#169).

    The live rows: four give commands from Grug and Grog to Og, seven
    identical `receiver bags are full` errors each, over six hours.
    """

    def _errors(self, n, holder="Grug", taker="Og", detail="receiver bags are full"):
        return [materials.Attempt(holder, taker, "error", detail)] * n

    def test_a_pair_refused_enough_times_is_stuck(self):
        refused = materials.stuck(self._errors(materials.GIVE_UP_AFTER))
        self.assertEqual(refused[("Grug", "Og")], "receiver bags are full")

    def test_one_bad_moment_is_not_a_refusal(self):
        self.assertEqual(materials.stuck(self._errors(1)), {})

    def test_a_pending_give_is_not_a_failure(self):
        """The distinction the whole rule rests on: nobody has answered yet
        is not the same as the world saying no."""
        pending = [materials.Attempt("Grug", "Og", "pending", "")] * 9
        self.assertEqual(materials.stuck(pending), {})

    def test_a_delivered_give_clears_the_count(self):
        attempts = (
            self._errors(2)
            + [materials.Attempt("Grug", "Og", "delivered", "")]
            + self._errors(2)
        )
        self.assertEqual(materials.stuck(attempts), {})

    def test_a_refusal_with_no_detail_still_says_something(self):
        refused = materials.stuck(self._errors(materials.GIVE_UP_AFTER, detail=""))
        self.assertTrue(refused[("Grug", "Og")].strip())

    def test_each_pair_is_counted_on_its_own(self):
        attempts = self._errors(materials.GIVE_UP_AFTER) + self._errors(
            1, holder="Bork"
        )
        refused = materials.stuck(attempts)
        self.assertIn(("Grug", "Og"), refused)
        self.assertNotIn(("Bork", "Og"), refused)

    def test_nothing_tried_is_nothing_stuck(self):
        self.assertEqual(materials.stuck([]), {})

    def test_a_full_receiver_reopens_when_a_slot_is_free_again(self):
        stuck = {("Grug", "Og"): "receiver bags are full"}
        self.assertEqual(materials.retryable_stuck(stuck, {"Og": 2}), {})

    def test_unknown_capacity_keeps_a_stuck_pair_quiet(self):
        stuck = {("Grug", "Og"): "receiver bags are full"}
        self.assertEqual(materials.retryable_stuck(stuck, {}), stuck)


class BlockedTest(unittest.TestCase):
    def _plan(self):
        return materials.plan(
            [
                _holding("Grug", "Linen Cloth", 20, 501),
                _holding("Grug", "Linen Cloth", 19, 502),
            ],
            stuck_pairs={("Grug", "Og"): "receiver bags are full"},
        )

    def test_a_stuck_pair_is_proposed_no_further(self):
        self.assertEqual(self._plan().grants, ())

    def test_it_is_said_once_rather_than_silently_dropped(self):
        blocked = self._plan().blocked
        self.assertEqual(len(blocked), 1)
        self.assertIn("receiver bags are full", blocked[0].said)

    def test_the_refusal_is_the_world_s_own_words(self):
        self.assertEqual(self._plan().blocked[0].refusal, "receiver bags are full")

    def test_a_blocked_line_claims_no_trade(self):
        said = self._plan().blocked[0].said
        self.assertNotIn("tailoring", said)

    def test_an_unaffected_pair_still_moves(self):
        plan = materials.plan(
            [
                _holding("Grug", "Linen Cloth", 20, 501),
                _holding("Bork", "Silverleaf", 19, 102),
            ],
            stuck_pairs={("Grug", "Og"): "receiver bags are full"},
        )
        self.assertEqual([(g.holder, g.taker) for g in plan.grants], [("Bork", "Ugga")])

    def test_the_blocked_key_is_not_the_handover_key(self):
        """Giving up is a different thing to say from handing over, so one
        must not silence the other."""
        blocked = self._plan().blocked[0]
        hand = materials.handovers(
            materials.plan([_holding("Grug", "Linen Cloth", 20, 501)]).grants,
            held=LIVE_SKILLS,
        )[0]
        self.assertNotEqual(blocked.key, hand.key)

    def test_lines_carry_the_blocked_handovers_too(self):
        said = materials.lines(self._plan(), held=LIVE_SKILLS)
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("Grug: "))


class RefusalCountsTest(unittest.TestCase):
    """`stuck` used to be the only reading of the give rows, and it answers one
    question: has this pair been refused enough times to be believed. A view
    showing "1 of 3" is showing a person the thing that is about to happen,
    which is a different question over the same rows."""

    def test_a_pair_nobody_has_refused_is_absent(self):
        counts = materials.refusal_counts([materials.Attempt("Grug", "Og", "pending")])
        self.assertEqual(counts, {})

    def test_one_refusal_is_counted_even_though_nothing_is_stuck_yet(self):
        attempts = [materials.Attempt("Grug", "Og", "error", "bags are full")]
        self.assertEqual(
            materials.refusal_counts(attempts)[("Grug", "Og")], (1, "bags are full")
        )
        self.assertEqual(materials.stuck(attempts), {})

    def test_a_delivery_starts_the_count_again(self):
        attempts = [
            materials.Attempt("Grug", "Og", "error", "bags are full"),
            materials.Attempt("Grug", "Og", "error", "bags are full"),
            materials.Attempt("Grug", "Og", "delivered"),
        ]
        self.assertEqual(materials.refusal_counts(attempts)[("Grug", "Og")][0], 0)

    def test_a_refusal_with_no_reason_still_says_something(self):
        attempts = [materials.Attempt("Grug", "Og", "error", "")]
        self.assertEqual(
            materials.refusal_counts(attempts)[("Grug", "Og")][1],
            materials.NO_REASON_GIVEN,
        )

    def test_stuck_is_this_with_the_threshold_applied(self):
        attempts = [
            materials.Attempt("Grug", "Og", "error", "bags are full")
        ] * materials.GIVE_UP_AFTER
        self.assertEqual(materials.stuck(attempts), {("Grug", "Og"): "bags are full"})


class TheBoardTest(unittest.TestCase):
    """What the Family view draws, which is a READ of the plan the bridge is
    already acting on rather than a second plan with different inputs."""

    def holdings(self):
        return [
            materials.Holding("Grug", "Linen Cloth", 20, 1),
            materials.Holding("Grug", "Linen Cloth", 19, 2),
            materials.Holding("Bork", "Linen Cloth", 19, 3),
        ]

    def test_two_stacks_in_one_pair_of_bags_are_one_row(self):
        """The double line that started #3197: two guids the world moves
        separately are one thing a person reads."""
        rows = materials.board(self.holdings())["rows"]
        grug = [r for r in rows if r.holder == "Grug"]
        self.assertEqual(len(grug), 1)
        self.assertEqual(grug[0].count, 39)

    def test_a_waiting_handover_carries_the_moving_word(self):
        for row in materials.board(self.holdings())["rows"]:
            self.assertEqual(row.word, materials.MOVING)
            self.assertFalse(row.blocked)
            self.assertEqual(row.refusal_line, "")

    def test_a_refused_pair_is_a_different_kind_of_row(self):
        attempts = [
            materials.Attempt("Grug", "Og", "error", "receiver bags are full")
        ] * materials.GIVE_UP_AFTER
        rows = materials.board(self.holdings(), attempts=attempts)["rows"]
        grug = next(r for r in rows if r.holder == "Grug")
        self.assertTrue(grug.blocked)
        self.assertEqual(grug.word, materials.gave_up_word())
        self.assertIn("receiver bags are full", grug.refusal_line)
        self.assertIn(str(materials.GIVE_UP_AFTER), grug.word)

    def test_a_blocked_row_still_says_how_much_is_stuck(self):
        """ "Og bags full" is worth reading. "39 Linen Cloth is stuck in Grug's
        bags because Og bags full" is worth acting on."""
        attempts = [
            materials.Attempt("Grug", "Og", "error", "full")
        ] * materials.GIVE_UP_AFTER
        rows = materials.board(self.holdings(), attempts=attempts)["rows"]
        grug = next(r for r in rows if r.holder == "Grug")
        self.assertEqual(grug.count, 39)
        self.assertIn("39", grug.title)

    def test_a_refused_pair_is_never_also_proposed(self):
        """The family has stopped asking. A row that said both would be the
        loop mod-overseer#169 is about, drawn twice."""
        attempts = [
            materials.Attempt("Grug", "Og", "error", "full")
        ] * materials.GIVE_UP_AFTER
        rows = materials.board(self.holdings(), attempts=attempts)["rows"]
        self.assertEqual(len([r for r in rows if r.holder == "Grug"]), 1)

    def test_the_rows_say_exactly_what_the_family_says(self):
        """Not a paraphrase. A view that reworded the line would put a sentence
        on screen nobody ever spoke."""
        plan = materials.plan(self.holdings())
        spoken = [h.said for h in materials.handovers(plan.grants)]
        self.assertEqual(
            [r.said for r in materials.board(self.holdings())["rows"]], spoken
        )

    def test_nothing_to_move_is_said_rather_than_left_empty(self):
        board = materials.board([])
        self.assertEqual(board["rows"], ())
        self.assertIn("nothing wants to move", board["headline"])

    def test_the_rule_is_built_from_the_threshold(self):
        """The sentence is the whole point of the section: a family that says a
        doomed handover once and stops is telling the truth, and a reader has
        to know the silence afterwards is the rule rather than a lost row."""
        self.assertIn(str(materials.GIVE_UP_AFTER), materials.giving_up_rule())
        self.assertIn("7", materials.giving_up_rule(threshold=7))

    def test_a_title_with_no_count_does_not_claim_zero(self):
        row = materials.Move(
            holder="Grug",
            taker="Og",
            material="Linen Cloth",
            skill="tailoring",
            count=0,
            said="",
            word="",
            blocked=True,
            refusals=3,
            refusal="full",
        )
        self.assertNotIn("0", row.title)

    def test_the_row_key_is_stable_across_two_identical_reads(self):
        """The page reuses a row rather than rebuilding it, and a key that
        moved would rebuild every row on every poll."""
        first = [r.key for r in materials.board(self.holdings())["rows"]]
        second = [r.key for r in materials.board(self.holdings())["rows"]]
        self.assertEqual(first, second)
        self.assertEqual(len(set(first)), len(first))


if __name__ == "__main__":
    unittest.main()

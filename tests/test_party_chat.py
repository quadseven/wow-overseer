"""The three faults, pinned where they were actually wired (infra#3197).

WHY THIS IS A CONTRACT OVER SOURCE TEXT. bridge.py imports `discord` and
`pymysql` at module level and this directory's suites are stdlib-only with no
pip install, so it cannot be imported here - the same wall tests/
test_headless_bridge.py meets, and the same answer: pin the wiring by reading
the source, because a pure rule nothing calls is decoration.

WHAT WAS ON SCREEN, captured from Evan's stream and confirmed against the
live database on 2026-09-02:

    [Party] [Grog]: Grog give Og 20 Linen Cloth. Og need it for tailoring.
    [Party] [Grug]: Grug give Og 19 Linen Cloth. Og need it for tailoring.
    [Party] [Og]:   Og need cloth? Og know tailoring. Og make it, family
                    just bring the stuff.

`overseer_chat` held 58 copies of that last sentence in three minutes. Og has
never had tailoring: `overseer_trade` has held `learn tailoring` at 'planned'
since 2026-08-26 and `character_skills` gives him herbalism (mod-overseer#160,
#167, #168). And the four give commands underneath it all sat at
`status='error'`, `detail="receiver bags are full"` for six hours
(mod-overseer#169), which is why silencing the chatter alone would have been a
worse bug than the noise.
"""
import inspect
import pathlib
import re
import unittest

import chat
import craftpleas
import materials

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = _source()
    start = src.index(signature)
    indent = len(src[:start].split("\n")[-1])
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


class SkillClaimsAreCheckedLiveTest(unittest.TestCase):
    """Never claim a skill you do not have."""

    def test_the_answer_cannot_be_built_without_the_live_skills(self):
        """`held` is keyword-only with NO default, so no call site can
        accidentally go back to boasting from ROSTER alone."""
        held = inspect.signature(craftpleas.answer).parameters["held"]
        self.assertIs(held.default, inspect.Parameter.empty)
        self.assertIs(held.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_the_bridge_reads_character_skills_before_answering(self):
        body = _block("    async def _answer_craft_ask(")
        self.assertIn("_fetch_trade_skills", body)
        self.assertIn("craftpleas.answer(", body)

    def test_the_bridge_never_answers_from_the_roster_alone(self):
        self.assertNotIn("craftpleas.answer(ask)", _source())

    def test_a_reworded_line_is_checked_before_it_is_spoken(self):
        """persona hands the sentence to an LLM between the decision and the
        chat window, and a hedge can come back as a boast."""
        for signature in ("    async def _answer_craft_ask(",
                          "    async def _speak_handovers("):
            with self.subTest(signature=signature):
                self.assertIn("chat.honest_claim", _block(signature))

    def test_the_handover_line_is_built_from_the_live_skills_too(self):
        body = _block("    async def _speak_handovers(")
        self.assertIn("_fetch_trade_skills", body)
        self.assertIn("materials.handovers(", body)

    def test_no_grant_carries_a_spoken_line_any_more(self):
        """`grant.said` was the false sentence; what is spoken is a Handover
        built from what the taker can actually do."""
        self.assertNotIn("grant.said", _source())
        self.assertFalse(any(
            field == "said" for field in materials.Grant.__dataclass_fields__
        ))


class SaidOnceTest(unittest.TestCase):
    """Say a thing once."""

    def test_the_bridge_keeps_one_ledger_of_what_it_has_said(self):
        self.assertIn("self._said: dict = {}", _source())

    def test_every_speaking_path_asks_before_it_speaks(self):
        for signature in ("    async def _speak_craft_asks(",
                          "    async def _stood_down_for_craft(",
                          "    async def _speak_handovers(",
                          "    async def _say_blocked("):
            with self.subTest(signature=signature):
                self.assertIn("chat.should_say", _block(signature))

    def test_every_speaking_path_remembers_afterwards(self):
        """A should_say with no remember_said is a cooldown that never
        starts - the mechanism-that-does-nothing shape this repo keeps
        meeting."""
        for signature in ("    async def _answer_craft_ask(",
                          "    async def _stood_down_for_craft(",
                          "    async def _speak_handovers(",
                          "    async def _say_blocked("):
            with self.subTest(signature=signature):
                self.assertIn("chat.remember_said", _block(signature))

    def test_the_craft_answer_is_keyed_on_the_intent(self):
        self.assertIn("craftpleas.ask_key(ask)", _block("    async def _speak_craft_asks("))

    def test_the_bridge_ignores_its_own_echo(self):
        """Every line the family says comes back through this relay, and an
        answer that mentions cloth reads as an ask about cloth."""
        self.assertIn("_authored_lines", _block("    async def _speak_craft_asks("))


class NeverAddressYourselfTest(unittest.TestCase):
    def test_a_crafter_never_answers_its_own_line(self):
        self.assertIsNone(craftpleas.parse_ask(
            "Og",
            "Og need cloth? Og know tailoring. Og make it, family just bring "
            "the stuff.",
        ))

    def test_the_module_uses_the_shared_rule_rather_than_a_private_copy(self):
        source = pathlib.Path(craftpleas.__file__).read_text(encoding="utf-8")
        self.assertIn("chat.addressed_to_self", source)

    def test_a_handover_never_names_its_own_holder_as_the_taker(self):
        """materials refuses this in the plan; the assertion is on the whole
        measured family rather than on one case."""
        holdings = [
            materials.Holding("Og", "Linen Cloth", 15, 301),
            materials.Holding("Grug", "Linen Cloth", 19, 501),
            materials.Holding("Ugga", "Silverleaf", 18, 202),
        ]
        for hand in materials.handovers(materials.plan(holdings).grants, held={}):
            with self.subTest(holder=hand.holder):
                self.assertFalse(chat.addressed_to_self(hand.holder, hand.taker))


class ReadTheRoomTest(unittest.TestCase):
    """Crafting chatter stands down mid-run.

    Evan, watching a Deadmines pull stop so somebody could hand over cloth:
    "They should say shut up we are in a dungeon just wait."
    """

    def test_the_materials_pass_stands_down_during_a_run(self):
        self.assertIn("self._mid_run(", _block("    async def _move_materials_once("))

    def test_mid_run_asks_the_run_row_and_the_roster_job(self):
        body = _block("    async def _mid_run(")
        self.assertIn("_active_dungeon_run", body)
        self.assertIn("_roster_jobs", body)
        self.assertIn("chat.mid_run", body)

    def test_a_craft_ask_mid_run_is_answered_with_not_now(self):
        body = _block("    async def _stood_down_for_craft(")
        self.assertIn("chat.stand_down", body)
        self.assertIn("_active_dungeon_run", body)

    def test_the_stand_down_is_remembered_like_any_other_line(self):
        """Every path that speaks also writes the thought, so the timeline
        shows why the answer never came rather than a gap."""
        for signature in ("    async def _answer_craft_ask(",
                          "    async def _stood_down_for_craft(",
                          "    async def _speak_handovers(",
                          "    async def _say_blocked("):
            with self.subTest(signature=signature):
                self.assertIn("_insert_thought", _block(signature))

    def test_both_ends_of_the_conversation_count(self):
        """The party chat window is the same window whoever is standing
        where, so the asker being in the run is enough."""
        self.assertIn(
            "for who in (ask.crafter, ask.asker)",
            _block("    async def _stood_down_for_craft("),
        )


class StuckHandoversTest(unittest.TestCase):
    """A failing loop must not be hidden by the dedupe (mod-overseer#169)."""

    def test_the_pass_asks_what_the_world_has_already_refused(self):
        body = _block("    async def _move_materials_once(")
        self.assertIn("materials.stuck(", body)
        self.assertIn("stuck_pairs=", body)

    def test_the_refusals_are_read_from_status_and_detail(self):
        body = _block("def _give_attempts(")
        self.assertIn("status", body)
        self.assertIn("detail", body)
        self.assertIn("kind = 'give'", body)

    def test_the_window_is_wider_than_the_retry_interval(self):
        """Seven refusals over six hours: an hour-wide window never reaches
        materials.GIVE_UP_AFTER, so the family would ask forever."""
        self.assertIn("GIVE_GIVE_UP_HOURS", _source())

    def test_giving_up_is_said_rather_than_done_silently(self):
        self.assertIn("await self._say_blocked(", _source())

    def test_a_stuck_pair_is_distinguishable_from_an_unanswered_one(self):
        pending = [materials.Attempt("Grug", "Og", "pending", "")] * 9
        errors = [
            materials.Attempt("Grug", "Og", "error", "receiver bags are full")
        ] * materials.GIVE_UP_AFTER
        self.assertEqual(materials.stuck(pending), {})
        self.assertIn(("Grug", "Og"), materials.stuck(errors))


if __name__ == "__main__":
    unittest.main()

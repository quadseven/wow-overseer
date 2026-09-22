"""Seven passes, one column, and the door they now all ask at (infra#3703).

WHAT THIS FILE GUARDS, AND WHY IT IS SHAPED THE WAY IT IS. bridge.py imports
`discord` and `pymysql` at module level and this directory's suites run with NO
pip install (see check.python-units.yml's own scope note), so a test here cannot
import it. Every other bridge suite answers that by reading bridge.py as source
text, and most of this file does the same.

ONE PART DOES NOT, AND DELIBERATELY. `_is_economy_aim` is the guard that decides
whether an errand can ever be handed back, and getting it wrong is how a vault
aim spent its life in a column nothing could clear. A test that reads the words
`_retaskable_from` out of its body proves it mentions the right function; it
cannot tell `return bool(...)` from `return not bool(...)`. So
`TheReleaseGuardAnswersRealAims` COMPILES those two functions out of bridge.py
and runs them, against the real `travel` and `craft_supply` modules and the real
`ECONOMY_ERRANDS` tuple. It is the one place in this package that does that, and
the reason is that it is the one guard whose failure is silent in both
directions: too narrow and an errand latches forever, too wide and an economy
pass blanks a profession errand (mod-overseer#438).
"""

import ast
import pathlib
import re
import unittest

import craft_supply
import learnaim
import townslot
import travel

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PACKAGE / "bridge.py"
DOCKERFILE = PACKAGE / "Dockerfile"


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = _source()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


def _statements(signature: str) -> str:
    """The same block with its docstring and its `#` prose removed.

    This codebase argues at length in comments on purpose, so a test that
    COUNTS a call has to read the statements: the comment above a call names
    the function it is explaining.
    """
    body = _block(signature)
    marker = '"""'
    if body.count(marker) >= 2:
        body = body.split(marker, 2)[2]
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


def _guard_namespace():
    """`ECONOMY_ERRANDS`, `_retaskable_from` and `_is_economy_aim`, executed.

    Pulled out of bridge.py's own AST rather than copied here, so what runs is
    the shipping source and not a second version of it that could agree with
    the test while disagreeing with the realm. The two modules they reach for
    are imported for real: `travel.is_ground_aim` is what decides that an `at:`
    aim is a ground aim, and `craft_supply.VENDOR_ROLE` is the keyword the
    numeric refinement is allowed to be written over.
    """
    tree = ast.parse(_source())
    wanted = {"_retaskable_from", "_is_economy_aim"}
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            out.append(node)
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "ECONOMY_ERRANDS"
        ):
            out.append(node)
    if len(out) != 3:
        raise AssertionError(
            "expected ECONOMY_ERRANDS, _retaskable_from and _is_economy_aim at "
            "bridge.py's top level, found %d" % len(out)
        )
    namespace = {"travel": travel, "craft_supply": craft_supply}
    # S102 is `exec`, and the answer to it is the argument in this file's
    # docstring rather than a wider rule. What is executed is not a string this
    # test built: it is three nodes lifted out of bridge.py's own AST, by name,
    # in a test process, with a namespace holding two modules this suite already
    # imports. The alternative is a substring assertion that cannot tell
    # `return bool(...)` from `return not bool(...)` on the one guard whose
    # failure is silent in both directions. If bridge.py ever becomes importable
    # here (it needs discord and pymysql, which CI does not install), this goes
    # away and the tests call the functions directly.
    exec(
        compile(ast.Module(body=out, type_ignores=[]), str(BRIDGE), "exec"),  # noqa: S102 - bridge.py's own AST, by name, in a test
        namespace,
    )
    return namespace


class TheReleaseGuardAnswersRealAims(unittest.TestCase):
    """THE HALF OF infra#3703 THAT MAKES A STUCK ERRAND RELEASABLE AT ALL.

    Before this the WRITE called a ground aim an economy errand
    (`_retaskable_from`, since infra#3702) and the RELEASE called it a
    profession errand (membership of `ECONOMY_ERRANDS`, keywords only). So the
    guild bank pass and the forge pass could write one down the economy branch
    and nothing anywhere could hand it back - measured live on wow-dev with
    `at:1:-7203.1,-3821.1,8.6` sitting in the leader's column while the auction
    pass logged that it was starved behind it.
    """

    @classmethod
    def setUpClass(cls):
        cls.ns = _guard_namespace()

    def economy(self, aim):
        return self.ns["_is_economy_aim"](aim)

    def test_every_keyword_the_economy_writes_can_be_handed_back(self):
        for aim in self.ns["ECONOMY_ERRANDS"]:
            with self.subTest(aim=aim):
                self.assertTrue(self.economy(aim))

    def test_the_vault_aim_that_was_measured_holding_the_column(self):
        """The exact string out of the 2026-09-14 log line. Before this change
        `_release_trade_errand` answered "not an economy errand" to it."""
        self.assertTrue(travel.is_ground_aim("at:1:-7203.1,-3821.1,8.6"))
        self.assertTrue(self.economy("at:1:-7203.1,-3821.1,8.6"))

    def test_a_forge_ground_aim_too(self):
        self.assertTrue(self.economy("at:1:-8920.89,-2209.71,9.37107"))

    def test_a_bare_creature_entry_is_an_economy_errand(self):
        """craft_supply's refined vendor aim (infra#3692)."""
        self.assertTrue(self.economy("5594"))

    def test_a_trainer_errand_is_refused(self):
        """mod-overseer#438. A profession errand is a standing plan that
        outlives a town run and carries `learn_skill` with it."""
        for aim in ("trainer", "class trainer", "profession trainer"):
            with self.subTest(aim=aim):
                self.assertFalse(self.economy(aim))

    def test_the_keyword_learnaim_actually_writes_is_refused(self):
        """Asked of the constant rather than of a string this file chose, so a
        rename on that side cannot leave this test passing about nothing."""
        self.assertFalse(self.economy(learnaim.TRAINER_ROLE))

    def test_an_empty_column_is_not_an_errand(self):
        """Releasing "" would be a blanking UPDATE that matches every idle
        character on the roster."""
        self.assertFalse(self.economy(""))
        self.assertFalse(self.economy(None))

    def test_an_unknown_keyword_is_refused(self):
        for aim in ("innkeeper", "flight master", "stable master", "mailbox"):
            with self.subTest(aim=aim):
                self.assertFalse(self.economy(aim))

    def test_it_is_exactly_the_write_s_own_guard(self):
        """The whole point: one predicate, so the two can no longer disagree
        about any aim at all."""
        retaskable = self.ns["_retaskable_from"]
        for aim in (
            "vendor",
            "banker",
            "repair",
            "guild banker",
            "auctioneer",
            "at:1:-7203.1,-3821.1,8.6",
            "5594",
            "profession trainer",
            "trainer",
            "",
            "innkeeper",
        ):
            with self.subTest(aim=aim):
                self.assertEqual(bool(retaskable(aim)), self.economy(aim))

    def test_a_ground_aim_still_may_not_overwrite_another_errand(self):
        """Releasable is not the same as retaskable-over, and widening the one
        must not widen the other: a vault aim may be handed BACK, and it still
        only ever goes into an idle column or over its own self."""
        self.assertEqual(("", "at:1:1,2,3"), self.ns["_retaskable_from"]("at:1:1,2,3"))

    def test_the_numeric_aim_may_still_refine_a_vendor_errand(self):
        self.assertIn(craft_supply.VENDOR_ROLE, self.ns["_retaskable_from"]("5594"))


class EveryTownPassAsksAtTheSameDoor(unittest.TestCase):
    """THE POINT OF THE CHANGE. Seven passes wrote `travel_npc` directly, each
    read its own refusal and each logged its own version of "already on
    somebody else's errand" - so nothing decided between them and the winner
    was whichever pass happened to run first."""

    PASSES = {
        "    async def _aim_at_reagent_vendor(": '"craft_supply", trip.traveller, trip.target',
        "    async def _settle_auction_errand(": None,
        "    async def _auction_once(": '"auction", leader, auction.AUCTIONEER_ROLE',
        "    async def _vendor_once(": '"economy", leader, "vendor"',
        "    async def _settle_bank_errand(": '"bank", leader, "banker"',
        "    async def _guild_bank_once(": '"guild bank", leader, vault.aim',
        "    async def _forge_once(": '"forge", leader, forge.aim',
        "    async def _settle_town_errand(": '"towntrip", leader, "repair"',
    }

    def test_every_town_aim_goes_through_the_slot(self):
        for signature, call in self.PASSES.items():
            if call is None:
                continue
            with self.subTest(pass_=signature.strip()):
                self.assertIn("_claim_town_slot(", _statements(signature))

    def test_each_pass_names_itself_and_aims_the_leader(self):
        for signature, call in self.PASSES.items():
            if call is None:
                continue
            with self.subTest(pass_=signature.strip()):
                body = _statements(signature)
                self.assertIn(call, body)

    def test_no_town_pass_writes_the_column_itself_any_more(self):
        for signature in self.PASSES:
            with self.subTest(pass_=signature.strip()):
                body = _statements(signature)
                self.assertNotIn("_write_trade_errand", body)
                self.assertNotIn("UPDATE overseer_roster", body)

    def test_exactly_three_callers_write_the_column(self):
        """The door, the profession errand and auction hold.

        The profession errand is not a town errand and must not be leased or
        arbitrated (see the next class). The auction hold reasserts the same
        guarded keyword while listing rows are still pending.
        """
        calls = re.findall(r"to_thread\(\s*_write_trade_errand", _source())
        self.assertEqual(3, len(calls))
        self.assertIn(
            "to_thread(_write_trade_errand",
            _statements("    async def _send_trade_errand("),
        )
        self.assertIn(
            "_write_trade_errand", _statements("    async def _claim_town_slot(")
        )

    def test_the_pass_names_are_the_words_they_already_log_with(self):
        """A log a person greps has to join up: `guild bank: ...` and `town
        slot: guild bank waits ...` are the same pass or the line is useless."""
        for name, signature in (
            ("economy", "    async def _vendor_once("),
            ("bank", "    async def _settle_bank_errand("),
            ("guild bank", "    async def _guild_bank_once("),
            ("auction", "    async def _auction_once("),
            ("forge", "    async def _forge_once("),
            ("towntrip", "    async def _settle_town_errand("),
            ("craft_supply", "    async def _aim_at_reagent_vendor("),
            ("mail", "    async def _mail_once("),
        ):
            with self.subTest(name=name):
                body = _statements(signature)
                claim = body[body.index("_claim_town_slot(") :]
                self.assertIn('"%s"' % name, claim[: len(name) + 40])
                self.assertIn('"%s: ' % name, body)


class TheProfessionErrandIsNotATownErrand(unittest.TestCase):
    """A trainer errand is a standing plan that outlives a town run: it carries
    `learn_skill`/`unlearn_skill` with it, it goes down `_write_trade_errand`'s
    OTHER branch, and nothing may lease it or hand it back. Putting it through
    the slot would have made the guard this whole file is about meaningless."""

    def test_it_still_writes_through_the_unconditional_branch(self):
        body = _statements("    async def _send_trade_errand(")
        self.assertIn("_write_trade_errand", body)
        self.assertNotIn("_claim_town_slot", body)

    def test_the_slot_never_sees_a_learn_errand(self):
        door = _statements("    async def _claim_town_slot(")
        for column in ("learn_skill", "unlearn_skill", "unlearn_max"):
            with self.subTest(column=column):
                self.assertNotIn(column, door)


class TheDoorDoesThreeThingsInOneOrder(unittest.TestCase):
    def setUp(self):
        self.body = _block("    async def _claim_town_slot(")
        self.code = _statements("    async def _claim_town_slot(")

    def test_it_reads_the_leader_itself_rather_than_trusting_the_caller(self):
        """Seven passes remembering "only the leader travels" is seven places
        for it to be forgotten; one place that reads `_head_now` and refuses
        anybody else is the rule enforced."""
        self.assertIn("leader = await asyncio.to_thread(_head_now)", self.code)
        self.assertLess(
            self.code.index("_head_now"), self.code.index("self._town_slot.want(")
        )

    def test_it_reads_the_column_before_it_decides(self):
        self.assertIn("_current_travel_npc, leader", self.code)
        self.assertLess(
            self.code.index("_current_travel_npc"),
            self.code.index("self._town_slot.want("),
        )

    def test_it_hands_the_write_s_own_guard_to_the_decision(self):
        """The slot must never grant a write the UPDATE would refuse, so it is
        asked against the same tuple the WHERE clause is built from."""
        self.assertIn("retaskable=_retaskable_from(aim)", self.code)

    def test_a_refusal_writes_nothing_and_says_so(self):
        refusal = self.code[self.code.index("if not decision.granted:") :]
        refusal = refusal[: refusal.index("if decision.release")]
        self.assertIn("townslot.report(decision)", refusal)
        self.assertIn("return False", refusal)
        self.assertNotIn("_write_trade_errand", refusal)

    def test_the_release_happens_before_the_write(self):
        """`_write_trade_errand`'s economy guard retasks only an IDLE traveller
        and is not being weakened, so a preemption is two statements: hand the
        stuck errand back, then take the empty column the ordinary way."""
        self.assertLess(
            self.code.index("_release_trade_errand"),
            self.code.index("_write_trade_errand"),
        )

    def test_the_release_names_the_errand_that_was_read(self):
        """Not the aim being asked for. Releasing anything else would be the
        cross-pass theft the guard exists to prevent.

        ASSERTED ON THE CALL AND NOT ON THE BLOCK, because the log line just
        below it names the same two fields while explaining what was handed
        back - so a block-wide search is answered by the explanation even after
        the call itself has been changed to release the wrong thing. A first
        draft of this test passed a mutation that did exactly that."""
        self.assertIn(
            "_release_trade_errand, decision.release.character,\n"
            "                decision.release.aim,",
            self.code,
        )

    def test_a_hold_returns_true_without_writing_anything(self):
        """Re-writing a word the column already carries makes mod-overseer's
        aim book erase its own state and read a standing errand as a brand new
        one, releasing and re-taking the counter hold (infra#3708)."""
        hold = self.code[self.code.index("townslot.SLOT_HOLD") :]
        hold = hold[: hold.index("taken = await")]
        self.assertIn("return True", hold)
        self.assertNotIn("_write_trade_errand", hold)

    def test_the_ledger_records_the_outcome_and_not_the_intention(self):
        """A write can lose a race the decision could not see. A ledger that
        recorded the intention would hand this pass a lease it is not using."""
        self.assertLess(
            self.code.index("taken = await"),
            self.code.index("self._town_slot.settle(decision, taken"),
        )

    def test_a_lost_race_returns_false_rather_than_claiming_the_aim(self):
        tail = self.code[self.code.index("settle(decision, taken") :]
        self.assertIn("if not taken:", tail)
        self.assertIn("return False", tail)

    def test_it_never_writes_the_column_itself(self):
        self.assertNotIn("UPDATE overseer_roster", self.code)
        self.assertNotIn("travel_npc =", self.code)


class TheIdleDoorClearsWithoutAReplacement(unittest.TestCase):
    def setUp(self):
        self.code = _statements("    async def _idle_town_slot(")

    def test_it_asks_the_same_ledger_for_an_idle_verdict(self):
        self.assertIn("self._town_slot.want_idle(", self.code)

    def test_it_compares_and_swaps_the_exact_stale_aim(self):
        self.assertIn(
            "_release_trade_errand, decision.release.character,\n"
            "            decision.release.aim,",
            self.code,
        )

    def test_it_never_writes_a_successor(self):
        self.assertNotIn("_write_trade_errand", self.code)


class TheSlotIsHeldForTheLifeOfTheProcess(unittest.TestCase):
    def test_urgent_maintenance_can_preempt_an_orphaned_economy_aim(self):
        """Zero-room pressure cannot wait for the world's 20-minute fuse."""
        slot = townslot.Slot(releasable=travel.is_ground_aim)
        decision = slot.want(
            claimant="economy",
            character="Grug",
            leader="Grug",
            aim="vendor",
            column="at:0:1,2,3",
            retaskable=("", "vendor"),
            now=100.0,
            urgent=True,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, decision.verdict)
        self.assertEqual("at:0:1,2,3", decision.release.aim)

    def test_normal_maintenance_keeps_the_orphan_lease(self):
        """Ordinary town work still leaves an unknown economy aim alone."""
        slot = townslot.Slot(releasable=travel.is_ground_aim)
        decision = slot.want(
            claimant="economy",
            character="Grug",
            leader="Grug",
            aim="vendor",
            column="at:0:1,2,3",
            retaskable=("", "vendor"),
            now=100.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, decision.verdict)

    def test_the_ledger_is_built_once_on_the_client(self):
        init = _block("    def __init__(self, allowed_ids: frozenset[str]):")
        self.assertIn("self._town_slot = townslot.Slot(", init)

    def test_it_is_wired_to_the_release_guard(self):
        """Without the predicate the slot is fail-closed and preempts nothing,
        which would be this change shipped inert."""
        init = _block("    def __init__(self, allowed_ids: frozenset[str]):")
        self.assertIn("releasable=_is_economy_aim", init)

    def test_the_lease_is_an_env_knob_like_every_other_cadence(self):
        source = _source()
        self.assertIn(
            'os.environ.get("TOWN_SLOT_LEASE_SECONDS", townslot.LEASE_SECONDS)', source
        )
        init = _block("    def __init__(self, allowed_ids: frozenset[str]):")
        self.assertIn("lease=TOWN_SLOT_LEASE_SECONDS", init)

    def test_the_module_is_imported_and_shipped(self):
        self.assertIn("\nimport townslot\n", _source())
        self.assertIn("townslot.py", DOCKERFILE.read_text(encoding="utf-8"))

    def test_the_default_lease_is_the_modules_own(self):
        """One number, argued for in one place. A second default here would be
        a second answer to the same question."""
        self.assertEqual(300.0, townslot.LEASE_SECONDS)

    def test_vendor_pass_marks_pressure_as_urgent(self):
        body = _statements("    async def _vendor_once(")
        self.assertIn(
            'self._claim_town_slot(\n                "economy", leader, "vendor", urgent=True,',
            body,
        )


class TheStarvationLineIsGreppable(unittest.TestCase):
    """The owner has to be able to SEE a starved pass finally run, and the old
    lines could not say it: three passes said only "already on somebody else's
    errand", which cannot tell a pass starved by a live errand from one starved
    by an errand left behind."""

    def test_every_slot_sentence_carries_one_prefix(self):
        for line in re.findall(r'"town slot: [^"]*"', _source()):
            with self.subTest(line=line):
                self.assertTrue(line.startswith('"town slot: '))

    def test_the_report_helper_is_what_the_passes_log(self):
        self.assertIn(
            'return "town slot: %s" % decision.reason',
            (PACKAGE / "townslot.py").read_text(encoding="utf-8"),
        )

    def test_the_preemption_sentence_cites_the_issue(self):
        """So the line that proves this shipped can be found by issue number."""
        module = (PACKAGE / "townslot.py").read_text(encoding="utf-8")
        self.assertIn('issue = "infra#3728" if clearing else "infra#3703"', module)

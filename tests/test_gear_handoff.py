"""The piece a sibling should be wearing actually reaches them (infra#3464).

THE MEASUREMENT THAT MAKES THIS THE BIGGEST HALF OF THE GREENS PROBLEM. When
the family-fit gate shipped (infra#3450) it split the 101 carried weapons and
armour into 34 the HOLDER should be wearing, 35 a SIBLING should be handed, 3
rings this codebase has no slot map for, and 25 nobody will ever wear. The pass
acted on the 25. The 35 - the larger pile, and the only one that also makes the
family stronger rather than richer - were computed every cycle and dropped on
the floor, because `bag_pressure.gear_candidates` keeps only VENDOR verdicts
and a sale was the only thing the caller could write.

`gear.plan` has been the answer to "who should have this" since
mod-overseer#14 and has never had a production call site: bridge.py did not
import gear at all, and the kind='give' rows on the realm come from
materials.py and bag_upgrade.py. Two finished halves and no wire between them
is the same shape as the repair, buy and conjure verbs this pass also fixes.

WHAT THIS SUITE IS FOR, and it is not for re-testing gear.py. tests/test_gear.py
already pins who should get what, the Severing Axe role guard and the
class-eligibility bitmask. What is pinned here is that the answer REACHES the
world, that it cannot contradict the sell half, and that every refusal the sell
half honours is honoured here too.
"""
import pathlib
import re
import unittest

import bag_pressure
import disposition

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

WARRIOR, PALADIN, ROGUE, PRIEST, MAGE = 1, 2, 4, 5, 8
ANY_CLASS = -1
MAGE_ONLY = 1 << (MAGE - 1)
THE_FIVE = ["Bork", "Grog", "Grug", "Og", "Ugga"]


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


def worn(name, class_id, level, **slots):
    """Equipped rows for one character, as _FAMILY_EQUIPPED_SQL returns them."""
    if not slots:
        return [dict(name=name, class_id=class_id, level=level,
                     inventory_type=None, item_level=None)]
    return [dict(name=name, class_id=class_id, level=level,
                 inventory_type=int(inv.lstrip("i")), item_level=int(ilvl))
            for inv, ilvl in slots.items()]


def carried(**kw):
    """One carried gear row, as _SURPLUS_GEAR_SQL returns it.

    Defaults describe Ugga's Mystic's Woolies: green cloth legs a priest is
    carrying, that only a mage may wear. It is the shape of the drop this
    whole module exists for - group loot lands on whoever won the roll, never
    on whoever can use it.
    """
    base = dict(holder="Ugga", level=27, item_guid=7002, entry=9002, count=1,
                instance_flags=0, name="Mystic's Woolies", quality=2,
                sell_price=402, required_level=14, bonding=2, item_class=4,
                item_level=19, allowable_class=MAGE_ONLY, inventory_type=7)
    base.update(kw)
    return base


# Ugga wearing better legs than the robe she carries, Og wearing worse.
THE_HAND_OFF = worn("Ugga", PRIEST, 27, i7=20) + worn("Og", MAGE, 28, i7=12)


def gifts(gear_rows, equipped_rows, keep_names=()):
    """The grants only. `family_gifts` returns a Plan since the delivery gate
    landed; what this file pins is WHO should get WHAT, and
    tests/test_gear_delivery.py pins whether it can land and by which verb.
    Neither position nor capacity is passed, which means "nobody asked" and
    keeps every case below about the decision it was written for."""
    return bag_pressure.family_gifts(gear_rows, equipped_rows, THE_FIVE,
                                     keep_names=keep_names).grants


class TheAnswerReachesSomebody(unittest.TestCase):
    def test_a_piece_a_sibling_would_wear_becomes_a_hand_off(self):
        got = gifts([carried()], THE_HAND_OFF)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0].holder, got[0].taker), ("Ugga", "Og"))

    def test_the_command_names_the_exact_stack_that_dropped(self):
        """`entry:` lets the worldserver pick any matching stack off the
        holder's bags, which for a unique drop is a silent chance to hand
        over the wrong copy. ParseGiveSpec accepts both; only one is right."""
        got = gifts([carried()], THE_HAND_OFF)
        self.assertEqual(got[0].command, "guid:7002")

    def test_the_same_bags_twice_propose_the_same_plan(self):
        """The bridge's retry window keys on (holder, taker, command), so a
        plan that shuffled would never match itself and would re-queue every
        cycle."""
        rows = [carried(), carried(item_guid=7003, entry=9003)]
        self.assertEqual([g.command for g in gifts(rows, THE_HAND_OFF)],
                         [g.command for g in gifts(rows, THE_HAND_OFF)])


class ItCannotDisagreeWithTheSellHalf(unittest.TestCase):
    """One gate, two questions. A piece can be handed on or sold, never both,
    and that has to be structural rather than hoped for: both paths ask
    `gear.would_wear` of the holder and `gear.is_upgrade_for` of every
    sibling, so `claimant` and `plan` differ about WHO and never about
    WHETHER."""

    def _both(self, rows, equipped):
        fits = bag_pressure.family_fits(rows, equipped, THE_FIVE)
        sold = {c.item_guid for c in bag_pressure.gear_candidates(
            rows, disposition.Family(vendor_reachable=True),
            available=disposition.EXECUTABLE_TODAY, fits=fits)}
        handed = {int(g.guid) for g in gifts(rows, equipped)}
        return fits, sold, handed

    def test_a_sibling_upgrade_is_handed_on_and_never_sold(self):
        fits, sold, handed = self._both([carried()], THE_HAND_OFF)
        self.assertEqual(fits[7002], disposition.FIT_SIBLING)
        self.assertEqual(handed, {7002})
        self.assertEqual(sold, set())

    def test_a_piece_nobody_wants_is_sold_and_never_handed_on(self):
        nobody = carried(item_guid=7020, name="Ridge Cloak",
                         allowable_class=ANY_CLASS, inventory_type=16,
                         required_level=25, item_level=10)
        equipped = (worn("Ugga", PRIEST, 27, i16=30)
                    + worn("Og", MAGE, 28, i16=30))
        fits, sold, handed = self._both([nobody], equipped)
        self.assertEqual(fits[7020], disposition.FIT_NOBODY)
        self.assertEqual(sold, {7020})
        self.assertEqual(handed, set())

    def test_the_holders_own_upgrade_is_neither(self):
        mine = carried(holder="Og", item_guid=7021, allowable_class=MAGE_ONLY,
                       item_level=19)
        equipped = worn("Og", MAGE, 28, i7=12) + worn("Ugga", PRIEST, 27, i7=30)
        fits, sold, handed = self._both([mine], equipped)
        self.assertEqual(fits[7021], disposition.FIT_HOLDER)
        self.assertEqual(sold, set())
        self.assertEqual(handed, set())

    def test_a_ring_nothing_can_judge_is_neither(self):
        """InventoryType 11 has no entry in the slot map, deliberately, and
        "no slot for it" must never read as "nobody wants it"."""
        ring = carried(item_guid=7022, inventory_type=11,
                       allowable_class=ANY_CLASS)
        fits, sold, handed = self._both([ring], THE_HAND_OFF)
        self.assertEqual(fits[7022], disposition.FIT_UNJUDGEABLE)
        self.assertEqual(sold, set())
        self.assertEqual(handed, set())


class EveryRefusalTheSellHalfHonoursIsHonouredHere(unittest.TestCase):
    def test_a_soulbound_piece_is_never_offered_to_a_sibling(self):
        """It cannot legally reach one, so wanting it is beside the point.
        DoTrade refuses it again on its own side; this refuses it first, so
        the row is never written."""
        bound = carried(item_guid=7023, instance_flags=1)
        self.assertEqual(gifts([bound], THE_HAND_OFF), ())

    def test_the_owners_never_dispose_mark_is_honoured(self):
        """A hand-off is not a disposal, and the mark still wins. An owner
        should not have to know which of three passes would have moved it."""
        self.assertEqual(len(gifts([carried()], THE_HAND_OFF)), 1)
        self.assertEqual(
            gifts([carried()], THE_HAND_OFF,
                  keep_names=("mystic's woolies",)), ())

    def test_no_equipped_rows_at_all_hands_nothing_over(self):
        """The same fail-closed answer the sell half gives: a world image
        this cannot read is not a licence to move anybody's gear."""
        self.assertEqual(gifts([carried()], []), ())

    def test_a_row_missing_a_gear_fact_is_dropped_not_guessed_at(self):
        broken = carried(item_guid=7024)
        del broken["item_level"]
        self.assertEqual(gifts([broken], THE_HAND_OFF), ())

    def test_nothing_that_is_not_a_weapon_or_armour_is_ever_seen(self):
        """Quest items, reagents and consumables are invisible by
        construction, not by a special case: _SURPLUS_GEAR_SQL selects
        classes 2 and 4, and gear.would_wear refuses anything else."""
        lockbox = carried(item_guid=7025, item_class=12, name="Bronze Lockbox")
        self.assertEqual(gifts([lockbox], THE_HAND_OFF), ())


class TheRowIsTheRowTheExecutorReads(unittest.TestCase):
    """bridge.py imports discord and cannot be imported here, so this reads it
    as text the way tests/test_towntrip_pass.py does."""

    def test_the_pass_asks_the_one_gear_opinion_for_the_hand_offs(self):
        body = _block("    async def _hand_gear(self")
        self.assertIn("bag_pressure.family_gifts(", body)

    def test_the_pass_honours_the_owners_mark(self):
        body = _block("    async def _hand_gear(self")
        self.assertIn("OWNER_KEEPS", body)

    def test_a_repeat_inside_the_retry_window_is_not_queued_again(self):
        body = _block("    async def _hand_gear(self")
        self.assertIn("_recent_trade_keys", body)

    def test_the_hand_off_is_reached_even_when_nothing_is_for_sale(self):
        """A family with nothing to sell can still be carrying somebody
        else's upgrade, so this must sit above the `no candidates` return."""
        body = _block("    async def _vendor_once(self")
        self.assertLess(body.index("self._hand_gear("),
                        body.index("no safe carried vendor goods"))

    def test_the_row_carries_its_verb_and_its_receiver(self):
        """The kind is `grant.verb` and no longer a literal: which verb can
        land is a fact about where the two of them are standing, and
        gear.deliverable has already looked."""
        body = _block("def _insert_gear_handoff(grant)")
        self.assertIn("grant.verb", body)
        self.assertIn("grant.taker", body)
        self.assertIn("grant.command", body)

    def test_the_writer_degrades_on_a_world_without_the_migration(self):
        """1146 missing table, 1265 a `kind` ENUM with no 'trade' value."""
        body = _block("def _insert_gear_handoff(grant)")
        self.assertIn("1146", body)
        self.assertIn("1265", body)

    def test_the_retry_window_reads_this_pass_and_not_the_others(self):
        """The materials and bag passes write kind='give' with the same
        `guid:N` shape. One window over both would let either silence the
        other's retry - so it keys on `source`, which names the pass, rather
        than on `kind`, which since the delivery gate no longer does."""
        body = _block("def _recent_trade_keys(minutes: int)")
        self.assertIn("source = 'gear'", body)

    def test_nothing_is_destroyed_and_no_gm_command_is_used(self):
        body = _block("    async def _hand_gear(self")
        for forbidden in ("DELETE", ".delete", "'gm'", "additem"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)


class TheSaleIsOnlyOfferedWhereItCanWork(unittest.TestCase):
    """A rule that never runs at a vendor and a rule that refuses to sell
    leave exactly the same greens in the bags (infra#3464).

    MEASURED ON THE LIVE REALM, three hours on 2026-09-09: 1,950 sell rows
    answered, 1,940 of them errors - 1,860 `vendor not in range`, 48 `seller
    is dead`, 42 `seller is in flight` - against 10 sales. Roughly 650
    attempts an hour, issued from wherever the party happened to be standing.
    """

    def test_the_pass_asks_where_the_leader_is_before_queueing(self):
        body = _block("    async def _vendor_once(self")
        self.assertIn("_fetch_town", body)
        self.assertIn("town.vendor", body)

    def test_the_gate_sits_between_the_candidates_and_the_insert(self):
        """Above it the pass may plan; below it, it may write. A gate after
        the insert would be decoration."""
        body = _block("    async def _vendor_once(self")
        self.assertLess(body.index("town.vendor"), body.index("_insert_sell"))

    def test_the_gate_reads_the_vendor_and_not_the_stock(self):
        """A merchant with no npc_vendor rows still buys, so gating on stock
        would refuse exactly the vendors that would have taken the greens."""
        body = _block("    async def _vendor_once(self")
        self.assertIn("if not town.vendor:", body)
        # Comments may argue about `stocks`; no branch may read it.
        code = [line for line in body.splitlines()
                if not line.strip().startswith("#")]
        self.assertNotIn("town.stocks", " ".join(code))

    def test_the_aim_is_written_before_the_gate_is_read(self):
        """Nobody arrives at a vendor they were never sent to. The aim is the
        one thing that must happen on a cycle that queues nothing.

        THE GATE IS NAMED BY ITS ARGUMENT NOW, because `_fetch_town` has two
        callers in this pass since infra#3708. One reads where the LEADER is
        standing, to decide whether the errand it is already carrying has
        landed, and that one deliberately runs before anything else. The other
        is this gate, per selling HOLDER, and it is the one the aim has to
        precede. A bare `_fetch_town` index now finds the wrong one and would
        have failed this test for a change that kept its invariant exactly.
        """
        body = _block("    async def _vendor_once(self")
        self.assertLess(body.index("_write_trade_errand"),
                        body.index("_fetch_town, holder"))

    def test_an_aim_nobody_took_is_reported_rather_than_assumed(self):
        """The economy guard only retasks an IDLE traveller, so a vendor aim
        written while another pass owns `travel_npc` matches no row and
        changes nothing. That was silent, and it is half of why nobody was
        ever standing at a vendor."""
        body = _block("def _write_trade_errand(errand)")
        self.assertIn("cur.rowcount", body)
        self.assertIn("-> bool", body)
        pass_body = _block("    async def _vendor_once(self")
        self.assertIn("aimed", pass_body)

    def test_the_hand_off_is_not_behind_the_vendor_gate(self):
        """A trade happens where the two of them already are. Making it wait
        for a vendor would be inventing a dependency the executor does not
        have."""
        body = _block("    async def _vendor_once(self")
        self.assertLess(body.index("self._hand_gear("),
                        body.index("_fetch_town, holder"))


class TheSupplyPlannerStaysReadable(unittest.TestCase):
    """Grug Elder flagged `_supply` at cyclomatic 20 against a cap of 15, as a
    NEW function landing over it. The three routes it chooses between are now
    three functions, which is also how they are argued about."""

    def test_each_route_is_its_own_function(self):
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "towntrip.py").read_text(encoding="utf-8")
        for name in ("def _hand_on(", "def _conjure(", "def _conjure_target(",
                     "def _buy(", "def _supply("):
            with self.subTest(name=name):
                self.assertIn(name, source)


class TheOneOpinionIsStillTheOnlyOpinion(unittest.TestCase):
    def test_bag_pressure_is_the_only_thing_that_imports_gear(self):
        """gear.py is deliberately dependency-free and the adapter between
        world rows and its judgement is bag_pressure. A second importer would
        be a second place where a row becomes a Holding."""
        package = pathlib.Path(__file__).resolve().parents[1]
        importers = sorted(
            path.name for path in package.glob("*.py")
            if re.search(r"^import gear$", path.read_text(encoding="utf-8"),
                         re.MULTILINE)
        )
        self.assertEqual(importers, ["bag_pressure.py"])

    @staticmethod
    def _function(name):
        """One top-level function's source, bounded by the NEXT one.

        THE BOUND IS THE POINT. This used to slice to end of file, which was
        the same thing only while `family_gifts` happened to be the last
        function in the module - so adding any function after it silently
        re-aimed this assertion at code it was never written about. That is
        the reader being wrong rather than the module, the same way
        test_ship_manifest's own COPY-block regex once was.
        """
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "bag_pressure.py").read_text(encoding="utf-8")
        body = source[source.index("def %s(" % name):]
        nxt = re.search(r"^def ", body[1:], re.MULTILINE)
        return body[:nxt.start() + 1] if nxt else body

    def test_the_adapter_adds_no_judgement_of_its_own(self):
        """It filters on the owner's mark and then hands everything to
        gear.plan. A threshold here would be the second opinion."""
        body = self._function("family_gifts")
        self.assertIn("gear.plan(", body)
        for invented in ("item_level", "required_level", "quality"):
            with self.subTest(invented=invented):
                self.assertNotIn(invented, body)

    def test_the_recipe_adapter_adds_no_judgement_of_its_own_either(self):
        """The same contract for the recipe half (infra#3731), and the field
        it must not touch is a different one.

        `recipe_gifts` legitimately plumbs `quality` and `sell_price` into a
        `disposition.Item`, exactly as `gear_candidates` does - carrying a
        column is not judging with it. What it must never read is
        `required_skill_rank`. The SQL selects it, and the decision NOT to gate
        a hand-off on it is deliberate and argued: Grug is Blacksmithing 1 and
        Plans: Green Iron Boots wants 145, and he is still the only character
        who will ever be able to learn it. A rank check here would hold every
        recipe in the wrong bag until the day it became learnable, which is the
        bag slot the owner is complaining about.
        """
        body = self._function("recipe_gifts")
        self.assertIn("disposition.learners(", body)
        self.assertIn("disposition.decide(", body)
        self.assertNotIn("required_skill_rank", body)


if __name__ == "__main__":
    unittest.main()

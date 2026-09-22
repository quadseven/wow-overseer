"""A hand-off the family decided on actually LANDS (infra#3464 follow-up).

THE MEASUREMENT THAT MAKES THIS ITS OWN SUITE. tests/test_gear_handoff.py
pins that a piece a sibling should be wearing becomes an overseer_command row.
It does, and the planner is not the problem: measured on the live realm,
`overseer_command` holds 755 kind='trade' rows aimed at exactly the right
people. 41 of them were delivered. The other 714 are:

    343  characters are too far apart to trade
    169  target not online
    146  receiver bags are full
     29  receiver not online
     15  one of the characters is on a flight path
     10  giver is dead

Five per cent. The same three hours of kind='give' rows - the verb the
materials pass uses - delivered 107 of 182, and give's ONLY failure was a full
receiver, because DoGive (mod_overseer.cpp) tests the receiver is online, the
item is not soulbound and the bags have room, and tests nothing else. DoTrade
tests all of that AND that both are alive, neither is in flight, neither is
stunned, neither is logging out, and - the one its own comment calls "normally
false for a travelling group rather than rarely false" - that they are within
TRADE_DISTANCE, 11.11 yards.

SO THE VERB IS NOT A TASTE QUESTION, IT IS A FACT QUESTION. `_hand_gear`'s
docstring says "A trade happens where the two of them already are", and that
is exactly right; what was missing is that nothing ever ASKED where they are.
Measured tonight the five were spread 157-744 yards apart in Ratchet. A trade
issued across 744 yards was never going to render as a visible exchange - it
was only ever going to become an error row - so choosing `give` for it costs
the operator no spectacle at all, and choosing `trade` when they ARE together
keeps the one that can be watched.

WHAT IS PINNED HERE. That the two facts which decide the outcome are read
before the row is written, that they pick the verb rather than being hoped
for, that a receiver with no room is never sent anything by either verb, and
that the pass says what it decided when it decides nothing.
"""

import pathlib
import re
import unittest

import bag_pressure
import gear

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

WARRIOR, PALADIN, ROGUE, PRIEST, MAGE = 1, 2, 4, 5, 8
ANY_CLASS = -1
THE_FIVE = ["Bork", "Grog", "Grug", "Og", "Ugga"]

# Kalimdor, and the stretch of Ratchet the family was measured standing on.
KALIMDOR, EASTERN_KINGDOMS = 1, 0


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = BRIDGE.read_text(encoding="utf-8")
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


def worn(name, class_id, level, **slots):
    """Equipped rows for one character, as _FAMILY_EQUIPPED_SQL returns them."""
    if not slots:
        return [
            dict(
                name=name,
                class_id=class_id,
                level=level,
                inventory_type=None,
                item_level=None,
            )
        ]
    return [
        dict(
            name=name,
            class_id=class_id,
            level=level,
            inventory_type=int(inv.lstrip("i")),
            item_level=int(ilvl),
        )
        for inv, ilvl in slots.items()
    ]


def carried(**kw):
    """One carried gear row, as _SURPLUS_GEAR_SQL returns it.

    Defaults describe the worst row of the 24 measured on 2026-09-11: Grog
    the paladin is carrying Archer's Gloves, item level 35, while Bork the
    rogue is wearing Gloves of the Fang at 19. Sixteen item levels, sitting
    in the wrong bag. `bonding = 2` and `instance_flags = 0` - bind on
    equip, never worn, genuinely tradable.
    """
    base = dict(
        holder="Grog",
        level=39,
        item_guid=7101,
        entry=2033,
        count=1,
        instance_flags=0,
        name="Archer's Gloves",
        quality=2,
        sell_price=1102,
        required_level=30,
        bonding=2,
        item_class=4,
        item_level=35,
        allowable_class=ANY_CLASS,
        inventory_type=10,
    )
    base.update(kw)
    return base


# Grog wearing better gloves than the pair he carries, Bork wearing worse.
THE_HAND_OFF = worn("Grog", PALADIN, 39, i10=36) + worn("Bork", ROGUE, 38, i10=19)


def at(map_id, x, y):
    """One overseer_snapshot row, as _fetch_positions returns it."""
    return dict(map_id=map_id, pos_x=float(x), pos_y=float(y))


# The two states the family is actually ever in. TOGETHER is a dungeon run or
# a vendor hold; APART is the 744 yards measured in Ratchet tonight.
TOGETHER = {"Grog": at(KALIMDOR, 100.0, 100.0), "Bork": at(KALIMDOR, 104.0, 103.0)}
APART = {"Grog": at(KALIMDOR, 100.0, 100.0), "Bork": at(KALIMDOR, 844.0, 100.0)}

ROOM = {"Grog": 4, "Bork": 4}


def hand_off(
    gear_rows, equipped_rows, positions=TOGETHER, free_slots=ROOM, keep_names=()
):
    return bag_pressure.family_gifts(
        gear_rows,
        equipped_rows,
        THE_FIVE,
        keep_names=keep_names,
        position_rows=positions,
        free_slots=free_slots,
    )


class TheGrantIsStillTheGrant(unittest.TestCase):
    """The planner was never the problem, and this suite must not become a
    place where a delivery rule quietly eats a correct decision."""

    def test_the_measured_row_is_still_handed_from_grog_to_bork(self):
        got = hand_off([carried()], THE_HAND_OFF).grants
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0].holder, got[0].taker), ("Grog", "Bork"))
        self.assertEqual(got[0].command, "guid:7101")


class TheVerbFollowsWhereTheyAreStanding(unittest.TestCase):
    def test_together_it_is_a_trade_the_operator_can_watch(self):
        """Inside TRADE_DISTANCE the exchange renders and animates, which is
        the whole reason mod-overseer#14 built DoTrade instead of reusing
        DoGive. Nothing here gives that up."""
        got = hand_off([carried()], THE_HAND_OFF, positions=TOGETHER).grants
        self.assertEqual(got[0].verb, gear.TRADE)

    def test_apart_it_is_a_give_that_actually_lands(self):
        """744 yards. A trade issued across it becomes `characters are too
        far apart to trade` - 343 of the 755 measured rows - and renders
        nothing at all, so there is no spectacle to protect."""
        got = hand_off([carried()], THE_HAND_OFF, positions=APART).grants
        self.assertEqual(got[0].verb, gear.GIVE)

    def test_a_different_map_is_never_a_trade(self):
        """Three of the five hearth to Eastern Kingdoms while the dungeon is
        on Kalimdor. Coordinates on two maps are not comparable at all, and
        subtracting them would put them eleven yards apart by arithmetic."""
        split = {
            "Grog": at(KALIMDOR, 100.0, 100.0),
            "Bork": at(EASTERN_KINGDOMS, 100.0, 100.0),
        }
        got = hand_off([carried()], THE_HAND_OFF, positions=split).grants
        self.assertEqual(got[0].verb, gear.GIVE)

    def test_the_range_is_the_cores_own_trade_distance(self):
        """TRADE_DISTANCE is 11.11 yards (ObjectDefines.h:29) and DoTrade
        measures it in two dimensions, so this measures the same two."""
        self.assertAlmostEqual(gear.TRADE_YARDS, 11.11, places=2)
        inside = {"Grog": at(KALIMDOR, 0.0, 0.0), "Bork": at(KALIMDOR, 11.0, 0.0)}
        outside = {"Grog": at(KALIMDOR, 0.0, 0.0), "Bork": at(KALIMDOR, 12.0, 0.0)}
        self.assertEqual(
            hand_off([carried()], THE_HAND_OFF, positions=inside).grants[0].verb,
            gear.TRADE,
        )
        self.assertEqual(
            hand_off([carried()], THE_HAND_OFF, positions=outside).grants[0].verb,
            gear.GIVE,
        )


class NobodyIsSentAnythingTheyCannotHold(unittest.TestCase):
    """146 trade rows and 68 give rows died on `receiver bags are full`, and
    the family was measured at 221 of 282 slots used with Og at 62 of 62.
    Both verbs test it, so neither is a way around it."""

    def test_a_receiver_with_no_room_is_not_sent_it(self):
        plan = hand_off([carried()], THE_HAND_OFF, free_slots={"Grog": 4, "Bork": 0})
        self.assertEqual(plan.grants, ())
        self.assertIn("Bork", " ".join(plan.notes))

    def test_unknown_capacity_is_treated_as_no_room(self):
        """A failed capacity read is not a licence to write a doomed row -
        the direction materials.retryable_stuck already takes."""
        self.assertEqual(hand_off([carried()], THE_HAND_OFF, free_slots={}).grants, ())

    def test_room_is_budgeted_across_one_pass_not_checked_once(self):
        """Bork has two free slots and three pieces are waiting. Issuing all
        three writes one that was doomed when it was written."""
        rows = [
            carried(),
            carried(item_guid=7102, entry=2034),
            carried(item_guid=7103, entry=2035),
        ]
        plan = hand_off(rows, THE_HAND_OFF, free_slots={"Grog": 4, "Bork": 2})
        self.assertEqual(len(plan.grants), 2)
        self.assertEqual({g.taker for g in plan.grants}, {"Bork"})
        self.assertTrue(plan.notes)


# ---------------------------------------------------------------------------
# THE RANKING DECIDED WHETHER, WHEN IT WAS ONLY EVER ASKED TO DECIDE BETWEEN
#
# Measured on wow-dev 2026-09-19, with the family carrying 23 pieces of
# uncommon-or-better gear and free slots reading Bork 11, Grug 12, Grog 6,
# Og 3, Ugga 0:
#
#     Arachnidian Pauldrons  held by Og (3 free)
#         gain 12   Ugga   0 free
#         gain 10   Grog   6 free
#         gain 10   Grug  12 free
#         gain  1   Bork  11 free
#
# One grant proposed, one grant withheld, nothing moved - while three siblings
# who could wear it had room between them for 29 items. `gear.plan` collapsed
# the four to Ugga because she gained most, and `gear.deliverable` found Ugga
# full and dropped the piece, having no way to reach the other three.
#
# THE ROOM RULE ITSELF WAS NEVER WRONG and is not touched: one free slot on the
# RECEIVER, never a comparison against the giver's. A 0-free-slot holder handing
# to an 11-free-slot sibling must always be tried, and is. What is fixed is that
# a full front-runner now costs that front-runner the item rather than costing
# the item its move.
SHOULDER = 3
THE_FAMILY = (
    worn("Og", MAGE, 60, i3=60)  # holder, already better
    + worn("Ugga", PRIEST, 60, i3=40)  # gain 12
    + worn("Grog", PALADIN, 60, i3=42)  # gain 10, ties broken by name
    + worn("Grug", WARRIOR, 60, i3=42)  # gain 10
    + worn("Bork", ROGUE, 60, i3=51)
)  # gain 1

ALL_PRESENT = {
    name: at(KALIMDOR, 100.0 + i * 400.0, 100.0)
    for i, name in enumerate(["Og", "Ugga", "Grog", "Grug", "Bork"])
}

# The live free-slot reading, to the slot.
MEASURED_ROOM = {"Og": 3, "Ugga": 0, "Grog": 6, "Grug": 12, "Bork": 11}


def pauldrons(**kw):
    """The measured row: cloth shoulders in the bag of somebody wearing better.

    Cloth on purpose, so that all four siblings are genuinely eligible and the
    ranking is the only thing choosing between them - the armour-proficiency
    rule below is a separate guard and must not be what makes this test pass.
    """
    base = dict(
        holder="Og",
        level=60,
        item_guid=7411,
        entry=15452,
        count=1,
        instance_flags=0,
        name="Arachnidian Pauldrons",
        quality=2,
        sell_price=2400,
        required_level=47,
        bonding=2,
        item_class=4,
        item_subclass=gear.ARMOR_CLOTH,
        item_level=52,
        allowable_class=ANY_CLASS,
        inventory_type=SHOULDER,
    )
    base.update(kw)
    return base


class TheRankingChoosesBetweenTakersAndNotWhether(unittest.TestCase):
    """infra#4198. Each of these fails on the code before it, by returning
    zero grants and one note, which is the whole defect stated as a test."""

    def test_the_piece_reaches_the_runner_up_when_the_best_taker_is_full(self):
        plan = hand_off(
            [pauldrons()], THE_FAMILY, positions=ALL_PRESENT, free_slots=MEASURED_ROOM
        )
        self.assertEqual(len(plan.grants), 1)
        self.assertEqual((plan.grants[0].holder, plan.grants[0].taker), ("Og", "Grog"))
        self.assertEqual(plan.notes, ())

    def test_a_zero_slot_holder_may_still_hand_to_an_eleven_slot_sibling(self):
        """The rule is one free slot on the RECEIVER, not more room than the
        giver. Og at 0 handing to Bork at 11 is the move this issue is about,
        and a "must gain room" rule would refuse it by arithmetic."""
        only_bork = {"Og": 0, "Ugga": 0, "Grog": 0, "Grug": 0, "Bork": 11}
        plan = hand_off(
            [pauldrons()], THE_FAMILY, positions=ALL_PRESENT, free_slots=only_bork
        )
        self.assertEqual([(g.holder, g.taker) for g in plan.grants], [("Og", "Bork")])

    def test_the_biggest_beneficiary_still_wins_when_they_have_room(self):
        """The fallback must not become a reason the ranking stops mattering:
        with a slot, Ugga is still the right answer."""
        plan = hand_off(
            [pauldrons()],
            THE_FAMILY,
            positions=ALL_PRESENT,
            free_slots=dict(MEASURED_ROOM, Ugga=2),
        )
        self.assertEqual(plan.grants[0].taker, "Ugga")

    def test_a_promoted_grant_says_who_is_actually_getting_it(self):
        """The reason and the spoken line are what reach the log and party
        chat. A promoted grant still naming the front-runner would be a line
        that lies about what just happened."""
        grant = hand_off(
            [pauldrons()], THE_FAMILY, positions=ALL_PRESENT, free_slots=MEASURED_ROOM
        ).grants[0]
        self.assertIn("Grog", grant.reason)
        self.assertNotIn("Ugga", grant.reason)
        self.assertIn("Grog", grant.said)
        self.assertNotIn("Ugga", grant.said)

    def test_the_verb_is_measured_from_the_taker_who_actually_gets_it(self):
        """Og stands beside Grug, not beside Grog. A verb chosen from the
        front-runner's position and then applied to a different receiver is
        the `characters are too far apart` class of refusal all over again."""
        beside_grug = dict(ALL_PRESENT, Grug=at(KALIMDOR, 103.0, 100.0))
        plan = hand_off(
            [pauldrons()],
            THE_FAMILY,
            positions=beside_grug,
            free_slots={"Og": 3, "Ugga": 0, "Grog": 0, "Grug": 12, "Bork": 0},
        )
        self.assertEqual(
            (plan.grants[0].taker, plan.grants[0].verb), ("Grug", gear.TRADE)
        )

    def test_an_absent_runner_up_is_stepped_over_as_well(self):
        """Presence and room are two walls in front of the same ranking, and
        walking past one must not mean walking into the other."""
        without_grog = {k: v for k, v in ALL_PRESENT.items() if k != "Grog"}
        plan = hand_off(
            [pauldrons()], THE_FAMILY, positions=without_grog, free_slots=MEASURED_ROOM
        )
        self.assertEqual([(g.holder, g.taker) for g in plan.grants], [("Og", "Grug")])

    def test_the_room_budget_still_bites_across_the_whole_ranking(self):
        """Two pieces, one slot on the first taker with room. The second must
        fall through to the next, not be promised the slot the first took."""
        rows = [pauldrons(), pauldrons(item_guid=7412, entry=15453)]
        plan = hand_off(
            rows,
            THE_FAMILY,
            positions=ALL_PRESENT,
            free_slots={"Og": 3, "Ugga": 0, "Grog": 1, "Grug": 12, "Bork": 0},
        )
        self.assertEqual(sorted(g.taker for g in plan.grants), ["Grog", "Grug"])

    def test_a_grant_that_is_written_carries_no_leftover_ranking(self):
        """The insert path reads one taker. A Grant arriving there still
        carrying three more is an invitation to write four rows."""
        grant = hand_off(
            [pauldrons()], THE_FAMILY, positions=ALL_PRESENT, free_slots=MEASURED_ROOM
        ).grants[0]
        self.assertEqual(grant.alternates, ())


class EverybodyRefusingIsStillOneRefusal(unittest.TestCase):
    """The withheld path keeps its contract: one note per ITEM, never one per
    taker tried, or "decided N, queued M, held back K" stops adding up."""

    def test_nobody_with_room_withholds_the_piece(self):
        plan = hand_off(
            [pauldrons()],
            THE_FAMILY,
            positions=ALL_PRESENT,
            free_slots={"Og": 3, "Ugga": 0, "Grog": 0, "Grug": 0, "Bork": 0},
        )
        self.assertEqual(plan.grants, ())
        self.assertEqual(len(plan.notes), 1)

    def test_the_note_names_every_taker_that_was_tried(self):
        """Naming only the front-runner sends the next reader looking at one
        character's bags for a problem all four of them have."""
        plan = hand_off(
            [pauldrons()],
            THE_FAMILY,
            positions=ALL_PRESENT,
            free_slots={"Og": 3, "Ugga": 0, "Grog": 0, "Grug": 0, "Bork": 0},
        )
        note = plan.notes[0]
        self.assertIn("Arachnidian Pauldrons", note)
        for name in ("Ugga", "Grog", "Grug", "Bork"):
            with self.subTest(name=name):
                self.assertIn(name, note)
        self.assertIn("no free bag slot", note)

    def test_both_walls_are_named_when_both_were_hit(self):
        """A note saying only "no free bag slot" for a ranking where two were
        offline and two were full is a note that sends the reader to the wrong
        table."""
        without_the_pair = {
            k: v for k, v in ALL_PRESENT.items() if k not in ("Grug", "Bork")
        }
        plan = hand_off(
            [pauldrons()],
            THE_FAMILY,
            positions=without_the_pair,
            free_slots={"Og": 3, "Ugga": 0, "Grog": 0, "Grug": 12, "Bork": 11},
        )
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("no free bag slot", plan.notes[0])
        self.assertIn("not in the world", plan.notes[0])

    def test_an_absent_giver_is_one_note_about_the_giver(self):
        """The holder is a fact about the item, not about any taker, so it
        refuses the whole ranking at once and says so."""
        without_og = {k: v for k, v in ALL_PRESENT.items() if k != "Og"}
        plan = hand_off(
            [pauldrons()], THE_FAMILY, positions=without_og, free_slots=MEASURED_ROOM
        )
        self.assertEqual(plan.grants, ())
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("Og", plan.notes[0])


class SomebodyWhoIsNotInTheWorldIsNotSentAnything(unittest.TestCase):
    """169 `target not online` plus 29 `receiver not online`. A fresh
    overseer_snapshot row IS the online fact - the module refreshes it about
    once a minute and bridge.py filters stale ones everywhere else - so one
    read answers both where they are and whether they are there at all."""

    def test_an_absent_receiver_is_not_sent_it(self):
        plan = hand_off(
            [carried()], THE_HAND_OFF, positions={"Grog": at(KALIMDOR, 100.0, 100.0)}
        )
        self.assertEqual(plan.grants, ())
        self.assertIn("Bork", " ".join(plan.notes))

    def test_an_absent_giver_hands_nothing_over(self):
        plan = hand_off(
            [carried()], THE_HAND_OFF, positions={"Bork": at(KALIMDOR, 100.0, 100.0)}
        )
        self.assertEqual(plan.grants, ())

    def test_a_row_missing_its_coordinates_is_dropped_not_guessed_at(self):
        broken = {"Grog": at(KALIMDOR, 100.0, 100.0), "Bork": dict(map_id=1)}
        self.assertEqual(
            hand_off([carried()], THE_HAND_OFF, positions=broken).grants, ()
        )


class NobodyAskedIsNotTheSameAsNobodyIsThere(unittest.TestCase):
    """`fits=None` in gear_candidates already means "nobody asked", and the
    pass behaves exactly as it did before that gate existed. These two
    defaults mean the same thing for the same reason, and bridge.py always
    asks - which the source test below pins."""

    def test_positions_unasked_keeps_the_verb_the_pass_always_used(self):
        got = bag_pressure.family_gifts([carried()], THE_HAND_OFF, THE_FIVE)
        self.assertEqual(len(got.grants), 1)
        self.assertEqual(got.grants[0].verb, gear.TRADE)

    def test_free_slots_unasked_does_not_block(self):
        got = bag_pressure.family_gifts(
            [carried()], THE_HAND_OFF, THE_FIVE, position_rows=TOGETHER
        )
        self.assertEqual(len(got.grants), 1)


class ThePassSaysWhatItDecided(unittest.TestCase):
    """`if not grants: return` with no log at all is why 714 doomed rows went
    unnoticed for a fortnight. Every sibling pass around it logs what it
    decided; this one logged only when it wrote something."""

    def test_a_refusal_names_the_piece_and_the_wall_it_hit(self):
        plan = hand_off([carried()], THE_HAND_OFF, free_slots={"Grog": 4, "Bork": 0})
        note = " ".join(plan.notes)
        self.assertIn("Archer's Gloves", note)
        self.assertIn("Bork", note)

    def test_the_empty_path_is_not_silent(self):
        body = _block("    async def _hand_gear(self")
        head = body[: body.index("_recent_trade_keys")]
        self.assertIn("log.", head)

    def test_every_refusal_is_logged_and_not_only_counted(self):
        body = _block("    async def _hand_gear(self")
        self.assertIn(".notes", body)


class TheFactsAreReadBeforeTheRowIsWritten(unittest.TestCase):
    def test_the_pass_asks_where_everybody_is(self):
        body = _block("    async def _hand_gear(self")
        self.assertIn("_fetch_positions", body)

    def test_the_pass_asks_how_much_room_the_receiver_has(self):
        body = _block("    async def _hand_gear(self")
        self.assertIn("_fetch_free_slots", body)

    def test_the_position_read_is_freshness_filtered(self):
        """POSITION COMES FROM overseer_snapshot AND NOT FROM `characters`,
        and a stale row is filtered rather than trusted - bridge.py's own
        rule, stated at _TOWN_COUNTERS_SQL and obeyed everywhere else. A
        stale row here would mean handing gear to somebody who logged out ten
        minutes ago, which is 198 of the 714 refusals."""
        sql = _block("_FAMILY_POSITION_SQL = (")
        self.assertIn("overseer_snapshot", sql)
        self.assertIn("updated_at", sql)
        self.assertNotIn("FROM characters", sql)
        self.assertIn("_FAMILY_POSITION_SQL", _block("def _fetch_positions(names"))

    def test_the_writer_sends_the_verb_the_plan_chose(self):
        body = _block("def _insert_gear_handoff(grant)")
        self.assertIn("grant.verb", body)
        self.assertIn("grant.taker", body)
        self.assertIn("grant.command", body)

    def test_the_writer_still_degrades_on_a_world_without_the_migration(self):
        """1146 missing table, 1265 a `kind` ENUM with no 'trade' value."""
        body = _block("def _insert_gear_handoff(grant)")
        self.assertIn("1146", body)
        self.assertIn("1265", body)

    def test_the_retry_window_covers_both_verbs_of_this_one_pass(self):
        """It keyed on kind='trade' to stay tellable apart from the reagent
        gives. `source` is what actually tells the passes apart, and now that
        this pass writes both verbs, kind no longer can."""
        body = _block("def _recent_trade_keys(minutes: int)")
        self.assertIn("source = 'gear'", body)

    def test_nothing_is_destroyed_and_no_gm_command_is_used(self):
        body = _block("    async def _hand_gear(self")
        for forbidden in ("DELETE", ".delete", "'gm'", "additem"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)


class TheDeliveryRuleIsPureAndLivesWithTheGrant(unittest.TestCase):
    def test_bag_pressure_is_still_the_only_thing_that_imports_gear(self):
        package = pathlib.Path(__file__).resolve().parents[1]
        importers = sorted(
            path.name
            for path in package.glob("*.py")
            if re.search(
                r"^import gear$", path.read_text(encoding="utf-8"), re.MULTILINE
            )
        )
        self.assertEqual(importers, ["bag_pressure.py"])

    def test_the_adapter_still_adds_no_judgement_of_its_own(self):
        source = (
            pathlib.Path(__file__).resolve().parents[1] / "bag_pressure.py"
        ).read_text(encoding="utf-8")
        body = source[source.index("def family_gifts(") :]
        self.assertIn("gear.plan(", body)
        self.assertIn("gear.deliverable(", body)
        for invented in ("TRADE_YARDS", "map_id", "item_level"):
            with self.subTest(invented=invented):
                self.assertNotIn(invented, body)


class ArmourNobodyCanWearIsNeverHandedOver(unittest.TestCase):
    """AllowableClass is -1 on essentially every piece of armour, so the
    bitmask says YES to a priest asked about mail. Measured 2026-09-11: the
    planner proposed handing Battleforge Boots (mail) to Ugga, a priest, and
    7 of the 24 upgrades the family is sitting on are held by somebody who
    physically cannot equip them.

    THIS IS A PREREQUISITE FOR THE REST OF THIS SUITE AND NOT A SIDE QUEST.
    While five per cent of hand-offs landed, a wrong one mostly failed on its
    way out. Making delivery work makes the wrong ones land too.
    """

    def _boots(self, **kw):
        base = dict(
            holder="Grug",
            guid=7301,
            entry=2304,
            name="Battleforge Boots",
            quality=2,
            item_level=29,
            required_level=24,
            allowable_class=ANY_CLASS,
            inventory_type=8,
            item_class=4,
            item_subclass=gear.ARMOR_MAIL,
        )
        base.update(kw)
        return gear.Holding(**base)

    def _who(self, name, class_id, level, feet):
        return gear.CharacterState(
            name=name, class_id=class_id, level=level, equipped={"feet": feet}
        )

    def test_mail_is_never_handed_to_a_priest(self):
        family = [self._who("Grug", WARRIOR, 38, 40), self._who("Ugga", PRIEST, 38, 10)]
        self.assertEqual(gear.plan([self._boots()], family).grants, ())

    def test_mail_still_reaches_the_warrior_who_can_wear_it(self):
        """The check must not become a reason nothing moves at all."""
        family = [self._who("Ugga", PRIEST, 38, 40), self._who("Grug", WARRIOR, 38, 10)]
        got = gear.plan([self._boots(holder="Ugga")], family).grants
        self.assertEqual([(g.holder, g.taker) for g in got], [("Ugga", "Grug")])

    def test_a_priest_holding_mail_has_no_claim_that_blocks_it(self):
        """The same missing fact caused both halves: a priest who counts as
        able to wear mail counts as HAVING A CLAIM on it, and `plan` leaves a
        holder's own claim alone - so the boots never moved either."""
        family = [self._who("Ugga", PRIEST, 38, 10), self._who("Grug", WARRIOR, 38, 20)]
        got = gear.plan([self._boots(holder="Ugga")], family).grants
        self.assertEqual([(g.holder, g.taker) for g in got], [("Ugga", "Grug")])

    def test_plate_waits_for_level_40_and_mail_does_not(self):
        """A paladin at 38-39 wears mail; plate comes at 40."""
        self.assertEqual(gear.heaviest_armor(PALADIN, 39), gear.ARMOR_MAIL)
        self.assertEqual(gear.heaviest_armor(PALADIN, 40), gear.ARMOR_PLATE)
        self.assertEqual(gear.heaviest_armor(WARRIOR, 39), gear.ARMOR_MAIL)

    def test_everybody_wears_cloth_and_only_the_leather_classes_leather(self):
        for class_id in (WARRIOR, PALADIN, ROGUE, PRIEST, MAGE):
            with self.subTest(class_id=class_id):
                self.assertGreaterEqual(
                    gear.heaviest_armor(class_id, 39), gear.ARMOR_CLOTH
                )
        self.assertEqual(gear.heaviest_armor(ROGUE, 39), gear.ARMOR_LEATHER)
        self.assertEqual(gear.heaviest_armor(MAGE, 39), gear.ARMOR_CLOTH)

    def test_a_shield_is_its_own_proficiency_and_not_heavier_armour(self):
        shield = self._boots(
            guid=7302,
            name="Aegis of Stone",
            inventory_type=14,
            item_subclass=gear.ARMOR_SHIELD,
        )
        mage = gear.CharacterState(name="Og", class_id=MAGE, level=39, equipped={})
        warrior = gear.CharacterState(
            name="Grug", class_id=WARRIOR, level=39, equipped={}
        )
        self.assertFalse(gear.wearable_armor(shield, mage))
        self.assertTrue(gear.wearable_armor(shield, warrior))

    def test_a_row_that_never_stated_its_subclass_is_not_guessed_at(self):
        """Refusing on a fact nobody supplied would stop every hand-off on an
        older world image. The SQL always supplies it - pinned below."""
        unstated = self._boots(item_subclass=gear.SUBCLASS_UNSTATED)
        ugga = self._who("Ugga", PRIEST, 38, 10)
        self.assertTrue(gear.wearable_armor(unstated, ugga))

    def test_the_carried_gear_query_states_the_subclass(self):
        sql = _block("_SURPLUS_GEAR_SQL = (")
        self.assertIn("it.subclass AS item_subclass", sql)

    def test_a_weapon_is_not_touched_by_the_armour_rule(self):
        axe = self._boots(
            guid=7303,
            name="Severing Axe",
            item_class=2,
            inventory_type=17,
            item_subclass=1,
        )
        ugga = self._who("Ugga", PRIEST, 38, 0)
        self.assertTrue(gear.wearable_armor(axe, ugga))


if __name__ == "__main__":
    unittest.main()

"""Who in the family takes which trade, and how it is allowed to be acquired.

WHY THIS FILE EXISTS (infra#2757). All five characters gather herbs and nothing
they own consumes one. Measured live 2026-08-23 in `character_skills`:

    herbalism (182)   Grug 34/75  Ugga 17  Bork 15  Og 8  Grog 4
    alchemy (171), cooking (185), first aid (129), fishing (356)   ALL 1/75
    no mining, no skinning, no TAILORING, no leatherworking, no blacksmithing

Upstream's own profession assignment is `PlayerbotFactory::InitTradeSkills`,
and its FIRST TWO LINES are

    if (!sRandomPlayerbotMgr.IsRandomBot(bot))
        return;

(PlayerbotFactory.cpp:2755-2758). mod-overseer's `TrainRoster` calls
`factory.InitSkills()` (mod_overseer.cpp:2206), `InitSkills` calls
`InitTradeSkills` (PlayerbotFactory.cpp:3172), and that call has therefore been
returning at its first line every time it has ever run for these five. Same
wall as #2756 (talents), #2813 (bags) and #2782 (trainer spells).

THE ASSIGNMENT, which is Evan's and not this module's invention:

    Grug   warrior  tank     mining      + blacksmithing
    Bork   rogue             skinning    + leatherworking
    Og     mage              tailoring   + enchanting
    Ugga   priest   healer   herbalism   + alchemy     <- already correct
    Grog   paladin           inscription + jewelcrafting

Engineering is deliberately left to nobody (#2831, the guild).

THE RULE THIS SUITE IS REALLY ABOUT. Evan rejected #2823 for conjuring bags out
of nowhere, and #2782 is open against spells that appear without a trainer
being visited. A profession that simply appears in `character_skills` is the
same violation wearing a different noun. So the tests below assert, as hard as
they assert anything, that this module DECIDES and never GRANTS: there is no
write path to a skill anywhere in it, and an assignment is only ever recorded
as settled once the world is observed to already agree.
"""
import inspect
import pathlib
import re
import unittest

import bonds
import council
import goals
import professions
import travel

SOURCE = pathlib.Path(professions.__file__).read_text(encoding="utf-8")


def _m(name, class_name, skills, seniority=None):
    if seniority is None:
        bond = bonds.member(name)
        seniority = bond.seniority if bond else 0
    return professions.Member(
        name=name, class_name=class_name, skills=dict(skills), seniority=seniority
    )


# The family exactly as it was measured. Every test that talks about who should
# take what runs against this, not against a convenient invention.
def _family():
    def held(herbalism):
        # The three secondaries and alchemy are all present at the floor: they
        # were learned and have never been used. Herbalism is the only one
        # anyone has worked.
        return {
            "herbalism": herbalism, "alchemy": 1,
            "first aid": 1, "cooking": 1, "fishing": 1,
        }

    return [
        _m("Grug", "warrior", held(34)),
        _m("Ugga", "priest", held(17)),
        _m("Bork", "rogue", held(15)),
        _m("Og", "mage", held(8)),
        _m("Grog", "paladin", held(4)),
    ]


def _walk(family, limit=40):
    """Run the plan to completion, applying each errand as if the world obeyed.

    The single most valuable thing this suite does. `plan` only ever emits one
    trade, so no single call can show that the SEQUENCE terminates, that it
    reaches the assignment Evan actually wrote, or that no guard deadlocks it
    three trades in. Walking it does all three at once.

    Returns (steps, final skills) where steps is the flat list of assignments
    in the order they were issued.
    """
    skills = {m.name: dict(m.skills) for m in family}
    steps = []
    for _ in range(limit):
        current = [professions.Member(m.name, m.class_name, skills[m.name],
                                      m.seniority)
                   for m in family]
        issued = professions.plan(current).assignments
        if not issued:
            return steps, skills
        for assignment in issued:
            steps.append(assignment)
            if assignment.verb == "unlearn":
                skills[assignment.character].pop(assignment.skill, None)
            else:
                skills[assignment.character][assignment.skill] = 1
    raise AssertionError("the plan never finished - it is looping")



def _strip_comments(text: str) -> str:
    """The same source with // comments removed, so a guard cannot be tripped
    by prose that explains the very thing it forbids."""
    return "\n".join(re.sub(r"//.*$", "", line) for line in text.splitlines())


def _module_function(signature: str) -> str:
    """The whole of one member function of mod_overseer.cpp, braces balanced.

    Same shape as test_schema_degrade._function and for the same reason: the
    C++ compiles only on a push to `main`, never on a PR, so a contract over
    its source text is the only check that runs before a forty-five minute
    build finds out.
    """
    source = (pathlib.Path(__file__).resolve().parents[3]
              / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
              ).read_text(encoding="utf-8")
    start = source.index(signature)
    depth = 0
    for i in range(source.index("{", start), len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError("%s has no closing brace" % signature)

class SkillFactsTest(unittest.TestCase):
    """The tables, and their agreement with the ones already in the tree."""

    def test_skill_ids_are_not_restated(self):
        """One table of skill ids in this service, not two.

        goals.SKILL_IDS is already the answer to "what number is tailoring". A
        second copy here is a second thing to get wrong.
        """
        for name in professions.PRIMARY | professions.SECONDARY:
            self.assertIn(name, goals.SKILL_IDS)
        self.assertEqual(professions.skill_id("tailoring"), goals.SKILL_IDS["tailoring"])

    def test_the_two_ids_nobody_on_the_realm_holds_are_the_core_s_own(self):
        """Jewelcrafting and inscription could not be verified the way the
        others were - nobody on this realm has either, which is exactly why the
        plan has to name them. They come from the core's enum at the pinned
        SHA instead (SharedDefines.h:3218 and :3235).
        """
        self.assertEqual(goals.SKILL_IDS["jewelcrafting"], 755)
        self.assertEqual(goals.SKILL_IDS["inscription"], 773)

    def test_gathering_and_crafting_partition_the_primaries(self):
        self.assertEqual(
            professions.GATHERING | professions.CRAFTING, professions.PRIMARY
        )
        self.assertFalse(professions.GATHERING & professions.CRAFTING)
        self.assertIn("herbalism", professions.GATHERING)
        self.assertIn("tailoring", professions.CRAFTING)

    def test_secondaries_cost_no_primary_slot(self):
        self.assertEqual(
            professions.SECONDARY, {"first aid", "cooking", "fishing"}
        )
        self.assertFalse(professions.SECONDARY & professions.PRIMARY)
        me = _m("Ugga", "priest", {"first aid": 1, "cooking": 1, "fishing": 1})
        self.assertEqual(professions.free_primary_slots(me), professions.MAX_PRIMARY)


class RosterTest(unittest.TestCase):
    """The assignment itself, and the properties that make it a plan rather
    than five independent guesses."""

    def test_every_member_of_the_family_is_assigned_a_pair(self):
        self.assertEqual(set(professions.ROSTER), set(bonds.FAMILY))
        for name in professions.ROSTER:
            self.assertEqual(len(professions.assigned(name)),
                             professions.MAX_PRIMARY, name)

    def test_the_assignment_is_exactly_what_evan_wrote(self):
        self.assertEqual(professions.assigned("Grug"), ("mining", "blacksmithing"))
        self.assertEqual(professions.assigned("Bork"), ("skinning", "leatherworking"))
        self.assertEqual(professions.assigned("Og"), ("tailoring", "enchanting"))
        self.assertEqual(professions.assigned("Ugga"), ("herbalism", "alchemy"))
        self.assertEqual(professions.assigned("Grog"), ("inscription", "jewelcrafting"))

    def test_nobody_is_assigned_the_same_trade_as_anybody_else(self):
        """Two blacksmiths is one wasted profession slot in a family of five."""
        taken = [s for name in professions.ROSTER
                 for s in professions.assigned(name)]
        self.assertEqual(len(taken), len(set(taken)))

    def test_all_three_gathering_trades_are_covered(self):
        taken = {s for name in professions.ROSTER
                 for s in professions.assigned(name)}
        self.assertEqual(professions.GATHERING - taken, set())

    def test_engineering_is_left_unassigned_on_purpose(self):
        """#2831: Evan wants the guild to cover the last profession. A future
        reader counting the crafts must not 'fix' this."""
        taken = {s for name in professions.ROSTER
                 for s in professions.assigned(name)}
        self.assertEqual(professions.CRAFTING - taken, set(professions.UNASSIGNED))
        self.assertEqual(professions.UNASSIGNED, ("engineering",))

    def test_every_armour_making_craft_suits_the_class_that_owns_it(self):
        """The table was handed down by a person; this is what keeps it
        answerable to a rule anyway. A tailoring warrior would otherwise pass
        unnoticed forever."""
        for member in _family():
            self.assertTrue(
                professions.suits_wearer(member.name, member.class_name),
                f"{member.name} ({member.class_name}) is assigned "
                f"{professions.assigned(member.name)}",
            )

    def test_a_mismatched_pair_would_be_caught(self):
        """The guard above is only worth having if it can fail."""
        self.assertFalse(professions.suits_wearer("Og", "warrior"))

    def test_grog_is_the_one_who_depends_on_everyone_else(self):
        """His pair is deliberately gathering-free: inscription runs on Ugga's
        herbs and jewelcrafting on Grug's ore, which makes the material
        hand-off (#2830) structural rather than optional."""
        self.assertFalse(set(professions.assigned("Grog")) & professions.GATHERING)
        self.assertIn("#2830", professions.ROSTER["Grog"].why)

    def test_every_row_says_why(self):
        for name, trade in professions.ROSTER.items():
            self.assertTrue(trade.why.strip(), name)


class SlotsTest(unittest.TestCase):
    """Two primaries, and the family has no spare ones. This is the fact that
    makes the whole assignment expensive."""

    def test_a_character_may_hold_two_primaries(self):
        self.assertEqual(professions.MAX_PRIMARY, 2)

    def test_the_measured_family_has_no_free_primary_slot(self):
        for member in _family():
            self.assertEqual(
                professions.free_primary_slots(member), 0,
                f"{member.name} holds herbalism AND alchemy - both slots are full",
            )


class GuardTest(unittest.TestCase):
    """`expendable`, which is the guard, and which had to be rewritten when the
    plan went from one tailor to a whole economy.

    The old form was "at the floor, and somebody else holds it". It is recorded
    in the module why that was both too strict (it would refuse the family's
    own decision, because three of them have WORKED herbalism) and too weak (an
    unlucky order could walk the family down to a single holder who is himself
    scheduled to drop it next). These tests pin the replacement.
    """

    def test_a_skill_you_are_assigned_is_never_expendable(self):
        ugga = next(m for m in _family() if m.name == "Ugga")
        self.assertEqual(professions.expendable(ugga, _family()), ())

    def test_worked_skill_IS_expendable_when_the_assignment_says_so(self):
        """The relaxation, stated as a test so it is a decision and not a
        drift. Grug's herbalism is 34/75 and he is assigned mining +
        blacksmithing, so it goes - and the cost is reported, not hidden."""
        grug = next(m for m in _family() if m.name == "Grug")
        self.assertIn("herbalism", professions.expendable(grug, _family()))

    def test_the_family_must_keep_the_trade_by_ASSIGNMENT_not_by_luck(self):
        """The condition the old count-based rule could not express. If nobody
        in this family is assigned herbalism, nobody may give it up - however
        many people happen to be holding it right now."""
        family = _family()
        original = professions.ROSTER["Ugga"]
        professions.ROSTER["Ugga"] = professions._Trade(
            primaries=("tailoring", "enchanting"), why="test",
        )
        try:
            grug = next(m for m in family if m.name == "Grug")
            self.assertNotIn("herbalism", professions.expendable(grug, family))
        finally:
            professions.ROSTER["Ugga"] = original

    def test_the_transition_never_passes_through_zero_holders(self):
        """Belt and braces alongside the assignment rule: even with a keeper
        assigned, nobody may drop the only copy that currently exists."""
        family = [
            _m("Grug", "warrior", {"herbalism": 34, "alchemy": 1}),
            _m("Ugga", "priest", {"alchemy": 1}),
        ]
        grug = family[0]
        # Ugga is ASSIGNED herbalism, so condition (b) holds - but she does not
        # hold it yet, so Grug dropping it would leave the family with none.
        self.assertNotIn("herbalism", professions.expendable(grug, family))

    def test_the_cheapest_thing_goes_first(self):
        """Alchemy at 1/75 before herbalism at 34/75, so the expensive loss is
        deferred as long as the plan allows."""
        grug = next(m for m in _family() if m.name == "Grug")
        self.assertEqual(professions.expendable(grug, _family())[0], "alchemy")

    def test_a_stalled_plan_says_so_instead_of_forcing_it(self):
        """With the only assigned herbalist offline, the plan must refuse to
        strip the family's herbalism rather than proceed. Loud, not silent."""
        family = [m for m in _family() if m.name != "Ugga"]
        # Drive Grug to the point where herbalism is the only room he has.
        family = [
            _m("Grug", "warrior", {"herbalism": 34, "mining": 1})
            if m.name == "Grug" else m
            for m in family
        ]
        plan = professions.plan(family)
        blocked = [a for a in plan.assignments if a.character == "Grug"]
        self.assertEqual(blocked, [])


class PlanTest(unittest.TestCase):
    """What the family decides, on the measured state."""

    def test_ugga_is_asked_for_nothing_at_all(self):
        """The correctness check the whole rework hangs on: she already holds
        exactly her assignment, so an errand for her means something is wrong.
        """
        steps, _ = _walk(_family())
        self.assertEqual([a for a in steps if a.character == "Ugga"], [])

    def test_the_family_gets_a_tailor_first(self):
        """The measured blocker. Every bag is full, a full bag freezes a
        character on a herb node (#2813), and the linen is already in their
        bags - so tailoring is the one trade that pays out the day it lands."""
        plan = professions.plan(_family())
        learns = [a for a in plan.assignments if a.verb == "learn"]
        self.assertEqual([(a.character, a.skill) for a in learns],
                         [("Og", "tailoring")])

    def test_only_one_trade_is_opened_at_a_time(self):
        """Each learn is a journey to a trainer the family cannot currently
        make. Queueing eight of them would be eight things not happening
        instead of one."""
        learns = [a for a in professions.plan(_family()).assignments
                  if a.verb == "learn"]
        self.assertEqual(len(learns), 1)

    def test_making_room_is_its_own_errand_and_comes_first(self):
        """Both primary slots are full, so learning is two errands at two
        different trainers. Recording it as one would hide the half that costs
        somebody something."""
        rows = professions.plan(_family()).assignments
        self.assertEqual([(a.character, a.verb, a.skill) for a in rows],
                         [("Og", "unlearn", "alchemy"),
                          ("Og", "learn", "tailoring")])

    def test_the_sequence_terminates_at_exactly_the_assignment(self):
        """The whole economy, walked end to end. No guard deadlocks it, it
        does not loop, and where it stops is where Evan said it should."""
        _, final = _walk(_family())
        for name, wanted in (
            ("Grug", {"mining", "blacksmithing"}),
            ("Bork", {"skinning", "leatherworking"}),
            ("Og", {"tailoring", "enchanting"}),
            ("Ugga", {"herbalism", "alchemy"}),
            ("Grog", {"inscription", "jewelcrafting"}),
        ):
            held = {s for s in final[name] if s in professions.PRIMARY}
            self.assertEqual(held, wanted, name)

    def test_the_whole_sequence_is_eight_learns_and_eight_unlearns(self):
        """Four characters each give up BOTH herbalism and alchemy, so it is
        eight unlearns and not four - the arithmetic is worth pinning, because
        it is the size of what this plan costs."""
        steps, _ = _walk(_family())
        self.assertEqual(len([a for a in steps if a.verb == "learn"]), 8)
        self.assertEqual(len([a for a in steps if a.verb == "unlearn"]), 8)

    def test_the_family_keeps_a_herbalist_and_an_alchemist_throughout(self):
        """Walked step by step: at no point does the family have zero of
        either. This is the guard doing its job over time rather than at one
        instant."""
        family = _family()
        skills = {m.name: dict(m.skills) for m in family}
        for _ in range(40):
            current = [professions.Member(m.name, m.class_name, skills[m.name],
                                          m.seniority) for m in family]
            issued = professions.plan(current).assignments
            if not issued:
                break
            for assignment in issued:
                if assignment.verb == "unlearn":
                    skills[assignment.character].pop(assignment.skill, None)
                else:
                    skills[assignment.character][assignment.skill] = 1
                for trade in ("herbalism", "alchemy"):
                    holders = [n for n, s in skills.items() if trade in s]
                    self.assertTrue(holders, f"nobody holds {trade} any more")

    def test_a_gatherer_is_opened_before_the_craft_it_feeds(self):
        """A craft with no supply is a skill that sits at 1/75, which is the
        exact failure this whole issue is about."""
        steps, _ = _walk(_family())
        order = [a.skill for a in steps if a.verb == "learn"]
        self.assertLess(order.index("mining"), order.index("blacksmithing"))
        self.assertLess(order.index("skinning"), order.index("leatherworking"))

    def test_grogs_pair_is_opened_last(self):
        """It depends entirely on other people having their gathering trades
        first; opening it early would be opening two more empty skills."""
        steps, _ = _walk(_family())
        order = [a.skill for a in steps if a.verb == "learn"]
        self.assertEqual(order[-2:], ["inscription", "jewelcrafting"])

    def test_nobody_is_ever_asked_to_give_up_something_they_are_assigned(self):
        steps, _ = _walk(_family())
        for assignment in steps:
            if assignment.verb != "unlearn":
                continue
            self.assertNotIn(assignment.skill,
                             professions.assigned(assignment.character))

    def test_the_plan_is_deterministic_under_reordering(self):
        family = _family()
        first = professions.plan(family)
        second = professions.plan(list(reversed(family)))
        self.assertEqual(first.assignments, second.assignments)

    def test_every_assignment_says_why(self):
        for assignment in professions.plan(_family()).assignments:
            self.assertTrue(assignment.reason.strip())

    def test_an_empty_family_plans_nothing(self):
        self.assertEqual(professions.plan([]).assignments, ())

    def test_the_alchemist_is_read_off_the_roster(self):
        """Not computed from who gathers most today - that is a fact about
        today, and the plan is about to change it."""
        self.assertEqual(professions.alchemist(_family()), "Ugga")


class CostTest(unittest.TestCase):
    """What this plan destroys, said before it happens."""

    def test_the_loss_is_priced_on_the_errand(self):
        steps, _ = _walk(_family())
        drop = next(a for a in steps
                    if a.character == "Grug" and a.skill == "herbalism")
        self.assertEqual(drop.cost, 34)
        self.assertIn("34/75", drop.reason)

    def test_the_notes_add_up_every_worked_point_in_advance(self):
        """Nobody should find out afterwards that Grug's 34/75 went. It is the
        single largest cost in the assignment and it is stated before a single
        errand runs."""
        notes = " ".join(professions.plan(_family()).notes)
        self.assertIn("Grug's herbalism at 34/75", notes)
        for value in ("15/75", "8/75", "4/75"):
            self.assertIn(value, notes)

    def test_a_floor_skill_is_not_reported_as_a_loss(self):
        """Alchemy at 1/75 was learned and never used. Calling that a loss
        would make the warning about Grug's 34 read as boilerplate."""
        notes = " ".join(professions.plan(_family()).notes)
        self.assertNotIn("alchemy at 1/75", notes)

    def test_the_secondaries_are_a_levelling_matter_and_never_an_errand(self):
        steps, _ = _walk(_family())
        for assignment in steps:
            self.assertNotIn(assignment.skill, professions.SECONDARY)
        notes = " ".join(professions.plan(_family()).notes)
        self.assertIn("cooking, fishing and first aid", notes)

    def test_who_needs_nothing_is_named(self):
        self.assertIn("Ugga", " ".join(professions.plan(_family()).notes))


class ErrandTest(unittest.TestCase):
    """An assignment is a journey, and it says so."""

    def test_an_errand_names_a_trainer(self):
        steps, _ = _walk(_family())
        for assignment in steps:
            self.assertIn("trainer", professions.errand(assignment).lower())

    def test_the_errand_names_the_character_and_the_skill(self):
        assignment = next(a for a in professions.plan(_family()).assignments
                          if a.verb == "learn")
        errand = professions.errand(assignment)
        self.assertIn(assignment.character, errand)
        self.assertIn("tailoring", errand.lower())

    def test_the_family_says_it_out_loud(self):
        """#2829: a need has to become a request to a person, in party chat.
        A plan nobody hears is the overseer talking to itself."""
        lines = professions.lines(professions.plan(_family()))
        self.assertTrue(lines)
        for line in lines:
            speaker, sep, said = line.partition(": ")
            self.assertEqual(sep, ": ", line)
            self.assertIsNotNone(bonds.member(speaker), speaker)
            self.assertTrue(said.strip())


class NoMagicTest(unittest.TestCase):
    """The whole point of the issue. A profession is LEARNED, never granted.

    These are structural assertions against the module's own source, in the
    same spirit as test_bags.py: they hold whatever a future edit intends,
    which an assertion about behaviour on one input does not.
    """

    # Every way a skill could be made to appear without anybody going anywhere.
    # Named upstream functions are deliberately NOT on this list: the module
    # docstring cites InitTradeSkills and character_skills by name, and it
    # should - the citation is the argument. What is banned is the machinery
    # that could act on them.
    FORBIDDEN = [
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "execute(",
        "cursor",
        "SetSkill",
        "learnSpell",
        ".learn ",              # the GM dot-command
    ]

    def test_the_module_cannot_write_a_skill(self):
        for needle in self.FORBIDDEN:
            self.assertNotIn(
                needle, SOURCE,
                f"professions.py must not contain {needle!r} - a profession is "
                "learned at a trainer, not written into the database",
            )

    def test_the_module_touches_no_database_and_no_network(self):
        """Pure decision module, same seam as council.py and goals.py. It is
        importable with nothing running, which is also what makes this suite
        able to assert anything at all about it."""
        for banned in ("pymysql", "import os", "requests", "urllib", "socket",
                       "subprocess"):
            self.assertNotIn(banned, SOURCE, banned)

    def test_settled_reads_the_world_and_never_changes_it(self):
        """`settled` is the ONLY thing that may move an assignment forward, and
        it takes the observed skills as an argument. There is no path from this
        module to the observation, which is what stops it from being faked."""
        signature = inspect.signature(professions.settled)
        self.assertEqual(list(signature.parameters), ["assignment", "skills"])

    def test_a_learn_is_settled_only_once_the_skill_exists(self):
        assignment = next(a for a in professions.plan(_family()).assignments
                          if a.verb == "learn")
        self.assertFalse(professions.settled(assignment, {"herbalism": 17}))
        self.assertTrue(
            professions.settled(assignment, {"herbalism": 17, "tailoring": 1})
        )

    def test_an_unlearn_is_settled_only_once_the_skill_is_gone(self):
        assignment = next(a for a in professions.plan(_family()).assignments
                          if a.verb == "unlearn")
        self.assertFalse(professions.settled(assignment, {"alchemy": 1}))
        self.assertTrue(professions.settled(assignment, {"herbalism": 17}))

    def test_the_blockers_are_stated_rather_than_worked_around(self):
        """The honest half of this change, and it must never become empty.

        BLOCKERS used to list the transaction: the family could reach a trainer
        and not buy anything from it. #2757 built that verb, so those entries
        are gone - but deleting the constant, or emptying it, would say
        "nothing can go wrong", and a feature that reports success while doing
        nothing is the exact failure this whole epic is about.

        What must remain is the fact that none of it is real until it SHIPS.
        The verbs are C++ compiled only on a push to main, and the roster
        columns travel in a different image on a different pin (infra#2846), so
        a decision reached here can still be silently dropped by a SELECT that
        fails with error 1054.
        """
        blockers = professions.BLOCKERS
        self.assertTrue(blockers)
        self.assertTrue(any("1054" in b for b in blockers),
                        "the undeployed-schema failure must stay named")
        self.assertTrue(any("2846" in b for b in blockers))

    def test_the_transaction_is_no_longer_claimed_to_be_missing(self):
        """THE SAME REGRESSION AS test_the_aim_is_no_longer_claimed_to_be_missing,
        one step further along.

        professions.py asserted for weeks that nothing could point a bot at a
        chosen NPC; #2840 made that false and the wording was removed. It then
        asserted that arriving could not TRAIN; #2757 made that false too. A
        module that keeps saying either sends the next reader off to rebuild
        something that already shipped - which is the same class of harm as a
        module that grants a skill: a confident false statement about the tree.

        The citations banned below are the ones that were true of the OLD
        world. TrainerAction really does read the master's selection, and
        arrival really does only interact for a quest - both are still true of
        UPSTREAM, and both stopped being blockers the moment mod-overseer went
        underneath them to the core's own Trainer object.
        """
        blob = "\n".join(professions.BLOCKERS)
        for stale in ("TRAVEL, NOT TRANSACTION", "TrainerAction.cpp:22-24",
                      "NewRpgAction.cpp:398-400", "NOTHING LEARNS FROM A TRAINER",
                      "it is one verb wide"):
            self.assertNotIn(stale, blob, stale)

    def test_a_plan_becomes_roster_columns_and_nothing_else(self):
        """The road that was missing, and the shape it may take.

        `overseer_trade` is a Python table; mod-overseer reads
        `overseer_roster`. That gap is why two correct rows sat unread for two
        days. `to_errand` is the crossing - and it is still only a VALUE, not
        an action: this module has no database and cannot write anything.
        """
        family = [
            professions.Member("Og", "mage", {"alchemy": 1, "herbalism": 15}),
            professions.Member("Ugga", "priest", {"alchemy": 1, "herbalism": 47}),
            professions.Member("Grug", "warrior", {"alchemy": 1, "herbalism": 41}),
            professions.Member("Bork", "rogue", {"alchemy": 1, "herbalism": 15}),
            professions.Member("Grog", "paladin", {"alchemy": 1, "herbalism": 33}),
        ]
        plan = professions.plan(family)
        skills = {m.name: dict(m.skills) for m in family}
        errand = professions.to_errand(plan, skills)

        # The measured family's actual next step: Og drops an alchemy he has
        # never used and buys the tailoring the bags need.
        self.assertEqual(errand.character, "Og")
        self.assertEqual(errand.learn_skill, professions.skill_id("tailoring"))
        self.assertEqual(errand.unlearn_skill, professions.skill_id("alchemy"))
        self.assertEqual(errand.travel_npc, "profession trainer")

        # THE PRICE IS READ FROM THE OBSERVATION, never invented. Og's alchemy
        # is 1/75, so that is what the request agrees to destroy - and
        # mod-overseer refuses if the live value is above it.
        self.assertEqual(errand.unlearn_max, 1)

    def test_the_price_of_an_unlearn_tracks_what_was_observed(self):
        """A stale price must not silently become a licence to destroy more.

        The whole point of `unlearn_max` is that it is the requester's BELIEF
        about the cost, checked against the world at the moment of the act. So
        it has to come from the observation handed in, not from the plan.
        """
        family = [
            professions.Member("Og", "mage", {"alchemy": 30, "herbalism": 15}),
            professions.Member("Ugga", "priest", {"alchemy": 1, "herbalism": 47}),
            professions.Member("Grug", "warrior", {"alchemy": 1, "herbalism": 41}),
            professions.Member("Bork", "rogue", {"alchemy": 1, "herbalism": 15}),
            professions.Member("Grog", "paladin", {"alchemy": 1, "herbalism": 33}),
        ]
        plan = professions.plan(family)
        skills = {m.name: dict(m.skills) for m in family}
        errand = professions.to_errand(plan, skills)

        # Whatever the plan chose to drop, the price is that skill's OBSERVED
        # value - not a constant, not Assignment.cost, and not the value it had
        # when the row was first written. Asserted against the observation
        # rather than against a hard-coded 30, because which skill `expendable`
        # picks is the plan's business and this test is about the price.
        dropped = next(a for a in plan.assignments if a.verb == "unlearn")
        self.assertEqual(errand.unlearn_skill, dropped.skill_id)
        self.assertEqual(errand.unlearn_max, skills["Og"][dropped.skill])
        # And it moved with the world: the same family with everything at 1
        # prices the same drop at 1.
        self.assertNotEqual(errand.unlearn_max, 0)

    def test_an_errand_moves_the_leadership_rather_than_the_strategy(self):
        """The answer to the blocker that looked unanswerable, pinned down.

        Only `new rpg` walks a character to an NPC and the family carry it on
        the LEADER ALONE - a follower given both it and `follow` wanders off
        every tick, which is the 937-yard scatter of infra#2812. So an errand
        cannot be run by handing a follower the travelling strategy. It is run
        by making the character with the errand BE the leader, so the other
        four follow it to the trainer and the party stays together.

        An unlearn needs no journey - it is a spellbook action - so it moves
        nobody, and `traveller` says so.
        """
        walk = professions.Errand("Og", learn_skill=197, travel_npc="profession trainer")
        self.assertEqual(professions.traveller(walk), "Og")

        no_walk = professions.Errand("Og", unlearn_skill=171, unlearn_max=1)
        self.assertEqual(professions.traveller(no_walk), "")
        self.assertEqual(professions.traveller(None), "")

    def test_the_declared_end_state_is_written_as_ids(self):
        """The roster column is the module's only permission, and it carries
        numbers because both ends already hold these numbers. A word here would
        be a third spelling of a fact that exists twice, and the only thing a
        third spelling can add is a way to disagree."""
        self.assertEqual(
            professions.wanted_ids("Og"),
            "%d,%d" % tuple(sorted((professions.skill_id("tailoring"),
                                    professions.skill_id("enchanting")))),
        )
        # A character nobody has decided about declares nothing - and an empty
        # column is what makes mod-overseer refuse to touch it at all.
        self.assertEqual(professions.wanted_ids("Nobody"), "")

    def test_the_aim_is_no_longer_claimed_to_be_missing(self):
        """THE REGRESSION THIS FILE EXISTS TO CATCH TWICE OVER.

        professions.py used to assert, in BLOCKERS, that nothing could point a
        bot at a chosen NPC - ChangeToWanderNpc took no argument. #2840 made
        that false. A module that keeps saying it sends the next reader to
        rebuild something that already shipped, which is the same class of
        harm as a module that grants a skill: a false statement about the
        tree. So the old wording may not come back.
        """
        blob = "\n".join(professions.BLOCKERS)
        for stale in ("ChangeToWanderNpc()", "NewRpgInfo.h:104",
                      "picks its own", "SetMoveFarTo",
                      "there is no word for travel"):
            self.assertNotIn(stale, blob, stale)

    def test_the_aim_this_plan_needs_is_a_role_travel_actually_offers(self):
        """The claim that the aim exists is checked against the module that
        provides it, not just asserted in prose. If travel.ROLES ever loses
        the profession-trainer role, the follow-up this PR defers to has lost
        its footing and BLOCKERS is wrong again."""
        self.assertIn("profession trainer", travel.ROLES)
        self.assertEqual(travel.ROLES["profession trainer"],
                         "UNIT_NPC_FLAG_TRAINER_PROFESSION")


class UpstreamWallTest(unittest.TestCase):
    """The reason this had to be written at all, pinned to the shipped source.

    mod-overseer calls InitSkills expecting it to do the whole job. If a future
    reader deletes that call, or upstream is bumped past the IsRandomBot guard,
    this suite should be what tells them the premise changed.
    """

    ROOT = pathlib.Path(__file__).resolve().parents[3]
    MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"

    def test_train_roster_still_calls_initskills(self):
        source = self.MODULE.read_text(encoding="utf-8")
        self.assertIn("factory.InitSkills();", source)

    def test_the_module_grants_no_profession_without_a_trainer(self):
        """A profession may only ever arrive by being bought from a trainer.

        THIS TEST USED TO SAY `SetSkill(` MUST NOT APPEAR AT ALL, and that was
        the right guard for as long as the module could not train. It is the
        wrong guard now, and keeping it would have blocked the fix rather than
        the cheat: `SetSkill(id, 0, 0, 0)` is how a profession is GIVEN UP -
        it is the one line WorldSession::HandleUnlearnSkillOpcode runs - and it
        cannot grant anything to anybody.

        What the old test was really protecting is #2782: a skill must not
        appear in `character_skills` without a trainer having been visited and
        paid. That rule is unchanged and is now stated directly. The three ways
        a module could break it are all named below, because a blanket ban on a
        function name is only ever a proxy for the rule it stands in for.
        """
        source = self.MODULE.read_text(encoding="utf-8")
        # Comments are stripped for the refusals below. Searching the raw text
        # is not a reachability test: this file EXPLAINS both cheats at length,
        # naming InitTradeSkills and learnSpell to say why they are not used,
        # and a guard that a correct explanation can trip is a guard nobody
        # will keep. Same reason test_schema_degrade._code exists.
        code = _strip_comments(source)

        # 1. NO SECOND COPY OF THE TEACHING LOOP. Trainer::TeachSpell is where
        #    the money is taken and the free-slot rule is enforced. Going round
        #    it - the way PlayerbotFactory and TrainerAction both do, with a
        #    bare learnSpell or a CastSpell of the trainer spell - is exactly
        #    how a profession appears without a trainer being paid.
        self.assertIn("trainer->TeachSpell(npc, bot, spellId);", source)
        for cheat in ("bot->learnSpell(", "InitTradeSkills"):
            self.assertNotIn(cheat, code, cheat)

        # 2. THE ONLY SetSkill IS THE ZEROING ONE. A SetSkill with a non-zero
        #    value would be a granted skill wearing an unlearn's clothes.
        self.assertEqual(
            ["bot->SetSkill(static_cast<uint16>(skill), 0, 0, 0);"],
            [line.strip() for line in code.splitlines()
             if "->SetSkill(" in line and not line.lstrip().startswith("//")])

        # 3. THE DECLARED END STATE IS THE ONLY PERMISSION. Both verbs consult
        #    it, in opposite directions: nothing outside `wanted` is learned,
        #    and nothing inside it is ever unlearned.
        learn = _module_function("bool TrainOnArrival(")
        unlearn = _module_function("void UnlearnProfession(")
        self.assertIn("if (!plan.wanted.count(skill))", learn)
        self.assertIn("if (plan.wanted.count(skill))", unlearn)

    def test_the_level_up_sweep_cannot_take_a_profession(self):
        """The fourth blocker, and the one that would have made the rest moot.

        PlayerbotFactory::InitAvailableSpells walks every Tradeskill trainer
        TEMPLATE in the world and learns everything CanTeachSpell says yes to,
        with no NPC and no money. CanTeachSpell refuses a primary profession's
        first rank on exactly one condition - no free primary profession point.
        So for as long as a slot is open, the level-up sweep takes a profession
        out of thin air, and it is where the alchemy all five hold at 1/75 came
        from: the same one for everybody, because it was an iteration order and
        never a roll.

        Without the guard, freeing Og's slot for tailoring would have handed it
        straight back to the sweep within sixty seconds, forever.
        """
        train = _module_function("void TrainRoster(")
        shut = train.index("bot->SetFreePrimaryProfessions(0);")
        sweep = train.index("factory.InitAvailableSpells();")
        restore = train.index(
            "bot->SetFreePrimaryProfessions(static_cast<uint16>(freeProfessionSlots));")
        self.assertLess(shut, sweep, "the slots must be shut BEFORE the sweep")
        self.assertLess(sweep, restore, "and reopened after it")

    def test_an_unlearn_refuses_a_cost_nobody_agreed_to(self):
        """Dropping a profession destroys skill progress, so the request has to
        carry the price. `unlearn_max` is the most the requester agreed to
        destroy; a live value above it is a refusal that LEAVES THE REQUEST
        STANDING, so a stale requester can answer by raising the price rather
        than discovering the loss afterwards."""
        unlearn = _module_function("void UnlearnProfession(")
        self.assertIn("if (value > plan.unlearnMax)", unlearn)
        # Refused, not cleared: the three refusals that can never become right
        # clear the request; this one is a disagreement and must survive.
        refusal = unlearn[unlearn.index("if (value > plan.unlearnMax)"):]
        self.assertNotIn("ClearUnlearnRequest", refusal[:refusal.index("return;")])

    def test_a_trainer_errand_is_narrowed_to_a_trainer_that_teaches_it(self):
        """UNIT_NPC_FLAG_TRAINER_PROFESSION is worn by cooking instructors and
        fishing trainers too, so the nearest one to Elwynn is very unlikely to
        be a tailor. Resolving without narrowing would walk a mage confidently
        to a cook, log an arrival, and teach him nothing."""
        resolve = _module_function("bool ResolveTravelTarget(")
        self.assertIn("uint32 wantSkill = 0", resolve)
        self.assertIn(
            "if (narrowToSkill && !TrainerStartedSkills(spawn.entry).count(wantSkill))",
            resolve)


class CouncilTest(unittest.TestCase):
    """The family can now RAISE it. Before this, it could not.

    council.assess had a 'trades' branch guarded by `me.trades <
    TRADES_EXPECTED`, and bridge fed it `SELECT COUNT(*) FROM character_skills`
    - every skill a character has, including languages, Defense and every
    weapon skill. On the measured family that count is at least the five
    profession rows above before a single language is counted, so the branch
    was false for everybody, always. The proposal existed and could never be
    made.
    """

    def test_a_member_who_owes_the_family_a_trade_says_so(self):
        me = council.Member(name="Og", level=12, class_name="Mage",
                            trades=5, trade_wanted="tailoring")
        proposal = council.assess(me, public_levels={"Og": 12, "Grug": 14})
        self.assertEqual((proposal.kind, proposal.beneficiary), ("trades", "Og"))
        self.assertIn("tailoring", proposal.said.lower())

    def test_it_outranks_an_idle_afternoon_and_loses_to_a_quest(self):
        wanted = council.Member(name="Og", level=12, class_name="Mage",
                                trades=5, trade_wanted="tailoring")
        questing = council.Member(name="Og", level=12, class_name="Mage",
                                  trades=5, trade_wanted="tailoring",
                                  quest="I must find the candles.", quest_left=2,
                                  quest_id=60)
        self.assertEqual(council.assess(
            questing, public_levels={"Og": 12, "Grug": 14}).kind, "quest")
        self.assertEqual(council.assess(
            wanted, public_levels={"Og": 12, "Grug": 14}).kind, "trades")

    def test_a_member_with_nothing_owed_is_unaffected(self):
        me = council.Member(name="Ugga", level=12, class_name="Priest", trades=5)
        proposal = council.assess(me, public_levels={"Ugga": 12, "Grug": 14})
        self.assertNotEqual(proposal.kind, "trades")

    def test_a_trades_plan_is_not_a_goal_the_supervisor_drives(self):
        """A 'trades' plan is a real decision and is NOT a goal. There is no
        strategy that makes a character learn a profession, and persisting one
        would have the supervisor issue `nc +grind` for it and then report the
        trade healthy - the exact 'reports success, does nothing' shape this
        epic keeps rediscovering. So it stays out of DRIVEN_KINDS.
        """
        bridge = pathlib.Path(bonds.__file__).with_name("bridge.py").read_text(
            encoding="utf-8"
        )
        driven = re.search(r"^DRIVEN_KINDS = \((.*)\)$", bridge, re.MULTILINE)
        self.assertIsNotNone(driven)
        self.assertNotIn("trades", driven.group(1))


class BridgeContractTest(unittest.TestCase):
    """What bridge.py must be doing with all this, asserted against its source
    because the bridge itself is not importable without a database."""

    BRIDGE = pathlib.Path(bonds.__file__).with_name("bridge.py").read_text(
        encoding="utf-8"
    )

    def _holds(self, needle):
        """assertIn against a 100KB file prints the whole file on failure, and
        one failing assertion then buries the run that reported it."""
        self.assertTrue(needle in self.BRIDGE, f"bridge.py should contain {needle!r}")

    def _lacks(self, needle):
        self.assertFalse(needle in self.BRIDGE,
                         f"bridge.py should no longer contain {needle!r}")

    def test_the_trade_count_the_council_sees_counts_only_trades(self):
        """`COUNT(*) FROM character_skills` counts languages, Defense and every
        weapon skill, and was therefore never below two for anybody alive - so
        council.assess's trades branch could never once be reached."""
        self._lacks("COUNT(*) FROM character_skills k WHERE k.guid = c.guid")
        self._holds("k.skill IN")

    def test_the_bridge_never_writes_character_skills(self):
        for statement in re.findall(r"\"[^\"]*character_skills[^\"]*\"", self.BRIDGE):
            self.assertNotRegex(statement, r"(?i)\b(insert|update|delete|replace)\b")

    def test_the_trade_plan_is_persisted_and_spoken(self):
        self._holds("overseer_trade")
        self._holds("professions.plan")
        self._holds("professions.lines")

    def test_a_trade_row_is_only_settled_by_observation(self):
        self._holds("professions.settled")


if __name__ == "__main__":
    unittest.main()

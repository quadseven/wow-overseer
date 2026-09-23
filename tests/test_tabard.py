"""The family argues about the tabard and arrives at one.

The operator, on infra#2831: "when they have enough money they will make one called
Cave and they will design their tabard after discussing what it should look
like".

The guild exists now, so this is the last third of that sentence. Two things
make it a design rather than a config value, and both are tested here: every
field is won by somebody who wanted it, and the same family always arrives at
the same tabard - because a debate that reaches a different answer each night
is the #2807 restaging bug wearing a new hat.
"""

import pathlib
import re
import unittest

import bonds
import tabard

BRIDGE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()


# The real family, with the race and class ids the live characters row holds -
# verified against the dev realm 2026-09-12 rather than remembered:
#   Grug human(1) warrior(1)   Ugga human(1) priest(5)   Grog dwarf(3) paladin(2)
#   Bork gnome(7) rogue(4)     Og   human(1) mage(8)
# The two short races are the joke bonds.py explains: they read as children.
FAMILY = [
    tabard.Kin("Grug", race=1, char_class=1),
    tabard.Kin("Ugga", race=1, char_class=5),
    tabard.Kin("Grog", race=3, char_class=2),
    tabard.Kin("Bork", race=7, char_class=4),
    tabard.Kin("Og", race=1, char_class=8),
]
NAMES = [k.name for k in FAMILY]


class WhatEachMemberWants(unittest.TestCase):
    def test_every_member_wants_something_in_every_field(self):
        """A member with no opinion cannot be argued with."""
        for who in FAMILY:
            claim = tabard.claim(who)
            self.assertIsNotNone(claim, who.name)
            for field in tabard.FIELDS:
                self.assertIn(
                    field.name, claim.wants, f"{who.name} has no {field.name}"
                )

    def test_every_wanted_value_is_in_the_range_the_realm_has_evidence_for(self):
        """Out of range is not a rendering bug, it is an unreadable tabard the
        operator has to notice in-game. The ranges are measured, not assumed -
        see the module docstring."""
        for who in FAMILY:
            claim = tabard.claim(who)
            for field in tabard.FIELDS:
                value = claim.wants[field.name]
                self.assertGreaterEqual(value, field.low, f"{who.name}.{field.name}")
                self.assertLessEqual(value, field.high, f"{who.name}.{field.name}")

    def test_an_outsider_wants_nothing(self):
        """Only the family designs the family's tabard."""
        self.assertIsNone(tabard.claim(tabard.Kin("Thrall", race=2, char_class=7)))


class TheDebateConcludes(unittest.TestCase):
    """The risk the ticket names out loud: 'A tabard debate that never ends
    would be a very funny way to rediscover that bug.'"""

    def test_it_settles_every_field(self):
        out = tabard.debate(FAMILY)
        for field in tabard.FIELDS:
            self.assertIn(field.name, out.design.fields)

    def test_the_same_family_always_arrives_at_the_same_tabard(self):
        first = tabard.debate(FAMILY)
        second = tabard.debate(list(reversed(FAMILY)))
        self.assertEqual(
            first.design.fields, second.design.fields, "dict order changed the tabard"
        )

    def test_it_says_who_won_each_field(self):
        out = tabard.debate(FAMILY)
        for field in tabard.FIELDS:
            self.assertIn(out.design.won_by[field.name], NAMES)

    def test_more_than_one_member_gets_their_way(self):
        """Five characters and one winner is an announcement, which is the
        thing the council docstring exists to prevent."""
        out = tabard.debate(FAMILY)
        self.assertGreater(len(set(out.design.won_by.values())), 1)

    def test_the_transcript_is_an_argument_not_a_result(self):
        out = tabard.debate(FAMILY)
        speakers = {line.split(":", 1)[0] for line in out.lines}
        self.assertEqual(
            speakers & set(NAMES),
            set(NAMES),
            "somebody sat through the whole thing in silence",
        )

    def test_it_settles_out_loud(self):
        out = tabard.debate(FAMILY)
        self.assertTrue(out.lines[-1].startswith(bonds.head_of_family() + ":"))


class NobodyToArgueIsAnAnswer(unittest.TestCase):
    """`max()` over an empty list raises ValueError from the void: the debate
    would die, the bridge would log an exception, and the next cycle would do
    it again with nothing anywhere saying why."""

    def test_an_empty_family_is_reported_not_raised(self):
        out = tabard.debate([])
        self.assertEqual(out.lines, [])
        self.assertIsNone(out.design)
        self.assertTrue(out.reason)

    def test_a_roster_of_outsiders_is_the_same_answer(self):
        """A roster that has drifted out of bonds.FAMILY reads as empty here,
        because claim() refuses everyone in it."""
        out = tabard.debate([tabard.Kin("Thrall", race=2, char_class=7)])
        self.assertIsNone(out.design)

    def test_one_member_alone_still_reaches_a_tabard(self):
        """The other edge. One voice is a poor argument but it is not a
        failure, and every field still has to be settled."""
        out = tabard.debate(FAMILY[:1])
        self.assertIsNotNone(out.design)
        for field in tabard.FIELDS:
            self.assertIn(field.name, out.design.fields)


class TheSceneReadsLikeFiveCharacters(unittest.TestCase):
    """bonds.py keeps a persona per member because "the register is shared, so
    this is what stops five characters saying one sentence - which is exactly
    what happened when the personas differed only in role". A single template
    here would have rebuilt that bug one layer down, where the LLM pass cannot
    fix it: what persona.build_prompt is handed IS this line."""

    def test_no_two_members_open_the_same_way(self):
        openings = [tabard.claim(k).said.split(":")[0] for k in FAMILY]
        self.assertEqual(
            len(set(openings)),
            len(FAMILY),
            f"five characters, {len(set(openings))} voices: {openings}",
        )

    def test_nobody_says_a_database_column_out_loud(self):
        """The ticket has them arguing about "border style and colours". A
        character saying "EmblemColor" in party chat is reading a schema to
        his family."""
        said = "\n".join(tabard.debate(FAMILY).lines)
        for field in tabard.FIELDS:
            self.assertNotIn(
                field.name, said, f"{field.name} is a column name, not a word"
            )

    def test_the_numbers_stay_out_of_the_transcript(self):
        """They are palette indices. Said aloud they mean nothing, and this
        module is explicit that it cannot know what any of them look like."""
        out = tabard.debate(FAMILY)
        for value in out.design.fields.values():
            self.assertNotIn(f" {value}", out.lines[-1])


class TheLayersAgreeOnWhatNoTabardMeans(unittest.TestCase):
    """The bridge reads "every emblem column is zero" as "no tabard yet", and
    the module's C++ parser accepts `tabard 0 0 0 0 0` as a legal design. Those
    two only coexist while the debate cannot PRODUCE all zeros - otherwise a
    family could agree on a tabard that reads, forever, as not having one."""

    def test_the_debate_can_never_produce_all_zeros(self):
        self.assertGreaterEqual(
            min(f.low for f in tabard.FIELDS if f.name == "BackgroundColor"),
            1,
            "a floor of 0 on every field would let the debate agree on a "
            "tabard the bridge would read as absent, and restage it forever",
        )
        out = tabard.debate(FAMILY)
        self.assertTrue(any(out.design.fields.values()))


class WhoCanActuallyApplyIt(unittest.TestCase):
    """AzerothCore's Guild::HandleSetEmblem refuses anyone but the guild
    leader and charges EMBLEM_PRICE. Both are the server's rules, not ours,
    so the module reports them rather than discovering them in-game."""

    def test_the_command_is_addressed_to_the_guild_master(self):
        out = tabard.debate(FAMILY)
        self.assertEqual(out.design.applied_by, bonds.head_of_family())

    def test_the_price_is_the_servers_price(self):
        self.assertEqual(tabard.EMBLEM_PRICE, 10 * 10000)

    def test_a_leader_who_cannot_pay_is_refused_before_the_command_is_sent(self):
        out = tabard.debate(FAMILY)
        self.assertFalse(out.design.affordable(tabard.EMBLEM_PRICE - 1))
        self.assertTrue(out.design.affordable(tabard.EMBLEM_PRICE))

    def test_the_command_is_the_verb_the_module_reads(self):
        out = tabard.debate(FAMILY)
        parts = out.design.command().split()
        self.assertEqual(parts[0], "tabard")
        self.assertEqual(len(parts), 1 + len(tabard.FIELDS))
        for raw in parts[1:]:
            int(raw)


if __name__ == "__main__":
    unittest.main()


class TheGuardAsksWhetherItHappenedNotWhetherWeTried(unittest.TestCase):
    """A CONTRACT OVER SOURCE TEXT, the same shape as test_headless_bridge:
    bridge.py imports `discord` and `pymysql` at module level and this suite
    is stdlib-only with no pip install, so it cannot be imported here.

    What it guards is a distinction that cost a live rollout. The first guard
    asked "is there a tabard command row", i.e. did we TRY. On 2026-09-12 the
    bridge - which deploys on merge in seconds, while the module it talks to
    needs a full image build, so the two halves of one feature land 15-20
    minutes apart - held the debate into a worldserver that was still
    rolling. All eleven lines and the guild row came back `target not
    online`. Nothing reached the world, and the guard would still have said
    "asked" and suppressed the scene permanently; a row had to be deleted by
    hand. A pod swap is not rare, so this has to be self-healing.
    """

    def _guard(self):
        start = BRIDGE.index("def _tabard_already_held(")
        end = BRIDGE.index("\ndef ", start + 10)
        return BRIDGE[start:end]

    def test_it_counts_only_lines_that_were_delivered(self):
        """`delivered` is the status a chat row reaches when a character
        actually said it; `error` is the one it reaches when nobody was there
        to hear. Counting both is what made a scene nobody heard look held."""
        guard = self._guard()
        self.assertIn(
            "'delivered'",
            guard,
            "the guard must require delivery, or an undelivered "
            "scene reads as an argument the family had",
        )
        self.assertIn("kind = 'chat'", guard)

    def test_it_no_longer_keys_on_the_command_row(self):
        """Whether the guild command was SENT says nothing about whether the
        family was heard, and it was the wrong question in both directions:
        it counted an unheard attempt, and it would also have counted a row
        issued by a person testing the verb by hand."""
        self.assertNotIn(
            "LIKE 'tabard %'", BRIDGE, "the guard is back on the command row"
        )

    def test_the_writer_and_the_guard_name_the_same_source(self):
        """Two literals would be one rename away from a guard that never
        matches the rows it guards - which fails OPEN, restaging the scene
        forever, and is exactly the bug this area keeps growing."""
        self.assertEqual(
            BRIDGE.count("TABARD_SOURCE"),
            4,
            "expected the constant at its definition, the guard, "
            "the speak rows and the guild row",
        )
        self.assertEqual(
            BRIDGE.count('"overseer:tabard"'),
            1,
            "the source string should be written once",
        )

    def test_the_loop_is_registered_in_both_lists(self):
        """setup_hook and the headless driver. A loop in only one runs only
        under Discord, and wow-dev runs headless."""
        self.assertEqual(BRIDGE.count("self._design_tabard,"), 2)


class TheSceneIsNotStagedToAnEmptyRoom(unittest.TestCase):
    """Source-text contract, same reason as the class above.

    Two failures share one cause, and the second is the expensive one.

    COST: voicing a line is an LLM call, so a scene nobody can hear is eleven
    of them per cycle, forever. Measured 2026-09-12: the family was offline
    five hours and the loop kept paying for a conversation into an empty room.

    A HALF-TOLD ARGUMENT: _tabard_already_held counts PARTIAL delivery as
    held, on purpose. So three members present means six lines land, the
    guard closes, and the family is stuck having had two thirds of an
    argument with no way to finish it. That is worse than the cost and it is
    not recoverable without deleting rows by hand.
    """

    def _once(self):
        """Code only.

        The WHY block above the gate NAMES `_in_character`, in order to
        explain what staging to an empty room costs - and the first version
        of the test below matched that comment and concluded the gate came
        after the call it precedes. A text match that cannot tell a warning
        about a call from the call itself is not a structural test; this is
        the same rule tests/test_bags.py states for the C++ side.
        """
        start = BRIDGE.index("async def _tabard_once(")
        end = BRIDGE.index("\n    async def ", start + 10)
        return re.sub(r"#[^\n]*", "", BRIDGE[start:end])

    def test_presence_is_checked_before_a_single_line_is_voiced(self):
        body = self._once()
        gate = body.index("_bot_held_names")
        voiced = body.index("_in_character")
        self.assertLess(
            gate,
            voiced,
            "presence must be settled before the LLM is asked for "
            "a line, or an empty room costs eleven calls a cycle",
        )

    def test_it_waits_for_everyone_not_just_for_anyone(self):
        """Partial presence is the half-told-argument case, so the gate is
        'all of them' and not 'some of them'."""
        body = self._once()
        self.assertIn("absent", body)
        self.assertIn(
            "if absent:",
            body,
            "the gate must refuse on ANY absentee; a truthiness "
            "check on the present set would stage to a half-empty "
            "room",
        )

    def test_it_reuses_the_existing_presence_rule(self):
        """_bot_held_names already carries the 60-second freshness window and
        the is_bot rule. A second copy would be a second answer to who is in
        the world, and they would drift."""
        self.assertIn("_bot_held_names, [k.name for k in kin]", BRIDGE)

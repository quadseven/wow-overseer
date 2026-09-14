"""The specialization catalogue, the 100% arithmetic and the crafting order.

FIVE THINGS THIS FILE IS FOR.

The first is the CATALOGUE, and it is the reason this file exists at all. Every
row in tradespec.SPECS is a claim about five columns of a live world database
and about two DBCs inside a running worldserver image, and not one of those can
be reached from CI. What CAN be checked is that the rows are internally
consistent in the ways the world guarantees: a grant is never its own
specialization, two specializations on one exclusive group are rivals of each
other, a rival group never spans two professions, and every skill id is one
this service already names. Every one of those catches a real typo class, and
the brief this was built from contained exactly such an error - it named
Grumnus Steelshaper as the Weaponsmith trainer when five columns of the world
database say Armorsmith.

The second is the OPERATOR'S INSTRUCTION. "I want Grug to be armor blacksmith" is
the one line in this feature that was not a choice, and a test is the only
thing that stops it being quietly refactored into one.

The third is the ARITHMETIC. A completion percentage is the number on this page
a reader would act on, and two of its parts have already been got wrong once
each during this change: the RANK a craft asks for (the DBC field that looks
like the gate is 1 for 439 of 439 tailoring abilities) and the SPELLBOOK's
answer for an auto-learned craft (which is "no" forever, for everybody). Both
are pinned below against the measurements that corrected them.

The fourth is the ORDER. The ladder is a list in an order, which is read as a
finding, and the rule it is in is printed above it: family first, then empty
slots, then the ones nothing can reach, each group by what it unlocks.

The fifth is the PAGE, held to the contract test_recap_tab established and
test_trades_tab already applies to the other half of this tab: every sentence a
reader sees arrives written from Python, because a sentence composed in
JavaScript is a judgement no Python test can reach.
"""
import json
import pathlib
import re
import unittest

import goals
import professions
import tradespec

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
MODULE = (HERE / "tradespec.py").read_text(encoding="utf-8")
CRAFTBOOK = json.loads((HERE / "craftbook.json").read_text(encoding="utf-8"))

BANNER = "// --- the hundred per cent, and who is first in line (infra#3507"
NEXT = "// --- where to go next (infra#3500)"
BLOCK = PAGE[PAGE.index(BANNER):PAGE.index(NEXT, PAGE.index(BANNER))]
SECTION = PAGE[PAGE.index('<section id="trades">'):]
SECTION = SECTION[:SECTION.index("</section>")]


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The helper test_trades_tab.py and test_dungeon_tab.py both carry, and for
    the same reason: a guard its own explanation can trip is a guard that gets
    weakened until it passes. Several assertions below name the words they
    forbid, and those words appear in the comments that explain them.
    """
    return "\n".join(line for line in block.splitlines()
                     if not line.lstrip().startswith("//"))


CODE = code(BLOCK)


class TheCatalogue(unittest.TestCase):
    """What the world guarantees about a specialization, asserted about a row."""

    def test_every_key_and_every_spell_is_unique(self):
        """Two rows sharing a spell id would silently merge in BY_SPELL and one
        of them would vanish from every count on the page."""
        self.assertEqual(len({s.key for s in tradespec.SPECS}),
                         len(tradespec.SPECS))
        self.assertEqual(len({s.spell for s in tradespec.SPECS}),
                         len(tradespec.SPECS))

    def test_a_grant_is_never_its_own_specialization(self):
        """THE MISTAKE THIS CATCHES IS THE ONE THE OFFSETS INVITE. The quest
        casts a LEARN spell and the thing it teaches is a different id with the
        SAME DISPLAY NAME: 9790 Armorsmith teaches 9788 Armorsmith. Writing the
        grant into `spell` would gate every Armorsmith craft on a spell no
        character ever holds, so the page would report twelve reachable crafts
        as permanently blocked."""
        for spec in tradespec.SPECS:
            if not spec.grant:
                continue
            self.assertNotEqual(spec.spell, spec.grant, spec.key)

    def test_no_grant_is_another_rows_specialization(self):
        """And the same confusion the other way round, across rows."""
        specs = {s.spell for s in tradespec.SPECS}
        for spec in tradespec.SPECS:
            if spec.grant:
                self.assertNotIn(spec.grant, specs, spec.key)

    def test_the_offsets_really_are_irregular(self):
        """THE REASON THE CATALOGUE CANNOT BE GENERATED FROM ONE PAIR, pinned so
        that a later reader does not "simplify" it into spell + 1. Measured off
        Spell.dbc: blacksmithing's grant is spec + 2, leatherworking's is
        spec + 1, and Goblin Engineering's is spec MINUS one."""
        offsets = {spec.grant - spec.spell for spec in tradespec.SPECS
                   if spec.grant}
        self.assertGreater(len(offsets), 1, offsets)
        self.assertIn(2, offsets)
        self.assertIn(-1, offsets)

    def test_a_rival_group_never_spans_two_professions(self):
        """An ExclusiveGroup is one profession's branch point. A group spanning
        two would make a blacksmith's choice close off a tailor's."""
        groups: dict = {}
        for spec in tradespec.SPECS:
            if spec.rival_group:
                groups.setdefault(spec.rival_group, set()).add(spec.skill)
        for group, skills in groups.items():
            self.assertEqual(len(skills), 1, (group, skills))

    def test_rivalry_is_symmetric(self):
        """If A locks B out then B locks A out, or the page tells one crafter
        their branch is still open after the other has shut it."""
        for spec in tradespec.SPECS:
            for rival in tradespec.rivals_of(spec):
                self.assertIn(spec, tradespec.rivals_of(rival),
                              (spec.key, rival.key))

    def test_nothing_is_its_own_rival(self):
        for spec in tradespec.SPECS:
            self.assertNotIn(spec, tradespec.rivals_of(spec), spec.key)

    def test_the_master_weapon_branches_are_rivals_of_nothing(self):
        """A weaponsmith goes ON to take one of these, so they sit beside
        Armorsmith and Weaponsmith without being an alternative to either.
        rival_group 0 is the world's own way of saying so, and a 0 matching
        another 0 would make all three lock each other out."""
        for key in ("swordsmith", "hammersmith", "axesmith"):
            self.assertEqual(tradespec.rivals_of(tradespec.BY_KEY[key]), ())

    def test_every_skill_is_one_this_service_already_names(self):
        """A skill id typed here and nowhere else would produce a card headed
        "skill 165" and would never join up with character_skills."""
        known = set(goals.SKILL_IDS.values())
        for spec in tradespec.SPECS:
            self.assertIn(spec.skill, known, spec.key)

    def test_an_unreachable_row_carries_its_evidence_and_no_grant(self):
        """"Nobody can take this" is the strongest claim on the page. It has to
        carry what was measured, and a row claiming it while also naming a
        grant spell would be contradicting itself."""
        for spec in tradespec.SPECS:
            if not spec.unreachable:
                continue
            self.assertEqual(spec.grant, 0, spec.key)
            self.assertIn("RewardSpell", spec.unreachable, spec.key)

    def test_a_reachable_row_names_a_grant_a_quest_and_an_npc(self):
        for spec in tradespec.SPECS:
            if spec.unreachable:
                continue
            self.assertTrue(spec.grant, spec.key)
            self.assertTrue(spec.quest, spec.key)
            self.assertTrue(spec.npc_name, spec.key)

    def test_the_armorsmith_row_is_the_one_the_measurement_corrected(self):
        """THE SPECIFIC ERROR THIS FEATURE WAS BUILT ON TOP OF. The brief said
        Grumnus Steelshaper is the Weaponsmith trainer. creature_template's own
        subname, both of quest 5283's creature rows, its RewardSpell, and
        Grumnus's trainer gate all say Armorsmith. Pinned by id so a later
        "correction" back to the remembered version fails here."""
        armor = tradespec.BY_KEY["armorsmith"]
        self.assertEqual((armor.npc, armor.npc_name, armor.quest, armor.grant,
                          armor.spell),
                         (5164, "Grumnus Steelshaper", 5283, 9790, 9788))
        weapon = tradespec.BY_KEY["weaponsmith"]
        self.assertEqual((weapon.npc, weapon.npc_name, weapon.quest,
                          weapon.grant, weapon.spell),
                         (11146, "Ironus Coldsteel", 5284, 9789, 9787))
        self.assertIn(weapon, tradespec.rivals_of(armor))


class TheFamilysChoices(unittest.TestCase):
    def test_grug_is_the_armorsmith_because_the_operator_said_so(self):
        """The one line in this feature that was not a choice."""
        self.assertEqual(tradespec.chosen_spec("Grug"),
                         tradespec.BY_KEY["armorsmith"])

    def test_every_slot_names_a_specialization_that_exists(self):
        for slot in tradespec.FAMILY_SLOTS:
            self.assertIn(slot.spec_key, tradespec.BY_KEY, slot.spec_key)

    def test_nobody_is_given_a_branch_of_a_trade_they_do_not_have(self):
        """THE CROSS-CHECK THAT CATCHES THE WHOLE CLASS OF ERROR. A
        specialization is a branch of a profession, so giving Bork a tailoring
        branch is not a bad choice, it is an impossible one - and it would read
        perfectly on the page, because the page prints whatever it is handed.
        professions.ROSTER is the family's own trade table and is the only
        thing that can answer it."""
        for slot in tradespec.FAMILY_SLOTS:
            spec = tradespec.BY_KEY[slot.spec_key]
            word = tradespec._skill_word(spec.skill)
            self.assertIn(word, professions.assigned(slot.holder),
                          (slot.holder, spec.label, word))

    def test_no_two_of_the_family_take_the_same_profession(self):
        """professions.ROSTER assigns each primary to exactly one person, so
        two slots on one profession would mean one of them was typed against
        the wrong name."""
        skills = [tradespec.BY_KEY[s.spec_key].skill
                  for s in tradespec.FAMILY_SLOTS]
        self.assertEqual(len(set(skills)), len(skills), skills)

    def test_the_family_never_takes_a_branch_nothing_can_reach(self):
        """Three of the blacksmithing branches have no route on this realm.
        Assigning one to a family member would put a goal on the page that can
        never be completed, under a heading that says first in line."""
        for slot in tradespec.FAMILY_SLOTS:
            self.assertEqual(tradespec.BY_KEY[slot.spec_key].unreachable, "",
                             slot.spec_key)

    def test_every_choice_carries_its_reasoning(self):
        """A choice with no reason beside it is a preference, and the page
        renders `why` directly. An empty one would render as a blank paragraph
        under a heading promising the reasoning."""
        for slot in tradespec.FAMILY_SLOTS:
            self.assertGreater(len(slot.why), 80, slot.spec_key)

    def test_borks_leatherworking_choice_is_argued_from_item_data(self):
        """THE ONE CHOICE THAT WENT AGAINST RECIPE COUNT, so the reasoning has
        to name what it went on instead. Dragonscale unlocks eight crafts and
        Elemental five; Bork is a rogue, Dragonscale's eight are all mail, and
        Elemental's five are the leather agility set. If somebody later
        "corrects" this to the branch with more recipes, the argument that it
        was measured has to go with it."""
        bork = tradespec.chosen_spec("Bork")
        self.assertEqual(bork.skill, goals.SKILL_IDS["leatherworking"])
        slot = next(s for s in tradespec.FAMILY_SLOTS
                    if s.spec_key == bork.key)
        for evidence in ("mail", "leather", "agility", "rogue"):
            self.assertIn(evidence, slot.why.lower(), evidence)

    def test_a_choice_worth_no_recipes_says_so_in_its_reasoning(self):
        """All three alchemy branches gate zero crafts on this realm. A slot
        sold as progress toward 100% when it moves that figure by nothing is
        the one thing this page must not do."""
        ugga = tradespec.chosen_spec("Ugga")
        slot = next(s for s in tradespec.FAMILY_SLOTS if s.spec_key == ugga.key)
        self.assertIn("no alchemy specialization gates a single craft",
                      slot.why)


class TheRankArithmetic(unittest.TestCase):
    """What a craft actually asks for, which the obvious DBC field is not."""

    def test_the_world_rank_wins_over_the_dbc_field(self):
        entry = ["Bolt of Linen Cloth", 1, 25, 1, 2996]
        self.assertEqual(tradespec.effective_rank(entry, 125), 125)

    def test_a_zero_world_rank_is_still_the_world_rank(self):
        """0 is a real answer - `trainer_spell.ReqSkillRank` is 0 for some
        mining rows - and `or` would have turned it into the fallback."""
        self.assertEqual(tradespec.effective_rank(["x", 1, 25, 0, 0], 0), 0)

    def test_the_fallback_is_the_higher_of_the_two_dbc_numbers(self):
        """THE MEASUREMENT THAT CORRECTED THIS. ReqSkillValue is 1 for 439 of
        439 tailoring abilities, so reading it alone concluded that a tailor at
        50 could learn 421 of them. The yellow value is always at or above the
        true learn rank, so falling back to it can only under-report."""
        self.assertEqual(tradespec.effective_rank(["x", 1, 25, 0, 0], None), 25)
        self.assertEqual(tradespec.effective_rank(["x", 200, 25, 0, 0], None),
                         200)

    def test_the_dbc_field_really_is_useless_on_its_own(self):
        """Pinned against the committed projection, so this argument stays true
        of the file rather than only of the sentence that describes it."""
        tailoring = CRAFTBOOK[str(goals.SKILL_IDS["tailoring"])]
        self.assertTrue(all(entry[1] <= 1 for entry in tailoring.values()))


class TheCraftStates(unittest.TestCase):
    def test_a_spell_in_the_book_is_known_however_high_its_rank(self):
        self.assertEqual(
            tradespec._craft_state(400, 0, 0, 1, frozenset({7}), 7, ()),
            tradespec.KNOWN)

    def test_an_auto_learned_craft_under_the_skill_is_counted_known(self):
        """THE RULE professions.py MEASURED AND THIS PAGE DEPENDS ON. An
        AcquireMethod 1 craft is never written to character_spell at all - 0 of
        457 tailors hold Bolt of Linen Cloth and one of the family was watched
        casting it - so asking the spellbook gets "no" forever. Counting that
        as missing would hold the completion figure down permanently."""
        self.assertEqual(
            tradespec._craft_state(50, tradespec.ACQUIRE_AUTOMATIC, 0, 75,
                                   frozenset(), 7, ()),
            tradespec.KNOWN)

    def test_an_auto_learned_craft_above_the_skill_is_not(self):
        self.assertEqual(
            tradespec._craft_state(200, tradespec.ACQUIRE_AUTOMATIC, 0, 75,
                                   frozenset(), 7, ()),
            tradespec.BLOCKED_SKILL)

    def test_a_trained_craft_under_the_skill_is_learnable_and_not_known(self):
        """The opposite rule for AcquireMethod 0, and the two must not be
        merged: an explicit grant PERSISTS, so the absence of a row is real and
        counting it as known would invent progress."""
        self.assertEqual(
            tradespec._craft_state(50, tradespec.ACQUIRE_TRAINED, 0, 75,
                                   frozenset(), 7, ()),
            tradespec.LEARNABLE)

    def test_a_craft_behind_an_unheld_branch_is_blocked_on_the_branch(self):
        armor = tradespec.BY_KEY["armorsmith"]
        self.assertEqual(
            tradespec._craft_state(1, 0, armor.spell, 450, frozenset(), 7, ()),
            tradespec.BLOCKED_SPEC)

    def test_holding_the_branch_lets_the_skill_decide_again(self):
        armor = tradespec.BY_KEY["armorsmith"]
        self.assertEqual(
            tradespec._craft_state(1, 0, armor.spell, 450, frozenset(), 7,
                                   (armor,)),
            tradespec.LEARNABLE)

    def test_a_craft_behind_a_branch_with_no_route_is_unreachable(self):
        """And it must NOT read as "behind a branch nobody took", because that
        one is answered by recruiting and this one is not answered at all."""
        sword = tradespec.BY_KEY["swordsmith"]
        self.assertEqual(
            tradespec._craft_state(1, 0, sword.spell, 450, frozenset(), 7, ()),
            tradespec.UNREACHABLE)

    def test_a_gate_this_catalogue_does_not_know_is_not_a_branch(self):
        """`ReqAbility1` also carries ordinary prerequisites - a rank-2 enchant
        requiring its rank-1. Reading one of those as a specialization would
        report a craft as blocked behind a branch that does not exist."""
        ranks, gates = tradespec.craft_facts(
            [{"SpellId": 7, "ReqSkillRank": 10, "ReqAbility1": 12345}])
        self.assertEqual(gates, {})
        self.assertEqual(ranks, {7: 10})


class TheCraftFacts(unittest.TestCase):
    def test_the_lowest_rank_of_several_rows_wins_in_either_order(self):
        """Rows are alternative routes to the same craft, so the cheapest is
        the gate. Taking the last row read would make the answer depend on the
        order the database happened to return.

        BOTH ORDERS ARE ASSERTED AND THE SECOND ONE IS THE TEST. A fixture
        listing the dearest first passes whether the code takes the lowest or
        the last, which is how this assertion first shipped catching nothing.
        """
        for rows in ([{"SpellId": 7, "ReqSkillRank": 260, "ReqAbility1": 0},
                      {"SpellId": 7, "ReqSkillRank": 250, "ReqAbility1": 0}],
                     [{"SpellId": 7, "ReqSkillRank": 250, "ReqAbility1": 0},
                      {"SpellId": 7, "ReqSkillRank": 260, "ReqAbility1": 0}]):
            ranks, _gates = tradespec.craft_facts(rows)
            self.assertEqual(ranks[7], 250, rows)

    def test_a_rank_of_zero_is_carried_through_as_a_rank(self):
        """0 IS A REAL ANSWER AND NOT A MISSING ONE. `trainer_spell` carries
        ReqSkillRank 0 on mining rows, and a falsy test here would drop it and
        send the craft to the DBC fallback - which is the yellow value, a
        couple of hundred points higher, so a craft anybody could learn would
        report as behind more skill."""
        ranks, _gates = tradespec.craft_facts(
            [{"SpellId": 7, "ReqSkillRank": 0, "ReqAbility1": 0}])
        self.assertEqual(ranks, {7: 0})
        self.assertEqual(tradespec.effective_rank(["x", 1, 300, 0, 0],
                                                  ranks.get(7)), 0)

    def test_a_row_with_no_rank_at_all_leaves_the_craft_to_the_fallback(self):
        """Distinct from the case above: None is "this table said nothing",
        and only then may the DBC number stand in."""
        ranks, _gates = tradespec.craft_facts(
            [{"SpellId": 7, "ReqAbility1": 0}])
        self.assertEqual(ranks, {})
        self.assertEqual(tradespec.effective_rank(["x", 1, 300, 0, 0],
                                                  ranks.get(7)), 300)

    def test_a_gate_from_a_recipe_item_counts_as_much_as_one_from_a_trainer(self):
        """THE BUG THIS EXISTS TO STOP, measured during the change that added
        it: the three tailoring branches gate NO trainer row on this realm, so
        a gate map built from trainer_spell alone reported all three as
        unlocking zero crafts."""
        spellfire = tradespec.BY_KEY["spellfire"]
        _ranks, gates = tradespec.craft_facts(
            [{"SpellId": 26752, "ReqSkillRank": 355,
              "ReqAbility1": spellfire.spell}])
        self.assertEqual(gates, {26752: spellfire.spell})


class ThePercentage(unittest.TestCase):
    def test_it_rounds_down(self):
        """99.6% reported as 100% is the one number on this page a reader would
        act on and be wrong about, on a feature whose whole point is finishing."""
        self.assertEqual(tradespec._percent(996, 1000), 99)

    def test_a_hundred_means_a_hundred(self):
        self.assertEqual(tradespec._percent(10, 10), 100)

    def test_nothing_known_is_zero_and_nothing_at_all_is_zero(self):
        self.assertEqual(tradespec._percent(0, 10), 0)
        self.assertEqual(tradespec._percent(0, 0), 0)

    def test_a_profession_nobody_holds_counts_nothing_as_known(self):
        """With no holder the honest reading is that every craft is behind
        somebody taking the trade, not that the guild knows none of them for
        some other reason."""
        done = tradespec.profession_completion(
            164, {"7": ["Big Black Mace", 1, 25, 0, 1]}, [], {}, {}, {})
        self.assertEqual(done["known"], 0)
        self.assertEqual(done["percent"], 0)
        self.assertIn("nobody holds", done["line"])

    def test_the_counts_add_up_to_the_total(self):
        """Every craft lands in exactly one state. A craft counted twice or
        dropped would move the denominator without moving the page."""
        crafts = {"1": ["a", 1, 25, 0, 0], "2": ["b", 1, 400, 0, 0],
                  "3": ["c", 1, 25, 1, 0]}
        done = tradespec.profession_completion(
            164, crafts, [{"who": "Grug", "value": 30, "max": 75, "level": 51}],
            {}, {}, {"Grug": {1}})
        self.assertEqual(sum(done["counts"].values()), len(crafts))
        self.assertEqual(done["total"], len(crafts))

    def test_a_zero_count_draws_no_chip(self):
        """Five chips on every row buries the two that matter, and "0 behind a
        branch nobody took" beside a profession with no branches sends a reader
        looking for something that is not there."""
        chips = tradespec._count_chips(
            {tradespec.KNOWN: 3, tradespec.LEARNABLE: 0,
             tradespec.BLOCKED_SKILL: 0, tradespec.BLOCKED_SPEC: 0,
             tradespec.UNREACHABLE: 0})
        self.assertEqual(len(chips), 1)
        self.assertIn("3", chips[0]["text"])

    def test_every_state_has_a_word_and_a_tone_for_both_vocabularies(self):
        """A state with no entry would raise a KeyError inside the poll and
        take the whole tab to its stale banner."""
        for state in tradespec.STATE_ORDER:
            self.assertIn(state, tradespec.STATE_WORDS, state)
            self.assertIn(state, tradespec.SPEC_WORDS, state)


class TheLadder(unittest.TestCase):
    """The cascading order the operator asked for."""

    def setUp(self):
        armor = tradespec.BY_KEY["armorsmith"]
        weapon = tradespec.BY_KEY["weaponsmith"]
        elemental = tradespec.BY_KEY["elemental"]
        # Three crafts behind Armorsmith, one behind Weaponsmith, none behind
        # anything else, so the order under test is one this fixture decides
        # rather than one the live world happens to produce.
        self.gates = {1: armor.spell, 2: armor.spell, 3: armor.spell,
                      4: weapon.spell, 5: elemental.spell}
        self.ladder = tradespec.hierarchy(self.gates)

    def test_the_family_comes_before_every_empty_slot(self):
        """FIRST DIBS, which is the operator's word for it. A backup rung above a
        family rung would read as the guild's crafter outranking the family's."""
        last_family = max(i for i, row in enumerate(self.ladder)
                          if row["family"])
        first_backup = min(i for i, row in enumerate(self.ladder)
                           if not row["family"])
        self.assertLess(last_family, first_backup)

    def test_a_family_rung_worth_less_still_outranks_a_backup_worth_more(self):
        """The rule is family-first and worth-second, in that order. Sorting on
        worth alone would put an empty slot nobody can fill above a branch one
        of the five is actually walking toward."""
        elemental = next(r for r in self.ladder if r["spec"] == "elemental")
        weapon = next(r for r in self.ladder if r["spec"] == "weaponsmith")
        self.assertEqual(elemental["unlocks"], 1)
        self.assertEqual(weapon["unlocks"], 1)
        self.assertLess(elemental["rank"], weapon["rank"])

    def test_within_the_family_the_biggest_unlock_is_first(self):
        family = [row for row in self.ladder if row["family"]]
        self.assertEqual(family[0]["spec"], "armorsmith")
        self.assertEqual(family[0]["unlocks"], 3)

    def test_the_ones_with_no_route_are_last(self):
        """No amount of recruiting fills those, so a reader scanning for
        something to act on should reach them only after everything actionable."""
        unreachable = [i for i, row in enumerate(self.ladder)
                       if not row["reachable"]]
        self.assertEqual(unreachable,
                         list(range(len(self.ladder) - len(unreachable),
                                    len(self.ladder))))

    def test_rank_is_dense_and_starts_at_one(self):
        self.assertEqual([row["rank"] for row in self.ladder],
                         list(range(1, len(self.ladder) + 1)))

    def test_no_specialization_appears_twice(self):
        keys = [row["spec"] for row in self.ladder]
        self.assertEqual(len(set(keys)), len(keys))

    def test_a_branch_the_family_took_is_never_also_a_backup_slot(self):
        """It would ask a person to recruit for a slot one of the five is
        already standing in."""
        taken = {slot.spec_key for slot in tradespec.FAMILY_SLOTS}
        for key in tradespec._BACKUP_KEYS:
            self.assertNotIn(key, taken, key)

    def test_every_backup_key_names_a_real_specialization(self):
        for key in tradespec._BACKUP_KEYS:
            self.assertIn(key, tradespec.BY_KEY, key)

    def test_the_ladder_covers_every_specialization_in_the_catalogue(self):
        """A branch in neither table is one nothing on the page ever mentions,
        and the crafts behind it would be counted blocked with no explanation
        anywhere of what would unblock them."""
        listed = {row["spec"] for row in self.ladder}
        self.assertEqual(listed, {spec.key for spec in tradespec.SPECS})

    def test_an_empty_slot_says_only_a_recruit_can_fill_it(self):
        weapon = next(r for r in self.ladder if r["spec"] == "weaponsmith")
        self.assertEqual(weapon["holder"], "")
        self.assertIn("recruited", weapon["line"])

    def test_an_empty_rung_worth_nothing_says_so_in_words_rather_than_a_zero(self):
        """"0 crafts" reads like a page that failed to count. The two call for
        opposite responses: one is a bug and the other is a slot nobody should
        spend a recruit on."""
        potion = next(r for r in self.ladder if r["spec"] == "potion")
        self.assertEqual(potion["unlocks"], 0)
        self.assertIn("not worth filling", potion["line"])

    def test_a_family_rung_worth_nothing_admits_it_instead_of_claiming_first_dibs(self):
        """THE HARDER HALF OF THE SAME RULE, and the one a test on the empty
        rung alone does not reach. Ugga's branch gates no craft on this realm,
        so "first in line for the 0 crafts behind it" would be selling a slot
        that moves the completion figure by nothing as progress toward it."""
        elixir = next(r for r in self.ladder if r["spec"] == "elixir")
        self.assertEqual(elixir["unlocks"], 0)
        self.assertTrue(elixir["family"])
        self.assertIn("unlocks no recipe at all", elixir["line"])
        self.assertNotIn("first in line", elixir["line"])

    def test_a_family_rung_that_is_worth_something_does_claim_first_dibs(self):
        """The control for the assertion above: without it, a sentence that
        never said first in line would pass both."""
        armor = next(r for r in self.ladder if r["spec"] == "armorsmith")
        self.assertIn("first in line", armor["line"])


class TheSpecStates(unittest.TestCase):
    def test_meeting_both_gates_is_ready_to_take(self):
        armor = tradespec.BY_KEY["armorsmith"]
        self.assertEqual(tradespec.spec_state(armor, 200, 40, ()),
                         tradespec.LEARNABLE)

    def test_short_on_either_gate_is_not(self):
        armor = tradespec.BY_KEY["armorsmith"]
        self.assertEqual(tradespec.spec_state(armor, 199, 40, ()),
                         tradespec.BLOCKED_SKILL)
        self.assertEqual(tradespec.spec_state(armor, 200, 39, ()),
                         tradespec.BLOCKED_SKILL)

    def test_a_held_rival_shuts_it_for_good(self):
        armor = tradespec.BY_KEY["armorsmith"]
        weapon = tradespec.BY_KEY["weaponsmith"]
        self.assertEqual(tradespec.spec_state(armor, 450, 80, (weapon,)),
                         tradespec.BLOCKED_SPEC)

    def test_holding_it_beats_every_other_answer(self):
        armor = tradespec.BY_KEY["armorsmith"]
        self.assertEqual(tradespec.spec_state(armor, 0, 1, (armor,)),
                         tradespec.KNOWN)

    def test_a_branch_with_no_route_says_so_however_good_the_character_is(self):
        """AND IT MUST NOT READ AS "not yet". A character at blacksmithing 450
        and level 80 meets every gate quest 5307 states, and the quest still
        rewards nothing: the three master weapon branches have no route on this
        realm at all. Reporting that as a skill problem would put eight crafts
        on a list of things more grinding fixes."""
        sword = tradespec.BY_KEY["swordsmith"]
        self.assertEqual(tradespec.spec_state(sword, 450, 80, ()),
                         tradespec.UNREACHABLE)
        self.assertEqual(tradespec.spec_state(sword, 0, 1, ()),
                         tradespec.UNREACHABLE)

    def test_a_branch_with_no_route_is_still_reported_as_held_if_held(self):
        """Somebody could have been granted it by hand. An observation always
        beats a claim about what the world data allows."""
        sword = tradespec.BY_KEY["swordsmith"]
        self.assertEqual(tradespec.spec_state(sword, 450, 80, (sword,)),
                         tradespec.KNOWN)

    def test_held_specs_reads_the_specialization_and_not_the_grant(self):
        """The grant is cast once by the quest and character_spell is not where
        it lands. Reading it would report every specialization as unheld
        forever."""
        armor = tradespec.BY_KEY["armorsmith"]
        self.assertEqual(tradespec.held_specs([armor.spell]), (armor,))
        self.assertEqual(tradespec.held_specs([armor.grant]), ())

    def test_a_trainer_on_another_map_is_named_as_a_refusal(self):
        """ResolveTravelTarget refuses a spawn on another map outright, so this
        is not a long walk. professions.py's BLOCKERS records that leaving it
        unmeasured misled an investigation."""
        armor = tradespec.BY_KEY["armorsmith"]
        self.assertEqual(armor.npc_map, 0)
        self.assertIn("refusal", tradespec.reach_line(armor, 1, "Grug"))
        self.assertEqual(tradespec.reach_line(armor, 0, "Grug"), "")

    def test_an_unknown_map_makes_no_claim_either_way(self):
        """0 is "this page did not read a map", and drawing a refusal from it
        would be inventing one."""
        armor = tradespec.BY_KEY["armorsmith"]
        self.assertEqual(tradespec.reach_line(armor, 0, "Grug"), "")


class TheWholeView(unittest.TestCase):
    """build_tradespec end to end, on rows shaped like the live reads."""

    def setUp(self):
        self.book = {"164": {"7": ["Big Black Mace", 1, 25, 0, 1],
                             "8": ["Breastplate of Kings", 1, 350, 0, 2]}}
        self.crafts = [
            {"SpellId": 7, "ReqSkillRank": 30, "ReqAbility1": 0},
            {"SpellId": 8, "ReqSkillRank": 350,
             "ReqAbility1": tradespec.BY_KEY["armorsmith"].spell},
        ]
        self.members = [{"name": "Grug", "level": 51, "map": 1}]
        self.skills = [{"name": "Grug", "skill": 164, "value": 30, "max": 75}]
        self.out = tradespec.build_tradespec(
            self.book, self.crafts, self.skills, [], self.members, ["Grug"])

    def test_it_counts_the_whole_book_and_not_only_what_was_read(self):
        black = self.out["professions"][0]
        self.assertEqual(black["total"], 2)
        self.assertEqual(black["counts"][tradespec.LEARNABLE], 1)
        self.assertEqual(black["counts"][tradespec.BLOCKED_SPEC], 1)

    def test_a_character_outside_the_roster_is_not_read(self):
        """The roster is the family, and a guild member's skills arriving here
        would put somebody nobody can steer at the top of a profession."""
        out = tradespec.build_tradespec(
            self.book, self.crafts,
            self.skills + [{"name": "Stranger", "skill": 164, "value": 400,
                            "max": 450}],
            [], self.members, ["Grug"])
        self.assertEqual(out["professions"][0]["holder"], "Grug")

    def test_an_absent_craftbook_says_so_rather_than_drawing_zeroes(self):
        """A row of 0% across fourteen professions is a claim somebody would
        act on, and it is what a container built without the file looks like."""
        out = tradespec.build_tradespec({}, [], [], [], [], [])
        self.assertEqual(out["professions"], [])
        self.assertIn("craftbook.json", out["empty_note"])

    def test_the_limit_and_the_grant_refusal_are_always_present(self):
        """Both are the honest half of this feature. A view that dropped them
        under some condition would be a view that sometimes overclaims."""
        for key in ("limit_line", "grant_line", "order", "basis"):
            self.assertTrue(self.out[key], key)

    def test_the_limit_names_the_roster_and_the_number_it_leaves_out(self):
        self.assertIn("overseer_roster", tradespec.STEERING_LIMIT)
        self.assertIn("RECRUITING TARGET", tradespec.STEERING_LIMIT)

    def test_the_basis_admits_which_half_of_the_count_is_not_observed(self):
        """An AcquireMethod 1 craft is COUNTED known, never seen to be known,
        and a reader taking a counted number for an observed one will act on
        it."""
        self.assertIn("COUNTED", self.out["basis"])
        self.assertIn("AcquireMethod", self.out["basis"])

    def test_a_missing_gate_read_is_admitted_and_not_reported_as_no_branches(self):
        out = tradespec.build_tradespec(
            self.book, [], self.skills, [], self.members, ["Grug"])
        self.assertIn("no ReqAbility1 rows", out["basis"])

    def test_the_load_of_an_absent_craftbook_is_an_empty_book(self):
        """A file a container was built without must thin this view, not take
        the map server down at import."""
        self.assertEqual(tradespec.load_craftbook("/no/such/dir"), {})


class TheCommittedProjection(unittest.TestCase):
    def test_it_covers_exactly_the_professions_this_service_names(self):
        """A skill in goals and not in the book is a profession whose
        completion is silently never reported; one in the book and not in goals
        renders as "skill 773"."""
        self.assertEqual({int(key) for key in CRAFTBOOK},
                         set(goals.SKILL_IDS.values()))

    def test_the_generator_scopes_itself_to_the_same_professions(self):
        """The tool deliberately does not import goals, so that an unrelated
        edit cannot re-scope every completion figure on the site. This is that
        check made explicit rather than assumed."""
        tool = (HERE / "tools" / "craftbook_from_dbc.py").read_text(
            encoding="utf-8")
        listed = {int(found) for found in
                  re.findall(r"^    (\d+): \"", tool, re.M)}
        self.assertEqual(listed, set(goals.SKILL_IDS.values()))

    def test_every_entry_has_the_five_fields_the_module_reads(self):
        for skill, crafts in CRAFTBOOK.items():
            for spell, entry in crafts.items():
                self.assertEqual(len(entry), 5, (skill, spell))
                self.assertTrue(entry[0], (skill, spell))
                self.assertIn(entry[3], (tradespec.ACQUIRE_TRAINED,
                                         tradespec.ACQUIRE_AUTOMATIC,
                                         tradespec.ACQUIRE_AUTOMATIC_AT_RANK),
                              (skill, spell))

    def test_the_rare_third_acquire_method_really_is_in_here(self):
        """EXACTLY ONE ROW IN THE WHOLE BOOK, which is precisely the shape of
        thing a rule written against "0 or 1" misses and a test written against
        today's data never catches. It is asserted to EXIST so that
        `is_automatic` stays a rule about "not trained" rather than a pair of
        literals somebody tidies back down to one."""
        methods = {entry[3] for crafts in CRAFTBOOK.values()
                   for entry in crafts.values()}
        self.assertIn(tradespec.ACQUIRE_AUTOMATIC_AT_RANK, methods)
        self.assertTrue(tradespec.is_automatic(
            tradespec.ACQUIRE_AUTOMATIC_AT_RANK))
        self.assertTrue(tradespec.is_automatic(tradespec.ACQUIRE_AUTOMATIC))
        self.assertFalse(tradespec.is_automatic(tradespec.ACQUIRE_TRAINED))

    def test_the_anchor_the_generator_asserts_is_in_the_output(self):
        """If the parse had slipped a field this row would be something else,
        and the whole file would be plausible nonsense."""
        self.assertEqual(
            CRAFTBOOK[str(goals.SKILL_IDS["tailoring"])]["2963"],
            ["Bolt of Linen Cloth", 1, 25, 1, 2996])

    def test_every_specialization_the_catalogue_names_gates_a_real_skill_line(self):
        for spec in tradespec.SPECS:
            self.assertIn(str(spec.skill), CRAFTBOOK, spec.key)


class ThePageDecidesNothing(unittest.TestCase):
    """Every sentence arrives written, the contract test_recap_tab set."""

    def test_the_four_paragraphs_are_printed_and_not_composed(self):
        for printed in ("g.line", "g.order", "g.limit_line", "g.grant_line",
                        "g.basis"):
            self.assertIn(printed, CODE, printed)

    def test_the_headline_stands_down_for_the_empty_note(self):
        """A completion figure describes a measurement, so it must not stand
        over one that could not be made."""
        self.assertIn("g.empty_note || g.line", CODE)

    def test_no_sentence_about_a_branch_is_built_here(self):
        for invented in ('"crafts"', '"recipes"', '" of "', '"behind"',
                         '"nobody"', '"backup"', '"Armorsmith"',
                         'row.unlocks +', 'row.holder +'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_counts_are_the_modules_and_not_a_length(self):
        for counted in ("g.professions.length", "g.hierarchy.length",
                        "g.specs.length", "row.counts"):
            self.assertNotIn(counted, CODE, counted)

    def test_the_place_in_the_order_is_the_modules_and_not_a_loop_index(self):
        """The page would agree with it today and disagree the first time this
        list was filtered, with nothing failing."""
        self.assertIn('el("span", "gcr-rank", String(row.rank))', CODE)
        self.assertNotIn("index + 1", CODE)

    def test_the_reason_a_person_was_chosen_is_the_modules(self):
        self.assertIn("row.why", CODE)

    def test_the_only_number_it_turns_into_anything_is_the_percent(self):
        """The bar's fill is the module's own rounded-down figure. A width
        worked out here from the counts would be a second opinion about it."""
        self.assertIn('fill.style.width = row.percent + "%"', CODE)
        self.assertNotIn("row.known /", CODE)
        self.assertNotIn("row.total", CODE)

    def test_the_chips_reuse_the_one_tone_mapping_on_this_tab(self):
        """Two mappings would be two chances to disagree about what "no"
        means, on one tab."""
        self.assertIn("gcrChips", CODE)
        self.assertNotIn("chip.tone ===", CODE)

    def test_an_older_server_with_no_goal_draws_nothing_rather_than_blanks(self):
        """This tab is served by two deployments that are promoted separately.
        Blanking four paragraphs would make an old server look like a family
        with no professions and no plan."""
        self.assertIn("if (!g) return;", CODE)


class TheMarkup(unittest.TestCase):
    def test_every_element_the_render_writes_into_exists(self):
        for element in ('id="gclgoal"', 'id="gclbars"', 'id="gclspecs"',
                        'id="gclorder"', 'id="gcllimit"', 'id="gclladder"',
                        'id="gclgrant"', 'id="gclbasis"'):
            self.assertIn(element, SECTION, element)

    def test_the_completion_figure_is_above_everything_it_explains(self):
        """It is the answer to the question the whole tab was asked, and a
        reader who has scrolled past sixteen ladder rungs has stopped looking
        for it."""
        self.assertLess(SECTION.index('id="gclgoal"'),
                        SECTION.index('id="gclladder"'))
        self.assertLess(SECTION.index('id="gclgoal"'),
                        SECTION.index('id="gcrlist"'))

    def test_the_limit_sits_above_the_ladder_and_not_below_it(self):
        """A ladder of sixteen rungs where eleven are empty slots reads as work
        in progress until the sentence saying nothing can fill them, and a
        reader who stops early takes it for a plan."""
        self.assertLess(SECTION.index('id="gcllimit"'),
                        SECTION.index('id="gclladder"'))

    def test_the_basis_sits_below_the_ladder_it_describes(self):
        self.assertGreater(SECTION.index('id="gclbasis"'),
                           SECTION.index('id="gclladder"'))

    def test_the_rules_are_numbered_without_a_gap_or_a_repeat(self):
        """Five blocks now stand where two did. A duplicated index reads as two
        parts of one section and a missing one reads as a section that failed
        to render."""
        found = re.findall(r'<span class="ix">(\d+)</span>', SECTION)
        self.assertEqual(found, ["01", "02", "03", "04", "05"])


class TheMobileRules(unittest.TestCase):
    """The page is read on a phone. Nothing scrolls sideways."""

    CSS_BANNER = "  #gclgoal, #gclorder, #gcllimit, #gclgrant, #gclbasis"
    CSS = PAGE[PAGE.index(CSS_BANNER):
               PAGE.index("  .gcr-body {", PAGE.index(CSS_BANNER))]

    def test_nothing_in_the_new_styles_sets_a_width_in_pixels(self):
        """Including the progress bar, whose fill is a percentage of its own
        row so that it is the same shape on a phone and on a desk."""
        self.assertIsNone(re.search(r"width:\s*\d+px", self.CSS))

    def test_both_new_grids_cannot_be_pushed_wider_than_their_column(self):
        """A grid column defaults to min-content, so a long profession name
        would widen the row and take the page sideways with it. Named rule by
        rule rather than counted: this window also holds the trade card's own
        grid, so a count would pass on the strength of somebody else's rule."""
        for rule in (".gcl-row", ".gcl-card > summary"):
            block = self.CSS[self.CSS.index(rule + " {"):]
            block = block[:block.index("}")]
            self.assertIn("minmax(0, 1fr)", block, rule)

    def test_long_names_break_rather_than_scroll(self):
        for rule in (".gcl-name", ".gcl-why", ".gcl-label", ".gcl-sum",
                     ".gcl-reason"):
            block = self.CSS[self.CSS.index(rule + " {"):]
            block = block[:block.index("}")]
            self.assertIn("overflow-wrap:anywhere", block, rule)

    def test_the_new_cards_hide_their_marker_in_both_engines(self):
        """Safari draws its own triangle from a pseudo-element list-style does
        not reach."""
        self.assertIn(".gcl-card > summary { list-style:none", self.CSS)
        self.assertIn(".gcl-card > summary::-webkit-details-marker", self.CSS)

    def test_the_new_cards_can_be_reached_from_a_keyboard(self):
        self.assertIn(".gcl-card > summary:focus-visible", self.CSS)

    def test_the_block_declares_no_breakpoint_of_its_own(self):
        """Mobile first: one column at every width, so a media query here would
        be a second opinion about what small means."""
        self.assertNotIn("@media", self.CSS)


class TheEndpoint(unittest.TestCase):
    def test_the_craft_facts_read_unions_both_tables(self):
        """THE BUG THIS EXISTS TO STOP. The three tailoring branches gate no
        trainer row, so reading trainer_spell alone reported all three as
        unlocking nothing."""
        block = SERVER[SERVER.index("_TRADE_CRAFT_FACTS = ("):]
        block = block[:block.index(")\n")]
        self.assertIn("trainer_spell", block)
        self.assertIn("item_template", block)
        self.assertIn("ReqAbility1", block)
        self.assertIn("RequiredSpell", block)
        self.assertIn("ReqSkillRank", block)
        self.assertIn("RequiredSkillRank", block)

    def test_it_is_deduplicated_rather_than_unioned_all(self):
        """One craft sold by nine trainers at the same rank is one row."""
        block = SERVER[SERVER.index("_TRADE_CRAFT_FACTS = ("):]
        block = block[:block.index(")\n")]
        self.assertIn("UNION ", block)
        self.assertNotIn("UNION ALL", block)

    def test_the_read_is_guarded_like_every_other_one_on_this_endpoint(self):
        """production lacks tables dev has, and an unguarded read here is a 503
        on the live realm for a feature it has nothing to do with."""
        fetch = SERVER[SERVER.index("def _fetch_guildcraft"):
                       SERVER.index("# --- which dungeon is worth running next")]
        self.assertIn("_TRADE_CRAFT_FACTS", fetch)
        self.assertNotIn("cur.execute", fetch)

    def test_the_craft_rows_are_lifted_out_before_the_splat(self):
        """They are not a build_guildcraft argument, and leaving them in the
        dict would be a TypeError on every poll."""
        handler = SERVER[SERVER.index("def _trades"):SERVER.index("def _dungeons")]
        self.assertIn('crafts = fetched.pop("craft_rows")', handler)
        self.assertIn("tradespec.build_tradespec(", handler)

    def test_the_map_is_read_for_the_reachability_sentence(self):
        """Which continent a character stands on is the difference between a
        long walk and a refusal."""
        self.assertIn("`map` FROM characters", SERVER)

    def test_the_book_is_loaded_once_at_import_like_the_other_three(self):
        self.assertIn("CRAFTBOOK = tradespec.load_craftbook(HERE)", SERVER)


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in ("tradespec.py", "index.html", "map_server.py",
                     "tools/craftbook_from_dbc.py",
                     "tests/test_tradespec.py"):
            self.assertNotIn(chr(0x2014),
                             (HERE / name).read_text(encoding="utf-8"), name)

    def test_the_page_reaches_no_new_outside_host(self):
        self.assertNotIn("http", BLOCK)

    def test_nothing_from_a_payload_is_parsed_as_markup(self):
        """Profession names and craft names come from the world database and
        from client files, and neither is trusted."""
        for parsed in ("innerHTML", "insertAdjacentHTML"):
            self.assertNotIn(parsed, BLOCK, parsed)

    def test_the_module_and_the_book_both_ship_in_the_image(self):
        """A module the page imports and the image does not carry is a 503 on
        a tab that was green in CI, and a book it does not carry is fourteen
        professions reported at 0%."""
        dockerfile = (HERE.parent.parent / "docker" / "wow-overseer"
                      / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("_shared/tradespec.py", dockerfile)
        self.assertIn("_shared/craftbook.json", dockerfile)

    def test_the_module_never_reaches_the_world_itself(self):
        """The same seam professions.plan and guildcraft.build_guildcraft keep:
        every observation is handed in, so this module cannot invent one."""
        for forbidden in ("pymysql", "cur.execute", "urllib", "requests"):
            self.assertNotIn(forbidden, MODULE, forbidden)


if __name__ == "__main__":
    unittest.main()

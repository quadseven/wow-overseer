"""Who is behind on quests, and whether they can still do anything about it.

Evan: all five should quest equally and nobody should fall behind. Live the
turn-ins were Og 17, Bork 13, Grug 13, Grog 3, Ugga 3, because the five hold
different quest logs.

The fixtures below are the real shape of that: real quest ids, real column
values, real class and race ids. Every trap the live data lays is pinned with
a test, because each one has a wrong answer that looks like a working feature:
AllowableRaces=1101 reads as "race locked" and is not, `characters.class`
reads as a bitmask and is not, a chain reads as a set and is not, and Bork's
Coldridge Valley rows read as "everyone else is behind" and are not.
"""

import unittest

import questbook


# The family, with the class and race IDs the characters table really stores.
# NOT bitmasks - that conversion is the point of half these tests.
GRUG = questbook.Member(
    name="Grug", class_id=1, race_id=1, level=12, zones=frozenset({12})
)
BORK = questbook.Member(
    name="Bork", class_id=4, race_id=3, level=11, zones=frozenset({12})
)
GROG = questbook.Member(
    name="Grog", class_id=2, race_id=3, level=10, zones=frozenset({12})
)
OG = questbook.Member(name="Og", class_id=8, race_id=7, level=10, zones=frozenset({12}))
UGGA = questbook.Member(
    name="Ugga", class_id=5, race_id=1, level=10, zones=frozenset({12})
)

# Elwynn Forest, where the family actually is; Coldridge Valley and Dun
# Morogh, where Bork's quest log thinks it is.
ELWYNN = 12
COLDRIDGE = 132
DUN_MOROGH = 1


def _quest(qid, title="", **over):
    """A quest with the family's usual masks: no class lock, Alliance races."""
    fields = {
        "allowable_races": 1101,
        "zone": ELWYNN,
    }
    fields.update(over)
    return questbook.Quest(id=qid, title=title, **fields)


CATALOG = {
    q.id: q
    for q in [
        # Elwynn work the whole family can do.
        _quest(62, "A Threat Within"),
        _quest(40, "The Fargodeep Mine"),
        # The chain. 35 needs 40, 37 needs 35 - so catching up is ORDERED.
        _quest(35, "Further Concerns", prev_quest_id=40),
        _quest(37, "Find the Lost Guards", prev_quest_id=35),
        # Class-locked, verified live: 1 is warrior, 16 is priest.
        _quest(1638, "A Warrior's Training", allowable_classes=1),
        _quest(5624, "Garments of the Light", allowable_classes=16),
        # Too high for the three level-10s.
        _quest(76, "The Jasperlode Mine", min_level=11),
        # Bork's dwarf starting-zone dead weight, a continent away.
        _quest(218, "The Stolen Journal", zone=COLDRIDGE),
        _quest(234, "Coldridge Valley Mail Delivery", zone=COLDRIDGE),
        _quest(400, "Tools for Steelgrill", zone=COLDRIDGE),
        _quest(3361, "A Refugee's Quandary", zone=DUN_MOROGH),
    ]
}

# The lopsided state: three of them have run the Elwynn chain, two have not,
# and Bork is carrying four quests he will never hand in.
AHEAD = frozenset({62, 40, 35, 37})
FAMILY = [
    questbook.Member(**{**GRUG.__dict__, "rewarded": AHEAD | {1638}}),
    questbook.Member(
        **{**BORK.__dict__, "rewarded": AHEAD, "held": frozenset({218, 234, 400, 3361})}
    ),
    questbook.Member(**{**OG.__dict__, "rewarded": AHEAD}),
    questbook.Member(**{**GROG.__dict__, "held": frozenset({37})}),
    questbook.Member(**{**UGGA.__dict__, "held": frozenset({35})}),
]
BY_NAME = {m.name: m for m in FAMILY}


class BitmaskTest(unittest.TestCase):
    """`characters.class` is a class ID; AllowableClasses is a bitmask."""

    def test_class_id_is_not_the_class_bit(self):
        # Rogue is id 4 and bit 8; priest is id 5 and bit 16. If these were
        # ever equal the conversion would not be worth a function.
        self.assertEqual(questbook.class_bit(4), 8)
        self.assertEqual(questbook.class_bit(5), 16)
        self.assertEqual(questbook.class_bit(8), 128)
        self.assertNotEqual(questbook.class_bit(4), 4)

    def test_every_class_bit_is_one_shifted_by_the_id(self):
        for class_id, bit in questbook.CLASS_BIT.items():
            self.assertEqual(bit, 1 << (class_id - 1), class_id)

    def test_race_ids_convert_the_same_way(self):
        self.assertEqual(questbook.race_bit(1), 1)  # human
        self.assertEqual(questbook.race_bit(3), 4)  # dwarf
        self.assertEqual(questbook.race_bit(7), 64)  # gnome
        self.assertEqual(questbook.race_bit(11), 1024)  # draenei

    def test_a_rogue_quest_admits_the_rogue_and_not_the_mage(self):
        """The bug the conversion exists to stop.

        AllowableClasses=8 is rogue. Og the mage has class_id 8, so comparing
        the raw id against the mask lets him in - and it looks like it works.
        """
        rogue_only = _quest(9999, "Rogue Business", allowable_classes=8)
        self.assertTrue(questbook.eligible(BORK, rogue_only))
        self.assertFalse(questbook.eligible(OG, rogue_only))

    def test_an_unknown_class_id_has_no_bit(self):
        self.assertEqual(questbook.class_bit(10), 0)


class AllianceMaskTest(unittest.TestCase):
    """AllowableRaces=1101 is on all 41 held rows and restricts nobody."""

    def test_1101_is_exactly_the_alliance_races(self):
        self.assertEqual(questbook.ALLIANCE_MASK, 1101)

    def test_the_alliance_mask_shuts_out_nobody_in_this_family(self):
        q = _quest(62, "A Threat Within", allowable_races=1101)
        self.assertEqual(questbook.restricted_for(q, FAMILY), ())

    def test_every_member_is_eligible_despite_a_non_zero_race_mask(self):
        """Counting non-zero AllowableRaces as a restriction would report all
        41 held quests race-locked, which is wrong in every single case."""
        q = _quest(9989, "Anywhere In Elwynn", allowable_races=1101)
        for m in (GRUG, BORK, GROG, OG, UGGA):
            self.assertTrue(questbook.eligible(m, q), m.name)

    def test_a_mask_that_really_does_exclude_says_who(self):
        human_only = _quest(9998, "Human Business", allowable_races=1)
        self.assertEqual(
            questbook.restricted_for(human_only, FAMILY), ("Bork", "Grog", "Og")
        )

    def test_zero_means_no_restriction_not_nobody(self):
        """39 of the family's 41 held quests have AllowableClasses=0."""
        self.assertTrue(questbook.mask_allows(0, 1))
        self.assertTrue(questbook.mask_allows(0, 1024))
        open_to_all = _quest(9997, "Anyone", allowable_classes=0, allowable_races=0)
        self.assertEqual(len(questbook.participants(open_to_all, FAMILY)), 5)


class EligibilityTest(unittest.TestCase):
    def test_a_warrior_quest_is_grug_and_only_grug(self):
        q = CATALOG[1638]
        self.assertTrue(questbook.eligible(GRUG, q))
        for m in (BORK, GROG, OG, UGGA):
            self.assertFalse(questbook.eligible(m, q), m.name)
        self.assertIn(questbook.CLASS, questbook.blockers(OG, q))

    def test_a_priest_quest_is_ugga_and_only_ugga(self):
        q = CATALOG[5624]
        self.assertTrue(questbook.eligible(UGGA, q))
        self.assertFalse(questbook.eligible(GRUG, q))

    def test_min_level_keeps_the_level_tens_out(self):
        q = CATALOG[76]
        self.assertTrue(questbook.eligible(BORK, q))
        self.assertEqual(questbook.blockers(GROG, q), (questbook.TOO_LOW,))

    def test_max_level_zero_is_no_cap(self):
        q = _quest(9996, "No Cap", max_level=0)
        self.assertTrue(questbook.eligible(GRUG, q))

    def test_max_level_shuts_out_whoever_outgrew_it(self):
        q = _quest(9995, "Stale", max_level=11)
        self.assertEqual(questbook.blockers(GRUG, q), (questbook.TOO_HIGH,))
        self.assertTrue(questbook.eligible(BORK, q))

    def test_a_rewarded_quest_is_not_eligible_again(self):
        self.assertIn(questbook.DONE, questbook.blockers(BY_NAME["Grug"], CATALOG[62]))

    def test_blockers_reports_all_of_them_at_once(self):
        q = _quest(9994, "Hard", allowable_classes=1, min_level=40, prev_quest_id=62)
        self.assertEqual(
            questbook.blockers(UGGA, q),
            (questbook.CLASS, questbook.PREREQUISITE, questbook.TOO_LOW),
        )


class PrerequisiteTest(unittest.TestCase):
    def test_a_positive_prev_quest_needs_it_rewarded(self):
        self.assertEqual(
            questbook.blockers(GROG, CATALOG[35]), (questbook.PREREQUISITE,)
        )
        done40 = questbook.Member(**{**GROG.__dict__, "rewarded": frozenset({40})})
        self.assertTrue(questbook.eligible(done40, CATALOG[35]))

    def test_holding_the_prev_quest_is_not_the_same_as_finishing_it(self):
        """Only a turn-in satisfies a positive PrevQuestID."""
        holding = questbook.Member(**{**GROG.__dict__, "held": frozenset({40})})
        self.assertFalse(questbook.eligible(holding, CATALOG[35]))

    def test_a_negative_prev_quest_accepts_it_merely_being_in_the_log(self):
        q = _quest(9993, "Optional Follow-up", prev_quest_id=-40)
        holding = questbook.Member(**{**GROG.__dict__, "held": frozenset({40})})
        self.assertTrue(questbook.eligible(holding, q))
        self.assertFalse(questbook.eligible(GROG, q))


class ExclusiveGroupTest(unittest.TestCase):
    def test_a_positive_group_locks_out_the_siblings(self):
        """AC's SatisfyQuestExclusiveGroup: pick one of these, lose the rest."""
        catalog = {
            1: _quest(1, "Left", exclusive_group=77),
            2: _quest(2, "Right", exclusive_group=77),
        }
        took_left = questbook.Member(**{**GROG.__dict__, "rewarded": frozenset({1})})
        self.assertEqual(
            questbook.blockers(took_left, catalog[2], catalog=catalog),
            (questbook.EXCLUSIVE,),
        )

    def test_merely_holding_a_sibling_already_locks_the_others(self):
        catalog = {
            1: _quest(1, "Left", exclusive_group=77),
            2: _quest(2, "Right", exclusive_group=77),
        }
        holding = questbook.Member(**{**GROG.__dict__, "held": frozenset({1})})
        self.assertFalse(questbook.eligible(holding, catalog[2], catalog=catalog))

    def test_a_negative_group_is_deliberately_not_a_blocker(self):
        """AC returns true immediately for ExclusiveGroup <= 0; the negative
        form is the 'any one of these prior quests' case and lives in the
        prev-quest logic, not in availability. Handling only the case we are
        sure of is the documented choice - see _exclusive_blocks."""
        catalog = {
            1: _quest(1, "Left", exclusive_group=-77),
            2: _quest(2, "Right", exclusive_group=-77),
        }
        took_left = questbook.Member(**{**GROG.__dict__, "rewarded": frozenset({1})})
        self.assertTrue(questbook.eligible(took_left, catalog[2], catalog=catalog))

    def test_without_a_catalog_no_group_can_be_checked(self):
        q = _quest(2, "Right", exclusive_group=77)
        self.assertTrue(questbook.eligible(GROG, q))


class SharedAndPersonalTest(unittest.TestCase):
    def test_the_family_quests_are_the_ones_everyone_can_reach(self):
        ids = [q.id for q in questbook.shared_quests(FAMILY, CATALOG)]
        self.assertEqual(ids, [35, 37, 40, 62])

    def test_a_chain_quest_is_still_a_family_quest(self):
        """Grog is a step behind on 35, not excluded from it. Judging shared
        on today's eligibility would drop the whole chain out of the ledger."""
        self.assertFalse(questbook.eligible(GROG, CATALOG[35]))
        self.assertTrue(questbook.reachable(GROG, CATALOG[35]))
        self.assertIn(35, [q.id for q in questbook.shared_quests(FAMILY, CATALOG)])

    def test_class_locked_quests_belong_to_exactly_one_character(self):
        owners = {q.id: who for q, who in questbook.personal_quests(FAMILY, CATALOG)}
        self.assertEqual(owners[1638], "Grug")
        self.assertEqual(owners[5624], "Ugga")

    def test_a_personal_quest_is_never_shared(self):
        shared = {q.id for q in questbook.shared_quests(FAMILY, CATALOG)}
        self.assertNotIn(1638, shared)
        self.assertNotIn(5624, shared)

    def test_a_quest_only_some_can_reach_is_neither(self):
        """76 is open to Grug and Bork on level. Two out of five is not the
        family's quest and is not one character's either."""
        shared = {q.id for q in questbook.shared_quests(FAMILY, CATALOG)}
        personal = {q.id for q, _ in questbook.personal_quests(FAMILY, CATALOG)}
        self.assertNotIn(76, shared)
        self.assertNotIn(76, personal)

    def test_results_come_back_in_quest_id_order(self):
        ids = [q.id for q in questbook.shared_quests(FAMILY, CATALOG)]
        self.assertEqual(ids, sorted(ids))


class BehindTest(unittest.TestCase):
    def test_the_two_who_are_behind_are_the_two_evan_named(self):
        counts = {m.name: len(questbook.behind(m, FAMILY, CATALOG)) for m in FAMILY}
        self.assertEqual(counts["Grug"], 0)
        self.assertEqual(counts["Bork"], 0)
        self.assertEqual(counts["Og"], 0)
        self.assertEqual(counts["Grog"], 2)
        self.assertEqual(counts["Ugga"], 2)

    def test_behind_is_only_what_they_can_take_today(self):
        """35 and 37 are missed too, but 40 has to happen first, so they are
        not 'behind' - they are behind a door. See catch_up_plan."""
        ids = [q.id for q in questbook.behind(BY_NAME["Grog"], FAMILY, CATALOG)]
        self.assertEqual(ids, [40, 62])

    def test_nobody_is_behind_on_a_class_locked_quest(self):
        """Grug is the only one who can ever do 1638. Four characters
        permanently behind on it would be a metric nobody could act on."""
        for name in ("Bork", "Grog", "Og", "Ugga"):
            ids = [q.id for q in questbook.behind(BY_NAME[name], FAMILY, CATALOG)]
            self.assertNotIn(1638, ids)

    def test_borks_dead_weight_makes_nobody_behind(self):
        """The whole point. Bork alone holds the Coldridge set; if that read
        as 'Bork is ahead' the other four would be marched to Dun Morogh."""
        for m in FAMILY:
            ids = [q.id for q in questbook.behind(m, FAMILY, CATALOG)]
            self.assertEqual([i for i in ids if i in (218, 234, 400, 3361)], [])

    def test_work_nobody_has_done_yet_is_not_a_gap(self):
        """Behind means somebody else already turned it in."""
        fresh = _quest(9992, "Untouched")
        catalog = {**CATALOG, 9992: fresh}
        ids = [q.id for q in questbook.behind(BY_NAME["Grog"], FAMILY, catalog)]
        self.assertNotIn(9992, ids)


class UnreachableTest(unittest.TestCase):
    def test_borks_coldridge_set_is_reported_as_stalled(self):
        stalls = questbook.unreachable(BY_NAME["Bork"], CATALOG)
        self.assertEqual([s.quest_id for s in stalls], [218, 234, 400, 3361])
        for s in stalls:
            self.assertEqual(s.reason, questbook.ELSEWHERE)

    def test_a_stalled_quest_is_never_also_behind(self):
        stalled = {
            s.quest_id for m in FAMILY for s in questbook.unreachable(m, CATALOG)
        }
        missed = {q.id for m in FAMILY for q in questbook.behind(m, FAMILY, CATALOG)}
        self.assertEqual(stalled & missed, set())

    def test_being_a_step_down_a_chain_is_not_a_stall(self):
        """Grog holds 37 with 35 undone. That is homework, not rubbish -
        telling him to drop it would break the chain he is on."""
        self.assertEqual(questbook.unreachable(BY_NAME["Grog"], CATALOG), ())
        self.assertEqual(questbook.unreachable(BY_NAME["Ugga"], CATALOG), ())

    def test_a_chain_hanging_off_something_out_of_reach_is_a_stall(self):
        catalog = dict(CATALOG)
        catalog[9991] = _quest(9991, "Follow-up", prev_quest_id=218)
        bork = questbook.Member(
            **{**BY_NAME["Bork"].__dict__, "held": frozenset({9991})}
        )
        stalls = questbook.unreachable(bork, catalog)
        self.assertEqual(
            [(s.quest_id, s.reason) for s in stalls], [(9991, questbook.PREREQUISITE)]
        )

    def test_an_unknown_zone_never_stalls_anything(self):
        """Unknown facts stay quiet. A false 'drop it' costs real work."""
        nowhere = questbook.Member(**{**BY_NAME["Bork"].__dict__, "zones": frozenset()})
        self.assertEqual(questbook.unreachable(nowhere, CATALOG), ())

    def test_a_held_quest_the_catalog_does_not_know_is_skipped(self):
        odd = questbook.Member(**{**GROG.__dict__, "held": frozenset({424242})})
        self.assertEqual(questbook.unreachable(odd, CATALOG), ())


class CatchUpPlanTest(unittest.TestCase):
    def test_the_chain_comes_out_in_an_order_that_works(self):
        """35 before 37, always. You cannot hand someone 37 first."""
        ids = [q.id for q in questbook.catch_up_plan(BY_NAME["Grog"], FAMILY, CATALOG)]
        self.assertEqual(ids, [40, 35, 37, 62])
        self.assertLess(ids.index(35), ids.index(37))
        self.assertLess(ids.index(40), ids.index(35))

    def test_the_plan_covers_everything_they_missed(self):
        ids = {q.id for q in questbook.catch_up_plan(BY_NAME["Ugga"], FAMILY, CATALOG)}
        self.assertEqual(ids, {35, 37, 40, 62})

    def test_somebody_who_is_not_behind_has_nothing_to_do(self):
        self.assertEqual(questbook.catch_up_plan(BY_NAME["Og"], FAMILY, CATALOG), ())

    def test_the_plan_never_contains_a_stalled_quest(self):
        for m in FAMILY:
            ids = {q.id for q in questbook.catch_up_plan(m, FAMILY, CATALOG)}
            self.assertEqual(ids & {218, 234, 400, 3361}, set())

    def test_the_same_facts_always_produce_the_same_plan(self):
        """A council that reversed itself on identical facts would be noise."""
        first = questbook.catch_up_plan(BY_NAME["Grog"], FAMILY, CATALOG)
        second = questbook.catch_up_plan(BY_NAME["Grog"], FAMILY, CATALOG)
        self.assertEqual(first, second)

    def test_a_chain_step_nobody_finished_is_still_scheduled(self):
        """The prerequisite is pulled in even though nobody would call it
        'missed' - a plan without it is a plan that cannot be followed."""
        catalog = dict(CATALOG)
        catalog[9990] = _quest(9990, "Deep Step", prev_quest_id=37)
        family = [
            questbook.Member(**{**m.__dict__, "rewarded": m.rewarded | {9990}})
            if m.name in ("Grug", "Bork", "Og")
            else m
            for m in FAMILY
        ]
        ids = [q.id for q in questbook.catch_up_plan(BY_NAME["Grog"], family, catalog)]
        self.assertEqual(ids[-1], 9990)
        self.assertLess(ids.index(37), ids.index(9990))


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.ledger = questbook.build(FAMILY, CATALOG)

    def test_the_ledger_names_who_needs_help_most(self):
        # Grog and Ugga are level with each other; the tie breaks on name so
        # the answer does not wander between ticks.
        self.assertEqual(self.ledger.furthest_behind, "Grog")

    def test_the_ledger_carries_the_turn_in_counts(self):
        self.assertEqual(self.ledger.rewarded_counts["Grog"], 0)
        self.assertEqual(self.ledger.rewarded_counts["Grug"], 5)

    def test_every_member_appears_in_every_map(self):
        names = {m.name for m in FAMILY}
        for field in (
            self.ledger.behind,
            self.ledger.stalled,
            self.ledger.plans,
            self.ledger.rewarded_counts,
        ):
            self.assertEqual(set(field), names)

    def test_the_ledger_agrees_with_the_functions_it_is_built_from(self):
        self.assertEqual(
            self.ledger.behind["Grog"],
            questbook.behind(BY_NAME["Grog"], FAMILY, CATALOG),
        )
        self.assertEqual(
            self.ledger.stalled["Bork"], questbook.unreachable(BY_NAME["Bork"], CATALOG)
        )

    def test_an_empty_ledger_names_nobody(self):
        self.assertEqual(questbook.Ledger().furthest_behind, "")


class SayTest(unittest.TestCase):
    def setUp(self):
        self.ledger = questbook.build(FAMILY, CATALOG)

    def test_it_says_how_far_behind_and_what_comes_next(self):
        line = questbook.say(self.ledger, "Grog")
        self.assertIn("Grog is behind on 2 quests", line)
        # Next is the first step of the plan, not the first thing missed.
        self.assertIn("The Fargodeep Mine", line)

    def test_it_tells_bork_to_drop_the_dead_weight(self):
        line = questbook.say(self.ledger, "Bork")
        self.assertIn("should drop 4 quests", line)
        self.assertIn("Coldridge Valley Mail Delivery", line)

    def test_somebody_with_nothing_wrong_gets_a_plain_sentence(self):
        self.assertEqual(
            questbook.say(self.ledger, "Og"),
            "Og is not behind on anything we can help with.",
        )

    def test_an_unknown_name_does_not_raise(self):
        self.assertIn("Nobody", questbook.say(self.ledger, "Nobody"))


class FromRowTest(unittest.TestCase):
    """The verified column spellings live in exactly one place."""

    def test_a_joined_row_becomes_a_quest(self):
        q = questbook.Quest.from_row(
            {
                "ID": 1638,
                "LogTitle": "A Warrior's Training",
                "QuestLevel": 10,
                "MinLevel": 10,
                "AllowableRaces": 1101,
                "MaxLevel": 0,
                "AllowableClasses": 1,
                "PrevQuestID": 0,
                "NextQuestID": 1665,
                "ExclusiveGroup": 0,
            }
        )
        self.assertEqual(q.id, 1638)
        self.assertEqual(q.title, "A Warrior's Training")
        self.assertEqual(q.allowable_classes, 1)
        self.assertEqual(q.allowable_races, 1101)
        self.assertTrue(questbook.eligible(GRUG, q))
        self.assertFalse(questbook.eligible(UGGA, q))

    def test_null_columns_read_as_zero(self):
        q = questbook.Quest.from_row({"ID": 35, "LogTitle": None, "PrevQuestID": None})
        self.assertEqual(q.title, "")
        self.assertEqual(q.prev_quest_id, 0)
        self.assertEqual(q.max_level, 0)


class PurityTest(unittest.TestCase):
    def test_the_module_imports_nothing_that_talks_to_anything(self):
        """The seam the epic pinned: facts in, judgements out. A database
        handle in here would put the decision core behind a live server."""
        import ast
        import pathlib

        src = pathlib.Path(questbook.__file__).read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported - {"__future__", "dataclasses"}, set())


if __name__ == "__main__":
    unittest.main()

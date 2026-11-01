"""Who should be handed which quest, by whom, and in what order.

The live state this is written against, read off the server:

    name   level  quests_done
    Og       10       17
    Grug     14       13
    Bork     11       13
    Ugga     11        3
    Grog     10        3

Grog and Ugga stand three yards from the rest and kill the same mobs. They
have three turn-ins between them because they do not HOLD the quests those
kills count towards. The fix is to hand them the quests - and every way of
getting that wrong looks like working code, which is what this file pins:

  * handing over 1638 "A Warrior's Training" (AllowableClasses=1) or 5624
    "Garments of the Light" (16), which nobody but Grug and Ugga can ever
    take, and which must not count as anybody being behind either;
  * reading AllowableRaces=1101 as a restriction. It is the Alliance mask and
    all five are Alliance, so it restricts nobody - and it is on all 41 held
    rows, so a wrong reading refuses everything;
  * comparing `characters.class` (a class ID) against AllowableClasses (a
    bitmask). Og the mage has class id 8 and a rogue quest has mask 8;
  * handing somebody 37 "Find the Lost Guards" before 35 "Further Concerns";
  * marching the family to Dun Morogh because Bork is carrying four Coldridge
    Valley quests from the dwarf starting zone;
  * proposing a share the server will refuse, because the quest does not carry
    QUEST_FLAGS_SHARABLE and Player::CanShareQuest says no.
"""

import json
import unittest

import questbook
import questshare
import modsource


ELWYNN = 12
COLDRIDGE = 132
DUN_MOROGH = 1

# The family, with the class and race IDs the characters table really stores.
# NOT bitmasks - that conversion is the point of several tests below.
GRUG = questbook.Member(
    name="Grug", class_id=1, race_id=1, level=14, zones=frozenset({ELWYNN})
)
BORK = questbook.Member(
    name="Bork", class_id=4, race_id=3, level=11, zones=frozenset({ELWYNN})
)
GROG = questbook.Member(
    name="Grog", class_id=2, race_id=3, level=10, zones=frozenset({ELWYNN})
)
OG = questbook.Member(
    name="Og", class_id=8, race_id=7, level=10, zones=frozenset({ELWYNN})
)
UGGA = questbook.Member(
    name="Ugga", class_id=5, race_id=1, level=11, zones=frozenset({ELWYNN})
)


def _quest(qid, title="", **over):
    """A quest with the family's usual masks: Alliance races, sharable."""
    fields = {
        "allowable_races": 1101,
        "flags": questshare.QUEST_FLAGS_SHARABLE,
        "zone": ELWYNN,
    }
    fields.update(over)
    return questbook.Quest(id=qid, title=title, **fields)


CATALOG = {
    q.id: q
    for q in [
        _quest(62, "A Threat Within"),
        _quest(40, "The Fargodeep Mine"),
        # The chain. 35 needs 40, 37 needs 35 - so catching up is ORDERED.
        _quest(35, "Further Concerns", prev_quest_id=40),
        _quest(37, "Find the Lost Guards", prev_quest_id=35),
        # Class-locked, verified live: 1 is warrior, 16 is priest.
        _quest(1638, "A Warrior's Training", allowable_classes=1),
        _quest(5624, "Garments of the Light", allowable_classes=16),
        # Bork's dwarf starting-zone dead weight, a continent away.
        _quest(218, "The Stolen Journal", zone=COLDRIDGE),
        _quest(3361, "A Refugee's Quandary", zone=DUN_MOROGH),
        # A real Elwynn quest the server will not let anyone share.
        _quest(83, "Cloth and Leather Armor", flags=0),
    ]
}

# Elwynn work the whole family has already turned in, and the lopsided
# turn-in counts that are the reason this module exists: Og 17, Grug 13,
# Bork 13, Ugga 3, Grog 3. The ids past 62 are filler - nobody holds them and
# they are never candidates - but the COUNTS are the live ones, and they are
# what decides who the pass serves first.
AHEAD = frozenset({62, 40})
MANY = AHEAD | frozenset(range(100, 115))  # 17, Og
MOST = AHEAD | frozenset(range(100, 111))  # 13, Grug and Bork
FEW = AHEAD | frozenset({100})  # 3, Grog and Ugga

FAMILY = [
    # Grug carries the chain and his warrior-only quest.
    questbook.Member(
        **{**GRUG.__dict__, "rewarded": MOST, "held": frozenset({35, 37, 1638, 83})}
    ),
    questbook.Member(
        **{**BORK.__dict__, "rewarded": MOST, "held": frozenset({218, 3361})}
    ),
    questbook.Member(**{**OG.__dict__, "rewarded": MANY, "held": frozenset({35})}),
    # The two who are behind, holding almost nothing.
    questbook.Member(**{**GROG.__dict__, "rewarded": FEW, "held": frozenset()}),
    questbook.Member(**{**UGGA.__dict__, "rewarded": FEW, "held": frozenset({5624})}),
]
BY_NAME = {m.name: m for m in FAMILY}


def _grants_for(name, plan):
    return [g for g in plan.grants if g.taker == name]


def _ids_for(name, plan):
    return [g.quest_id for g in _grants_for(name, plan)]


def _reasons_for(name, quest_id, plan):
    return {
        r
        for ref in plan.refusals
        if ref.taker == name and ref.quest_id == quest_id
        for r in ref.reasons
    }


class TheLaggardsGetHandedTheWork(unittest.TestCase):
    """The whole point: a quest one of them holds reaches the others."""

    def test_grog_is_handed_the_chain_nobody_gave_him(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertIn(35, _ids_for("Grog", plan))

    def test_ugga_is_handed_it_too(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertIn(35, _ids_for("Ugga", plan))

    def test_the_holder_named_on_a_grant_really_holds_it(self):
        """A grant naming a holder who is not carrying the quest is a command
        the worldserver refuses at CanShareQuest and nothing else."""
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertTrue(plan.grants)
        for g in plan.grants:
            self.assertIn(g.quest_id, BY_NAME[g.holder].held, g)

    def test_nobody_shares_with_themselves(self):
        plan = questshare.plan(FAMILY, CATALOG)
        for g in plan.grants:
            self.assertNotEqual(g.holder, g.taker, g)

    def test_the_three_who_are_ahead_are_not_handed_what_they_carry(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertNotIn(35, _ids_for("Og", plan))

    def test_the_command_is_the_shape_the_module_parses(self):
        grant = questshare.Grant(holder="Og", taker="Ugga", quest_id=35)
        self.assertEqual(grant.command, "quest:35")


class ClassLocksAreNeverShared(unittest.TestCase):
    """1638 is warrior-only and 5624 is priest-only. Verified live."""

    def test_the_warrior_quest_reaches_nobody(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertEqual([g for g in plan.grants if g.quest_id == 1638], [])

    def test_the_priest_quest_reaches_nobody(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertEqual([g for g in plan.grants if g.quest_id == 5624], [])

    def test_the_refusal_says_class_and_not_something_vaguer(self):
        """An operator has to be able to tell 'never' from 'not yet'."""
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertIn(questbook.CLASS, _reasons_for("Ugga", 1638, plan))
        self.assertIn(questbook.CLASS, _reasons_for("Grug", 5624, plan))

    def test_a_class_lock_does_not_make_anyone_behind(self):
        """questbook already refuses to count these; the sharing pass must
        agree with it or the two halves would report different families."""
        ledger = questbook.build(FAMILY, CATALOG)
        for name in BY_NAME:
            self.assertNotIn(1638, [q.id for q in ledger.behind[name]])
            self.assertNotIn(5624, [q.id for q in ledger.behind[name]])


class TheAllianceMaskRestrictsNobody(unittest.TestCase):
    """AllowableRaces=1101 is on all 41 held rows and locks nobody out."""

    def test_the_mask_is_exactly_the_alliance_races(self):
        self.assertEqual(questbook.ALLIANCE_MASK, 1101)

    def test_a_quest_carrying_it_is_still_shared(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertEqual(CATALOG[35].allowable_races, 1101)
        self.assertTrue([g for g in plan.grants if g.quest_id == 35])

    def test_no_refusal_anywhere_blames_race(self):
        plan = questshare.plan(FAMILY, CATALOG)
        for ref in plan.refusals:
            self.assertNotIn(questbook.RACE, ref.reasons, ref)


class TheClassIdIsNotTheClassBit(unittest.TestCase):
    """Og the mage is class id 8; a rogue quest is mask 8. Comparing them
    directly admits the mage and reads as working code."""

    def test_a_rogue_quest_bork_holds_never_reaches_og(self):
        catalog = dict(CATALOG)
        catalog[9999] = _quest(9999, "Rogue Business", allowable_classes=8)
        family = [
            questbook.Member(
                **{
                    **m.__dict__,
                    "held": m.held | ({9999} if m.name == "Bork" else set()),
                }
            )
            for m in FAMILY
        ]
        plan = questshare.plan(family, catalog)
        self.assertEqual([g for g in plan.grants if g.quest_id == 9999], [])

    def test_and_a_mage_quest_never_reaches_the_rogue(self):
        catalog = dict(CATALOG)
        catalog[9998] = _quest(
            9998, "Mage Business", allowable_classes=questbook.CLASS_BIT[8]
        )
        family = [
            questbook.Member(
                **{**m.__dict__, "held": m.held | ({9998} if m.name == "Og" else set())}
            )
            for m in FAMILY
        ]
        plan = questshare.plan(family, catalog)
        self.assertEqual([g.taker for g in plan.grants if g.quest_id == 9998], [])


class PrerequisiteOrderIsRespected(unittest.TestCase):
    """Nobody is handed 37 "Find the Lost Guards" before 35 "Further
    Concerns" - and, because AzerothCore requires the PRIOR quest to be
    REWARDED and not merely held, that means 37 is not proposed at all while
    35 is undone. It becomes a grant on a later pass."""

    def test_grog_is_handed_35_and_not_37(self):
        plan = questshare.plan(FAMILY, CATALOG)
        ids = _ids_for("Grog", plan)
        self.assertIn(35, ids)
        self.assertNotIn(37, ids)

    def test_and_37_is_refused_for_the_reason_that_is_actually_true(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertEqual(_reasons_for("Grog", 37, plan), {questbook.PREREQUISITE})

    def test_37_becomes_a_grant_once_35_is_turned_in(self):
        """The chain moving forward, which is the half a single snapshot
        cannot show."""
        family = [
            questbook.Member(**{**m.__dict__, "rewarded": m.rewarded | {35}})
            if m.name == "Grog"
            else m
            for m in FAMILY
        ]
        plan = questshare.plan(family, CATALOG)
        self.assertIn(37, _ids_for("Grog", plan))

    def test_no_grant_anywhere_has_an_unrewarded_prerequisite(self):
        plan = questshare.plan(FAMILY, CATALOG)
        for grant in plan.grants:
            prev = CATALOG[grant.quest_id].prev_quest_id
            if prev <= 0:
                continue
            self.assertIn(prev, BY_NAME[grant.taker].rewarded, grant)

    def test_a_chain_whose_root_is_unreachable_is_not_scheduled(self):
        """40 is the root of the chain. A member who has not done it and
        cannot take it must not be handed 35 either."""
        catalog = dict(CATALOG)
        catalog[40] = _quest(40, "The Fargodeep Mine", min_level=60)
        family = [
            questbook.Member(**{**m.__dict__, "rewarded": m.rewarded - {40}})
            for m in FAMILY
        ]
        plan = questshare.plan(family, catalog)
        self.assertEqual([g for g in plan.grants if g.quest_id in (35, 37)], [])


class ColdridgeIsNotCatchingUp(unittest.TestCase):
    """Bork carries four quests from the dwarf starting zone, on another
    continent. Sharing them would march five characters to Dun Morogh."""

    def test_the_coldridge_quests_are_never_shared(self):
        plan = questshare.plan(FAMILY, CATALOG)
        for stale in (218, 3361):
            self.assertEqual([g for g in plan.grants if g.quest_id == stale], [])

    def test_the_refusal_names_the_zone_and_not_a_class_or_level(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertEqual(_reasons_for("Grog", 218, plan), {questbook.ELSEWHERE})

    def test_an_unknown_zone_never_blocks(self):
        """Zone 0 is 'we do not know', and a guess costs a character real
        work - the same rule questbook already follows."""
        catalog = dict(CATALOG)
        catalog[218] = _quest(218, "The Stolen Journal", zone=0)
        plan = questshare.plan(FAMILY, catalog)
        self.assertTrue([g for g in plan.grants if g.quest_id == 218])


class TheServerHasToAgreeItIsSharable(unittest.TestCase):
    """Player::CanShareQuest requires QUEST_FLAGS_SHARABLE (0x8)."""

    def test_the_bit_is_the_one_the_core_checks(self):
        self.assertEqual(questshare.QUEST_FLAGS_SHARABLE, 0x8)

    def test_a_quest_without_the_flag_is_never_proposed(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertEqual([g for g in plan.grants if g.quest_id == 83], [])

    def test_and_the_refusal_says_so_rather_than_going_quiet(self):
        """If it turns out the whole zone lacks the flag, that must be
        readable in one log line rather than looking like 'nothing to do'."""
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertIn(questshare.NOT_SHARABLE, _reasons_for("Grog", 83, plan))

    def test_flags_defaulting_to_zero_is_not_silently_sharable(self):
        bare = questbook.Quest(id=1)
        self.assertFalse(questshare.is_sharable(bare))

    def test_the_flag_is_read_off_the_column_the_server_uses(self):
        quest = questbook.Quest.from_row({"ID": 35, "Flags": 8})
        self.assertTrue(questshare.is_sharable(quest))


class NothingAlreadyOwnedIsProposed(unittest.TestCase):
    def test_a_quest_already_in_the_log_is_not_re_shared(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertEqual(
            [g for g in plan.grants if g.taker == "Grug" and g.quest_id == 35], []
        )

    def test_a_quest_already_turned_in_is_not_re_shared(self):
        catalog = dict(CATALOG)
        family = [
            questbook.Member(
                **{**m.__dict__, "held": m.held | ({62} if m.name == "Og" else set())}
            )
            for m in FAMILY
        ]
        plan = questshare.plan(family, catalog)
        # Everyone was rewarded 62 already.
        self.assertEqual([g for g in plan.grants if g.quest_id == 62], [])


class TheQuestLogHasTwentyFiveSlots(unittest.TestCase):
    def test_the_size_matches_the_core_constant(self):
        self.assertEqual(questshare.MAX_QUEST_LOG_SIZE, 25)

    def test_a_full_log_gets_no_grants_and_one_honest_refusal(self):
        full = frozenset(range(9000, 9025))
        family = [
            questbook.Member(**{**m.__dict__, "held": full}) if m.name == "Grog" else m
            for m in FAMILY
        ]
        plan = questshare.plan(family, CATALOG)
        self.assertEqual(_ids_for("Grog", plan), [])
        self.assertTrue(
            any(
                r.taker == "Grog" and questshare.LOG_FULL in r.reasons
                for r in plan.refusals
            )
        )

    def test_grants_never_exceed_the_room_left(self):
        held = frozenset(range(9000, 9023))  # 23 of 25 used
        family = [
            questbook.Member(**{**m.__dict__, "held": held}) if m.name == "Grog" else m
            for m in FAMILY
        ]
        plan = questshare.plan(family, CATALOG)
        self.assertLessEqual(len(_ids_for("Grog", plan)), 2)


class TheSamePlanTwiceIsTheSamePlan(unittest.TestCase):
    """The pass runs on a timer. A plan that reorders itself on identical
    facts would insert a different command every cycle forever."""

    def test_two_runs_agree(self):
        first = questshare.plan(FAMILY, CATALOG)
        second = questshare.plan(list(reversed(FAMILY)), dict(CATALOG))
        self.assertEqual(first.grants, second.grants)

    def test_the_holder_is_chosen_deterministically(self):
        """Two members hold 35; the same one must be named every time."""
        holders = questshare.holders(35, FAMILY)
        self.assertEqual(holders, ("Grug", "Og"))
        self.assertEqual(questshare.donor(35, FAMILY), "Grug")

    def test_the_furthest_behind_is_served_first(self):
        plan = questshare.plan(FAMILY, CATALOG)
        takers = []
        for g in plan.grants:
            if g.taker not in takers:
                takers.append(g.taker)
        self.assertEqual(takers[0], "Grog")


class ItSaysWhatItDid(unittest.TestCase):
    """'Nothing happened' and 'nothing to do' must never look alike."""

    def test_the_summary_counts_both_halves(self):
        plan = questshare.plan(FAMILY, CATALOG)
        line = questshare.say(plan)
        self.assertIn(str(len(plan.grants)), line)
        self.assertIn("refused", line)

    def test_an_empty_plan_still_says_why_it_is_empty(self):
        plan = questshare.plan(FAMILY, {})
        self.assertEqual(plan.grants, ())
        self.assertIn("0", questshare.say(plan))

    def test_every_refusal_carries_at_least_one_reason(self):
        plan = questshare.plan(FAMILY, CATALOG)
        self.assertTrue(plan.refusals)
        for ref in plan.refusals:
            self.assertTrue(ref.reasons, ref)

    def test_no_quest_appears_as_both_a_grant_and_a_refusal_for_one_taker(self):
        plan = questshare.plan(FAMILY, CATALOG)
        granted = {(g.taker, g.quest_id) for g in plan.grants}
        refused = {(r.taker, r.quest_id) for r in plan.refusals}
        self.assertEqual(granted & refused, set())


class TheLiveShapeConverges(unittest.TestCase):
    """Og 17 / Grug 13 / Bork 13 / Ugga 3 / Grog 3, the state on the server."""

    LIVE = [
        questbook.Member(
            **{
                **OG.__dict__,
                "rewarded": frozenset(range(100, 117)),
                "held": frozenset({35, 37}),
            }
        ),
        questbook.Member(
            **{
                **GRUG.__dict__,
                "rewarded": frozenset(range(100, 113)),
                "held": frozenset({35, 1638}),
            }
        ),
        questbook.Member(
            **{
                **BORK.__dict__,
                "rewarded": frozenset(range(100, 113)),
                "held": frozenset({218}),
            }
        ),
        questbook.Member(
            **{
                **UGGA.__dict__,
                "rewarded": frozenset(range(100, 103)),
                "held": frozenset({5624}),
            }
        ),
        questbook.Member(
            **{
                **GROG.__dict__,
                "rewarded": frozenset(range(100, 103)),
                "held": frozenset(),
            }
        ),
    ]
    CAT = dict(CATALOG)
    CAT.update({q.id: q for q in [_quest(i) for i in range(100, 117)]})
    # 40 is the chain root and everybody turned it in long ago.
    CAT[40] = _quest(40, "The Fargodeep Mine")

    def _live(self):
        members = [
            questbook.Member(**{**m.__dict__, "rewarded": m.rewarded | {40}})
            for m in self.LIVE
        ]
        return questshare.plan(members, self.CAT)

    def test_the_two_laggards_are_handed_work_and_the_leaders_are_not(self):
        plan = self._live()
        self.assertTrue(_ids_for("Grog", plan))
        self.assertTrue(_ids_for("Ugga", plan))
        self.assertEqual(_ids_for("Og", plan), [])

    def test_nobody_is_handed_a_class_quest_out_of_that_state(self):
        plan = self._live()
        for g in plan.grants:
            self.assertNotIn(g.quest_id, (1638, 5624), g)

    def test_and_bork_does_not_drag_coldridge_along(self):
        plan = self._live()
        self.assertEqual([g for g in plan.grants if g.quest_id == 218], [])


# Spark-authored: qwen3-coder-next:q8_0 on an on-prem DGX Spark, 2026-09-02, then
# moved here by hand after review so the decision runs under real tests.
class BackingOffIsForPermanentRefusalsOnly(unittest.TestCase):
    """infra#2892 was 167 identical share attempts at a quest the holder had
    at status 0. After a PERMANENT refusal the pass waits, and the wait
    doubles with each further refusal up to a cap. A taker who was offline
    or on the wrong map five times has told us nothing about the quest, so
    those rows must not count: Codex found the draft suppressed them for a
    day."""

    PERMANENT = json.dumps(
        {
            "outcome": "refused",
            "reason": "holder cannot share it (not held, or not flagged sharable)",
        }
    )
    TRANSIENT = json.dumps({"outcome": "refused", "reason": "taker offline"})
    KEY = ("Bork", "Aiyla", "share 1234")
    BASE, CAP = 60, 168  # the bridge's defaults: an hour, a week
    H = 3600

    def rows(self, result, ages_h, key=None, status="error"):
        holder, taker, command = key or self.KEY
        return [
            (holder, taker, command, status, result, age * self.H) for age in ages_h
        ]

    def delivered(self, ages_h, key=None):
        return self.rows(
            json.dumps({"outcome": "shared"}), ages_h, key, status="delivered"
        )

    def held(self, rows):
        return questshare.backed_off(rows, self.BASE, self.CAP)

    def test_one_permanent_refusal_holds_for_two_hours(self):
        self.assertEqual(
            self.held(self.rows(self.PERMANENT, [1])), frozenset({self.KEY})
        )
        self.assertEqual(self.held(self.rows(self.PERMANENT, [2])), frozenset())

    def test_the_wait_doubles_with_each_refusal(self):
        # five refusals: 2**5 hours = 32h of quiet, measured from the youngest
        ages = [31, 40, 50, 60, 70]
        self.assertEqual(
            self.held(self.rows(self.PERMANENT, ages)), frozenset({self.KEY})
        )
        ages = [32, 40, 50, 60, 70]
        self.assertEqual(self.held(self.rows(self.PERMANENT, ages)), frozenset())

    def test_the_wait_is_capped_at_a_week(self):
        ages = [167] + [200 + 10 * i for i in range(30)]
        self.assertEqual(
            self.held(self.rows(self.PERMANENT, ages)), frozenset({self.KEY})
        )
        ages = [168] + [200 + 10 * i for i in range(30)]
        self.assertEqual(self.held(self.rows(self.PERMANENT, ages)), frozenset())

    def test_an_unchanged_permanent_refusal_never_returns_to_hourly(self):
        """Codex's scenario against the rolling-window draft: five hourly
        failures, a 19h pause, then one retry per hour forever as rows age
        out. Drive the real loop - every hour, offer unless held, and every
        offer is refused - for ninety days and look at the gaps."""
        rows, offers = [], []
        for hour in range(90 * 24):
            rows = [(h, t, c, st, r, age + self.H) for h, t, c, st, r, age in rows]
            if self.KEY in self.held(rows):
                continue
            offers.append(hour)
            rows.append((*self.KEY, "error", self.PERMANENT, 0))
        gaps = [b - a for a, b in zip(offers, offers[1:], strict=False)]
        self.assertEqual(gaps[:7], [2, 4, 8, 16, 32, 64, 128])
        self.assertTrue(all(g == self.CAP for g in gaps[7:]), gaps)
        self.assertLess(len(offers), 20, offers)

    def test_a_delivered_share_resets_the_streak(self):
        """Codex's third finding: refusals, then the holder re-picks the
        quest and a share lands, then the taker abandons it and the same
        share is needed again. The delivery proved the old refusals are
        about a state that no longer exists; a fresh refusal after it is
        the first of a new streak, not the ninth of the old one."""
        old = self.rows(self.PERMANENT, [30, 40, 50, 60, 70, 80, 90, 100])
        landed = self.delivered([20])
        # nothing since the delivery: not held at all
        self.assertEqual(self.held(old + landed), frozenset())
        # one fresh refusal after it: a 2h wait, not the week eight would earn
        fresh = self.rows(self.PERMANENT, [1])
        self.assertEqual(self.held(old + landed + fresh), frozenset({self.KEY}))
        fresh = self.rows(self.PERMANENT, [2])
        self.assertEqual(self.held(old + landed + fresh), frozenset())

    def test_a_delivery_for_another_taker_resets_nothing(self):
        other = ("Bork", "Ilhan", "share 1234")
        # three refusals, youngest an hour old: an 8h wait, which Ilhan's
        # delivery has nothing to say about
        rows = self.rows(self.PERMANENT, [1, 40, 50]) + self.delivered([20], other)
        self.assertEqual(self.held(rows), frozenset({self.KEY}))
        rows = self.rows(self.PERMANENT, [1, 40, 50]) + self.delivered([20])
        self.assertEqual(
            self.held(rows), frozenset({self.KEY})
        )  # 1h < 2h: streak of one
        rows = self.rows(self.PERMANENT, [3, 40, 50]) + self.delivered([20])
        self.assertEqual(self.held(rows), frozenset())

    def test_transient_refusals_never_accumulate(self):
        self.assertEqual(self.held(self.rows(self.TRANSIENT, range(50))), frozenset())

    def test_transient_rows_do_not_lengthen_a_permanent_wait(self):
        rows = self.rows(self.PERMANENT, [3]) + self.rows(self.TRANSIENT, [0, 1, 2])
        self.assertEqual(self.held(rows), frozenset())

    def test_every_permanent_reason_counts(self):
        for reason in questshare.PERMANENT_REFUSALS:
            with self.subTest(reason=reason):
                rows = self.rows(json.dumps({"reason": reason}), [1])
                self.assertEqual(self.held(rows), frozenset({self.KEY}))

    def test_a_sweeper_timeout_has_no_result_and_counts_for_nothing(self):
        """The sweeper marks a stuck row status='error' with detail only and
        result NULL. The worldserver never spoke, so nothing was refused."""
        self.assertEqual(self.held(self.rows(None, range(9))), frozenset())

    def test_malformed_result_counts_for_nothing(self):
        rows = (
            self.rows("not json", [0]) + self.rows("[1, 2]", [0]) + self.rows("", [0])
        )
        self.assertEqual(self.held(rows), frozenset())

    def test_a_result_with_no_reason_counts_for_nothing(self):
        self.assertEqual(
            self.held(self.rows(json.dumps({"outcome": "refused"}), [0])), frozenset()
        )

    def test_triples_are_held_separately(self):
        other = ("Bork", "Ilhan", "share 1234")
        rows = self.rows(self.PERMANENT, [1]) + self.rows(self.PERMANENT, [5], other)
        self.assertEqual(self.held(rows), frozenset({self.KEY}))

    def test_no_rows_no_hold(self):
        self.assertEqual(self.held([]), frozenset())

    def refused(self, reason, ages_h, key=None):
        return self.rows(
            json.dumps({"outcome": "refused", "reason": reason}), ages_h, key
        )

    def test_a_later_gate_refusal_ends_an_earlier_permanent_streak(self):
        """Codex, round 5: five 'holder cannot share it' refusals, then the
        holder re-picks the quest and the next attempt is refused for 'not
        on the same map' - a gate the worldserver reaches only after
        CanShareQuest passed. The holder problem is over; when the party
        regroups the share must be offered within the hour, not held for
        the 32h the dead streak would have charged."""
        streak = self.refused(
            "holder cannot share it (not held, or not flagged sharable)",
            [4, 5, 6, 7, 8],
        )
        self.assertEqual(self.held(streak), frozenset({self.KEY}))
        for later in (
            "not in the same party",
            "not on the same map",
            "taker already holds it",
            "taker cannot take it in its current state",
            "taker quest log is full",
            # Not "taker is not eligible": since #170 it is permanent itself
            # and starts its own streak (pinned in the next test class).
            "no bag space for the quest starting item",
            "the quest did not land in the taker log",
        ):
            self.assertEqual(
                self.held(streak + self.refused(later, [1])), frozenset(), later
            )

    def test_an_earlier_gate_refusal_ends_nothing(self):
        """'taker offline' is tested BEFORE the holder is, so a taker who
        logged off says nothing about whether the holder can share now."""
        streak = self.refused(
            "holder cannot share it (not held, or not flagged sharable)",
            [4, 5, 6, 7, 8],
        )
        for earlier in ("taker offline", "no taker"):
            self.assertEqual(
                self.held(streak + self.refused(earlier, [1])),
                frozenset({self.KEY}),
                earlier,
            )

    def test_the_same_gate_refused_again_extends_the_streak(self):
        holder = "holder cannot share it (not held, or not flagged sharable)"
        self.assertEqual(
            self.held(self.refused(holder, [3, 5])), frozenset({self.KEY})
        )  # 4h
        self.assertEqual(self.held(self.refused(holder, [4, 5])), frozenset())

    def test_a_later_permanent_gate_starts_its_own_streak(self):
        """'taker already turned it in' comes after the holder gate: it ends
        the holder streak and begins a streak of one, so the wait is 2h from
        it, not 2**6 h from the six refusals together."""
        holder = "holder cannot share it (not held, or not flagged sharable)"
        rows = self.refused(holder, [3, 4, 5, 6, 7]) + self.refused(
            "taker already turned it in", [1]
        )
        self.assertEqual(self.held(rows), frozenset({self.KEY}))
        rows = self.refused(holder, [3, 4, 5, 6, 7]) + self.refused(
            "taker already turned it in", [2]
        )
        self.assertEqual(self.held(rows), frozenset())

    def test_recovery_then_a_transient_refusal_then_a_prompt_retry(self):
        """The whole round-5 scenario driven through the loop: the holder
        cannot share for two days (the streak reaches a 64h wait), the
        holder re-picks the quest, the next offer fails because the party
        is split, and the offer after THAT must come an hour later, not
        64h later."""
        holder = "holder cannot share it (not held, or not flagged sharable)"
        split = "not on the same map"
        rows, offers, hour = [], [], 0
        answer = holder
        while hour < 24 * 14:
            rows = [(h, t, c, st, r, age + self.H) for h, t, c, st, r, age in rows]
            if hour == 48:
                answer = split  # the holder has the quest again; the party is apart
            if self.KEY not in self.held(rows):
                offers.append((hour, answer))
                rows.append(
                    (
                        *self.KEY,
                        "error",
                        json.dumps({"outcome": "refused", "reason": answer}),
                        0,
                    )
                )
            hour += 1
        after = [h for h, a in offers if a == split]
        self.assertGreaterEqual(len(after), 2)
        self.assertEqual(after[1] - after[0], 1)
        self.assertTrue(all(b - a == 1 for a, b in zip(after, after[1:], strict=False)))

    def test_an_unknown_reason_proves_nothing_and_counts_for_nothing(self):
        streak = self.refused(
            "holder cannot share it (not held, or not flagged sharable)",
            [4, 5, 6, 7, 8],
        )
        self.assertEqual(
            self.held(streak + self.refused("a gate added next year", [1])),
            frozenset({self.KEY}),
        )
        self.assertEqual(
            self.held(self.refused("a gate added next year", [1])), frozenset()
        )

    def test_the_gate_order_is_the_worldservers(self):
        """SHARE_GATES is only right while it matches the order DoShare tests
        its gates in. Read the mod source (the submodule the gate command
        initialises) and compare the describe() literals, in order, with
        adjacent C++ string literals joined."""
        src = modsource.read(modsource.MODULE, encoding="utf-8")
        start = src.index("static char const* DoShare(")
        # DoShare's own closing brace, not a later function's name: the
        # module has grown other describe() callers between the two.
        body = src[start : src.index("\n    }\n", start)]
        found = _gate_literals(body)
        self.assertEqual(len(found), len(questshare.SHARE_GATES), found)
        for written, gate in zip(found, questshare.SHARE_GATES, strict=True):
            # Each gate lists every wording a worldserver has written for it,
            # old and new, so the pinned module's reasons must be among them.
            self.assertTrue(written, gate)
            self.assertLessEqual(set(written), set(gate), gate)
        known = {reason for gate in questshare.SHARE_GATES for reason in gate}
        self.assertTrue(questshare.PERMANENT_REFUSALS <= known)

    def test_history_depth_is_where_the_doubling_meets_the_cap(self):
        # 60 min * 2**8 = 256h >= 168h, and 2**7 = 128h is not
        self.assertEqual(questshare.history_depth(60, 168), 8)
        self.assertEqual(questshare.history_depth(60, 1), 1)
        self.assertEqual(questshare.history_depth(0, 168), 1)
        self.assertEqual(questshare.history_depth(60, 0), 1)

    def test_the_youngest_rows_per_answer_decide_identically(self):
        """What lets the bridge bound its read (Codex, round 5): keeping
        only the youngest history_depth() rows per (triple, status, reason)
        - what the SQL window does - must never change the decision. Random
        histories, dense with transient noise, compared full against
        truncated."""
        import random

        rng = random.Random(2892)
        depth = questshare.history_depth(self.BASE, self.CAP)
        outcomes = [
            ("error", json.dumps({"outcome": "refused", "reason": r}))
            for gate in questshare.SHARE_GATES
            for r in gate
        ]
        # the worldserver's own verdict (mod-overseer#1059), on a known gate
        # and on a wording this side has never seen
        outcomes += [
            ("error", json.dumps({"reason": r, "retryable": False}))
            for r in ("holder does not carry the quest", "taker offline", "reworded")
        ]
        outcomes += [
            ("delivered", json.dumps({"outcome": "shared"})),
            ("error", None),
            ("error", "{not json"),
        ]
        keys = [
            self.KEY,
            ("Bork", "Ilhan", "share 1234"),
            ("Aiyla", "Bork", "share 77"),
        ]
        disagreements = 0
        for _ in range(400):
            rows = []
            for key in keys:
                for _ in range(rng.randrange(0, 60)):
                    status, result = rng.choice(outcomes)
                    rows.append(
                        (*key, status, result, rng.randrange(0, 90 * 24 * self.H))
                    )
            rng.shuffle(rows)
            kept, seen = [], {}
            for row in sorted(rows, key=lambda r: r[5]):
                holder, taker, command, status, result, _age = row
                try:
                    reason = json.loads(result).get("reason") if result else None
                except (ValueError, AttributeError):
                    reason = None
                bucket = (holder, taker, command, status, reason)
                seen[bucket] = seen.get(bucket, 0) + 1
                if seen[bucket] <= depth:
                    kept.append(row)
            if self.held(rows) != self.held(kept):
                disagreements += 1
        self.assertEqual(disagreements, 0)

    def _recent_only(self, rows):
        """What the bridge's read keeps once it skips every triple with no
        answered row inside the cap (the SQL IN-subquery): the triple's whole
        history, or nothing."""
        recent = {r[:3] for r in rows if r[5] < self.CAP * self.H}
        return [r for r in rows if r[:3] in recent]

    def test_a_triple_with_nothing_inside_the_cap_is_never_held(self):
        # steady state at the cap: a refusal every week and an hour, eight
        # deep. The youngest is 3 days old, so the triple is held on the
        # strength of the OLD rows, which the recent filter keeps.
        ages = [3 * 24 + i * (7 * 24 + 1) for i in range(8)]
        rows = self.rows(self.PERMANENT, ages)
        self.assertEqual(self.held(rows), frozenset({self.KEY}))
        self.assertEqual(self.held(self._recent_only(rows)), frozenset({self.KEY}))
        # quiet-then-resume: seven refusals a month old, then a fresh one
        rows = self.rows(self.PERMANENT, [3] + [30 * 24 + i * 24 for i in range(7)])
        self.assertEqual(self.held(rows), frozenset({self.KEY}))
        self.assertEqual(self.held(self._recent_only(rows)), frozenset({self.KEY}))
        # the same streak with nothing inside the cap: not held either way,
        # and the filter drops the triple without changing that
        rows = self.rows(self.PERMANENT, [8 * 24 + i * 24 for i in range(8)])
        self.assertEqual(self.held(rows), frozenset())
        self.assertEqual(self._recent_only(rows), [])
        # the cut that would NOT be safe: windowing the history itself
        eight_days = [
            r for r in self.rows(self.PERMANENT, ages) if r[5] < 8 * 24 * self.H
        ]
        self.assertEqual(self.held(eight_days), frozenset())

    def test_skipping_triples_with_nothing_recent_decides_identically(self):
        """The bridge reads the full, depth-limited history only for triples
        with an answer younger than the cap. Random histories over ninety
        days, dense and sparse, with the cap-spaced and resumed streaks the
        doubling produces: the held set is identical read in full or read
        through the recent filter."""
        import random

        rng = random.Random(1664)
        outcomes = [
            ("error", json.dumps({"outcome": "refused", "reason": r}))
            for gate in questshare.SHARE_GATES
            for r in gate
        ]
        outcomes += [
            ("error", json.dumps({"reason": "reworded", "retryable": False})),
            ("delivered", json.dumps({"outcome": "shared"})),
            ("error", None),
            ("error", "{not json"),
        ]
        keys = [
            self.KEY,
            ("Bork", "Ilhan", "share 1234"),
            ("Aiyla", "Bork", "share 77"),
        ]
        disagreements = filtered = 0
        for _ in range(600):
            rows = []
            for key in keys:
                style = rng.choice(("dense", "sparse", "cap-spaced", "old"))
                for n in range(rng.randrange(0, 40)):
                    status, result = rng.choice(outcomes)
                    if style == "dense":
                        age = rng.randrange(0, 90 * 24 * self.H)
                    elif style == "sparse":
                        age = rng.randrange(0, 12 * 24 * self.H)
                    elif style == "cap-spaced":
                        age = (rng.randrange(0, 200) + n * 7 * 24) * self.H
                    else:
                        age = rng.randrange(6 * 24 * self.H, 90 * 24 * self.H)
                    rows.append((*key, status, result, age))
            kept = self._recent_only(rows)
            filtered += len(kept) < len(rows)
            if self.held(rows) != self.held(kept):
                disagreements += 1
        self.assertEqual(disagreements, 0)
        self.assertGreater(filtered, 50)  # the filter really dropped triples


def _gate_literals(body):
    """The reason literals of every describe() refusal in a DoShare body, in
    order, one tuple per gate. A gate passes its reason either inline (the
    adjacent C++ literals joined) or, since mod-overseer#1059, through a
    local picked by a ternary just above the call (`char const* reason =
    holderHasQuest ? "..." : "...";`), whose literals are that gate's
    possible reasons."""
    import re

    gates = []
    cursor = 0
    for call in re.finditer(
        r'describe\("(?:refused|error)",\s*((?:"[^"]*"\s*)+|\w+)', body
    ):
        arg = call.group(1)
        if arg.lstrip().startswith('"'):
            gates.append(("".join(re.findall(r'"([^"]*)"', arg)),))
        else:
            name = re.escape(arg.strip())
            window = body[cursor : call.start()]
            picks = re.findall(r"char const\*\s+" + name + r"\s*=([^;]*);", window)
            gates.append(tuple(re.findall(r'"([^"]*)"', picks[-1])) if picks else ())
        cursor = call.end()
    return gates


# The CanShareQuest gate as mod-overseer#1059 writes it, verbatim from the
# module the live worldserver runs (mod-overseer cc25b2f6). The submodule this
# suite reads is pinned older and still carries the single literal, so this
# copy is what proves the gate-order reader handles the shape that bump brings.
_SHARE_GATE_AFTER_1059 = """
        if (!holder->CanShareQuest(questId))
        {
            bool const holderHasQuest =
                holder->GetQuestStatus(questId) != QUEST_STATUS_NONE;
            char const* reason = holderHasQuest ? "quest is not sharable"
                                                : "holder does not carry the quest";
            describe("refused", reason, int32(taker->GetQuestStatus(questId)), false);
            return "holder is not carrying that quest or it is not sharable";
        }
        Group* group = holder->GetGroup();
        if (!group || !group->IsMember(taker->GetGUID()))
        {
            describe("refused", "not in the same party", int32(taker->GetQuestStatus(questId)));
            return "holder and taker are not in the same party";
        }
"""


class TheWorldserverCanSayARefusalIsFinal(unittest.TestCase):
    """mod-overseer#1059 (live since 2026-10-20) split the CanShareQuest
    refusal into "quest is not sharable" and "holder does not carry the
    quest", and marks it `"retryable":false`. The bridge matched refusals by
    their old wording only, so a reason it did not know counted for nothing
    and the hourly retry of a share that can never land came back - the
    shape of infra#2892 and mod-overseer#969. These rows are the module's own
    JSON, field for field."""

    KEY = ("Bork", "Grug", "quest:3361")
    BASE, CAP = 60, 168
    H = 3600

    @staticmethod
    def answer(reason, retryable=None, **extra):
        body = {"outcome": "refused", "reason": reason}
        if retryable is not None:
            body["retryable"] = retryable
        body.update(extra)
        return json.dumps(body)

    LIVE = (
        '{"outcome":"refused","reason":"holder does not carry the quest",'
        '"retryable":false,"from":"Bork","to":"Grug","quest_id":3361,'
        '"taker_status":0,"request":"quest:3361"}'
    )
    LIVE_NOT_SHARABLE = (
        '{"outcome":"refused","reason":"quest is not sharable",'
        '"retryable":false,"from":"Bork","to":"Grug","quest_id":3361,'
        '"taker_status":0,"request":"quest:3361"}'
    )

    def rows(self, result, ages_h, status="error"):
        return [(*self.KEY, status, result, age * self.H) for age in ages_h]

    def held(self, rows):
        return questshare.backed_off(rows, self.BASE, self.CAP)

    def test_the_live_holder_refusal_backs_off(self):
        for result in (self.LIVE, self.LIVE_NOT_SHARABLE):
            with self.subTest(result=result):
                self.assertEqual(
                    self.held(self.rows(result, [1])), frozenset({self.KEY})
                )
                self.assertEqual(self.held(self.rows(result, [2])), frozenset())

    def test_the_live_holder_refusal_never_returns_to_hourly(self):
        """The loop the bridge runs: offer every hour unless held, every offer
        answered with the live refusal. 2h, 4h, ... then a week, never an
        hourly retry."""
        rows, offers = [], []
        for hour in range(30 * 24):
            rows = [(h, t, c, st, r, age + self.H) for h, t, c, st, r, age in rows]
            if self.KEY in self.held(rows):
                continue
            offers.append(hour)
            rows.append((*self.KEY, "error", self.LIVE, 0))
        gaps = [b - a for a, b in zip(offers, offers[1:], strict=False)]
        self.assertEqual(gaps[:7], [2, 4, 8, 16, 32, 64, 128])
        self.assertLess(len(offers), 12, offers)

    def test_the_old_wording_still_backs_off_for_an_older_worldserver(self):
        old = self.answer("holder cannot share it (not held, or not flagged sharable)")
        self.assertEqual(self.held(self.rows(old, [1])), frozenset({self.KEY}))

    def test_the_two_new_wordings_are_one_gate(self):
        """Both come from the one CanShareQuest check, so the holder dropping
        the quest after it was found unsharable (or the other way round) is a
        streak of two, not a later gate ending the first."""
        rows = self.rows(self.LIVE, [3]) + self.rows(self.LIVE_NOT_SHARABLE, [5])
        self.assertEqual(self.held(rows), frozenset({self.KEY}))  # 4h wait
        rows = self.rows(self.LIVE_NOT_SHARABLE, [3]) + self.rows(self.LIVE, [5])
        self.assertEqual(self.held(rows), frozenset({self.KEY}))
        old = self.answer("holder cannot share it (not held, or not flagged sharable)")
        rows = self.rows(self.LIVE, [3]) + self.rows(old, [5])
        self.assertEqual(self.held(rows), frozenset({self.KEY}))

    def test_a_later_gate_still_ends_the_new_streak(self):
        streak = self.rows(self.LIVE, [4, 5, 6, 7, 8])
        later = self.rows(self.answer("not on the same map", True), [1])
        self.assertEqual(self.held(streak), frozenset({self.KEY}))
        self.assertEqual(self.held(streak + later), frozenset())

    def test_an_earlier_gate_still_ends_nothing(self):
        streak = self.rows(self.LIVE, [4, 5, 6, 7, 8])
        earlier = self.rows(self.answer("taker offline", True), [1])
        self.assertEqual(self.held(streak + earlier), frozenset({self.KEY}))

    def test_retryable_false_backs_off_whatever_the_wording(self):
        """The generic half: a future rewording of any refusal still carries
        the worldserver's own verdict, so the bridge cannot silently drift
        back to hourly retries the way it did after #1059."""
        reworded = self.answer("a reason worded some new way next year", False)
        self.assertEqual(self.held(self.rows(reworded, [1])), frozenset({self.KEY}))
        self.assertEqual(self.held(self.rows(reworded, [2])), frozenset())
        self.assertEqual(
            self.held(self.rows(reworded, [3, 5])), frozenset({self.KEY})
        )  # a streak of two: 4h

    def test_retryable_false_on_a_known_gate_is_honoured(self):
        offline = self.answer("taker offline", False)
        self.assertEqual(self.held(self.rows(offline, [1])), frozenset({self.KEY}))

    def test_a_delivery_ends_an_unknown_final_streak(self):
        reworded = self.answer("a reason worded some new way next year", False)
        rows = self.rows(reworded, [3, 4, 5]) + self.rows(
            json.dumps({"outcome": "shared"}), [2], status="delivered"
        )
        self.assertEqual(self.held(rows), frozenset())

    def test_an_unknown_final_refusal_proves_no_later_gate_passed(self):
        """Its gate is unknown, so it cannot end an older streak the way a
        later known gate does: the older refusals keep counting."""
        holder = self.rows(self.LIVE, [3, 4, 5, 6, 7])
        reworded = self.rows(self.answer("a reason worded some new way", False), [1])
        # six in the streak: 64h from the youngest, not the 2h of a fresh one
        held = self.held(holder + reworded)
        self.assertEqual(held, frozenset({self.KEY}))
        later = self.rows(self.answer("a reason worded some new way", False), [40])
        self.assertEqual(self.held(holder + later), frozenset({self.KEY}))

    def test_retryable_true_or_absent_on_an_unknown_reason_counts_for_nothing(self):
        for result in (
            self.answer("a reason worded some new way", True),
            self.answer("a reason worded some new way"),
            self.answer("a reason worded some new way", "false"),
        ):
            with self.subTest(result=result):
                self.assertEqual(self.held(self.rows(result, [0])), frozenset())

    def test_retryable_true_does_not_shorten_a_bridge_side_permanent_reason(self):
        """The module marks only CanShareQuest final; eligibility (#170) and
        the rest of PERMANENT_REFUSALS are the bridge's own judgement and
        stay permanent when the row says retryable:true."""
        for reason in questshare.PERMANENT_REFUSALS:
            with self.subTest(reason=reason):
                rows = self.rows(self.answer(reason, True), [1])
                self.assertEqual(self.held(rows), frozenset({self.KEY}))

    def test_a_transient_gate_marked_retryable_stays_transient(self):
        rows = self.rows(self.answer("taker offline", True), range(50))
        self.assertEqual(self.held(rows), frozenset())

    def test_every_new_reason_is_known_and_permanent(self):
        for reason in ("quest is not sharable", "holder does not carry the quest"):
            with self.subTest(reason=reason):
                self.assertIn(reason, questshare.PERMANENT_REFUSALS)
                self.assertIn(
                    reason,
                    {r for gate in questshare.SHARE_GATES for r in gate},
                )

    def test_the_gate_reader_handles_the_1059_shape(self):
        self.assertEqual(
            _gate_literals(_SHARE_GATE_AFTER_1059),
            [
                ("quest is not sharable", "holder does not carry the quest"),
                ("not in the same party",),
            ],
        )
        holder_gate = next(
            g for g in questshare.SHARE_GATES if "quest is not sharable" in g
        )
        self.assertLessEqual(
            {"quest is not sharable", "holder does not carry the quest"},
            set(holder_gate),
        )


if __name__ == "__main__":
    unittest.main()


class AnAbandonedQuestIsNotHeld(unittest.TestCase):
    """infra#2892, found by a Datadog page rather than by a test.

    `questshare` tried **167 times** to make Bork share quest 3361
    ("A Refugee's Quandary"), every attempt answered:

        holder is not carrying that quest or it is not sharable

    It fired roughly hourly and could never succeed. Bork holds a row for 3361
    at `status = 0` - the row exists, the quest does not. Dozens of random bots
    hold it properly at `status = 3`.

    The bug was in the READ, not the planner: `_QUEST_SQL` selected from
    `character_queststatus` with no status filter at all, so an abandoned row
    read as "this character holds this quest". A sibling query in the same file
    already got this right, filtering `q.status IN (1, 3)`.

    Quest status here: 0 none/abandoned, 1 complete, 3 incomplete.

    READ AS TEXT, NOT IMPORTED. bridge.py imports discord, and this suite is
    stdlib-only by design (see the module docstring) - the same reason
    test_schema_degrade.py reads the C++ source rather than linking it.
    """

    @classmethod
    def setUpClass(cls):
        import pathlib

        cls.src = (
            pathlib.Path(__file__).resolve().parent.parent / "bridge.py"
        ).read_text(encoding="utf-8")

    def _quest_sql(self):
        start = self.src.index("_QUEST_SQL = ")
        return self.src[start : self.src.index('"""', self.src.index('"""', start) + 3)]

    def test_the_read_only_counts_quests_actually_held(self):
        self.assertIn(
            "q.status IN (1, 3)",
            self._quest_sql(),
            "an abandoned row must not read as a held quest",
        )

    def test_the_single_quest_read_carries_the_same_filter(self):
        # _QUEST_ONE_SQL is DERIVED from _QUEST_SQL by swapping the WHERE
        # clause, so the filter must live where the swap cannot drop it.
        derive = self.src[self.src.index("_QUEST_ONE_SQL = ") :]
        derive = derive[: derive.index(chr(10) + chr(10))]
        self.assertIn("c.name = %s", derive)
        self.assertNotIn(
            "q.status",
            derive,
            "the status filter must survive the WHERE swap, not be re-stated in it",
        )

    def test_the_derivation_tripwire_still_holds(self):
        # The import-time guard exists because a silent drift here fails once
        # an hour inside the supervision cycle.
        self.assertIn("_QUEST_SQL WHERE clause moved", self.src)

    def _ledger_held_sql(self):
        # Sliced to the assignment's own closing paren at column 0, NOT to the
        # second ")" in the text: the constant carries a WHY comment, and any
        # parenthesis inside it (an issue number, the status tuple) truncated
        # the slice before the SQL and made this read pass or fail on prose.
        start = self.src.index("_LEDGER_HELD_SQL = (")
        return self.src[start : self.src.index(chr(10) + ")", start)]

    def test_the_ledger_read_carries_the_same_filter(self):
        # The ledger read is what questshare aims at, so it must agree with
        # _QUEST_SQL about what "held" means. When it did not, a status-0 row
        # read as held and the same impossible share was retried 167 times
        # (#2892) -- the worldserver's refusal is not an error anywhere it
        # would be seen.
        self.assertIn(
            "q.status IN (1, 3)",
            self._ledger_held_sql(),
            "an abandoned row must not read as a held quest",
        )

    def test_the_rewarded_read_is_deliberately_unfiltered(self):
        # character_queststatus_rewarded has no status column: a row there IS
        # the completion record. Pinning that so a future sweep does not
        # "consistently" add a filter to a table that cannot support one.
        start = self.src.index("_LEDGER_REWARDED_SQL = (")
        self.assertNotIn(
            "q.status", self.src[start : self.src.index(chr(10) + ")", start)]
        )

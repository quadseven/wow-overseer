"""What the family's quest logs are allowed to say, and what they may not.

The rules here are not "does it render". They are the handful of judgements
that decide whether the two defects this view exists to expose stay visible:
which rows occupy a log slot at all, what counts as full, and who else is
carrying a quest. Each of them is a place where a plausible-looking
simplification quietly puts the defect back in hiding.

Ticket: infra#3110.
"""

import unittest

import bonds
import family
import questlog

# The column spellings a real row carries, all zero, so a test only has to
# name the two or three fields it is actually about. Copied from the live
# quest_template + character_queststatus join in map_server._QUESTLOG_SQL -
# if that query loses a column this dict is where it stops matching.
_BLANK = {"LogTitle": "", "QuestLevel": 0, "RequiredPlayerKills": 0, "playercount": 0}
for _i in range(1, questlog.NPC_SLOTS + 1):
    _BLANK["RequiredNpcOrGo%d" % _i] = 0
    _BLANK["RequiredNpcOrGoCount%d" % _i] = 0
    _BLANK["mobcount%d" % _i] = 0
    _BLANK["ObjectiveText%d" % _i] = ""
for _i in range(1, questlog.ITEM_SLOTS + 1):
    _BLANK["RequiredItemId%d" % _i] = 0
    _BLANK["RequiredItemCount%d" % _i] = 0
    _BLANK["itemcount%d" % _i] = 0


def row(name, quest, status=questlog.INCOMPLETE, **fields):
    out = dict(_BLANK)
    out.update({"name": name, "quest": quest, "status": status})
    out.update(fields)
    return out


def chars(*specs):
    """(name, level) pairs -> `characters` rows."""
    return [{"name": n, "level": lvl, "class": 1, "online": 1} for n, lvl in specs]


def build(quest_rows, char_specs=None, rewarded=None, names=None):
    roster = family.roster()
    if char_specs is None:
        char_specs = [(n, 20) for n in roster]
    return questlog.build_questlog(
        chars(*char_specs),
        quest_rows,
        rewarded or [],
        names or {"creatures": {}, "gameobjects": {}, "items": {}},
    )


def member(payload, name):
    return next(m for m in payload["members"] if m["name"] == name)


class WhatIsActuallyInTheLog(unittest.TestCase):
    """The slot count is the whole of mod-overseer#73, and it is one
    subtraction that nothing on any surface was doing. Getting the numerator
    wrong is the only way to get it wrong."""

    def test_an_abandoned_row_holds_no_slot(self):
        """Status NONE rows outnumber real ones two to one on this realm.
        Counting them puts three of the five over a cap of 25 - Bork alone
        carried 37 rows against 22 real quests - so a log built from the raw
        row count reports a number the client cannot produce."""
        self.assertNotIn(0, questlog.IN_LOG)

    def test_a_failed_quest_still_holds_its_slot(self):
        """It sits in the log until somebody abandons or retries it, which is
        precisely the dead weight #73 is about. Dropping it would hide a slot
        that is genuinely spent."""
        self.assertIn(questlog.FAILED, questlog.IN_LOG)

    def test_the_slot_count_is_what_the_rows_say(self):
        first = family.roster()[0]
        rows = [row(first, 100 + i) for i in range(7)]
        rows.append(row(first, 900, questlog.FAILED))
        m = member(build(rows), first)
        self.assertEqual(m["used"], 8)
        self.assertEqual(m["slots"], questlog.LOG_SLOTS)
        self.assertEqual(m["free"], questlog.LOG_SLOTS - 8)
        self.assertEqual(m["failed"], 1)

    def test_full_fires_before_the_cap_not_at_it(self):
        """At 25 the quest drive has already been silently refusing accepts
        for a while, which is the invisibility #73 describes. The warning has
        to arrive with room left to act on it."""
        first = family.roster()[0]
        near = [
            row(first, 500 + i)
            for i in range(questlog.LOG_SLOTS - questlog.FULL_WITHIN)
        ]
        self.assertTrue(member(build(near), first)["full"])
        self.assertFalse(member(build(near[:-1]), first)["full"])

    def test_a_log_over_the_cap_never_reports_negative_room(self):
        """The core can exceed the client's cap through a GM grant or a
        migration, and "-2 slots free" reads as a bug in the page rather than
        as the state it is describing."""
        first = family.roster()[0]
        rows = [row(first, 700 + i) for i in range(questlog.LOG_SLOTS + 4)]
        m = member(build(rows), first)
        self.assertEqual(m["used"], questlog.LOG_SLOTS + 4)
        self.assertEqual(m["free"], 0)
        self.assertTrue(m["full"])


class WhoElseIsCarryingIt(unittest.TestCase):
    """mod-overseer#28: five characters, five quest logs, so the same kill
    pays only whoever holds the quest. Every one of these is the difference
    between that being visible and being arithmetic somebody has to do."""

    def test_every_quest_names_the_others_holding_it(self):
        a, b, c = family.roster()[:3]
        payload = build([row(a, 60), row(b, 60), row(c, 99)])
        shared = member(payload, a)["quests"][0]
        self.assertEqual(shared["held_by"], [a, b])
        self.assertFalse(shared["alone"])
        lone = member(payload, c)["quests"][0]
        self.assertEqual(lone["held_by"], [c])
        self.assertTrue(lone["alone"])

    def test_holders_come_out_in_roster_order(self):
        """The family is already ordered - bonds.speaking_order decides who
        comes first everywhere else on this page. A second ordering here
        would be a second opinion about the same five people."""
        roster = family.roster()
        payload = build([row(n, 60) for n in reversed(roster)])
        self.assertEqual(member(payload, roster[0])["quests"][0]["held_by"], roster)

    def test_the_family_totals_count_quests_not_rows(self):
        """Five characters holding one quest is ONE piece of work the family
        is doing. Counting the rows instead makes a badly-shared log look
        five times busier than it is."""
        roster = family.roster()
        payload = build([row(n, 60) for n in roster] + [row(roster[0], 61)])
        self.assertEqual(payload["held"], 2)
        self.assertEqual(payload["alone"], 1)
        self.assertEqual(payload["shared"], 1)
        self.assertEqual(payload["everyone"], 1)

    def test_a_quest_short_of_one_member_is_not_held_by_everyone(self):
        """The live number is zero - not one quest of the forty-one is held
        by all five - and an off-by-one here would report the opposite."""
        roster = family.roster()
        payload = build([row(n, 60) for n in roster[:-1]])
        self.assertEqual(payload["everyone"], 0)
        self.assertEqual(payload["shared"], 1)

    def test_each_member_counts_what_nobody_else_is_helping_with(self):
        a, b = family.roster()[:2]
        payload = build([row(a, 60), row(b, 60), row(a, 61), row(a, 62)])
        self.assertEqual(member(payload, a)["alone"], 2)
        self.assertEqual(member(payload, b)["alone"], 0)

    def test_the_turn_in_spread_is_the_evidence_the_issue_was_opened_with(self):
        roster = family.roster()
        payload = build(
            [],
            rewarded=[
                {"name": roster[0], "turned_in": 50},
                {"name": roster[3], "turned_in": 18},
            ],
        )
        spread = payload["turn_in_spread"]
        self.assertEqual(spread["most"], roster[0])
        self.assertEqual(spread["most_count"], 50)
        self.assertEqual(spread["least_count"], 0)
        self.assertEqual(spread["gap"], 50)

    def test_a_member_with_no_turn_ins_row_reads_as_zero_not_missing(self):
        """A character with nothing turned in has no row in a GROUP BY, and
        that absence is the loudest fact about them - it must not be the one
        that drops them out of the comparison."""
        payload = build([])
        for m in payload["members"]:
            self.assertEqual(m["turned_in"], 0)


class WhatTheObjectivesSay(unittest.TestCase):
    def test_a_kill_objective_counts_from_the_real_columns(self):
        first = family.roster()[0]
        payload = build(
            [
                row(
                    first,
                    226,
                    RequiredNpcOrGo1=213,
                    RequiredNpcOrGoCount1=12,
                    mobcount1=6,
                )
            ],
            names={
                "creatures": {213: "Starving Dire Wolf"},
                "gameobjects": {},
                "items": {},
            },
        )
        q = member(payload, first)["quests"][0]
        self.assertEqual(
            q["objectives"],
            [{"what": "Starving Dire Wolf", "have": 6, "need": 12, "done": False}],
        )
        self.assertEqual(q["progress_pct"], 50)

    def test_a_gathering_objective_counts_from_the_item_columns(self):
        first = family.roster()[0]
        payload = build(
            [
                row(
                    first,
                    127,
                    RequiredItemId1=1467,
                    RequiredItemCount1=10,
                    itemcount1=9,
                )
            ],
            names={
                "creatures": {},
                "gameobjects": {},
                "items": {1467: "Spotted Sunfish"},
            },
        )
        q = member(payload, first)["quests"][0]
        self.assertEqual(q["objectives"][0]["what"], "Spotted Sunfish")
        self.assertEqual(q["progress_pct"], 90)

    def test_a_negative_target_is_a_gameobject_not_a_creature(self):
        """RequiredNpcOrGo stores gameobjects as the negative of their entry.
        Reading the sign as a creature id looks up -1735 in creature_template,
        misses, and renders a fallback over a perfectly nameable chest."""
        first = family.roster()[0]
        rows = [row(first, 1, RequiredNpcOrGo1=-1735, RequiredNpcOrGoCount1=1)]
        self.assertEqual(questlog.objective_entries(rows)["gameobjects"], [1735])
        self.assertEqual(questlog.objective_entries(rows)["creatures"], [])
        payload = build(
            rows,
            names={
                "creatures": {},
                "items": {},
                "gameobjects": {1735: "Battered Chest"},
            },
        )
        self.assertEqual(
            member(payload, first)["quests"][0]["objectives"][0]["what"],
            "Battered Chest",
        )

    def test_the_quests_own_wording_beats_the_creature_name(self):
        """ObjectiveText is what the client itself prints, and it exists for
        the case where one name would be wrong - four different mobs counting
        towards "Defias Bandits slain"."""
        first = family.roster()[0]
        payload = build(
            [
                row(
                    first,
                    1,
                    RequiredNpcOrGo1=598,
                    RequiredNpcOrGoCount1=8,
                    ObjectiveText1="Defias Bandit slain",
                )
            ],
            names={
                "creatures": {598: "Defias Smuggler"},
                "gameobjects": {},
                "items": {},
            },
        )
        self.assertEqual(
            member(payload, first)["quests"][0]["objectives"][0]["what"],
            "Defias Bandit slain",
        )

    def test_a_name_that_cannot_be_looked_up_still_says_which_thing(self):
        """A custom or removed entry is not a reason to drop the objective:
        "8 of creature #1735" is worse than a name and far better than an
        objective that silently is not there."""
        first = family.roster()[0]
        payload = build([row(first, 1, RequiredNpcOrGo1=1735, RequiredNpcOrGoCount1=8)])
        self.assertEqual(
            member(payload, first)["quests"][0]["objectives"][0]["what"],
            "creature #1735",
        )

    def test_progress_past_the_target_reads_as_done_not_as_a_bug(self):
        """The core keeps counting past the requirement on some quests, and
        "12 / 10" on a card reads as the page being broken."""
        first = family.roster()[0]
        payload = build(
            [
                row(
                    first,
                    1,
                    RequiredNpcOrGo1=213,
                    RequiredNpcOrGoCount1=10,
                    mobcount1=12,
                )
            ]
        )
        q = member(payload, first)["quests"][0]
        self.assertEqual(q["objectives"][0]["have"], 10)
        self.assertTrue(q["objectives"][0]["done"])
        self.assertEqual(q["progress_pct"], 100)

    def test_a_quest_that_counts_nothing_has_no_percentage(self):
        """Six of the family's held quests count nothing at all - a delivery,
        a conversation, a place to walk to. Reporting those at 0% draws an
        empty bar under a quest that may be finished, which is the page
        inventing a fact about it."""
        first = family.roster()[0]
        q = member(build([row(first, 467)]), first)["quests"][0]
        self.assertEqual(q["objectives"], [])
        self.assertIsNone(q["progress_pct"])

    def test_a_pvp_objective_is_counted_too(self):
        first = family.roster()[0]
        payload = build([row(first, 1, RequiredPlayerKills=10, playercount=3)])
        self.assertEqual(
            member(payload, first)["quests"][0]["objectives"],
            [{"what": "enemy players", "have": 3, "need": 10, "done": False}],
        )

    def test_every_id_the_rows_name_is_offered_for_lookup(self):
        """The adapter fetches names for exactly this set, so an id missed
        here is a name that silently never renders."""
        first = family.roster()[0]
        rows = [
            row(
                first,
                1,
                RequiredNpcOrGo1=10,
                RequiredNpcOrGo4=-20,
                RequiredItemId1=30,
                RequiredItemId6=40,
            )
        ]
        self.assertEqual(
            questlog.objective_entries(rows),
            {"creatures": [10], "gameobjects": [20], "items": [30, 40]},
        )


class WhatOrderTheLogComesIn(unittest.TestCase):
    def test_what_can_be_handed_in_comes_first(self):
        first = family.roster()[0]
        rows = [
            row(first, 1),
            row(first, 2, questlog.COMPLETE),
            row(first, 3, questlog.FAILED),
        ]
        got = [q["status"] for q in member(build(rows), first)["quests"]]
        self.assertEqual(got, [questlog.READY, questlog.ACTIVE, questlog.STUCK])

    def test_a_started_quest_outranks_an_untouched_one(self):
        first = family.roster()[0]
        rows = [
            row(first, 1, RequiredNpcOrGo1=9, RequiredNpcOrGoCount1=10),
            row(first, 2, RequiredNpcOrGo1=9, RequiredNpcOrGoCount1=10, mobcount1=4),
        ]
        self.assertEqual(
            [q["id"] for q in member(build(rows), first)["quests"]], [2, 1]
        )

    def test_the_oldest_work_sinks_within_its_group(self):
        """Newest first, so the stragglers from ten levels ago end up at the
        foot of the list where their own marker can be read against them."""
        first = family.roster()[0]
        rows = [row(first, 1, QuestLevel=7), row(first, 2, QuestLevel=21)]
        self.assertEqual(
            [q["id"] for q in member(build(rows), first)["quests"]], [2, 1]
        )

    def test_the_same_state_always_sorts_the_same_way(self):
        """Two identical quests must not swap places between polls - a list
        that reshuffles under a thumb is unreadable."""
        first = family.roster()[0]
        rows = [row(first, 9), row(first, 4), row(first, 7)]
        self.assertEqual(
            [q["id"] for q in member(build(rows), first)["quests"]], [4, 7, 9]
        )


class DeadWeight(unittest.TestCase):
    def test_a_quest_far_under_the_character_is_marked(self):
        """#73's evidence is two level 7 quests in a level 20 log. That is
        what the marker is for."""
        first = family.roster()[0]
        payload = build([row(first, 1, QuestLevel=7)], char_specs=[(first, 20)])
        self.assertTrue(member(payload, first)["quests"][0]["outleveled"])
        self.assertEqual(member(payload, first)["outleveled"], 1)

    def test_ordinary_play_is_not_marked(self):
        """The family runs quests two to five levels under themselves all
        day. A marker that fires on those means nothing."""
        first = family.roster()[0]
        payload = build([row(first, 1, QuestLevel=21)], char_specs=[(first, 25)])
        self.assertFalse(member(payload, first)["quests"][0]["outleveled"])

    def test_a_quest_with_no_level_is_never_marked(self):
        """Escort and class quests ship with QuestLevel 0, and subtracting
        from that flags every one of them as ancient."""
        first = family.roster()[0]
        payload = build([row(first, 1, QuestLevel=0)], char_specs=[(first, 60)])
        self.assertFalse(member(payload, first)["quests"][0]["outleveled"])


class NobodyIsDropped(unittest.TestCase):
    def test_all_five_get_a_column_in_roster_order(self):
        payload = build([])
        self.assertEqual([m["name"] for m in payload["members"]], family.roster())
        self.assertEqual(payload["expected"], len(family.roster()))

    def test_a_character_with_no_saved_row_still_gets_a_column(self):
        """A quest log is SAVED state, so unlike the Family tab there is no
        freshness window here - but a character the `characters` table has
        never seen still has to appear, or a view that quietly drops somebody
        is how that somebody stops being noticed."""
        roster = family.roster()
        payload = build([], char_specs=[(n, 20) for n in roster[:-1]])
        absent = member(payload, roster[-1])
        self.assertFalse(absent["present"])
        self.assertEqual(absent["quests"], [])
        # Still says who they are. bonds is where that belongs, and reading
        # it here is what proves the column is a real one rather than a
        # placeholder with a name on it.
        self.assertEqual(absent["role"], bonds.FAMILY[roster[-1]].role)

    def test_an_empty_log_is_reported_rather_than_omitted(self):
        first = family.roster()[0]
        m = member(build([]), first)
        self.assertTrue(m["present"])
        self.assertEqual(m["used"], 0)
        self.assertEqual(m["quests"], [])
        self.assertEqual(m["alone"], 0)

    def test_the_spread_says_nothing_when_there_is_nobody_to_compare(self):
        self.assertIsNone(build([], char_specs=[])["turn_in_spread"])


class TheVocabularyIsOwnedHere(unittest.TestCase):
    """The page reads these words; a second set of them in a render function
    is a second answer that can disagree with this one."""

    def test_every_status_in_the_log_renders_as_a_word(self):
        first = family.roster()[0]
        for status in questlog.IN_LOG:
            payload = build([row(first, 1, status)])
            self.assertIn(
                member(payload, first)["quests"][0]["status"],
                (questlog.READY, questlog.ACTIVE, questlog.STUCK),
            )

    def test_a_quest_with_no_title_still_says_which_quest(self):
        first = family.roster()[0]
        payload = build([row(first, 4242, LogTitle="")])
        self.assertIn("4242", member(payload, first)["quests"][0]["title"])


def board(quest_rows, done=None, party=None, char_specs=None):
    """The shared board, with the same defaults build() uses."""
    roster = family.roster()
    if char_specs is None:
        char_specs = [(n, 20) for n in roster]
    return questlog.build_questlog(
        chars(*char_specs),
        quest_rows,
        [],
        {"creatures": {}, "gameobjects": {}, "items": {}},
        done_rows=done,
        party_rows=party,
    )["board"]


def brow(payload_board, quest_id):
    return next(r for r in payload_board["rows"] if r["id"] == quest_id)


def role_of(payload_board, quest_id, name):
    people = brow(payload_board, quest_id)["people"]
    return next((p["role"] for p in people if p["name"] == name), None)


def grouped(*names, leader=None):
    """Snapshot party rows: everyone named is in one party under `leader`
    (the first name when unsaid). guid is the roster position plus one."""
    roster = family.roster()
    lead = leader or names[0]
    return [
        {"guid": roster.index(n) + 1, "name": n, "group_leader": roster.index(lead) + 1}
        for n in names
    ]


class TheSharedBoard(unittest.TestCase):
    """infra#88: one quest board for the family, deduped by quest id, with a
    portrait per member on each row saying what that member IS to the quest.
    Five side-by-side logs made a person read the same title five times to
    learn who was on it; these are the rules that make one list say it."""

    def test_one_row_per_quest_however_many_hold_it(self):
        roster = family.roster()
        b = board([row(n, 60) for n in roster] + [row(roster[0], 61)])
        self.assertEqual(sorted(r["id"] for r in b["rows"]), [60, 61])

    def test_a_holder_is_on_it_until_it_is_complete_then_ready_to_hand_in(self):
        a, c = family.roster()[0], family.roster()[2]
        b = board([row(a, 7, questlog.INCOMPLETE), row(c, 7, questlog.COMPLETE)])
        self.assertEqual(role_of(b, 7, a), questlog.ON)
        self.assertEqual(role_of(b, 7, c), questlog.HAND_IN)
        self.assertEqual(brow(b, 7)["on"], 1)
        self.assertEqual(brow(b, 7)["hand_in"], 1)

    def test_somebody_with_no_relation_to_the_quest_gets_no_portrait(self):
        a, b_ = family.roster()[:2]
        b = board([row(a, 7)])
        self.assertIsNone(role_of(b, 7, b_))
        self.assertEqual([p["name"] for p in brow(b, 7)["people"]], [a])

    def test_a_party_member_who_does_not_hold_it_is_helping(self):
        """Kills in a party count for every member of it, so a member grouped
        with the holder is doing the quest for someone else's log - which is
        mod-overseer#28 working the way it should, and worth showing."""
        a, b_, c = family.roster()[:3]
        b = board([row(a, 7)], party=grouped(a, b_))
        self.assertEqual(role_of(b, 7, b_), questlog.HELPING)
        # c is not in the party and not holding it: nothing to say.
        self.assertIsNone(role_of(b, 7, c))
        self.assertEqual(brow(b, 7)["helping"], 1)

    def test_being_grouped_with_a_non_holder_is_not_helping(self):
        a, b_, c = family.roster()[:3]
        b = board([row(a, 7)], party=grouped(b_, c))
        self.assertIsNone(role_of(b, 7, b_))
        self.assertIsNone(role_of(b, 7, c))

    def test_a_turn_in_reads_as_done_and_only_for_quests_still_held(self):
        a, b_ = family.roster()[:2]
        b = board(
            [row(a, 7)], done=[{"name": b_, "quest": 7}, {"name": b_, "quest": 999}]
        )
        self.assertEqual(role_of(b, 7, b_), questlog.DONE)
        self.assertEqual(brow(b, 7)["done"], 1)
        # 999 is in nobody's log: it is not a row, so it is not on the board.
        self.assertEqual([r["id"] for r in b["rows"]], [7])

    def test_helping_beats_done_but_the_turn_in_is_still_said(self):
        """Turned it in last week and standing in the party tonight: they are
        helping tonight. The flag survives so the page can still tick the
        portrait; only the word is decided here."""
        a, b_ = family.roster()[:2]
        b = board([row(a, 7)], done=[{"name": b_, "quest": 7}], party=grouped(a, b_))
        self.assertEqual(role_of(b, 7, b_), questlog.HELPING)
        person = next(p for p in brow(b, 7)["people"] if p["name"] == b_)
        self.assertTrue(person["turned_in"])

    def test_holding_it_beats_everything(self):
        a, b_ = family.roster()[:2]
        b = board(
            [row(a, 7), row(b_, 7)],
            done=[{"name": b_, "quest": 7}],
            party=grouped(a, b_),
        )
        self.assertEqual(role_of(b, 7, b_), questlog.ON)

    def test_the_leader_wears_the_crown_and_it_is_the_worlds_leader(self):
        a, b_ = family.roster()[:2]
        b = board([row(a, 7), row(b_, 7)], party=grouped(a, b_, leader=b_))
        self.assertEqual(b["leader"], b_)
        people = {p["name"]: p for p in brow(b, 7)["people"]}
        self.assertTrue(people[b_]["leader"])
        self.assertFalse(people[a]["leader"])

    def test_with_no_party_the_roster_head_leads(self):
        """The operator asked for the crown on "the roster lead flag / group
        leader". With nobody grouped there is no group leader, and the family
        table is the answer to who the party follows when it forms."""
        a = family.roster()[0]
        b = board([row(a, 7)])
        self.assertEqual(b["leader"], bonds.head_of_family())

    def test_portraits_come_out_in_roster_order(self):
        roster = family.roster()
        b = board([row(n, 7) for n in reversed(roster)])
        self.assertEqual([p["name"] for p in brow(b, 7)["people"]], roster)

    def test_hand_ins_first_then_the_most_held_then_the_rest(self):
        a, b_, c = family.roster()[:3]
        rows = [
            row(a, 1, QuestLevel=30),  # on, one holder
            row(a, 2),
            row(b_, 2),
            row(c, 2),  # on, three holders
            row(b_, 3, questlog.COMPLETE, QuestLevel=5),  # ready to hand in
            row(c, 4, questlog.FAILED, QuestLevel=40),  # the rest
            row(a, 5),
            row(b_, 5),  # on, two holders
        ]
        self.assertEqual([r["id"] for r in board(rows)["rows"]], [3, 2, 5, 1, 4])

    def test_the_row_carries_the_furthest_holders_objectives(self):
        """Five holders are five counters, and drawing all five is the
        repetition the board exists to remove. The row shows the one that is
        furthest along and says whose it is; each portrait keeps its own."""
        a, b_ = family.roster()[:2]
        rows = [
            row(a, 7, RequiredNpcOrGo1=100, RequiredNpcOrGoCount1=10, mobcount1=2),
            row(b_, 7, RequiredNpcOrGo1=100, RequiredNpcOrGoCount1=10, mobcount1=8),
        ]
        r = brow(board(rows), 7)
        self.assertEqual(r["furthest"], b_)
        self.assertEqual(r["progress_pct"], 80)
        by = {p["name"]: p["progress_pct"] for p in r["people"]}
        self.assertEqual(by, {a: 20, b_: 80})

    def test_a_helper_has_no_progress_of_their_own(self):
        a, b_ = family.roster()[:2]
        r = brow(board([row(a, 7)], party=grouped(a, b_)), 7)
        helper = next(p for p in r["people"] if p["name"] == b_)
        self.assertIsNone(helper["progress_pct"])

    def test_every_portrait_carries_its_class_colour(self):
        a = family.roster()[0]
        r = brow(board([row(a, 7)]), 7)
        self.assertTrue(r["people"][0]["class_colour"].startswith("#"))

    def test_a_logged_out_member_still_has_a_colour(self):
        a = family.roster()[0]
        payload = build([row(a, 7)], char_specs=[])
        self.assertTrue(member(payload, a)["class_colour"].startswith("#"))

    def test_the_fold_size_is_decided_here_not_in_the_page(self):
        a = family.roster()[0]
        self.assertEqual(board([row(a, 7)])["preview"], questlog.BOARD_PREVIEW)

    def test_an_empty_family_is_an_empty_board(self):
        self.assertEqual(board([])["rows"], [])


class WhoIsGroupedWithWhom(unittest.TestCase):
    def test_solo_members_are_in_no_group(self):
        a, b_ = family.roster()[:2]
        rows = [
            {"guid": 1, "name": a, "group_leader": 0},
            {"guid": 2, "name": b_, "group_leader": None},
        ]
        self.assertEqual(questlog.party(rows)["groups"], {})

    def test_a_leader_the_snapshot_has_not_got_names_nobody_from_the_world(self):
        a = family.roster()[0]
        rows = [{"guid": 1, "name": a, "group_leader": 999}]
        got = questlog.party(rows)
        self.assertEqual(got["groups"], {a: 999})
        self.assertEqual(got["leader"], bonds.head_of_family())

    def test_none_is_the_same_as_no_snapshot(self):
        self.assertEqual(questlog.party(None)["groups"], {})


if __name__ == "__main__":
    unittest.main()


class TheBoardIsTheFamilyAsked(unittest.TestCase):
    """The Horde family's tab showed the Alliance board: the builder only
    knew bonds' family and indexed it by name, so any other roster was a
    KeyError, and the adapter never asked for one."""

    HORDE = ["Zug", "Oz", "Uzza"]

    def build(self, party_rows=None):
        return questlog.build_questlog(
            chars(("Zug", 15), ("Oz", 11), ("Uzza", 11)),
            [row("Zug", 100, QuestLevel=12), row("Oz", 100, QuestLevel=12)],
            [{"name": "Zug", "turned_in": 4}],
            {"creatures": {}, "gameobjects": {}, "items": {}},
            party_rows=party_rows,
            roster=self.HORDE,
        )

    def test_the_members_are_the_roster_given(self):
        p = self.build()
        self.assertEqual([m["name"] for m in p["members"]], self.HORDE)
        self.assertEqual(p["expected"], 3)

    def test_a_member_bonds_does_not_know_has_no_role_rather_than_a_crash(self):
        self.assertEqual(member(self.build(), "Zug")["role"], "")

    def test_the_board_is_their_quests(self):
        rows = self.build()["board"]["rows"]
        self.assertEqual([r["id"] for r in rows], [100])
        self.assertEqual({p["name"] for p in rows[0]["people"]}, {"Zug", "Oz"})

    def test_with_no_live_group_the_crown_is_their_lead_not_the_other_head(self):
        self.assertEqual(self.build()["board"]["leader"], "Zug")

    def test_the_turn_in_spread_is_theirs(self):
        spread = self.build()["turn_in_spread"]
        self.assertEqual(spread["most"], "Zug")

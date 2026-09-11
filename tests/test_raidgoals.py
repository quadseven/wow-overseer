"""What the raid-readiness view is allowed to claim, and what it is not.

MOST OF THIS FILE IS ABOUT THE SECOND HALF. The arithmetic here is addition;
the risk is that a page planning real farming states a hand-written number as
though the world had handed it over. raidgoals.py carries a reagent table it
CANNOT check against this realm, because reagents live in Spell.dbc and this
deployment does not import it, so the guards that matter are the ones keeping
those numbers distinguishable from the measured ones.

FOUR DISTINCTIONS THIS SUITE EXISTS TO KEEP:

  unreachable vs short      a trade nobody has is not an evening of farming
  unknown vs none           an empty character_skills read is not "nobody has
                            alchemy", and saying so turns a failed read into
                            an errand for a person
  absent rank vs rank 0     "this realm states no rank" is not "anybody can
                            make it"
  made vs sourceless        a reagent in no vendor, loot or node table is
                            sometimes crafted and sometimes genuinely
                            unaccounted for, and the two send a reader to
                            opposite places

Ticket: infra#3508.
"""
import unittest

import professions
import raidgoals

ALCHEMY = professions.skill_id("alchemy")
ENGINEERING = professions.skill_id("engineering")
HERBALISM = professions.skill_id("herbalism")

FAMILY = ["Bork", "Grog", "Grug", "Og", "Ugga"]
FLASK_SPELLS = (17637, 17636, 17635)
MANA_SPELL = 17580
HEALING_SPELL = 17556


def items(drop=(), twin=()):
    """An item_template row per name in the plan, minus whatever `drop` names.

    Entries are positional and arbitrary: nothing in the module reads meaning
    into the number, it only has to be stable enough for the three source
    reads to bind.
    """
    rows = []
    for i, name in enumerate(raidgoals.plan_item_names(), start=1000):
        if name in drop:
            continue
        rows.append({"entry": i, "item_name": name, "quality": 1,
                     "item_level": 60})
        if name in twin:
            rows.append({"entry": i + 500, "item_name": name, "quality": 1,
                         "item_level": 60})
    return rows


def entry_of(rows, name):
    for row in rows:
        if row["item_name"] == name:
            return row["entry"]
    raise AssertionError("no fixture row for %r" % name)


def holding(holder, name, count, slot=23, bag=0):
    """One character_inventory row in the shape bank.members_from_rows reads.

    Slot 23 is the backpack, 40 is a bank slot and 5 is worn: bank.py's own
    geography, which this module borrows rather than restating.
    """
    return {"holder": holder, "level": 37, "item_guid": abs(hash((holder, name, slot))) % 10**8,
            "count": count, "name": name, "quality": 1, "sell_price": 10,
            "required_level": 0, "bonding": 0, "item_class": 0,
            "container_slots": 0, "bag": bag, "slot": slot}


def payload(*, alchemy=300, engineering=0, known=FLASK_SPELLS,
            skills_present=True, drop=(), twin=(), holdings=(), worn=(),
            guild=(), recipes=None, trainer=None, roster=None, chars=None,
            sources=True, oil_source=False):
    """A live-shaped payload with one knob per thing this suite has to vary."""
    rows = items(drop=drop, twin=twin)
    skill_rows = []
    if skills_present:
        skill_rows = [{"name": "Ugga", "skill": ALCHEMY, "value": alchemy},
                      {"name": "Ugga", "skill": HERBALISM, "value": 200}]
        if engineering:
            skill_rows.append({"name": "Grug", "skill": ENGINEERING,
                               "value": engineering})
    vendor, creature, objects = [], [], []
    if sources:
        vendor = [{"item": entry_of(rows, "Crystal Vial")}]
        creature = [{"item": entry_of(rows, "Elemental Fire")}]
        objects = [{"item": entry_of(rows, herb)} for herb in
                   ("Dreamfoil", "Black Lotus", "Gromsblood",
                    "Mountain Silversage", "Golden Sansam")
                   if any(r["item_name"] == herb for r in rows)]
    if oil_source:
        creature.append({"item": entry_of(rows, "Stonescale Oil")})
    names = list(roster if roster is not None else FAMILY)
    if chars is None:
        chars = [{"name": n, "level": 37, "class": "Druid"} for n in names]
    return raidgoals.build_raidgoals(
        item_rows=rows,
        recipe_rows=list(recipes if recipes is not None else
                         [{"entry": 9001, "teaches": HEALING_SPELL,
                           "skill": ALCHEMY, "skill_rank": 275}]),
        trainer_rows=list(trainer if trainer is not None else
                          [{"spell": MANA_SPELL, "skill_rank": 260}]),
        char_rows=chars,
        skill_rows=skill_rows,
        spell_rows=[{"name": "Ugga", "spell": s} for s in known],
        holding_rows=list(holdings),
        worn_rows=list(worn),
        vendor_rows=vendor, creature_rows=creature, object_rows=objects,
        guild_rows=list(guild), roster=names)


def goal(p, key):
    for g in p["goals"]:
        if g["key"] == key:
            return g
    raise AssertionError("no goal %r in %r" % (key, [g["key"] for g in p["goals"]]))


def sentences(node, out=None):
    """Every string this payload would put in front of a reader."""
    out = [] if out is None else out
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            sentences(value, out)
    elif isinstance(node, (list, tuple)):
        for value in node:
            sentences(value, out)
    return out


class ThePlanIsItsOwnSourceOfTruth(unittest.TestCase):
    def test_every_product_and_reagent_is_offered_to_the_reads(self):
        """The reads bind this list, so a name missing from it comes back with
        no row and renders as an item this realm does not carry."""
        names = raidgoals.plan_item_names()
        for recipe in raidgoals.RECIPES:
            self.assertIn(recipe.product, names, recipe.product)
            for reagent in recipe.reagents:
                self.assertIn(reagent.name, names, reagent.name)

    def test_the_name_list_has_no_duplicates(self):
        """Crystal Vial is in six recipes and must be bound once."""
        names = raidgoals.plan_item_names()
        self.assertEqual(len(names), len(set(names)))

    def test_every_craft_spell_is_offered_to_the_reads(self):
        self.assertEqual(sorted(raidgoals.craft_spells()),
                         sorted(r.spell for r in raidgoals.RECIPES))

    def test_every_recipe_names_a_trade_the_skill_table_knows(self):
        """professions.skill_id raises on a trade nobody has written down, and
        it is called on every recipe, so a typo here is a 503 on the tab."""
        for recipe in raidgoals.RECIPES:
            self.assertIsInstance(professions.skill_id(recipe.trade), int)

    def test_the_yield_is_the_floor_and_the_arithmetic_follows_it(self):
        """How much a cast makes is not readable on this deployment, so it is
        counted at one. `casts_for` is the single place that would change."""
        self.assertEqual(raidgoals.MAKES_ONE, 1)
        self.assertEqual(raidgoals.casts_for(0), 0)
        self.assertEqual(raidgoals.casts_for(-3), 0)
        self.assertEqual(raidgoals.casts_for(7), 7)


class WhoIsCountedFor(unittest.TestCase):
    """The goals are per member of the guild, and there is no guild yet."""

    def test_no_guild_falls_back_to_the_family_and_says_so(self):
        p = payload()
        self.assertIn("no guild yet", p["roster_line"])
        self.assertIn("5 members", p["roster_line"])

    def test_a_guild_replaces_the_family_without_an_edit(self):
        """A page that had to be rewritten on the day a guild is formed would
        be a page hardcoded to five with extra steps."""
        guild = [{"name": n, "level": 60, "guild_name": "The Hand",
                  "guildid": 1} for n in FAMILY + ["Kesh", "Mol", "Rin"]]
        p = payload(guild=guild, chars=[])
        self.assertIn("The Hand", p["roster_line"])
        self.assertIn("8 members", p["roster_line"])
        self.assertEqual(goal(p, "fireprot")["need"],
                         8 * raidgoals.FIRE_PROTECTION_PER_MEMBER)

    def test_the_family_in_two_guilds_is_not_one_roster(self):
        """Counting the union would invent a raid group nobody is in, and
        picking one would be this page choosing which guild is the real one."""
        guild = [{"name": "Ugga", "guild_name": "One", "guildid": 1},
                 {"name": "Bork", "guild_name": "Two", "guildid": 2}]
        chosen = raidgoals.roster_from_guild(guild, FAMILY)
        self.assertFalse(chosen["from_guild"])
        self.assertTrue(chosen["split"])
        self.assertEqual(chosen["names"], sorted(FAMILY))
        self.assertIn("more than one guild",
                      payload(guild=guild)["roster_line"])

    def test_a_member_with_no_characters_row_is_still_counted(self):
        """A guild member who has never logged in is somebody the raid still
        needs consumables for, and dropping them lowers every total."""
        p = payload(chars=[{"name": "Ugga", "level": 37, "class": "Druid"}])
        self.assertEqual(goal(p, "fireprot")["need"],
                         5 * raidgoals.FIRE_PROTECTION_PER_MEMBER)
        self.assertEqual(len(goal(p, "fireprot")["members"]), 5)

    def test_an_empty_roster_invents_no_counts(self):
        p = payload(roster=[], chars=[])
        self.assertTrue(p["empty_note"])
        self.assertIn("nothing here knows", p["line"])
        self.assertEqual(goal(p, "fireprot")["need"], 0)


class UnreachableIsNotShort(unittest.TestCase):
    """The distinction the operator's repair bot exists to prove."""

    def test_a_trade_nobody_holds_is_unreachable_and_names_the_trade(self):
        p = payload()
        repair = goal(p, "repair")
        self.assertEqual(repair["status"], raidgoals.UNREACHABLE)
        self.assertIn("nobody on this roster has engineering",
                      " ".join(repair["recipes"][0]["blocked"]))

    def test_an_unreachable_goal_says_it_is_not_a_farming_problem(self):
        """"40 short" and "nobody can make it" are the same arithmetic and
        completely different evenings."""
        self.assertIn("not a farming problem", goal(payload(), "repair")["line"])

    def test_the_headline_counts_what_cannot_be_finished_separately(self):
        self.assertIn("cannot be finished by this roster at all",
                      payload()["line"])

    def test_giving_somebody_engineering_makes_it_reachable_again(self):
        """The guard on the guard: if this were unreachable whatever the data
        said, the sentence above would be decoration."""
        p = payload(engineering=300, known=FLASK_SPELLS + (22704,))
        self.assertNotEqual(goal(p, "repair")["status"], raidgoals.UNREACHABLE)

    def test_an_unreachable_goal_still_lists_what_it_would_take(self):
        """A goal that vanished because it was impossible would read exactly
        like a goal already met."""
        card = goal(payload(), "repair")["recipes"][0]
        self.assertIn("Thorium Bar", [r["name"] for r in card["reagents"]])


class AnEmptyReadIsNotAnAnswer(unittest.TestCase):
    """Every read behind this page is guarded and a guard that fires returns
    []. An empty character_skills read looks exactly like a roster that has
    taken no professions."""

    def test_missing_skill_rows_block_rather_than_declare_unreachable(self):
        p = payload(skills_present=False)
        for g in p["goals"]:
            self.assertNotEqual(g["status"], raidgoals.UNREACHABLE, g["key"])

    def test_it_says_the_read_came_back_empty_rather_than_naming_a_person(self):
        card = goal(payload(skills_present=False), "flasks")["recipes"][0]
        self.assertIn("character_skills read came back empty",
                      " ".join(card["blocked"]))

    def test_a_populated_read_still_reaches_the_real_reasons(self):
        card = goal(payload(), "flasks")["recipes"][0]
        self.assertNotIn("came back empty", " ".join(card["blocked"]))


class TheStatusLadder(unittest.TestCase):
    def test_enough_held_is_met_even_with_a_blocked_recipe_under_it(self):
        """Nobody has to make one, so the recipe being blocked is not this
        goal's problem today."""
        held = [holding("Ugga", "Greater Fire Protection Potion", 25)]
        p = payload(holdings=held, known=())
        self.assertEqual(goal(p, "fireprot")["status"], raidgoals.MET)

    def test_enough_held_beats_unreachable_too(self):
        """Every rung below "met" is about MAKING the thing, and nobody has to
        make one when the roster already holds what the goal asks for. Asked
        the other way round, a guild that had bought a repair bot was told
        "nobody on this roster can make it, so the 1 it asks for is not a
        farming problem" over a goal that was finished, and would have gone
        looking for an Engineer it did not need."""
        held = [holding("Grug", raidgoals.FIELD_REPAIR_BOT, 1)]
        p = payload(holdings=held)
        repair = goal(p, "repair")
        self.assertEqual(repair["status"], raidgoals.MET)
        self.assertNotIn("not a farming problem", repair["line"])
        # The reason is still on the card: met is a fact about the count, and
        # "nobody here can make another" is a fact a reader still wants.
        self.assertIn("nobody on this roster has engineering",
                      " ".join(repair["recipes"][0]["blocked"]))

    def test_unreachable_outranks_blocked(self):
        """A trade nobody holds is not something more farming fixes, so it is
        the stronger answer of the two."""
        self.assertEqual(goal(payload(), "repair")["status"],
                         raidgoals.UNREACHABLE)

    def test_short_with_one_clear_recipe_is_short_and_not_blocked(self):
        p = payload(known=FLASK_SPELLS, alchemy=300)
        self.assertEqual(goal(p, "flasks")["status"], raidgoals.SHORT)

    def test_short_with_every_recipe_blocked_is_blocked(self):
        p = payload(known=())
        self.assertEqual(goal(p, "flasks")["status"], raidgoals.BLOCKED)

    def test_a_skill_too_low_blocks_and_states_both_numbers(self):
        p = payload(alchemy=150, known=FLASK_SPELLS + (HEALING_SPELL,))
        card = goal(p, "healing")["recipes"][0]
        self.assertEqual(card["status"], raidgoals.BLOCKED)
        self.assertIn("needs alchemy 275 and the best on this roster is 150",
                      " ".join(card["blocked"]))

    def test_the_order_is_worst_first_then_by_name(self):
        got = [g["status"] for g in payload()["goals"]]
        ranks = [raidgoals.STATUS_ORDER.index(s) for s in got]
        self.assertEqual(ranks, sorted(ranks))

    def test_the_order_it_used_is_printed_on_the_page(self):
        """A list in an order is read as a finding whether or not anybody
        meant it to be."""
        self.assertIn("cannot finish at all first", payload()["order"])


class ARankTheRealmDoesNotStateIsNotZero(unittest.TestCase):
    def test_an_absent_rank_says_so_rather_than_naming_a_number(self):
        """Zero would read as "anybody can make it", which is the opposite of
        what a missing row means."""
        card = goal(payload(recipes=[], trainer=[]), "flasks")["recipes"][0]
        self.assertIn("states no alchemy rank", card["rank_line"])
        self.assertNotIn("alchemy 0", card["rank_line"])

    def test_an_absent_rank_is_an_unknown_and_does_not_block_the_goal(self):
        """It blocks the PAGE from answering, not the guild from crafting. As
        a blocker it marked a flask goal blocked over something a 300
        alchemist who knew the recipe could have made that evening."""
        p = payload(recipes=[], trainer=[], alchemy=300, known=FLASK_SPELLS)
        card = goal(p, "flasks")["recipes"][0]
        self.assertIn("states no alchemy rank", " ".join(card["unknown"]))
        self.assertEqual(card["blocked"], [])
        self.assertEqual(goal(p, "flasks")["status"], raidgoals.SHORT)

    def test_a_recipe_item_states_the_rank_and_the_page_uses_it(self):
        card = goal(payload(), "healing")["recipes"][0]
        self.assertIn("asks for alchemy 275", card["rank_line"])

    def test_a_trainer_row_states_it_when_no_recipe_item_does(self):
        card = goal(payload(), "mana")["recipes"][0]
        self.assertIn("asks for alchemy 260", card["rank_line"])

    def test_the_recipe_item_wins_over_the_trainer_row(self):
        """It is the row naming the rank beside the recipe a reader would go
        and find, so the two disagreeing is not a coin toss."""
        p = payload(recipes=[{"teaches": MANA_SPELL, "skill_rank": 999}],
                    trainer=[{"spell": MANA_SPELL, "skill_rank": 260}])
        self.assertIn("alchemy 999", goal(p, "mana")["recipes"][0]["rank_line"])


class AnItemThisRealmDoesNotCarry(unittest.TestCase):
    """The plan is hand written and cannot be checked against this realm, so
    the realm gets to refuse a name out loud."""

    def test_a_missing_reagent_is_named_rather_than_counted_as_zero(self):
        card = goal(payload(drop=("Icecap",)), "mana")["recipes"][0]
        self.assertIn("carries no item called Icecap", " ".join(card["blocked"]))

    def test_the_missing_reagents_own_row_says_it_cannot_be_counted(self):
        card = goal(payload(drop=("Icecap",)), "mana")["recipes"][0]
        row = [r for r in card["reagents"] if r["name"] == "Icecap"][0]
        self.assertFalse(row["known_here"])
        self.assertIn("no item under that name", row["line"])

    def test_a_missing_product_says_so_on_its_own_row(self):
        p = payload(drop=("Major Mana Potion",))
        row = goal(p, "mana")["products"][0]
        self.assertFalse(row["known_here"])
        self.assertIn("no item under that name", row["line"])

    def test_two_rows_under_one_name_are_reported_and_not_resolved(self):
        """A holding of it cannot be matched to one entry, so every count on
        that item would be unprovable."""
        card = goal(payload(twin=("Dreamfoil",)), "flasks")["recipes"][0]
        self.assertIn("more than one item called Dreamfoil",
                      " ".join(card["blocked"]))


class WhereAReagentComesFrom(unittest.TestCase):
    def test_the_three_tables_are_three_different_answers(self):
        card = goal(payload(), "fireprot")["recipes"][0]
        where = {r["name"]: r["source"] for r in card["reagents"]}
        self.assertIn("sold by a vendor", where["Crystal Vial"])
        self.assertIn("dropped by a creature", where["Elemental Fire"])
        self.assertIn("gathered from a node", where["Dreamfoil"])

    def test_a_reagent_in_none_of_them_says_it_is_unanswered_here(self):
        """Not "cannot be got". Nothing this page READS accounts for it, and
        the two send a reader to opposite places."""
        card = goal(payload(sources=False), "fireprot")["recipes"][0]
        self.assertIn("nothing this page reads sells, drops or grows",
                      " ".join(card["unknown"]))

    def test_an_unaccounted_source_is_an_unknown_and_not_a_blocker(self):
        """The page not knowing where a herb grows does not stop an alchemist
        who already has forty of them. Folding this into the blockers marked a
        goal blocked over the page's own blind spot."""
        card = goal(payload(sources=False), "fireprot")["recipes"][0]
        self.assertNotIn("sells, drops or grows", " ".join(card["blocked"]))

    def test_a_reagent_that_is_itself_a_craft_is_not_called_sourceless(self):
        """Stonescale Oil is in no vendor, loot or node table for the same
        reason a flask is not: nothing drops it, somebody makes it. Reported
        as sourceless it sent a reader hunting for something unhuntable."""
        card = [c for c in goal(payload(), "flasks")["recipes"]
                if c["product"] == raidgoals.FLASK_OF_THE_TITANS][0]
        self.assertNotIn("grows Stonescale Oil", " ".join(card["blocked"]))
        row = [r for r in card["reagents"] if r["name"] == "Stonescale Oil"][0]
        self.assertIn("made rather than found", row["source"])

    def test_the_chain_is_followed_one_craft_deep(self):
        card = [c for c in goal(payload(), "flasks")["recipes"]
                if c["product"] == raidgoals.FLASK_OF_THE_TITANS][0]
        row = [r for r in card["reagents"] if r["name"] == "Stonescale Oil"][0]
        self.assertEqual([sub["name"] for sub in row["made"]],
                         ["Stonescale Eel"])

    def test_and_no_further_than_one(self):
        """`depth` is what keeps a cycle in the recipe table from hanging the
        endpoint, and nothing below the second level is claimed."""
        card = [c for c in goal(payload(), "flasks")["recipes"]
                if c["product"] == raidgoals.FLASK_OF_THE_TITANS][0]
        row = [r for r in card["reagents"] if r["name"] == "Stonescale Oil"][0]
        for sub in row["made"]:
            self.assertEqual(sub["made"], [])

    def test_the_sub_recipe_sentence_agrees_with_its_own_count(self):
        """It is assembled around a number, so it reads as English at one and
        at twelve or it reads as English at neither."""
        card = [c for c in goal(payload(), "flasks")["recipes"]
                if c["product"] == raidgoals.FLASK_OF_THE_TITANS][0]
        row = [r for r in card["reagents"] if r["name"] == "Stonescale Oil"][0]
        self.assertIn("the 15 that are short are each an alchemy craft",
                      row["made_line"])
        self.assertIn("the one that is short is itself an alchemy craft",
                      raidgoals._made_line("Stonescale Oil", 1, "alchemy"))

    def test_the_sub_recipe_is_counted_against_the_shortfall_above_it(self):
        """Three oils per flask and five flasks short is fifteen oils, and
        fifteen eels behind them."""
        card = [c for c in goal(payload(), "flasks")["recipes"]
                if c["product"] == raidgoals.FLASK_OF_THE_TITANS][0]
        row = [r for r in card["reagents"] if r["name"] == "Stonescale Oil"][0]
        self.assertEqual(row["need"], 15)
        self.assertEqual(row["made"][0]["need"], 15)


class WhatTheRosterAlreadyHolds(unittest.TestCase):
    def test_bags_and_bank_both_count_toward_a_goal(self):
        p = payload(holdings=[holding("Ugga", "Major Mana Potion", 4),
                              holding("Bork", "Major Mana Potion", 6, slot=40)])
        self.assertEqual(goal(p, "mana")["held"], 10)

    def test_the_bank_half_is_reported_separately(self):
        """A stack in a bank in a capital is not in the raid, so "has five"
        and "has five, all banked" are different evenings."""
        p = payload(holdings=[holding("Bork", "Major Mana Potion", 6, slot=40)])
        row = [m for m in goal(p, "mana")["members"] if m["who"] == "Bork"][0]
        self.assertEqual(row["banked"], 6)
        self.assertIn("in the bank", row["line"])

    def test_worn_gear_is_not_something_anybody_holds(self):
        """bank.py places a paper-doll slot as neither carried nor banked, and
        that is right here too."""
        p = payload(holdings=[holding("Bork", "Major Mana Potion", 6, slot=5)])
        self.assertEqual(goal(p, "mana")["held"], 0)

    def test_a_reagent_already_held_reduces_what_is_short(self):
        p = payload(holdings=[holding("Ugga", "Crystal Vial", 40)])
        card = goal(p, "fireprot")["recipes"][0]
        row = [r for r in card["reagents"] if r["name"] == "Crystal Vial"][0]
        self.assertEqual(row["held"], 40)
        self.assertEqual(row["short"], 0)

    def test_the_working_behind_a_total_is_printed(self):
        """A total with no working is a number nobody can disagree with, and
        this one is a convention multiplied by a roster."""
        line = goal(payload(), "fireprot")["need_line"]
        self.assertIn("5 per member", line)
        self.assertIn("5 members", line)
        self.assertIn("convention", line)


class ThreeFlasksSatisfyOneGoal(unittest.TestCase):
    def test_each_flask_gets_its_own_recipe_and_they_are_not_summed(self):
        """A single reagent list under a goal three items satisfy would be one
        of the three presented as the answer, and a reader would farm to it."""
        flasks = goal(payload(), "flasks")
        self.assertEqual(len(flasks["recipes"]), 3)
        self.assertIn("alternatives and not a sum", flasks["recipes_line"])

    def test_all_three_count_toward_the_same_held_total(self):
        p = payload(holdings=[
            holding("Ugga", raidgoals.FLASK_OF_SUPREME_POWER, 2),
            holding("Bork", raidgoals.FLASK_OF_THE_TITANS, 1)])
        self.assertEqual(goal(p, "flasks")["held"], 3)

    def test_the_mix_is_broken_out_so_a_reader_can_choose(self):
        p = payload(holdings=[holding("Ugga", raidgoals.FLASK_OF_SUPREME_POWER, 2)])
        rows = {r["name"]: r["held"] for r in goal(p, "flasks")["products"]}
        self.assertEqual(rows[raidgoals.FLASK_OF_SUPREME_POWER], 2)
        self.assertEqual(rows[raidgoals.FLASK_OF_THE_TITANS], 0)

    def test_which_flask_suits_whom_is_not_decided_here(self):
        """Spec is not readable from any table this service has, so a class to
        flask mapping would be this page inventing one."""
        said = " ".join(sentences(payload()))
        for invented in ("tank should", "healers should", "your spec"):
            self.assertNotIn(invented, said)


class FireResistanceIsMeasuredAndNotScored(unittest.TestCase):
    def test_it_sums_the_fire_res_of_worn_items(self):
        p = payload(worn=[{"name": "Grug", "fire_res": 8},
                          {"name": "Grug", "fire_res": 5}])
        row = [m for m in goal(p, "fireres")["members"]
               if m["who"] == "Grug"][0]
        self.assertEqual(row["held"], 13)

    def test_nobody_is_called_short_because_nobody_here_decides_who_tanks(self):
        p = payload(worn=[])
        fire = goal(p, "fireres")
        self.assertEqual(fire["need"], 0)
        for member in fire["members"]:
            self.assertEqual(member["short"], 0)

    def test_the_convention_is_printed_as_a_convention(self):
        line = goal(payload(), "fireres")["need_line"]
        self.assertIn("this realm's tables state no requirement", line)
        self.assertIn("Who tanks is not decided on this page", line)

    def test_a_roster_wearing_none_says_so_rather_than_printing_zeroes(self):
        self.assertIn("not one of the 5 is wearing anything",
                      goal(payload(worn=[]), "fireres")["line"])


class WhatTheFooterMustAdmit(unittest.TestCase):
    def test_the_weakest_claim_is_stated_first(self):
        """A reader who takes a hand-written reagent list for a measurement
        will farm to it, so it cannot be the last sentence of a long footer."""
        self.assertTrue(
            payload()["basis"].startswith("THE REAGENT LISTS ARE NOT MEASURED"))

    def test_it_names_the_reason_the_reagents_cannot_be_read(self):
        basis = payload()["basis"]
        self.assertIn("Spell.dbc", basis)
        self.assertIn("spell_dbc", basis)

    def test_it_admits_the_yield_and_which_way_it_leans(self):
        basis = payload()["basis"]
        self.assertIn("one item per cast", basis)
        self.assertIn("double what is needed", basis)

    def test_it_lists_the_tables_the_measured_half_came_from(self):
        basis = payload()["basis"]
        for table in ("character_skills", "character_spell", "item_template",
                      "trainer_spell", "character_inventory", "npc_vendor",
                      "creature_loot_template", "gameobject_loot_template"):
            self.assertIn(table, basis, table)

    def test_it_says_what_is_not_asked_at_all(self):
        basis = payload()["basis"]
        self.assertIn("what anything costs", basis)
        self.assertIn("who tanks", basis)


class OneRaidIsModelledAndFourAreNot(unittest.TestCase):
    def test_every_raid_at_the_cap_gets_a_row(self):
        """A short list reads exactly like a complete one, so the only thing
        that can say Blackwing Lair was never asked about is a row."""
        names = [r["name"] for r in payload()["others"]]
        self.assertEqual(names, [r["name"] for r in raidgoals.RAIDS])
        self.assertIn("Blackwing Lair", names)

    def test_the_unmodelled_ones_say_they_are_unmodelled(self):
        for row in payload()["others"]:
            if row["name"] != "Molten Core":
                self.assertIn("not modelled", row["line"])

    def test_the_two_that_are_easy_to_assume_are_named_and_ruled_out(self):
        """Onyxia and Naxxramas in this client are the level 80 rebuilds, and
        the realm's own worldserver override config proves it against
        creature_template rather than from memory."""
        line = payload()["others_line"]
        self.assertIn("Onyxia", line)
        self.assertIn("Naxxramas", line)
        self.assertIn("level 80 rebuilds", line)

    def test_molten_core_is_named_by_map_id_so_it_can_be_checked(self):
        self.assertEqual(raidgoals.MOLTEN_CORE, 409)
        self.assertIn("map 409", payload()["raid_line"])

    def test_the_raid_gates_nobody_and_the_page_says_so(self):
        self.assertIn("gates nobody on consumables", payload()["raid_line"])


class EverySentenceIsReadable(unittest.TestCase):
    def test_nothing_a_reader_sees_is_none_or_empty_where_it_matters(self):
        p = payload()
        for key in ("line", "roster_line", "raid_line", "order", "basis",
                    "others_line"):
            self.assertTrue(p[key], key)
        for g in p["goals"]:
            self.assertTrue(g["line"], g["key"])
            self.assertTrue(g["need_line"], g["key"])

    def test_nothing_counts_one_as_a_plural(self):
        """Every count here comes from a list the world handed over, so every
        one of them can be one, and "1 members" is the sentence that appears
        on the day something has gone wrong."""
        for said in sentences(payload(roster=["Ugga"],
                                      chars=[{"name": "Ugga", "level": 60,
                                              "class": "Druid"}])):
            for wrong in ("1 members", "1 goals", "1 casts", "1 blockers",
                          "1 items", "1 dungeons"):
                self.assertNotIn(wrong, said, said)

    def test_no_article_disagrees_with_the_word_after_it(self):
        """The trade names are DATA and the sentences are written around them,
        which is how "a engineering craft" reached a rendered page."""
        for said in sentences(payload()):
            for wrong in ("a engineering", "a alchemy", "a enchanting",
                          "a inscription", "a item"):
                self.assertNotIn(wrong, said, said)

    def test_no_em_dash_reaches_a_reader(self):
        """The house voice on this site uses none, in code or in prose.

        Written as an escape rather than as the character, so this file stays
        pure ASCII: a guard against a character is not a licence to be the one
        place in the directory carrying one.
        """
        for said in sentences(payload()):
            self.assertNotIn("\u2014", said, said)

if __name__ == "__main__":
    unittest.main()

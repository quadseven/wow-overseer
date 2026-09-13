"""The Armory profile: the tooltip, the stat block, the doll and the grid.

test_armory.py holds the rules of the first cut (what an empty slot is, how
points are counted). These are the rules the profile added on top, and
again most of them are rules about NOT lying: a "Belt of the Tiger" has the
Tiger's stats and not the template's none, a set piece names the pieces the
character is missing, a stat the world has not saved says so rather than
showing zero, and the talent grid has every talent of the tree at its true
place - not only the learned ones.

Run against the COMMITTED item books and talents.json rather than stubs,
for the reason test_armory.py gives: the files are the feature.

Ticket: infra#3139.
"""
import importlib.util
import pathlib
import unittest

import armory
import family

HERE = pathlib.Path(__file__).resolve().parent.parent
BOOK = armory.TalentBook.load(str(HERE))
ITEMS = armory.ItemBook.load(str(HERE))
FIRST = family.roster()[0]

WARRIOR, PRIEST = 1, 5

# Real rows out of the live world database, verbatim, so the numbers below
# are the numbers a person would check against the game.
SCOUTING_BELT = dict(
    entry=6581, item_name="Scouting Belt", quality=2, item_level=21, required_level=16,
    max_durability=35, displayid=17127, **{"class": 4}, subclass=2, inventory_type=6,
    armor=45, block=0, bonding=2, itemset=0, sell_price=422, allowable_class=-1,
    description="", dmg_min1=0, dmg_max1=0, delay=0,
    holy_res=0, fire_res=0, nature_res=0, frost_res=0, shadow_res=0, arcane_res=0,
)
DEFIAS_GLOVES = dict(
    entry=10401, item_name="Blackened Defias Gloves", quality=2, item_level=18,
    required_level=13, max_durability=30, displayid=27946, **{"class": 4}, subclass=2,
    inventory_type=10, armor=46, block=0, bonding=2, itemset=161, sell_price=255,
    allowable_class=-1, description="", dmg_min1=0, dmg_max1=0, delay=0,
    holy_res=0, fire_res=0, nature_res=0, frost_res=0, shadow_res=0, arcane_res=0,
    stat_type1=4, stat_value1=3, stat_type2=7, stat_value2=1,
)
IRONPATCH = dict(
    entry=12976, item_name="Ironpatch Blade", quality=3, item_level=20, required_level=15,
    max_durability=65, displayid=8272, **{"class": 2}, subclass=7, inventory_type=13,
    armor=0, block=0, bonding=1, itemset=0, sell_price=1770, allowable_class=-1,
    description="", dmg_min1=24, dmg_max1=46, delay=2600,
    holy_res=0, fire_res=0, nature_res=0, frost_res=0, shadow_res=0, arcane_res=0,
    stat_type1=4, stat_value1=4, stat_type2=7, stat_value2=2,
    # Sharpened: the permanent enchant in slot 0.
    enchantments="14 0 0 " + "0 0 0 " * 11,
)


def char(**kw):
    row = {"name": FIRST, "level": 26, "race": 1, "class": WARRIOR, "gender": 0,
           "online": 1, "activeTalentGroup": 0, "totalKills": 0, "guild": None}
    row.update(kw)
    return row


def worn(slot, template, **kw):
    row = {"name": FIRST, "slot": slot, "durability": 20, "enchantments": None,
           "random_property_id": 0}
    row.update(template)
    row.update(kw)
    return row


def build(equipment=(), **rest):
    rest.setdefault("char_rows", [char()])
    return armory.build_armory(rest.pop("char_rows"), list(equipment), rest.pop("talent_rows", []),
                               BOOK, ITEMS, **rest)


def member(payload, name=FIRST):
    return next(m for m in payload["members"] if m["name"] == name)


def slot_of(m, slot_name):
    return next(s for s in m["slots"] if s["slot"] == slot_name)


class TheTooltipTest(unittest.TestCase):
    def test_the_lines_come_in_the_order_the_game_draws_them(self):
        t = slot_of(member(build([worn(5, SCOUTING_BELT)])), "waist")["tooltip"]
        self.assertEqual(t["name"], "Scouting Belt")
        self.assertEqual(t["item_level"], 21)
        self.assertEqual(t["binding"], "Binds when equipped")
        self.assertEqual((t["slot"], t["kind"]), ("Waist", "Leather"))
        self.assertEqual(t["armor"], 45)
        self.assertEqual(t["durability"], "20 / 35")
        self.assertEqual(t["requires_level"], 16)
        self.assertEqual(t["sell_price"], {"gold": 0, "silver": 4, "copper": 22})

    def test_a_random_property_gives_the_item_its_suffix_and_its_stats(self):
        """The template of a Scouting Belt has no stats at all. Every one
        the family wears is 'of the X', and the X is the whole point."""
        # of the Tiger: enchants 76 (+3 Agility) and 70 (+3 Strength) in the
        # property slots, exactly as item_instance stores them.
        row = worn(5, SCOUTING_BELT, random_property_id=643,
                   enchantments="0 0 0 " * 7 + "76 0 0 70 0 0 " + "0 0 0 " * 3)
        s = slot_of(member(build([row])), "waist")
        self.assertTrue(s["name"].startswith("Scouting Belt of "), s["name"])
        self.assertEqual(s["tooltip"]["stats"], ["+3 Agility", "+3 Strength"])

    def test_a_random_suffix_is_scaled_by_the_items_level(self):
        """A WotLK-era 'of the Monkey' carries no fixed amount: it is a
        percentage of RandPropPoints for the item's level, quality and slot
        group - the same arithmetic the core does when the item is put on."""
        # Suffix 5 (of the Monkey): enchants 2802 at 6666/10000 and 2803 at
        # 10000/10000, both agility/stamina stats with amount 0.
        row = worn(5, SCOUTING_BELT, random_property_id=-5,
                   enchantments="0 0 0 " * 7 + "2802 0 0 2803 0 0 " + "0 0 0 " * 3)
        s = slot_of(member(build([row])), "waist")
        self.assertEqual(s["name"], "Scouting Belt of the Monkey")
        # Level 21 uncommon, waist -> group 1 -> 5 points; 6666 * 5 // 10000 = 3,
        # 10000 * 5 // 10000 = 5.
        factor = armory.suffix_factor(row, ITEMS)
        self.assertEqual(factor, 5)
        self.assertEqual(sorted(s["tooltip"]["stats"]), ["+3 Agility", "+5 Stamina"])

    def test_a_set_piece_lists_the_set_and_which_pieces_are_worn(self):
        set_rows = [{"entry": e, "item_name": n} for e, n in [
            (10399, "Blackened Defias Armor"), (10400, "Blackened Defias Leggings"),
            (10401, "Blackened Defias Gloves"), (10402, "Blackened Defias Boots"),
            (10403, "Blackened Defias Belt")]]
        t = slot_of(member(build([worn(9, DEFIAS_GLOVES)], set_rows=set_rows)),
                    "hands")["tooltip"]
        self.assertEqual(t["set"]["name"], "Defias Leather")
        self.assertEqual((t["set"]["worn"], t["set"]["total"]), (1, 5))
        self.assertEqual([p["worn"] for p in t["set"]["pieces"]].count(True), 1)
        self.assertIn("Blackened Defias Leggings", [p["name"] for p in t["set"]["pieces"]])
        first = t["set"]["bonuses"][0]
        self.assertEqual((first["threshold"], first["active"], first["text"]),
                         (2, False, "+10 Armor."))

    def test_a_set_bonus_lights_up_when_enough_pieces_are_worn(self):
        belt = dict(DEFIAS_GLOVES, entry=10403, item_name="Blackened Defias Belt",
                    inventory_type=6)
        t = slot_of(member(build([worn(9, DEFIAS_GLOVES), worn(5, belt)])), "hands")["tooltip"]
        self.assertEqual(t["set"]["worn"], 2)
        self.assertTrue(t["set"]["bonuses"][0]["active"])
        self.assertFalse(t["set"]["bonuses"][1]["active"])

    def test_a_weapon_shows_its_damage_and_speed_and_its_enchant_by_name(self):
        t = slot_of(member(build([worn(15, IRONPATCH)])), "main hand")["tooltip"]
        self.assertEqual((t["slot"], t["kind"]), ("One-Hand", "Sword"))
        self.assertEqual(t["damage"], {"min": 24, "max": 46, "speed": 2.6,
                                       "dps": 13.5, "elemental": None})
        self.assertEqual(t["stats"], ["+4 Strength", "+2 Stamina"])
        self.assertEqual(t["enchant"], ["Sharpened (+4 Damage)"])
        self.assertEqual(t["binding"], "Binds when picked up")

    def test_an_equip_spell_is_the_spells_text_not_its_id(self):
        # Riverside Staff: spell 21618 on equip -> "Restores 5 mana per 5 sec."
        row = worn(15, dict(IRONPATCH, spellid_1=21618, spelltrigger_1=1))
        t = slot_of(member(build([row])), "main hand")["tooltip"]
        self.assertEqual(t["effects"], ["Equip: Restores 5 mana per 5 sec."])

    def test_an_equip_spell_the_book_does_not_know_still_says_which(self):
        row = worn(15, dict(IRONPATCH, spellid_1=999999, spelltrigger_1=1))
        t = slot_of(member(build([row])), "main hand")["tooltip"]
        self.assertEqual(t["effects"], ["Equip: spell #999999"])

    def test_a_rating_stat_is_a_green_equip_line_not_a_white_one(self):
        row = worn(5, dict(SCOUTING_BELT, stat_type1=32, stat_value1=10))
        t = slot_of(member(build([row])), "waist")["tooltip"]
        self.assertEqual(t["stats"], [])
        self.assertEqual(t["effects"], ["Equip: Improves critical strike rating by 10."])

    def test_a_class_restricted_item_names_the_classes(self):
        row = worn(5, dict(SCOUTING_BELT, allowable_class=1 << 4))
        t = slot_of(member(build([row])), "waist")["tooltip"]
        self.assertEqual(t["classes"], ["Priest"])
        row = worn(5, dict(SCOUTING_BELT, allowable_class=-1))
        self.assertIsNone(slot_of(member(build([row])), "waist")["tooltip"]["classes"])

    def test_the_icon_is_the_displays_and_a_custom_item_has_none(self):
        s = slot_of(member(build([worn(5, SCOUTING_BELT)])), "waist")
        self.assertEqual(s["icon"], "inv_belt_16")
        s = slot_of(member(build([worn(5, dict(SCOUTING_BELT, displayid=0))])), "waist")
        self.assertIsNone(s["icon"])

    def test_the_per_item_stat_sums_do_not_leak_into_the_payload(self):
        s = slot_of(member(build([worn(5, SCOUTING_BELT)])), "waist")
        self.assertNotIn("_stats", s)
        self.assertNotIn("_armor", s)


SAVED = {"name": FIRST, "maxhealth": 1200, "maxpower1": 0, "maxpower2": 1000,
         "maxpower4": 0, "maxpower7": 0, "strength": 90, "agility": 50, "stamina": 100,
         "intellect": 25, "spirit": 35, "armor": 1500, "blockPct": 5.0, "dodgePct": 6.25,
         "parryPct": 5.0, "critPct": 7.123456, "rangedCritPct": 4.0, "spellCritPct": 1.0,
         "attackPower": 250, "rangedAttackPower": 70, "spellPower": 0}
BASE = {"race": 1, "class": WARRIOR, "level": 26, "health": 296, "mana": 0,
        "strength": 55, "agility": 40, "stamina": 51, "intellect": 23, "spirit": 28}


class TheStatBlockTest(unittest.TestCase):
    def rows(self, stats):
        return {r["key"]: r for r in stats["rows"]}

    def test_the_worlds_own_saved_numbers_win_when_they_exist(self):
        stats = member(build(stats_rows=[SAVED], base_rows=[BASE]))["stats"]
        self.assertEqual(stats["source"], "saved")
        rows = self.rows(stats)
        self.assertEqual(rows["health"]["value"], 1200)
        # Rage is stored x10.
        self.assertEqual((rows["power"]["label"], rows["power"]["value"]), ("Rage", 100))
        self.assertEqual(rows["dodge"]["value"], 6.25)
        self.assertEqual(rows["melee_crit"]["value"], 7.12)
        self.assertEqual(rows["attack_power"]["value"], 250)

    def test_without_a_save_the_base_stats_are_base_plus_gear(self):
        belt = worn(5, dict(SCOUTING_BELT, stat_type1=7, stat_value1=6, stat_type2=4, stat_value2=3))
        stats = member(build([belt], base_rows=[BASE]))["stats"]
        self.assertEqual(stats["source"], "derived")
        rows = self.rows(stats)
        self.assertEqual(rows["stamina"]["value"], 57)
        self.assertEqual(rows["strength"]["value"], 58)
        # 296 base + 20 + (57 - 20) * 10
        self.assertEqual(rows["health"]["value"], 686)
        # Warrior: 3 * level + 2 * strength - 20
        self.assertEqual(rows["attack_power"]["value"], 3 * 26 + 2 * 58 - 20)
        self.assertEqual(rows["armor"]["value"], 45 + 40 * 2)
        self.assertIn("buffs and talents not counted", rows["stamina"]["note"])

    def test_a_suffix_counts_toward_the_derived_stats(self):
        """The Tiger's +3 Strength is on the item instance, not the template,
        and a stat block that ignored it would be quietly short."""
        row = worn(5, SCOUTING_BELT, random_property_id=643,
                   enchantments="0 0 0 " * 7 + "76 0 0 70 0 0 " + "0 0 0 " * 3)
        rows = self.rows(member(build([row], base_rows=[BASE]))["stats"])
        self.assertEqual(rows["strength"]["value"], 58)
        self.assertEqual(rows["agility"]["value"], 43)

    def test_what_cannot_be_derived_is_unavailable_not_zero(self):
        rows = self.rows(member(build(base_rows=[BASE]))["stats"])
        for key in ("block", "dodge", "parry", "melee_crit", "ranged_crit", "spell_crit"):
            self.assertIsNone(rows[key]["value"], key)
            self.assertEqual(rows[key]["note"], "not saved by the world yet")

    def test_a_mana_class_gets_mana_from_intellect(self):
        priest = char(**{"class": PRIEST, "level": 20})
        base = dict(BASE, **{"class": PRIEST, "level": 20, "mana": 300, "intellect": 40})
        rows = self.rows(member(build(char_rows=[priest], base_rows=[base]))["stats"])
        self.assertEqual(rows["power"]["label"], "Mana")
        self.assertEqual(rows["power"]["value"], 300 + 20 + 20 * 15)

    def test_no_base_row_at_all_means_every_line_says_so(self):
        """A level the world tables do not know: nothing can be derived, and
        a gear-only stamina would read as the whole."""
        stats = member(build([worn(5, SCOUTING_BELT)]))["stats"]
        self.assertEqual(stats["source"], "unavailable")
        self.assertTrue(all(r["value"] is None for r in stats["rows"]))
        self.assertEqual(len(stats["rows"]), 17)


class TheStatSourceTest(unittest.TestCase):
    """WHERE A STAT CAME FROM IS PART OF THE STAT, and the redesign is where
    it stopped being a note nobody could see and became a label the block is
    coloured by.

    "Attack Power 214" read off the world's own save and "Attack Power 214"
    worked out here from base stats and gear are different claims: the second
    is missing every buff and every talent. A block that prints them in one
    ink invites a comparison between two numbers that do not mean the same
    thing, and the reader has no way to know they were invited."""

    def rows(self, stats):
        return {r["key"]: r for r in stats["rows"]}

    def test_a_saved_block_labels_every_row_saved(self):
        stats = member(build(stats_rows=[SAVED], base_rows=[BASE]))["stats"]
        self.assertTrue(all(r["source"] == armory.STAT_SAVED
                            for r in stats["rows"]))

    def test_a_derived_block_still_has_rows_that_are_not_derived(self):
        """THE ROW IS NOT THE BLOCK. Dodge and parry cannot be derived at all
        without the rating tables, and "derived, and 0" is exactly the lie
        this arrangement exists to stop."""
        stats = member(build([worn(5, SCOUTING_BELT)], base_rows=[BASE]))["stats"]
        self.assertEqual(stats["source"], armory.STAT_DERIVED)
        rows = self.rows(stats)
        self.assertEqual(rows["attack_power"]["source"], armory.STAT_DERIVED)
        for key in ("block", "dodge", "parry", "melee_crit"):
            self.assertEqual(rows[key]["source"], armory.STAT_UNAVAILABLE, key)

    def test_every_row_carries_a_gloss_that_says_what_its_word_means(self):
        """The colour is not a code the reader is asked to crack."""
        for stats in (member(build(stats_rows=[SAVED], base_rows=[BASE]))["stats"],
                      member(build([worn(5, SCOUTING_BELT)], base_rows=[BASE]))["stats"],
                      member(build([worn(5, SCOUTING_BELT)]))["stats"]):
            self.assertTrue(stats["gloss"])
            for row in stats["rows"]:
                self.assertEqual(row["gloss"],
                                 armory.STAT_SOURCE_GLOSS[row["source"]])

    def test_a_missing_stat_prints_the_word_and_can_never_print_zero(self):
        """The page is handed a string precisely so there is no branch left in
        it that could turn a null into a 0 - and 0 attack power is a number
        somebody acts on."""
        rows = self.rows(member(build(base_rows=[BASE]))["stats"])
        for key in ("block", "dodge", "parry", "melee_crit"):
            self.assertIsNone(rows[key]["value"], key)
            self.assertEqual(rows[key]["reading"], armory.STAT_UNAVAILABLE, key)

    def test_a_real_zero_still_prints_as_a_zero(self):
        """The rule is "a null is not a zero", not "a zero is suspicious".
        A saved 0.0 dodge is the world's own answer."""
        saved = dict(SAVED, dodgePct=0.0)
        rows = self.rows(member(build(stats_rows=[saved], base_rows=[BASE]))["stats"])
        self.assertEqual(rows["dodge"]["reading"], "0")
        self.assertEqual(rows["dodge"]["source"], armory.STAT_SAVED)

    def test_a_whole_percentage_is_not_printed_with_a_trailing_zero(self):
        """"4.0% dodge" is a percentage nobody writes that way, and the page
        no longer formats numbers so this is the only place it can be got
        right."""
        saved = dict(SAVED, dodgePct=4.0, critPct=7.5)
        rows = self.rows(member(build(stats_rows=[saved], base_rows=[BASE]))["stats"])
        self.assertEqual(rows["dodge"]["reading"], "4")
        self.assertEqual(rows["melee_crit"]["reading"], "7.5")


class TheHeaderTest(unittest.TestCase):
    def test_guild_and_kills_come_through_when_they_exist(self):
        m = member(build(char_rows=[char(guild="Ashenvale", totalKills=12)]))
        self.assertEqual(m["guild"], "Ashenvale")
        self.assertEqual(m["honorable_kills"], 12)

    def test_no_guild_is_none_not_a_placeholder(self):
        m = member(build())
        self.assertIsNone(m["guild"])
        self.assertEqual(m["honorable_kills"], 0)

    def test_the_portrait_is_the_race_gender_and_class_icons(self):
        m = member(build(char_rows=[char(race=7, gender=1, **{"class": PRIEST})]))
        self.assertEqual(m["portrait"], {"race_icon": "achievement_character_gnome_female",
                                         "class_icon": "classicon_priest"})
        self.assertEqual(m["gender"], "female")
        self.assertEqual(m["class_colour"], "#ffffff")

    def test_a_race_the_table_does_not_know_has_no_portrait_rather_than_a_wrong_one(self):
        m = member(build(char_rows=[char(race=99)]))
        self.assertIsNone(m["portrait"]["race_icon"])


class TheDollTest(unittest.TestCase):
    def test_the_two_columns_are_exactly_the_slot_list(self):
        """Every slot on one side or the other, none twice, none missing:
        the page draws only what these two lists name."""
        both = armory.DOLL_LEFT + armory.DOLL_RIGHT
        self.assertEqual(sorted(both), sorted(armory.EQUIPPED_SLOTS))
        self.assertEqual(len(both), len(set(both)))

    def test_the_layout_is_sent_with_the_payload(self):
        p = build()
        self.assertEqual(p["doll"], {"left": armory.DOLL_LEFT, "right": armory.DOLL_RIGHT})


class TheGridTest(unittest.TestCase):
    def test_every_talent_of_the_tree_is_on_the_grid_learned_or_not(self):
        spec = member(build(talent_rows=[{"name": FIRST, "spell": 12308, "specMask": 1}]))["spec"]
        protection = spec["trees"][2]
        self.assertEqual(protection["name"], "Protection")
        self.assertEqual(len(protection["talents"]), 1)
        self.assertGreater(len(protection["grid"]), 20)
        puncture = next(t for t in protection["grid"] if t["name"] == "Puncture")
        self.assertEqual((puncture["rank"], puncture["max_rank"]), (1, 3))
        self.assertTrue(all(t["rank"] == 0 for t in protection["grid"] if t["name"] != "Puncture"))
        self.assertEqual((protection["rows"], protection["cols"]), (11, 4))

    def test_a_grid_talent_has_a_place_an_icon_and_its_prerequisite(self):
        spec = member(build())["spec"]
        arms = spec["trees"][0]
        for t in arms["grid"]:
            self.assertIn(t["row"], range(11))
            self.assertIn(t["col"], range(4))
            self.assertTrue(t["icon"], t["name"])
        with_req = [t for t in arms["grid"] if t["requires"]]
        self.assertTrue(with_req)
        ids = {t["id"] for t in arms["grid"]}
        for t in with_req:
            for req_id, req_rank in t["requires"]:
                self.assertIn(req_id, ids, "an arrow must point at a talent of the same tree")
                self.assertGreaterEqual(req_rank, 1)

    def test_every_tree_has_an_icon(self):
        for tid, tree in BOOK.trees.items():
            self.assertTrue(tree["icon"], tid)


class TheItemBookTest(unittest.TestCase):
    def test_the_book_covers_what_the_family_actually_wear(self):
        for display in (17127, 27946, 8272, 14260, 19699):
            self.assertIn(display, ITEMS.icons)

    def test_spell_text_carries_no_unresolved_effect_macros_for_the_common_kinds(self):
        """$s1 and $d are the two macros almost every item spell uses; a
        file that left them in would put '$s1' on a tooltip."""
        for spell, text in ITEMS.spells.items():
            self.assertNotIn("$s1", text, spell)
            self.assertNotIn("$d", text, spell)

    def test_every_random_property_and_suffix_names_enchants_the_book_has(self):
        for pid, (_, enchants) in ITEMS.properties.items():
            for e in enchants:
                self.assertIn(e, ITEMS.enchants, (pid, e))
        for sid, (_, enchants) in ITEMS.suffixes.items():
            for e, _pct in enchants:
                self.assertIn(e, ITEMS.enchants, (sid, e))

    def test_enchantment_parsing_survives_garbage(self):
        self.assertEqual(armory.parse_enchantments(None), [0] * 12)
        self.assertEqual(armory.parse_enchantments("x y z"), [0] * 12)
        self.assertEqual(armory.parse_enchantments("14 0 0")[0], 14)
        self.assertEqual(len(armory.parse_enchantments("14 0 0")), 12)


def load_generator():
    path = HERE / "tools" / "gen_items.py"
    spec = importlib.util.spec_from_file_location("gen_items", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheDescriptionExpanderTest(unittest.TestCase):
    """The freeze resolves Spell.dbc macros once. These are the rules a
    reader would otherwise never see broken: they would see a wrong number."""

    @classmethod
    def setUpClass(cls):
        cls.gen = load_generator()

    def row(self, base=(0, 0, 0), sides=(1, 1, 1), amplitude=(0, 0, 0),
            duration_index=0, proc_chance=0):
        r = [0] * 234
        for i, v in enumerate(base):
            r[80 + i] = v & 0xFFFFFFFF
        for i, v in enumerate(sides):
            r[74 + i] = v
        for i, v in enumerate(amplitude):
            r[98 + i] = v
        r[40] = duration_index
        r[35] = proc_chance
        return tuple(r)

    def expander(self, **spells):
        return self.gen.Expander({int(k): v for k, v in spells.items()}, {21: 30000})

    def test_a_base_point_is_shown_one_higher_as_the_client_does(self):
        ex = self.expander(**{"1": self.row(base=(19, 0, 0))})
        self.assertEqual(ex.expand(1, "Increases attack power by $s1."),
                         "Increases attack power by 20.")

    def test_a_negative_effect_is_shown_as_its_size(self):
        ex = self.expander(**{"1": self.row(base=(-11, 0, 0))})
        self.assertEqual(ex.expand(1, "Reduces threat by $s1%."), "Reduces threat by 10%.")

    def test_die_sides_make_a_range(self):
        ex = self.expander(**{"1": self.row(base=(9, 0, 0), sides=(5, 1, 1))})
        self.assertEqual(ex.expand(1, "Deals $s1 damage."), "Deals 10 to 14 damage.")

    def test_duration_reads_in_the_clients_units(self):
        ex = self.expander(**{"1": self.row(duration_index=21)})
        self.assertEqual(ex.expand(1, "Lasts $d."), "Lasts 30 sec.")
        self.assertEqual(self.gen.duration_text(120000), "2 min")
        self.assertEqual(self.gen.duration_text(3600000), "1 hour")

    def test_a_periodic_total_is_ticks_times_tick(self):
        ex = self.expander(**{"1": self.row(base=(4, 0, 0), amplitude=(3000, 0, 0), duration_index=21)})
        self.assertEqual(ex.expand(1, "$o1 damage over $d."), "50 damage over 30 sec.")

    def test_another_spells_value_can_be_reached(self):
        ex = self.expander(**{"1": self.row(), "2": self.row(base=(41, 0, 0))})
        self.assertEqual(ex.expand(1, "Heals $2s1."), "Heals 42.")

    def test_a_divided_macro_divides(self):
        ex = self.expander(**{"1": self.row(base=(2999, 0, 0))})
        self.assertEqual(ex.expand(1, "Every $/1000;s1 sec."), "Every 3 sec.")

    def test_arithmetic_is_evaluated_and_max_is_left_alone(self):
        ex = self.expander(**{"1": self.row(base=(9, 0, 0))})
        self.assertEqual(ex.expand(1, "${$s1*2} damage."), "20 damage.")
        self.assertEqual(ex.expand(1, "${$s1/4}.1 sec."), "2.5 sec.")
        self.assertEqual(ex.expand(1, "$max(1, $PL)"), "$max(1, $PL)")

    def test_an_unknown_macro_is_left_exactly_as_written(self):
        """A quietly wrong number is worse than a visible '$a1'."""
        ex = self.expander(**{"1": self.row()})
        self.assertEqual(ex.expand(1, "within $a1 yards"), "within $a1 yards")

    def test_colour_codes_are_stripped_and_line_breaks_normalised(self):
        ex = self.expander(**{"1": self.row()})
        self.assertEqual(ex.expand(1, "|cFFFF0000Red|r text\r\nnext"), "Red text\nnext")


class TheModelTest(unittest.TestCase):
    """The 3D model (infra#88): the character as Wowhead's viewer wants it."""

    def test_the_viewer_slot_is_the_inventory_type_not_the_doll_position(self):
        self.assertEqual(armory.viewer_slot("head", 1), 1)
        self.assertEqual(armory.viewer_slot("shoulders", 3), 3)
        self.assertEqual(armory.viewer_slot("back", 16), 16)
        self.assertEqual(armory.viewer_slot("tabard", 19), 19)
        self.assertEqual(armory.viewer_slot("shirt", 4), 4)

    def test_a_robe_hangs_from_twenty_and_every_other_chest_from_five(self):
        self.assertEqual(armory.viewer_slot("chest", 20), 20)
        self.assertEqual(armory.viewer_slot("chest", 5), 5)
        self.assertEqual(armory.viewer_slot("chest", None), 5)

    def test_whatever_is_in_the_hands_goes_to_the_hand_not_the_weapon_kind(self):
        """A two-hander (17), a one-hander (13) and a main-hand (21) all sit
        in the main hand; a shield (14), a held item (23) and an off-hand
        weapon all sit in the off hand."""
        for kind in (13, 17, 21):
            self.assertEqual(armory.viewer_slot("main hand", kind), 21)
        for kind in (13, 14, 22, 23):
            self.assertEqual(armory.viewer_slot("off hand", kind), 22)

    def test_a_ranged_weapon_is_attached_by_its_own_kind_and_a_relic_is_not(self):
        self.assertEqual(armory.viewer_slot("ranged", 15), 15)
        self.assertEqual(armory.viewer_slot("ranged", 26), 26)
        self.assertEqual(armory.viewer_slot("ranged", 25), 25)
        self.assertIsNone(armory.viewer_slot("ranged", 28))

    def test_what_the_viewer_never_draws_is_never_sent(self):
        for slot in ("neck", "finger 1", "finger 2", "trinket 1", "trinket 2"):
            self.assertIsNone(armory.viewer_slot(slot, 11))

    def test_the_model_carries_the_face_the_character_was_made_with(self):
        row = char(race=1, gender=1, skin=4, face=2, hairStyle=7, hairColor=3, facialStyle=0)
        model = armory.viewer_model(row, [])
        self.assertEqual(model, {"race": 1, "gender": 1, "skin": 4, "face": 2,
                                 "hairStyle": 7, "hairColor": 3, "facialStyle": 0,
                                 "items": [], "assets": []})

    def test_gender_passes_through_as_the_database_stores_it(self):
        """Viewer model id = race * 2 - 1 + gender, and model 1 is the human
        male, so 0 is male on both sides. Flipping it would dress every
        member of the family in the other body."""
        self.assertEqual(armory.viewer_model(char(gender=0), [])["gender"], 0)
        self.assertEqual(armory.viewer_model(char(gender=1), [])["gender"], 1)

    def test_a_missing_appearance_is_left_out_rather_than_defaulted(self):
        model = armory.viewer_model(char(), [])
        for key in ("skin", "face", "hairStyle", "hairColor", "facialStyle"):
            self.assertNotIn(key, model)

    def test_items_are_the_display_id_at_the_viewers_slot(self):
        rows = [worn(0, SCOUTING_BELT, displayid=1170, inventory_type=1),
                worn(4, SCOUTING_BELT, displayid=9575, inventory_type=20),
                worn(15, IRONPATCH, displayid=20379, inventory_type=17),
                worn(1, SCOUTING_BELT, displayid=999, inventory_type=2)]
        model = armory.viewer_model(char(), rows)
        self.assertEqual(model["items"], [[1, 1170], [20, 9575], [21, 20379]])

    def test_an_item_with_no_display_is_skipped_not_sent_as_zero(self):
        rows = [worn(0, SCOUTING_BELT, displayid=None, inventory_type=1),
                worn(2, SCOUTING_BELT, displayid=0)]
        self.assertEqual(armory.viewer_model(char(), rows)["items"], [])

    def test_a_race_the_viewer_has_no_model_for_gets_no_model(self):
        self.assertIsNone(armory.viewer_model(char(race=99), []))
        self.assertIsNone(armory.viewer_model(char(gender=None), []))

    def test_the_model_and_the_display_id_reach_the_payload(self):
        rows = [worn(0, SCOUTING_BELT, displayid=1170, inventory_type=1)]
        m = member(build(rows, char_rows=[char(gender=0, skin=1)]))
        self.assertEqual(m["model"]["items"], [[1, 1170]])
        self.assertEqual(m["model"]["skin"], 1)
        self.assertEqual(slot_of(m, "head")["display_id"], 1170)

    def test_every_slot_the_viewer_draws_reaches_it(self):
        """THE HOLE THIS CLOSES (infra#3510). The four tests above between
        them name head, shoulders, back, tabard, shirt, chest and the hands -
        and leave waist, legs, feet, wrists and hands unasserted, which is
        five of the twelve pieces a dressed character wears. The operator
        reported a model standing in its underwear and bare feet, and the
        first thing to rule out was that legs and feet were being dropped
        here; nothing in this file could have said so either way.

        One worn piece in every drawn doll slot at once, and the whole list
        read back, so a slot that stops being sent fails HERE rather than on
        a screenshot."""
        kinds = [(0, 1), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8),
                 (8, 9), (9, 10), (14, 16), (15, 13), (16, 14), (17, 15), (18, 19)]
        rows = [worn(doll, SCOUTING_BELT, displayid=900 + doll, inventory_type=kind)
                for doll, kind in kinds]
        self.assertEqual(
            armory.viewer_model(char(), rows)["items"],
            [[1, 900], [3, 902], [4, 903], [5, 904], [6, 905], [7, 906],
             [8, 907], [9, 908], [10, 909], [16, 914], [21, 915], [22, 916],
             [15, 917], [19, 918]])

    def test_the_asset_path_is_the_viewers_own_rule_and_not_one_slot_shape(self):
        """Anything worn on the body is filed under its viewer slot; anything
        held in a hand is filed flat, with no slot in the path at all. Read
        out of the viewer build the page pins. Getting this wrong would make
        the page report a piece as undrawable that the viewer drew perfectly
        well - a false alarm on every weapon in the family."""
        for slot in sorted(armory.VIEWER_BODY_SLOTS):
            self.assertEqual(armory.viewer_asset(slot, 25796),
                             f"meta/armor/{slot}/25796.json")
        for held in (armory.VIEWER_MAIN_HAND, armory.VIEWER_OFF_HAND, 15, 25, 26):
            self.assertEqual(armory.viewer_asset(held, 8272), "meta/item/8272.json")

    def test_the_body_slots_are_exactly_the_ones_the_doll_can_fill(self):
        """The two tables are halves of one fact and can drift apart in
        silence: a slot in VIEWER_SLOTS but not here would be asked for at
        the wrong address, and every piece in it reported as missing art."""
        drawn = set(armory.VIEWER_SLOTS.values()) - {armory.VIEWER_MAIN_HAND,
                                                     armory.VIEWER_OFF_HAND}
        self.assertTrue(drawn <= armory.VIEWER_BODY_SLOTS, drawn)
        self.assertIn(armory.INVENTORY_TYPE_ROBE, armory.VIEWER_BODY_SLOTS)

    def test_each_drawn_piece_carries_where_to_look_and_what_to_say(self):
        """The viewer drops a piece whose art the model host has not got and
        says nothing at all, so the page has to ask for the same file itself.
        Both the address and the sentence are written here, because the page
        may not invent either."""
        rows = [worn(6, SCOUTING_BELT, displayid=25796, inventory_type=7,
                     item_name="Battleforge Legguards"),
                worn(15, IRONPATCH, displayid=8272, inventory_type=13)]
        assets = armory.viewer_model(char(), rows)["assets"]
        self.assertEqual(assets[0], {
            "slot": "legs",
            "path": "meta/armor/7/25796.json",
            "note": "legs - Battleforge Legguards (display 25796)",
        })
        self.assertEqual(assets[1]["slot"], "main hand")
        self.assertEqual(assets[1]["path"], "meta/item/8272.json")

    def test_a_piece_the_world_cannot_name_still_gets_a_sentence(self):
        """A custom or removed item joins as a NULL name. "undefined (display
        25760)" is the note that teaches a reader to distrust the rest."""
        row = worn(7, SCOUTING_BELT, displayid=25760, inventory_type=8,
                   item_name=None)
        note = armory.viewer_model(char(), [row])["assets"][0]["note"]
        self.assertNotIn("None", note)
        self.assertIn("25760", note)
        self.assertTrue(note.startswith("feet - "), note)

    def test_a_slot_the_viewer_never_draws_is_never_looked_up(self):
        """A ring has no art to be missing, so it must not appear as a piece
        that failed to draw."""
        rows = [worn(1, SCOUTING_BELT, displayid=555, inventory_type=2),
                worn(10, SCOUTING_BELT, displayid=556, inventory_type=11)]
        self.assertEqual(armory.viewer_model(char(), rows)["assets"], [])

    def test_the_heading_over_the_undrawn_pieces_is_the_modules(self):
        """The page prints it; it does not write it."""
        self.assertEqual(build()["model_gap_hint"], armory.MODEL_GAP_HINT)


if __name__ == "__main__":
    unittest.main()

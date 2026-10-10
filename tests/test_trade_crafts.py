"""One profession's crafts, on demand, for the phone view of the Trades tab.

WHAT THIS FILE PINS. The pure helpers in tradespec.py that answer
/api/trades?skill=<id> (the request parser, the craft list, the one-line brief
a profession row carries), and the handler's refusal to let a caller's value
anywhere near SQL. map_server.py imports pymysql, so the handler is read as
text, the seam every other tab suite uses.
"""

import json
import pathlib
import unittest

import tradespec

HERE = pathlib.Path(__file__).resolve().parent.parent
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
BOOK = json.loads((HERE / "craftbook.json").read_text(encoding="utf-8"))

ARMOR = tradespec.BY_KEY["armorsmith"].spell


class Geo:
    def zone_name(self, _map, _x, _y):
        return "Somewhere"


def build(skills=None, spells=None, extra_members=(), **rows):
    book = {
        "164": {
            "7": ["Copper Sword", 1, 25, 0, 1],
            "8": ["Bronze Mace", 1, 120, 0, 2],
            "9": ["Mithril Plate", 1, 300, 0, 3],
            "10": ["Shiny Plate", 1, 200, 0, 4],
            "11": ["Rough Grindstone", 1, 1, 1, 5],
        }
    }
    craft_rows = [
        {"SpellId": 7, "ReqSkillRank": 25, "ReqAbility1": 0},
        {"SpellId": 8, "ReqSkillRank": 120, "ReqAbility1": 0},
        {"SpellId": 9, "ReqSkillRank": 300, "ReqAbility1": 0},
        {"SpellId": 10, "ReqSkillRank": 200, "ReqAbility1": ARMOR},
    ]
    members = [
        {"name": "Grug", "level": 40, "map": 1},
        {"name": "Og", "level": 40, "map": 1},
        {"name": "Zed", "level": 60, "map": 0},
    ]
    skill_rows = skills or [
        {"name": "Grug", "skill": 164, "value": 150, "max": 150},
        {"name": "Zed", "skill": 164, "value": 300, "max": 300},
    ]
    spell_rows = spells or [{"name": "Grug", "spell": 7}, {"name": "Zed", "spell": 9}]
    args = dict(
        recipe_rows=[],
        trainer_rows=[],
        vendor_rows=[],
        drop_rows=[],
        quest_rows=[],
    )
    args.update(rows)
    return tradespec.build_craft_list(
        164,
        book,
        craft_rows,
        skill_rows,
        spell_rows,
        members,
        ["Grug", "Og"],
        names={34: "The Stockade"},
        geo=Geo(),
        **args,
    )


def by_name(out):
    return {c["name"]: c for c in out["crafts"]}


class TheRequest(unittest.TestCase):
    def test_a_craftbook_key_is_accepted(self):
        self.assertEqual(tradespec.parse_skill({"skill": ["164"]}, BOOK), (164, ""))

    def test_everything_else_is_refused_before_the_database(self):
        for bad in (
            "",
            "0",
            "abc",
            "164 ",
            "-164",
            "1e3",
            "99999",
            "16.4",
            "164;drop",
            "\u0663\u0663\u0663",
            "163",
        ):
            _skill, error = tradespec.parse_skill({"skill": [bad]}, BOOK)
            self.assertTrue(error, repr(bad))

    def test_a_skill_that_is_not_in_the_book_is_refused(self):
        self.assertTrue(tradespec.parse_skill({"skill": ["9999"]}, BOOK)[1])

    def test_an_empty_book_refuses_every_skill(self):
        self.assertTrue(tradespec.parse_skill({"skill": ["164"]}, {})[1])

    def test_a_family_must_be_a_roster_key(self):
        self.assertEqual(
            tradespec.parse_family({"family": ["a"]}, ["a", "b"]), ("a", "")
        )
        self.assertEqual(tradespec.parse_family({}, ["a", "b"]), ("", ""))
        self.assertTrue(tradespec.parse_family({"family": ["x"]}, ["a"])[1])


class TheHandler(unittest.TestCase):
    HANDLER = SERVER[SERVER.index("def _trade_crafts") : SERVER.index("def _dungeons")]

    def test_the_skill_is_validated_before_any_read(self):
        h = self.HANDLER
        self.assertLess(h.index("tradespec.parse_skill("), h.index("_faction_sides()"))
        self.assertLess(h.index("self._send(400"), h.index("_fetch_guildcraft("))

    def test_a_caller_value_is_never_bound_or_formatted_into_a_query(self):
        h = self.HANDLER
        for banned in ("execute", ".format(", "% (", 'f"', "cur."):
            self.assertNotIn(banned, h, banned)

    def test_the_plain_form_still_takes_nothing(self):
        plain = SERVER[SERVER.index("    def _trades") : SERVER.index("def _dungeons")]
        self.assertNotIn("query.get", plain)
        self.assertIn('if "skill" in query:', plain)


class TheBrief(unittest.TestCase):
    def counts(self, **kw):
        out = {s: 0 for s in tradespec.STATE_ORDER}
        for key, n in kw.items():
            out[key] = n
        return out

    def test_plain_words_and_one_line(self):
        c = self.counts(known=1, learnable=5, skill=6)
        line = tradespec.brief_line("skinning", "Bork", c, 12)
        self.assertEqual(
            line, "Bork can make 1 of 12; 5 ready to learn, 6 need more skill"
        )
        self.assertNotIn("\n", line)
        self.assertLess(len(line), 80)

    def test_zero_states_are_not_named(self):
        c = self.counts(known=3, skill=1)
        self.assertEqual(
            tradespec.brief_line("x", "Bork", c, 4),
            "Bork can make 3 of 4; 1 need more skill",
        )

    def test_a_finished_profession_says_all(self):
        c = self.counts(known=4)
        self.assertEqual(tradespec.brief_line("x", "Bork", c, 4), "Bork can make all 4")

    def test_nobody_holding_it_is_said_plainly(self):
        c = self.counts(skill=4)
        self.assertEqual(
            tradespec.brief_line("skinning", "", c, 4),
            "Nobody has skinning yet; 4 crafts to find",
        )

    def test_each_profession_row_carries_it(self):
        book = {"164": {"7": ["A", 1, 25, 0, 1], "8": ["B", 1, 25, 0, 2]}}
        out = tradespec.build_tradespec(
            book,
            [{"SpellId": 7, "ReqSkillRank": 25, "ReqAbility1": 0}],
            [{"name": "Grug", "skill": 164, "value": 50, "max": 75}],
            [{"name": "Grug", "spell": 7}],
            [{"name": "Grug", "level": 10, "map": 1}],
            ["Grug"],
        )
        self.assertEqual(out["professions"][0]["brief"][:20], "Grug can make 1 of 2")
        self.assertEqual(out["professions"][0]["percent"], 50)


class ThePeopleFilter(unittest.TestCase):
    def test_all_then_each_member(self):
        got = tradespec.people_filter(["Grug", "Og"], [{"name": "Grug"}])
        self.assertEqual([p["key"] for p in got], ["", "Grug", "Og"])

    def test_guild_crafters_only_when_somebody_outside_the_family_was_read(self):
        got = tradespec.people_filter(["Grug"], [{"name": "Grug"}, {"name": "Zed"}])
        self.assertEqual(got[-1]["key"], tradespec.GUILD_KEY)
        self.assertEqual(got[-1]["label"], "Guild crafters")

    def test_the_goal_payload_carries_it(self):
        out = tradespec.build_tradespec({}, [], [], [], [{"name": "Grug"}], ["Grug"])
        self.assertEqual(out["people"][0], {"key": "", "label": "All"})


class TheCraftList(unittest.TestCase):
    def setUp(self):
        self.out = build()
        self.c = by_name(self.out)

    def test_every_craft_of_the_profession_is_listed_once_in_rank_order(self):
        ranks = [c["rank"] for c in self.out["crafts"]]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(self.out["total"], 5)
        self.assertEqual(len({c["spell"] for c in self.out["crafts"]}), 5)

    def test_views_are_all_each_member_then_the_guild(self):
        self.assertEqual(
            [v["key"] for v in self.out["views"]],
            ["", "Grug", "Og", tradespec.GUILD_KEY],
        )

    def test_the_all_view_is_the_best_family_holder_and_matches_the_headline(self):
        book = {"164": {"7": ["A", 1, 25, 0, 1], "8": ["B", 1, 120, 0, 2]}}
        crafts = [
            {"SpellId": 7, "ReqSkillRank": 25, "ReqAbility1": 0},
            {"SpellId": 8, "ReqSkillRank": 120, "ReqAbility1": 0},
        ]
        skills = [{"name": "Grug", "skill": 164, "value": 150, "max": 150}]
        spells = [{"name": "Grug", "spell": 7}]
        members = [{"name": "Grug", "level": 40, "map": 1}]
        headline = tradespec.build_tradespec(
            book, crafts, skills, spells, members, ["Grug"]
        )["professions"][0]
        listed = tradespec.build_craft_list(
            164,
            book,
            crafts,
            skills,
            spells,
            members,
            ["Grug"],
            [],
            [],
            [],
            [],
            [],
            {},
            Geo(),
        )["views"][0]
        self.assertEqual(listed["counts"]["k"], headline["counts"]["known"])
        self.assertEqual(listed["counts"]["l"], headline["counts"]["learnable"])
        self.assertEqual(listed["percent"], headline["percent"])
        self.assertEqual(listed["brief"], headline["brief"])

    def test_state_codes_follow_the_view_order(self):
        sword = self.c["Copper Sword"]["states"]
        self.assertEqual(sword[0], "k")
        self.assertEqual(sword[1], "k")
        self.assertEqual(sword[2], "s")
        self.assertEqual(sword[3], "k")

    def test_who_knows_it_and_who_could_learn_it(self):
        mace = self.c["Bronze Mace"]
        self.assertNotIn("known_by", mace)
        self.assertEqual(mace["can_learn"], ["Grug", "Zed"])
        plate = self.c["Mithril Plate"]
        self.assertEqual(plate["known_by"], ["Zed"])

    def test_a_craft_behind_a_branch_nobody_took_is_its_own_state(self):
        shiny = self.c["Shiny Plate"]
        self.assertEqual(shiny["states"][0], "b")
        self.assertEqual(shiny["gate_line"], "Needs the Armorsmith specialization")
        view = self.out["views"][0]
        self.assertIn("b", [g["state"] for g in view["groups"]])

    def test_the_fourth_group_is_absent_when_it_has_no_crafts(self):
        out = build(skills=[{"name": "Grug", "skill": 164, "value": 150, "max": 150}])
        # Shiny Plate is still gated, so the group exists; remove the gate.
        book = {"164": {"7": ["A", 1, 25, 0, 1]}}
        out = tradespec.build_craft_list(
            164,
            book,
            [],
            [],
            [],
            [{"name": "Grug"}],
            ["Grug"],
            [],
            [],
            [],
            [],
            [],
            {},
            Geo(),
        )
        states = [g["state"] for g in out["views"][0]["groups"]]
        self.assertEqual(states, ["k", "l", "s"])

    def test_group_labels_are_the_modules(self):
        labels = [g["label"] for g in self.out["views"][0]["groups"]]
        self.assertEqual(
            labels[:3], ["Known", "Ready to learn now", "Needs more skill"]
        )
        self.assertIn("Needs a specialization nobody took", labels)

    def test_group_counts_add_up_to_the_total(self):
        for view in self.out["views"]:
            self.assertEqual(sum(g["count"] for g in view["groups"]), 5)

    def test_a_member_without_the_trade_is_said_plainly(self):
        og = self.out["views"][2]
        self.assertTrue(og["brief"].startswith("Nobody has"))

    def test_the_guild_view_is_the_best_of_everyone(self):
        guild = self.out["views"][3]
        # Zed knows Mithril Plate; Grug knows Copper Sword; Grindstone is auto.
        self.assertEqual(guild["counts"]["k"], 3)
        self.assertTrue(guild["brief"].startswith("The guild can make 3 of 5"))

    def test_guild_crafters_are_not_read_as_the_family(self):
        self.assertEqual(self.out["views"][0]["counts"]["k"], 2)

    def test_the_auto_learned_craft_is_counted_known_and_says_how(self):
        stone = self.c["Rough Grindstone"]
        self.assertEqual(stone["how"], tradespec.SOURCE_AUTOMATIC)
        self.assertIn("on its own", self.out["how_words"][stone["how"]])
        self.assertNotIn("how_line", stone)


class TheSources(unittest.TestCase):
    def setUp(self):
        self.recipes = [
            {"entry": 500, "spellid_2": 8, "item_name": "Plans: Bronze Mace"},
            {"entry": 501, "spellid_2": 9, "item_name": "Plans: Mithril Plate"},
        ]
        self.drops = [
            {
                "item": 500,
                "Chance": 1.5,
                "name": "Hogger",
                "minlevel": 20,
                "maxlevel": 22,
                "map": 34,
                "position_x": 1,
                "position_y": 2,
            },
            {
                "item": 500,
                "Chance": 3,
                "name": "A Wolf",
                "minlevel": 5,
                "maxlevel": 5,
                "map": 0,
                "position_x": 1,
                "position_y": 2,
            },
        ]
        self.vendors = [
            {"item": 500, "name": "Smith", "map": 0, "position_x": 1, "position_y": 2}
        ]
        self.trainer = [{"SpellId": 7}]
        self.out = build(
            recipe_rows=self.recipes,
            drop_rows=self.drops,
            vendor_rows=self.vendors,
            trainer_rows=self.trainer,
        )
        self.c = by_name(self.out)

    def test_a_trainer_craft_says_so(self):
        sword = self.c["Copper Sword"]
        self.assertEqual(sword["how"], tradespec.SOURCE_TRAINER)
        self.assertIn("trainer", self.out["how_words"][sword["how"]])

    def test_a_recipe_craft_names_the_recipe_item(self):
        mace = self.c["Bronze Mace"]
        self.assertEqual(mace["how"], tradespec.SOURCE_RECIPE)
        self.assertIn("Plans: Bronze Mace", mace["how_line"])

    def test_the_dungeon_drop_is_named_and_listed_first(self):
        mace = self.c["Bronze Mace"]
        self.assertIn("The Stockade", mace["dungeon_line"])
        self.assertIn("Hogger", mace["where"][0])
        self.assertIn("The Stockade", mace["where"][0])
        self.assertLessEqual(len(mace["where"]), 3)

    def test_a_recipe_with_no_source_row_says_it_cannot_tell(self):
        plate = self.c["Mithril Plate"]
        self.assertNotIn("where", plate)
        self.assertIn("No vendor, quest or direct drop", plate["where_line"])

    def test_a_craft_with_no_dungeon_has_no_dungeon_line(self):
        self.assertNotIn("dungeon_line", self.c["Copper Sword"])

    def test_the_basis_admits_what_the_data_lacks(self):
        self.assertIn("NO REAGENTS", self.out["basis"])
        self.assertIn("boss", self.out["basis"])
        self.assertIn("reagents", self.out["reagents_line"].lower())

    def test_the_whole_payload_is_json_and_small(self):
        body = json.dumps(self.out)
        self.assertLess(len(body), 20000)


class TheRealBook(unittest.TestCase):
    def test_the_largest_profession_stays_small_enough_for_a_phone(self):
        crafts = BOOK["164"]
        members = [{"name": "Grug", "level": 40, "map": 1}]
        out = tradespec.build_craft_list(
            164,
            BOOK,
            [],
            [{"name": "Grug", "skill": 164, "value": 300, "max": 300}],
            [],
            members,
            ["Grug"],
            [],
            [],
            [],
            [],
            [],
            {},
            Geo(),
        )
        self.assertEqual(out["total"], len(crafts))
        self.assertLess(len(json.dumps(out)), 250000)


if __name__ == "__main__":
    unittest.main()

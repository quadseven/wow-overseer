"""Who receives which recipe: the designated crafters (#248).

THE FIXTURE is Ugga, the Alliance family's level 60 priest, as read off the
dev realm on 2026-09-23: Alchemy 14, First Aid 1, Cooking 1, and eight recipes
for trades she lacks or cannot learn yet (guids as tests/test_bag_keep.py
numbers them). The guild members are real names from the Alliance guild with
their measured skills; every Alliance alchemist at 285 or more had
Purification Potion (spell 17572) in character_spell, and the three below 285
were at 250 and 255.
"""

import ast
import pathlib
import unittest

import bank
import clearance
import crafters
import guildroute
import jev_keep
from test_bag_keep import UGGA, UGGA_PLAN, UGGA_SKILLS, VIALS, OPEN_GUILD
from test_bag_keep import _bank_rows

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

FIRST_AID, BLACKSMITHING, LEATHERWORKING, ALCHEMY = 129, 164, 165, 171
COOKING, TAILORING, ENGINEERING, ENCHANTING, JEWELCRAFTING = 185, 197, 202, 333, 755
PURIFICATION = 17572


def recipe(guid, entry, name, skill, rank, spell):
    return crafters.Recipe("Ugga", guid, entry, name, skill, rank, spell)


# Ugga's eight recipes: (guid, entry, name, RequiredSkill, rank, spellid_2).
UGGA_RECIPES = [
    recipe(13, 6454, "Manual: Strong Anti-Venom", FIRST_AID, 130, 7935),
    recipe(16, 6661, "Recipe: Savory Deviate Delight", COOKING, 85, 8238),
    recipe(22, 6663, "Recipe: Elixir of Giant Growth", ALCHEMY, 90, 8240),
    recipe(25, 13492, "Recipe: Purification Potion", ALCHEMY, 285, PURIFICATION),
    recipe(31, 21949, "Design: Ruby Serpent", JEWELCRAFTING, 260, 26900),
    recipe(33, 13492, "Recipe: Purification Potion", ALCHEMY, 285, PURIFICATION),
    recipe(38, 9297, "Recipe: Elixir of Dream Vision", ALCHEMY, 240, 11468),
    recipe(45, 2553, "Recipe: Elixir of Minor Agility", ALCHEMY, 50, 3230),
]


def person(name, skills, level=60, family=False, online=True):
    return crafters.Person(name, skills, level, family, online)


FAMILY = [
    person("Grug", {BLACKSMITHING: 1, FIRST_AID: 1, COOKING: 1}, family=True),
    person("Ugga", {ALCHEMY: 14, FIRST_AID: 1, COOKING: 1}, family=True),
    person("Og", {TAILORING: 50, ENCHANTING: 1, FIRST_AID: 1}, family=True),
    person("Bork", {LEATHERWORKING: 1, FIRST_AID: 1}, family=True),
    person("Grog", {ENGINEERING: 1, FIRST_AID: 1}, family=True),
]
GUILD = [
    person("Aehuurn", {ALCHEMY: 300, FIRST_AID: 300, COOKING: 300}),
    person("Alindy", {ALCHEMY: 300, FIRST_AID: 300}),
    person("Goraraa", {ALCHEMY: 300, FIRST_AID: 300, COOKING: 300}, level=59),
    person("Anneve", {ALCHEMY: 250}),
    person("Arehr", {ALCHEMY: 255, JEWELCRAFTING: 300}),
    person("Annian", {JEWELCRAFTING: 300}),
    person("Achevar", {FIRST_AID: 300}),
    person("Actehuurn", {FIRST_AID: 300}),
    person("Ameth", {COOKING: 300}, online=False),
    person("Amilyn", {COOKING: 300}),
    person("Aristina", {TAILORING: 300}),
]
PEOPLE = FAMILY + GUILD

# Every alchemist at 285 or more knows Purification Potion.
KNOWN = crafters.known_from_rows(
    [{"name": p.name, "spell": PURIFICATION} for p in PEOPLE if p.rank(ALCHEMY) >= 285]
)


def register(people=PEOPLE, n=2):
    return crafters.register(people, n)


def routes(people=PEOPLE, known=KNOWN, gap=25, recipes=UGGA_RECIPES):
    return crafters.route(recipes, register(people), people, known, gap)


class TheRegister(unittest.TestCase):
    def names(self, skill, reg=None):
        return [(s.name, s.seat) for s in (reg or register())[skill]]

    def test_family_members_who_hold_the_trade_come_first(self):
        self.assertEqual(
            self.names(ALCHEMY),
            [("Ugga", "family"), ("Aehuurn", "designated"), ("Alindy", "designated")],
        )
        self.assertEqual(self.names(TAILORING)[0], ("Og", "family"))

    def test_designated_are_picked_by_skill_then_level(self):
        """Goraraa is 300 too but level 59, so he is not one of the two."""
        seats = [s.name for s in register()[ALCHEMY] if s.seat == "designated"]
        self.assertNotIn("Goraraa", seats)
        self.assertNotIn("Anneve", seats)

    def test_one_bot_is_not_designated_for_every_trade(self):
        """With three seats, Aehuurn takes one in first aid (seated first),
        so alchemy seats the unseated Alindy ahead of him."""
        first_aid = [s.name for s in register(n=3)[FIRST_AID] if s.seat == "designated"]
        self.assertEqual(first_aid, ["Achevar", "Actehuurn", "Aehuurn"])
        alchemy = [s.name for s in register(n=3)[ALCHEMY] if s.seat == "designated"]
        self.assertEqual(alchemy[0], "Alindy")

    def test_n_is_configurable(self):
        self.assertEqual(crafters.per_trade({}), 2)
        self.assertEqual(crafters.per_trade({"DESIGNATED_CRAFTERS_PER_TRADE": "3"}), 3)
        self.assertEqual(crafters.per_trade({"DESIGNATED_CRAFTERS_PER_TRADE": "x"}), 2)
        self.assertEqual(
            crafters.per_trade({"DESIGNATED_CRAFTERS_PER_TRADE": "99"}), 10
        )
        three = [s.name for s in register(n=3)[ALCHEMY] if s.seat == "designated"]
        self.assertEqual(len(three), 3)

    def test_nobody_without_the_trade_is_seated(self):
        self.assertEqual(self.names(JEWELCRAFTING)[0][1], "designated")
        self.assertNotIn("Ugga", [n for n, _ in self.names(JEWELCRAFTING)])

    def test_the_register_is_what_the_page_draws(self):
        payload = crafters.register_payload(register())
        alchemy = next(t for t in payload if t["trade"] == "alchemy")
        self.assertEqual(
            alchemy["seats"][0],
            {"name": "Ugga", "rank": 14, "level": 60, "seat": "family"},
        )


class UggasEightRecipes(unittest.TestCase):
    def test_each_goes_to_the_crafter_who_learns_it(self):
        got = {g: (p.taker, p.seat, p.when) for g, p in routes().items()}
        self.assertEqual(
            got,
            {
                13: ("Achevar", "designated", "now"),
                16: ("Amilyn", "designated", "now"),
                22: ("Aehuurn", "designated", "now"),
                25: ("", "", ""),
                31: ("Annian", "designated", "now"),
                33: ("", "", ""),
                38: ("Aehuurn", "designated", "now"),
                45: ("Aehuurn", "designated", "now"),
            },
        )

    def test_nobody_who_already_knows_it_is_sent_it(self):
        """Without the known check the 300 alchemists would take Purification."""
        unknown = routes(known=crafters.Known())
        self.assertEqual(unknown[25].taker, "Aehuurn")
        self.assertEqual(routes()[25].taker, "")
        self.assertIn("without already knowing it", routes()[25].why)

    def test_a_use_verb_already_knows_answer_counts_too(self):
        verdicts = [
            {
                "target_name": "Annian",
                "detail": "the character already knows that recipe",
                "entry": 21949,
            },
            {
                "target_name": "Arehr",
                "detail": "the character skill is too low to use that item",
                "entry": 21949,
            },
        ]
        known = crafters.known_from_rows([], verdicts)
        self.assertEqual(routes(known=known)[31].taker, "Arehr")

    def test_an_online_crafter_beats_an_offline_one(self):
        self.assertEqual(routes()[16].taker, "Amilyn")

    def test_the_family_learns_first_when_it_can(self):
        og = person("Og", {TAILORING: 120}, family=True)
        pattern = crafters.Recipe(
            "Ugga",
            90,
            4347,
            "Pattern: Reinforced Woolen Shoulders",
            TAILORING,
            120,
            3849,
        )
        people = [og, *GUILD]
        pick = crafters.choose(pattern, register(people), people, KNOWN, 25)
        self.assertEqual((pick.taker, pick.seat, pick.when), ("Og", "family", "now"))

    def test_the_holder_keeps_what_the_holder_learns(self):
        ugga = person("Ugga", {ALCHEMY: 60}, family=True)
        people = [ugga, *GUILD]
        pick = crafters.choose(UGGA_RECIPES[-1], register(people), people, KNOWN, 25)
        self.assertTrue(pick.kept)
        self.assertFalse(pick.routed)

    def test_learning_now_beats_a_family_member_who_is_short(self):
        ugga = person("Ugga", {ALCHEMY: 30}, family=True)
        people = [ugga, *GUILD]
        pick = crafters.choose(UGGA_RECIPES[-1], register(people), people, KNOWN, 25)
        self.assertEqual((pick.taker, pick.when), ("Aehuurn", "now"))

    def test_a_designated_crafter_a_little_short_is_sent_it_soon(self):
        """Nobody can learn Purification now; a designated 270 is 15 short."""
        people = [*FAMILY, person("Brewer", {ALCHEMY: 270})]
        pick = crafters.choose(UGGA_RECIPES[3], register(people), people, KNOWN, 25)
        self.assertEqual(
            (pick.taker, pick.seat, pick.when), ("Brewer", "designated", "soon")
        )
        far = crafters.choose(UGGA_RECIPES[3], register(people), people, KNOWN, 10)
        self.assertEqual(far.taker, "")

    def test_a_guildmate_off_the_register_is_sent_only_what_they_learn_now(self):
        """Arehr is 30 short and not a designated alchemist: never 'soon'."""
        self.assertEqual(routes(gap=40)[25].taker, "")

    def test_the_benefit_is_the_closest_skill(self):
        people = [*FAMILY, person("Hi", {ALCHEMY: 300}), person("Mid", {ALCHEMY: 245})]
        pick = crafters.choose(UGGA_RECIPES[6], register(people), people, KNOWN, 25)
        self.assertEqual(pick.taker, "Mid")

    def test_the_summary_line_carries_the_log_prefix(self):
        line = crafters.summary(routes())
        self.assertTrue(line.startswith("crafter-route: 8 recipe(s)"))
        self.assertIn("6 routed to a crafter, 2 with nobody", line)


def stack(guid, name, skill, rank, holder="Ugga"):
    return clearance.Stack(
        holder, guid, 1, name, clearance.RECIPE_CLASS, 1, 2, 100, skill, rank
    )


def cperson(p):
    return clearance.Person(
        p.name, p.skills, family=p.family, online=p.online or p.family
    )


class TheClearanceRouteTakesThePick(unittest.TestCase):
    def plan(self, picks, stacks, kept=frozenset()):
        return {
            r.stack.guid: r
            for r in clearance.plan(
                stacks, [cperson(p) for p in PEOPLE], kept=kept, picks=picks
            )
        }

    def test_ruby_serpent_is_posted_to_the_designated_jeweler(self):
        got = self.plan(
            routes(), [stack(31, "Design: Ruby Serpent", JEWELCRAFTING, 260)]
        )
        self.assertEqual((got[31].route, got[31].taker), (clearance.GUILD, "Annian"))

    def test_without_the_pick_the_first_name_who_knows_it_takes_it(self):
        """The old by-name search sends Purification to a 300 who knows it."""
        purification = stack(25, "Recipe: Purification Potion", ALCHEMY, 285)
        old = self.plan(None, [purification])
        self.assertEqual(old[25].taker, "Aehuurn")
        new = self.plan(routes(), [purification])
        self.assertNotIn(new[25].route, clearance.GIVEN)

    def test_a_routed_recipe_is_not_held_for_the_family_hand_off(self):
        got = self.plan(
            routes(),
            [stack(22, "Recipe: Elixir of Giant Growth", ALCHEMY, 90)],
            kept={22},
        )
        self.assertEqual(got[22].route, clearance.GUILD)

    def test_an_offline_taker_waits(self):
        picks = routes()
        pick = picks[16]
        picks[16] = crafters.Pick(
            pick.recipe, pick.taker, pick.seat, pick.when, pick.why, False
        )
        got = self.plan(
            picks, [stack(16, "Recipe: Savory Deviate Delight", COOKING, 85)]
        )
        self.assertEqual((got[16].route, got[16].taker), (clearance.WAIT, "Amilyn"))

    def test_one_stack_per_taker_per_pass(self):
        got = self.plan(
            routes(),
            [
                stack(22, "Recipe: Elixir of Giant Growth", ALCHEMY, 90),
                stack(38, "Recipe: Elixir of Dream Vision", ALCHEMY, 240),
            ],
        )
        self.assertEqual(
            sorted(r.route for r in got.values()), [clearance.GUILD, clearance.WAIT]
        )


class TheBankLeavesARoutedRecipeToTheHandOff(unittest.TestCase):
    def storage(self, routed=None):
        return bank.storage_from(
            UGGA_SKILLS, UGGA_PLAN, VIALS, OPEN_GUILD, routed=routed
        )

    def stored(self, storage):
        member = bank.members_from_rows(_bank_rows(UGGA), ["Ugga"])[0]
        return {h.item.name for h, _ in bank._stored(member, storage)}

    def test_a_routed_recipe_stays_in_the_bags(self):
        self.assertIn("Design: Ruby Serpent", self.stored(self.storage()))
        routed = self.storage({31: "Annian"})
        self.assertNotIn("Design: Ruby Serpent", self.stored(routed))
        self.assertIn("Recipe: Purification Potion", self.stored(routed))

    def test_a_banked_routed_recipe_comes_back_out(self):
        row = next(r for r in UGGA if r[6] == "Design: Ruby Serpent")
        banked = (0, 40, 740, *row[3:])
        member = bank.members_from_rows(_bank_rows([banked]), ["Ugga"])[0]
        family = bank.family_from_skills(UGGA_SKILLS)
        before = bank.plan([member], family, storage=self.storage())
        self.assertNotIn(bank.WITHDRAW, [m.verb for m in before.moves])
        after = bank.plan([member], family, storage=self.storage({740: "Annian"}))
        out = [m for m in after.moves if m.verb == bank.WITHDRAW]
        self.assertEqual([m.item for m in out], ["Design: Ruby Serpent"])
        self.assertIn("Annian", out[0].why)


class JevIsShownTheRegister(unittest.TestCase):
    def ask(self, takers=None, reg=None):
        row = {
            "holder": "Ugga",
            "item_guid": 31,
            "entry": 21949,
            "name": "Design: Ruby Serpent",
            "item_class": 9,
            "count": 1,
            "quality": 2,
            "sell_price": 2500,
            "quest_item": False,
            "reagent": False,
            "profession_needed": False,
        }
        template = {"required_skill": JEWELCRAFTING, "required_rank": 260, "bonding": 0}
        people = [cperson(p) for p in PEOPLE]
        return jev_keep.asks(
            [row],
            templates={21949: template},
            holders={},
            people=people,
            routes={},
            market={},
            reagent_trades={},
            mode="shadow",
            takers=takers,
            register=reg,
        )[0]

    def test_give_options_follow_the_register(self):
        reg = register()
        takers = {31: crafters.candidates(UGGA_RECIPES[4], reg, PEOPLE, KNOWN, 25)}
        _, state, questions = self.ask(takers, reg)
        gives = [
            k
            for k in questions["route"]["criteria"]
            if k.startswith(jev_keep.GIVE_PREFIX)
        ]
        self.assertEqual(gives[0], "give:Annian")
        self.assertEqual(
            [s["name"] for s in state["item"]["teaches"]["designated_crafters"]],
            ["Annian", "Arehr"],
        )

    def test_without_the_register_the_old_order_stands(self):
        _, state, _ = self.ask()
        self.assertNotIn("designated_crafters", state["item"]["teaches"])


def letter(receiver, mail_id, guid, rec, delivered=1, cod=0):
    return crafters.letter_from_row(
        {
            "receiver": receiver,
            "mail_id": mail_id,
            "item_guid": guid,
            "entry": rec.entry,
            "name": rec.name,
            "required_skill": rec.skill,
            "required_rank": rec.rank,
            "recipe_spell": rec.spell,
            "delivered": delivered,
            "cod": cod,
        }
    )


class TheCrafterTakesTheLetterOutAndLearnsIt(unittest.TestCase):
    crafters_by_name = {p.name: p for p in GUILD}

    def test_a_ready_letter_is_taken_and_used(self):
        visits, _ = crafters.visits(
            [letter("Annian", 24816, 5412039, UGGA_RECIPES[4])],
            self.crafters_by_name,
            KNOWN,
        )
        self.assertEqual(len(visits), 1)
        take = visits[0].takes[0]
        self.assertEqual(take.take_command, "take-item mail:24816 item:5412039")
        self.assertEqual(take.use_command, "use guid:5412039")
        self.assertEqual(visits[0].walk_command, "walk-to-mailbox max:600")

    def test_what_cannot_be_taken_or_learned_stays(self):
        letters = [
            letter("Annian", 1, 11, UGGA_RECIPES[4], delivered=0),
            letter("Aehuurn", 2, 12, UGGA_RECIPES[3]),
            letter("Anneve", 3, 13, UGGA_RECIPES[3]),
            letter("Ameth", 4, 14, UGGA_RECIPES[1]),
        ]
        visits, notes = crafters.visits(letters, self.crafters_by_name, KNOWN)
        self.assertEqual(visits, [])
        self.assertEqual(len(notes), 4)

    def test_bounds(self):
        letters = [letter("Aehuurn", i, 100 + i, UGGA_RECIPES[2]) for i in range(1, 6)]
        letters += [
            letter("Achevar", 7, 107, UGGA_RECIPES[0]),
            letter("Amilyn", 8, 108, UGGA_RECIPES[1]),
        ]
        visits, _ = crafters.visits(
            letters, self.crafters_by_name, KNOWN, free_slots={"Achevar": 0}
        )
        self.assertEqual([v.receiver for v in visits], ["Aehuurn", "Amilyn"])
        self.assertEqual(len(visits[0].takes), crafters.TAKES_PER_VISIT)
        busy, _ = crafters.visits(
            letters, self.crafters_by_name, KNOWN, busy=frozenset({"Aehuurn"})
        )
        self.assertNotIn("Aehuurn", [v.receiver for v in busy])

    def test_only_a_bot_off_the_roster_is_walked(self):
        walker = guildroute.Walker(
            "Annian", map_id=0, yards=100.0, aim="at:0:1,2,3", by_row=True
        )
        self.assertEqual(crafters.walk_refusal("Annian", walker), "")
        roster = guildroute.Walker("Og", map_id=0, yards=100.0, aim="at:0:1,2,3")
        self.assertIn("walk row", crafters.walk_refusal("Og", roster))


class TheBridgeWiring(unittest.TestCase):
    tree = ast.parse(BRIDGE)

    def body(self, name):
        fn = next(
            n
            for n in ast.walk(self.tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name
        )
        return ast.get_source_segment(BRIDGE, fn)

    def test_the_pickup_loop_is_registered_in_both_lists(self):
        self.assertEqual(BRIDGE.count("self._crafter_mail_loop,"), 2)

    def test_clearance_routes_by_the_register(self):
        body = self.body("_clearance_plan")
        self.assertIn("_crafter_plan", body)
        self.assertIn("picks=crafting.picks", body)

    def test_the_family_hand_off_leaves_routed_recipes_alone(self):
        self.assertIn("not in routed", self.body("_hand_recipes"))

    def test_the_bank_knows_what_is_routed(self):
        self.assertIn("routed=_crafter_plan(names).routed", self.body("_plan_bank"))

    def test_jev_is_given_the_register(self):
        body = self.body("_jev_keep_once")
        self.assertIn("takers=crafting.takers", body)
        self.assertIn("register=crafting.register", body)

    def test_the_letter_is_taken_only_after_the_walk_and_used_only_after(self):
        follow = self.body("_follow_crafter_visit")
        self.assertLess(
            follow.index("guildroute.ARRIVED"), follow.index("_take_and_learn")
        )
        take = self.body("_take_and_learn")
        self.assertLess(
            take.index('status != "delivered"'), take.index("_insert_learn")
        )

    def test_never_a_give_or_a_gm_command(self):
        for name in ("_crafter_mail_for", "_follow_crafter_visit", "_take_and_learn"):
            body = self.body(name)
            self.assertNotIn("_insert_gm", body)
            self.assertNotIn("'give'", body)

    def test_the_page_and_the_image(self):
        self.assertIn('lineup["crafters"] = _crafter_register(', SERVER)
        self.assertIn("lnCrafters(g.crafters)", PAGE)
        self.assertIn(" crafters.py ", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()

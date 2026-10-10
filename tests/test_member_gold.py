"""Members keep gold for training first, and the guild funds the rest.

The dev realm on 2026-10-10 at about 12:50 ET: 1,569 class spells waited at
the trainers of the two family guilds' 142 members (a median of ten each); 65
of Cave's 71 members and 63 of Bonkers' held under a gold; Cave's bank held
155 gold and Bonkers' none. A level 25 mage in Cave waited on 25 spells
costing 6 gold 1 silver and carried 22 silver. Thirteen of Cave's members had
posted guild dues before they were reset to level 1.

Pure tests against guildwork, classtrain, guildfund and guildpost, plus source
checks on the bridge passes that write the rows.
"""

import ast
import pathlib
import unittest

import classtrain
import guildfund
import guildpost
import guildroute
import guildwork

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
GOLD = 10_000


def function_source(name):
    tree = ast.parse(BRIDGE)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return ast.get_source_segment(BRIDGE, node)
    raise AssertionError("no function %s in bridge.py" % name)


# A level 25 mage's class trainer rows, as acore_world.trainer_spell has them.
MAGE = [
    {"spell": 133, "level": 1, "cost": 0},
    {"spell": 5144, "level": 16, "cost": 1500},
    {"spell": 475, "level": 18, "cost": 1800},
    {"spell": 10, "level": 20, "cost": 2000},
    # Needs a talent first: not trainable.
    {"spell": 12051, "level": 20, "cost": 2000, "req1": 11958},
    # Above level 25.
    {"spell": 8401, "level": 26, "cost": 3000},
]


class DuesKeepTheTrainingReserve(unittest.TestCase):
    def test_a_member_keeps_its_reserve_when_it_is_more_than_the_float(self):
        # Level 25: the float is 17 gold 36 silver; the reserve is 26 gold.
        self.assertEqual(guildwork.float_for(25), 173611)
        self.assertEqual(
            guildwork.dues_for(30 * GOLD, level=25, reserve=26 * GOLD), 2 * GOLD
        )
        self.assertEqual(guildwork.dues_for(26 * GOLD, level=25, reserve=26 * GOLD), 0)

    def test_the_float_still_holds_when_the_reserve_is_smaller(self):
        self.assertEqual(
            guildwork.dues_for(30 * GOLD, level=25, reserve=1 * GOLD),
            guildwork.dues_for(30 * GOLD, level=25),
        )

    def test_the_reserve_rides_on_the_row(self):
        rows = [
            {
                "guild_name": "Cave",
                "name": "Eggrok",
                "level": 25,
                "money": 30 * GOLD,
                "online": 1,
                "reserve": 26 * GOLD,
            }
        ]
        member = guildwork._member_from("Cave", rows[0])
        self.assertEqual(member.reserve, 26 * GOLD)
        self.assertEqual(member.dues, 2 * GOLD)

    def test_the_note_names_the_reserve(self):
        m = guildwork.Member(
            "Eggrok", "Cave", money=20 * GOLD, online=True, level=25, reserve=26 * GOLD
        )
        why = guildwork._not_due(m, "Grug", set(), {"Eggrok"})
        self.assertIn("training and gear reserve", why)

    def test_the_dues_pass_reads_the_reserves(self):
        body = function_source("_guild_dues_once")
        self.assertIn("_with_reserves", body)
        self.assertLess(body.index("_with_reserves"), body.index("members_from_rows"))


class ClassSpellsDue(unittest.TestCase):
    def test_due_counts_what_the_trainer_sells_now(self):
        due = classtrain.due(MAGE, {133}, 25)
        self.assertEqual(due, classtrain.Due(5300, 3, 1500))

    def test_a_spell_that_needs_a_talent_or_a_level_is_not_due(self):
        due = classtrain.due(MAGE, {133, 5144, 475, 10}, 25)
        self.assertEqual(due.count, 0)
        self.assertFalse(due.affords(10 * GOLD))

    def test_affords_means_the_cheapest_one(self):
        due = classtrain.due(MAGE, {133}, 25)
        self.assertTrue(due.affords(1500))
        self.assertFalse(due.affords(1499))

    def test_the_profile_reads_the_same_rule(self):
        import apiv2.training as training

        self.assertIs(training.spell_state, classtrain.spell_state)


def walker(name, **over):
    base = dict(
        name=name,
        map_id=0,
        in_combat=False,
        unwalkable="",
        cohort="",
        yards=300.0,
        aim="at:0:1,2,3",
        by_row=True,
    )
    base.update(over)
    return guildroute.Walker(**base)


def trainee(name, money, guild="Cave", level=25, online=True, known=(133,)):
    return classtrain.Trainee(
        name, guild, level, money, classtrain.due(MAGE, set(known), level), online
    )


class ClassTrainerWalks(unittest.TestCase):
    def test_a_member_who_can_pay_walks_to_its_class_trainer(self):
        walks, _ = classtrain.plan(
            [trainee("Eggrok", 2240)], {"Eggrok": walker("Eggrok")}, set(), set()
        )
        self.assertEqual([w.name for w in walks], ["Eggrok"])
        self.assertEqual(walks[0].command, "walk-to-trainer class max:20000")
        self.assertEqual(walks[0].source, "guildtrain:Eggrok")
        self.assertIn("walks to its class trainer", walks[0].said)

    def test_the_near_cap_names_no_max(self):
        walk = classtrain.Walk(
            "Eggrok", "Cave", 25, 3, 5300, 2240, guildroute.MAIL_RUN_YARDS
        )
        self.assertEqual(walk.command, "walk-to-trainer class")

    def test_a_member_too_poor_for_any_spell_saves(self):
        walks, notes = classtrain.plan(
            [trainee("Eggrok", 1000)], {"Eggrok": walker("Eggrok")}, set(), set()
        )
        self.assertEqual(walks, [])
        self.assertIn("saves for its trainer", notes[0])

    def test_cooldown_busy_offline_and_instance_wait(self):
        walks, notes = classtrain.plan(
            [
                trainee("A", 9000),
                trainee("B", 9000),
                trainee("C", 9000, online=False),
                trainee("D", 9000),
            ],
            {"A": walker("A"), "B": walker("B"), "D": walker("D", map_id=36)},
            {"A"},
            {"B"},
        )
        self.assertEqual(walks, [])
        self.assertTrue(any("inside an instance" in n for n in notes))

    def test_a_guild_starts_a_few_walks_a_pass(self):
        people = [trainee("M%d" % i, 9000) for i in range(6)]
        walks, notes = classtrain.plan(
            people, {p.name: walker(p.name) for p in people}, set(), set()
        )
        self.assertEqual(len(walks), classtrain.WALKS_PER_GUILD)
        self.assertTrue(any("trainer walks per guild per pass" in n for n in notes))

    def test_recent_walks_and_an_old_worldserver_are_read_from_the_log(self):
        rows = [
            {"target_name": "A", "source": "guildtrain:A", "age": 30},
            {"target_name": "B", "source": "guildtrain:B", "age": 600},
            {
                "target_name": "C",
                "source": "guildtrain:C",
                "age": 5,
                "detail": "malformed walk-to-trainer command",
            },
        ]
        self.assertEqual(classtrain.recent_walkers(rows), {"A", "C"})
        self.assertTrue(classtrain.unsupported(rows))
        self.assertFalse(classtrain.unsupported(rows[:2]))

    def test_the_summary_counts_spells_learned(self):
        rows = [
            {
                "source": "guildtrain:A",
                "status": "applied",
                "result": '{"taught":[5144,475]}',
            },
            {"source": "guildtrain:B", "status": "unchanged", "result": "{}"},
        ]
        self.assertIn(
            "2 class trainer walk(s) in the last day, 1 bought spells, 2 spell(s)",
            classtrain.summary(rows),
        )


def member(name, money, training=0, level=25):
    return guildfund.Member(name, "Cave", level, money, training)


class GuildFund(unittest.TestCase):
    def test_reserve_is_training_and_a_gear_budget(self):
        self.assertEqual(guildfund.gear_budget(25), 15625)
        self.assertEqual(guildfund.gear_budget(70), guildfund.gear_budget(60))
        self.assertEqual(member("Eggrok", 2240, 60100).reserve, 60100 + 15625)

    def test_dues_paid_follow_the_rename(self):
        rows = [
            {
                "target_name": "Derred",
                "source": "guilddues:2500000",
                "status": "delivered",
            },
            {
                "target_name": "Becalin",
                "source": "guilddues:2500000",
                "status": "error",
            },
            {
                "target_name": "Ganras",
                "source": "guilddues:2500000",
                "status": "delivered",
            },
            {
                "target_name": "Ganras",
                "source": "guilddues:2500000",
                "status": "delivered",
            },
        ]
        paid = guildfund.dues_paid(rows, {"Derred": "Eggrok", "Ganras": "Cronk"})
        self.assertEqual(paid, {"Eggrok": 250 * GOLD, "Cronk": 500 * GOLD})

    def test_a_refund_is_what_the_member_is_short_never_more_than_it_paid(self):
        members = [member("Eggrok", 2240, 60100), member("Rich", 50 * GOLD, 1000)]
        plan = guildfund.plan(
            "Grug",
            members,
            155 * GOLD,
            guildfund.Ledger(),
            {"Eggrok": 250 * GOLD, "Rich": 250 * GOLD},
        )
        refunds = [x for x in plan.letters if x.kind == guildfund.REFUND]
        self.assertEqual(
            [(x.member, x.copper) for x in refunds], [("Eggrok", 60100 + 15625 - 2240)]
        )
        self.assertEqual(
            refunds[0].command, "send money:%d subject:Dues refund" % 73485
        )
        self.assertEqual(refunds[0].source, "guildfund:refund:Eggrok")
        said = refunds[0].said
        for part in ("Dues refund", "Eggrok", "7g 34s", "dues paid 250g"):
            self.assertIn(part, said)

    def test_a_refund_is_bounded_by_the_bank(self):
        members = [member("A", 0, 90 * GOLD), member("B", 0, 90 * GOLD)]
        plan = guildfund.plan(
            "Grug",
            members,
            100 * GOLD,
            guildfund.Ledger(),
            {"A": 250 * GOLD, "B": 250 * GOLD},
        )
        self.assertLessEqual(plan.total, 100 * GOLD)
        self.assertEqual(plan.withdraw, 100 * GOLD)

    def test_nobody_is_refunded_twice(self):
        rows = [
            {
                "target_name": "Grug",
                "source": "guildfund:refund:Eggrok",
                "command": "send money:73485 subject:Dues refund",
                "status": "delivered",
                "age": 9000,
            }
        ]
        book = guildfund.ledger(rows, "Grug")
        self.assertEqual(book.refunded, frozenset({"Eggrok"}))
        plan = guildfund.plan(
            "Grug",
            [member("Eggrok", 0, 60100)],
            155 * GOLD,
            book,
            {"Eggrok": 250 * GOLD},
        )
        self.assertFalse([x for x in plan.letters if x.kind == guildfund.REFUND])

    def test_a_bank_with_nothing_refunds_nothing(self):
        plan = guildfund.plan(
            "Zug",
            [member("Frostymon", 1415, 61600)],
            0,
            guildfund.Ledger(),
            {"Frostymon": 198 * GOLD},
        )
        self.assertEqual(plan.letters, ())
        self.assertEqual(plan.withdraw, 0)

    def test_training_letters_cover_the_trainer_inside_the_daily_limits(self):
        members = [member("A", 1000, 61600), member("B", 0, 30 * GOLD)]
        plan = guildfund.plan("Grug", members, 155 * GOLD, guildfund.Ledger(), {})
        got = {x.member: x.copper for x in plan.letters}
        self.assertEqual(got["A"], 60600)
        self.assertEqual(got["B"], guildfund.MEMBER_DAILY_COPPER)
        self.assertEqual(
            plan.letters[0].command, "send money:%d subject:For your training" % 60600
        )
        # A member already given today's limit waits.
        rows = [
            {
                "target_name": "Grug",
                "source": "guildfund:train:B",
                "status": "delivered",
                "command": "send money:100000 subject:For your training",
                "age": 60,
            }
        ]
        plan = guildfund.plan(
            "Grug", members, 155 * GOLD, guildfund.ledger(rows, "Grug"), {}
        )
        self.assertNotIn("B", {x.member for x in plan.letters})

    def test_the_guild_spends_half_its_bank_a_day_on_training(self):
        members = [member("M%d" % i, 0, 9 * GOLD) for i in range(20)]
        plan = guildfund.plan("Grug", members, 100 * GOLD, guildfund.Ledger(), {})
        self.assertLessEqual(plan.total, 50 * GOLD)

    def test_the_refunds_come_first_and_training_shares_what_is_left(self):
        members = [member("A", 0, 70 * GOLD)] + [
            member("M%d" % i, 0, 9 * GOLD) for i in range(20)
        ]
        plan = guildfund.plan(
            "Grug", members, 100 * GOLD, guildfund.Ledger(), {"A": 250 * GOLD}
        )
        refund = sum(x.copper for x in plan.letters if x.kind == guildfund.REFUND)
        training = sum(x.copper for x in plan.letters if x.kind == guildfund.TRAIN)
        self.assertEqual(refund, 70 * GOLD + guildfund.gear_budget(25))
        self.assertLessEqual(training, (100 * GOLD - refund) // 2)

    def test_the_family_and_the_master_are_not_funded_here(self):
        members = [member("Grug", 0, 9 * GOLD), member("Grog", 0, 9 * GOLD)]
        plan = guildfund.plan(
            "Grug", members, 100 * GOLD, guildfund.Ledger(), {}, roster={"Grog"}
        )
        self.assertEqual(plan.letters, ())

    def test_the_master_posts_only_what_it_withdrew(self):
        rows = [
            {
                "target_name": "Grug",
                "source": "guildfund:withdraw",
                "status": "applied",
                "command": "bank withdraw 80000",
            },
            {
                "target_name": "Grug",
                "source": "guildfund:withdraw",
                "status": "error",
                "command": "bank withdraw 80000",
            },
            {
                "target_name": "Grug",
                "source": "guildfund:train:A",
                "status": "error",
                "command": "send money:60000 subject:For your training",
                "age": 5,
            },
        ]
        book = guildfund.ledger(rows, "Grug")
        self.assertEqual(book.carried, 80000)
        members = [member("A", 0, 60000), member("B", 0, 60000)]
        plan = guildfund.plan("Grug", members, 155 * GOLD, book, {})
        self.assertEqual(plan.withdraw, 120000 - 80000)
        posted = guildfund.postable(plan, book.carried)
        self.assertEqual([x.member for x in posted], ["A"])

    def test_carried_gold_is_not_deposited_back(self):
        rows = [{"name": "Grug", "money": 200000}, {"name": "Grog", "money": 50000}]
        out = guildfund.hold_back(rows, {"Grug": 80000})
        self.assertEqual([r["money"] for r in out], [120000, 50000])


class GoldInTheGuildPost(unittest.TestCase):
    def test_a_letter_of_gold_is_taken_with_take_money(self):
        letter = guildpost.letter_from_row(
            {
                "receiver": "Eggrok",
                "mail_id": 77,
                "item_guid": 0,
                "money": 73485,
                "delivered": 1,
                "cod": 0,
            }
        )
        self.assertIsNotNone(letter)
        visits, _ = guildpost.visits([letter], {"Eggrok"}, free_slots={"Eggrok": 0})
        self.assertEqual([t.command for t in visits[0].takes], ["take-money mail:77"])

    def test_a_row_with_neither_item_nor_gold_is_skipped(self):
        self.assertIsNone(
            guildpost.letter_from_row(
                {"receiver": "Eggrok", "mail_id": 77, "item_guid": 0, "money": 0}
            )
        )


class BridgeWiring(unittest.TestCase):
    def test_both_passes_are_started(self):
        self.assertIn('_Pass("_guild_train_loop")', BRIDGE)
        self.assertIn('_Pass("_guild_fund_loop")', BRIDGE)

    def test_the_fund_withdraws_at_a_vault_and_posts_at_a_mailbox(self):
        body = function_source("_guild_fund_once")
        self.assertIn("guildfund.withdraw_command(plan.withdraw)", body)
        self.assertEqual(guildfund.withdraw_command(80000), "bank withdraw 80000")
        self.assertIn("guildfund.WITHDRAW_SOURCE", body)
        self.assertIn("_nearest_vault", body)
        self.assertIn("_holders_at_mailbox", body)
        self.assertIn("guildfund.postable(plan, carried)", body)
        self.assertNotIn("kind='give'", body)

    def test_the_bank_pass_walks_for_the_fund(self):
        self.assertIn('"_fund_wants"', function_source("_guild_bank_once"))

    def test_the_guild_money_read_holds_the_fund_back(self):
        self.assertIn("guildfund.hold_back", function_source("_fetch_guild_money"))

    def test_the_post_reads_letters_of_gold(self):
        self.assertIn("m.money > 0", BRIDGE)
        self.assertIn("list(names) * 2", function_source("_fetch_guild_post"))


if __name__ == "__main__":
    unittest.main()

"""Banked role upgrades use the equip scorer without changing seat policy."""

import unittest

from test_equip_score import member, piece


class BankedRoleUpgrades(unittest.TestCase):
    def test_a_real_healer_fetches_a_better_banked_chest(self):
        import setswap

        healer = member("Mender", 2, 60, talents="20473", skills="415")
        worn = piece(
            "Worn Robe", 20, holder="Mender", slot=4, guid=11, stats=((45, 5),)
        )
        banked = piece(
            "Healing Robe", 20, holder="Mender", guid=22, stats=((45, 60), (5, 20))
        )
        self.assertEqual(
            {22: "Mender"},
            setswap.bank_routes([healer], [worn], [banked], ["Mender"]),
        )


class TheExistingBankPlanFetchesTheUpgrade(unittest.TestCase):
    def plan(self, bag_count=0, scored_available=True, routes=None):
        import ast
        import pathlib
        import types
        from unittest.mock import Mock

        import bank
        import bankbags
        import bankpolicy
        import setswap

        routes = routes or {}
        source = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
        functions = [
            node
            for node in ast.parse(source.read_text()).body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_plan_bank", "_bank_role_routes"}
        ]
        healer = member("Mender", 2, 60, talents="20473", skills="415")
        worn = piece(
            "Worn Robe", 20, holder="Mender", slot=4, guid=11, stats=((45, 5),)
        )
        banked = piece(
            "Healing Robe", 20, holder="Mender", guid=22, stats=((45, 60), (5, 20))
        )
        inventory = [
            dict(
                banked,
                level=60,
                bag=0,
                slot=39,
                count=1,
                bonding=1,
                sell_price=1,
                container_slots=0,
            )
        ]
        inventory += [
            dict(
                banked,
                item_guid=100 + i,
                item_class=0,
                bag=0,
                slot=23 + i,
                level=60,
                count=1,
            )
            for i in range(bag_count)
        ]
        policy = {
            22: bankpolicy.Placement(
                22,
                "Mender",
                "Healing Robe",
                bankpolicy.PERSONAL,
                None,
                "healing set",
                "kept as a healing set",
            )
        }
        namespace = dict(
            bank=bank,
            bankbags=bankbags,
            setswap=setswap,
            OWNER_KEEPS=(),
            REAGENT_TRADES={},
            _GUILD_BANK_KEEPS={},
            _fetch_bank_items=lambda names: inventory,
            _fetch_trade_skills=lambda names: {},
            _worked_by=lambda names: {},
            _fetch_guild_bank_setup=lambda names: None,
            _crafter_plan=lambda names: types.SimpleNamespace(
                routed=routes.get("crafter", {})
            ),
            _tidy_routes=lambda names: routes.get("tidy", {}),
            _withdrawn_for_sale_routes=lambda names: routes.get("sale", {}),
            _bank_policy=lambda names: policy,
            _bank_spare=lambda names: frozenset(),
            _bank_forecast=lambda names: types.SimpleNamespace(over_target={}),
            _campaign_waiting=lambda names: False,
            _fetch_bank_bag_facts=lambda names: [],
            _fetch_wearers=lambda names: [healer],
            _fetch_scored_gear=lambda names, banked=False: (
                [banked_row] if banked else ([worn] if scored_available else [])
            ),
            _jev_item_book=lambda: None,
            log=Mock(),
        )
        banked_row = banked
        exec(
            compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"),
            namespace,
        )
        return namespace["_plan_bank"](["Mender"])

    def test_the_bank_plan_withdraws_the_kept_actual_healer_upgrade(self):
        import bank

        plan = self.plan()
        self.assertEqual(
            [("Mender", "withdraw guid:22")],
            [(move.character, bank.command(move)) for move in plan.moves],
        )

    def test_existing_crafter_tidy_and_sale_routes_keep_precedence(self):
        for source in ("crafter", "tidy", "sale"):
            with self.subTest(source=source):
                plan = self.plan(routes={source: {22: "Recipient"}})
                self.assertEqual(1, len(plan.moves))
                self.assertIn("Healing Robe is for Recipient", plan.moves[0].why)

    def test_unreadable_worn_facts_do_not_treat_the_holder_as_naked(self):
        self.assertEqual((), self.plan(scored_available=False).moves)

    def test_a_full_backpack_keeps_the_upgrade_in_the_bank(self):
        self.assertEqual((), self.plan(bag_count=16).moves)


class OnlyUsableBankedUpgradesLeaveStorage(unittest.TestCase):
    def setUp(self):
        self.healer = member("Mender", 2, 60, talents="20473", skills="415")
        self.worn = piece(
            "Worn Robe", 20, holder="Mender", slot=4, guid=11, stats=((45, 30),)
        )
        self.banked = piece(
            "Healing Robe", 20, holder="Mender", guid=22, stats=((45, 60), (5, 20))
        )

    def routes(self, people=None, gear=None, banked=None, **kwargs):
        import setswap

        return setswap.bank_routes(
            [self.healer] if people is None else people,
            [self.worn] if gear is None else gear,
            [self.banked] if banked is None else banked,
            ["Mender"],
            **kwargs,
        )

    def test_a_lower_scoring_piece_stays_banked(self):
        weak = dict(self.banked, stat_value1=2, stat_value2=1)
        self.assertEqual({}, self.routes(banked=[weak]))

    def test_an_upgrade_already_in_the_bags_prevents_a_weaker_withdrawal(self):
        carried = dict(self.banked, item_guid=33, stat_value1=120)
        self.assertEqual({}, self.routes(gear=[self.worn, carried]))

    def test_an_unspent_healing_target_does_not_assign_a_healer_role(self):
        unspent = dict(self.healer, talent_spells="", target_tree="Holy")
        self.assertEqual({}, self.routes(people=[unspent]))

    def test_a_damage_spec_does_not_get_healing_gear_by_changing_its_target(self):
        damage = dict(self.healer, talent_spells="20066", target_tree="Holy")
        self.assertEqual({}, self.routes(people=[damage]))

    def test_a_member_outside_the_family_cannot_fetch_a_family_piece(self):
        outsider = dict(self.healer, name="Visitor")
        self.assertEqual({}, self.routes(people=[outsider]))

    def test_missing_proficiency_keeps_the_piece_banked(self):
        mail = dict(self.banked, item_subclass=3)
        self.assertEqual({}, self.routes(banked=[mail]))

    def test_an_owner_named_keep_is_not_withdrawn_for_an_equip(self):
        self.assertEqual({}, self.routes(keep_names=["Healing Robe"]))


class ScoredBankReadsKeepTheInventoryBoundaries(unittest.TestCase):
    def namespace(self):
        import ast
        import pathlib
        from unittest.mock import MagicMock

        source = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
        nodes = []
        for node in ast.parse(source.read_text()).body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name)
                and t.id
                in {
                    "_SCORED_GEAR_SQL",
                    "_BANKED_SCORED_GEAR_SQL",
                }
                for t in node.targets
            ):
                nodes.append(node)
            elif (
                isinstance(node, ast.FunctionDef) and node.name == "_fetch_scored_gear"
            ):
                nodes.append(node)
        conn, cursor = MagicMock(), MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.return_value = []
        namespace = {"_connect": lambda: conn}
        exec(
            compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"),
            namespace,
        )
        return namespace, cursor

    def test_banked_selector_reads_only_personal_bank_slots_and_bags(self):
        import sqlglot

        namespace, cursor = self.namespace()
        namespace["_fetch_scored_gear"](["Mender"], banked=True)
        sql, arguments = cursor.execute.call_args.args
        self.assertEqual(["Mender"], arguments)
        banked = sqlglot.parse_one(sql.replace("%s", "'Mender'"), read="mysql")
        where = banked.args["where"].sql()
        self.assertIn("ci.slot BETWEEN 39 AND 66", where)
        self.assertIn("bag.slot BETWEEN 67 AND 73", where)
        self.assertNotIn("ci.slot < 19", where)
        self.assertNotIn("ci.slot BETWEEN 19 AND 38", where)
        self.assertNotIn("bag.slot BETWEEN 19 AND 22", where)
        normal = sqlglot.parse_one(
            namespace["_SCORED_GEAR_SQL"].replace("%s", "'Mender'"), read="mysql"
        )
        self.assertEqual(normal.expressions, banked.expressions)
        for column in (
            "ii.randomPropertyId",
            "ii.enchantments",
            "it.spellid_1",
            "it.requiredspell",
        ):
            self.assertIn(column, sql)

    def test_default_selector_still_reads_worn_and_carried_items_only(self):
        namespace, cursor = self.namespace()
        namespace["_fetch_scored_gear"](["Mender"])
        sql, _arguments = cursor.execute.call_args.args
        self.assertIn("ci.slot BETWEEN 19 AND 38", sql)
        self.assertIn("bag.slot BETWEEN 19 AND 22", sql)
        self.assertNotIn("ci.slot BETWEEN 39 AND 66", sql)
        self.assertNotIn("bag.slot BETWEEN 67 AND 73", sql)

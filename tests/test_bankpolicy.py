"""The bank policy (#320): what a raid guild keeps, where, and why."""

from __future__ import annotations

import pathlib
import sys
import types
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bag_pressure  # noqa: E402
import bank  # noqa: E402
import bankpolicy  # noqa: E402
import disposition  # noqa: E402
import guildbank  # noqa: E402
import jev_items  # noqa: E402
import raidsupply  # noqa: E402
import vclient  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

WARRIOR, PALADIN, PRIEST, MAGE, ROGUE = 1, 2, 5, 8, 4


def reach(
    holder="Grog", bucket="off_hand", role="damage", cls=PALADIN, wears=True, guild=()
):
    return bag_pressure.GearReach(
        bucket=bucket,
        holder_role=role,
        holder_class=cls,
        holder_level=60,
        holder_wears=wears,
        later_wearers=tuple(guild),
    )


def keeper(name="Grog", cls=PALADIN, role="damage", trades=()):
    return bankpolicy.Keeper(name, cls, 60, role, frozenset(trades))


def piece(guid, name="Piece", holder="Grog", **kw):
    base = dict(
        holder=holder,
        guid=guid,
        entry=kw.pop("entry", 90000 + guid),
        name=name,
        quality=kw.pop("quality", 2),
        item_class=kw.pop("item_class", bankpolicy.ARMOR),
        required_level=kw.pop("required_level", 55),
        item_level=kw.pop("item_level", 60),
        bound=kw.pop("bound", True),
    )
    base.update(kw)
    return bankpolicy.Piece(**base)


TANK_STATS = (("stamina", 12), ("defense", 8), ("block", 5))
DAMAGE_STATS = (("strength", 12), ("crit", 1))


class AFamilyMemberKeepsItsSecondSet(unittest.TestCase):
    def test_a_damage_paladin_keeps_its_tank_shield(self):
        shield = piece(1, "Templar Shield", stats=TANK_STATS, armor=2000)
        facts = bankpolicy.Facts(
            pieces=(shield,), family=(keeper(),), reach={1: reach()}
        )
        placed = bankpolicy.place(facts)[1]
        self.assertEqual(bankpolicy.PERSONAL, placed.to)
        self.assertEqual("tank set", placed.kind)
        self.assertEqual("Grog's bank", placed.where)
        self.assertIn("tank set", placed.why)

    def test_gear_for_its_own_role_is_not_a_second_set(self):
        sword = piece(2, "Runeblade", stats=DAMAGE_STATS)
        facts = bankpolicy.Facts(
            pieces=(sword,), family=(keeper(),), reach={2: reach(bucket="weapon")}
        )
        self.assertEqual({}, bankpolicy.place(facts))

    def test_only_the_best_piece_per_slot_is_kept(self):
        worse = piece(3, "Old Shield", stats=TANK_STATS, item_level=50)
        better = piece(4, "New Shield", stats=TANK_STATS, item_level=58)
        facts = bankpolicy.Facts(
            pieces=(worse, better), family=(keeper(),), reach={3: reach(), 4: reach()}
        )
        self.assertEqual([4], sorted(bankpolicy.place(facts)))

    def test_fire_resistance_it_can_wear_is_its_molten_core_set(self):
        legs = piece(5, "Flarecore Leggings", fire_res=16, stats=(("stamina", 5),))
        facts = bankpolicy.Facts(
            pieces=(legs,), family=(keeper(),), reach={5: reach(bucket="legs")}
        )
        placed = bankpolicy.place(facts)[5]
        self.assertEqual(
            (bankpolicy.PERSONAL, "fire resistance set"), (placed.to, placed.kind)
        )
        self.assertIn("+16 fire resistance for Molten Core", placed.why)

    def test_pvp_gear_is_kept_only_when_its_source_is_pvp(self):
        honor = piece(6, "Knight-Captain's Chain Hauberk", pvp=True, stats=DAMAGE_STATS)
        plain = piece(7, "Chain Hauberk", stats=DAMAGE_STATS)
        facts = bankpolicy.Facts(
            pieces=(honor, plain),
            family=(keeper(),),
            reach={6: reach(bucket="chest"), 7: reach(bucket="chest")},
        )
        placed = bankpolicy.place(facts)
        self.assertEqual("PvP set", placed[6].kind)
        self.assertNotIn(7, placed)

    def test_a_piece_the_gear_passes_claim_is_left_to_them(self):
        shield = piece(8, "Templar Shield", stats=TANK_STATS)
        facts = bankpolicy.Facts(
            pieces=(shield,),
            family=(keeper(),),
            reach={8: reach()},
            claimed=frozenset({8}),
        )
        self.assertEqual({}, bankpolicy.place(facts))

    def test_an_outgrown_piece_is_not_a_set(self):
        shield = piece(9, "Buckler", stats=TANK_STATS, required_level=30)
        facts = bankpolicy.Facts(
            pieces=(shield,), family=(keeper(),), reach={9: reach()}
        )
        self.assertEqual({}, bankpolicy.place(facts))

    def test_a_quest_item_is_the_quest_rules(self):
        shield = piece(10, "Shield", stats=TANK_STATS, quest_needed=True)
        facts = bankpolicy.Facts(
            pieces=(shield,), family=(keeper(),), reach={10: reach()}
        )
        self.assertEqual({}, bankpolicy.place(facts))

    def test_a_banked_set_piece_stays_placed(self):
        shield = piece(11, "Templar Shield", stats=TANK_STATS, place="bank")
        facts = bankpolicy.Facts(
            pieces=(shield,), family=(keeper(),), reach={11: reach()}
        )
        self.assertEqual(bankpolicy.PERSONAL, bankpolicy.place(facts)[11].to)


class WhatTheHolderGrowsIntoWaitsInItsOwnBank(unittest.TestCase):
    """The family is lowered to its natural levels: Grog, about 36, keeps his
    epic Destiny (level 52) in his own bank until he can wear it again."""

    def grog(self, level=36):
        return bankpolicy.Keeper("Grog", PALADIN, level, "damage", frozenset())

    def destiny(self, **kw):
        base = dict(quality=4, required_level=52, item_class=bankpolicy.WEAPON)
        base.update(kw)
        return piece(647, "Destiny", **base)

    def test_destiny_waits_in_groggs_bank_until_52(self):
        facts = bankpolicy.Facts(
            pieces=(self.destiny(),),
            family=(self.grog(),),
            reach={647: reach(bucket="weapon", guild=("Grug",))},
        )
        placed = bankpolicy.place(facts)[647]
        self.assertEqual(
            (bankpolicy.PERSONAL, bankpolicy.GROWS_INTO), (placed.to, placed.kind)
        )
        self.assertIn("Grog keeps Destiny until level 52", placed.why)

    def test_even_tradable_it_never_goes_to_the_guild(self):
        facts = bankpolicy.Facts(
            pieces=(self.destiny(bound=False),),
            family=(self.grog(),),
            reach={647: reach(bucket="weapon", guild=("Grug",))},
        )
        self.assertEqual(bankpolicy.PERSONAL, bankpolicy.place(facts)[647].to)

    def test_at_its_level_it_is_the_gear_passes_again(self):
        facts = bankpolicy.Facts(
            pieces=(self.destiny(),),
            family=(self.grog(60),),
            reach={647: reach(bucket="weapon")},
        )
        self.assertEqual({}, bankpolicy.place(facts))

    def test_every_piece_it_grows_into_is_kept(self):
        a = piece(
            1, "Blade A", quality=3, required_level=40, item_class=bankpolicy.WEAPON
        )
        b = piece(
            2, "Blade B", quality=3, required_level=50, item_class=bankpolicy.WEAPON
        )
        facts = bankpolicy.Facts(
            pieces=(a, b),
            family=(self.grog(),),
            reach={1: reach(bucket="weapon"), 2: reach(bucket="weapon")},
        )
        self.assertEqual([1, 2], sorted(bankpolicy.place(facts)))


class TheOperatorsReservationOutranksEveryRule(unittest.TestCase):
    def rows(self):
        return [
            {
                "character": "Grog",
                "item": 647,
                "reason": "his sword",
                "until_level": 52,
            },
            {"character": "Somebody", "item": 1, "until_level": 10},
            {"character": "Grog", "item": 0},
        ]

    def test_rows_are_read_by_name_for_the_family_only(self):
        got = bankpolicy.reservations_from_rows(self.rows(), ["Grog", "Og"])
        self.assertEqual((bankpolicy.Reservation("Grog", 647, 52, "his sword"),), got)
        alias = bankpolicy.reservations_from_rows(
            [{"name": "Og", "item_guid": 9, "level": 30}], ["Og"]
        )
        self.assertEqual((bankpolicy.Reservation("Og", 9, 30, ""),), alias)

    def test_a_reserved_potion_is_kept_home_not_sent_to_the_raid(self):
        potion = piece(
            21,
            "Greater Fire Protection Potion",
            item_class=0,
            bound=False,
            entry=raidsupply.GREATER_FIRE_PROTECTION,
            count=9,
        )
        facts = bankpolicy.Facts(
            pieces=(potion,),
            family=(keeper(),),
            reserved=(
                bankpolicy.Reservation(
                    "Grog", raidsupply.GREATER_FIRE_PROTECTION, 0, "mine"
                ),
            ),
        )
        placed = bankpolicy.place(facts)[21]
        self.assertEqual(
            (bankpolicy.PERSONAL, bankpolicy.RESERVED), (placed.to, placed.kind)
        )
        self.assertEqual("Grog keeps Greater Fire Protection Potion: mine", placed.why)

    def test_the_level_it_waits_for_is_on_the_page(self):
        blade = piece(
            30, "Destiny", quality=4, bound=False, item_class=bankpolicy.WEAPON
        )
        facts = bankpolicy.Facts(
            pieces=(blade,),
            family=(keeper(),),
            reach={30: reach(bucket="weapon", wears=False, guild=("Aleth",))},
            reserved=(bankpolicy.Reservation("Grog", 30, 70, ""),),
        )
        placed = bankpolicy.place(facts)[30]
        self.assertEqual(bankpolicy.PERSONAL, placed.to)
        self.assertEqual(
            "Bank: Grog's bank - Grog keeps Destiny until level 70", placed.line
        )

    def test_a_reservation_whose_level_is_reached_places_nothing(self):
        blade = piece(30, "Destiny", quality=4, item_class=bankpolicy.WEAPON)
        facts = bankpolicy.Facts(
            pieces=(blade,),
            family=(keeper(),),
            reach={30: reach(bucket="weapon")},
            reserved=(bankpolicy.Reservation("Grog", 30, 52, ""),),
        )
        self.assertEqual({}, bankpolicy.place(facts))


class TheRaidsSuppliesGoToTheirTab(unittest.TestCase):
    def test_potions_past_the_holders_own_night_are_banked(self):
        # A damage paladin drinks two Greater Fire Protection a night.
        want = raidsupply.SUPPLIES[0].per_raider(
            raidsupply.Raider("Grog", raidsupply.PHYSICAL, PALADIN)
        )
        self.assertEqual(2, want)
        kept = piece(
            20,
            "Greater Fire Protection Potion",
            item_class=0,
            bound=False,
            entry=raidsupply.GREATER_FIRE_PROTECTION,
            count=2,
        )
        spare = piece(
            21,
            "Greater Fire Protection Potion",
            item_class=0,
            bound=False,
            entry=raidsupply.GREATER_FIRE_PROTECTION,
            count=1,
        )
        facts = bankpolicy.Facts(pieces=(kept, spare), family=(keeper(),))
        placed = bankpolicy.place(facts)
        self.assertEqual([21], sorted(placed))
        self.assertEqual(
            (bankpolicy.GUILD, bankpolicy.RAID_TAB), (placed[21].to, placed[21].tab)
        )
        self.assertIn("past the 2 Grog drinks in one night", placed[21].why)

    def test_a_reagent_the_holder_does_not_brew_is_banked(self):
        fire = piece(
            22,
            "Elemental Fire",
            item_class=7,
            bound=False,
            entry=raidsupply.ELEMENTAL_FIRE,
            count=4,
        )
        facts = bankpolicy.Facts(pieces=(fire,), family=(keeper(),))
        placed = bankpolicy.place(facts)[22]
        self.assertEqual(bankpolicy.RAID_TAB, placed.tab)
        self.assertIn("Greater Fire Protection Potion", placed.why)

    def test_an_alchemist_keeps_its_own_reagents(self):
        fire = piece(
            23,
            "Elemental Fire",
            item_class=7,
            bound=False,
            entry=raidsupply.ELEMENTAL_FIRE,
            holder="Ugga",
            count=4,
        )
        facts = bankpolicy.Facts(
            pieces=(fire,), family=(keeper("Ugga", PRIEST, "healer", ("alchemy",)),)
        )
        self.assertEqual({}, bankpolicy.place(facts))

    def test_fire_resistance_the_holder_cannot_wear_goes_to_the_raid(self):
        robe = piece(24, "Robe of the Flame", fire_res=10, bound=False)
        facts = bankpolicy.Facts(
            pieces=(robe,),
            family=(keeper(),),
            reach={24: reach(bucket="chest", wears=False)},
        )
        placed = bankpolicy.place(facts)[24]
        self.assertEqual(
            (bankpolicy.GUILD, bankpolicy.RAID_TAB), (placed.to, placed.tab)
        )


class RareGearIsKeptForLater(unittest.TestCase):
    def test_a_tradable_rare_nobody_wears_now_goes_to_gear_for_later(self):
        blade = piece(
            30, "Destiny", quality=4, bound=False, item_class=bankpolicy.WEAPON
        )
        facts = bankpolicy.Facts(
            pieces=(blade,),
            family=(keeper(),),
            reach={30: reach(bucket="weapon", wears=False, guild=("Aleth", "Bran"))},
        )
        placed = bankpolicy.place(facts)[30]
        self.assertEqual(
            (bankpolicy.GUILD, bankpolicy.GEAR_TAB), (placed.to, placed.tab)
        )
        self.assertIn(
            "epic gear nobody in the family wears now; Aleth and 1 more", placed.why
        )
        self.assertEqual("the guild bank's Gear for Later tab", placed.where)

    def test_bound_uncommon_or_unwearable_gear_is_not(self):
        bound = piece(31, "Bound", quality=3, bound=True)
        green = piece(32, "Green", quality=2, bound=False)
        nobody = piece(33, "Nobody", quality=3, bound=False)
        facts = bankpolicy.Facts(
            pieces=(bound, green, nobody),
            family=(keeper(),),
            reach={
                31: reach(wears=False, guild=("A",)),
                32: reach(wears=False, guild=("A",)),
                33: reach(wears=False),
            },
        )
        self.assertEqual({}, bankpolicy.place(facts))


class TheFactsAreReadFromRows(unittest.TestCase):
    def row(self, **kw):
        base = {
            "holder": "Grog",
            "item_guid": 1,
            "entry": 16367,
            "count": 1,
            "instance_flags": 0,
            "bag": 0,
            "slot": 30,
            "name": "Knight-Captain's Silk Sash",
            "quality": 3,
            "item_class": 4,
            "item_subclass": 1,
            "inventory_type": 6,
            "required_level": 58,
            "allowable_class": -1,
            "item_level": 63,
            "bonding": 1,
            "fire_res": 0,
            "armor": 60,
            "container_slots": 0,
            "honor_rank": 12,
            "rep_faction": 0,
            "has_effect": 0,
            "pvp_vendor": 0,
            "quest_needed": 0,
            "stat_type1": 7,
            "stat_value1": 10,
        }
        base.update(kw)
        return base

    def test_an_honor_rank_is_pvp_and_stats_are_named(self):
        (p,) = bankpolicy.pieces_from_rows([self.row()])
        self.assertTrue(p.pvp)
        self.assertEqual((("stamina", 10),), p.stats)
        self.assertTrue(p.bound)
        self.assertEqual("bags", p.place)

    def test_a_vendor_or_battleground_source_is_pvp_and_a_drop_is_not(self):
        vendor, faction, drop = bankpolicy.pieces_from_rows(
            [
                self.row(item_guid=1, honor_rank=0, pvp_vendor=1),
                self.row(item_guid=2, honor_rank=0, rep_faction=890),
                self.row(item_guid=3, honor_rank=0),
            ]
        )
        self.assertEqual((True, True, False), (vendor.pvp, faction.pvp, drop.pvp))

    def test_the_bank_and_its_bags_are_the_bank(self):
        bag = self.row(item_guid=500, slot=67, container_slots=16)
        inside = self.row(item_guid=2, bag=500, slot=3)
        slot = self.row(item_guid=3, slot=40)
        pieces = {p.guid: p for p in bankpolicy.pieces_from_rows([bag, inside, slot])}
        self.assertNotIn(500, pieces)
        self.assertEqual(("bank", "bank"), (pieces[2].place, pieces[3].place))

    def test_the_sql_survives_both_formatting_passes(self):
        """`% marks`, then pymysql's `query % args`: one %s per name and no
        other percent sign, or pymysql reads it as a format spec."""
        sql = bankpolicy.ITEMS_SQL % "%s,%s"
        self.assertEqual(2, sql.count("%"))
        self.assertIn("LOCATE('Arena', ct.subname) > 0", sql)
        self.assertIn("AS quest_needed", sql)
        for other in (bankpolicy.WORN_SQL, bankpolicy.SKILLS_SQL):
            self.assertEqual(2, (other % "%s,%s").count("%"))

    def test_gear_reach_counts_only_the_family(self):
        """Natural things only: a factory-levelled guild member is never a
        wearer; a family member who will level into the piece is."""
        gear_rows = [
            self.row(
                item_guid=7,
                name="Mail Helm",
                item_subclass=3,
                inventory_type=1,
                honor_rank=0,
                required_level=50,
            )
        ]
        worn = [
            {
                "name": "Grog",
                "class_id": PALADIN,
                "level": 60,
                "inventory_type": 1,
                "item_level": 66,
            },
            {"name": "Zork", "class_id": 7, "level": 20},
            {"name": "Oz", "class_id": MAGE, "level": 20},
            # Already past the level: never a LATER wearer.
            {"name": "Zug", "class_id": 7, "level": 60},
        ]
        fit = bag_pressure.gear_reach(gear_rows, worn, ["Grog", "Zork", "Oz", "Zug"])[7]
        self.assertTrue(fit.holder_wears)
        self.assertEqual("head", fit.bucket)
        # A shaman trains mail at 40 and will wear it at 50; a mage never will.
        self.assertEqual(("Zork",), fit.later_wearers)
        self.assertNotIn("GUILD_SQL", dir(bankpolicy))


class TheBankPlanFollowsThePolicy(unittest.TestCase):
    GUILD = {
        "purchased_tabs": 3,
        "deposit_rank_ids": (0, 1),
        "member_ranks": {"Grog": 1},
        "tab0_items": 10,
        "tab_items": {0: 10, 1: 0, 2: 0},
    }

    def member(self, *holdings):
        return bank.Member(
            name="Grog", level=60, bag_free=0, bank_free=10, carried=tuple(holdings)
        )

    def holding(self, guid, name, item_class, bound):
        return bank.Holding(
            holder="Grog",
            guid=guid,
            place=bank.BAGS,
            count=1,
            container_slots=0,
            item=disposition.Item(
                name=name,
                known=True,
                quality=3,
                item_class=item_class,
                quest_item=False,
                equipment=item_class in (2, 4),
            ),
            template_id=guid,
            bound=bound,
        )

    def plan(self, placed, guild=None):
        storage = bank.storage_from({}, guild=guild or self.GUILD, policy=placed)
        members = [
            self.member(
                self.holding(1, "Templar Shield", 4, True),
                self.holding(2, "Destiny", 2, False),
                self.holding(3, "Greater Fire Protection Potion", 0, False),
            )
        ]
        return bank.plan(members, disposition.Family(), storage=storage)

    def placed(self):
        def p(guid, item, to, tab, kind):
            return bankpolicy.Placement(guid, "Grog", item, to, tab, kind, "because")

        return {
            1: p(1, "Templar Shield", bankpolicy.PERSONAL, None, "tank set"),
            2: p(2, "Destiny", bankpolicy.GUILD, bankpolicy.GEAR_TAB, "gear for later"),
            3: p(
                3,
                "Greater Fire Protection Potion",
                bankpolicy.GUILD,
                bankpolicy.RAID_TAB,
                "raid supply",
            ),
        }

    def test_each_goes_where_the_policy_says(self):
        result = self.plan(self.placed())
        self.assertEqual(["deposit guid:1"], [bank.command(m) for m in result.moves])
        self.assertEqual(
            ["bank deposit-item guid:2 tab:1", "bank deposit-item guid:3 tab:2"],
            [bank.command(m) for m in result.guild],
        )

    def test_a_tab_not_bought_yet_falls_back_to_materials(self):
        guild = dict(self.GUILD, purchased_tabs=1, tab_items={0: 10})
        result = self.plan(self.placed(), guild)
        self.assertEqual(
            ["bank deposit-item guid:2", "bank deposit-item guid:3"],
            [bank.command(m) for m in result.guild],
        )

    def test_a_kept_set_in_the_bank_is_never_withdrawn(self):
        shield = self.holding(1, "Templar Shield", 4, True)
        banked = bank.Holding(**{**shield.__dict__, "place": bank.BANK})
        storage = bank.storage_from({}, guild=self.GUILD, policy=self.placed())
        self.assertTrue(bank.storage_reason(banked, storage))

    def test_the_item_verb_names_its_tab(self):
        self.assertEqual(
            "bank deposit-item guid:5 tab:2",
            guildbank.format_item_deposit(item_guid=5, tab=2),
        )
        self.assertEqual(
            "bank deposit-item guid:5", guildbank.format_item_deposit(item_guid=5)
        )
        with self.assertRaises(ValueError):
            guildbank.format_item_deposit(item_guid=5, tab=6)


class JevIsAskedWithTheBankOnOffer(unittest.TestCase):
    def test_the_bank_route_is_offered_in_the_policys_words(self):
        class H:
            holder, name, soulbound = "Grog", "Templar Shield", True

        offered = jev_items.options(
            {"sell_price": 100}, H, (), "Bank: Grog's bank - a tank set"
        )
        self.assertIn(jev_items.BANK, offered)
        self.assertIn("a tank set", offered[jev_items.BANK])
        self.assertNotIn(jev_items.BANK, jev_items.options({}, H, ()))

    def test_the_heuristic_banks_and_never_sells_a_kept_piece(self):
        pipeline = jev_items.Pipeline(
            claimants={1: bag_pressure.CLAIM_NOBODY},
            equipping=frozenset(),
            selling=frozenset(),
            banked={1: "Bank: Grog's bank - a tank set"},
        )
        route, why = pipeline.route({"name": "Templar Shield"}, 1, "Grog")
        self.assertEqual(jev_items.BANK, route)
        self.assertIn("tank set", why)

    def test_a_sale_jev_prefers_has_no_path_to_act(self):
        """A confident vendor answer cannot override the policy's keep: only
        keep and equip act, and never against a bank route."""
        for answer in (
            jev_items.VENDOR,
            jev_items.AUCTION,
            jev_items.KEEP,
            jev_items.EQUIP,
            jev_items.BANK,
        ):
            judged = types.SimpleNamespace(jev=answer, heuristic=jev_items.BANK)
            self.assertFalse(jev_items._disposition_can(judged), answer)


class ThePageSaysWhy(unittest.TestCase):
    def test_a_cell_carries_its_reason(self):
        cell = vclient.item_cell(
            {"entry": 1, "item_name": "X", "why": "Bank: here"}, {}
        )
        self.assertEqual("Bank: here", cell["why"])
        self.assertNotIn("why", vclient.item_cell({"entry": 1, "item_name": "X"}, {}))

    def test_a_guild_bank_tab_says_what_it_holds(self):
        frame = vclient.build_guild_bank(
            {"guild_name": "Cave", "bank_money": 0},
            [{"tab_id": 1, "tab_name": "Gear for Later", "tab_holds": "rare gear"}],
            [],
            {},
        )
        self.assertEqual("rare gear", frame["tabs"][0]["holds"])

    def test_a_stored_item_says_why_from_its_tab_and_kind(self):
        why = bankpolicy.why_stored({"tab_id": 2, "entry": raidsupply.ELEMENTAL_FIRE})
        self.assertIn("a reagent for Greater Fire Protection Potion", why)
        self.assertIn("Raid Supplies:", why)
        self.assertIn("Materials:", bankpolicy.why_stored({"tab_id": 0, "entry": 1}))

    def test_the_bags_tooltip_gains_the_line(self):
        placed = {
            7: bankpolicy.Placement(
                7, "Grog", "Shield", bankpolicy.PERSONAL, None, "tank set", "kept"
            )
        }
        payload = {"members": [{"items": [{"guid": 7, "tip": "Shield"}]}]}
        self.assertEqual(1, bankpolicy.annotate_tips(payload, placed))
        self.assertEqual(
            "Shield\nBank: Grog's bank - kept", payload["members"][0]["items"][0]["tip"]
        )

    def test_the_server_reads_the_policy_for_every_bank_view(self):
        source = (ROOT / "map_server.py").read_text(encoding="utf-8")
        bags = source[
            source.index("    def _client_bags(") : source.index(
                "    def _client_guild_bank("
            )
        ]
        self.assertEqual(
            2, bags.count('_with_bank_reasons(f["rows"], _fetch_bank_policy(names))')
        )
        self.assertIn(
            "bankpolicy.annotate_tips(payload, _fetch_bank_policy(group))", source
        )
        self.assertIn('item["why"] = bankpolicy.why_stored(item)', source)
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(
            'if (item.why) t.appendChild(el("div", "vcsub vcwhy", item.why));', page
        )
        self.assertIn("if (tab.holds)", page)


class TheSellPassesSkipWhatThePolicyKeeps(unittest.TestCase):
    SOURCE = (ROOT / "bridge.py").read_text(encoding="utf-8")

    def test_the_vendor_pass_filters_its_candidates(self):
        body = self.SOURCE[self.SOURCE.index("    async def _vendor_once(") :]
        body = body[: body.index("\n    async def ")]
        self.assertIn("candidates = _without_bank_keeps(", body)

    def test_the_auction_pass_lists_nothing_the_policy_keeps(self):
        body = self.SOURCE[self.SOURCE.index("    async def _auction_sales_once(") :]
        body = body[: body.index("\n    async def ")]
        self.assertIn("not in banked", body)
        self.assertIn("banked[guid].where", body)

    def test_the_bank_plan_is_given_the_policy(self):
        body = self.SOURCE[self.SOURCE.index("def _plan_bank(") :]
        body = body[: body.index("\ndef ")]
        self.assertIn("policy=_bank_policy(names)", body)

    def test_the_filter_drops_kept_guids_only(self):
        ns = {"_log_capped": lambda prefix, notes: None}
        start = self.SOURCE.index("def _without_bank_keeps(")
        end = self.SOURCE.index("\ndef ", start + 1)
        exec(compile(self.SOURCE[start:end], "bridge.py", "exec"), ns)  # noqa: S102

        class C:
            def __init__(self, guid):
                self.item_guid = guid

        placed = {
            2: bankpolicy.Placement(2, "Grog", "X", bankpolicy.PERSONAL, None, "k", "w")
        }
        kept = ns["_without_bank_keeps"]([C(1), C(2)], placed, "economy")
        self.assertEqual([1], [c.item_guid for c in kept])

    def test_the_sell_passes_read_a_fresh_policy(self):
        self.assertEqual(
            2, self.SOURCE.count("asyncio.to_thread(_bank_policy, names, True)")
        )

    def test_a_kept_at_home_move_never_reaches_the_guild(self):
        ns = {
            "log": types.SimpleNamespace(exception=lambda *a: None),
            "bankpolicy": bankpolicy,
        }
        start = self.SOURCE.index("def _not_kept_at_home(")
        end = self.SOURCE.index("\ndef ", start + 1)
        exec(compile(self.SOURCE[start:end], "bridge.py", "exec"), ns)  # noqa: S102
        home = bankpolicy.Placement(1, "Grog", "X", bankpolicy.PERSONAL, None, "k", "w")
        ns["_bank_policy"] = lambda names: {1: home}
        moves = [types.SimpleNamespace(guid=1), types.SimpleNamespace(guid=2)]
        self.assertEqual(
            [2], [m.guid for m in ns["_not_kept_at_home"](moves, ["Grog"])]
        )

        def broken(names):
            raise RuntimeError("down")

        ns["_bank_policy"] = broken
        self.assertEqual((), ns["_not_kept_at_home"](moves, ["Grog"]))

    def test_jevs_routes_survive_an_unreadable_policy(self):
        body = self.SOURCE[self.SOURCE.index("    async def _jev_items_plan(") :]
        body = body[: body.index("\n    def ")]
        self.assertIn("asyncio.to_thread(_bank_policy_lines_or_none, names)", body)

    def test_the_module_is_in_the_image(self):
        self.assertIn(
            "bankpolicy.py", (ROOT / "Dockerfile").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()

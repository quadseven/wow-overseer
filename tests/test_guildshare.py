"""Which family surplus reaches which guildmate, and which never should.

Pure unit tests against synthetic Holdings and Members, the same seam and the
same honesty as tests/test_materials.py: this suite proves the DECISION is
right for the inputs given. It does not prove bridge.py's SQL produces those
inputs, and it does not re-prove `kind='give'` itself - tests/test_give.py
already holds the mechanism.

WHAT IT DOES CARRY THAT IS NOT SYNTHETIC. The fixtures below are the realm as
it was measured while this was written: Og holding 151 Bolts of Linen Cloth
across eight stacks, forty guild members of whom SIX were online, and the one
online recruit being a level 40 mage carrying Tailoring 145 / First Aid 200 on
another continent. Every number in `_measured_*` came off the live database,
so a rule that passes here has been checked against a real shape rather than a
convenient one.
"""

import pathlib
import unittest

import craft_rhythm
import gear
import bag_pressure
import guildshare

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
DOCKERFILE = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"


def _stack(
    holder,
    item,
    entry,
    count,
    guid,
    item_class=guildshare.TRADE_GOODS,
    subclass=5,
    bonding=0,
    required_skill=0,
    required_rank=0,
    required_level=0,
):
    return guildshare.Holding(
        holder=holder,
        item=item,
        entry=entry,
        count=count,
        guid=guid,
        item_class=item_class,
        subclass=subclass,
        bonding=bonding,
        required_skill=required_skill,
        required_rank=required_rank,
        required_level=required_level,
    )


def _member(name, level=40, skills=None, online=True, family=False, class_id=8):
    return guildshare.Member(
        name=name,
        class_id=class_id,
        level=level,
        skills=skills or {},
        online=online,
        family=family,
    )


# Og's Bolts of Linen Cloth exactly as `character_inventory` held them: eight
# separate `item_instance` rows, 151 units, one of them a partial stack of 11.
def _measured_bolts():
    return [
        _stack("Og", "Bolt of Linen Cloth", 2996, 20, 1500548),
        _stack("Og", "Bolt of Linen Cloth", 2996, 11, 1841340),
        _stack("Og", "Bolt of Linen Cloth", 2996, 20, 1841184),
        _stack("Og", "Bolt of Linen Cloth", 2996, 20, 1841081),
        _stack("Og", "Bolt of Linen Cloth", 2996, 20, 1841000),
        _stack("Og", "Bolt of Linen Cloth", 2996, 20, 1840742),
        _stack("Og", "Bolt of Linen Cloth", 2996, 20, 1840380),
        _stack("Og", "Bolt of Linen Cloth", 2996, 20, 1840884),
    ]


# The guild as it stood: the five family characters online, one recruit online,
# and a representative slice of the thirty-four who were not.
def _measured_guild():
    return [
        _member("Og", level=52, family=True, skills={197: 150, 333: 60}),
        _member("Ugga", level=52, family=True, skills={171: 200}),
        _member("Bork", level=48, family=True, skills={165: 90}),
        _member("Grug", level=51, family=True, skills={164: 100}),
        _member("Grog", level=49, family=True, skills={202: 80}),
        # The one recruit who was actually in the world, on another continent.
        _member(
            "Tinceenk",
            level=40,
            online=True,
            skills={129: 200, 171: 200, 182: 200, 197: 145, 333: 145},
        ),
        # Offline recruits: a tailor, an alchemist and a leatherworker, all of
        # whom could use what is spare and none of whom can receive it.
        _member("Navnah", level=51, online=False, skills={197: 230, 333: 230}),
        _member("Vanuli", level=42, online=False, skills={165: 170, 186: 210}),
        _member("Ahgeathou", level=16, online=False, skills={197: 20, 129: 80}),
    ]


class ReserveIsCraftRhythmsNumberTest(unittest.TestCase):
    """The family's own "stocked" threshold, not a second one invented here."""

    def test_the_reserve_constant_is_craft_rhythms_stocked_threshold(self):
        self.assertEqual(guildshare.RESERVE_CASTS, craft_rhythm.STOCK_CASTS)

    def test_linen_cloth_reserve_is_twelve_casts_of_the_bolt_recipe(self):
        # GATHERED[2963] is 2x Linen Cloth (2589) per Bolt. Twelve casts is 24.
        self.assertEqual(guildshare.reserve_for(2589, (2963,)), 24)

    def test_the_largest_claim_wins_when_two_recipes_want_one_reagent(self):
        # Bolt of Linen eats 2 Linen Cloth a cast, Linen Bandage eats 1. The
        # family must reserve for the hungrier ladder, not the sum of both.
        self.assertEqual(guildshare.reserve_for(2589, (2963, 3275)), 24)
        self.assertEqual(guildshare.reserve_for(2589, (3275,)), 12)

    def test_an_item_no_family_recipe_consumes_reserves_nothing(self):
        # A Bolt of Linen Cloth is the OUTPUT of 2963, never an input, so
        # nothing in the family's rhythm is waiting on one.
        self.assertEqual(guildshare.reserve_for(2996, (2963, 3275)), 0)


class GearRecipientPriorityTest(unittest.TestCase):
    def _gear(self, holder="Grug", guid=1, level=40):
        return gear.Holding(
            holder=holder,
            guid=guid,
            entry=1000 + guid,
            name="Useful BoE",
            quality=2,
            item_level=level,
            required_level=1,
            allowable_class=-1,
            inventory_type=13,
            item_class=gear.ITEM_CLASS_WEAPON,
        )

    def _character(self, name, level=40):
        return gear.CharacterState(
            name=name, class_id=1, level=level, equipped={"main_hand": 1}
        )

    def test_family_upgrade_is_reserved_before_guildmate_fallback(self):
        members = [_member("Guildie", online=True, family=False)]
        grants = bag_pressure.guild_gear_gifts(
            [self._gear(holder="Ugga")],
            [
                self._character("Ugga", level=40),
                self._character("Grug"),
                self._character("Guildie"),
            ],
            ["Grug"],
            members,
        )
        self.assertEqual(grants.grants, ())

    def test_unclaimed_boe_falls_back_to_online_guildmate(self):
        members = [_member("Guildie", online=True, family=False)]
        # Grug is not represented as a character, so the family has no
        # eligible recipient; the observed guild member gets the item.
        grants = bag_pressure.guild_gear_gifts(
            [self._gear()],
            [self._character("Guildie")],
            ["Grug"],
            members,
        )
        self.assertEqual(len(grants.grants), 1)
        self.assertEqual(grants.grants[0].taker, "Guildie")

    def test_offline_guildmate_is_never_a_recipient(self):
        members = [_member("Guildie", online=False, family=False)]
        grants = bag_pressure.guild_gear_gifts(
            [self._gear()],
            [self._character("Guildie")],
            ["Grug"],
            members,
        )
        self.assertEqual(grants.grants, ())


class SurplusNeverBreaksTheReserveTest(unittest.TestCase):
    """The family may not be made generous at the cost of its own crafting."""

    def test_a_family_exactly_on_its_reserve_shares_nothing(self):
        # 24 Linen Cloth against a 24-unit reserve: spare is zero, not "one
        # stack, we are basically fine".
        holdings = [
            _stack("Og", "Linen Cloth", 2589, 12, 1),
            _stack("Grug", "Linen Cloth", 2589, 12, 2),
        ]
        self.assertEqual(guildshare.surplus(holdings, (2963,)), ())

    def test_a_family_one_unit_over_still_shares_nothing_if_the_stack_is_big(self):
        # 25 held, 24 reserved, and the only stacks are 12 and 13. Moving
        # either drops the family below its reserve, so neither moves: there
        # is no partial give, and pretending otherwise is how a family gets
        # starved a unit at a time.
        holdings = [
            _stack("Og", "Linen Cloth", 2589, 12, 1),
            _stack("Og", "Linen Cloth", 2589, 13, 2),
        ]
        self.assertEqual(guildshare.surplus(holdings, (2963,)), ())

    def test_the_stack_that_moves_is_the_smallest_one_that_fits(self):
        # 40 held, 24 reserved: 16 units are spare, and no combination of
        # whole stacks adds up to more than 9 without crossing the reserve.
        # The stack of 9 leaves 31 and goes; taking the 11 as well would leave
        # 20, so it stays even though 11 is under the 16 that is "spare" in
        # the abstract. Spare-in-total is not the same as spare-in-stacks, and
        # it is the stacks that move.
        holdings = [
            _stack("Og", "Linen Cloth", 2589, 20, 1),
            _stack("Og", "Linen Cloth", 2589, 11, 2),
            _stack("Og", "Linen Cloth", 2589, 9, 3),
        ]
        spare = guildshare.surplus(holdings, (2963,))
        self.assertEqual([s.guid for s in spare], [3])
        self.assertEqual(sum(s.count for s in spare), 9)

    def test_the_reserve_is_shared_across_the_family_not_held_per_character(self):
        # Five characters holding 12 Linen each is 60 units against ONE family
        # reserve of 24, so 36 is spare - not "each of them is under 24, so
        # nothing moves", which would make 84 of the 151 Bolts untouchable.
        holdings = [
            _stack(name, "Linen Cloth", 2589, 12, guid)
            for guid, name in enumerate(("Og", "Ugga", "Bork", "Grug", "Grog"), 1)
        ]
        spare = guildshare.surplus(holdings, (2963,))
        self.assertEqual(sum(s.count for s in spare), 36)

    def test_the_measured_151_bolts_are_spare_because_nothing_eats_a_bolt(self):
        spare = guildshare.surplus(_measured_bolts(), (2963, 3275))
        self.assertEqual(len(spare), 8)
        self.assertEqual(sum(s.count for s in spare), 151)

    def test_surplus_is_deterministic_across_runs(self):
        first = guildshare.surplus(_measured_bolts(), (2963,))
        second = guildshare.surplus(list(reversed(_measured_bolts())), (2963,))
        self.assertEqual([s.guid for s in first], [s.guid for s in second])


class OnlyTheRightKindOfItemMovesTest(unittest.TestCase):
    def test_a_bind_on_pickup_item_is_never_shareable(self):
        self.assertFalse(
            guildshare.shareable(_stack("Og", "Soulbound Thing", 9001, 1, 1, bonding=1))
        )

    def test_a_bind_on_equip_item_is_never_shareable_either(self):
        # gear.py owns the question of whether a wearable should leave the
        # family. This pass must never be the reason one did.
        self.assertFalse(
            guildshare.shareable(_stack("Og", "Green Robe", 9002, 1, 1, bonding=2))
        )

    def test_conjured_food_is_not_shareable(self):
        # class 0 subclass 5 - it vanishes in the receiver's bags.
        self.assertFalse(
            guildshare.shareable(
                _stack(
                    "Bork",
                    "Conjured Cinnamon Roll",
                    22895,
                    20,
                    1,
                    item_class=guildshare.CONSUMABLE,
                    subclass=5,
                )
            )
        )

    def test_potions_elixirs_and_bandages_are_shareable(self):
        for name, entry, sub in (
            ("Healing Potion", 929, 1),
            ("Elixir of Lion's Strength", 2454, 2),
            ("Linen Bandage", 1251, 7),
        ):
            self.assertTrue(
                guildshare.shareable(
                    _stack(
                        "Ugga",
                        name,
                        entry,
                        5,
                        1,
                        item_class=guildshare.CONSUMABLE,
                        subclass=sub,
                    )
                ),
                "%s should be shareable" % name,
            )

    def test_an_unknown_trade_good_subclass_is_refused_rather_than_guessed(self):
        # class 7 subclass 11 is "Other" - Empty Vial, Large Fang. No
        # profession in FEEDS claims it, so it is left alone.
        self.assertFalse(
            guildshare.shareable(_stack("Ugga", "Large Fang", 5637, 1, 1, subclass=11))
        )


class WhoCanUseItTest(unittest.TestCase):
    """The recipient must actually be able to use what it is given."""

    def test_a_warlock_with_no_leatherworking_gets_no_leather(self):
        leather = _stack("Bork", "Raptor Hide", 4461, 5, 1, subclass=6)
        warlock = _member("Fugotik", level=29, skills={129: 145, 171: 95})
        self.assertEqual(guildshare.can_use(leather, warlock), "")

    def test_a_leatherworker_does_get_the_leather(self):
        leather = _stack("Bork", "Raptor Hide", 4461, 5, 1, subclass=6)
        worker = _member("Vanuli", level=42, skills={165: 170})
        self.assertEqual(
            guildshare.can_use(leather, worker), "Vanuli has leatherworking"
        )

    def test_cloth_suits_a_tailor_and_equally_suits_a_first_aider(self):
        cloth = _stack("Og", "Linen Cloth", 2589, 20, 1, subclass=5)
        self.assertEqual(
            guildshare.can_use(cloth, _member("A", skills={197: 145})),
            "A has tailoring",
        )
        self.assertEqual(
            guildshare.can_use(cloth, _member("B", skills={129: 200})),
            "B has first aid",
        )
        self.assertEqual(guildshare.can_use(cloth, _member("C", skills={164: 200})), "")

    def test_a_bandage_needs_first_aid_at_rank_not_a_level(self):
        # Measured live: bandages carry RequiredSkill 129 and RequiredLevel 0.
        bandage = _stack(
            "Ugga",
            "Silk Bandage",
            6450,
            10,
            1,
            item_class=guildshare.CONSUMABLE,
            subclass=7,
            required_skill=129,
            required_rank=180,
        )
        self.assertEqual(
            guildshare.can_use(bandage, _member("Ready", level=1, skills={129: 200})),
            "Ready has first aid",
        )
        self.assertEqual(
            guildshare.can_use(bandage, _member("Short", level=60, skills={129: 80})),
            "",
        )

    def test_a_potion_needs_a_level_and_no_profession_at_all(self):
        # Measured live: potions carry RequiredSkill 0 and a real RequiredLevel.
        potion = _stack(
            "Ugga",
            "Greater Healing Potion",
            1710,
            5,
            1,
            item_class=guildshare.CONSUMABLE,
            subclass=1,
            required_level=21,
        )
        self.assertEqual(
            guildshare.can_use(potion, _member("Grown", level=29, skills={})),
            "Grown is level 29",
        )
        self.assertEqual(
            guildshare.can_use(potion, _member("Young", level=18, skills={})), ""
        )

    def test_an_herbs_milling_skill_does_not_lock_out_the_alchemist(self):
        # THE BUG THIS TEST EXISTS FOR, found by running the real query
        # against the live realm. Silverleaf, Briarthorn, Purple Lotus and
        # Swiftthistle all carry RequiredSkill 773 - INSCRIPTION - with ranks
        # of 1, 25 and 175. That is what it takes to MILL them, not to use
        # them. Read as a usage gate it refuses every herb to every alchemist
        # in the guild and offers them to scribes instead, which inverts the
        # answer completely.
        silverleaf = _stack(
            "Ugga",
            "Silverleaf",
            765,
            7,
            1300933,
            subclass=9,
            required_skill=773,
            required_rank=1,
        )
        alchemist = _member("Michane", level=36, skills={171: 85, 182: 85})
        self.assertEqual(
            guildshare.can_use(silverleaf, alchemist), "Michane has alchemy"
        )

    def test_a_scribe_can_still_have_the_herb_to_mill(self):
        # The declared skill is not meaningless, it is just not exclusive: a
        # scribe really can use Silverleaf, by milling it.
        silverleaf = _stack(
            "Ugga",
            "Silverleaf",
            765,
            7,
            1300933,
            subclass=9,
            required_skill=773,
            required_rank=1,
        )
        scribe = _member("Alemid", level=29, skills={773: 145})
        self.assertEqual(
            guildshare.can_use(silverleaf, scribe), "Alemid has inscription"
        )

    def test_a_purple_lotus_still_refuses_somebody_with_neither(self):
        lotus = _stack(
            "Ugga",
            "Purple Lotus",
            8831,
            1,
            1878727,
            subclass=9,
            required_skill=773,
            required_rank=175,
        )
        smith = _member("Nangri", level=41, skills={164: 205, 186: 205})
        self.assertEqual(guildshare.can_use(lotus, smith), "")

    def test_every_profession_in_feeds_has_a_skill_line_id(self):
        # A trade named in FEEDS with no id in SKILL_LINES would silently
        # match nobody for ever, which reads exactly like "nobody has it".
        for trades in guildshare.FEEDS.values():
            for trade in trades:
                self.assertIn(trade, guildshare.SKILL_LINES)


class PlanTest(unittest.TestCase):
    def test_the_measured_guild_sends_og_bolts_to_the_one_online_recruit(self):
        share = guildshare.plan(
            _measured_bolts(), _measured_guild(), craft_spells=(2963, 3275)
        )
        self.assertEqual(share.present, 1)
        self.assertEqual(len(share.gifts), 1)
        gift = share.gifts[0]
        self.assertEqual(gift.holder, "Og")
        self.assertEqual(gift.taker, "Tinceenk")
        self.assertEqual(gift.need, "Tinceenk has tailoring")
        self.assertEqual(gift.command, "guid:%d" % gift.guid)

    def test_no_family_member_is_ever_a_receiver_here(self):
        # materials.py owns hand-offs inside the family. Two modules writing
        # gives for one pair is the second-writer bug this project keeps
        # finding, so the family must never appear on the receiving end.
        share = guildshare.plan(
            _measured_bolts(), _measured_guild(), craft_spells=(2963,)
        )
        family = {"Og", "Ugga", "Bork", "Grug", "Grog"}
        for gift in share.gifts:
            self.assertNotIn(gift.taker, family)

    def test_nobody_online_plans_nothing_and_says_why(self):
        # "Nobody is here" and "what we have suits nobody" are different
        # findings about the guild and only one of them is true when the
        # world is empty. Saying the second one - eight times, once per spare
        # stack - would tell a reader the family's surplus is useless to
        # thirty-five people who were simply not logged in.
        roster = [m for m in _measured_guild() if m.family or not m.online]
        share = guildshare.plan(_measured_bolts(), roster, craft_spells=(2963,))
        self.assertEqual(share.gifts, ())
        self.assertEqual(share.present, 0)
        self.assertEqual(len(share.notes), 1)
        self.assertIn("a give needs both characters online", share.notes[0])
        for note in share.notes:
            self.assertNotIn("nobody online can use it", note)
        self.assertEqual(
            guildshare.headline(share), "no guildmate is in the world right now"
        )

    def test_an_offline_member_who_could_use_it_is_still_not_sent_it(self):
        # Navnah has Tailoring 230 and is the best possible receiver for
        # cloth. He is not in the world, and the live probe proved that a give
        # to an offline receiver is refused outright.
        roster = [m for m in _measured_guild() if m.name != "Tinceenk"]
        share = guildshare.plan(_measured_bolts(), roster, craft_spells=(2963,))
        self.assertNotIn("Navnah", {g.taker for g in share.gifts})

    def test_one_gift_per_member_per_pass(self):
        # Eight spare stacks and one online receiver is one gift, not eight
        # rows into bags nobody manages.
        share = guildshare.plan(
            _measured_bolts(), _measured_guild(), craft_spells=(2963,)
        )
        takers = [g.taker for g in share.gifts]
        self.assertEqual(len(takers), len(set(takers)))

    def test_surplus_nobody_can_use_is_reported_rather_than_dropped(self):
        ore = [_stack("Grug", "Silver Ore", 2775, 20, 1, subclass=7)]
        roster = [
            _member("Og", level=52, family=True),
            _member("Tinceenk", level=40, skills={197: 145}),  # no smith skills
        ]
        share = guildshare.plan(ore, roster, craft_spells=())
        self.assertEqual(share.gifts, ())
        self.assertTrue(any("Silver Ore" in n for n in share.notes))

    def test_a_refused_pair_is_blocked_rather_than_asked_again(self):
        refused = {("Og", "Tinceenk"): "receiver bags are full"}
        share = guildshare.plan(
            _measured_bolts(),
            _measured_guild(),
            craft_spells=(2963,),
            stuck_pairs=refused,
        )
        self.assertEqual(share.gifts, ())
        self.assertEqual(len(share.blocked), 1)
        self.assertEqual(share.blocked[0][2], "receiver bags are full")

    def test_the_lowest_level_qualifying_guildmate_is_preferred(self):
        cloth = [_stack("Og", "Linen Cloth", 2589, 30, 1, subclass=5)]
        roster = [
            _member("Og", level=52, family=True),
            _member("Elder", level=55, skills={197: 300}),
            _member("Young", level=16, skills={197: 20}),
        ]
        share = guildshare.plan(cloth, roster, craft_spells=())
        self.assertEqual([g.taker for g in share.gifts], ["Young"])

    def test_the_plan_is_deterministic(self):
        first = guildshare.plan(
            _measured_bolts(), _measured_guild(), craft_spells=(2963,)
        )
        second = guildshare.plan(
            list(reversed(_measured_bolts())),
            list(reversed(_measured_guild())),
            craft_spells=(2963,),
        )
        self.assertEqual(
            [(g.taker, g.guid) for g in first.gifts],
            [(g.taker, g.guid) for g in second.gifts],
        )


class WhatGetsSaidTest(unittest.TestCase):
    def test_the_spoken_line_names_the_receivers_own_reason(self):
        share = guildshare.plan(
            _measured_bolts(), _measured_guild(), craft_spells=(2963,)
        )
        said = guildshare.lines(share)
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("Og: Og give Tinceenk "))
        self.assertIn("Tinceenk has tailoring", said[0])

    def test_the_reason_names_the_reserve_it_cleared(self):
        # 46 held against a 24 reserve. The stack of 16 clears it and leaves
        # the family 30, comfortably above what it told itself it needed.
        cloth = [
            _stack("Og", "Linen Cloth", 2589, 30, 1, subclass=5),
            _stack("Og", "Linen Cloth", 2589, 16, 2, subclass=5),
        ]
        roster = [
            _member("Og", level=52, family=True),
            _member("Tinceenk", level=40, skills={197: 145}),
        ]
        share = guildshare.plan(cloth, roster, craft_spells=(2963,))
        self.assertEqual(share.gifts[0].count, 16)
        self.assertIn("reserve of 24 Linen Cloth", share.gifts[0].reason)
        self.assertIn("12 casts", share.gifts[0].reason)

    def test_the_three_empty_states_read_differently(self):
        nobody = guildshare.plan([], [_member("A", family=True)], craft_spells=())
        nothing = guildshare.plan([], _measured_guild(), craft_spells=())
        something = guildshare.plan(
            _measured_bolts(), _measured_guild(), craft_spells=(2963,)
        )
        heads = {
            guildshare.headline(nobody),
            guildshare.headline(nothing),
            guildshare.headline(something),
        }
        self.assertEqual(len(heads), 3)


class TheBridgeActuallyCallsThisTest(unittest.TestCase):
    """A planner nothing invokes is a planner that decided nothing.

    This project's own most-repeated failure is a working mechanism with no
    caller: a verb shipped in C++ that Python never invokes, a patch directory
    nothing applies, a correctly formatted command with nowhere to go. A pure
    module and a green unit suite prove neither that the pass runs nor that it
    writes anything, so the wiring is asserted here as source text - the same
    check `test_guildbank.py` makes against `_fetch_guild_money`, and for the
    same reason: this suite has no live database and source text is the
    assertion that can actually run.
    """

    def setUp(self):
        self.source = BRIDGE.read_text(encoding="utf-8")

    def _body(self, name):
        start = self.source.index(name)
        end = self.source.index("\n    async def ", start + 1)
        return self.source[start:end]

    def test_the_module_is_imported(self):
        self.assertIn("\nimport guildshare\n", self.source)

    def test_the_loop_is_registered_in_both_schedulers(self):
        # setup_hook and run_headless hold two literal tuples that must stay
        # in step; a pass added to one and not the other is live in the
        # Discord bridge and dark in the headless one, or the reverse.
        self.assertEqual(self.source.count("self._guild_share_loop,"), 2)

    def test_the_pass_writes_a_command_and_does_not_merely_log(self):
        body = self._body("async def _guild_share_once")
        self.assertIn("_insert_guild_gift", body)
        self.assertIn("guildshare.plan", body)

    def test_the_write_is_kind_give_with_its_own_source(self):
        start = self.source.index("def _insert_guild_gift(")
        body = self.source[start : self.source.index("\ndef ", start + 1)]
        self.assertIn("'give'", body)
        self.assertIn('"guildshare"', body)

    def test_the_retry_window_is_keyed_on_source_not_kind(self):
        # kind='give' is written by three passes now. A window keyed on kind
        # would let any one of them silence another's retry.
        start = self.source.index("def _recent_guild_gift_keys(")
        body = self.source[start : self.source.index("\ndef ", start + 1)]
        self.assertIn("source = 'guildshare'", body)
        self.assertNotIn("kind = 'give'", body)

    def test_the_roster_read_uses_guild_member_and_joins_on_guid(self):
        # `characters` has no guildid column on this world - the mistake
        # _fetch_guild_money made and test_guildbank.py pins.
        self.assertIn("gm.guid = c.guid", self.source)
        self.assertIn("SELECT gm2.guildid FROM guild_member gm2", self.source)

    def test_presence_comes_from_the_snapshot_freshness_rule(self):
        start = self.source.index("_GUILD_ROSTER_SQL = (")
        body = self.source[start : self.source.index("\n_GUILD_SKILLS_SQL", start)]
        self.assertIn("overseer_snapshot", body)
        self.assertIn("INTERVAL 60 SECOND", body)
        # characters.online is minutes stale and is not this service's rule.
        self.assertNotIn("c.online", body)

    def test_the_surplus_read_refuses_bound_items_in_sql_too(self):
        start = self.source.index("_GUILD_SURPLUS_SQL = (")
        body = self.source[start : self.source.index("\ndef ", start)]
        self.assertIn("it.bonding = 0", body)
        self.assertIn("it.class = 7", body)

    def test_the_skills_read_never_touches_character_spell(self):
        # character_spell is NOT authoritative: recipes granted at runtime
        # never persist to it, so it is permanently wrong rather than stale.
        start = self.source.index("_GUILD_SKILLS_SQL = (")
        body = self.source[start : self.source.index("\ndef ", start)]
        self.assertIn("character_skills", body)
        self.assertNotIn("character_spell", body)

    def test_the_module_ships_in_the_image(self):
        # A module missing from the Dockerfile COPY imports fine in the test
        # suite and ImportErrors the container on boot.
        self.assertIn("guildshare.py", DOCKERFILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

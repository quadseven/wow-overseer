"""What stays in the bags: the quest rule and the keeper rule (#233).

THE FIXTURE IS ONE MEASURED CHARACTER. Ugga, the family's level 60 priest,
read off the dev realm on 2026-09-23 at 0 free bag slots: every carried row
(item guids renumbered, bag positions kept), her trade skills, the quests in
her log with the items they name, and the quests she has turned in. At that
reading the bank pass logged "nothing to put down" every cycle and both
guild banks held zero items.

The quest half runs `bag_pressure.QUEST_NEEDED_SQL` itself, against the same
rows loaded into SQLite, so what is pinned is the answer the expression
gives and not its spelling.
"""

import pathlib
import sqlite3
import unittest

import bag_pressure
import bank

# (bag, slot, guid, entry, count, instance flags, name, class, subclass,
#  quality, sell price, bonding, startquest, RequiredSkill, RequiredSkillRank,
#  lockid, BagFamily, ContainerSlots, RequiredLevel)
UGGA = [
    (0, 19, 919, 4496, 1, 0, 'Small Brown Pouch', 1, 0, 1, 125, 0, 0, 0, 0, 0, 0, 6, 0),
    (0, 20, 920, 2657, 1, 0, 'Red Leather Bag', 1, 0, 1, 875, 0, 0, 0, 0, 0, 0, 8, 0),
    (0, 21, 921, 5573, 1, 0, 'Green Leather Bag', 1, 0, 1, 875, 0, 0, 0, 0, 0, 0, 8, 0),
    (0, 22, 922, 1537, 1, 1, "Old Blanchy's Feed Pouch", 1, 0, 1, 62, 1, 0, 0, 0, 0, 0, 8, 0),
    (0, 23, 5, 6948, 1, 1, 'Hearthstone', 15, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0),
    (0, 24, 6, 1210, 6, 0, 'Shadowgem', 3, 7, 2, 250, 0, 0, 0, 0, 0, 512, 0, 0),
    (0, 25, 7, 22895, 20, 0, 'Conjured Cinnamon Roll', 0, 5, 1, 0, 0, 0, 0, 0, 0, 0, 0, 55),
    (0, 26, 8, 46875, 1, 1, 'Riding Training Pamphlet', 12, 0, 1, 0, 1, 14079, 0, 0, 0, 0, 0, 1),
    (0, 27, 9, 46875, 1, 1, 'Riding Training Pamphlet', 12, 0, 1, 0, 1, 14079, 0, 0, 0, 0, 0, 1),
    (0, 28, 10, 46875, 1, 1, 'Riding Training Pamphlet', 12, 0, 1, 0, 1, 14079, 0, 0, 0, 0, 0, 1),
    (0, 29, 11, 3864, 1, 0, 'Citrine', 3, 7, 2, 800, 0, 0, 0, 0, 0, 512, 0, 0),
    (0, 30, 12, 46875, 1, 1, 'Riding Training Pamphlet', 12, 0, 1, 0, 1, 14079, 0, 0, 0, 0, 0, 1),
    (0, 31, 13, 6454, 1, 0, 'Manual: Strong Anti-Venom', 9, 7, 2, 225, 0, 0, 129, 130, 0, 0, 0, 0),
    (0, 32, 14, 11018, 99, 0, "Un'Goro Soil", 12, 0, 1, 146, 0, 0, 0, 0, 0, 32, 0, 0),
    (0, 33, 15, 5637, 2, 0, 'Large Fang', 7, 11, 1, 75, 0, 0, 0, 0, 0, 8, 0, 0),
    (0, 34, 16, 6661, 1, 0, 'Recipe: Savory Deviate Delight', 9, 5, 2, 115, 0, 0, 185, 85, 0, 0, 0, 0),
    (0, 35, 17, 1206, 7, 0, 'Moss Agate', 3, 7, 2, 400, 0, 0, 0, 0, 0, 512, 0, 0),
    (0, 36, 18, 765, 20, 0, 'Silverleaf', 7, 9, 1, 10, 0, 0, 773, 1, 0, 32, 0, 0),
    (0, 37, 19, 11188, 65, 0, 'Yellow Power Crystal', 12, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (0, 38, 20, 3371, 20, 0, 'Empty Vial', 7, 11, 1, 1, 0, 0, 0, 0, 0, 16, 0, 0),
    (919, 0, 21, 8079, 20, 0, 'Conjured Crystal Water', 0, 5, 1, 0, 0, 0, 0, 0, 0, 0, 0, 55),
    (919, 1, 22, 6663, 1, 0, 'Recipe: Elixir of Giant Growth', 9, 6, 2, 150, 0, 0, 171, 90, 0, 0, 0, 0),
    (919, 2, 23, 3371, 5, 0, 'Empty Vial', 7, 11, 1, 1, 0, 0, 0, 0, 0, 16, 0, 0),
    (919, 3, 24, 732, 1, 0, 'Okra', 12, 0, 1, 6, 0, 0, 0, 0, 0, 0, 0, 0),
    (919, 4, 25, 13492, 1, 0, 'Recipe: Purification Potion', 9, 6, 2, 5000, 0, 0, 171, 285, 0, 0, 0, 0),
    (919, 5, 26, 5758, 1, 0, 'Mithril Lockbox', 15, 0, 2, 250, 0, 0, 0, 0, 62, 0, 0, 0),
    (922, 0, 27, 12891, 1, 1, "Jaron's Pick", 12, 0, 1, 0, 4, 0, 0, 0, 0, 0, 0, 0),
    (922, 1, 28, 19279, 1, 0, 'Three of Portals', 12, 0, 3, 12500, 0, 0, 0, 0, 0, 16, 0, 0),
    (922, 2, 29, 818, 4, 0, 'Tigerseye', 3, 7, 2, 100, 0, 0, 0, 0, 0, 512, 0, 0),
    (922, 3, 30, 1705, 9, 0, 'Lesser Moonstone', 3, 7, 2, 600, 0, 0, 0, 0, 0, 512, 0, 0),
    (922, 4, 31, 21949, 1, 0, 'Design: Ruby Serpent', 9, 10, 2, 2500, 0, 0, 755, 260, 0, 0, 0, 0),
    (922, 5, 32, 14181, 1, 1, "Watcher's Handwraps", 4, 1, 2, 775, 2, 0, 0, 0, 0, 0, 0, 23),
    (922, 6, 33, 13492, 1, 0, 'Recipe: Purification Potion', 9, 6, 2, 5000, 0, 0, 171, 285, 0, 0, 0, 0),
    (922, 7, 34, 11734, 1, 0, 'Libram of Tenacity', 9, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 50),
    (921, 0, 35, 11315, 88, 1, 'Bloodpetal Sprout', 12, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0),
    (921, 1, 36, 8623, 1, 1, 'OOX-17/TN Distress Beacon', 12, 0, 2, 0, 1, 351, 0, 0, 0, 0, 0, 43),
    (921, 2, 37, 9251, 1, 0, 'Upper Map Fragment', 12, 0, 1, 62, 0, 0, 0, 0, 0, 0, 0, 0),
    (921, 3, 38, 9297, 1, 0, 'Recipe: Elixir of Dream Vision', 9, 6, 2, 2500, 0, 0, 171, 240, 0, 0, 0, 0),
    (921, 4, 39, 7909, 11, 0, 'Aquamarine', 3, 7, 2, 1000, 0, 0, 0, 0, 0, 512, 0, 0),
    (921, 5, 40, 7910, 4, 0, 'Star Ruby', 3, 7, 2, 5000, 0, 0, 0, 0, 0, 512, 0, 0),
    (921, 6, 41, 4638, 1, 0, 'Reinforced Steel Lockbox', 15, 0, 2, 200, 0, 0, 0, 0, 62, 0, 0, 0),
    (921, 7, 42, 5758, 1, 0, 'Mithril Lockbox', 15, 0, 2, 250, 0, 0, 0, 0, 62, 0, 0, 0),
    (920, 0, 43, 1529, 6, 0, 'Jade', 3, 7, 2, 700, 0, 0, 0, 0, 0, 512, 0, 0),
    (920, 1, 44, 33175, 6, 1, 'Wyrmtail', 12, 0, 1, 0, 4, 0, 0, 0, 0, 0, 0, 0),
    (920, 2, 45, 2553, 1, 0, 'Recipe: Elixir of Minor Agility', 9, 6, 2, 25, 0, 0, 171, 50, 0, 0, 0, 0),
    (920, 3, 46, 20519, 10, 1, 'Southsea Pirate Hat', 12, 0, 1, 0, 4, 0, 0, 0, 0, 0, 0, 0),
    (920, 4, 47, 5117, 2, 0, 'Vibrant Plume', 12, 0, 1, 825, 0, 0, 0, 0, 0, 0, 0, 0),
    (920, 5, 48, 11116, 1, 1, 'A Mangled Journal', 15, 0, 2, 0, 1, 3884, 0, 0, 0, 0, 0, 48),
    (920, 6, 49, 8483, 7, 0, 'Wastewander Water Pouch', 12, 0, 1, 171, 0, 0, 0, 0, 0, 0, 0, 0),
    (920, 7, 50, 1307, 1, 1, 'Gold Pickup Schedule', 12, 0, 1, 0, 1, 123, 0, 0, 0, 0, 0, 7),
]  # fmt: skip

NAME = 6

# Her professions as character_skills held them.
UGGA_SKILLS = {
    "Ugga": {
        "alchemy": 14,
        "herbalism": 135,
        "first aid": 1,
        "cooking": 1,
        "fishing": 1,
    }
}

# Quests in her log and every item column they name:
# (quest, status, StartItem, RequiredItemId1..6, ItemDrop1..4).
UGGA_LOG = [
    (3783, 3, 0, 12366, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (3881, 3, 0, 11113, 11112, 0, 0, 0, 0, 0, 0, 0, 0),
    (4141, 3, 0, 11316, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (4243, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (4289, 3, 0, 11478, 11479, 11480, 0, 0, 0, 0, 0, 0, 0),
    (4502, 3, 0, 11829, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (4504, 3, 0, 11834, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (5245, 3, 12891, 12896, 12897, 12898, 12899, 0, 0, 0, 0, 0, 0),
    (8284, 3, 0, 20378, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (8318, 3, 0, 20404, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (8321, 3, 0, 20466, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (8361, 3, 0, 20513, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (8548, 3, 0, 20802, 20800, 20801, 0, 0, 0, 0, 0, 0, 0),
    (8572, 3, 0, 20802, 20800, 20801, 0, 0, 0, 0, 0, 0, 0),
    # Status 0 is QUEST_STATUS_NONE: not in the log, so it needs nothing.
    # The item column is set here to prove the status filter, not measured.
    (22, 0, 0, 11018, 0, 0, 0, 0, 0, 0, 0, 0, 0),
]  # fmt: skip

UGGA_REWARDED = (
    9, 12, 13, 14, 20, 35, 37, 40, 46, 52, 64, 65, 66, 67, 102, 109, 129, 148,
    151, 153, 165, 173, 221, 244, 399, 436, 473, 536, 690, 1097, 1437, 2158,
    2605, 4501, 5244, 5623, 6603, 6604, 6606, 8320, 8800, 11214,
)  # fmt: skip

CHAR_GUID = 1


def _bank_rows(fixture=UGGA, holder="Ugga"):
    """The fixture as _BANK_ITEMS_SQL names its columns."""
    return [
        dict(
            holder=holder,
            level=60,
            item_guid=guid,
            count=count,
            name=name,
            quality=quality,
            sell_price=price,
            required_level=req_level,
            bonding=bonding,
            item_class=cls,
            container_slots=slots,
            bag=bag,
            slot=slot,
            entry=entry,
            bag_family=family,
            required_skill=skill,
            required_rank=rank,
            lock_id=lock,
            start_quest=startq,
            instance_flags=flags,
        )
        for (
            bag, slot, guid, entry, count, flags, name, cls, _sub, quality,
            price, bonding, startq, skill, rank, lock, family, slots, req_level,
        ) in fixture
    ]  # fmt: skip


def _quest_flags(rewarded=UGGA_REWARDED):
    """name -> the set of QUEST_NEEDED_SQL answers over its carried stacks."""
    db = sqlite3.connect(":memory:")
    db.execute("ATTACH DATABASE ':memory:' AS acore_world")
    db.execute(
        "CREATE TABLE acore_world.item_template (entry, name, class, startquest)"
    )
    db.execute("CREATE TABLE item_instance (guid, itemEntry)")
    db.execute("CREATE TABLE character_inventory (guid, bag, slot, item)")
    db.execute("CREATE TABLE character_queststatus (guid, quest, status)")
    db.execute("CREATE TABLE character_queststatus_rewarded (guid, quest)")
    db.execute(
        "CREATE TABLE acore_world.quest_template (ID, StartItem, "
        "RequiredItemId1, RequiredItemId2, RequiredItemId3, RequiredItemId4, "
        "RequiredItemId5, RequiredItemId6, ItemDrop1, ItemDrop2, ItemDrop3, "
        "ItemDrop4)"
    )
    for row in UGGA:
        bag, slot, guid, entry, name, cls, startq = (
            row[0], row[1], row[2], row[3], row[6], row[7], row[12],
        )  # fmt: skip
        db.execute(
            "INSERT OR IGNORE INTO acore_world.item_template VALUES (?,?,?,?)",
            (entry, name, cls, startq),
        )
        db.execute("INSERT INTO item_instance VALUES (?,?)", (guid, entry))
        db.execute(
            "INSERT INTO character_inventory VALUES (?,?,?,?)",
            (CHAR_GUID, bag, slot, guid),
        )
    for quest, status, *items in UGGA_LOG:
        db.execute(
            "INSERT INTO character_queststatus VALUES (?,?,?)",
            (CHAR_GUID, quest, status),
        )
        db.execute(
            "INSERT INTO acore_world.quest_template VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quest, *items),
        )
    for quest in rewarded:
        db.execute(
            "INSERT INTO character_queststatus_rewarded VALUES (?,?)",
            (CHAR_GUID, quest),
        )
    rows = db.execute(
        "SELECT it.name, " + bag_pressure.QUEST_NEEDED_SQL + " "
        "FROM character_inventory ci "
        "JOIN item_instance ii ON ii.guid = ci.item "
        "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
        "WHERE it.class = 12"
    ).fetchall()
    flags: dict = {}
    for name, flag in rows:
        flags.setdefault(name, set()).add(bool(flag))
    return flags


# Her declared trades, and the guild as it stood: tab 0 bought and empty,
# ranks 0 to 2 carrying the deposit-item right, and her rank 1.
UGGA_PLAN = {"Ugga": ("alchemy", "herbalism")}
OPEN_GUILD = {
    "purchased_tabs": 1,
    "deposit_rank_ids": (0, 1, 2),
    "member_ranks": {"Ugga": 1},
    "tab0_items": 0,
}
VIALS = {3371: ("alchemy",)}

GEMS = {
    "Shadowgem",
    "Citrine",
    "Moss Agate",
    "Tigerseye",
    "Lesser Moonstone",
    "Aquamarine",
    "Star Ruby",
    "Jade",
}
RECIPES = {
    "Manual: Strong Anti-Venom",
    "Recipe: Savory Deviate Delight",
    "Recipe: Elixir of Giant Growth",
    "Recipe: Purification Potion",
    "Recipe: Elixir of Dream Vision",
    "Recipe: Elixir of Minor Agility",
    "Design: Ruby Serpent",
}
LOCKBOXES = {"Mithril Lockbox", "Reinforced Steel Lockbox"}


def _storage(guild=OPEN_GUILD, skills=UGGA_SKILLS, plan=UGGA_PLAN):
    return bank.storage_from(skills, plan, VIALS, guild)


def _ugga(fixture=UGGA):
    return bank.members_from_rows(_bank_rows(fixture), ["Ugga"])


def _stored(member, storage):
    return {holding.item.name: why for holding, why in bank._stored(member, storage)}


def _copy(name, guid, slot, count=None):
    """A carried copy of a fixture row under a new guid and backpack slot."""
    row = next(r for r in UGGA if r[NAME] == name)
    return (0, slot, guid, row[3], row[4] if count is None else count, *row[5:])


class TheQuestRule(unittest.TestCase):
    def test_only_her_log_or_an_unfinished_starter_protects_a_stack(self):
        flags = _quest_flags()
        protected = {name for name, f in flags.items() if f == {True}}
        # Jaron's Pick is the item quest 5245 (in her log) hands out; the
        # other three start quests she has not turned in.
        self.assertEqual(
            {
                "Jaron's Pick",
                "Riding Training Pamphlet",
                "Gold Pickup Schedule",
                "OOX-17/TN Distress Beacon",
            },
            protected,
        )
        for name in (
            "Un'Goro Soil",
            "Bloodpetal Sprout",
            "Yellow Power Crystal",
            "Southsea Pirate Hat",
            "Wastewander Water Pouch",
            "Wyrmtail",
            "Upper Map Fragment",
            "Okra",
            "Vibrant Plume",
        ):
            self.assertEqual({False}, flags[name], name)

    def test_a_starter_whose_quest_is_turned_in_is_released(self):
        """The change itself: `startquest > 0` alone protected these for ever."""
        flags = _quest_flags(UGGA_REWARDED + (14079, 123))
        self.assertEqual({False}, flags["Riding Training Pamphlet"])
        self.assertEqual({False}, flags["Gold Pickup Schedule"])
        self.assertEqual({True}, flags["OOX-17/TN Distress Beacon"])

    def test_a_quest_not_in_the_log_needs_nothing(self):
        self.assertEqual({False}, _quest_flags()["Un'Goro Soil"])


class TheBankPassUsedToStoreNothing(unittest.TestCase):
    def test_without_the_keeper_rule_her_bags_plan_no_move(self):
        """The measured defect: 0 free slots, 28 empty bank slots, no move."""
        members = _ugga()
        self.assertEqual(0, members[0].bag_free)
        self.assertEqual(28, members[0].bank_free)
        plan = bank.plan(members, bank.family_from_skills(UGGA_SKILLS))
        self.assertEqual((), plan.moves)
        self.assertEqual((), plan.guild)


class TheKeeperRule(unittest.TestCase):
    def setUp(self):
        self.member = _ugga()[0]
        self.stored = _stored(self.member, _storage())

    def test_gems_recipes_lockboxes_and_the_libram_are_stored(self):
        self.assertEqual(
            GEMS | RECIPES | LOCKBOXES | {"Libram of Tenacity"}, set(self.stored)
        )
        self.assertIn("does not cut gems", self.stored["Aquamarine"])
        self.assertIn("lockbox", self.stored["Mithril Lockbox"])
        self.assertIn("does not have yet", self.stored["Design: Ruby Serpent"])

    def test_what_she_uses_from_the_bags_stays(self):
        for name in (
            "Hearthstone",
            "Conjured Cinnamon Roll",
            "Conjured Crystal Water",
            "Empty Vial",
            "Silverleaf",
            "Watcher's Handwraps",
            "Three of Portals",
            "Jaron's Pick",
            "A Mangled Journal",
            "Riding Training Pamphlet",
            "Un'Goro Soil",
        ):
            self.assertNotIn(name, self.stored)

    def test_stock_no_trade_in_the_family_claims_is_left_to_the_vendor(self):
        """Large Fang is bagged as leatherworking supplies, and nobody in this
        fixture works leatherworking, so it is ordinary goods."""
        self.assertNotIn("Large Fang", self.stored)

    def test_stock_a_sibling_works_is_stored(self):
        storage = bank.storage_from(
            {**UGGA_SKILLS, "Bork": {"leatherworking": 150}},
            UGGA_PLAN,
            VIALS,
            OPEN_GUILD,
        )
        stored = _stored(self.member, storage)
        self.assertIn("leatherworking", stored["Large Fang"])

    def test_a_recipe_she_can_learn_stays_for_the_recipe_pass(self):
        skills = {"Ugga": {**UGGA_SKILLS["Ugga"], "alchemy": 60}}
        stored = _stored(self.member, _storage(skills=skills))
        self.assertNotIn("Recipe: Elixir of Minor Agility", stored)
        self.assertIn("Recipe: Elixir of Giant Growth", stored)

    def test_a_jeweler_keeps_her_gems(self):
        skills = {"Ugga": {**UGGA_SKILLS["Ugga"], "jewelcrafting": 100}}
        self.assertFalse(GEMS & set(_stored(self.member, _storage(skills=skills))))

    def test_own_stock_past_the_cap_is_stored_whole_stacks_largest_first(self):
        extra = [_copy("Silverleaf", 501, 23, 20), _copy("Silverleaf", 502, 24, 15)]
        member = _ugga(UGGA + extra)[0]
        leaf = [
            (h.guid, why)
            for h, why in bank._stored(member, _storage())
            if h.item.name == "Silverleaf"
        ]
        # 20 + 20 is the cap of 40, so the 15 is the surplus.
        self.assertEqual([502], [guid for guid, _ in leaf])
        self.assertIn("past the 40", leaf[0][1])

    def test_what_nobody_uses_goes_before_own_surplus(self):
        member = _ugga(UGGA + [_copy("Silverleaf", 501, 23, 30)])[0]
        names = [h.item.name for h, _ in bank._stored(member, _storage())]
        self.assertEqual("Silverleaf", names[-1])


class WhereTheStoredStacksGo(unittest.TestCase):
    def _plan(self, guild=OPEN_GUILD, fixture=UGGA):
        return bank.plan(
            _ugga(fixture),
            bank.family_from_skills(UGGA_SKILLS),
            storage=_storage(guild),
        )

    def test_tradable_keepers_go_to_the_guild_bank_one_visit_at_a_time(self):
        plan = self._plan()
        self.assertEqual(bank.VISIT_LIMIT, len(plan.guild))
        self.assertTrue(all(m.to == bank.GUILD for m in plan.guild))
        # Biggest pile first: the 11 Aquamarine lead.
        self.assertEqual("Aquamarine", plan.guild[0].item)
        self.assertEqual(
            "bank deposit-item guid:%d" % plan.guild[0].guid,
            bank.command(plan.guild[0]),
        )

    def test_past_one_vault_visit_the_rest_goes_to_the_banker(self):
        plan = self._plan()
        self.assertEqual(bank.VISIT_LIMIT, len(plan.moves))
        self.assertTrue(all(m.to == bank.PERSONAL for m in plan.moves))
        self.assertTrue(all(m.verb == bank.DEPOSIT for m in plan.moves))
        self.assertFalse({m.guid for m in plan.moves} & {m.guid for m in plan.guild})
        self.assertEqual(
            "deposit guid:%d" % plan.moves[0].guid, bank.command(plan.moves[0])
        )

    def test_no_purchased_tab_sends_everything_to_the_personal_bank(self):
        plan = self._plan(guild={**OPEN_GUILD, "purchased_tabs": 0})
        self.assertEqual((), plan.guild)
        self.assertEqual(bank.VISIT_LIMIT, len(plan.moves))

    def test_a_rank_without_the_right_sends_everything_to_the_personal_bank(self):
        plan = self._plan(guild={**OPEN_GUILD, "deposit_rank_ids": (0,)})
        self.assertEqual((), plan.guild)
        self.assertEqual(bank.VISIT_LIMIT, len(plan.moves))

    def test_a_full_tab_sends_everything_to_the_personal_bank(self):
        plan = self._plan(guild={**OPEN_GUILD, "tab0_items": bank.GUILD_TAB_SLOTS})
        self.assertEqual((), plan.guild)
        self.assertTrue(any("tab is full" in note for note in plan.notes))

    def test_the_tab_is_never_offered_more_than_its_free_slots(self):
        plan = self._plan(guild={**OPEN_GUILD, "tab0_items": bank.GUILD_TAB_SLOTS - 3})
        self.assertEqual(3, len(plan.guild))

    def test_a_bound_keeper_goes_to_her_own_bank(self):
        bound = [
            row[:5] + (1,) + row[6:] if row[NAME] == "Star Ruby" else row
            for row in UGGA
        ]
        plan = self._plan(fixture=bound)
        self.assertNotIn("Star Ruby", [m.item for m in plan.guild])
        self.assertIn("Star Ruby", [m.item for m in plan.moves])


class NothingStoredComesStraightBack(unittest.TestCase):
    def _banked(self, name, slot=40):
        row = next(r for r in UGGA if r[NAME] == name)
        return (0, slot, 700 + slot, *row[3:])

    def test_a_banked_gem_stays_banked(self):
        member = _ugga(UGGA + [self._banked("Star Ruby")])[0]
        plan = bank.plan(
            [member], bank.family_from_skills(UGGA_SKILLS), storage=_storage()
        )
        self.assertNotIn(bank.WITHDRAW, [m.verb for m in plan.moves])

    def test_a_banked_recipe_comes_back_once_she_can_learn_it(self):
        # Only the banked recipe, so a full visit of deposits and 0 free
        # slots do not stand in front of the withdrawal being tested.
        member = _ugga([self._banked("Recipe: Elixir of Minor Agility")])[0]
        family = bank.family_from_skills(UGGA_SKILLS)
        before = bank.plan([member], family, storage=_storage())
        self.assertNotIn(bank.WITHDRAW, [m.verb for m in before.moves])
        skills = {"Ugga": {**UGGA_SKILLS["Ugga"], "alchemy": 50}}
        after = bank.plan([member], family, storage=_storage(skills=skills))
        withdrawn = [m for m in after.moves if m.verb == bank.WITHDRAW]
        self.assertEqual(
            ["Recipe: Elixir of Minor Agility"], [m.item for m in withdrawn]
        )
        self.assertIn("can learn it now", withdrawn[0].why)


class TheGuildFactsComeFromTheWorld(unittest.TestCase):
    def test_depositors_are_members_whose_rank_carries_the_right(self):
        storage = bank.storage_from(
            {}, None, None, {**OPEN_GUILD, "member_ranks": {"Ugga": 1, "Other": 3}}
        )
        self.assertEqual(frozenset({"Ugga"}), storage.guild_depositors)
        self.assertEqual(bank.GUILD_TAB_SLOTS, storage.guild_free)

    def test_no_guild_read_opens_nothing(self):
        storage = bank.storage_from(UGGA_SKILLS, UGGA_PLAN, VIALS, None)
        self.assertEqual(frozenset(), storage.guild_depositors)
        self.assertEqual(0, storage.guild_free)


class TheBridgeReadsWhatTheRuleNeeds(unittest.TestCase):
    """bridge.py imports discord, so its half is read as text."""

    SRC = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
        encoding="utf-8"
    )

    def test_the_bank_rows_carry_every_fact_the_keeper_rule_reads(self):
        sql = self.SRC[
            self.SRC.index("_BANK_ITEMS_SQL = (") : self.SRC.index("def _plan_bank(")
        ]
        for alias in (
            "AS entry",
            "AS bag_family",
            "AS required_skill",
            "AS required_rank",
            "AS lock_id",
            "AS start_quest",
            "AS instance_flags",
        ):
            self.assertIn(alias, sql)

    def test_the_guild_read_names_ranks_and_tab_room(self):
        body = self.SRC[
            self.SRC.index("def _fetch_guild_bank_setup(") : self.SRC.index(
                "def _recent_guild_setup_keys("
            )
        ]
        self.assertIn('"member_ranks": member_ranks', body)
        self.assertIn('"tab0_items": tab0_items', body)
        self.assertIn("FROM guild_bank_item", body)

    def test_one_plan_feeds_both_banks(self):
        helper = self.SRC[
            self.SRC.index("def _plan_bank(") : self.SRC.index("def _fetch_bank_items(")
        ]
        self.assertIn("bank.storage_from(", helper)
        self.assertIn("_fetch_guild_bank_setup(names)", helper)
        self.assertIn("storage=storage", helper)


if __name__ == "__main__":
    unittest.main()

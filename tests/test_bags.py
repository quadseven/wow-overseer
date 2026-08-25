"""The family's bags, and the two separate bugs that kept them full and frozen.

WHY THIS FILE EXISTS. Measured live on 2026-08-24, every one of the five named
characters had ZERO free bag slots (Grug 40/40, Ugga 34/34, Bork/Grog/Og 22/22),
and only FOUR grey items existed across all five - so mod-junk-to-gold, which
sells greys and only greys, had been running correctly and freeing nothing for
the life of the realm. A full bag cannot accept a looted quest item and cannot
accept a quest reward, so the whole questing epic was unobservable underneath
this.

Two changes are asserted here, and they are deliberately NOT the obvious one:

  1. The roster is GIVEN BAGS. `PlayerbotFactory::InitBags` equips a bag into
     every empty bag slot, and every random bot on this realm gets it from
     `Randomize()` (PlayerbotFactory.cpp:759). These five never can:
     `Randomize` is RandomPlayerbotMgr's path and these accounts fail
     `IsRandomBot()` three separate ways. Same wall as #2756 (talents),
     #2757 (professions) and #2782.

  2. Looting a gathering node is REFUSED when there is no free slot, so a
     character with full bags stops re-casting on a herb three yards away
     forever (#2800: Grug held one position to 0.1 yard for 8h31m).

WHAT IS NOT HERE, ON PURPOSE. Nothing sells and nothing destroys. Their bags
hold live quest items right now - Westfall Deed, Large Candle (quest 60,
COMPLETE and pending turn-in), Gold Dust, Torn Murloc Fin, Red Linen Bandana,
Kobold Excavation Pick, Bundle of Wood - and every one of those is a quality-1
white, indistinguishable by quality from the junk anyone would want to sell.
`sell vendor` ("everything worth vendoring, not only greys") would have taken
them. So the tests below assert the ABSENCE of any disposal path, which is a
far stronger guarantee than an exclusion list: there is nothing to exclude
from, because nothing in this change can remove an item from a bag.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
PATCHES = ROOT / "docker/azerothcore-playerbots/patches/mod-playerbots"
PINS = ROOT / "docker/azerothcore-playerbots/UPSTREAM-PINS.env"
LOOT_PATCH = PATCHES / "0004-loot-needs-a-free-bag-slot.patch"

# Everything that can make an item leave a bag. None of these may appear
# anywhere in this fix. `InitBags(true)` is on the list because its destroyOld
# branch calls `bot->DestroyItem(INVENTORY_SLOT_BAG_0, slot, true)` on an
# OCCUPIED bag slot (PlayerbotFactory.cpp:2634-2635) - which destroys the bag
# AND everything inside it. That is how a Large Candle dies. (It is also
# BROKEN upstream: after destroying it hits `if (old_bag) continue;` at :2637
# and never equips the replacement, so the slot is left empty. A second reason
# never to reach for it.)
DISPOSAL = [
    "DestroyItemCount",
    "ClearInventory",
    "ClearAllItems",
    "SellItem",
    "sell vendor",
    "sell gray",
    "InitBags(true)",
]

# `DestroyItem` is handled separately rather than banned outright. There is
# exactly ONE in this change - replacing a starter bag that `Bag::IsEmpty()`
# has proven holds nothing - and the tests below pin down that it is one, that
# the emptiness check comes first, and that the replacement is proven
# equippable before anything is destroyed. Banning it outright would have been
# easier and would have left Grug, who has FOUR occupied bag slots and zero
# empty ones, gaining nothing at all.
DESTROY = "DestroyItem("


def _strip_comments(src: str) -> str:
    """Code only.

    These files carry long WHY blocks that quote the very calls the tests
    below forbid - the GiveBags header explains what `DestroyItem` on an
    occupied bag slot would do. A text match that cannot tell a warning about
    a call from the call itself is not a structural test.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", src)


def _body(func_signature: str) -> str:
    """One function body out of the C++ module, by brace matching."""
    src = MODULE.read_text(encoding="utf-8")
    start = src.index(func_signature)
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return _strip_comments(src[start:i + 1])
    raise AssertionError(f"{func_signature} has no closing brace")


GIVE_BAGS = "void GiveBags(Player* bot, std::string const& name)"
REPLACE = "uint32 ReplaceEmptyStarterBags(Player* bot, uint32& blocked)"


class TheRosterIsGivenBags(unittest.TestCase):
    def test_the_roster_sweep_gives_bags(self):
        """Without this call the five keep the starter bags forever.

        22 slots is 16 backpack plus one small bag; three of their four bag
        slots are simply empty, and nothing in the module or in upstream was
        ever going to fill them for a non-random bot.
        """
        self.assertIn("GiveBags(", _body("void TrainRoster()"))
        self.assertIn("InitBags(", _body(GIVE_BAGS))

    def test_bags_are_never_given_destructively(self):
        """`InitBags(true)` destroys the bag in an occupied slot, contents included.

        The default argument is `destroyOld = true` (PlayerbotFactory.h:87), so
        `InitBags()` written bare is the DANGEROUS call. It must always be
        spelled out as false.
        """
        src = _strip_comments(MODULE.read_text(encoding="utf-8"))
        calls = re.findall(r"InitBags\s*\(([^)]*)\)", src)
        self.assertTrue(calls, "no InitBags call found at all")
        for arg in calls:
            self.assertEqual(
                "false", arg.strip(),
                "InitBags must be called with an explicit false - the default "
                "is destroyOld=true, which destroys an occupied bag and every "
                "quest item inside it",
            )

    def test_the_bag_pass_is_not_behind_the_level_gate(self):
        """A character stuck at its level would never get bags.

        TrainRoster's expensive trainer walk is gated on
        `level == trainedLevel`, and every one of these five has been sitting
        at the same level for hours with full bags. Behind that gate the fix
        would compile, read correctly, and never once run - the `sell junk`
        shape this repo keeps finding.
        """
        body = _body("void TrainRoster()")
        self.assertLess(
            body.index("GiveBags("), body.index("level == trainedLevel"),
            "the bag pass sits behind the level gate and will never run for a "
            "character that is not levelling",
        )

    def test_the_bag_pass_stops_once_the_slots_are_full(self):
        """Otherwise this is a factory construction on every single poll."""
        body = _body(GIVE_BAGS)
        self.assertIn("CountEmptyBagSlots(", body)
        self.assertLess(
            body.index("CountEmptyBagSlots("), body.index("PlayerbotFactory"),
            "the factory is constructed before anyone asks whether there is "
            "an empty slot to fill",
        )

    def test_nothing_in_the_roster_sweep_can_remove_an_item(self):
        for where in ("void TrainRoster()", GIVE_BAGS, REPLACE):
            body = _body(where)
            for call in DISPOSAL:
                self.assertNotIn(
                    call, body,
                    f"{where} contains {call}: this fix must not be able to "
                    "remove an item from a bag, because the bags hold live "
                    "quest items that are quality-1 whites and look exactly "
                    "like junk",
                )


class AStarterBagIsReplacedONLYWhileItIsEmpty(unittest.TestCase):
    """Grug is why this exists, and he is why banning DestroyItem was wrong.

    Measured live from character_inventory, bag slots 19-22:

        who    bags equipped   empty bag slots   total
        Bork         1               3             22
        Grog         1               3             22
        Og           1               3             22
        Ugga         3               1             34
        Grug         4               0             40

    Grug has FOUR Small Pouches and no empty bag slot, so a fix that only
    fills empty slots gives him nothing - and he is the party leader, the only
    character carrying `new rpg`, and the one who sat 2.98 yards from a
    Silverleaf node for 8h31m. Replacing a bag means destroying the one that is
    there, so the only safe version of that is one that refuses any bag holding
    anything at all.

    `Player::DestroyItem` recursively destroys a bag's CONTENTS
    (`if (pItem->IsNotEmptyBag())`, PlayerStorage.cpp:3132-3134). The
    `Bag::IsEmpty()` guard (Bag.h:46, Bag.cpp:179-186) is the only thing
    between this code and a Westfall Deed.
    """

    def test_there_is_exactly_one_destroy_in_the_whole_module(self):
        src = _strip_comments(MODULE.read_text(encoding="utf-8"))
        self.assertEqual(
            1, src.count(DESTROY),
            "expected exactly one DestroyItem( in mod_overseer.cpp - the "
            "guarded starter-bag replacement and nothing else",
        )

    def test_the_one_destroy_lives_in_the_bag_replacement(self):
        self.assertIn(DESTROY, _body(REPLACE))

    def test_a_bag_that_holds_anything_is_never_destroyed(self):
        body = _body(REPLACE)
        self.assertIn("IsEmpty()", body, "no emptiness check at all")
        self.assertLess(
            body.index("IsEmpty()"), body.index(DESTROY),
            "the emptiness check must come BEFORE the destroy, or it is not a "
            "guard, it is a comment",
        )

    def test_the_replacement_is_proven_equippable_before_anything_is_destroyed(self):
        """Otherwise a failed equip costs the character the bag it had.

        Player::CanEquipNewItem (Player.h:1317, PlayerStorage.cpp:1885-1898)
        makes and deletes its own probe item, so this costs nothing and needs
        no access to PlayerbotFactory::CanEquipUnseenItem, which is private
        (PlayerbotFactory.h:159).
        """
        body = _body(REPLACE)
        self.assertIn("CanEquipNewItem", body)
        self.assertLess(body.index("CanEquipNewItem"), body.index(DESTROY))

    def test_a_bag_that_is_already_the_right_one_is_left_alone(self):
        """Otherwise every poll destroys and re-equips the same four bags."""
        self.assertIn("OVERSEER_BAG_ITEM", _body(REPLACE))


class ACharacterThatGainsNothingSaysSo(unittest.TestCase):
    def test_gaining_no_slots_is_logged_and_names_the_character(self):
        """A silent skip on the one character with the documented freeze is how
        this gets marked fixed and stays broken."""
        body = _body(GIVE_BAGS)
        self.assertIn("LOG_WARN", body,
                      "a character that gains no bag slots must say so at a "
                      "level somebody will see")

    def test_a_bag_that_could_not_be_equipped_is_an_error_not_a_silence(self):
        """The `sell junk` shape: reports success, does nothing. If InitBags
        leaves a slot empty, the item could not be equipped and nobody would
        ever find out."""
        self.assertIn("LOG_ERROR", _body(GIVE_BAGS))


def _patch_lines(path: pathlib.Path):
    """(added, removed) content lines of a patch, excluding the file headers."""
    text = path.read_text(encoding="utf-8")
    added, removed = [], []
    for line in text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])
    return added, removed


class LootStopsWhenThereIsNoRoom(unittest.TestCase):
    """#2800's freeze, fixed without touching a single relevance number.

    `LootObject::IsLootPossible` (LootObjectStack.cpp:280-348 at the pinned
    SHA) has no free-slot check at all. With zero free slots the loot can never
    complete, `add all loot` re-adds the node every tick, and `open loot` at
    relevance 8.0 preempts `new rpg do quest` at 3.0 forever. Relevance changes
    are known-unsafe here (#2800 declined exactly that), so the fix is on the
    other half of the product: make the 8.0 action terminate.
    """

    def test_the_patch_exists(self):
        self.assertTrue(LOOT_PATCH.is_file(), f"missing {LOOT_PATCH}")

    def test_it_patches_the_function_that_is_missing_the_check(self):
        text = LOOT_PATCH.read_text(encoding="utf-8")
        self.assertIn("src/Mgr/Item/LootObjectStack.cpp", text)

    def test_the_guard_asks_the_core_for_the_free_slot_count(self):
        """Player::GetFreeInventorySpace counts backpack + every equipped bag
        (PlayerStorage.cpp:470-490). Counting it here by hand would be a second,
        worse copy of it."""
        added, _ = _patch_lines(LOOT_PATCH)
        self.assertTrue(
            any("GetFreeInventorySpace" in line for line in added),
            "the patch adds no free-slot check",
        )

    def test_the_patch_deletes_nothing(self):
        """Purely additive. A patch that removes an upstream return changes
        behaviour the reviewer did not ask about, and this one compiles only in
        CI."""
        _, removed = _patch_lines(LOOT_PATCH)
        self.assertEqual([], removed, f"the patch removes lines: {removed}")

    def test_the_guard_is_scoped_to_gathering_nodes_only(self):
        """A CORPSE must still be lootable with full bags, because a corpse can
        hold MONEY, and money needs no slot. A gathering node yields items only,
        so refusing one with no free slot is exact rather than a heuristic.

        The scoping is positional: the guard has to sit AFTER
        `if (skillId == SKILL_NONE) return true;`, which is the corpse/plain
        chest path out of the function.
        """
        text = LOOT_PATCH.read_text(encoding="utf-8")
        diff = text[text.index("diff --git"):]
        self.assertIn("skillId == SKILL_NONE", diff,
                      "the hunk does not show the SKILL_NONE early return, so "
                      "nothing proves the guard is below it")
        self.assertLess(
            diff.index("skillId == SKILL_NONE"), diff.index("GetFreeInventorySpace"),
            "the free-slot guard is placed ABOVE the SKILL_NONE return, which "
            "would stop a full-bagged bot looting money off a corpse",
        )

    def test_the_patch_can_remove_nothing_from_a_bag(self):
        added, _ = _patch_lines(LOOT_PATCH)
        for call in DISPOSAL:
            self.assertFalse(
                any(call in line for line in added),
                f"the loot patch adds {call}",
            )


class ThePatchHeaderSaysHowToRetireIt(unittest.TestCase):
    """patches/README.md: these files are meant to be DELETED, and one nobody
    knows how to retire outlives its reason."""

    REQUIRED = ["WHY THIS PATCH EXISTS", "WHAT WOULD LET THIS PATCH BE DELETED",
                "APPLIES TO"]

    def test_it_carries_the_three_headings(self):
        text = LOOT_PATCH.read_text(encoding="utf-8")
        for heading in self.REQUIRED:
            self.assertIn(heading, text)

    def test_it_names_the_sha_it_was_cut_against(self):
        """A patch header quoting a SHA that is no longer pinned is a patch
        nobody re-verified after a bump."""
        pinned = set(re.findall(r"^AC_\w+_SHA=([0-9a-f]{40})$",
                                PINS.read_text(encoding="utf-8"), re.MULTILINE))
        self.assertTrue(pinned, "no SHAs parsed out of UPSTREAM-PINS.env")
        quoted = set(re.findall(r"[0-9a-f]{40}",
                                LOOT_PATCH.read_text(encoding="utf-8")))
        self.assertTrue(quoted, "the patch header quotes no upstream SHA")
        self.assertTrue(
            quoted <= pinned,
            f"patch quotes SHAs that are not pinned: {sorted(quoted - pinned)}",
        )


if __name__ == "__main__":
    unittest.main()

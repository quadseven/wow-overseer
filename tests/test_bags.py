"""The family's bags: the freeze is a bug, the fullness is a design problem.

WHY THIS FILE EXISTS. Measured live on 2026-08-24, every one of the five named
characters had ZERO free bag slots (Grug 40/40, Ugga 34/34, Bork/Grog/Og
22/22), and only FOUR grey items existed across all five - so mod-junk-to-gold,
which sells greys and only greys, had been running correctly and freeing
nothing for the life of the realm. Two different things came out of that
measurement and they are NOT the same kind of thing:

  1. A BUG. `LootObject::IsLootPossible` never asks whether the bot has room
     for what it is about to gather, so with no free slot the loot can never
     complete, `add all loot` re-adds the node every tick, and `open loot` at
     relevance 8.0 preempts `new rpg do quest` at 3.0 forever (#2800: Grug held
     one position to within 0.1 yard for 8h31m, 2.98 yards from a Silverleaf).
     Skipping a node you cannot carry is correct behaviour no matter where bags
     come from. That is what this file pins down.

  2. A DESIGN PROBLEM, deliberately left open. Having too few bags is not a bug
     to be patched out by materialising epic 24-slot Portable Holes into empty
     bag slots. Bags come from the world: looted, bought, or crafted by
     whichever of the family takes tailoring and mailed or traded to the rest.
     That route needs professions assigned first (#2757). An earlier revision
     of this file asserted the opposite - that the roster sweep hands out bags -
     and those assertions are gone with the code they pinned.

So the class below named `TheModuleDoesNotHandOutBags` is not a leftover: it is
the design decision, written down where the next person to reach for
`PlayerbotFactory::InitBags` will trip over it.

WHAT IS NOT HERE, ON PURPOSE. Nothing sells and nothing destroys. Their bags
hold live quest items right now - Westfall Deed, Large Candle (quest 60,
COMPLETE and pending turn-in), Gold Dust, Torn Murloc Fin, Red Linen Bandana,
Kobold Excavation Pick, Bundle of Wood - and every one of those is a quality-1
white, indistinguishable by quality from the junk anyone would want to sell.
`sell vendor` ("everything worth vendoring, not only greys") would have taken
them. So the tests below assert the ABSENCE of any disposal path, which is a
far stronger guarantee than an exclusion list: there is nothing to exclude
from, because nothing here can remove an item from a bag.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
PATCHES = ROOT / "docker/azerothcore-playerbots/patches/mod-playerbots"
PINS = ROOT / "docker/azerothcore-playerbots/UPSTREAM-PINS.env"
LOOT_PATCH = PATCHES / "0004-loot-needs-a-free-bag-slot.patch"

# Everything that can make an item leave a bag. None of these may appear in
# this fix. The loot guard is a REFUSAL to pick something up; it has no
# business being anywhere near a call that puts something down.
DISPOSAL = [
    "DestroyItem",
    "DestroyItemCount",
    "ClearInventory",
    "ClearAllItems",
    "SellItem",
    "sell vendor",
    "sell gray",
]

# Every way the module could conjure a bag out of nothing. `InitBags` is
# upstream's own bag handout (PlayerbotFactory.cpp:2625, hardcoded item 51809
# "Portable Hole", 24 slots, quality 4) and reaching for it is the exact move
# this file exists to refuse. Bags are found, bought or crafted in the world.
BAG_HANDOUT = [
    "InitBags",
    "GiveBags",
    "ReplaceEmptyStarterBags",
    "OVERSEER_BAG_ITEM",
    "51809",
]


def _strip_comments(src: str) -> str:
    """Code only.

    These files carry long WHY blocks that quote the very calls the tests
    below forbid - the loot patch header explains what a full-bagged bot does
    to a herb node, and the docstring above names `InitBags` in order to
    reject it. A text match that cannot tell a warning about a call from the
    call itself is not a structural test.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", src)


class TheModuleDoesNotHandOutBags(unittest.TestCase):
    """Bags must come from the world, not from the overseer module.

    The rejected design was: sweep the roster, replace empty starter bags, and
    call `PlayerbotFactory::InitBags(false)` to drop an epic Portable Hole into
    every empty bag slot. It was merged in #2823 and NEVER DEPLOYED, so no live
    character ever received one. It is removed because "magically upgrade
    themselves" is the same pattern already rejected on #2782 (trainer spells
    learned without visiting a trainer). Whoever in the group takes tailoring
    crafts bags for the rest, and is given the cloth to do it - which needs
    professions handed out first (#2757).
    """

    def test_the_module_never_conjures_a_bag(self):
        src = _strip_comments(MODULE.read_text(encoding="utf-8"))
        for call in BAG_HANDOUT:
            self.assertNotIn(
                call, src,
                f"mod_overseer.cpp contains {call}: the module must not create "
                "bags out of nothing. Bags are looted, bought, or crafted by a "
                "teammate with tailoring (#2757) and traded or mailed over.",
            )

    def test_the_module_can_remove_nothing_from_a_bag(self):
        """The bags hold live quest items that are quality-1 whites and look
        exactly like junk, so there is no exclusion list that could be got
        right. The guarantee is that no disposal call exists at all."""
        src = _strip_comments(MODULE.read_text(encoding="utf-8"))
        for call in DISPOSAL:
            self.assertNotIn(
                call, src,
                f"mod_overseer.cpp contains {call}: nothing in this module may "
                "remove an item from a bag",
            )


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

    This is a bug fix and not a handout. It does not give a bot one extra slot;
    it stops a bot spending eight and a half hours re-casting on a herb it has
    nowhere to put. That stays true however the family end up acquiring bags.
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

    def test_the_guard_refuses_the_node_and_does_nothing_else(self):
        """The whole mechanism is one early `return false` at exactly zero.
        Anything more than that has stopped being "skip what you cannot
        carry" and started being a policy about bags."""
        added, _ = _patch_lines(LOOT_PATCH)
        self.assertTrue(
            any("GetFreeInventorySpace" in line and "== 0" in line
                for line in added),
            "the guard does not test for exactly zero free slots",
        )
        self.assertTrue(
            any(line.strip() == "return false;" for line in added),
            "the guard does not refuse the node",
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

    def test_the_patch_hands_out_no_bags_either(self):
        """The loot guard is the half of #2823 that was kept. It must not pick
        up any of the half that was rejected."""
        added, _ = _patch_lines(LOOT_PATCH)
        for call in BAG_HANDOUT:
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

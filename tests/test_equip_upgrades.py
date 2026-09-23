"""A carried piece its holder would wear is put on (#146).

Measured on wow-dev 2026-09-22: `bag_pressure.family_fits` marked 15 of 24
carried gear pieces FIT_HOLDER, which keeps them, and nothing ever equipped
one. Grog carried Cabalist Chestpiece (item level 50) over a worn Sparkleshell
Breastplate (41); Bork Dervish Boots (28) over Bristlebark Boots (23); Ugga
Watcher's Handwraps (28) over Gold-flecked Gloves (22).

What is pinned here: the planner equips exactly what `gear.claimant` gives
the holder, one piece per slot, never an unjudgeable piece, never an
ambiguous weapon-hand swap, and the bridge writes it as a kind='bot' `e` row
with a retry window and a give-up.
"""

import pathlib
import re
import unittest

import bag_pressure
import gear

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

WARRIOR, PALADIN, ROGUE, PRIEST = 1, 2, 4, 5
ANY_CLASS = -1
THE_FIVE = ["Bork", "Grog", "Grug", "Og", "Ugga"]


def worn(name, class_id, level, **slots):
    """Equipped rows for one character, as _FAMILY_EQUIPPED_SQL returns them."""
    if not slots:
        return [
            dict(
                name=name,
                class_id=class_id,
                level=level,
                inventory_type=None,
                item_level=None,
            )
        ]
    return [
        dict(
            name=name,
            class_id=class_id,
            level=level,
            inventory_type=int(inv.lstrip("i")),
            item_level=int(ilvl),
        )
        for inv, ilvl in slots.items()
    ]


def carried(**kw):
    """One carried gear row, as _SURPLUS_GEAR_SQL returns it. Defaults are
    Grog's Cabalist Chestpiece: mail chest, item level 50, soulbound."""
    base = dict(
        holder="Grog",
        level=60,
        item_guid=8001,
        entry=7527,
        count=1,
        instance_flags=1,
        name="Cabalist Chestpiece",
        quality=2,
        sell_price=3000,
        required_level=45,
        bonding=2,
        item_class=4,
        item_subclass=3,
        item_level=50,
        allowable_class=ANY_CLASS,
        inventory_type=5,
    )
    base.update(kw)
    return base


def equips(gear_rows, equipped_rows, keep_names=()):
    return bag_pressure.holder_equips(
        gear_rows, equipped_rows, THE_FIVE, keep_names=keep_names
    )


GROG = worn("Grog", PALADIN, 60, i5=41)


class TheHolderPutsItOn(unittest.TestCase):
    def test_a_clear_upgrade_is_equipped(self):
        got = equips([carried()], GROG)
        self.assertEqual(
            [(e.holder, e.name) for e in got], [("Grog", "Cabalist Chestpiece")]
        )
        self.assertEqual((got[0].item_level, got[0].worn_level), (50, 41))

    def test_the_command_is_the_playerbots_equip_verb(self):
        """`e` is EquipAction, which reads `Hitem:<id>:` out of the text."""
        got = equips([carried()], GROG)
        self.assertEqual(got[0].command, "e Hitem:7527:0")
        self.assertEqual(bag_pressure.equip_entry(got[0].command), 7527)

    def test_an_empty_slot_is_filled(self):
        got = equips([carried()], worn("Grog", PALADIN, 60))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].worn_level, 0)

    def test_it_agrees_with_the_fit_gate(self):
        """One opinion: every piece equipped is one family_fits keeps as
        FIT_HOLDER, and nothing FIT_HOLDER is left in the bag by this."""
        import disposition

        rows = [
            carried(),
            carried(item_guid=8002, entry=1, name="Worse Chest", item_level=30),
            carried(
                item_guid=8003, entry=2, name="Boots", inventory_type=8, item_level=28
            ),
        ]
        fits = bag_pressure.family_fits(rows, GROG, THE_FIVE)
        got = {e.guid for e in equips(rows, GROG)}
        holder = {g for g, fit in fits.items() if fit == disposition.FIT_HOLDER}
        self.assertTrue(got <= holder)
        self.assertEqual(got, {8001, 8003})


class OnlyWhatTheNumbersSettle(unittest.TestCase):
    def test_not_an_upgrade_is_left_alone(self):
        self.assertEqual(equips([carried(item_level=41)], GROG), ())

    def test_a_ring_is_unjudgeable_and_stays(self):
        """Finger, neck and trinket slots have no bucket in gear.py; the fit
        gate calls them UNJUDGEABLE and so must this."""
        ring = carried(
            name="Band", item_class=4, item_subclass=0, inventory_type=11, item_level=60
        )
        self.assertEqual(equips([ring], GROG), ())

    def test_a_piece_the_class_cannot_wear_stays(self):
        plate = carried(item_subclass=4)  # a priest wears cloth only
        self.assertEqual(equips([plate], worn("Grog", PRIEST, 60, i5=41)), ())

    def test_an_unknown_holder_stays(self):
        self.assertEqual(equips([carried(holder="Stranger")], GROG), ())

    def test_the_owners_mark_is_honoured(self):
        self.assertEqual(
            equips([carried()], GROG, keep_names=["cabalist chestpiece"]), ()
        )

    def test_one_piece_per_slot_and_the_best_one(self):
        rows = [carried(item_guid=8002, entry=2, name="Good", item_level=45), carried()]
        got = equips(rows, GROG)
        self.assertEqual([e.guid for e in got], [8001])


def weapon(**kw):
    base = dict(
        item_class=2,
        item_subclass=7,
        allowable_class=ANY_CLASS,
        instance_flags=0,
        required_level=1,
    )
    base.update(kw)
    return carried(**base)


class TheWeaponHandsAreNotGuessed(unittest.TestCase):
    def test_a_one_hander_does_not_knock_off_a_worn_two_hander(self):
        who = worn("Grog", WARRIOR, 60, i17=40)
        self.assertEqual(equips([weapon(inventory_type=13, item_level=45)], who), ())

    def test_an_off_hand_does_not_knock_off_a_worn_two_hander(self):
        who = worn("Grog", WARRIOR, 60, i17=40)
        shield = carried(item_subclass=6, inventory_type=14, item_level=45)
        self.assertEqual(equips([shield], who), ())

    def test_a_two_hander_must_beat_the_worn_main_hand(self):
        who = worn("Grog", WARRIOR, 60, i13=45)
        self.assertEqual(equips([weapon(inventory_type=17, item_level=44)], who), ())
        got = equips([weapon(inventory_type=17, item_level=50)], who)
        self.assertEqual([e.item_level for e in got], [50])

    def test_a_two_hander_never_displaces_a_shield(self):
        who = worn("Grog", WARRIOR, 60, i13=30, i14=30)
        self.assertEqual(equips([weapon(inventory_type=17, item_level=60)], who), ())

    def test_main_hand_and_two_hand_are_one_choice(self):
        who = worn("Grog", WARRIOR, 60, i13=20)
        rows = [
            weapon(item_guid=1, entry=11, inventory_type=13, item_level=30),
            weapon(item_guid=2, entry=12, inventory_type=17, item_level=35),
        ]
        got = equips(rows, who)
        self.assertEqual([e.guid for e in got], [2])

    def test_no_off_hand_beside_a_two_hander_being_put_on(self):
        who = worn("Grog", WARRIOR, 60, i13=20)
        rows = [
            weapon(item_guid=2, entry=12, inventory_type=17, item_level=35),
            carried(
                item_guid=3, entry=13, item_subclass=6, inventory_type=14, item_level=30
            ),
        ]
        got = equips(rows, who)
        self.assertEqual([e.guid for e in got], [2])


class TheQueueIsBounded(unittest.TestCase):
    def setUp(self):
        self.wanted = equips([carried()], GROG)
        self.key = ("Grog", "e Hitem:7527:0")

    def test_a_fresh_piece_is_queued(self):
        queue, notes = bag_pressure.equips_to_queue(self.wanted, set(), {})
        self.assertEqual(queue, self.wanted)
        self.assertEqual(notes, ())

    def test_inside_the_retry_window_it_is_not_asked_again(self):
        queue, notes = bag_pressure.equips_to_queue(
            self.wanted, {self.key}, {self.key: 1}
        )
        self.assertEqual((queue, notes), ((), ()))

    def test_after_three_tries_it_is_held_and_said(self):
        queue, notes = bag_pressure.equips_to_queue(self.wanted, set(), {self.key: 3})
        self.assertEqual(queue, ())
        self.assertIn("Cabalist Chestpiece", notes[0])

    def test_equip_entry_ignores_other_commands(self):
        self.assertEqual(gear.equip_entry("nc +new rpg"), 0)
        self.assertEqual(gear.equip_entry(None), 0)


def _block(signature: str) -> str:
    src = BRIDGE.read_text(encoding="utf-8")
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


class TheBridgeWritesIt(unittest.TestCase):
    def test_the_vendor_pass_equips_above_the_town_run_gate(self):
        body = _block("    async def _vendor_once(self")
        equip = body.index(
            "await self._equip_upgrades(gear_rows, worn, names, jev_plan)"
        )
        gate = body.index("mode = await self._vendor_pass_mode(")
        self.assertLess(body.index("await self._hand_gear("), equip)
        self.assertLess(equip, gate)

    def test_the_row_is_a_bot_command_with_its_own_source(self):
        body = _block("def _insert_equip(")
        self.assertIn("'bot'", body)
        self.assertIn("EQUIP_SOURCE", body)

    def test_the_history_is_read_by_that_source_in_row_order(self):
        body = _block("def _equip_history(")
        self.assertIn("WHERE source = %s", body)
        self.assertIn("ORDER BY id", body)

    def test_each_equip_and_its_outcome_is_logged(self):
        body = _block("    async def _equip_upgrades(self")
        self.assertIn('"equip: %s puts on %s', body)
        self.assertIn('"equip: %s %r answered %s', body)


if __name__ == "__main__":
    unittest.main()

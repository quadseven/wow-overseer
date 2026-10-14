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

import asyncio
import pathlib
import re
import textwrap
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

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

    def test_three_tries_expire_after_the_two_hour_try_window(self):
        recent = {self.key}
        queue, _ = bag_pressure.equips_to_queue(self.wanted, recent, {self.key: 3})
        self.assertEqual(queue, ())
        queue, _ = bag_pressure.equips_to_queue(self.wanted, set(), {self.key: 3})
        self.assertEqual(queue, self.wanted)

    def test_refusal_holds_escalate_from_two_to_four_to_memory_hours(self):
        now = datetime(2026, 10, 14, 20, tzinfo=timezone.utc)
        worn = {"Grog": {4: (6000, "Sparkleshell Breastplate")}}
        for attempts, wait in ((1, 2), (2, 4), (3, 24)):
            answer = self.answer()
            answer[self.key]["created_at"] = now - timedelta(hours=1)
            queue, notes = bag_pressure.equips_to_queue(
                self.wanted, set(), {self.key: attempts}, answers=answer,
                worn=worn, holds={}, now=now,
            )
            if wait > 1:
                self.assertEqual(queue, ())
                self.assertIn("tries again at", notes[0])
            else:
                self.assertEqual(queue, self.wanted)
            answer[self.key]["created_at"] = now - timedelta(hours=wait)
            queue, _ = bag_pressure.equips_to_queue(
                self.wanted, set(), {self.key: attempts}, answers=answer,
                worn=worn, holds={}, now=now,
            )
            self.assertEqual(queue, self.wanted)

    def answer(self, status="unchanged", detail="the bot kept its own pick", id=7):
        return {
            self.key: dict(
                id=id,
                target_name="Grog",
                command=self.key[1],
                status=status,
                detail=detail,
            )
        }

    def test_equips_to_queue_holds_on_world_reason(self):
        """A refusal with a reason holds the piece at one try, and says why."""
        worn = {"Grog": {4: (6000, "Sparkleshell Breastplate")}}
        for status in ("unchanged", "error"):
            holds = {}
            queue, notes = bag_pressure.equips_to_queue(
                self.wanted,
                set(),
                {self.key: 1},
                answers=self.answer(status),
                worn=worn,
                holds=holds,
            )
            self.assertEqual(queue, ())
            self.assertEqual(
                notes,
                (
                    "Grog keeps Sparkleshell Breastplate over Cabalist Chestpiece: "
                "the bot kept its own pick; tries again at later",
                ),
            )
            self.assertEqual(gear.world_held(self.wanted, holds), 1)

    def test_a_delivered_or_bare_answer_keeps_the_three_try_rule(self):
        for answers in (
            self.answer("delivered"),
            self.answer("unchanged", detail=""),
        ):
            queue, notes = bag_pressure.equips_to_queue(
                self.wanted, set(), {self.key: 1}, answers=answers, holds={}
            )
            self.assertEqual((queue, notes), (self.wanted, ()))

    def test_an_applied_answer_is_not_counted_as_a_failed_equip(self):
        answers = self.answer("applied", detail="")
        for tries in (1, 3):
            queue, notes = bag_pressure.equips_to_queue(
                self.wanted, set(), {self.key: tries}, answers=answers, holds={}
            )
            self.assertEqual((queue, notes), ((), ()))

    def test_a_changed_worn_entry_in_that_slot_lifts_the_hold(self):
        holds = {}
        before = {"Grog": {4: (6000, "Sparkleshell Breastplate")}}
        after = {"Grog": {4: (6001, "Other Breastplate")}}
        args = (self.wanted, set(), {self.key: 1})
        kw = dict(answers=self.answer(), holds=holds)
        self.assertEqual(bag_pressure.equips_to_queue(*args, worn=before, **kw)[0], ())
        # Another slot changing does not lift it.
        other = {"Grog": {4: (6000, "Sparkleshell Breastplate"), 7: (1, "Boots")}}
        self.assertEqual(bag_pressure.equips_to_queue(*args, worn=other, **kw)[0], ())
        queue, notes = bag_pressure.equips_to_queue(*args, worn=after, **kw)
        self.assertEqual((queue, notes), (self.wanted, ()))
        # The same answer never holds it again, even with the old piece back.
        queue, _ = bag_pressure.equips_to_queue(*args, worn=before, **kw)
        self.assertEqual(queue, self.wanted)

    def test_leaving_the_bags_lifts_the_hold(self):
        holds = {}
        kw = dict(answers=self.answer(), holds=holds, holders={"Grog"})
        self.assertEqual(
            bag_pressure.equips_to_queue(self.wanted, set(), {}, **kw)[0], ()
        )
        bag_pressure.equips_to_queue((), set(), {}, **kw)
        queue, notes = bag_pressure.equips_to_queue(self.wanted, set(), {}, **kw)
        self.assertEqual((queue, notes), (self.wanted, ()))

    def test_another_pass_does_not_lift_the_hold(self):
        holds = {}
        kw = dict(answers=self.answer(), holds=holds)
        bag_pressure.equips_to_queue(self.wanted, set(), {}, holders={"Grog"}, **kw)
        bag_pressure.equips_to_queue((), set(), {}, holders={"Blammo"}, **kw)
        self.assertEqual(
            bag_pressure.equips_to_queue(self.wanted, set(), {}, **kw)[0], ()
        )

    def test_a_level_change_lifts_the_hold(self):
        """`since_level_change` drops the refusal, so no answer remains."""
        row = dict(self.answer()[self.key], created_at=1)
        holds = {}
        current = bag_pressure.since_level_change([row], {})
        answers = bag_pressure.latest_answers(current, {"pending"})
        self.assertEqual(
            bag_pressure.equips_to_queue(
                self.wanted, set(), {}, answers=answers, holds=holds
            )[0],
            (),
        )
        current = bag_pressure.since_level_change([row], {"Grog": 2})
        answers = bag_pressure.latest_answers(current, {"pending"})
        queue, notes = bag_pressure.equips_to_queue(
            self.wanted, set(), {}, answers=answers, holds=holds
        )
        self.assertEqual((queue, notes), (self.wanted, ()))
        self.assertEqual(holds, {})

    def test_the_latest_answered_row_is_the_one_read(self):
        rows = [
            dict(id=1, target_name="Grog", command="c", status="unchanged", detail="x"),
            dict(id=2, target_name="Grog", command="c", status="delivered", detail=""),
            dict(id=3, target_name="Grog", command="c", status="pending", detail=""),
        ]
        got = bag_pressure.latest_answers(rows, {"pending"})
        self.assertEqual(got[("Grog", "c")]["id"], 2)

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
    def test_a_first_worn_read_failure_waits_for_a_real_snapshot(self):
        class MySQLError(Exception):
            pass

        namespace = {
            "asyncio": asyncio,
            "bag_pressure": bag_pressure,
            "item_plan": types.SimpleNamespace(OPEN_STATUSES={"pending"}),
            "pymysql": types.SimpleNamespace(
                err=types.SimpleNamespace(MySQLError=MySQLError)
            ),
            "log": Mock(),
            "EQUIP_TRY_WINDOW_HOURS": 2,
            "EQUIP_MEMORY_HOURS": 24,
        }
        reads = iter(
            [
                MySQLError("read failed"),
                [
                    dict(
                        holder="Grog",
                        equipment_slot=4,
                        entry=6000,
                        name="Sparkleshell Breastplate",
                    )
                ],
                [
                    dict(
                        holder="Grog",
                        equipment_slot=4,
                        entry=6000,
                        name="Sparkleshell Breastplate",
                    )
                ],
            ]
        )

        def fetch(_names):
            read = next(reads)
            if isinstance(read, Exception):
                raise read
            return read

        inserts = []
        namespace["_fetch_worn_pieces"] = fetch
        namespace["_insert_equip"] = lambda equip: inserts.append(equip) or True
        exec(  # noqa: S102 - bridge.py's own source
            textwrap.dedent(_block("    async def _write_equips(self")), namespace
        )
        bridge = types.SimpleNamespace(_equip_worn={}, _equip_holds={})
        wanted = equips([carried()], GROG)
        history = [
            dict(
                id=7,
                target_name="Grog",
                command=wanted[0].command,
                status="unchanged",
                detail="the world kept its pick",
                recent=False,
            )
        ]

        asyncio.run(
            namespace["_write_equips"](bridge, wanted, history, holders={"Grog"})
        )
        self.assertEqual(bridge._equip_holds, {})
        self.assertEqual(inserts, [])

        asyncio.run(
            namespace["_write_equips"](bridge, wanted, history, holders={"Grog"})
        )
        self.assertEqual(
            bridge._equip_holds[("Grog", wanted[0].command)].worn,
            ((4, 6000, "Sparkleshell Breastplate"),),
        )
        asyncio.run(
            namespace["_write_equips"](bridge, wanted, history, holders={"Grog"})
        )
        self.assertFalse(bridge._equip_holds[("Grog", wanted[0].command)].lifted)
        self.assertEqual(inserts, [])

    def test_a_failed_worn_read_defers_only_the_holder_never_read(self):
        """A failed read holds Grog on his last snapshot and leaves Bork, who
        has none, out of both `wanted` and `holders`: nothing is queued for
        him against an empty slot, and he is asked for once a read lands."""

        class MySQLError(Exception):
            pass

        reads = iter(
            [
                MySQLError("read failed"),
                [
                    dict(
                        holder="Grog",
                        equipment_slot=4,
                        entry=6000,
                        name="Sparkleshell Breastplate",
                    ),
                    dict(holder="Bork", equipment_slot=4, entry=6001, name="Old Mail"),
                ],
            ]
        )

        def fetch(_names):
            read = next(reads)
            if isinstance(read, Exception):
                raise read
            return read

        inserts = []
        namespace = {
            "asyncio": asyncio,
            "bag_pressure": bag_pressure,
            "item_plan": types.SimpleNamespace(OPEN_STATUSES={"pending"}),
            "pymysql": types.SimpleNamespace(
                err=types.SimpleNamespace(MySQLError=MySQLError)
            ),
            "log": Mock(),
            "EQUIP_TRY_WINDOW_HOURS": 2,
            "EQUIP_MEMORY_HOURS": 24,
            "_fetch_worn_pieces": fetch,
            "_insert_equip": lambda equip: inserts.append(equip) or True,
        }
        exec(  # noqa: S102 - bridge.py's own source
            textwrap.dedent(_block("    async def _write_equips(self")), namespace
        )
        bridge = types.SimpleNamespace(
            _equip_worn={"Grog": {4: (6000, "Sparkleshell Breastplate")}},
            _equip_holds={},
        )
        wanted = equips(
            [carried(), carried(holder="Bork", item_guid=8002)],
            GROG + worn("Bork", WARRIOR, 60, i5=41),
        )
        grog = next(e for e in wanted if e.holder == "Grog")
        self.assertIn("Bork", {e.holder for e in wanted})
        history = [
            dict(
                id=7,
                target_name="Grog",
                command=grog.command,
                status="unchanged",
                detail="the world kept its pick",
                recent=False,
            )
        ]

        asyncio.run(
            namespace["_write_equips"](
                bridge, wanted, history, holders={"Grog", "Bork"}
            )
        )
        self.assertEqual(inserts, [])
        self.assertNotIn("Bork", bridge._equip_worn)
        self.assertFalse(bridge._equip_holds[("Grog", grog.command)].lifted)

        asyncio.run(
            namespace["_write_equips"](
                bridge, wanted, history, holders={"Grog", "Bork"}
            )
        )
        self.assertEqual([e.holder for e in inserts], ["Bork"])

    def test_the_vendor_pass_equips_above_the_town_run_gate(self):
        body = _block("    async def _vendor_once(self")
        equip = body.index(
            "await self._equip_upgrades(equip_rows, worn, names, jev_plan)"
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
        body = _block("    async def _write_equips(self")
        self.assertIn('"equip: %s puts on %s', body)
        self.assertIn("held on the world's answer", body)
        self.assertIn("answers=answers", body)
        body = _block("    async def _equip_upgrades(self")
        self.assertIn("await self._write_equips(wanted, current, holders=names)", body)
        self.assertIn('"equip: %s %r answered %s', body)

    def test_a_failed_worn_read_keeps_the_pass_and_the_last_read(self):
        """A database fault on the worn read neither stops the equip pass nor
        lifts a hold: it falls back on the last read per holder."""
        body = _block("    async def _write_equips(self")
        read = body.index("_fetch_worn_pieces, wearers")
        guard = body.index("except pymysql.err.MySQLError")
        self.assertLess(read, guard)
        self.assertIn("self._equip_worn.update(", body)
        self.assertLess(guard, body.index("bag_pressure.equips_to_queue("))
        self.assertIn("self._equip_worn: dict = {}", BRIDGE.read_text(encoding="utf-8"))

    def test_family_equip_leaves_roster_members_to_the_gear_drive(self):
        body = _block("    async def _equip_upgrades(self")
        read = body.index("_fetch_enabled_roster_names")
        write = body.index("await self._write_equips(wanted, current, holders=names)")
        self.assertLess(read, write)
        self.assertIn("equip.holder not in roster_names", body)
        self.assertIn("len(left_to_drive), len(roster_names)", body)
        self.assertIn(
            "equip: left %d piece(s) to the module's gear drive for %d roster member(s)",
            body,
        )

    def test_a_failed_roster_read_catches_only_database_errors(self):
        body = _block("    async def _equip_upgrades(self")
        self.assertIn("except (OSError, pymysql.err.MySQLError) as exc:", body)
        self.assertNotIn("except Exception", body)
        self.assertIn('"equip: could not read the enabled roster: %s"', body)

    def test_a_failed_roster_read_does_not_queue_any_equips(self):
        body = _block("    async def _equip_upgrades(self")
        tail = textwrap.dedent(
            body[body.index("        try:\n", body.index("jev_equips")) :]
        )
        namespace = {
            "asyncio": asyncio,
            "_fetch_enabled_roster_names": Mock(side_effect=OSError("read failed")),
            "pymysql": Mock(err=Mock(MySQLError=OSError)),
            "log": Mock(),
        }
        # Compiles a slice of our own bridge.py source, never external input.
        exec(  # noqa: S102
            "async def run(self, wanted, current, names):\n"
            + textwrap.indent(tail, "    "),
            namespace,
        )
        bridge = Mock(_write_equips=AsyncMock())

        asyncio.run(namespace["run"](bridge, equips([carried()], GROG), {}, ()))

        bridge._write_equips.assert_not_awaited()
        namespace["log"].warning.assert_called_once()

    def test_non_roster_family_pick_remains_wanted(self):
        body = _block("    async def _equip_upgrades(self")
        self.assertIn("wanted = tuple(equip for equip in wanted", body)
        self.assertIn("if equip.holder not in roster_names", body)


if __name__ == "__main__":
    unittest.main()

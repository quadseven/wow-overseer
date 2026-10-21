"""A two-hander over a worn shield needs a free bag slot first (#1088).

The live case, read 2026-10-18: three guild members wore a one-hand weapon and
a shield (equipment slots 15 and 16) and wanted a two-hander. Putting it on
moves the main hand into the bag slot the two-hander leaves and the shield
into a second, free one. None had a free slot (16 of 16 backpack slots used,
and one 6-slot bag holding 6 items), so the world refused every equip with
InventoryResult 21, "items cannot be swapped". Six refusals each in 48 hours,
and from the third one the staged retry parked the member for the whole
24 hour memory window, reading "Trying to wear ...: waiting for the game to
accept it", on a refusal nothing would clear.

What is pinned here:
- `gear.room_needed` counts the free slots an equip needs: one for a
  two-hander over a main hand and a shield, none for a one-for-one swap.
- An equip the holder has no room for is never queued and never held on the
  world's answer: its note says why in plain words, and the member's
  shortfall goes to the guild jobs pass (`gear.equip_room`).
- Once the room is there, a hold that began short of room lifts at once, so
  the equip is asked again that pass instead of 24 hours later.
- The guild jobs pass makes the room: a member short of it for an upgrade
  sells first, and one with nothing to part with is told so, with no step.
"""

import asyncio
import textwrap
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import bag_pressure
import gear
from test_classquest import class_plan, who
from test_classquest_room import grey, room_steps
from test_equip_upgrades import EQUIP_READS, _block

NOW = datetime(2026, 10, 18, 6, 1, tzinfo=timezone.utc)

STAFF = gear.Equip(
    holder="Cronk",
    guid=7001,
    entry=7757,
    name="Odo's Ley Staff",
    slot="two_hand",
    item_level=30,
    worn_level=24,
    reason="a two-hander beats the main hand and shield",
)
KEY = ("Cronk", STAFF.command)
# Cookie's Tenderizer in the main hand and War Paint Shield in the off hand.
WORN = {"Cronk": {15: (5197, "Cookie's Tenderizer"), 16: (15524, "War Paint Shield")}}
REFUSAL = "the game would not put it on (InventoryResult 21)"


def refused(minutes_ago=2, row_id=41):
    return {
        KEY: dict(
            id=row_id,
            target_name="Cronk",
            command=STAFF.command,
            status="error",
            detail=REFUSAL,
            created_at=NOW - timedelta(minutes=minutes_ago),
        )
    }


def queue_for(free, holds=None, answers=None, tries=3, now=NOW):
    return bag_pressure.equips_to_queue(
        (STAFF,),
        set(),
        {KEY: tries},
        answers=refused() if answers is None else answers,
        worn=WORN,
        holds={} if holds is None else holds,
        now=now,
        free_slots=free,
    )


class TheRoomAnEquipNeeds(unittest.TestCase):
    def test_a_two_hander_over_a_main_hand_and_a_shield_needs_one(self):
        self.assertEqual(gear.room_needed(STAFF, WORN), 1)

    def test_a_two_hander_over_a_main_hand_alone_needs_none(self):
        worn = {"Cronk": {15: (5197, "Cookie's Tenderizer")}}
        self.assertEqual(gear.room_needed(STAFF, worn), 0)

    def test_a_one_for_one_swap_needs_none(self):
        chest = gear.Equip("Cronk", 7002, 6000, "Vest", "chest", 30, 20, "upgrade")
        worn = {"Cronk": {4: (6001, "Old Vest")}}
        self.assertEqual(gear.room_needed(chest, worn), 0)

    def test_a_short_holder_is_named_with_what_it_needs(self):
        room = gear.equip_room((STAFF,), WORN, {"Cronk": 0})
        self.assertEqual(
            room,
            {
                "Cronk": (
                    1,
                    "to put on Odo's Ley Staff over Cookie's Tenderizer "
                    "and War Paint Shield",
                    0,
                )
            },
        )

    def test_a_holder_with_room_or_unread_bags_is_not_short(self):
        self.assertEqual(gear.equip_room((STAFF,), WORN, {"Cronk": 1}), {})
        self.assertEqual(gear.equip_room((STAFF,), WORN, {}), {})
        self.assertEqual(gear.equip_room((STAFF,), WORN, None), {})


class AFullBackpack(unittest.TestCase):
    def test_a_refused_two_hander_is_not_held_for_a_day(self):
        """The red test: on main the third refusal holds Cronk until the same
        time tomorrow, a stuck member on a refusal nothing will clear."""
        holds = {}
        queue, notes = queue_for({"Cronk": 0}, holds=holds)
        self.assertEqual(queue, ())
        self.assertFalse(any("tries again at" in n for n in notes), notes)
        self.assertEqual(
            notes,
            (
                "Cronk leaves Odo's Ley Staff in its bags: putting it on over "
                "Cookie's Tenderizer and War Paint Shield needs 1 free bag "
                "slot(s) and it has 0",
            ),
        )
        self.assertEqual(gear.world_held((STAFF,), holds), 1)

    def test_no_doomed_row_is_written_before_any_refusal(self):
        queue, notes = queue_for({"Cronk": 0}, answers={}, tries=0)
        self.assertEqual(queue, ())
        self.assertIn("needs 1 free bag slot(s) and it has 0", notes[0])

    def test_the_freed_slot_asks_again_at_once(self):
        """The room the guild pass made lifts the hold the refusal began, the
        same pass, though its retry time is still ahead."""
        holds = {}
        queue_for({"Cronk": 0}, holds=holds)
        queue, notes = queue_for({"Cronk": 1}, holds=holds)
        self.assertEqual(queue, (STAFF,))
        self.assertEqual(notes, ())
        self.assertEqual(gear.world_held((STAFF,), holds), 0)

    def test_room_seen_after_an_unread_pass_lifts_the_old_hold(self):
        holds = {}
        queue_for(None, holds=holds)
        queue, notes = queue_for({"Cronk": 0}, holds=holds)
        self.assertEqual(queue, ())
        self.assertFalse(any("tries again at" in note for note in notes))
        queue, notes = queue_for({"Cronk": 1}, holds=holds)
        self.assertEqual(queue, (STAFF,))
        self.assertEqual(notes, ())

    def test_a_room_refusal_with_room_read_waits_for_one_more_slot(self):
        """The read said there was room and the world said 21 anyway (#1088):
        the wait stands while the bags stay as they were, and lifts the pass
        one more slot is free, never a day later."""
        holds = {}
        queue, notes = queue_for({"Cronk": 1}, holds=holds)
        self.assertEqual(queue, ())
        self.assertIn("needs 2 free bag slot(s) and it has 1", notes[0])
        queue, notes = queue_for({"Cronk": 1}, holds=holds)
        self.assertEqual(queue, ())
        self.assertIn("needs 2 free bag slot(s) and it has 1", notes[0])
        queue, notes = queue_for({"Cronk": 2}, holds=holds)
        self.assertEqual((queue, notes), ((STAFF,), ()))

    def test_unread_bags_wait_on_the_refusal(self):
        queue, notes = queue_for(None)
        self.assertEqual(queue, ())
        self.assertIn("its bags were not read", notes[0])

    def test_a_one_for_one_swap_is_queued_with_full_bags(self):
        chest = gear.Equip("Cronk", 7002, 6000, "Vest", "chest", 30, 20, "upgrade")
        queue, notes = bag_pressure.equips_to_queue(
            (chest,),
            set(),
            {},
            worn={"Cronk": {4: (6001, "Old Vest")}},
            free_slots={"Cronk": 0},
        )
        self.assertEqual(queue, (chest,))
        self.assertEqual(notes, ())


ROOM = {"Cronk": (1, "to put on Odo's Ley Staff over Cookie's Tenderizer")}


def jobs_plan(members, **kw):
    """The guild jobs plan with no class quest book, so no class step competes."""
    return class_plan(members, classes=None, **kw)


def full_member(carried=()):
    return who("Cronk", free_slots=0, carried=tuple(carried))


class TheGuildMakesTheRoom(unittest.TestCase):
    def test_a_full_member_sells_to_make_room_for_its_upgrade(self):
        plan = jobs_plan([full_member([grey(1)])], equip_room=ROOM)
        (step,) = room_steps(plan)
        self.assertEqual(step.holder, "Cronk")
        self.assertEqual([r.command for r in step.rows], ["guid:1"])
        self.assertTrue(step.walk.command.startswith("walk-to-vendor any"))
        self.assertIn(
            "Cronk makes room in its bags (0 free, 1 needed) to put on Odo's Ley Staff",
            plan.lines["Cronk"],
        )

    def test_a_member_with_nothing_to_part_with_is_told_so(self):
        plan = jobs_plan([full_member()], equip_room=ROOM)
        self.assertEqual(room_steps(plan), [])
        self.assertIn(
            "Cronk has no room to put on Odo's Ley Staff over Cookie's "
            "Tenderizer and nothing it may sell, mail or destroy; the upgrade "
            "stays in its bags",
            plan.notes,
        )

    def test_a_member_with_room_now_takes_no_room_step(self):
        m = who("Cronk", free_slots=1, carried=(grey(1),))
        plan = jobs_plan([m], equip_room=ROOM)
        self.assertEqual(room_steps(plan), [])

    def test_no_room_asked_takes_no_room_step(self):
        plan = jobs_plan([full_member([grey(1)])])
        self.assertEqual(
            [s for s in room_steps(plan) if "to put on" in s.said],
            [],
        )


class MySQLError(Exception):
    """Stands in for pymysql.err.MySQLError in the exec'd bridge source."""


def _write_pass(free_reads):
    """bridge._write_equips for Cronk's staff over its third refusal, the bag
    room read from `free_reads` in turn (an exception is raised). Returns the
    fake bridge, the rows it wrote, the pass and the equip history."""
    reads = iter(free_reads)

    def free(_names):
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
        "_fetch_worn_pieces": lambda _names: [
            dict(holder="Cronk", equipment_slot=slot, entry=entry, name=name)
            for slot, (entry, name) in WORN["Cronk"].items()
        ],
        "_fetch_free_slots": free,
        "_insert_equip": lambda equip: inserts.append(equip) or True,
        **EQUIP_READS,
    }
    # Compiles a slice of our own bridge.py source, never external input.
    exec(textwrap.dedent(_block("    async def _write_equips(self")), namespace)  # noqa: S102
    bridge = types.SimpleNamespace(
        _equip_worn={}, _equip_holds={}, _equip_room={}, _equip_answers_read=set()
    )
    # _write_equips judges the history against the real clock, so the refusals
    # are stamped from it too; a pinned NOW aged them out 24 hours later.
    refused_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    history = [dict(refused()[KEY], recent=False, created_at=refused_at)] * 3
    return bridge, inserts, namespace["_write_equips"], history


class TheBridgeAsksOnceThereIsRoom(unittest.TestCase):
    def test_full_bags_write_nothing_then_the_freed_slot_writes_the_equip(self):
        bridge, inserts, write, history = _write_pass([{"Cronk": 0}, {"Cronk": 1}])
        asyncio.run(write(bridge, (STAFF,), history, holders={"Cronk"}))
        self.assertEqual(inserts, [])
        short = dict(bridge._equip_room)
        asyncio.run(write(bridge, (STAFF,), history, holders={"Cronk"}))
        # On main the third refusal held Cronk 24 hours, so nothing was written.
        self.assertEqual(inserts, [STAFF])
        self.assertEqual(short["Cronk"][0], 1)
        self.assertEqual(bridge._equip_room, {})

    def test_an_unread_room_judges_as_before(self):
        bridge, inserts, write, history = _write_pass([MySQLError("read failed")])
        asyncio.run(write(bridge, (STAFF,), history, holders={"Cronk"}))
        self.assertEqual(inserts, [])
        self.assertEqual(bridge._equip_room, {})

    def test_the_guild_jobs_plan_is_given_the_shortfalls(self):
        body = _block("    async def _plan_guild_jobs(self")
        self.assertIn("equip_room=self._equip_room", body)


if __name__ == "__main__":
    unittest.main()

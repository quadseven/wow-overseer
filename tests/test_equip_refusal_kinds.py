"""No equip refusal a member can clear itself ever becomes a long hold (#1088).

The live record, read 2026-10-16 to 2026-10-21 on the dev realm:

- Cronk (Odo's Ley Staff, InventoryResult 21), Bonk (Rhahk'Zor's Hammer, 21,
  39 and 38) and Ezzo (Emberstone Staff, 21) were held 8.6 to 10.8 hours each,
  "Waiting for the game to accept it". From the third refusal the staged wait
  `(15, 30, memory_hours * 60)[min(attempts, 3) - 1]` parked each member for
  the whole 24 hour memory window. 21 is "items cannot be swapped": a
  two-hander over a worn shield must move the shield into a free bag slot,
  and none of them had one.
- After #1191 the full-bag case stopped being written at all, and the hold
  became an upgrade left in the bags with no limit: Bonk, Cronk, Gorvash and
  Blingz logged "leaves <item> in its bags ... needs 1 free bag slot(s) and
  it has 0" on all 23 guild passes of 2026-10-21 14:31Z-18:14Z, and the
  guild jobs pass never made the room, because its make-room step sat behind
  the class quest, which comes first for every member that has one.
- Blingz's case was a misjudged need: a ring over two worn rings displaces one
  ring into the bag slot the new one leaves, so it needs no free slot.

What is pinned here, by what the member can do about the world's answer:

- ROOM (21, 4, 50, 53, 56, 62): the member makes the room. The answer is
  asked again the pass a slot frees; with none freed in 30 minutes the
  upgrade is settled with a plain reason until one is, never the memory
  window and never a doomed row every 30 minutes; the shortfall the world
  revealed goes to the make-room step even when the bag read said there was
  room.
- PASSING (stunned, dead, busy, in combat, disarmed, item locked, arena):
  15 minutes, every time. GONE (the piece is not carried, or not found):
  never held, asked again when the bags change.
- FINAL (level, skill, proficiency, unique-equipped, rank, reputation, ...):
  the upgrade is dropped at once with a plain reason, never held and never a
  "Waiting for the game to accept it" note. An unknown answer, or the bot not
  putting the piece on, is asked once more, then dropped the same way.
- A refusal inside the retry window never blocks the retry its hold allows.
- The class quest still comes ahead of the make-room step for an upgrade
  (operator rule, docs/ROLLS.md section 4); the room step runs on a pass
  the class quest asks nothing.
- A room shortfall that keeps a member from an upgrade is on the stuck read,
  so a member that waits on bag room is never hidden.
"""

import asyncio
import textwrap
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import bag_pressure
import gear
import nowstatus
from test_classquest import class_plan, who
from test_classquest_room import grey, room_steps
from test_equip_upgrades import EQUIP_READS, _block

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)

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


def answer(detail, minutes_ago=2, row_id=41, status="error"):
    return {
        KEY: dict(
            id=row_id,
            target_name="Cronk",
            command=STAFF.command,
            status=status,
            detail=detail,
            created_at=NOW - timedelta(minutes=minutes_ago),
        )
    }


def queue(detail, minutes_ago=2, tries=3, free=None, holds=None, worn=WORN, now=NOW):
    holds = {} if holds is None else holds
    out = gear.equips_to_queue(
        (STAFF,),
        set(),
        {KEY: tries},
        answers=answer(detail, minutes_ago),
        worn=worn,
        holds=holds,
        now=now,
        online={"Cronk"},
        free_slots=free,
    )
    return out, holds


def waited(holds):
    """Minutes from the refusal to the retry the hold names."""
    hold = holds[KEY]
    delta = hold.retry_at - hold.refusal_at.replace(tzinfo=timezone.utc)
    return int(delta.total_seconds() // 60)


class TheRoomAnEquipNeeds(unittest.TestCase):
    def test_a_two_hander_over_a_shield_alone_needs_a_slot(self):
        """The core stores the off hand before it equips a two-hander
        (Player::CanEquipItem), whatever the main hand holds: on main an
        empty main hand counted 0, the equip was written and refused 21."""
        worn = {"Cronk": {16: (15524, "War Paint Shield")}}
        self.assertEqual(gear.room_needed(STAFF, worn), 1)

    def test_a_two_hander_over_a_main_hand_alone_needs_none(self):
        worn = {"Cronk": {15: (5197, "Cookie's Tenderizer")}}
        self.assertEqual(gear.room_needed(STAFF, worn), 0)

    def test_a_ring_over_two_worn_rings_needs_none(self):
        """Blingz, 2026-10-21: held back on all 23 guild passes."""
        band = gear.Equip("Blingz", 1, 11985, "Viridian Band", "finger", 25, 20, "up")
        worn = {
            "Blingz": {
                10: (13097, "Lavishly Jeweled Ring"),
                11: (4997, "Volcanic Rock Ring"),
            }
        }
        self.assertEqual(gear.room_needed(band, worn), 0)
        queued, notes = gear.equips_to_queue(
            (band,), set(), {}, worn=worn, free_slots={"Blingz": 0}
        )
        self.assertEqual((queued, notes), ((band,), ()))

    def test_a_trinket_over_two_worn_trinkets_needs_none(self):
        charm = gear.Equip(
            "Blingz", 2, 744, "Thunderbrew's Boot Flask", "trinket", 25, 20, "up"
        )
        worn = {"Blingz": {12: (1, "Charm"), 13: (2, "Idol")}}
        self.assertEqual(gear.room_needed(charm, worn), 0)


class ARoomRefusal(unittest.TestCase):
    """The world said the bags are too full: the member can clear that."""

    def test_a_third_swap_refusal_waits_thirty_minutes_not_a_day(self):
        """The red test: on main the third 21 waited the 24 hour window."""
        (queued, notes), holds = queue("InventoryResult 21", tries=3, free={"Cronk": 1})
        self.assertEqual(queued, ())
        self.assertIsInstance(holds[KEY], gear.RoomWait)
        self.assertIn("needs 2 free bag slot(s) and it has 1", notes[0])
        (queued, notes), holds = queue(
            "InventoryResult 21", minutes_ago=31, tries=3, free={"Cronk": 1}
        )
        self.assertEqual(queued, ())
        self.assertIsInstance(holds[KEY], gear.EquipDropped)
        self.assertIn("Cronk waits for bag room to wear Odo's Ley Staff", notes[0])
        self.assertEqual(nowstatus.classify("equip: " + notes[0]), [])

    def test_every_bag_full_code_is_a_room_refusal(self):
        for code in (4, 21, 50, 53, 56, 62):
            with self.subTest(code=code):
                detail = "InventoryResult %d" % code
                (queued, _notes), holds = queue(detail, tries=6, free={"Cronk": 1})
                self.assertEqual(queued, ())
                self.assertIsInstance(holds[KEY], gear.RoomWait)
                holds = {}
                (queued, notes), _ = queue(
                    detail, minutes_ago=31, tries=6, free={"Cronk": 1}, holds=holds
                )
                self.assertEqual(queued, ())
                self.assertIn("waits for bag room", notes[0])
                (queued, notes), _ = queue(
                    detail, minutes_ago=31, tries=6, free={"Cronk": 2}, holds=holds
                )
                self.assertEqual((queued, notes), ((STAFF,), ()))

    def test_a_named_inventory_full_is_read_too(self):
        (queued, _), holds = queue(
            "EQUIP_ERR_INVENTORY_FULL 50", tries=4, free={"Cronk": 1}
        )
        self.assertEqual(queued, ())
        self.assertIsInstance(holds[KEY], gear.RoomWait)

    def test_the_world_reveals_the_shortfall_the_bag_read_missed(self):
        """The read said one slot was free (a quiver's, say); the world
        refused 21 anyway. The make-room step is asked for one more slot than
        the read showed, and on main it was asked for nothing."""
        holds = {}
        queue("InventoryResult 21", tries=3, free={"Cronk": 1}, holds=holds)
        room = gear.equip_room((STAFF,), WORN, {"Cronk": 1}, holds)
        self.assertEqual(room["Cronk"][0], 2)
        self.assertIn("Odo's Ley Staff", room["Cronk"][1])

    def test_the_freed_slot_asks_again_the_same_pass(self):
        holds = {}
        queue("InventoryResult 21", tries=3, free={"Cronk": 1}, holds=holds)
        (queued, notes), _ = queue(
            "InventoryResult 21", tries=3, free={"Cronk": 2}, holds=holds
        )
        self.assertEqual((queued, notes), ((STAFF,), ()))
        self.assertEqual(gear.equip_room((STAFF,), WORN, {"Cronk": 2}, holds), {})

    def test_full_bags_and_a_shield_alone_are_named_before_any_refusal(self):
        """No doomed row is written for the core to refuse: the shortfall
        goes to the make-room step instead (main hand empty, shield worn)."""
        worn = {"Cronk": {16: (15524, "War Paint Shield")}}
        queued, notes = gear.equips_to_queue(
            (STAFF,), set(), {}, worn=worn, free_slots={"Cronk": 0}
        )
        self.assertEqual(queued, ())
        self.assertIn("needs 1 free bag slot(s) and it has 0", notes[0])
        self.assertEqual(
            gear.equip_room((STAFF,), worn, {"Cronk": 0}),
            {"Cronk": (1, "to put on Odo's Ley Staff over War Paint Shield", 0)},
        )


class APassingOrGoneAnswer(unittest.TestCase):
    def test_item_locked_and_object_busy_pass_by_themselves(self):
        for code in (36, 58):
            with self.subTest(code=code):
                (queued, _), holds = queue("InventoryResult %d" % code, tries=5)
                self.assertEqual(queued, ())
                self.assertEqual(waited(holds), 15)

    def test_a_piece_not_carried_is_never_held(self):
        """The bags lag the world's save by up to fifteen minutes: the next
        read says whether the piece is gone, and a piece that is gone leaves
        `wanted`. So the answer is never a hold or a stuck reason: the equip
        is forgotten until the bags change. On main: the 24 hour park."""
        for detail in (
            "not carried",
            "InventoryResult 23",
            "EQUIP_ERR_ITEM_NOT_FOUND 23",
            "InventoryResult 32",
            "InventoryResult 54",
        ):
            with self.subTest(detail=detail):
                holds = {}
                (queued, notes), _ = queue(
                    detail, tries=3, free={"Cronk": 3}, holds=holds
                )
                self.assertEqual(queued, ())
                self.assertEqual(gear.world_held((STAFF,), holds), 0)
                self.assertNotIn("tries again at", notes[0])
                self.assertEqual(nowstatus.classify("equip: " + notes[0]), [])
                later = NOW + timedelta(hours=10)
                (queued, _), _ = queue(
                    detail, tries=3, free={"Cronk": 3}, holds=holds, now=later
                )
                self.assertEqual(queued, ())
                (queued, notes), _ = queue(
                    detail, tries=3, free={"Cronk": 4}, holds=holds, now=later
                )
                self.assertEqual((queued, notes), ((STAFF,), ()))


class AnAnswerNobodyCanClear(unittest.TestCase):
    def test_unique_equipped_drops_the_upgrade_with_a_reason(self):
        """The red test for (c): on main the third refusal parked a day."""
        (queued, notes), holds = queue("InventoryResult 67", tries=1)
        self.assertEqual(queued, ())
        self.assertEqual(len(notes), 1)
        self.assertNotIn("tries again at", notes[0])
        self.assertIn("Cronk cannot wear Odo's Ley Staff", notes[0])
        self.assertIn("unique", notes[0])
        self.assertEqual(gear.world_held((STAFF,), holds), 0)
        self.assertEqual(nowstatus.classify("equip: " + notes[0]), [])

    def test_every_final_code_drops_at_the_first_answer(self):
        for code in (1, 2, 3, 8, 9, 10, 11, 12, 13, 14, 18, 20, 63, 64, 67, 75, 76, 80):
            with self.subTest(code=code):
                (queued, notes), holds = queue("InventoryResult %d" % code, tries=1)
                self.assertEqual(queued, ())
                self.assertIn("cannot wear", notes[0])
                self.assertEqual(gear.world_held((STAFF,), holds), 0)

    def test_a_dropped_upgrade_is_not_asked_again_on_a_later_pass(self):
        holds = {}
        queue("InventoryResult 67", tries=1, holds=holds)
        (queued, notes), _ = queue(
            "InventoryResult 67", minutes_ago=600, tries=1, holds=holds
        )
        self.assertEqual(queued, ())
        self.assertIn("cannot wear", notes[0])

    def test_a_dropped_upgrade_reopens_when_the_worn_piece_changes(self):
        holds = {}
        queue("InventoryResult 67", tries=1, holds=holds)
        changed = {"Cronk": {15: (1, "Other Mace"), 16: (15524, "War Paint Shield")}}
        (queued, notes), _ = queue(
            "InventoryResult 67", tries=1, holds=holds, worn=changed, free={"Cronk": 1}
        )
        self.assertEqual((queued, notes), ((STAFF,), ()))

    def test_an_unknown_answer_is_asked_once_more_then_dropped(self):
        for detail in ("the bot did not put the item on", "InventoryResult 99"):
            with self.subTest(detail=detail):
                (queued, notes), holds = queue(detail, tries=1, minutes_ago=2)
                self.assertEqual(queued, ())
                self.assertEqual(waited(holds), 15)
                (queued, notes), holds = queue(detail, tries=2)
                self.assertEqual(queued, ())
                self.assertIn("cannot wear", notes[0])
                self.assertEqual(gear.world_held((STAFF,), holds), 0)

    def test_no_answer_ever_waits_past_thirty_minutes(self):
        """Every code the core can write, at any try count: a hold never names
        a retry more than 30 minutes after the refusal."""
        for code in range(0, 100):
            for tries in (1, 2, 3, 9):
                with self.subTest(code=code, tries=tries):
                    _, holds = queue("InventoryResult %d" % code, tries=tries)
                    hold = holds.get(KEY)
                    if isinstance(hold, gear.WorldHold) and not hold.lifted:
                        self.assertLessEqual(waited(holds), 30)


class MySQLError(Exception):
    """Stands in for pymysql.err.MySQLError in the exec'd bridge source."""


def _write_pass(history, free):
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
        "_fetch_free_slots": lambda _names: dict(free),
        "_insert_equip": lambda equip: inserts.append(equip) or True,
        **EQUIP_READS,
    }
    # Compiles a slice of our own bridge.py source, never external input.
    exec(textwrap.dedent(_block("    async def _write_equips(self")), namespace)  # noqa: S102
    bridge = types.SimpleNamespace(
        _equip_worn={}, _equip_holds={}, _equip_room={}, _equip_answers_read=set()
    )
    asyncio.run(
        namespace["_write_equips"](bridge, (STAFF,), history, holders={"Cronk"})
    )
    return bridge, inserts


class TheBridgeRetriesWhenTheHoldAllows(unittest.TestCase):
    def test_a_refusal_inside_the_retry_window_does_not_block_the_retry(self):
        """Shinyhair, 2026-10-19: code 38 at 01:52, 03:54 and 05:56, two hours
        apart, because the 2 hour retry window held the piece after its
        15 minute hold had lifted. Here a 38 from 20 minutes ago is asked
        again; on main nothing was written."""
        at = datetime.now(timezone.utc) - timedelta(minutes=20)
        row = dict(answer("InventoryResult 38")[KEY], created_at=at, recent=True)
        _bridge, inserts = _write_pass([row], {"Cronk": 1})
        self.assertEqual(inserts, [STAFF])

    def test_an_unanswered_ask_inside_the_window_still_blocks(self):
        at = datetime.now(timezone.utc) - timedelta(minutes=20)
        row = dict(answer("", status="delivered")[KEY], created_at=at, recent=True)
        _bridge, inserts = _write_pass([row], {"Cronk": 1})
        self.assertEqual(inserts, [])

    def test_a_room_refusal_names_the_shortfall_for_the_guild_pass(self):
        at = datetime.now(timezone.utc) - timedelta(minutes=5)
        row = dict(answer("InventoryResult 21")[KEY], created_at=at, recent=True)
        bridge, inserts = _write_pass([row, row, row], {"Cronk": 1})
        self.assertEqual(inserts, [])
        self.assertEqual(bridge._equip_room["Cronk"][0], 2)


ROOM = {
    "Bigzug": (
        1,
        "to put on Odo's Ley Staff over Cookie's Tenderizer and War Paint Shield",
    )
}


class TheClassQuestComesBeforeTheRoom(unittest.TestCase):
    def test_a_full_member_with_a_class_quest_takes_the_class_quest(self):
        """The operator's rule: the class quest is the first rung for every
        member that has one, ahead of making room for an upgrade."""
        m = who(quests_done=frozenset({1505}), free_slots=0, carried=(grey(1),))
        plan = class_plan([m], equip_room=ROOM)
        self.assertEqual(room_steps(plan), [])
        self.assertEqual([s.action for s in plan.steps], ["classquest"])

    def test_with_no_class_quest_the_full_member_makes_room(self):
        m = who(quests_done=frozenset({1505}), free_slots=0, carried=(grey(1),))
        plan = class_plan([m], classes=None, equip_room=ROOM)
        (step,) = room_steps(plan)
        self.assertEqual(step.holder, "Bigzug")
        self.assertIn("to put on Odo's Ley Staff", step.said)

    def test_with_nothing_to_part_with_the_class_quest_still_runs(self):
        m = who(quests_done=frozenset({1505}), free_slots=0, carried=())
        plan = class_plan([m], equip_room=ROOM)
        self.assertEqual(room_steps(plan), [])
        self.assertTrue(any(s.action == "classquest" for s in plan.steps))
        # With no class quest either, the note says why nothing is done.
        plan = class_plan([m], classes=None, equip_room=ROOM)
        self.assertEqual(room_steps(plan), [])
        self.assertTrue(any("the upgrade stays in its bags" in n for n in plan.notes))


class TheShortfallIsOnTheStuckRead(unittest.TestCase):
    def test_a_member_waiting_on_bag_room_for_an_upgrade_is_seen(self):
        """On main the line matched no rule: four members carried upgrades
        for days and neither the stuck list nor health could see one."""
        (step,) = nowstatus.classify(
            "equip: Gorvash leaves Rockslicer in its bags: putting it on over "
            "Gladius and Gladius needs 1 free bag slot(s) and it has 0"
        )
        self.assertEqual((step.subject, step.kind), ("Gorvash", "equip_held"))
        self.assertEqual(step.doing, "Trying to wear Rockslicer")
        self.assertEqual(
            step.waiting, "room in its bags (1 free slot(s) needed, 0 free)"
        )


if __name__ == "__main__":
    unittest.main()

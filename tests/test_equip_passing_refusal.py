"""A refusal on a passing state of the holder never waits a day (#869).

The live case, read 2026-10-18 after the 18:21Z bridge ship: Durg's equip of
Raider's Legguards was refused with InventoryResult 60 (EQUIP_ERR_NOT_IN_COMBAT)
and Bonk's and Shinyhair's with InventoryResult 38 (EQUIP_ERR_YOU_ARE_DEAD).
Both codes are Player::CanEquipItem saying what the holder was doing at that
moment, not anything about the piece. On the third such refusal the staged
retry still waited the whole 24 hour memory window, so each member read
"Trying to wear ...: waiting for the game to accept it" for hours on a state
that had long passed.

What is pinned here:
- A refusal on one of those codes waits the first step (15 minutes) however
  many times it has been refused, then the piece is asked again.
- No other refusal waits the memory window either (#1088): bags too full for
  the swap (InventoryResult 21) wait at most 30 minutes, and a named skill
  refusal drops the upgrade with its reason (test_equip_refusal_kinds).
"""

import unittest
from datetime import datetime, timedelta, timezone

import gear

NOW = datetime(2026, 10, 18, 22, 5, tzinfo=timezone.utc)

LEGS = gear.Equip(
    holder="Durg",
    guid=8101,
    entry=1978,
    name="Raider's Legguards",
    slot="legs",
    item_level=24,
    worn_level=20,
    reason="upgrade",
)
KEY = ("Durg", LEGS.command)
WORN = {"Durg": {6: (6187, "Defender Leggings")}}


def answers(detail, minutes_ago=2):
    return {
        KEY: dict(
            id=91,
            target_name="Durg",
            command=LEGS.command,
            status="error",
            detail=detail,
            created_at=NOW - timedelta(minutes=minutes_ago),
        )
    }


def queue(detail, minutes_ago=2, tries=3, holds=None):
    holds = {} if holds is None else holds
    out = gear.equips_to_queue(
        (LEGS,),
        set(),
        {KEY: tries},
        answers=answers(detail, minutes_ago),
        worn=WORN,
        holds=holds,
        now=NOW,
        online={"Durg"},
    )
    return out, holds


class APassingStateRefusal(unittest.TestCase):
    def test_in_combat_waits_fifteen_minutes_on_the_third_refusal(self):
        """The red test: on main the third refusal waits 24 hours."""
        (queued, notes), holds = queue("InventoryResult 60")
        self.assertEqual(queued, ())
        self.assertEqual(len(notes), 1)
        self.assertIn("InventoryResult 60", notes[0])
        self.assertEqual(
            holds[KEY].retry_at, NOW - timedelta(minutes=2) + timedelta(minutes=15)
        )

    def test_dead_is_asked_again_after_fifteen_minutes(self):
        (queued, notes), holds = queue("InventoryResult 38", minutes_ago=16)
        self.assertEqual(queued, (LEGS,))
        self.assertEqual(notes, ())
        self.assertTrue(holds[KEY].lifted)

    def test_every_passing_code_is_read(self):
        for code in (37, 38, 39, 60, 61, 78):
            with self.subTest(code=code):
                (queued, _notes), _holds = queue(
                    "InventoryResult %d" % code, minutes_ago=16, tries=6
                )
                self.assertEqual(queued, (LEGS,))


class AnyOtherRefusal(unittest.TestCase):
    def test_items_cannot_be_swapped_waits_thirty_minutes_not_a_day(self):
        (queued, notes), holds = queue("InventoryResult 21", minutes_ago=16)
        self.assertEqual(queued, ())
        self.assertEqual(len(notes), 1)
        self.assertEqual(
            holds[KEY].retry_at, NOW - timedelta(minutes=16) + timedelta(minutes=30)
        )

    def test_a_named_skill_refusal_drops_the_upgrade_with_its_reason(self):
        (queued, notes), holds = queue("EQUIP_ERR_CANT_EQUIP_SKILL 2", minutes_ago=16)
        self.assertEqual(queued, ())
        self.assertIsInstance(holds[KEY], gear.EquipDropped)
        self.assertIn(
            "Durg cannot wear Raider's Legguards: it lacks the skill", notes[0]
        )

    def test_a_code_number_alone_inside_other_words_is_not_read(self):
        (queued, _notes), _holds = queue("not carried 38 times", minutes_ago=16)
        self.assertEqual(queued, ())


if __name__ == "__main__":
    unittest.main()

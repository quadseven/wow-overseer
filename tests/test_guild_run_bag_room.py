"""A guild run starts with room to loot (#1568).

On 2026-10-27 three Deadmines guild runs stalled at the Iron Clad Door: every
member out of combat that knew Opening had full backpack and general bags, so
nobody could loot the Defias Gunpowder. A member with fewer than
guildrun.BAG_ROOM_FREE_SLOTS free general-bag slots is now held out of a run
while the guild jobs pass sends it to a vendor, and the hold is bounded so a
member who cannot make room does not keep the guild out of its dungeons.
"""

import asyncio
import unittest
from unittest import mock

import guildjobs
import guildrun
from test_guildsocial_bridge import _Self, bridge, facts, row
from test_member_income import bonk

MINUTE = 60.0


class TheHoldIsReadFromTheBags(unittest.TestCase):
    def test_a_member_short_of_room_is_held_and_one_with_room_is_not(self):
        held, clock = guildrun.bag_room_holds({"Full": 3, "Roomy": 4}, {}, 1000.0)
        self.assertEqual(held, {"Full"})
        self.assertEqual(clock, {"Full": 1000.0})

    def test_an_unread_or_broken_reading_holds_nobody(self):
        held, clock = guildrun.bag_room_holds(
            {"Unread": None, "Broken": -1, "Odd": "2"}, {}, 1000.0
        )
        self.assertEqual(held, frozenset())
        self.assertEqual(clock, {})


class TheWaitIsBounded(unittest.TestCase):
    def test_a_member_short_past_the_wait_is_free_to_a_run_again(self):
        start = 1000.0
        later = start + guildrun.BAG_ROOM_WAIT_SECONDS - 1
        held, clock = guildrun.bag_room_holds({"Full": 0}, {"Full": start}, later)
        self.assertEqual(held, {"Full"})
        past = start + guildrun.BAG_ROOM_WAIT_SECONDS
        held, clock = guildrun.bag_room_holds({"Full": 0}, clock, past)
        self.assertEqual(held, frozenset(), "no vendor in time: the run goes on")
        self.assertEqual(clock, {"Full": start}, "the clock is kept, not restarted")

    def test_room_made_forgets_the_clock_so_a_new_shortage_waits_again(self):
        _held, clock = guildrun.bag_room_holds({"Full": 10}, {"Full": 0.0}, 5000.0)
        self.assertEqual(clock, {})
        held, _clock = guildrun.bag_room_holds({"Full": 1}, clock, 5000.0)
        self.assertEqual(held, {"Full"})


class ALevellingSeatIsNeverHeldForRoom(unittest.TestCase):
    """The hold was written so a door could be looted (#1568). A raid seat under
    level 60 is there to level, and on 2026-11-15 about 38 of 81 members per
    guild sat in the hold at once while 5 to 12 were free to a group."""

    def test_an_exempt_member_is_neither_held_nor_clocked(self):
        held, clock = guildrun.bag_room_holds(
            {"Seat": 0, "Other": 0}, {}, 1000.0, exempt={"Seat"}
        )
        self.assertEqual(held, {"Other"})
        self.assertEqual(clock, {"Other": 1000.0})

    def test_the_levelling_seats_are_the_approved_seats_under_sixty(self):
        rows = [
            {"name": "SeatLow", "level": 41, "target_tree": "Fury"},
            {"name": "SeatCap", "level": 60, "target_tree": "Fury"},
            {"name": "Guildie", "level": 41, "target_tree": ""},
            {"name": "Unread", "level": None, "target_tree": "Fury"},
        ]
        self.assertEqual(guildrun.levelling_seats(rows), {"SeatLow"})

    def test_a_seat_with_full_bags_answers_a_yes_like_one_with_room(self):
        this = _Self()
        social = social_pass(this, {"Zappy": 0}, seats={"Zappy"})
        self.assertIsNotNone(social.form)
        self.assertIn("Zappy", social.form.composition.names)
        self.assertNotIn("Zappy", this._bag_room_since)

    def test_a_guildie_who_is_not_a_seat_is_still_held(self):
        this = _Self()
        social = social_pass(this, {"Zappy": 0})
        self.assertIsNone(social.form)
        self.assertIn("Zappy", this._bag_room_since)


class TheBagRoomWaitSurvivesARestart(unittest.TestCase):
    def test_the_bridge_keeps_the_wait_in_the_memo_store(self):
        text = open(bridge.__file__, encoding="utf-8").read()
        self.assertRegex(text, r'_bag_room_since[^\n]*=\s*_ClockMemo\(\s*"bag_room"')

    def test_the_memo_round_trips_a_monotonic_start(self):
        self.assertEqual(bridge._bag_wait_from_memo(bridge._bag_wait_memo(50.0, 1000.0), 1000.0), 50.0)
        self.assertEqual(bridge._bag_wait_clock(50.0), 50.0)


class TheBagRoomErrand(unittest.TestCase):
    def test_a_member_short_of_room_is_sent_to_sell(self):
        member = bonk(free_slots=guildrun.BAG_ROOM_FREE_SLOTS - 1, bag_slots=16)
        step = guildjobs._full_bags_first(member, None, (), 600.0)
        self.assertIsNotNone(step)
        self.assertEqual("sell", step.action)

    def test_a_member_with_room_is_not(self):
        member = bonk(free_slots=12, bag_slots=16)
        self.assertIsNone(guildjobs._full_bags_first(member, None, (), 600.0))


def social_pass(this, bag_room, seats=()):
    written = []

    def the_facts(bounds):
        out = facts()
        out["bag_room"] = bag_room
        for r in out["rows"]:
            if r["name"] in seats:
                r["target_tree"] = "Fury"
        return out

    def write(social):
        written.append(social)
        return 41 if social.form else 0

    stubs = {
        "_guild_run_gate": lambda: {"uptime": 99999, "latest": []},
        "_guild_runs_in_flight": lambda: 0,
        "_fetch_guild_social_facts": the_facts,
        "_write_guild_social": write,
        "_guild_social_names": lambda: set(),
    }
    with mock.patch.multiple(bridge, **stubs):
        asyncio.run(bridge.Bridge._guild_social_once(this))
    return written[0]


class TheSocialPassHoldsAFullMember(unittest.TestCase):
    def test_a_yes_from_a_member_with_full_bags_is_not_seated(self):
        this = _Self()
        social = social_pass(this, {"Zappy": 2})
        self.assertIsNone(social.form)
        self.assertEqual(social.withdraw, (3,))
        self.assertIn("Zappy", this._bag_room_since)

    def test_with_room_the_same_ask_becomes_the_run(self):
        social = social_pass(_Self(), {"Zappy": 12})
        self.assertIsNotNone(social.form)
        self.assertIn("Zappy", social.form.composition.names)

    def test_past_the_wait_the_full_member_is_seated_after_all(self):
        this = _Self()
        this._bag_room_since = {
            "Zappy": bridge.time.monotonic() - guildrun.BAG_ROOM_WAIT_SECONDS - MINUTE
        }
        social = social_pass(this, {"Zappy": 2})
        self.assertIsNotNone(social.form)

    def test_a_member_on_its_sale_is_held_for_the_room(self):
        held, lent, needs = bridge._hold_bag_room(
            {"Zappy": "on a guild job", "Locky": "dead"},
            {"Healy"},
            {"Zappy": 1, "Healy": 1, "Auren": 1},
            {"Zappy", "Locky", "Healy"},
        )
        self.assertEqual(held["Zappy"], guildrun.SHORT_OF_BAG_ROOM)
        self.assertEqual(held["Locky"], "dead")
        self.assertEqual(held["Healy"], guildrun.SHORT_OF_BAG_ROOM)
        self.assertEqual(lent, set())
        self.assertEqual(needs, {"Auren": 1})


class TheCoordinatorHoldsAFullMember(unittest.TestCase):
    def test_the_old_picker_skips_a_member_with_full_bags(self):
        this = _Self()
        this._class_owed_by = {}
        this._class_board = None
        seen = []
        the_facts = facts()
        the_facts.update(
            rows=[row("Fullbag", 19, 1), row("Zappy", 19, 8)],
            bag_room={"Fullbag": 0, "Zappy": 20},
        )

        def pools(members, doors):
            seen.extend(m.name for m in members)
            return []

        with (
            mock.patch.multiple(
                bridge,
                _guild_run_gate=lambda: {"uptime": 99999, "latest": []},
                _guild_runs_in_flight=lambda: 0,
                _fetch_guild_run_facts=lambda bounds: the_facts,
            ),
            mock.patch.object(guildrun, "pools", pools),
        ):
            asyncio.run(bridge.Bridge._guild_run_once(this))
        self.assertEqual(seen, ["Zappy"])


class TheBridgeReadsTheBags(unittest.TestCase):
    def test_the_formation_facts_carry_each_members_free_slots(self):
        ran = []

        class Cursor:
            rows = []

            def execute(self, sql, args=()):
                ran.append(sql)
                self.rows = []
                if sql.startswith("SELECT s.name"):
                    self.rows = [{"name": "Zappy"}]
                elif "AS bag_slot" in sql:
                    self.rows = [
                        {
                            "name": "Zappy",
                            "bag_slot": 0,
                            "size": 16,
                            "bag_class": 1,
                            "bag_subclass": 0,
                            "used": 15,
                        },
                    ]

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return {}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Conn:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with mock.patch.object(bridge, "_connect", Conn):
            read = bridge._fetch_guild_run_facts(guildrun.limits({}))
        self.assertEqual(read["bag_room"], {"Zappy": 1})


if __name__ == "__main__":
    unittest.main()

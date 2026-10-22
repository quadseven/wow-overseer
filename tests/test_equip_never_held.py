"""An equip a member cannot put on yet ends in a plain reason, never a hold (#1088).

The review of the first fix read the live bags, 2026-10-21. Bonk (16 of 16
backpack slots, no bag) wanted Rhahk'Zor's Hammer over Fist of Argus and a
Large Round Shield, and carried nothing the make-room ladder may let go of: a
Hearthstone, quest items with no sell price, a recipe, his Skinning Knife and
Mining Pick, and the hammer itself. Cronk's bags were the same shape. So the
make-room step had no step to give, the room note was written on every equip
pass, and it read as "Trying to wear" on the stuck list for as long as the
bags stood: the ticket's finding, back for good. The other gaps it found:

- A settled upgrade was asked again whenever its answer row left the 24 hour
  memory window, and after every restart.
- A piece the world could not find was still held fifteen minutes.
- The silent give-up ("still carries ... after 3 equip command(s); held until
  the memory window passes") was still a 24 hour hold.
- Nothing the tables already say (unique-equipped, a skill rank, Dual Wield)
  kept a doomed equip from being written.
- A quiver's or a soul bag's free slots counted as room for a shield.
- The room step ran ahead of the hearth out of a spot the member cannot leave,
  and a cooling or used-up room step left the member with no step at all.

What is pinned here: every one of those ends in a plain reason that is never
a hold and never a stuck reason, and reopens only on the change that can clear
it (level, skills, what is worn there, or the bags), never on a timer.
"""

import asyncio
import textwrap
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import bag_pressure
import gear
import guildjobs
import nowstatus
from test_classquest import class_plan, who
from test_classquest_room import grey, room_steps
from test_equip_upgrades import EQUIP_READS, _block

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)

HAMMER = gear.Equip(
    holder="Bonk",
    guid=9001,
    entry=5187,
    name="Rhahk'Zor's Hammer",
    slot="two_hand",
    item_level=23,
    worn_level=18,
    reason="a two-hander beats the main hand and shield",
)
KEY = ("Bonk", HAMMER.command)
WORN = {"Bonk": {15: (1, "Fist of Argus"), 16: (2, "Large Round Shield")}}
WEARER = gear.WearerFacts(25, ((44, 125), (54, 120)))


def answer(detail, minutes_ago=2, row_id=41, status="error", key=KEY, equip=HAMMER):
    return {
        key: dict(
            id=row_id,
            target_name=equip.holder,
            command=equip.command,
            status=status,
            detail=detail,
            created_at=NOW - timedelta(minutes=minutes_ago),
        )
    }


def judge(
    equip=HAMMER,
    answers=None,
    free=None,
    holds=None,
    worn=WORN,
    wearers=None,
    items=None,
    tries=None,
    now=NOW,
):
    return gear.equips_to_queue(
        (equip,),
        set(),
        tries or {},
        answers=answers or {},
        worn=worn,
        holds={} if holds is None else holds,
        now=now,
        online={equip.holder},
        free_slots=free,
        wearers=wearers,
        items=items,
    )


def stuck(note):
    return nowstatus.classify("equip: " + note)


class TheBagRoomIsGeneralBagsOnly(unittest.TestCase):
    """A two-hander's displaced shield goes into the backpack or a general
    bag; a quiver, an ammo pouch or a soul bag takes only its own kind."""

    def rows(self, *bags, used=16):
        out = [dict(name="Bonk", bag_slot=0, size=16, bag_class=1, used=used)]
        for slot, (kind, size, used_in) in enumerate(bags, start=19):
            out.append(
                dict(
                    name="Bonk",
                    bag_slot=slot,
                    size=size,
                    bag_class=kind[0],
                    bag_subclass=kind[1],
                    used=used_in,
                )
            )
        return out

    def test_a_free_quiver_slot_is_no_room_for_a_shield(self):
        """The red test: the old count added every worn bag's slots, so six
        free quiver slots read as room and the world refused 21."""
        room = gear.general_bag_room(self.rows(((11, 2), 8, 2)))
        self.assertEqual(room, {"Bonk": (0, 16)})
        queued, notes = judge(free={"Bonk": room["Bonk"][0]})
        self.assertEqual(queued, ())
        self.assertIn("needs 1 free bag slot(s) and it has 0", notes[0])

    def test_a_soul_bag_or_a_herb_bag_is_no_room_either(self):
        for kind in ((1, 1), (1, 2)):
            with self.subTest(kind=kind):
                room = gear.general_bag_room(self.rows((kind, 20, 3)))
                self.assertEqual(room, {"Bonk": (0, 16)})

    def test_a_general_bag_counts_and_so_does_the_backpack(self):
        room = gear.general_bag_room(self.rows(((1, 0), 6, 4), used=15))
        self.assertEqual(room, {"Bonk": (3, 22)})

    def test_a_bag_whose_template_is_unread_adds_nothing(self):
        rows = self.rows(((1, 0), 6, 0))
        rows[1]["bag_class"] = None
        self.assertEqual(gear.general_bag_room(rows), {"Bonk": (0, 16)})

    def test_the_bridge_reads_each_worn_bag_and_only_the_items_in_it(self):
        """Items in a bank bag (bag <> 0 but no worn bag) were counted as used,
        and every worn bag's slots as room."""
        sql = _block("_BAG_ROOM_SQL = (")
        self.assertIn("it.class AS bag_class", sql)
        self.assertIn("it.subclass AS bag_subclass", sql)
        self.assertIn("ci.bag = b.item", sql)
        self.assertNotIn("ci.bag <> 0", sql)
        self.assertIn("bag_pressure.general_bag_room(", _block("def _fetch_bag_room("))


class ASettledUpgradeReopensOnlyOnAChange(unittest.TestCase):
    def settle(self, detail="InventoryResult 67", holds=None, **kw):
        holds = {} if holds is None else holds
        kw.setdefault("wearers", {"Bonk": WEARER})
        queued, notes = judge(answers=answer(detail), holds=holds, **kw)
        self.assertEqual(queued, ())
        self.assertIsInstance(holds[KEY], gear.EquipDropped)
        return holds

    def test_it_outlives_its_answer_rows_memory_window(self):
        """The red test: the answer row left the 24 hour window, the settle
        was deleted with it and the doomed equip written again every day."""
        holds = self.settle()
        later = NOW + timedelta(hours=30)
        queued, notes = judge(holds=holds, wearers={"Bonk": WEARER}, now=later)
        self.assertEqual(queued, ())
        self.assertIn("Bonk cannot wear Rhahk'Zor's Hammer", notes[0])
        self.assertEqual(stuck(notes[0]), [])

    def test_it_reopens_on_a_level_change(self):
        holds = self.settle()
        older = gear.WearerFacts(26, WEARER.skills)
        queued, notes = judge(holds=holds, wearers={"Bonk": older})
        self.assertEqual((queued, notes), ((HAMMER,), ()))

    def test_it_reopens_on_a_skill_change(self):
        holds = self.settle("InventoryResult 8")
        trained = gear.WearerFacts(25, WEARER.skills + ((160, 1),))
        queued, _ = judge(
            answers=answer("InventoryResult 8"), holds=holds, wearers={"Bonk": trained}
        )
        self.assertEqual(queued, (HAMMER,))

    def test_a_final_answer_is_not_reopened_by_the_bags(self):
        holds = self.settle(free={"Bonk": 0})
        queued, _ = judge(
            answers=answer("InventoryResult 67"),
            holds=holds,
            free={"Bonk": 9},
            wearers={"Bonk": WEARER},
        )
        self.assertEqual(queued, ())

    def test_a_reopened_upgrade_is_asked_once_and_the_next_answer_settles_it(self):
        holds = self.settle()
        worn = {"Bonk": {15: (3, "Other Mace"), 16: (2, "Large Round Shield")}}
        kw = dict(holds=holds, worn=worn, wearers={"Bonk": WEARER}, free={"Bonk": 1})
        queued, _ = judge(answers=answer("InventoryResult 67"), **kw)
        self.assertEqual(queued, (HAMMER,))
        queued, notes = judge(answers=answer("InventoryResult 67", row_id=42), **kw)
        self.assertEqual(queued, ())
        self.assertIn("unique", notes[0])

    def test_another_pass_leaves_a_settle_it_did_not_read(self):
        """The family's pass and the guild's share the records: one never
        forgets the other's settled upgrade for want of its facts."""
        holds = self.settle()
        gear.equips_to_queue(
            (), set(), {}, holds=holds, holders={"Zug"}, wearers={"Zug": WEARER}
        )
        self.assertIsInstance(holds[KEY], gear.EquipDropped)

    def test_an_off_hand_answer_reopens_when_the_main_hand_changes(self):
        """13 (an off hand while a two-hander is worn) clears the pass a
        one-hander replaces the two-hander, though the off hand stays empty."""
        buckler = gear.Equip(
            "Bonk", 9002, 2129, "Large Round Buckler", "off_hand", 20, 0, "up"
        )
        key = ("Bonk", buckler.command)
        two_hander = {"Bonk": {15: (5, "Big Club")}}
        holds = {}
        kw = dict(equip=buckler, holds=holds, wearers={"Bonk": WEARER})
        refused = answer("InventoryResult 13", key=key, equip=buckler)
        queued, _ = judge(answers=refused, worn=two_hander, **kw)
        self.assertEqual(queued, ())
        one_hander = {"Bonk": {15: (1, "Fist of Argus")}}
        queued, _ = judge(answers=refused, worn=one_hander, **kw)
        self.assertEqual(queued, (buckler,))


class MySQLError(Exception):
    """Stands in for pymysql.err.MySQLError in the exec'd bridge source."""


def write_pass(current, older=(), free=None, bridge=None):
    """bridge._write_equips for Bonk's hammer, `older` the answers it reads
    once per holder beyond the memory window."""
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
            dict(holder="Bonk", equipment_slot=slot, entry=entry, name=name)
            for slot, (entry, name) in WORN["Bonk"].items()
        ],
        "_fetch_free_slots": lambda _names: dict(free or {"Bonk": 1}),
        "_insert_equip": lambda equip: inserts.append(equip) or True,
        **EQUIP_READS,
        "_equip_last_answers": lambda _names: list(older),
        "_fetch_equip_facts": lambda _names, _entries: (
            [dict(name="Bonk", level=25, skills="44:125,54:120")],
            [],
        ),
    }
    # Compiles a slice of our own bridge.py source, never external input.
    exec(textwrap.dedent(_block("    async def _write_equips(self")), namespace)  # noqa: S102
    bridge = bridge or types.SimpleNamespace(
        _equip_worn={}, _equip_holds={}, _equip_room={}, _equip_answers_read=set()
    )
    asyncio.run(
        namespace["_write_equips"](bridge, (HAMMER,), current, holders={"Bonk"})
    )
    return bridge, inserts


class ARestartKeepsWhatWasSettled(unittest.TestCase):
    def old_refusal(self, detail):
        row = dict(answer(detail)[KEY], recent=False)
        row["created_at"] = datetime.now(timezone.utc) - timedelta(days=3)
        return row

    def test_an_answer_older_than_the_window_settles_it_after_a_restart(self):
        """The red test: a fresh process saw no answer inside 24 hours and
        wrote the doomed equip again."""
        bridge, inserts = write_pass([], older=[self.old_refusal("InventoryResult 67")])
        self.assertEqual(inserts, [])
        self.assertIsInstance(bridge._equip_holds[KEY], gear.EquipDropped)
        self.assertEqual(bridge._equip_answers_read, {"Bonk"})

    def test_with_no_older_answer_the_piece_is_asked(self):
        _bridge, inserts = write_pass([], older=[])
        self.assertEqual(inserts, [HAMMER])

    def test_the_older_answers_are_read_once_per_holder(self):
        body = _block("    async def _write_equips(self")
        self.assertIn("self._equip_answers_read", body)
        sql = _block("def _equip_last_answers(")
        self.assertIn("MAX(id)", sql)
        self.assertIn("o.status IN ('error', 'unchanged')", sql)


class NothingTheTablesRefuseIsAsked(unittest.TestCase):
    """The FINAL answers the world gave were each one doomed command written
    to learn what item_template and the holder's skills already say."""

    def ask(self, equip, item, wearer=WEARER, worn=WORN):
        return judge(
            equip=equip,
            worn=worn,
            wearers={equip.holder: wearer},
            items={int(equip.entry): item},
            free={equip.holder: 5},
        )

    def assert_not_asked(self, equip, item, words, **kw):
        queued, notes = self.ask(equip, item, **kw)
        self.assertEqual(queued, ())
        self.assertIn(words, notes[0])
        self.assertEqual(stuck(notes[0]), [])

    def test_a_unique_piece_one_copy_of_which_is_worn(self):
        band = gear.Equip("Bonk", 9003, 11985, "Viridian Band", "finger", 25, 20, "up")
        worn = {"Bonk": {10: (11985, "Viridian Band"), 11: (4997, "Rock Ring")}}
        self.assert_not_asked(
            band, gear.ItemFacts(max_count=1), "unique-equipped", worn=worn
        )
        flagged = gear.ItemFacts(flags=0x80000)
        self.assert_not_asked(band, flagged, "unique-equipped", worn=worn)
        queued, _ = self.ask(band, gear.ItemFacts(), worn=worn)
        self.assertEqual(queued, (band,))

    def test_a_skill_rank_the_holder_lacks(self):
        goggles = gear.Equip("Bonk", 9004, 10500, "Fire Goggles", "head", 30, 20, "up")
        item = gear.ItemFacts(required_skill=202, required_skill_rank=150)
        self.assert_not_asked(goggles, item, "it needs skill 202 at 150 and has 0")
        skilled = gear.WearerFacts(25, WEARER.skills + ((202, 150),))
        queued, _ = self.ask(goggles, item, wearer=skilled)
        self.assertEqual(queued, (goggles,))

    def test_a_weapon_in_the_off_hand_without_dual_wield(self):
        dagger = gear.Equip(
            "Bonk", 9005, 2632, "Curved Dagger", "off_hand", 20, 0, "up"
        )
        item = gear.ItemFacts(inventory_type=13)
        worn = {"Bonk": {15: (1, "Fist of Argus")}}
        self.assert_not_asked(dagger, item, "it cannot dual wield", worn=worn)
        trained = gear.WearerFacts(25, WEARER.skills + ((118, 1),))
        queued, _ = self.ask(dagger, item, wearer=trained, worn=worn)
        self.assertEqual(queued, (dagger,))

    def test_a_reputation_or_a_level_it_has_not_reached(self):
        self.assert_not_asked(
            HAMMER, gear.ItemFacts(required_reputation=72), "asks a reputation"
        )
        self.assert_not_asked(
            HAMMER, gear.ItemFacts(required_level=30), "it needs level 30 and is 25"
        )

    def test_unread_facts_judge_nothing(self):
        queued, _ = judge(free={"Bonk": 5})
        self.assertEqual(queued, (HAMMER,))

    def test_the_bridge_reads_the_facts_it_judges_by(self):
        body = _block("    async def _write_equips(self")
        self.assertIn("_fetch_equip_facts", body)
        self.assertIn("wearers=", body)
        self.assertIn("items=", body)


class TheSilentGiveUpIsSettledNotHeld(unittest.TestCase):
    def delivered(self, row_id=41):
        return answer("", status="delivered", row_id=row_id)

    def test_three_silent_commands_settle_it_with_a_reason(self):
        """The red test: "held until the memory window passes", a 24 hour
        hold that read as stuck."""
        holds = {}
        queued, notes = judge(
            answers=self.delivered(),
            holds=holds,
            tries={KEY: 3},
            free={"Bonk": 2},
            wearers={"Bonk": WEARER},
        )
        self.assertEqual(queued, ())
        self.assertIn("the world took 3 equip command(s)", notes[0])
        self.assertNotIn("memory window", notes[0])
        self.assertEqual(stuck(notes[0]), [])
        # The rows age out of the window: still settled, no timer reopens it.
        queued, _ = judge(
            holds=holds, tries={}, free={"Bonk": 2}, wearers={"Bonk": WEARER}
        )
        self.assertEqual(queued, ())
        # A slot freed is a change: asked once more.
        queued, _ = judge(
            holds=holds, tries={}, free={"Bonk": 3}, wearers={"Bonk": WEARER}
        )
        self.assertEqual(queued, (HAMMER,))


class ARetryCountsOnlyTheAnswersNobodyNamed(unittest.TestCase):
    def test_passing_refusals_before_an_unknown_answer_do_not_count(self):
        rows = [
            dict(answer("InventoryResult 38", row_id=1)[KEY]),
            dict(answer("InventoryResult 38", row_id=2)[KEY]),
            dict(answer("InventoryResult 99", row_id=3)[KEY]),
        ]
        retries = gear.retry_answers(rows)
        self.assertEqual(retries, {KEY: 1})
        queued, notes = gear.equips_to_queue(
            (HAMMER,),
            set(),
            {KEY: 3},
            answers={KEY: rows[-1]},
            worn=WORN,
            holds={},
            now=NOW,
            free_slots={"Bonk": 1},
            retries=retries,
        )
        self.assertEqual(queued, ())
        self.assertIn("tries again at", notes[0])


ROOM_WORDS = "to put on Rhahk'Zor's Hammer over Fist of Argus and Large Round Shield"


def bonk(**over):
    over.setdefault("free_slots", 0)
    return who("Bonk", **over)


class AFullBackpackAWornShieldAndAWantedTwoHander(unittest.TestCase):
    def test_the_room_is_made_and_the_two_hander_is_put_on(self):
        """The scenario the ticket asks for, one pass after another: on main
        the third refusal parked Bonk for a day."""
        holds = {}
        queued, notes = judge(free={"Bonk": 0}, holds=holds)
        self.assertEqual(queued, ())
        self.assertIn("needs 1 free bag slot(s) and it has 0", notes[0])
        room = gear.equip_room((HAMMER,), WORN, {"Bonk": 0}, holds, now=NOW)
        self.assertEqual(room, {"Bonk": (1, ROOM_WORDS, 0)})
        # On a pass the class quest asks nothing, the guild pass sells the
        # grey for the slot.
        plan = class_plan(
            [bonk(quests_done=frozenset({1505}), carried=(grey(1),))],
            classes=None,
            equip_room=room,
        )
        (step,) = room_steps(plan)
        self.assertEqual([r.command for r in step.rows], ["guid:1"])
        # The slot is free: the hammer is asked the same pass.
        queued, notes = judge(
            free={"Bonk": 1}, holds=holds, now=NOW + timedelta(minutes=12)
        )
        self.assertEqual((queued, notes), ((HAMMER,), ()))
        # The world puts it on: nothing is wanted, nothing is held.
        worn = {"Bonk": {15: (5187, "Rhahk'Zor's Hammer")}}
        queued, notes = gear.equips_to_queue(
            (), set(), {}, worn=worn, holds=holds, holders={"Bonk"}, now=NOW
        )
        self.assertEqual((queued, notes, holds), ((), (), {}))


def bonks_bags():
    """Bonk's bags, read live 2026-10-21: nothing the ladder may let go of."""
    return (
        guildjobs.Carried(1, 6948, item_class=15, name="Hearthstone"),
        guildjobs.Carried(2, 5203, item_class=12, name="Flatland Prowler Claw"),
        guildjobs.Carried(3, 9365, 28, item_class=12, name="Irradiated Crystal Shard"),
        guildjobs.Carried(
            4, 6283, item_class=12, quality=0, name="The Story of Morgan Ladimore"
        ),
        guildjobs.Carried(5, 5508, item_class=9, sell_price=25, name="Recipe"),
        guildjobs.Carried(
            6, 7005, item_class=2, subclass=14, sell_price=16, name="Skinning Knife"
        ),
        guildjobs.Carried(
            7, 2901, item_class=2, subclass=14, sell_price=16, name="Mining Pick"
        ),
        guildjobs.Carried(
            8,
            5187,
            item_class=2,
            subclass=5,
            quality=2,
            sell_price=1300,
            item_level=23,
            required_level=18,
            inventory_type=17,
            name="Rhahk'Zor's Hammer",
        ),
    )


class NothingToPartWith(unittest.TestCase):
    """Bonk, 2026-10-21: the review's live case for a member the make-room
    ladder cannot help."""

    def test_the_guild_pass_has_no_step_and_says_so(self):
        m = bonk(level=25, carried=bonks_bags())
        got = guildjobs.equip_room_step(m, (1, ROOM_WORDS, 0), None, (), 1000.0)
        self.assertEqual(got[0], None)
        self.assertIn("nothing it may sell, mail or destroy", got[2])

    def test_the_upgrade_is_settled_after_thirty_minutes_never_held(self):
        """The red test: on the first fix the room note read as "Trying to
        wear" for as long as the bags stood, days for Bonk and Cronk."""
        holds = {}
        queued, notes = judge(free={"Bonk": 0}, holds=holds)
        self.assertEqual(queued, ())
        # Seen while the room may still be made.
        (step,) = stuck(notes[0])
        self.assertEqual(step.kind, "equip_held")
        later = NOW + timedelta(minutes=gear.ROOM_WAIT_MINUTES)
        queued, notes = judge(free={"Bonk": 0}, holds=holds, now=later)
        self.assertEqual(queued, ())
        self.assertIn("Bonk waits for bag room to wear Rhahk'Zor's Hammer", notes[0])
        self.assertEqual(stuck(notes[0]), [])
        self.assertEqual(gear.world_held((HAMMER,), holds), 0)
        # Days later the bags still stand: still settled, still no stuck reason.
        queued, notes = judge(
            free={"Bonk": 0}, holds=holds, now=later + timedelta(days=4)
        )
        self.assertEqual((queued, stuck(notes[0])), ((), []))
        # A slot frees (a quest turned in): asked at once.
        queued, notes = judge(
            free={"Bonk": 1}, holds=holds, now=later + timedelta(days=4)
        )
        self.assertEqual((queued, notes), ((HAMMER,), ()))

    def test_the_room_stays_asked_for_a_member_busy_while_it_waited(self):
        """Settled is not given up: a member on another walk while its wait ran
        still gets its make-room step when it is free."""
        holds = {}
        judge(free={"Bonk": 0}, holds=holds)
        later = NOW + timedelta(minutes=45)
        judge(free={"Bonk": 0}, holds=holds, now=later)
        room = gear.equip_room((HAMMER,), WORN, {"Bonk": 0}, holds, now=later)
        self.assertEqual(room, {"Bonk": (1, ROOM_WORDS, 45)})


class AFamilyMember(unittest.TestCase):
    """A family member has no guild make-room step: the family's own town run
    makes its room, and the equip pass never holds it meanwhile."""

    def test_a_family_member_at_no_free_slot_is_never_held(self):
        grug = gear.Equip(
            "Grug", 9100, 5187, "Rhahk'Zor's Hammer", "two_hand", 23, 18, "up"
        )
        key = ("Grug", grug.command)
        worn = {"Grug": {15: (1, "Fist of Argus"), 16: (2, "Large Round Shield")}}
        holds = {}
        refused = answer("InventoryResult 21", key=key, equip=grug)
        kw = dict(equip=grug, worn=worn, holds=holds, tries={key: 3})
        queued, notes = judge(answers=refused, free={"Grug": 0}, **kw)
        self.assertEqual(queued, ())
        # At 0 free the family's vendor trip is due: it is the room step.
        self.assertTrue(
            bag_pressure.family_town_run_needed({"Grug": 0}, sellable={"Grug": 4})
        )
        later = NOW + timedelta(minutes=gear.ROOM_WAIT_MINUTES)
        queued, notes = judge(answers=refused, free={"Grug": 0}, now=later, **kw)
        self.assertEqual(queued, ())
        self.assertIn("Grug waits for bag room", notes[0])
        self.assertEqual(stuck(notes[0]), [])
        queued, notes = judge(answers=refused, free={"Grug": 4}, now=later, **kw)
        self.assertEqual((queued, notes), ((grug,), ()))


def room_row(name, age):
    return guildjobs.Recent(name, guildjobs.ROOM_ACTION, age, "applied")


class AKeptPieceThatThenWaitsOnRoom(unittest.TestCase):
    """The bot kept its own piece, then what is worn there changed and the
    upgrade waited on bag room. The keep answer is acted on: it is not read
    as a fresh keep on the next pass, so the room wait stands until the slot
    frees."""

    KEEPS = "the bot keeps Large Round Shield: Rhahk'Zor's Hammer scores 40 against 44"

    def test_the_room_wait_outlives_the_keep_it_replaced(self):
        holds = {}
        keeps = answer(self.KEEPS, status="unchanged")
        queued, notes = judge(answers=keeps, free={"Bonk": 0}, holds=holds)
        self.assertEqual((queued, notes), ((), ()))
        self.assertIsInstance(holds[KEY], gear.BotKeep)
        # A new shield is put on: the keep lifts, and the hammer needs a slot.
        worn = {"Bonk": {15: (1, "Fist of Argus"), 16: (3, "Brackwater Shield")}}
        queued, notes = judge(answers=keeps, free={"Bonk": 0}, holds=holds, worn=worn)
        self.assertEqual(queued, ())
        self.assertIn("leaves Rhahk'Zor's Hammer in its bags", notes[0])
        self.assertIsInstance(holds[KEY], gear.RoomWait)
        # The next pass reads the same keep row: still the room wait, not a
        # new keep that would hide the upgrade with no reason.
        later = NOW + timedelta(minutes=5)
        queued, notes = judge(
            answers=keeps, free={"Bonk": 0}, holds=holds, worn=worn, now=later
        )
        self.assertEqual(queued, ())
        self.assertIn("leaves Rhahk'Zor's Hammer in its bags", notes[0])
        self.assertIsInstance(holds[KEY], gear.RoomWait)
        # A slot frees: the hammer is asked.
        queued, notes = judge(
            answers=keeps, free={"Bonk": 1}, holds=holds, worn=worn, now=later
        )
        self.assertEqual((queued, notes), ((HAMMER,), ()))


class TheWayOutComesFirstAndNoPassIsLost(unittest.TestCase):
    def test_a_member_stood_still_hearths_before_it_makes_room(self):
        m = bonk(quests_done=frozenset({1505}), carried=(grey(1),))
        plan = class_plan(
            [m],
            classes=None,
            equip_room={"Bonk": (1, ROOM_WORDS, 0)},
            still={"Bonk": 70},
        )
        self.assertEqual([s.action for s in plan.steps], ["hearth"])

    def test_a_cooling_room_step_leaves_the_pass_to_the_class_quest(self):
        """The red test: on the first fix a cooling room step returned no step
        at all, so the member idled 20 minutes after each sale."""
        m = bonk(quests_done=frozenset({1505}), carried=(grey(1),))
        plan = class_plan(
            [m], equip_room={"Bonk": (1, ROOM_WORDS, 30)}, recent=(room_row("Bonk", 5),)
        )
        self.assertEqual(room_steps(plan), [])
        self.assertTrue(any(s.action == "classquest" for s in plan.steps))

    def test_three_room_steps_that_freed_nothing_stop_until_the_bags_change(self):
        m = bonk(quests_done=frozenset({1505}), carried=(grey(1),))
        recent = tuple(room_row("Bonk", age) for age in (25, 50, 75))
        plan = class_plan(
            [m],
            classes=None,
            equip_room={"Bonk": (1, ROOM_WORDS, 80)},
            recent=recent,
        )
        self.assertEqual(room_steps(plan), [])
        self.assertTrue(any("made room 3 time(s)" in n for n in plan.notes))
        # The same steps before the bags last changed do not count.
        plan = class_plan(
            [m],
            classes=None,
            equip_room={"Bonk": (1, ROOM_WORDS, 20)},
            recent=recent,
        )
        self.assertEqual(len(room_steps(plan)), 1)

    def test_a_guild_out_of_room_steps_gives_the_rest_their_class_quest(self):
        """The red test: the seventh member's room step was refused by the
        allowance and it took no step at all. With the class quest first,
        every member with one takes it and no room step is spent."""
        names = ["Bonk%s" % c for c in "ABCDEFG"]
        members = [
            who(n, free_slots=0, quests_done=frozenset({1505}), carried=(grey(i + 1),))
            for i, n in enumerate(names)
        ]
        room = {n: (1, ROOM_WORDS, 0) for n in names}
        plan = class_plan(members, equip_room=room)
        self.assertEqual(room_steps(plan), [])
        self.assertTrue(plan.steps)
        self.assertEqual({s.action for s in plan.steps}, {"classquest"})
        # With no class quest, the allowance caps the room steps.
        plan = class_plan(members, classes=None, equip_room=room)
        self.assertEqual(len(room_steps(plan)), guildjobs.ROOM_STEPS_PER_GUILD)


class TheMaterialSaleSellsOnlyTheShortfall(unittest.TestCase):
    def test_one_slot_short_sells_one_stack(self):
        meat = tuple(
            guildjobs.Carried(
                guid=10 + i,
                entry=12223 + i,
                count=1,
                item_class=7,
                subclass=8,
                quality=1,
                sell_price=4 + i,
                name="Meat",
            )
            for i in range(3)
        )
        m = who("Bonk", free_slots=2, carried=meat)
        step, _said, _note = guildjobs.equip_room_step(
            m, (3, ROOM_WORDS, 0), None, (), 1000.0
        )
        self.assertEqual(len(step.rows), 1)


if __name__ == "__main__":
    unittest.main()

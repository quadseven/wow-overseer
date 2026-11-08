"""The item plan shadow's real inputs (#1973): bank room, worn gear, failed reads, quiet log."""

from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import itemplan  # noqa: E402
import itemplan_data  # noqa: E402
import itemplan_reads as reads  # noqa: E402
import itemplan_shadow as shadow  # noqa: E402
from tests.test_itemplan_shadow import Capture, fixture, row  # noqa: E402

ON = {"ITEMPLAN_SHADOW": "on"}


def epic(holder, guid):
    """An unwearable bind-on-pickup epic: its only destination is the bank."""
    r = row(
        holder, guid, 50000 + guid, "Epic %d" % guid, quality=4, sell=0, item_class=4
    )
    g = {
        "holder": holder,
        "item_guid": guid,
        "entry": r["entry"],
        "name": r["name"],
        "quality": 4,
        "sell_price": 0,
        "item_class": 4,
        "item_subclass": 4,
        "bonding": 1,
        "required_level": 50,
        "item_level": 60,
        "level": 54,
    }
    return r, g


def bank_fixture(stacks=11):
    rows, gear = [], []
    for i in range(1, stacks + 1):
        r, g = epic("Zork", i)
        rows.append(r)
        gear.append(g)
    worn = [{"name": "Zork", "class_id": 8, "level": 54}]
    return rows, gear, worn, {"Zork": 30}


def banked(report):
    return [d for d in report.plan.decisions if d.route == itemplan.BANK_PERSONAL]


def read_flags(rows, **kwargs):
    """Mark fixture flags as read and explicitly unbound by the instance."""
    return shadow.Extras(
        instance_soulbound={r["item_guid"]: False for r in rows},
        fire_gear=frozenset(),
        **kwargs,
    )


class BankRoomTest(unittest.TestCase):
    def test_two_free_bank_slots_hold_nothing_and_say_no_room(self):
        rows, gear, worn, free = bank_fixture()
        extras = read_flags(rows, bank_free={"Zork": 2})
        rep = shadow.shadow(
            ["Zork"], "Fam", rows, free, gear_rows=gear, worn_rows=worn, extras=extras
        )
        self.assertEqual(banked(rep), [])
        self.assertEqual(rep.no_room, 11)
        self.assertTrue(all(d.reason.startswith("NO_ROOM") for d in rep.plan.decisions))
        self.assertIn("no room 11", rep.lines[0])

    def test_free_bank_room_caps_the_route_at_what_is_there(self):
        rows, gear, worn, free = bank_fixture()
        extras = read_flags(rows, bank_free={"Zork": 5})
        rep = shadow.shadow(
            ["Zork"], "Fam", rows, free, gear_rows=gear, worn_rows=worn, extras=extras
        )
        self.assertEqual(len(banked(rep)), 3)  # five free, two kept in reserve
        self.assertEqual(rep.no_room, 8)

    def test_free_after_counts_only_the_room_that_exists(self):
        rows, gear, worn, free = bank_fixture()
        for room, moved in ((2, 0), (5, 3)):
            rep = shadow.shadow(
                ["Zork"],
                "Fam",
                rows,
                free,
                gear_rows=gear,
                worn_rows=worn,
                extras=read_flags(rows, bank_free={"Zork": room}),
            )
            m = rep.plan.members[0]
            stacks = shadow.build_stacks(rows, gear)
            self.assertEqual(
                itemplan.free_after(rep.plan, m, stacks),
                itemplan.free_now(m, stacks) + moved,
            )

    def test_without_the_bank_read_the_plan_assumes_an_empty_bank(self):
        rows, gear, worn, free = bank_fixture()
        rep = shadow.shadow(
            ["Zork"],
            "Fam",
            rows,
            free,
            gear_rows=gear,
            worn_rows=worn,
            extras=read_flags(rows),
        )
        self.assertEqual(len(banked(rep)), 11)
        self.assertIn("bank contents", "; ".join(rep.missing))

    def test_guild_room_per_tab_caps_the_guild_route(self):
        full = {("Fam", 0): 0, ("Fam", 1): 0, ("Fam", 2): 0}
        rows, gear, worn, free = fixture()
        for g in gear:
            g["quality"] = 3
        rows[3]["quality"] = 3
        quiet = shadow.shadow(
            ["Ana"],
            "Fam",
            rows,
            free,
            gear_rows=gear,
            worn_rows=worn,
            extras=read_flags(rows, guild_free=full),
        )
        self.assertFalse(
            [d for d in quiet.plan.decisions if d.route == itemplan.GUILD_BANK]
        )


class VerdictTest(unittest.TestCase):
    def extras(self, worn_level):
        return shadow.Extras(
            instance_soulbound={1: False, 2: False, 3: False, 4: False},
            fire_gear=frozenset(),
            worn={
                "Ana": {
                    "back": {
                        "entry": 1,
                        "item_level": worn_level,
                        "item_class": 4,
                        "subclass": 1,
                        "quality": 2,
                        "inventory_type": 16,
                        "req_level": 1,
                    }
                }
            },
            templates={
                7777: {
                    "item_class": 4,
                    "subclass": 4,
                    "bonding": 0,
                    "inventory_type": 16,
                    "item_level": 40,
                    "req_level": 50,
                }
            },
        )

    def cloak(self, extras=None):
        rows, gear, worn, free = fixture()
        rep = shadow.shadow(
            ["Ana"],
            "Fam",
            rows,
            free,
            gear_rows=gear,
            worn_rows=worn,
            extras=extras,
        )
        return next(d for d in rep.plan.decisions if d.entry == 7777), rep

    def test_a_bag_piece_that_beats_the_worn_one_is_kept_not_sold(self):
        d, rep = self.cloak(self.extras(worn_level=20))
        self.assertEqual(d.route, itemplan.KEEP_CARRY)
        self.assertNotIn("equipped gear verdicts", rep.missing)

    def test_without_worn_gear_the_same_piece_is_sold(self):
        d, rep = self.cloak(
            shadow.Extras(
                instance_soulbound={1: False, 2: False, 3: False, 4: False},
                fire_gear=frozenset(),
                templates={
                    7777: {
                        "item_class": 4,
                        "subclass": 4,
                        "bonding": 0,
                        "inventory_type": 16,
                        "item_level": 40,
                        "req_level": 1,
                    }
                },
            )
        )
        self.assertEqual(d.route, itemplan.SELL_VENDOR)
        self.assertIn("equipped gear verdicts", rep.missing)

    def test_a_worse_piece_gets_no_verdict_and_the_plan_decides(self):
        d, _ = self.cloak(self.extras(worn_level=70))
        self.assertEqual(d.route, itemplan.SELL_VENDOR)


class BindingTest(unittest.TestCase):
    def test_template_binding_reaches_non_gear_rows(self):
        rows, gear, worn, free = fixture()
        t = {
            9999: {
                "item_class": 15,
                "subclass": 0,
                "bonding": 1,
                "inventory_type": 0,
                "item_level": 30,
                "req_level": 0,
            }
        }
        stacks = shadow.build_stacks(rows, gear, t)
        trinket = next(s for s in stacks if s.entry == 9999)
        self.assertEqual((trinket.bind, trinket.item_level), (1, 30))
        self.assertFalse(trinket.tradable)
        plain = shadow.build_stacks(rows, gear)
        self.assertIsNone(next(s for s in plain if s.entry == 9999).bind)


class FakeCursor:
    def __init__(self, fail=(), tables=None):
        self.fail, self.tables, self.sql = fail, tables or {}, ""
        self.executed = []

    def execute(self, sql, params=()):
        self.sql = sql
        self.executed.append((sql, params))
        for marker in self.fail:
            if sql.startswith(marker):
                raise RuntimeError("boom")

    def fetchall(self):
        for marker, rows in self.tables.items():
            if self.sql.startswith(marker):
                return rows
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def read_with(cur, bank_rows=None, guild=None, roster=None, connect=None):
    rows, gear, worn, free = fixture()
    return reads.read(
        ["Ana"],
        "Fam",
        rows,
        gear,
        worn,
        connect=connect or (lambda: FakeConn(cur)),
        bank_rows=bank_rows or (lambda names: []),
        guild_setup=guild or (lambda names: None),
        roster=roster or (lambda names: []),
    )


class ReadTest(unittest.TestCase):
    def test_unread_quest_log_keeps_quest_stack(self):
        quest = row(
            "Ana",
            55,
            12345,
            "Quest Item",
            item_class=itemplan.C_QUEST,
            quest_item=False,
        )
        extras = shadow.Extras(
            open_quest_items=None,
            instance_soulbound={55: False},
            templates={
                12345: {
                    "item_class": itemplan.C_QUEST,
                    "subclass": 0,
                    "bonding": 0,
                    "req_level": 1,
                    "item_level": 1,
                    "required_skill_rank": 0,
                    "container_slots": 0,
                    "fire_res": 0,
                    "stats": {},
                }
            },
            fire_gear=frozenset(),
        )
        report = shadow.shadow(
            ["Ana"],
            "Fam",
            [quest],
            {"Ana": 10},
            extras=extras,
        )

        decision = report.plan.decisions[0]
        self.assertEqual(decision.route, itemplan.KEEP_CARRY)
        self.assertIn("quest log was not read", decision.reason)

    def test_a_failed_read_is_named_and_the_plan_still_runs(self):
        extras = read_with(FakeCursor(fail=("SELECT c.name AS member, qs.quest",)))
        self.assertIsNone(extras.open_quest_items)
        self.assertEqual(extras.unread["quest log"], "read failed: RuntimeError")
        rows, gear, worn, free = fixture()
        rep = shadow.shadow(
            ["Ana"], "Fam", rows, free, gear_rows=gear, worn_rows=worn, extras=extras
        )
        self.assertTrue(rep.plan.decisions)
        self.assertIn(
            "quest log [read failed: RuntimeError]",
            rep.missing,
        )

    def test_a_lost_connection_fails_every_cursor_read_and_raises_nothing(self):
        def broken():
            raise OSError("down")

        extras = read_with(None, connect=broken)
        for name in ("quest log", "binding of non-gear rows", "auction prices"):
            self.assertEqual(extras.unread[name], "read failed: OSError")
        self.assertIsNone(extras.templates)

    def test_run_logs_the_failed_read_in_the_tick_line(self):
        rows, gear, worn, free = fixture()
        cap = Capture()

        def reader(*args):
            return read_with(FakeCursor(fail=("SELECT it.entry",)))

        shadow.reset()
        shadow.run(
            ["Ana"],
            "Fam",
            rows,
            free,
            environ=ON,
            logger=cap,
            gear_rows=gear,
            worn_rows=worn,
            reader=reader,
        )
        self.assertIn(
            "binding of non-gear rows [read failed: RuntimeError]", cap.lines[-1]
        )

    def test_a_reader_that_raises_leaves_the_plan_running(self):
        rows, gear, worn, free = fixture()
        cap = Capture()

        def reader(*args):
            raise ValueError("bad")

        shadow.reset()
        out = shadow.run(
            ["Ana"],
            "Fam",
            rows,
            free,
            environ=ON,
            logger=cap,
            gear_rows=gear,
            worn_rows=worn,
            reader=reader,
        )
        self.assertIsNotNone(out)
        self.assertIn("read failed: ValueError", cap.lines[-1])

    def test_bank_free_comes_from_the_bank_pass_rows(self):
        bank_rows = [
            {
                "holder": "Ana",
                "level": 54,
                "bag": 0,
                "slot": 39 + i,
                "item_guid": 100 + i,
                "count": 1,
                "name": "x",
                "quality": 1,
                "sell_price": 1,
                "required_level": 0,
                "bonding": 0,
                "item_class": 15,
                "container_slots": 0,
                "entry": 1,
            }
            for i in range(26)
        ]
        extras = read_with(FakeCursor(), bank_rows=lambda names: bank_rows)
        self.assertEqual(extras.bank_free, {"Ana": 2})
        self.assertNotIn("bank contents", extras.unread)

    def test_guild_room_is_free_slots_per_tab_and_zero_without_deposit_rights(self):
        guild = {
            "purchased_tabs": 2,
            "deposit_rank_ids": [0],
            "member_ranks": {"Ana": 0},
            "tab_items": {0: 98, 1: 10},
        }
        extras = read_with(FakeCursor(), guild=lambda names: guild)
        self.assertEqual(extras.guild_free, {("Fam", 0): 0, ("Fam", 1): 88})
        guild["member_ranks"] = {"Ana": 3}
        extras = read_with(FakeCursor(), guild=lambda names: guild)
        self.assertEqual(extras.guild_free, {("Fam", 0): 0, ("Fam", 1): 0})

    def test_absent_guild_setup_is_reported(self):
        extras = read_with(FakeCursor())
        self.assertIsNone(extras.guild_free)
        self.assertEqual(
            extras.unread["guild bank room"], "no guild bank setup was read"
        )

    def test_quest_and_equipped_rows_flow_through_the_readers(self):
        cur = FakeCursor(
            tables={
                "SELECT c.name AS member, qs.quest": [
                    {"member": "Ana", "quest": 5, "status": 3}
                ],
                "SELECT qt.ID": [{"quest": 5, "item1": 9999, "item_count1": 2}],
                "SELECT c.name AS member, ci.slot": [
                    {
                        "member": "Ana",
                        "slot": 15,
                        "entry": 1,
                        "name": "w",
                        "item_class": 4,
                        "subclass": 1,
                        "quality": 2,
                        "item_level": 20,
                        "inventory_type": 16,
                        "req_level": 1,
                    }
                ],
            }
        )
        extras = read_with(cur)
        self.assertEqual(extras.open_quest_items, {"Ana": frozenset({9999})})
        self.assertIn("Ana", extras.worn)
        self.assertEqual(itemplan_data.worn_entries(extras.worn)["Ana"], {1})

    def test_shadow_read_captures_live_item_facts_and_roster_presence(self):
        rows, gear, worn, free = fixture()
        rows = [next(r for r in rows if r["entry"] == 7777)]
        gear = [next(r for r in gear if r["entry"] == 7777)]
        cur = FakeCursor(
            tables={
                "SELECT it.entry AS entry": [
                    {
                        "entry": 7777,
                        "item_class": 4,
                        "subclass": 4,
                        "bonding": 0,
                        "inventory_type": 4,
                        "item_level": 40,
                        "req_level": 30,
                        "required_skill_rank": 225,
                        "container_slots": 14,
                        "fire_res": 12,
                        "required_disenchant_skill": 75,
                        "stat_type1": 4,
                        "stat_value1": 5,
                        "armor": 80,
                        "block": 0,
                    }
                ],
                "SELECT c.name AS member, ci.slot": [
                    {
                        "member": "Ana",
                        "slot": 0,
                        "entry": 9000,
                        "name": "Iron Helm",
                        "item_class": 4,
                        "subclass": 4,
                        "quality": 2,
                        "item_level": 35,
                        "inventory_type": 1,
                        "req_level": 30,
                        "required_skill_rank": 0,
                        "container_slots": 0,
                        "fire_res": 15,
                        "stat_type1": 4,
                        "stat_value1": 7,
                        "armor": 100,
                        "block": 0,
                    }
                ],
                "SELECT ii.guid AS item_guid": [{"item_guid": 4, "instance_flags": 1}],
                "SELECT race FROM characters": [{"race": 1}],
                "SELECT a.id AS auction_id": [
                    {
                        "auction_id": 17,
                        "house": reads.auction.HOUSE_ALLIANCE,
                        "buyout": 2500,
                        "entry": 7777,
                        "count": 2,
                        "label": "Plain Green Cloak",
                    }
                ],
            }
        )
        roster = [
            SimpleNamespace(
                name="Offline Smith",
                family=False,
                online=False,
                rank_in=lambda skill: (
                    300
                    if skill == reads.itemplan.guildshare.SKILL_LINES["blacksmithing"]
                    else 0
                ),
            ),
            SimpleNamespace(
                name="Online Smith",
                family=False,
                online=True,
                rank_in=lambda skill: (
                    225
                    if skill == reads.itemplan.guildshare.SKILL_LINES["blacksmithing"]
                    else 0
                ),
            ),
        ]
        extras = reads.read(
            ["Ana"],
            "Fam",
            rows,
            gear,
            worn,
            connect=lambda: FakeConn(cur),
            bank_rows=lambda _names: [],
            guild_setup=lambda _names: None,
            roster=lambda _names: roster,
        )

        self.assertEqual(extras.templates[7777]["required_skill_rank"], 225)
        self.assertEqual(extras.templates[7777]["container_slots"], 14)
        self.assertEqual(extras.templates[7777]["fire_res"], 12)
        self.assertEqual(extras.market[7777][0], 1250)
        self.assertEqual(
            extras.worn["Ana"]["head"]["stats"],
            {"strength": 7, "armor": 100, "fire_resistance": 15},
        )
        self.assertEqual(extras.instance_soulbound, {4: True})
        self.assertIn(("Online Smith", "blacksmithing", 225, True), extras.guild_roster)
        self.assertIn(
            ("Offline Smith", "blacksmithing", 300, False), extras.guild_roster
        )
        self.assertEqual(
            extras.guild_crafters, (("Online Smith", "blacksmithing", 225),)
        )
        self.assertTrue(
            all(sql.lstrip().upper().startswith("SELECT") for sql, _ in cur.executed)
        )

    def test_failed_instance_flag_read_keeps_item_untradable(self):
        rows, gear, worn, _free = fixture()
        rows = [rows[-1]]
        gear = [gear[-1]]
        cur = FakeCursor(fail=("SELECT ii.guid AS item_guid",))
        extras = reads.read(
            ["Ana"],
            "Fam",
            rows,
            gear,
            worn,
            connect=lambda: FakeConn(cur),
            bank_rows=lambda _names: [],
            guild_setup=lambda _names: None,
            roster=lambda _names: [
                SimpleNamespace(
                    name="Smith", family=False, online=True, rank_in=lambda _skill: 0
                )
            ],
        )

        self.assertIsNone(extras.instance_soulbound)
        self.assertIn(shadow.INSTANCE_SOULBOUND, extras.unread)
        stack = shadow.build_stacks(
            rows, gear, extras.templates, extras.instance_soulbound
        )[0]
        self.assertIsNone(stack.soulbound)
        self.assertFalse(stack.tradable)

    def test_partial_instance_flag_read_marks_the_input_unread(self):
        rows, gear, worn, _free = fixture()
        rows = [rows[0], rows[-1]]
        cur = FakeCursor(
            tables={
                "SELECT ii.guid AS item_guid": [
                    {"item_guid": rows[0]["item_guid"], "instance_flags": 0}
                ]
            }
        )

        extras = reads.read(
            ["Ana"],
            "Fam",
            rows,
            gear,
            worn,
            connect=lambda: FakeConn(cur),
            bank_rows=lambda _names: [],
            guild_setup=lambda _names: None,
            roster=lambda _names: [],
        )

        self.assertIsNone(extras.instance_soulbound)
        self.assertIn(shadow.INSTANCE_SOULBOUND, extras.unread)

    def test_missing_instance_flags_fail_closed(self):
        rows, gear, worn, _free = fixture()
        rows = [rows[-1]]
        cur = FakeCursor(
            tables={
                "SELECT ii.guid AS item_guid": [{"item_guid": rows[0]["item_guid"]}]
            }
        )

        extras = reads.read(
            ["Ana"],
            "Fam",
            rows,
            gear,
            worn,
            connect=lambda: FakeConn(cur),
            bank_rows=lambda _names: [],
            guild_setup=lambda _names: None,
            roster=lambda _names: [],
        )

        self.assertIsNone(extras.instance_soulbound)
        self.assertIn(shadow.INSTANCE_SOULBOUND, extras.unread)
        stack = shadow.build_stacks(
            rows, gear, extras.templates, extras.instance_soulbound
        )[0]
        self.assertIsNone(stack.soulbound)
        self.assertFalse(stack.tradable)

    def test_missing_template_does_not_claim_fire_resistance_is_known(self):
        rows, gear, worn, _free = fixture()
        cur = FakeCursor()

        extras = reads.read(
            ["Ana"],
            "Fam",
            rows,
            gear,
            worn,
            connect=lambda: FakeConn(cur),
            bank_rows=lambda _names: [],
            guild_setup=lambda _names: None,
            roster=lambda _names: [],
        )

        self.assertIsNone(extras.fire_gear)
        self.assertIn(shadow.FIRE_RESISTANCE, extras.unread)


class QuietLogTest(unittest.TestCase):
    def tick(self, rows, gear, worn, free, cap, state, now):
        return shadow.run(
            ["Ana"],
            "Fam",
            rows,
            free,
            environ=ON,
            logger=cap,
            gear_rows=gear,
            worn_rows=worn,
            state=state,
            clock=lambda: now,
        )

    def test_unchanged_second_tick_is_one_summary_line(self):
        rows, gear, worn, free = fixture()
        state = {}
        first, second = Capture(), Capture()
        self.tick(rows, gear, worn, free, first, state, 0)
        self.tick(rows, gear, worn, free, second, state, 75)
        self.assertGreater(len(first.lines), 2)
        self.assertEqual(len(second.lines), 1)
        self.assertIn("tick:", second.lines[0])
        self.assertIn("detail written for 0 member(s), unchanged 1", second.lines[0])

    def test_a_changed_plan_is_logged_in_full(self):
        rows, gear, worn, free = fixture()
        state = {}
        self.tick(rows, gear, worn, free, Capture(), state, 0)
        rows.append(row("Ana", 20, 1234, "Gray Rag", quality=0, sell=3))
        third = Capture()
        self.tick(rows, gear, worn, free, third, state, 75)
        self.assertTrue(any(" plan Ana" in x for x in third.lines))
        self.assertIn("detail written for 1 member(s)", third.lines[-1])

    def test_unchanged_plan_is_logged_again_after_thirty_minutes(self):
        rows, gear, worn, free = fixture()
        state = {}
        self.tick(rows, gear, worn, free, Capture(), state, 0)
        soon, later = Capture(), Capture()
        self.tick(rows, gear, worn, free, soon, state, shadow.REFRESH_SECONDS - 1)
        self.tick(rows, gear, worn, free, later, state, shadow.REFRESH_SECONDS)
        self.assertEqual(len(soon.lines), 1)
        self.assertGreater(len(later.lines), 1)


class ShapeTest(unittest.TestCase):
    def test_the_bridge_reads_through_the_reader_and_the_switch_stays_off(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        self.assertIn("itemplan_shadow.run(*args, reader=_itemplan_reads", src)
        self.assertFalse(shadow.enabled({}))


if __name__ == "__main__":
    unittest.main()

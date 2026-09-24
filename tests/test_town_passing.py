"""The families check their post and bank on the way past, and a stop is kept (#276).

Measured on the dev realm on 2026-09-24. Grug held 22 letters with 2,609 gold
in them, Zug 6 with 1,042, and the ten members had one item in their personal
banks between them. The mail pass asked only whether the LEADER stood at the
ONE mailbox it aimed at, every ten minutes, so a family that passed a mailbox
never looked in it. And the auction pass claimed urgency for its listing and
bag upgrade walks with no bound at all, taking every other pass's column.

Pinned here on fakes, with the bridge's own functions loaded out of bridge.py:
the quick look writes rows only for a holder standing at a counter, never
claims the column, and runs for every family every minute; every counter
claim tells the slot how far the counter is; the campaign
does not hand back a live stop; and a fruitless urgent auction grant backs
the auction pass's urgency off.
"""

import asyncio
import pathlib
import types
import unittest

from test_family_economy_parity import (  # noqa: F401 - also sets up the pymysql stub
    ALLIANCE,
    FAKE_ASYNCIO,
    HELPERS,
    HORDE,
    _base,
    _load,
    _Log,
)

import townslot  # noqa: E402

BRIDGE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
    encoding="utf-8"
)


class _Take:
    def __init__(self, character, mail_id):
        self.character = character
        self.mail_id = mail_id


MAILRUN = types.SimpleNamespace(
    command=lambda take: "take-money mail:%d" % take.mail_id,
    lines=lambda fresh: ["%s took %d" % (t.character, t.mail_id) for t in fresh],
)


def _at(world):
    """spawn_in_reach, answered by who the world says is standing at a counter."""
    return lambda spawn, where, yards: bool(where) and where.get("at", False)


class TheMailLookWritesOnlyForWhoeverIsAtABox(unittest.TestCase):
    def run_look(self, standing, seen=frozenset()):
        world, log = {"written": []}, _Log()
        ns = _base(world)
        ns.update(
            {
                "log": log,
                "TOWN_COUNTER_YARDS": 8,
                "mailrun": MAILRUN,
                "_fetch_positions": lambda names: {
                    n: {"map_id": 1, "at": n in standing} for n in names
                },
                "_nearest_mailbox": lambda name: {"d2": 1.0, "for": name},
                "_insert_mail": lambda take, command: (
                    world["written"].append((take.character, command)) or 1
                ),
                "travel": types.SimpleNamespace(spawn_in_reach=_at(world)),
            }
        )
        ns = _load(["_mail_in_passing", *HELPERS], ns)
        takes = [_Take("Grug", 1), _Take("Grug", 2), _Take("Ugga", 3), _Take("Og", 4)]
        wrote = asyncio.run(ns["_mail_in_passing"](None, takes, set(seen), HORDE))
        return world, log, wrote

    def test_a_follower_at_a_box_collects_while_the_leader_is_elsewhere(self):
        world, log, wrote = self.run_look({"Ugga"})
        self.assertEqual([("Ugga", "take-money mail:3")], world["written"])
        self.assertEqual({("Ugga", "take-money mail:3")}, wrote)
        self.assertTrue(
            any(
                ln.startswith("mail passing: Ugga at a mailbox - queued 1 take(s)")
                and ln.endswith("for family Zug")
                for ln in log.lines
            ),
            log.lines,
        )

    def test_nobody_at_a_box_writes_nothing_and_says_nothing(self):
        world, log, wrote = self.run_look(set())
        self.assertEqual([], world["written"])
        self.assertEqual(set(), wrote)
        self.assertEqual([], log.lines)

    def test_a_take_already_asked_for_is_not_asked_again(self):
        world, _, wrote = self.run_look({"Grug"}, seen={("Grug", "take-money mail:1")})
        self.assertEqual([("Grug", "take-money mail:2")], world["written"])
        self.assertEqual({("Grug", "take-money mail:2")}, wrote)


class TheBankLookWritesOnlyForWhoeverIsAtABanker(unittest.TestCase):
    def test_only_the_mover_at_a_banker_is_written(self):
        world, log = {"written": []}, _Log()
        move = lambda who: types.SimpleNamespace(character=who)  # noqa: E731
        ns = _base(world)
        ns.update(
            {
                "log": log,
                "GIVE_RETRY_MINUTES": 60,
                "_plan_bank": lambda names: types.SimpleNamespace(
                    moves=[move("Bork"), move("Grog")]
                ),
                "_recent_bank_keys": lambda minutes: set(),
                "bank": types.SimpleNamespace(
                    command=lambda m: "deposit %s" % m.character,
                    lines=lambda fresh: [],
                ),
                "_fetch_town": lambda who: types.SimpleNamespace(banker=who == "Grog"),
                "_insert_bank": lambda m, command: (
                    world["written"].append(command) or 1
                ),
            }
        )
        ns = _load(["_bank_passing_once", "_bank_at_the_counter", *HELPERS], ns)

        class Me:
            _bank_at_the_counter = ns["_bank_at_the_counter"]

        asyncio.run(ns["_bank_passing_once"](Me(), None))
        self.assertEqual(["deposit Grog"], world["written"])
        self.assertTrue(
            any(ln.startswith("bank passing: Grog at a banker") for ln in log.lines),
            log.lines,
        )


class TheVaultLookDepositsOnlyForWhoeverIsAtAVault(unittest.TestCase):
    def test_the_depositor_at_a_vault_is_written_and_nobody_else(self):
        world, log = {"written": []}, _Log()
        ns = _base(world)
        ns.update(
            {
                "log": log,
                "GIVE_RETRY_MINUTES": 60,
                "TOWN_COUNTER_YARDS": 8,
                "_fetch_guild_bank_setup": lambda names: {"purchased_tabs": 1},
                "_fetch_guild_money": lambda names: [
                    {"name": n, "money": 50_000_000, "in_guild": 1} for n in names
                ],
                "guildbank": types.SimpleNamespace(
                    plan_deposits=lambda members, guild_has_tab: [
                        types.SimpleNamespace(name=m["name"], copper=1000)
                        for m in members
                    ]
                ),
                "_fetch_positions": lambda names: {
                    n: {"map_id": 1, "at": n == "Zug"} for n in names
                },
                "_nearest_vault": lambda name: {"d2": 1.0},
                "_recent_guild_bank_keys": lambda minutes: set(),
                "_insert_guild": lambda who, command, source: world["written"].append(
                    (who, command, source)
                ),
                "travel": types.SimpleNamespace(spawn_in_reach=_at(world)),
            }
        )
        ns = _load(["_guild_bank_passing_once", *HELPERS], ns)
        asyncio.run(ns["_guild_bank_passing_once"](object(), HORDE))
        self.assertEqual([("Zug", "bank deposit 1000", "guildbank")], world["written"])
        self.assertTrue(
            any(
                ln.startswith("guild bank passing: Zug at a vault") for ln in log.lines
            ),
            log.lines,
        )


class TheLookRunsForEveryFamilyAndNeverWalks(unittest.TestCase):
    def test_the_loop_is_started_in_both_modes(self):
        gateway = BRIDGE[
            BRIDGE.index("self._loops = {") : BRIDGE.index("async def on_ready(")
        ]
        self.assertIn("self._town_passing_loop,", gateway)
        headless = BRIDGE[
            BRIDGE.index("loops = [") : BRIDGE.index('log.info("headless:')
        ]
        self.assertIn("self._town_passing_loop,", headless)

    def test_each_look_is_guarded_and_every_family_is_served(self):
        world, log = {}, _Log()
        calls = []

        class Me:
            async def _mail_passing_once(self, cohort):
                calls.append(("mail", cohort))
                raise RuntimeError("the mail look broke")

            async def _bank_passing_once(self, cohort):
                calls.append(("bank", cohort))

            async def _guild_bank_passing_once(self, cohort):
                calls.append(("guild bank", cohort))

        ns = _base(world)
        ns["log"] = log
        ns = _load(["_town_passing_once", *HELPERS], ns)
        asyncio.run(ns["_town_passing_once"](Me(), HORDE))
        self.assertEqual(
            [("mail", HORDE), ("bank", HORDE), ("guild bank", HORDE)], calls
        )
        loop = BRIDGE[BRIDGE.index("    async def _town_passing_loop(") :]
        loop = loop[: loop.index("\n    async def ")]
        self.assertIn('self._for_other_families("town passing"', loop)

    def test_no_look_claims_the_travel_column(self):
        for name in (
            "_mail_passing_once",
            "_mail_in_passing",
            "_bank_passing_once",
            "_bank_at_the_counter",
            "_guild_bank_passing_once",
            "_town_passing_once",
        ):
            start = BRIDGE.index("    async def %s(" % name)
            body = BRIDGE[start : BRIDGE.index("\n    async def ", start + 1)]
            self.assertNotIn("_claim_town_slot", body, name)
            self.assertNotIn("_write_trade_errand", body, name)


class EveryCounterClaimSaysHowFar(unittest.TestCase):
    def body(self):
        start = BRIDGE.index("    async def _mail_once(")
        return BRIDGE[start : BRIDGE.index("\n    async def ", start + 1)]

    def test_every_counter_claim_carries_its_distance(self):
        self.assertIn("distance=_spawn_yards(spawn))", self.body())
        start = BRIDGE.index("    async def _guild_bank_once(")
        guild = BRIDGE[start : BRIDGE.index("\n    async def ", start + 1)]
        self.assertIn("distance=_spawn_yards(spawn))", guild)
        start = BRIDGE.index("    async def _settle_bank_errand(")
        bank = BRIDGE[start : BRIDGE.index("\n    async def ", start + 1)]
        self.assertIn("_nearest_banker_yards", bank)


class TheCampaignDoesNotHandBackALiveStop(unittest.TestCase):
    def run_hand_back(self, slot, column):
        world, log = {"released": []}, _Log()
        ns = _base(world)
        ns.update(
            {
                "log": log,
                "time": types.SimpleNamespace(monotonic=lambda: 60.0),
                "_current_travel_npc": lambda leader: column,
                "learnaim": types.SimpleNamespace(TRAINER_ROLE="trainer"),
                "travel": types.SimpleNamespace(
                    is_ground_aim=lambda a: a.startswith("at:")
                ),
                "_release_trade_errand": lambda leader, aim: (
                    world["released"].append(aim) or True
                ),
            }
        )
        ns = _load(["_hand_back_for_campaign"], ns)
        asyncio.run(ns["_hand_back_for_campaign"](object(), slot, "Zug"))
        return world, log

    def test_a_stop_inside_its_window_is_kept(self):
        slot = townslot.Slot(releasable=lambda a: a.startswith("at:"))
        slot.yield_to_campaign("dungeon:ragefire on Zug")
        aim = "at:1:1600,-4400,10"
        taken = slot.want(
            claimant="mail",
            character="Zug",
            aim=aim,
            leader="Zug",
            column="",
            retaskable=("", aim),
            now=0.0,
            distance=40.0,
        )
        slot.settle(taken, True, 0.0)
        world, log = self.run_hand_back(slot, aim)
        self.assertEqual([], world["released"])
        self.assertTrue(
            any("keeps mail's short town stop" in ln for ln in log.lines), log.lines
        )

    def test_any_other_bridge_errand_is_still_handed_back(self):
        slot = townslot.Slot(releasable=lambda a: a.startswith("at:"))
        aim = "at:1:1600,-4400,10"
        slot.settle(
            slot.want(
                claimant="clearance",
                character="Zug",
                aim=aim,
                leader="Zug",
                column="",
                retaskable=("", aim),
                now=0.0,
            ),
            True,
            0.0,
        )
        slot.yield_to_campaign("dungeon:ragefire on Zug")
        world, _ = self.run_hand_back(slot, aim)
        self.assertEqual([aim], world["released"])


class AFruitlessUrgentAuctionGrantBacksOff(unittest.TestCase):
    def test_the_grant_is_recorded_and_said(self):
        world, log = {}, _Log()
        slot = townslot.Slot()
        ns = _base(world)
        ns.update({"log": log, "time": types.SimpleNamespace(monotonic=lambda: 100.0)})
        ns = _load(["_auction_urgency_spent", *HELPERS], ns)

        class Me:
            def _cohort_town_slot(self, key):
                world["slot_for"] = key
                return slot

        ns["_auction_urgency_spent"](Me(), HORDE, "list", False)
        self.assertEqual(0.0, slot.urgency_suppressed_until("auction"))
        self.assertEqual([], log.lines)
        ns["_auction_urgency_spent"](Me(), HORDE, "list", True)
        self.assertEqual("Zug", world["slot_for"])
        self.assertGreater(slot.urgency_suppressed_until("auction"), 100.0)
        self.assertTrue(
            any(
                ln.startswith(
                    "auction: took the travel column on bag pressure for a "
                    "list walk and wrote nothing yet"
                )
                for ln in log.lines
            ),
            log.lines,
        )

    def test_both_urgent_walks_report_and_a_listing_or_a_bag_clears_it(self):
        for name, spent, cleared in (
            (
                "_auction_sales_once",
                '_auction_urgency_spent(cohort, "list", pressure)',
                'productive("auction")',
            ),
            (
                "_auction_bag_upgrades",
                '_auction_urgency_spent(cohort, "bag upgrade", aimed and pressure)',
                'productive("auction")',
            ),
        ):
            start = BRIDGE.index("    async def %s(" % name)
            body = BRIDGE[start : BRIDGE.index("\n    async def ", start + 1)]
            self.assertIn(spent, body, name)
            self.assertIn(cleared, body, name)


if __name__ == "__main__":
    unittest.main()

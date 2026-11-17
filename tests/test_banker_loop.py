"""The guild bankers' own loop (#2660, slice 4).

A banker stays in its guild's vault city, opens its post, banks what the item
plan banks and sells true junk only. These tests drive the real seams: the
facts the bridge builds, `bankerloop` for where a banker stands, and
`guildjobs.plan` for the step it is given.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest import mock

import bankerloop
import guildjobs
import seatbags
from test_guildjobs import member, only_step, plan
from test_guildsocial_bridge import bridge

NAME = "Hoarg"
IRONFORGE = 1537
VAULT = guildjobs.Spot(
    kind="gameobject", spawn=900, map_id=0, x=-4900.0, y=-1100.0, name="Guild Vault"
)


def banker(**over):
    base = dict(
        role=guildjobs.BANKER,
        level=1,
        class_id=5,
        race=3,
        map_id=0,
        x=-4900.0,
        y=-1100.0,
        zone_id=IRONFORGE,
        free_slots=3,
        vault=VAULT,
    )
    base.update(over)
    return member(NAME, **base)


def carried(guid, quality, name="stack"):
    return guildjobs.Carried(
        guid=guid, entry=1000 + guid, count=1, quality=quality, sell_price=10, name=name
    )


def step_of(m, **kw):
    return only_step(plan([m], **kw), NAME)


class WhereABankerStands(unittest.TestCase):
    def test_beside_the_vault_in_the_city_is_home(self):
        self.assertTrue(bankerloop.at_home(banker()))

    def test_another_zone_is_not_home(self):
        self.assertFalse(bankerloop.at_home(banker(zone_id=12)))

    def test_far_from_the_vault_in_the_city_is_not_home(self):
        far = banker(x=VAULT.x + bankerloop.STAY_YARDS + 50)
        self.assertFalse(bankerloop.at_home(far))

    def test_an_unread_position_is_never_home(self):
        self.assertFalse(bankerloop.at_home(banker(x=None)))
        self.assertFalse(bankerloop.at_home(banker(zone_id=None)))

    def test_each_guild_has_its_own_city(self):
        self.assertNotEqual(
            bankerloop.city_zone("Cave"), bankerloop.city_zone("Bonkers")
        )
        self.assertEqual(bankerloop.city_zone("Nobody"), 0)

    def test_only_grey_stacks_are_junk(self):
        stacks = [carried(1, 0), carried(2, 1), carried(3, 2)]
        self.assertEqual([c.guid for c in bankerloop.junk_only(stacks)], [1])

    def test_the_vault_chosen_is_the_one_in_the_guilds_city_map(self):
        elsewhere = replace(VAULT, spawn=901, map_id=1)
        got = bankerloop.attach_vaults([banker(vault=None)], [elsewhere, VAULT])
        self.assertEqual(got[0].vault, VAULT)

    def test_attaching_leaves_everyone_else_alone(self):
        other = member("Grug", role=guildjobs.RAIDER)
        self.assertEqual(bankerloop.attach_vaults([other], [VAULT]), [other])


class WhatABankerDoes(unittest.TestCase):
    def test_a_banker_away_from_its_vault_walks_back(self):
        step = step_of(banker(x=VAULT.x + 600))
        self.assertEqual(step.action, bankerloop.ACTION)
        self.assertIn("walk-to-spawn gameobject:900", step.rows[0].command)

    def test_a_banker_on_another_map_hearths(self):
        step = step_of(banker(map_id=530, zone_id=3430))
        self.assertEqual(step.action, "hearth")

    def test_a_banker_with_no_known_vault_hearths_when_away(self):
        step = step_of(banker(zone_id=12, vault=None))
        self.assertEqual(step.action, "hearth")

    def test_a_walk_home_is_not_asked_again_inside_the_cooldown(self):
        recent = guildjobs.Recent(
            name=NAME, action=bankerloop.ACTION, age_minutes=2, status="pending"
        )
        self.assertIsNone(step_of(banker(x=VAULT.x + 600), recent=(recent,)))

    def test_a_banker_at_home_opens_its_post(self):
        step = step_of(banker(), mail={NAME: ("take mail:1",)})
        self.assertEqual(step.action, "collect")
        self.assertEqual([r.command for r in step.rows], ["take mail:1"])

    def test_a_banker_at_home_with_nothing_to_do_gets_no_step(self):
        self.assertIsNone(step_of(banker()))

    def test_a_banker_sells_grey_stacks_only_and_never_destroys(self):
        m = banker(
            plan_sales=(carried(1, 0, "Grey Fang"), carried(2, 1, "White Cloth")),
            plan_destroy=(carried(3, 0, "Doomed"),),
        )
        step = step_of(m)
        self.assertEqual(step.action, guildjobs.SEAT_SELL_ACTION)
        sold = " ".join(r.command for r in step.rows)
        self.assertIn("guid:1", sold)
        self.assertNotIn("guid:2", sold)
        self.assertNotIn("guid:3", sold)

    def test_a_banker_with_only_white_sales_banks_instead_of_selling(self):
        m = banker(
            plan_sales=(carried(2, 1, "White Cloth"),),
            plan_bank=(carried(4, 1, "Stock"),),
            banker=guildjobs.Spot(
                kind="creature",
                spawn=777,
                map_id=0,
                x=-4890.0,
                y=-1100.0,
                name="Banker",
            ),
        )
        step = step_of(m)
        self.assertEqual(step.action, guildjobs.SEAT_BANK_ACTION)

    def test_an_offline_or_fighting_banker_is_left_alone(self):
        for over in ({"online": False}, {"in_combat": True}, {"alive": False}):
            self.assertIsNone(step_of(banker(**over)), over)

    def test_a_banker_gets_no_class_or_level_step(self):
        steps = plan([banker(level=1)]).steps
        self.assertEqual(list(steps), [])


class TheBridgeFacts(unittest.TestCase):
    def rows(self):
        return [
            {
                "name": NAME,
                "guid": 9,
                "guild_name": "Cave",
                "level": 1,
                "class_id": 5,
                "race": 3,
                "online": 1,
                "map_id": 0,
                "zone_id": IRONFORGE,
                "pos_x": -4900.0,
                "pos_y": -1100.0,
                "group_leader": 0,
            }
        ]

    def test_a_banker_is_a_member_of_role_banker_and_not_a_class_candidate(self):
        facts = bridge._job_facts_from_rows(self.rows(), [], {NAME}, [], [], [], [], [])
        self.assertEqual([m.name for m in facts["members"]], [NAME])
        self.assertEqual(facts["members"][0].role, guildjobs.BANKER)
        self.assertEqual(facts["class_candidates"], [])

    def test_a_banker_needs_the_seat_loop_plan_when_short_of_room(self):
        self.assertTrue(seatbags.needs_plan(banker(free_slots=2)))
        self.assertFalse(seatbags.needs_plan(banker(online=False)))


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=()):
        self.log.append((sql, params))

    def fetchall(self):
        return [
            {"spawn": 900, "map_id": 0, "x": -4900.0, "y": -1100.0, "name": "Vault"},
            {"spawn": 901, "map_id": 1, "x": 1.0, "y": 1.0, "name": "Other Vault"},
        ]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return FakeCursor(self.log)


class TheBridgeVaultRead(unittest.TestCase):
    def setUp(self):
        self.sql = []
        patch = mock.patch.object(bridge, "_connect", lambda: FakeConn(self.sql))
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_vault_is_read_and_put_on_the_banker(self):
        (m,) = bridge._banker_vaults([banker(vault=None)])
        self.assertEqual(m.vault.spawn, 900)
        self.assertEqual(m.vault.kind, "gameobject")
        self.assertEqual(self.sql[0][1][0], bridge._GUILD_BANK_GO_TYPE)

    def test_no_banker_means_no_read(self):
        other = member("Grug", role=guildjobs.RAIDER)
        self.assertEqual(bridge._banker_vaults([other]), [other])
        self.assertEqual(self.sql, [])

    def test_a_failed_read_leaves_the_banker_as_it_was(self):
        class Boom:
            def __enter__(self):
                raise OSError("down")

            def __exit__(self, *args):
                return False

        with mock.patch.object(bridge, "_connect", lambda: Boom()):
            (m,) = bridge._banker_vaults([banker(vault=None)])
        self.assertIsNone(m.vault)

    def test_the_guild_job_pass_reads_the_vaults_before_the_plan(self):
        import pathlib

        text = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        start = text.index("async def _start_guild_job_pass")
        end = text.index("plan = await self._plan_guild_jobs", start)
        self.assertIn("_banker_vaults", text[start:end])


if __name__ == "__main__":
    unittest.main()

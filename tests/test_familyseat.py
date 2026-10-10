"""A family's tank and healer take guild-run seats while their family is idle (#784).

The operator, 2026-10-10: yes, a family's tank and healer may take guild-run
seats while their own family has no campaign run going; never pulled from a
family campaign or a run in progress, and a family campaign about to start
takes them back. These pin familyseat.py, the social layer's seating of a lent
family member, and the bridge's half: the read, the release and the queue's
hold.
"""

import asyncio
import inspect
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import familyseat as fs  # noqa: E402
import guildrun  # noqa: E402
import guildsocial as gs  # noqa: E402
from test_campaign_queue import FakeWorld, _q, _queue_pass  # noqa: E402
from test_guildsocial import (  # noqa: E402
    HOLY,
    MAGE,
    PRIEST,
    PROTECTION,
    ROGUE,
    WARLOCK,
    WARRIOR,
    ask,
    mate,
    plan,
    yes,
)
from test_guildsocial_bridge import _Self, bridge, facts, row  # noqa: E402

# The Deadmines' bosses stand at 20 (guildrun.carries, #721).
BOSS_DOORS = guildrun.doors(None, {36: 20})


def roster(*rows):
    return [{"name": n, "family": f, "job": j} for n, f, j in rows]


GRUG_IDLE = roster(
    ("Grug", "Grug", "quest"), ("Ugga", "Grug", "quest"), ("Og", "Grug", "craft")
)
ZUG_RUNNING = roster(
    ("Zug", "Zug", "dungeon:shadowfang"), ("Uzza", "Zug", "dungeon:shadowfang")
)


class WhoIsLendable(unittest.TestCase):
    def test_every_member_of_an_idle_family(self):
        self.assertEqual(fs.lendable(GRUG_IDLE + ZUG_RUNNING, set()), {"Ugga", "Og"})

    def test_never_the_head_whom_its_family_follows(self):
        self.assertNotIn("Grug", fs.lendable(GRUG_IDLE, set()))

    def test_never_a_family_on_a_campaign_job(self):
        for job in ("dungeon", "dungeon:deadmines", "raid:molten-core", "town run"):
            with self.subTest(job):
                rows = roster(("Grug", "Grug", job), ("Ugga", "Grug", "quest"))
                self.assertEqual(fs.lendable(rows, set()), set())

    def test_never_a_family_with_a_member_inside_a_dungeon(self):
        self.assertEqual(fs.lendable(GRUG_IDLE, {"Og"}), set())

    def test_a_member_inside_with_a_guild_run_does_not_stop_its_family(self):
        self.assertEqual(
            fs.lendable(GRUG_IDLE, {"Ugga"}, in_runs={"Ugga"}), {"Ugga", "Og"}
        )

    def test_inside_reads_the_members_off_the_open_world(self):
        rows = [
            {"name": "Ugga", "level": 39, "class_id": PRIEST, "map_id": 36},
            {"name": "Grug", "level": 43, "class_id": WARRIOR, "map_id": 0},
        ]
        self.assertEqual(fs.inside(rows), {"Ugga"})

    def test_off_says_so(self):
        self.assertFalse(fs.enabled({fs.ENV_SWITCH: "off"}))
        self.assertTrue(fs.enabled({}))


def ugga(level=24, **kw):
    """A family's Holy priest, in its family's group."""
    kw.setdefault("talent_spells", HOLY)
    kw.setdefault("group_leader", 1062)
    return mate("Ugga", level, PRIEST, **kw)


class TheRelease(unittest.TestCase):
    def test_a_lendable_family_member_in_its_family_group_is_lent(self):
        held = {"Ugga": guildrun.FAMILY_MEMBER}
        out, lent = fs.release(held, [ugga()], {"Ugga"}, set(), set())
        self.assertEqual((out, lent), ({}, {"Ugga"}))

    def test_one_held_for_anything_else_keeps_that_reason(self):
        held = {"Ugga": guildrun.FAMILY_MEMBER}
        out, lent = fs.release(held, [ugga(in_combat=1)], {"Ugga"}, set(), set())
        self.assertEqual((out, lent), ({"Ugga": "in combat"}, set()))
        out, lent = fs.release(held, [ugga()], {"Ugga"}, {"Ugga"}, set())
        self.assertEqual((out, lent), ({"Ugga": "in a guild run"}, set()))

    def test_a_family_with_a_campaign_lends_nobody(self):
        held = {"Ugga": guildrun.FAMILY_MEMBER}
        out, lent = fs.release(held, [ugga()], set(), set(), set())
        self.assertEqual((out, lent), (held, set()))


def four():
    """An asker, a tank and two damage dealers who said yes; no guild healer."""
    return [
        mate("Auren", 20, ROGUE),
        mate("Tanky", 21, WARRIOR, talent_spells=PROTECTION, has_shield=1),
        mate("Zappy", 19, MAGE),
        mate("Locky", 20, WARLOCK),
    ]


def four_yeses():
    return [
        yes(1, 7, "Tanky", "tank"),
        yes(3, 7, "Zappy", "dps"),
        yes(4, 7, "Locky", "dps"),
    ]


class TheSocialLayerSeatsALentMember(unittest.TestCase):
    def test_a_lent_healer_answers_for_the_healer_seat(self):
        out = plan(
            four() + [ugga()],
            asks=[ask(7, "Auren")],
            answers=four_yeses(),
            lent={"Ugga"},
        )
        self.assertEqual(
            [(r.member, r.role) for r in out.replies], [("Ugga", "healer")]
        )

    def test_without_the_loan_a_family_member_says_nothing(self):
        out = plan(
            four() + [ugga()],
            asks=[ask(7, "Auren")],
            answers=four_yeses(),
            held={"Ugga": guildrun.FAMILY_MEMBER},
        )
        self.assertEqual(out.replies, ())

    def test_a_lent_member_never_takes_a_damage_seat(self):
        answers = [
            yes(1, 7, "Tanky", "tank"),
            yes(2, 7, "Healy", "healer"),
            yes(3, 7, "Zappy", "dps"),
        ]
        mates = four()[:3] + [mate("Healy", 20, PRIEST, talent_spells=HOLY), ugga()]
        out = plan(mates, asks=[ask(7, "Auren")], answers=answers, lent={"Ugga"})
        self.assertNotIn("Ugga", [r.member for r in out.replies])

    def test_a_lent_member_never_asks(self):
        need = gs.Need(
            member="Ugga",
            keyword="deadmines",
            item="Cape",
            entry=5193,
            gain=12.0,
            slot="cloak",
        )
        out = plan([ugga()], needs={"Ugga": [need]}, lent={"Ugga"})
        self.assertEqual(out.posts, ())

    def test_under_the_bosses_level_a_lent_healer_does_not_answer(self):
        out = gs.plan_pass(
            four() + [ugga(level=19)],
            {},
            [ask(7, "Auren")],
            four_yeses(),
            {},
            BOSS_DOORS,
            {},
            ask(7, "Auren").created_at,
            room=2,
            can_form=True,
            lent={"Ugga"},
        )
        self.assertEqual(out.replies, ())

    def test_the_group_forms_with_the_lent_healer(self):
        answers = four_yeses() + [yes(9, 7, "Ugga", "healer")]
        out = plan(
            four() + [ugga()], asks=[ask(7, "Auren")], answers=answers, lent={"Ugga"}
        )
        self.assertIsNotNone(out.form)
        self.assertEqual(out.form.composition.healer.name, "Ugga")
        self.assertEqual(out.form.pugs, ())


def short_a_healer(lendable):
    """The bridge's facts: Auren's Deadmines ask with a tank and two damage
    dealers, no guild healer free, and Ugga of Grug's family in its family's
    group."""
    out = facts()
    out["rows"] = [r for r in out["rows"] if r["name"] != "Healy"] + [
        row("Ugga", 24, PRIEST, talent_spells=HOLY, group_leader=1062)
    ]
    out["answers"] = [a for a in out["answers"] if a.member != "Healy"]
    out["family"] = {"Ugga", "Grug"}
    out["lendable"] = set(lendable)
    return out


class TheBridgeHalf(unittest.TestCase):
    def social_once(self, lendable):
        written = []
        stubs = {
            "_guild_run_gate": lambda: {"uptime": 99999, "latest": []},
            "_guild_runs_in_flight": lambda: 0,
            "_fetch_guild_social_facts": lambda bounds: short_a_healer(lendable),
            "_write_guild_social": lambda social: written.append(social) or 0,
            "_guild_social_names": lambda: set(),
        }
        with (
            mock.patch.multiple(bridge, **stubs),
            mock.patch.dict(bridge.os.environ, {"GUILD_PUGS": "off"}),
        ):
            asyncio.run(bridge.Bridge._guild_social_once(_Self()))
        return [(r.member, r.role) for r in written[0].replies]

    def test_an_idle_familys_healer_answers_the_guild_ask(self):
        self.assertIn(("Ugga", "healer"), self.social_once({"Ugga", "Grug"}))

    def test_a_family_with_a_campaign_lends_nobody(self):
        self.assertNotIn("Ugga", [m for m, _r in self.social_once(set())])

    def test_the_facts_read_who_is_lendable(self):
        body = inspect.getsource(bridge._fetch_guild_social_facts)
        self.assertIn("familyseat.ROSTER_SQL", body)
        self.assertIn('"lendable": lendable', body)

    def test_the_queue_waits_for_a_member_out_in_a_guild_run(self):
        this = types.SimpleNamespace()
        fam = {"names": ["Grug", "Ugga", "Og"]}
        with mock.patch.object(
            bridge, "_guild_run_members_out", lambda: {"Ugga", "Mok"}
        ):
            held = asyncio.run(bridge.Bridge._family_lent_hold(this, "Grug", fam))
        self.assertTrue(held)
        with mock.patch.object(bridge, "_guild_run_members_out", lambda: {"Mok"}):
            held = asyncio.run(bridge.Bridge._family_lent_hold(this, "Grug", fam))
        self.assertFalse(held)

    def test_off_the_queue_holds_nobody(self):
        this = types.SimpleNamespace()
        fam = {"names": ["Ugga"]}
        with (
            mock.patch.dict(bridge.os.environ, {fs.ENV_SWITCH: "off"}),
            mock.patch.object(bridge, "_guild_run_members_out", lambda: {"Ugga"}),
        ):
            held = asyncio.run(bridge.Bridge._family_lent_hold(this, "Grug", fam))
        self.assertFalse(held)

    def test_the_hold_comes_before_the_step(self):
        body = inspect.getsource(bridge.Bridge._campaign_queue_family_once)
        self.assertLess(
            body.index('"_family_lent_hold"'), body.index("campaignqueue.step(")
        )


def lent_hold(answer):
    async def hold(key, fam):
        return answer

    return hold


class TheQueueStepWaits(unittest.TestCase):
    def test_a_held_family_is_not_sent_into_its_campaign(self):
        world = FakeWorld([_q(1, "ragefire", 50, "queued", 0)])
        _queue_pass(world, _family_lent_hold=lent_hold(True))
        self.assertNotEqual("dungeon:ragefire", world.row("Zug")["job"])

    def test_an_unheld_family_starts_it(self):
        world = FakeWorld([_q(1, "ragefire", 50, "queued", 0)])
        _queue_pass(world, _family_lent_hold=lent_hold(False))
        self.assertEqual("dungeon:ragefire", world.row("Zug")["job"])


if __name__ == "__main__":
    unittest.main()

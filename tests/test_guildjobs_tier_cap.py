"""A guild member at a profession tier cap visits its trainer first (#1116).

Measured on the dev realm on 2026-10-18: fifteen guild members stood at
exactly 75/75 in a gathering trade, each with the level and (all but one) the
purse for Journeyman. Raiders of a guild with no craft focus never reach a
train step at all (their job is the post and the sale), and the rest reach
it only as the last rung, behind PvP, the post and the level walk, so a trade
at its ceiling waited behind every one of them. A trade at its ceiling gains
nothing until the rank is bought, so the rank walk now comes ahead of those
rungs, for every role, while the member is not held in a battleground.

Pure unit tests against guildjobs.plan.
"""

import unittest

import guildjobs
import pvpgear

H, M, S = guildjobs.HERBALISM, guildjobs.MINING, guildjobs.SKINNING
FA = guildjobs.FIRST_AID
ROGUE = 4


def member(name="Funkymon", role=guildjobs.RAIDER, **over):
    base = dict(
        name=name,
        guild="Bonkers",
        role=role,
        level=30,
        class_id=ROGUE,
        race=2,
        online=True,
        map_id=1,
        x=0.0,
        y=0.0,
        money=10903,
        eligible=True,
        skills={H: (75, 75), S: (75, 75), FA: (40, 75)},
    )
    base.update(over)
    return guildjobs.Member(**base)


def aim(name="Funkymon"):
    return pvpgear.Aim(name, "Bonkers", 30, 19325, "Outrider's Bow", 400, 0, pvpgear.AV)


def train_steps(result, name):
    return [s for s in result.steps if s.holder == name and s.action == "train"]


class AMemberAtATierCap(unittest.TestCase):
    def test_a_raider_with_no_craft_focus_walks_to_its_trainer(self):
        result = guildjobs.plan([member()])
        (step,) = train_steps(result, "Funkymon")
        self.assertIn(step.key, (H, S))
        self.assertIn("walk-to-trainer skill:%d" % step.key, step.rows[0].command)
        self.assertIn("up to 150", step.said)

    def test_each_tier_cap_buys_the_rank_above_it(self):
        for value, level, want in ((75, 10, 150), (150, 20, 225), (225, 35, 300)):
            with self.subTest(cap=value):
                m = member(level=level, money=60000, skills={M: (value, value)})
                (step,) = train_steps(guildjobs.plan([m]), "Funkymon")
                self.assertEqual(M, step.key)
                self.assertIn("up to %d" % want, step.said)

    def test_a_summoner_at_its_cap_trains_too(self):
        m = member(role=guildjobs.SUMMONER, class_id=9)
        self.assertEqual(1, len(train_steps(guildjobs.plan([m]), "Funkymon")))

    def test_a_summoner_a_summon_waits_on_stays_at_its_door(self):
        m = member(role=guildjobs.SUMMONER, class_id=9)
        result = guildjobs.plan([m], pending=("Funkymon",))
        self.assertEqual([], train_steps(result, "Funkymon"))

    def test_the_rank_walk_comes_before_a_pvp_buy(self):
        m = member(role=guildjobs.MAINTENANCE, skills={M: (75, 75), S: (75, 75)})
        a = aim()
        pvp = {"Funkymon": (a, pvpgear.Move(pvpgear.BUY, ""))}
        result = guildjobs.plan([m], pvp=pvp)
        self.assertEqual(1, len(train_steps(result, "Funkymon")))
        self.assertFalse(any(s.action == "pvp" for s in result.steps))

    def test_a_member_inside_a_battleground_stays_held(self):
        pvp = {"Funkymon": (aim(), pvpgear.Move(pvpgear.INSIDE, "plays"))}
        result = guildjobs.plan([member()], pvp=pvp)
        self.assertEqual((), result.steps)

    def test_a_trade_short_of_its_cap_keeps_its_old_place(self):
        # 72 of 75 is within RANK_UP_MARGIN, so the ordinary job buys it; the
        # PvP buy still comes first, as before.
        m = member(role=guildjobs.MAINTENANCE, skills={M: (72, 75), FA: (40, 75)})
        pvp = {"Funkymon": (aim(), pvpgear.Move(pvpgear.BUY, ""))}
        result = guildjobs.plan([m], pvp=pvp)
        self.assertEqual([], train_steps(result, "Funkymon"))
        self.assertTrue(any(s.action == "pvp" for s in result.steps))

    def test_the_top_rank_is_never_asked_for(self):
        m = member(level=60, money=900000, skills={H: (300, 300)})
        self.assertEqual([], train_steps(guildjobs.plan([m]), "Funkymon"))

    def test_a_short_purse_saves_and_says_so(self):
        result = guildjobs.plan([member(money=399)])
        self.assertEqual([], train_steps(result, "Funkymon"))
        self.assertTrue(any("saves for" in n for n in result.notes), result.notes)

    def test_a_maintenance_member_says_its_purse_note_once(self):
        m = member(role=guildjobs.MAINTENANCE, money=399, skills={H: (75, 75)})
        (note,) = [n for n in guildjobs.plan([m]).notes if "saves for" in n]
        self.assertEqual(1, note.count("saves for"), note)

    def test_a_failed_walk_cools_down_and_the_member_does_its_job(self):
        failed = tuple(
            guildjobs.Recent("Funkymon", "train", 5, "error", skill) for skill in (H, S)
        )
        result = guildjobs.plan([member()], recent=failed)
        self.assertEqual([], train_steps(result, "Funkymon"))

    def test_a_member_not_yet_natural_spends_nothing(self):
        result = guildjobs.plan([member(eligible=False)])
        self.assertEqual([], train_steps(result, "Funkymon"))

    def test_the_family_is_left_to_its_own_learn_errand(self):
        m = member(name="Oz", role=guildjobs.FAMILY)
        self.assertEqual([], train_steps(guildjobs.plan([m]), "Oz"))

    def test_capped_trades_names_only_a_trade_at_a_ceiling_below_the_top(self):
        m = member(skills={H: (75, 75), M: (74, 75), S: (300, 300), FA: (0, 0)})
        self.assertEqual((H,), guildjobs.capped_trades(m))


class TheRankWalkHasItsOwnAllowance(unittest.TestCase):
    """Live on wow-dev 2026-10-18 after eff63a7: one rank walk in about 4 hours
    while 15 trades sat at a tier cap. The members planned ahead of a capped
    one used the guild's STEPS_PER_GUILD on their own jobs, and the rank walk,
    counted against the same 4, was refused every pass."""

    def ahead(self, count=guildjobs.STEPS_PER_GUILD):
        # Planned before Funkymon (same role and guild, earlier names), each
        # with post waiting at its mailbox: a job step against STEPS_PER_GUILD.
        crew = [
            member(name="Aa%d" % i, level=40, skills={FA: (40, 75)})
            for i in range(count)
        ]
        mail = {m.name: ("take-item mail:1 item:2",) for m in crew}
        return crew, mail

    def test_the_jobs_ahead_do_not_use_up_the_rank_walk(self):
        crew, mail = self.ahead()
        result = guildjobs.plan(crew + [member()], mail=mail)
        self.assertEqual(1, len(train_steps(result, "Funkymon")), result.notes)
        collects = [s for s in result.steps if s.action == "collect"]
        self.assertEqual(guildjobs.STEPS_PER_GUILD, len(collects))

    def test_rank_walks_keep_a_cap_of_their_own(self):
        capped = [
            member(name="Cap%02d" % i)
            for i in range(guildjobs.TRAIN_STEPS_PER_GUILD + 2)
        ]
        result = guildjobs.plan(capped)
        trains = [s for s in result.steps if s.action == "train"]
        self.assertEqual(guildjobs.TRAIN_STEPS_PER_GUILD, len(trains))


if __name__ == "__main__":
    unittest.main()

"""A family member sits out its campaign to craft, and a guildmate stands in.

The operator's request (2026-10-05): when Og is busy tailoring, put a
different damage dealer, tank or healer in; Grug's family keeps Og on his
tailoring while Zug's family keeps running dungeons. These pin standin.py's
pure decisions and drive the bridge's half with its reads stubbed.
"""

import asyncio
import contextlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import craft_rhythm  # noqa: E402
import guildrun  # noqa: E402
import standin  # noqa: E402
from test_guildsocial_bridge import bridge, row  # noqa: E402

WARRIOR, HUNTER, ROGUE, PRIEST, MAGE, WARLOCK = 1, 3, 4, 5, 8, 9
PROTECTION = "12301"
HOLY = "14913"
DEADMINES = next(d for d in guildrun.doors() if d.keyword == "deadmines")
SKILLS = {"tailoring": 120, "enchanting": 10}


def member(name, level, class_id, **kw):
    return guildrun.member_from_row(row(name, level, class_id, **kw))


FAMILY = {
    "Grug": member("Grug", 20, WARRIOR, talent_spells=PROTECTION, has_shield=1),
    "Ugga": member("Ugga", 20, PRIEST, talent_spells=HOLY),
    "Og": member("Og", 20, MAGE),
    "Bork": member("Bork", 20, ROGUE),
    "Grog": member("Grog", 19, HUNTER),
}
ROSTER = tuple(sorted(FAMILY))


def facts(**over):
    """Grug's family at the Deadmines, Og ordered out, three guildmates free."""
    base = dict(
        family="Grug",
        leader="Grug",
        ordered="Og",
        roster=ROSTER,
        skills=dict(SKILLS),
        out_member=FAMILY["Og"],
        family_levels=tuple(m.level for n, m in sorted(FAMILY.items()) if n != "Og"),
        guild="Cave",
        faction="Alliance",
        door=DEADMINES,
        candidates=(
            member("Zappy", 21, MAGE),
            member("Locky", 20, WARLOCK),
            member("Arrow", 23, HUNTER),
        ),
        every_family=frozenset(ROSTER),
    )
    base.update(over)
    return standin.Facts(**base)


def seated(in_name="Locky", out_name="Og", seat="dps"):
    return standin.Seat("Grug", out_name, in_name, seat, "Og crafts")


# --- the order -----------------------------------------------------------------


class TheOrder(unittest.TestCase):
    def test_off_when_unset(self):
        self.assertEqual({}, standin.orders({}))
        self.assertEqual({}, standin.orders({standin.ENV: ""}))

    def test_head_and_member_pairs(self):
        self.assertEqual(
            {"Grug": "Og", "Zug": "Oz"},
            standin.orders({standin.ENV: "Grug:Og, Zug:Oz"}),
        )

    def test_the_head_never_sits_out_and_a_malformed_pair_is_dropped(self):
        self.assertEqual({}, standin.orders({standin.ENV: "Grug:Grug,Og,:Og,Grug:"}))


class TheCraftingGoal(unittest.TestCase):
    def test_live_below_the_cap_on_the_trade_climbed_furthest(self):
        self.assertEqual("tailoring 120/300", standin.goal(SKILLS))

    def test_met_at_the_cap(self):
        self.assertEqual("", standin.goal({"tailoring": 300, "enchanting": 10}))

    def test_none_without_a_crafting_trade(self):
        self.assertEqual("", standin.goal({"mining": 50, "first aid": 10}))


# --- who sits out and who stands in ----------------------------------------------


class WhoStandsIn(unittest.TestCase):
    def test_a_free_guild_damage_dealer_takes_ogs_seat(self):
        step = standin.step(facts())
        self.assertEqual(standin.SEAT, step.action, step.why)
        self.assertEqual(
            ("Grug", "Og", "dps"),
            (step.seat.family, step.seat.out_name, step.seat.seat),
        )
        # Nearest Og's level first, then the name: Locky (20) before Zappy (21).
        self.assertEqual("Locky", step.seat.in_name)
        self.assertIn("tailoring 120/300", step.seat.reason)
        self.assertLessEqual(len(step.seat.args()[4]), standin.REASON_WIDTH)

    def test_a_member_in_a_guild_run_or_standing_in_elsewhere_is_busy(self):
        step = standin.step(facts(busy=frozenset({"Locky"})))
        self.assertEqual("Zappy", step.seat.in_name)

    def test_another_guild_another_side_or_out_of_band_is_never_seated(self):
        step = standin.step(
            facts(
                candidates=(
                    member("Stranger", 20, MAGE, guild_name="Bonkers"),
                    member("Orcish", 20, MAGE, race=2),
                    member("Elder", 26, MAGE),
                    member("Young", 14, MAGE),
                )
            )
        )
        self.assertEqual("", step.seat.in_name)

    def test_a_family_member_is_never_a_guest(self):
        step = standin.step(facts(candidates=(FAMILY["Bork"],)))
        self.assertEqual("", step.seat.in_name)

    def test_a_healer_seat_wants_a_member_who_heals(self):
        out = member("Ugga", 20, PRIEST, talent_spells=HOLY)
        candidates = (
            member("Shadowy", 20, PRIEST),
            member("Mender", 21, PRIEST, talent_spells=HOLY),
        )
        step = standin.step(
            facts(ordered="Ugga", out_member=out, candidates=candidates)
        )
        self.assertEqual(("healer", "Mender"), (step.seat.seat, step.seat.in_name))

    def test_the_head_and_the_leader_never_sit_out(self):
        self.assertEqual(standin.NONE, standin.step(facts(ordered="Grug")).action)
        self.assertEqual(standin.NONE, standin.step(facts(leader="Og")).action)

    def test_no_queued_dungeon_seats_nobody(self):
        self.assertEqual(standin.NONE, standin.step(facts(door=None)).action)


# --- nobody can stand in: the family runs four-handed ------------------------------


class NoGuestRunsFourHanded(unittest.TestCase):
    """The operator's decision (2026-10-05): when no guildmate can take Og's
    seat, Og still sits out to tailor and the family runs as the four left."""

    def test_no_guest_still_sits_og_out_with_an_empty_seat(self):
        step = standin.step(facts(candidates=()))
        self.assertEqual(standin.SEAT, step.action, step.why)
        self.assertEqual(
            ("Grug", "Og", "", "dps"),
            (step.seat.family, step.seat.out_name, step.seat.in_name, step.seat.seat),
        )
        self.assertFalse(step.seat.has_guest)
        self.assertEqual(
            "no guest at deadmines; the family runs four-handed", step.seat.reason
        )
        self.assertEqual(("Grug", "Og", "", "dps"), step.seat.args()[:4])

    def test_a_guest_found_between_runs_takes_the_empty_seat(self):
        empty = seated(in_name="")
        step = standin.step(facts(current=empty))
        self.assertEqual(standin.SEAT, step.action, step.why)
        self.assertEqual("Locky", step.seat.in_name)

    def test_still_no_guest_keeps_the_four_handed_row(self):
        step = standin.step(facts(current=seated(in_name=""), candidates=()))
        self.assertEqual(standin.KEEP, step.action, step.why)
        self.assertIn("four-handed", step.why)

    def test_never_filled_mid_run(self):
        step = standin.step(facts(current=seated(in_name=""), mid_run=True))
        self.assertEqual(standin.KEEP, step.action)

    def test_kept_with_no_door_queued(self):
        step = standin.step(facts(current=seated(in_name=""), door=None))
        self.assertEqual(standin.KEEP, step.action)

    def test_the_order_removed_or_the_goal_met_still_clears_it(self):
        empty = seated(in_name="")
        self.assertEqual(
            standin.CLEAR, standin.step(facts(ordered="", current=empty)).action
        )
        self.assertEqual(
            standin.CLEAR,
            standin.step(facts(skills={"tailoring": 300}, current=empty)).action,
        )

    def test_the_head_never_sits_out_even_with_no_guest(self):
        self.assertEqual(
            standin.NONE, standin.step(facts(ordered="Grug", candidates=())).action
        )


# --- when the row is cleared -------------------------------------------------------


class WhenTheRowEnds(unittest.TestCase):
    def test_the_order_removed_clears_it(self):
        step = standin.step(facts(ordered="", current=seated()))
        self.assertEqual(standin.CLEAR, step.action)
        self.assertIn("removed", step.why)

    def test_the_goal_met_clears_it(self):
        step = standin.step(facts(skills={"tailoring": 300}, current=seated()))
        self.assertEqual(standin.CLEAR, step.action)
        self.assertIn("met", step.why)

    def test_a_guest_gone_from_the_world_between_runs_clears_it(self):
        step = standin.step(facts(current=seated(in_name="Gone")))
        self.assertEqual(standin.CLEAR, step.action)

    def test_a_guest_in_a_guild_run_between_runs_clears_it(self):
        step = standin.step(facts(current=seated(), busy=frozenset({"Locky"})))
        self.assertEqual(standin.CLEAR, step.action)
        self.assertIn("in a guild run", step.why)

    def test_an_offline_guest_between_runs_clears_it(self):
        step = standin.step(
            facts(
                current=seated(), candidates=(member("Locky", 20, WARLOCK, online=0),)
            )
        )
        self.assertEqual(standin.CLEAR, step.action)
        self.assertIn("offline", step.why)

    def test_a_free_guest_keeps_the_seat(self):
        self.assertEqual(standin.KEEP, standin.step(facts(current=seated())).action)

    def test_grouped_with_the_family_keeps_the_seat(self):
        step = standin.step(
            facts(
                current=seated(),
                candidates=(member("Locky", 20, WARLOCK, group_leader=1),),
            )
        )
        self.assertEqual(standin.KEEP, step.action)

    def test_never_mid_run(self):
        step = standin.step(facts(current=seated(in_name="Gone"), mid_run=True))
        self.assertEqual(standin.KEEP, step.action)


# --- the contract ---------------------------------------------------------------------


class TheContract(unittest.TestCase):
    def test_the_table_the_module_reads(self):
        sql = standin.TABLE_SQL
        self.assertIn("CREATE TABLE IF NOT EXISTS overseer_family_standin", sql)
        for column in (
            "family VARCHAR(12)",
            "out_name VARCHAR(12)",
            "in_name VARCHAR(12)",
            "seat ENUM('tank','healer','dps')",
            "reason VARCHAR(160)",
            "created_at",
        ):
            self.assertIn(column, sql)
        self.assertIn("UNIQUE KEY uq_family (family)", sql)

    def test_the_bridge_creates_it_at_start(self):
        ran = []

        @contextlib.contextmanager
        def connect():
            yield _Conn(ran)

        with mock.patch.object(bridge, "_connect", connect):
            bridge._ensure_standin_store()
        self.assertEqual([standin.TABLE_SQL], [sql for sql, _ in ran])

    def test_seat_replaces_the_familys_row_and_clear_deletes_it(self):
        ran = []

        @contextlib.contextmanager
        def connect():
            yield _Conn(ran)

        with mock.patch.object(bridge, "_connect", connect):
            bridge._write_standin("Grug", standin.Step(standin.SEAT, "x", seated()))
            bridge._write_standin("Grug", standin.Step(standin.CLEAR, "x"))
            bridge._write_standin("Grug", standin.Step(standin.KEEP, "x"))
        self.assertEqual(
            [standin.DELETE_SQL, standin.INSERT_SQL, standin.DELETE_SQL],
            [sql for sql, _ in ran],
        )
        self.assertEqual(("Grug", "Og", "Locky", "dps", "Og crafts"), ran[1][1])


class _Cursor:
    def __init__(self, ran, rows=()):
        self.ran = ran
        self.rows = list(rows)
        self.rowcount = 1

    def execute(self, sql, args=()):
        self.ran.append((sql, tuple(args)))

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, ran, rows=()):
        self.ran = ran
        self.rows = rows

    def cursor(self):
        return _Cursor(self.ran, self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- the member sitting out is exempt -------------------------------------------------


class _Exempt(unittest.TestCase):
    def setUp(self):
        self._saved = (
            getattr(bridge, "_STANDIN_OUT", None),
            getattr(bridge, "_STANDIN_GUESTS", None),
        )
        bridge._STANDIN_OUT = frozenset({"Og"})
        bridge._STANDIN_GUESTS = frozenset({"Locky"})

    def tearDown(self):
        bridge._STANDIN_OUT, bridge._STANDIN_GUESTS = self._saved


class TheFamilyRunsWithoutOg(_Exempt):
    def drive(self, gates_hold=False):
        seen = {"gear": [], "slots": [], "town_first": []}
        inserted = []

        @contextlib.contextmanager
        def connect():
            yield _Conn([])

        def gear_gate(names, keyword):
            seen["gear"].append(list(names))
            return (
                "gear-up first: Og has no main-hand weapon"
                if gates_hold and "Og" in names
                else None
            )

        def free_slots(names):
            seen["slots"].append(list(names))
            return {n: (0 if n == "Og" else 40) for n in names}

        def town_first(mode, names, slots):
            seen["town_first"].append(list(names))
            return "Og waits for a town run" if "Og" in names else ""

        with mock.patch.multiple(
            bridge,
            _gear_gate=gear_gate,
            _fetch_free_slots=free_slots,
            _bag_hold_stuck=lambda names, slots: tuple(
                n for n in names if slots.get(n) == 0
            ),
            _town_first=town_first,
            _insert_job=lambda name, mode, source: inserted.append((name, mode)),
            _hand_to_town=lambda *a: 0,
            _keep_in_town=lambda names: 0,
            _quest_while_stuck=lambda *a: 0,
            _connect=connect,
        ):
            written = bridge._drive_dungeon(
                "deadmines", 5, list(ROSTER), "s", withheld=[]
            )
        return written, inserted, seen

    def test_og_is_not_sent_and_not_gated_on(self):
        written, inserted, seen = self.drive(gates_hold=True)
        self.assertEqual(4, written[0])
        self.assertNotIn("Og", {n for n, _ in inserted})
        for gate, calls in seen.items():
            self.assertTrue(calls, gate)
            for names in calls:
                self.assertNotIn("Og", names, gate)

    def test_the_family_job_writer_skips_og_and_the_guest(self):
        inserted = []
        with mock.patch.object(
            bridge, "_insert_job", lambda name, mode, source: inserted.append(name)
        ):
            self.assertEqual(
                4,
                bridge._insert_family_jobs(
                    list(ROSTER) + ["Locky"], "dungeon:deadmines", "s"
                ),
            )
        self.assertEqual(sorted(set(ROSTER) - {"Og"}), sorted(inserted))

    def test_another_familys_job_order_leaves_og_on_craft(self):
        inserted = []
        cohort = types.SimpleNamespace(key="Grug", names=set(ROSTER))
        with mock.patch.multiple(
            bridge,
            _queue_owns_job=lambda key=None: False,
            _insert_job=lambda name, mode, source: inserted.append(name),
        ):
            written = asyncio.run(
                bridge.Bridge._set_family_job(
                    types.SimpleNamespace(), cohort, "quest", "overseer:craft_rhythm"
                )
            )
        self.assertEqual(4, written)
        self.assertNotIn("Og", inserted)

    def test_ogs_own_craft_job_is_not_a_half_landed_order(self):
        jobs = {
            "Grug": "dungeon:deadmines",
            "Ugga": "dungeon:deadmines",
            "Og": "craft",
            "Bork": "dungeon:deadmines",
            "Grog": "dungeon:deadmines",
        }
        self.assertEqual("", craft_rhythm.standing_mode(jobs))
        self.assertEqual(
            "dungeon:deadmines",
            craft_rhythm.standing_mode(jobs, exempt=bridge._standin_out()),
        )


# --- the guest is busy for the guild -------------------------------------------------


class TheGuestIsBusyForTheGuild(unittest.TestCase):
    def test_guild_runs_asks_and_walks_count_the_guest_busy(self):
        class Cursor(_Cursor):
            def execute(self, sql, args=()):
                super().execute(sql, args)
                self.rows = (
                    [{"in_name": "Locky"}] if "overseer_family_standin" in sql else []
                )

            def fetchone(self):
                return {}

        class Conn(_Conn):
            def cursor(self):
                return Cursor(self.ran)

        @contextlib.contextmanager
        def connect():
            yield Conn([])

        with mock.patch.object(bridge, "_connect", connect):
            facts_read = bridge._fetch_guild_run_facts(guildrun.limits({}))
            active = bridge._active_guild_run_names()
        self.assertIn("Locky", facts_read["busy"])
        self.assertIn("Locky", active)
        locky = member("Locky", 20, WARLOCK)
        self.assertEqual(
            "in a guild run",
            guildrun.why_not(locky, facts_read["busy"], set(), facts_read["family"]),
        )


# --- the bridge pass -------------------------------------------------------------------


def _fams(leader_job="dungeon:deadmines"):
    return {
        "Grug": {"leader": {"name": "Grug", "job": leader_job}, "names": list(ROSTER)},
        "Zug": {
            "leader": {"name": "Zug", "job": "dungeon:ragefire"},
            "names": ["Oz", "Uzza", "Zork", "Zrog", "Zug"],
        },
    }


def _guild_facts():
    return {
        "rows": [row("Locky", 20, WARLOCK), row("Zappy", 21, MAGE)],
        "busy": set(),
        "in_runs": set(),
        "resting": set(),
        "benched": set(),
        "family": set(ROSTER) | {"Oz", "Uzza", "Zork", "Zrog", "Zug"},
        "finder_floors": {},
    }


class TheBridgePass(unittest.TestCase):
    def setUp(self):
        self._saved = (
            getattr(bridge, "_STANDIN_OUT", None),
            getattr(bridge, "_STANDIN_GUESTS", None),
            dict(getattr(bridge, "_STANDIN_TOLD", {})),
        )

    def tearDown(self):
        bridge._STANDIN_OUT, bridge._STANDIN_GUESTS = self._saved[:2]
        if hasattr(bridge, "_STANDIN_TOLD"):
            bridge._STANDIN_TOLD.clear()
            bridge._STANDIN_TOLD.update(self._saved[2])

    def run_pass(
        self,
        order="Grug:Og",
        rows=None,
        mid_run=False,
        og_job="dungeon:deadmines",
        leader_job="dungeon:deadmines",
        guild_rows=None,
    ):
        written, jobs_told, lines = [], [], []
        gfacts = _guild_facts()
        if guild_rows is not None:
            gfacts["rows"] = list(guild_rows)
        this = bridge.Bridge.__new__(bridge.Bridge)

        async def fake_mid_run(names):
            return mid_run

        this._mid_run = fake_mid_run
        pending = {
            "Grug": [{"id": 1, "keyword": "deadmines", "status": "active"}],
            "Zug": [{"id": 2, "keyword": "ragefire", "status": "active"}],
        }
        members = {n: row(n, m.level, m.class_id) for n, m in FAMILY.items()}
        log = types.SimpleNamespace(
            info=lambda msg, *a: lines.append(msg % a),
            exception=lambda msg, *a: lines.append("EXC " + (msg % a)),
            warning=lambda msg, *a: lines.append(msg % a),
        )
        with (
            mock.patch.dict("os.environ", {standin.ENV: order}),
            mock.patch.multiple(
                bridge,
                log=log,
                _fetch_standin_rows=lambda: dict(rows or {}),
                _fetch_guild_run_facts=lambda bounds: gfacts,
                _fetch_trade_skills=lambda names: {"Og": dict(SKILLS)},
                _fetch_standin_members=lambda names: {
                    n: members[n] for n in names if n in members
                },
                _write_standin=lambda family, step: written.append(
                    (family, step.action, step.seat)
                ),
                _standing_jobs=lambda family=None: {"Og": og_job, "Grug": leader_job},
                _insert_job=lambda name, mode, source: jobs_told.append(
                    (name, mode, source)
                ),
            ),
        ):
            fams = asyncio.run(this._standin_pass(pending, _fams(leader_job)))
        return fams, written, jobs_told, lines

    def test_og_sits_out_a_guest_is_written_and_og_goes_to_craft(self):
        fams, written, jobs_told, lines = self.run_pass()
        # Compared by its fields: another suite may import standin afresh.
        self.assertEqual(
            [("Grug", standin.SEAT, ("Grug", "Og", "Locky", "dps"))],
            [
                (family, action, (s.family, s.out_name, s.in_name, s.seat))
                for family, action, s in written
            ],
        )
        self.assertNotIn("Og", fams["Grug"]["names"])
        self.assertEqual(5, len(fams["Zug"]["names"]), "Zug's family keeps running")
        self.assertEqual(frozenset({"Og"}), bridge._STANDIN_OUT)
        self.assertEqual(frozenset({"Locky"}), bridge._STANDIN_GUESTS)
        self.assertEqual([("Og", "craft", standin.SOURCE)], jobs_told)
        self.assertTrue(
            any("Og sits out, Locky stands in" in line for line in lines), lines
        )

    def test_never_a_craft_job_mid_run_and_never_a_job_for_the_guest(self):
        _, written, jobs_told, _ = self.run_pass(mid_run=True)
        self.assertEqual(standin.SEAT, written[0][1])
        self.assertEqual([], jobs_told)

    def test_unset_writes_nothing_and_reads_no_guild(self):
        def boom(bounds):
            raise AssertionError("the guild was read with no order and no row")

        with mock.patch.object(bridge, "_fetch_guild_run_facts", boom):
            fams, written, jobs_told, _ = self.run_pass(order="")
        self.assertEqual(([], []), (written, jobs_told))
        self.assertIn("Og", fams["Grug"]["names"])
        self.assertEqual(frozenset(), bridge._STANDIN_OUT)

    def test_the_order_removed_releases_the_guest_and_og_rejoins(self):
        fams, written, jobs_told, lines = self.run_pass(
            order="", rows={"Grug": seated()}, og_job="craft"
        )
        self.assertEqual([("Grug", standin.CLEAR, None)], written)
        self.assertIn("Og", fams["Grug"]["names"])
        self.assertEqual([("Og", "dungeon:deadmines", standin.SOURCE)], jobs_told)
        self.assertEqual(frozenset(), bridge._STANDIN_GUESTS)
        self.assertTrue(
            any("Locky is released and Og rejoins" in line for line in lines), lines
        )

    def test_a_standing_row_is_kept_and_og_stays_out(self):
        fams, written, jobs_told, _ = self.run_pass(
            rows={"Grug": seated()}, og_job="craft"
        )
        self.assertEqual([("Grug", standin.KEEP, None)], written)
        self.assertNotIn("Og", fams["Grug"]["names"])
        self.assertEqual([], jobs_told)

    def test_no_guest_writes_an_empty_seat_and_og_still_sits_out(self):
        fams, written, jobs_told, lines = self.run_pass(guild_rows=())
        self.assertEqual(
            [("Grug", standin.SEAT, ("Grug", "Og", "", "dps"))],
            [
                (family, action, (s.family, s.out_name, s.in_name, s.seat))
                for family, action, s in written
            ],
        )
        self.assertEqual(
            "no guest at deadmines; the family runs four-handed", written[0][2].reason
        )
        self.assertNotIn("Og", fams["Grug"]["names"])
        self.assertEqual(4, len(fams["Grug"]["names"]))
        self.assertEqual(frozenset({"Og"}), bridge._STANDIN_OUT)
        self.assertEqual(frozenset(), bridge._STANDIN_GUESTS)
        self.assertEqual([("Og", "craft", standin.SOURCE)], jobs_told)
        self.assertTrue(
            any("Og sits out, nobody stands in" in line for line in lines), lines
        )

    def test_a_four_handed_row_is_kept_while_nobody_can_stand_in(self):
        fams, written, _, _ = self.run_pass(
            rows={"Grug": seated(in_name="")}, og_job="craft", guild_rows=()
        )
        self.assertEqual([("Grug", standin.KEEP, None)], written)
        self.assertNotIn("Og", fams["Grug"]["names"])
        self.assertEqual(frozenset(), bridge._STANDIN_GUESTS)

    def test_the_queue_pass_runs_it_before_anything_drives_a_family(self):
        import ast
        import pathlib

        source = (pathlib.Path(bridge.__file__)).read_text(encoding="utf-8")
        node = next(
            n
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_campaign_queue_once"
        )
        body = ast.get_source_segment(source, node)
        self.assertLess(
            body.index("standin_pass(pending, fams)"),
            body.index("self._plan_campaigns(pending, fams)"),
        )


if __name__ == "__main__":
    unittest.main()


class AScarletWingTakesAGuest(unittest.TestCase):
    """2026-10-05: Grug's family ran the Scarlet Monastery Library, a wing the
    guild-run door list does not name, and no guest could ever fit it."""

    def test_the_wing_fits_by_its_own_band(self):
        library = guildrun.Door("scarlet-library", "Library", 33, 38, 189, 33)
        family = [41, 39, 38, 38]
        self.assertTrue(standin.fits_door(family, 38, library))
        self.assertTrue(standin.fits_door(family, 40, library), "no higher than Grug")
        self.assertFalse(standin.fits_door(family, 32, library), "under the finder")
        self.assertFalse(standin.fits_door(family, 42, library), "past family and door")

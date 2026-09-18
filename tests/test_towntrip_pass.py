"""The town trip reaches the command queue, and only through the pure planner.

bridge.py imports discord and cannot be imported here, so this reads it as text
the way test_bank_pass.py does. What is pinned is the seam: the bridge fetches
durability, bags, purse and spellbook and writes `repair` and `buy` rows, every
decision about what to repair and what to buy is towntrip.py's, and the errand
that puts a counter within reach is written BEFORE any row that needs one.

THE FAILURE THIS SUITE EXISTS FOR. mod-overseer#227 shipped DoRepair and DoBuy,
and towntrip.plan has been complete and tested since infra#3357, and for a week
neither was reachable from anything: two working executors and a working
planner with no writer between them. Nothing failed, because nothing ran. So
the assertions below are mostly about the wiring being present at all.
"""
import pathlib
import re
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PACKAGE / "bridge.py"
DOCKERFILE = pathlib.Path(__file__).resolve().parents[3] / "docker/wow-overseer/Dockerfile"


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = _source()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


def _code(signature: str) -> str:
    """The same block with its docstring removed.

    The prose is allowed to say `durability` and `stack`; the CODE is what must
    not, because a threshold in the code is a decision being made twice.
    """
    body = _block(signature)
    marker = '"""'
    if body.count(marker) >= 2:
        return body.split(marker, 2)[2]
    return body


class ThePassRunsAndInTheRightOrder(unittest.TestCase):
    def test_the_loop_is_registered(self):
        """An unregistered loop is a pass that never runs and never says so.

        THE WINDOW IS THE BLOCK, NOT A CHARACTER COUNT. This read
        `src[start:start + 900]` until infra#3741, and 900 was however long the
        list happened to be on the day it was written: registering ONE more loop
        pushed `self._towntrip_loop,` past the cut and failed this test on a
        change that had nothing to do with the town trip. A slice that stops
        short is the same defect as a slice that runs to EOF - it decides what
        the assertion can see - so it now ends where the registration actually
        ends.
        """
        src = _source()
        start = src.index("self._loops = {")
        self.assertIn("self._towntrip_loop,",
                      src[start:src.index("async def on_ready(", start)])

    def test_the_bridge_imports_the_planner(self):
        self.assertIn("\nimport towntrip\n", _source())

    def test_the_pass_stands_down_mid_run(self):
        """A town errand pulls the leader out of the instance and the party
        spreads. The vendor and bank passes gate on this and so does this one."""
        code = _code("    async def _towntrip_once(self)")
        self.assertIn("self._mid_run(names)", code)

    def test_the_travel_errand_is_written_before_any_row(self):
        """A row queued for a counter nobody is walking to is a refusal.

        Order matters and is asserted by position, not by reading: the aim has
        to appear in the source before the insert does.

        THE AIM MOVED INTO `_settle_town_errand` (infra#3728) and the invariant
        did not. It is written there because writing it and giving it back are
        one decision with one answer - the unconditional write at the top of
        this pass, with nothing anywhere writing the column back, is the whole
        of the defect - so what this pins now is that the settling still happens
        before the first insert, and that the aim is still what the settling
        writes.
        """
        code = _code("    async def _towntrip_once(self)")
        self.assertLess(code.index("_settle_town_errand"),
                        code.index("_insert_town_errand"))
        settle = _code("    async def _settle_town_errand(")
        self.assertIn('self._claim_town_slot("towntrip", leader, "repair")',
                      settle)

    def test_the_leader_is_the_one_sent(self):
        """Only the leader carries `new rpg`; an aimed follower wanders."""
        code = _code("    async def _towntrip_once(self)")
        self.assertIn("leader = await asyncio.to_thread(_head_now)", code)

    def test_the_leader_is_head_now_not_the_static_seniority_answer(self):
        """infra#3553/#3554, the same defect as the bank pass right beside it.

        `_head_now()`, NOT bonds.head_of_family() directly: the resting
        seniority answer never moves, but `overseer_roster.lead` (and
        whoever actually carries `new rpg`) does, whenever a trade errand or
        a standing `job = train` borrows the lead. Aiming the static answer
        while a live errand has moved leadership elsewhere writes a
        `travel_npc` nobody can walk. Checked with comments stripped, since
        the prose above is allowed to name the function it warns against.
        """
        code = _code("    async def _towntrip_once(self)")
        self.assertIn("_head_now", code)
        code_lines = [ln.split("#", 1)[0] for ln in code.splitlines()]
        self.assertNotIn("bonds.head_of_family()", "\n".join(code_lines))

    def test_repair_is_an_economy_errand(self):
        """`_write_trade_errand` refuses to write a role it does not know as an
        economy one, so the aim would silently never be written."""
        src = _source()
        start = src.index("ECONOMY_ERRANDS = (")
        self.assertIn('"repair"', src[start:start + 120])

    def test_the_loop_does_not_race_its_two_siblings_for_the_column(self):
        """Three passes write `travel_npc` and only an idle traveller may be
        retasked, so they must not arrive together. Vendor waits 90, bank 150."""
        code = _code("    async def _towntrip_loop(self)")
        self.assertIn("min(cycle, 210.0)", code)

    def test_a_failed_pass_is_logged_and_retried_rather_than_swallowed(self):
        code = _code("    async def _towntrip_loop(self)")
        self.assertIn("log.exception", code)


class TheBridgeDecidesNothingAboutTheTrip(unittest.TestCase):
    """Every threshold belongs to towntrip.py, which is where it is tested."""

    def test_the_pass_names_no_threshold_of_its_own(self):
        code = _code("    async def _towntrip_once(self)")
        for number in ("0.35", "0.9", "20", "STACK", "FLOOR", "ANY_DAMAGE"):
            with self.subTest(number=number):
                self.assertNotIn(number, code)

    def test_the_pass_names_no_item_entry(self):
        """A food or drink entry in the bridge is the FOOD/DRINK table being
        written down a second time, in the one place nothing tests it."""
        code = _code("    async def _towntrip_once(self)")
        for entry in ("787", "4592", "4593", "4594", "159", "1179", "1205", "1708"):
            with self.subTest(entry=entry):
                self.assertNotIn(entry, code)

    def test_what_counts_as_food_comes_from_the_planners_own_tables(self):
        """The two spell categories are named once, in towntrip, beside the
        test that pins them (infra#3464). The predecessor of this query
        filtered on the twelve VENDOR entries instead, which made conjured and
        looted stock invisible and every holder of it read as carrying none."""
        code = _code("def _fetch_town_carried(names: list)")
        self.assertIn("towntrip.CONSUMABLE_CATEGORY_FOOD", code)
        self.assertIn("towntrip.CONSUMABLE_CATEGORY_DRINK", code)
        self.assertNotIn("towntrip.FOOD", code)
        self.assertNotIn("towntrip.DRINK", code)

    def test_the_town_is_built_by_the_pure_constructor(self):
        code = _code("def _fetch_town(leader: str)")
        self.assertIn("towntrip.town_from_rows(", code)

    def test_the_npc_flags_come_from_the_pure_module(self):
        """The two bits are named once, beside the test that pins them."""
        code = _code("def _fetch_town(leader: str)")
        self.assertIn("towntrip.NPC_FLAG_VENDOR", code)
        self.assertIn("towntrip.NPC_FLAG_REPAIR", code)


class TheRowsCarryWhatThePlannerReads(unittest.TestCase):
    """A column the planner reads and the query does not select is a fact
    silently defaulted to zero, which plans nothing and looks like a family
    that needs nothing."""

    def test_the_worn_query_names_every_column_the_constructor_reads(self):
        src = _source()
        sql = src[src.index("_TOWN_WORN_SQL = ("):src.index("_TOWN_CARRIED_SQL = (")]
        for column in ("holder", "klass_id", "money", "level", "entry",
                       "item_name", "durability", "max_durability"):
            with self.subTest(column=column):
                self.assertIn("AS %s" % column, sql)

    def test_the_carried_query_names_its_columns(self):
        src = _source()
        sql = src[src.index("_TOWN_CARRIED_SQL = ("):src.index("_TOWN_SPELLS_SQL = (")]
        for column in ("holder", "guid", "entry", "name", "carried",
                       "spell_category", "item_flags"):
            with self.subTest(column=column):
                self.assertIn("AS %s" % column, sql)

    def test_the_counter_query_names_its_columns(self):
        src = _source()
        sql = src[src.index("_TOWN_COUNTERS_SQL = ("):src.index("_TOWN_WORN_SQL = (")]
        for column in ("npcflag", "item"):
            with self.subTest(column=column):
                self.assertIn("AS %s" % column, sql)

    def test_the_equipped_slot_bound_is_not_a_literal(self):
        """19 is a magic number that changes with the core. armory owns it."""
        code = _code("def _fetch_town_worn(names: list)")
        self.assertIn("len(armory.EQUIPPED_SLOTS)", code)
        self.assertNotIn("slot < 19", code)

    def test_position_is_read_from_the_live_snapshot_not_the_save_timer(self):
        """`characters` is written on PlayerSaveInterval and can be a quarter
        of an hour stale, which would read the wrong town's counters."""
        src = _source()
        sql = src[src.index("_TOWN_COUNTERS_SQL = ("):src.index("_TOWN_WORN_SQL = (")]
        self.assertIn("overseer_snapshot", sql)
        self.assertIn("updated_at >", sql)

    def test_counter_query_requires_three_dimensional_reachability(self):
        """A vendor below or above the leader is not an interactable counter.

        The core sale path checks live 3D interaction. The bridge must not
        queue a transaction from an X/Y-only match that the core will reject.
        """
        src = _source()
        sql = src[src.index("_TOWN_COUNTERS_SQL = ("):src.index("_TOWN_WORN_SQL = (")]
        self.assertIn("ABS(cr.position_z - s.pos_z) <= %s", sql)
        fetch = _code("def _fetch_town(leader: str)")
        self.assertIn(
            "(TOWN_COUNTER_YARDS, TOWN_COUNTER_YARDS, TOWN_COUNTER_YARDS,",
            fetch,
        )


class TheRowIsTheRowTheExecutorReads(unittest.TestCase):
    def test_only_kinds_that_have_an_executor_are_written(self):
        """mod-overseer#257: a kind in the ENUM with no executor is not
        refused, it falls through to the bot whisper and reports delivered."""
        code = _code("def _insert_town_errand(errand)")
        self.assertIn("errand.kind", code)
        self.assertNotIn("'mail'", code)
        self.assertNotIn("'auction'", code)

    def test_a_hand_off_names_its_receiver(self):
        """kind='give' moves an item out of target_name into target_arg, so a
        row that left target_arg empty would be a give to nobody."""
        code = _code("def _insert_town_errand(errand)")
        self.assertIn("errand.taker", code)
        self.assertNotIn("'', %s)", code)

    def test_the_retry_window_cannot_be_silenced_by_another_pass(self):
        """The materials and bag passes write kind='give' with the same
        `guid:N` command shape. Without the source scope one of them could
        hold a conjured hand-off back for a whole retry window."""
        code = _code("def _recent_town_keys(minutes: int)")
        self.assertIn("source = 'towntrip'", code)

    def test_the_insert_degrades_on_a_world_without_the_migration(self):
        """1146 missing table, 1265 a `kind` ENUM with no repair/buy value."""
        code = _code("def _insert_town_errand(errand)")
        self.assertIn("1146", code)
        self.assertIn("1265", code)

    def test_a_repeat_inside_the_retry_window_is_not_queued_again(self):
        """A walk that has not finished would otherwise turn one slow journey
        into a hundred dead commands."""
        code = _code("    async def _towntrip_once(self)")
        self.assertIn("_recent_town_keys", code)

    def test_the_retry_window_reads_every_kind_the_trip_writes(self):
        code = _code("def _recent_town_keys(minutes: int)")
        for kind in ("'repair'", "'buy'", "'conjure'", "'give'"):
            with self.subTest(kind=kind):
                self.assertIn(kind, code)


class TheModuleShips(unittest.TestCase):
    def test_the_planner_is_copied_into_the_image(self):
        """A module the Dockerfile does not COPY is an ImportError at start."""
        if not DOCKERFILE.exists():
            self.skipTest("Dockerfile not in this checkout")
        self.assertIn("towntrip.py", DOCKERFILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

"""Say which guild bank tab is full, which is not bought, and what frees room (#2605 follow-up).

Measured on the dev realm on 2026-11-15 in both family guilds: two tabs bought,
tab 0 (Materials) at 98 of 98, tab 1 empty, the third tab (Raid Supplies) never
bought. The plan said "guild bank tab is full" for all of it, including a tab
that does not exist, so a reader could not tell a full vault from a missing
purchase. The report names each tab's numbers; the plan names the missing tab.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import guildbank  # noqa: E402
import itemplan  # noqa: E402
from test_itemplan import decide, member, stack  # noqa: E402

GUILD = {
    "purchased_tabs": 2,
    "deposit_rank_ids": (0,),
    "member_ranks": {"Zug": 0, "Zork": 1},
    "tab_items": {0: 98, 1: 0},
    "tab_names": {0: "Materials", 1: "Gear for Later"},
}


class TheReport(unittest.TestCase):
    def lines(self, guild=GUILD, names=("Zug", "Zork")):
        return guildbank.tab_report(guild, names)

    def test_each_bought_tab_has_its_used_and_free_slots(self):
        text = " ".join(self.lines())
        self.assertIn("tab 0 Materials 98 of 98 used, 0 free", text)
        self.assertIn("tab 1 Gear for Later 0 of 98 used, 98 free", text)

    def test_the_next_tab_is_named_with_its_price_when_not_bought(self):
        text = " ".join(self.lines())
        self.assertIn("tab 2 Raid Supplies is not bought", text)
        self.assertIn("500 gold", text)

    def test_a_full_tab_says_what_would_free_room(self):
        text = " ".join(self.lines())
        self.assertIn("withdraw or list", text)

    def test_members_who_cannot_deposit_on_every_tab_are_named(self):
        text = " ".join(self.lines())
        self.assertIn("cannot deposit on every tab: Zork", text)

    def test_no_guild_reads_nothing(self):
        self.assertEqual(guildbank.tab_report(None, ("Zug",)), [])


class ThePlanNamesAMissingTab(unittest.TestCase):
    def libram(self):
        return stack(
            holder="Uzza",
            entry=9500,
            name="Libram of Fire",
            item_class=itemplan.C_RECIPE,
            subclass=0,
            quality=2,
            sell=2000,
            required_skill_rank=0,
            required_skill=0,
        )

    def ctx(self, free):
        return itemplan.Context(fire_gear=frozenset(), guild_free=free)

    def skipped(self, free):
        item = self.libram()
        by_key, _ = decide([item], [member("Uzza")], self.ctx(free))
        return by_key[item.key].skipped

    def test_a_tab_the_guild_has_not_bought_is_not_called_full(self):
        free = {("Fam", 0): 0, ("Fam", 1): 98}
        got = self.skipped(free)
        self.assertTrue(any("not bought" in why for why in got), got)
        self.assertFalse(any("tab is full" in why for why in got), got)

    def test_a_bought_full_tab_is_still_called_full(self):
        free = {("Fam", 0): 0, ("Fam", 1): 98, ("Fam", 2): 0}
        got = self.skipped(free)
        self.assertTrue(any("tab is full" in why for why in got), got)

    def test_with_no_tab_read_at_all_it_stays_the_old_answer(self):
        got = self.skipped({})
        self.assertTrue(any("tab is full" in why for why in got), got)


class TheReadSaysItOncePerChange(unittest.TestCase):
    def test_the_free_slot_read_logs_the_numbers_once_until_they_change(self):
        import itemplan_reads

        itemplan_reads._TAB_SAID.clear()
        with self.assertLogs("wow-overseer.itemplan", level="INFO") as first:
            itemplan_reads._guild_free(["Zug"], "Fam", lambda names: GUILD)
        self.assertTrue(any("98 of 98" in line for line in first.output))
        with self.assertNoLogs("wow-overseer.itemplan", level="INFO"):
            itemplan_reads._guild_free(["Zug"], "Fam", lambda names: GUILD)


if __name__ == "__main__":
    unittest.main()

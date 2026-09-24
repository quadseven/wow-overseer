"""The family's mail, bank and vault, and the week behind them.

holdings.py folds the rows into numbers and scales the samples; wealth.py
puts words on them; bridge.py writes one overseer_economy_sample row per
member and per guild every ten minutes; map_server.py reads the week back.
The pure halves are tested with rows written by hand, the adapters as source
text, the way test_wealth_tab.py and test_collation_split.py read them.
"""

import datetime
import pathlib
import re
import unittest

import family
import holdings
import panel
import wealth

HERE = pathlib.Path(__file__).resolve().parent.parent
ROSTER = family.roster()
FIRST, SECOND = ROSTER[0], ROSTER[1]
GOLD = wealth.COPPER_PER_GOLD
NOW = datetime.datetime(2026, 9, 20, 12, 0, 0)


def letter(holder=FIRST, mail_id=1, money=0, item_guid=None, delivered=1, **kw):
    """One row of the mail adapter: one per attachment, LEFT JOINed."""
    row = {
        "holder": holder,
        "mail_id": mail_id,
        "money": money,
        "cod": 0,
        "expire_time": 1790000000,
        "checked": 0,
        "delivered": delivered,
        "item_guid": item_guid,
    }
    row.update(kw)
    return row


def inv(name=FIRST, bag=0, slot=panel._BACKPACK_SLOTS.start, guid=None, **kw):
    """The sampler's inventory row: just enough for split_inventory."""
    row = {
        "name": name,
        "bag": bag,
        "slot": slot,
        "item_guid": guid if guid is not None else 5000 + slot,
        "entry": 2589,
        "count": 1,
    }
    row.update(kw)
    return row


def sample(subject=FIRST, kind=holdings.MEMBER, hours_ago=0.0, **kw):
    row = {
        "subject": subject,
        "kind": kind,
        "money": 0,
        "mail_letters": 0,
        "mail_money": 0,
        "mail_items": 0,
        "bank_items": 0,
        "bank_tabs": 0,
        "taken_at": NOW - datetime.timedelta(hours=hours_ago),
    }
    row.update(kw)
    return row


class TheMailbox(unittest.TestCase):
    def test_letters_gold_and_attachments_are_counted_per_member(self):
        rows = [
            letter(mail_id=1, money=4100),
            letter(mail_id=2, item_guid=71),
            letter(mail_id=2, item_guid=72),
            letter(holder=SECOND, mail_id=3, money=50, item_guid=90),
        ]
        boxes = holdings.mailboxes(rows, [FIRST, SECOND])
        self.assertEqual(
            boxes[FIRST], {"letters": 2, "unread": 2, "money": 4100, "items": 2}
        )
        self.assertEqual(
            boxes[SECOND], {"letters": 1, "unread": 1, "money": 50, "items": 1}
        )

    def test_a_letter_in_transit_is_not_waiting(self):
        """Its gold cannot be collected yet, so it is not in the mailbox."""
        boxes = holdings.mailboxes([letter(money=900, delivered=0)], [FIRST])
        self.assertEqual(boxes[FIRST]["letters"], 0)
        self.assertEqual(boxes[FIRST]["money"], 0)

    def test_a_read_letter_is_waiting_but_not_unread(self):
        boxes = holdings.mailboxes([letter(checked=holdings.MAIL_READ)], [FIRST])
        self.assertEqual(boxes[FIRST]["letters"], 1)
        self.assertEqual(boxes[FIRST]["unread"], 0)

    def test_rows_without_checked_are_never_guessed_unread(self):
        """The sampler reads the mail pass's own rows, which carry no
        `checked`; a letter is then counted, and not called unread."""
        row = letter()
        del row["checked"]
        boxes = holdings.mailboxes([row], [FIRST])
        self.assertEqual((boxes[FIRST]["letters"], boxes[FIRST]["unread"]), (1, 0))

    def test_every_name_gets_an_empty_box_rather_than_no_key(self):
        self.assertEqual(
            holdings.mailboxes([], [FIRST]), {FIRST: holdings.empty_mailbox()}
        )


class TheBank(unittest.TestCase):
    def test_bank_slots_and_bank_bag_contents_are_the_bank(self):
        rows = [
            inv(slot=panel._BANK_SLOTS.start),
            inv(slot=panel._BANK_SLOTS.stop - 1),
            inv(slot=panel._BANK_BAG_SLOTS.start, guid=8001),
            inv(bag=8001, slot=0, guid=8101),
            inv(bag=8001, slot=1, guid=8102),
            inv(slot=panel._BACKPACK_SLOTS.start),
        ]
        split = wealth.split_inventory(rows, {})
        # Two bank slots and two stacks in the bank bag; the bag itself is
        # furniture and the backpack stack is carried.
        self.assertEqual(split["bank"], 4)
        self.assertEqual(split["elsewhere"], 5)

    def test_the_keyring_and_buyback_are_not_the_bank(self):
        rows = [inv(slot=panel._BANK_BAG_SLOTS.stop), inv(slot=90)]
        self.assertEqual(wealth.split_inventory(rows, {})["bank"], 0)

    def test_the_bank_slot_range_is_the_cores(self):
        """BANK_SLOT_ITEM_START..END in 3.3.5a: 39 to 66, right after the
        backpack and right before the bank bags."""
        self.assertEqual(panel._BANK_SLOTS.start, panel._BACKPACK_SLOTS.stop)
        self.assertEqual(panel._BANK_SLOTS.stop, panel._BANK_BAG_SLOTS.start)
        self.assertEqual(len(panel._BANK_SLOTS), 28)

    def test_bank_stacks_counts_per_name_with_one_split(self):
        rows = [
            inv(slot=panel._BANK_SLOTS.start),
            inv(name=SECOND, slot=panel._BANK_SLOTS.start),
            inv(name=SECOND, slot=panel._BANK_SLOTS.start + 1),
        ]
        self.assertEqual(wealth.bank_stacks(rows), {FIRST: 1, SECOND: 2})

    def test_the_bank_line(self):
        self.assertEqual(wealth.bank_line(0)["label"], wealth.BANK_EMPTY)
        self.assertEqual(wealth.bank_line(1)["label"], "1 stack in the bank")
        self.assertEqual(wealth.bank_line(12)["label"], "12 stacks in the bank")


class TheMailboxInWords(unittest.TestCase):
    def test_gold_waiting_is_amber_and_carries_the_coins(self):
        line = wealth.mailbox_line(
            {"letters": 3, "unread": 1, "money": 4100, "items": 2}
        )
        self.assertEqual(
            line["before"], "3 letters waiting (1 unread), 2 attachments, carrying "
        )
        self.assertEqual(line["money"]["text"], "41s 0c")
        self.assertEqual(line["tone"], wealth.CAUTION)

    def test_an_empty_mailbox_says_so(self):
        line = wealth.mailbox_line(holdings.empty_mailbox())
        self.assertEqual(line["before"], wealth.MAIL_EMPTY)
        self.assertIsNone(line["money"])
        self.assertEqual(line["tone"], wealth.PLAIN)

    def test_an_unread_table_is_not_an_empty_mailbox(self):
        self.assertEqual(wealth.mailbox_line(None)["before"], wealth.MAIL_UNREAD_NOTE)

    def test_a_letter_with_nothing_on_it_is_plain(self):
        line = wealth.mailbox_line({"letters": 1, "unread": 0, "money": 0, "items": 0})
        self.assertEqual(line["before"], "1 letter waiting")
        self.assertEqual(line["tone"], wealth.PLAIN)


class TheSampleRows(unittest.TestCase):
    def test_a_member_row_carries_purse_mail_and_bank(self):
        members, guilds = holdings.sample_rows(
            [{"name": FIRST, "money": 166 * GOLD}],
            {FIRST: 7},
            {FIRST: {"letters": 2, "unread": 0, "money": 4100, "items": 3}},
            [],
        )
        self.assertEqual(guilds, [])
        self.assertEqual(
            members,
            [
                {
                    "subject": FIRST,
                    "kind": holdings.MEMBER,
                    "money": 166 * GOLD,
                    "mail_letters": 2,
                    "mail_money": 4100,
                    "mail_items": 3,
                    "bank_items": 7,
                    "bank_tabs": 0,
                }
            ],
        )

    def test_one_guild_row_per_guild_however_many_members_share_it(self):
        vault = {
            "guild_id": 4,
            "guild_name": "Cave",
            "bank_money": 12 * GOLD,
            "tab_count": 2,
            "item_count": 40,
        }
        _members, guilds = holdings.sample_rows([], {}, None, [vault, dict(vault)])
        self.assertEqual(len(guilds), 1)
        self.assertEqual(guilds[0]["kind"], holdings.GUILD)
        self.assertEqual(guilds[0]["money"], 12 * GOLD)
        self.assertEqual(guilds[0]["bank_items"], 40)
        self.assertEqual(guilds[0]["bank_tabs"], 2)
        self.assertEqual(guilds[0]["mail_money"], 0)

    def test_unread_mail_tables_still_leave_a_purse_to_sample(self):
        members, _ = holdings.sample_rows([{"name": FIRST, "money": 5}], {}, None, [])
        self.assertEqual(members[0]["money"], 5)
        self.assertEqual(members[0]["mail_letters"], 0)

    def test_every_row_has_exactly_the_columns_the_insert_names(self):
        members, guilds = holdings.sample_rows(
            [{"name": FIRST, "money": 1}],
            {},
            None,
            [{"guild_id": 1, "guild_name": "Cave", "bank_money": 0}],
        )
        for row in members + guilds:
            self.assertEqual(tuple(row), holdings.SAMPLE_COLUMNS)

    def test_subjects_are_every_roster_family_then_the_fallback(self):
        rows = [{"name": "Alpha"}, {"name": "Beta"}, {"name": "Alpha"}]
        self.assertEqual(
            holdings.subjects(rows, ["Beta", "Gamma"]), ["Alpha", "Beta", "Gamma"]
        )


class TheSeries(unittest.TestCase):
    def test_no_samples_is_none_rather_than_a_flat_line(self):
        self.assertIsNone(holdings.series([], holdings.MEMBER, FIRST, "money", NOW))
        self.assertIsNone(
            holdings.series([sample()], holdings.MEMBER, FIRST, "money", None)
        )

    def test_points_span_the_window_and_the_range(self):
        rows = [
            sample(hours_ago=48, money=100),
            sample(hours_ago=24, money=300),
            sample(hours_ago=0, money=200),
        ]
        line = holdings.series(rows, holdings.MEMBER, FIRST, "money", NOW)
        self.assertEqual((line["first"], line["last"]), (100, 200))
        self.assertEqual((line["low"], line["high"]), (100, 300))
        self.assertEqual(line["span_seconds"], 48 * 3600)
        self.assertEqual([p[1] for p in line["points"]], [0.0, 1.0, 0.5])
        self.assertEqual(line["points"][-1][0], 1.0)
        self.assertAlmostEqual(line["points"][0][0], 5 / 7, places=3)

    def test_the_last_sample_in_a_bucket_is_kept_not_the_mean(self):
        rows = [
            sample(hours_ago=0.9, money=10),
            sample(hours_ago=0.5, money=90),
            sample(hours_ago=0, money=40),
        ]
        line = holdings.series(rows, holdings.MEMBER, FIRST, "money", NOW)
        values = [line["first"], line["last"]]
        self.assertNotIn(sum([10, 90, 40]) / 3, values)
        self.assertLessEqual(len(line["points"]), 2)

    def test_a_flat_line_sits_in_the_middle(self):
        rows = [sample(hours_ago=5, money=7), sample(hours_ago=0, money=7)]
        line = holdings.series(rows, holdings.MEMBER, FIRST, "money", NOW)
        self.assertEqual({p[1] for p in line["points"]}, {0.5})

    def test_other_subjects_kinds_and_old_samples_are_left_out(self):
        rows = [
            sample(subject=SECOND, money=5),
            sample(kind=holdings.GUILD, money=5),
            sample(hours_ago=24 * 8, money=5),
            sample(money=9),
        ]
        line = holdings.series(rows, holdings.MEMBER, FIRST, "money", NOW)
        self.assertEqual(len(line["points"]), 1)
        self.assertEqual(line["last"], 9)

    def test_every_line_shares_the_newest_sample_as_its_right_edge(self):
        rows = [sample(hours_ago=3), sample(subject=SECOND, hours_ago=0)]
        self.assertEqual(holdings.timeline_end(rows), NOW)
        self.assertIsNone(holdings.timeline_end([]))


class TheWeekInWords(unittest.TestCase):
    def test_the_span_is_the_lines_own_not_the_windows(self):
        rows = [
            sample(hours_ago=50, money=100 * GOLD),
            sample(hours_ago=0, money=112 * GOLD),
        ]
        h = wealth.build_history(rows, holdings.MEMBER, FIRST, NOW)
        self.assertIsNone(h["note"])
        self.assertEqual(h["lines"][0]["label"], "purse")
        self.assertEqual(
            h["lines"][0]["caption"], "112g 0s 0c now, up 12g 0s 0c over 2 days"
        )

    def test_down_and_unchanged_and_counts(self):
        rows = [
            sample(hours_ago=5, money=50, bank_items=9),
            sample(hours_ago=0, money=50, bank_items=4),
        ]
        h = wealth.build_history(rows, holdings.MEMBER, FIRST, NOW)
        captions = {line["label"]: line["caption"] for line in h["lines"]}
        self.assertEqual(captions["purse"], "50c now, unchanged over 5 hours")
        self.assertEqual(captions["bank stacks"], "4 now, down 5 over 5 hours")

    def test_a_line_that_was_zero_all_week_is_not_drawn_except_the_purse(self):
        rows = [sample(hours_ago=1), sample(hours_ago=0)]
        h = wealth.build_history(rows, holdings.MEMBER, FIRST, NOW)
        self.assertEqual([line["label"] for line in h["lines"]], ["purse"])

    def test_one_sample_says_so(self):
        h = wealth.build_history([sample(money=3)], holdings.MEMBER, FIRST, NOW)
        self.assertEqual(h["lines"][0]["caption"], "3c now, one sample so far")

    def test_no_samples_is_a_sentence_not_an_empty_box(self):
        for rows in (None, []):
            h = wealth.build_history(rows, holdings.MEMBER, FIRST, None)
            self.assertEqual(h, {"lines": [], "note": wealth.HISTORY_NOTE})

    def test_span_words(self):
        self.assertEqual(wealth.span_words(60), "1 minute")
        self.assertEqual(wealth.span_words(40 * 60), "40 minutes")
        self.assertEqual(wealth.span_words(5 * 3600), "5 hours")
        self.assertEqual(wealth.span_words(3 * 86400), "3 days")
        self.assertEqual(wealth.span_words(7 * 86400 - 600), "7 days")


class TheWholeView(unittest.TestCase):
    def build(self, **kw):
        return wealth.build_wealth(
            [{"name": FIRST, "level": 20, "class": 1, "money": 7 * GOLD}],
            [inv(slot=panel._BANK_SLOTS.start)],
            [],
            [
                {
                    "name": FIRST,
                    "guild_id": 4,
                    "guild_name": "Cave",
                    "bank_money": 3 * GOLD,
                }
            ],
            {},
            guild_bank_rows=[{"guild_id": 4, "tab_id": 0, "item_count": 5}],
            **kw,
        )

    def test_a_card_carries_its_mailbox_bank_and_week(self):
        p = self.build(
            mail_rows=[letter(money=4100)],
            economy_rows=[
                sample(hours_ago=3, money=5 * GOLD),
                sample(hours_ago=0, money=7 * GOLD),
            ],
        )
        m = next(m for m in p["members"] if m["name"] == FIRST)
        self.assertEqual(m["mailbox"]["money"], 4100)
        self.assertEqual(m["mail"]["tone"], wealth.CAUTION)
        self.assertEqual(m["bank"]["label"], "1 stack in the bank")
        self.assertEqual(
            m["history"]["lines"][0]["caption"],
            "7g 0s 0c now, up 2g 0s 0c over 3 hours",
        )
        self.assertEqual(p["history_caption"], wealth.HISTORY_CAPTION)

    def test_unread_tables_say_so_on_the_card(self):
        m = next(m for m in self.build()["members"] if m["name"] == FIRST)
        self.assertEqual(m["mail"]["before"], wealth.MAIL_UNREAD_NOTE)
        self.assertEqual(m["history"]["note"], wealth.HISTORY_NOTE)

    def test_each_vault_carries_its_gold_and_its_week(self):
        p = self.build(
            economy_rows=[
                sample(subject="Cave", kind=holdings.GUILD, hours_ago=0, money=3 * GOLD)
            ]
        )
        vault = p["guild_bank"]["by_guild"][0]
        self.assertEqual(vault["money"]["gold"], 3)
        self.assertEqual(vault["money_line"]["before"], "Cave vault holds ")
        self.assertEqual(vault["history"]["lines"][0]["label"], "vault gold")

    def test_a_vault_whose_gold_was_not_read_is_not_called_empty(self):
        bank = wealth.build_guild_bank(
            [{"name": FIRST, "guild_id": 4, "guild_name": "Cave"}]
        )
        self.assertIsNone(bank["by_guild"][0]["money"])
        self.assertIsNone(bank["by_guild"][0]["money_line"])


def _block(src: str, signature: str) -> str:
    start = src.index(signature)
    indent = len(src[:start].split("\n")[-1])
    lines = src[start:].split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line.strip() and not line.startswith(" " * (indent + 1)):
            break
        out.append(line)
    return "\n".join(out)


class TheBridgeWritesTheWeek(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (HERE / "bridge.py").read_text(encoding="utf-8")

    def test_the_table_is_bridge_owned_and_names_its_collation(self):
        ddl = _block(self.src, "def _ensure_economy_store() -> None:")
        self.assertIn("CREATE TABLE IF NOT EXISTS overseer_economy_sample", ddl)
        self.assertIn("COLLATE=utf8mb4_0900_ai_ci", ddl)
        for column in holdings.SAMPLE_COLUMNS + ("taken_at",):
            self.assertRegex(ddl, r"\" %s [A-Z]" % column)

    def test_the_insert_names_the_columns_the_rows_carry(self):
        m = re.search(
            r"INSERT INTO overseer_economy_sample \"\s*\"\(([^)]*)\)", self.src
        )
        self.assertIsNotNone(m)
        cols = tuple(c.strip() for c in m.group(1).split(","))
        self.assertEqual(cols, holdings.SAMPLE_COLUMNS)

    def test_it_is_ensured_at_start_in_both_modes(self):
        for sig in ("async def on_ready(self)", "async def run_headless(self)"):
            self.assertIn("_ensure_economy_store", _block(self.src, sig))

    def test_it_runs_on_the_sample_beat_in_its_own_handler(self):
        """Exactly two `except Exception:` in `_sample_family`, and the count
        is the contract: one for the digest's counters, one for the economy
        sample. Folding them into one would let either failure cost the
        other its sample."""
        loop = _block(self.src, "async def _sample_family(self) -> None:")
        self.assertIn("_take_economy_sample", loop)
        self.assertIn("_prune_economy_samples", loop)
        self.assertIn('"economy sample: wrote %d member row(s) and %d guild "', loop)
        self.assertIn('log.exception("economy sample failed; retrying', loop)
        # Two handlers: the digest's counters and this, never one for both.
        self.assertEqual(loop.count("except Exception:"), 2)
        self.assertEqual(loop.count("await asyncio.sleep(SAMPLE_INTERVAL)"), 1)

    def test_retention_is_the_sample_tables(self):
        prune = _block(self.src, "def _prune_economy_samples() -> int:")
        self.assertIn("DELETE FROM overseer_economy_sample", prune)
        self.assertIn("SAMPLE_RETENTION_DAYS", prune)

    def test_the_bank_is_counted_by_split_inventory_not_by_a_slot_range(self):
        take = _block(self.src, "def _take_economy_sample() -> tuple:")
        self.assertIn("wealth.bank_stacks(", take)
        self.assertIn("holdings.sample_rows(", take)
        self.assertIn("holdings.mailboxes(_fetch_mail(names), names)", take)
        sql = self.src[self.src.index("_ECONOMY_INVENTORY_SQL = (") :]
        sql = sql[: sql.index("\n)\n")]
        self.assertNotRegex(sql, r"ci\.(slot|bag)\s*(<|>|=|BETWEEN|IN)")


class TheViewReadsTheWeek(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = (HERE / "map_server.py").read_text(encoding="utf-8")
        cls.fetch = src[
            src.index("# --- the Wealth and Bags view") : src.index(
                "# Everything a tooltip draws"
            )
        ]
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")

    def test_the_vault_gold_is_read(self):
        self.assertIn("g.BankMoney AS bank_money", self.fetch)

    def test_the_mail_is_read_with_delivery_and_the_read_flag(self):
        self.assertIn("FROM mail m", self.fetch)
        self.assertIn("LEFT JOIN mail_items mi ON mi.mail_id = m.id", self.fetch)
        self.assertIn("(m.deliver_time <= UNIX_TIMESTAMP()) AS delivered", self.fetch)
        self.assertIn("m.checked AS checked", self.fetch)

    def test_the_samples_are_read_for_the_window_and_both_fail_closed(self):
        self.assertIn("FROM overseer_economy_sample", self.fetch)
        self.assertIn("holdings.HISTORY_DAYS", self.fetch)
        self.assertIn(
            '"mail_rows": mail_rows, "economy_rows": economy_rows', self.fetch
        )
        self.assertEqual(
            self.fetch.count("in (1054, 1146)"),
            4,
            "expected four fail-closed reads in the Bags adapter: guild_bank_tab "
            "and guild_bank_right in _fetch_wealth, mail and "
            "overseer_economy_sample in _fetch_wealth_holdings",
        )

    def test_the_page_draws_what_it_is_handed(self):
        econ = self.page[self.page.index("function wspark(points)") :]
        econ = econ[: econ.index("// WHERE IT IS ALL GOING")]
        for field in (
            "m.mail",
            "m.bank.label",
            "m.history",
            "line.caption",
            "line.label",
            "line.points",
            "h.note",
        ):
            self.assertIn(field, econ)
        self.assertNotIn("innerHTML", econ)
        self.assertIn("renderEcon(c.econ, m);", self.page)
        self.assertIn("c.econ.replaceChildren();", self.page)
        self.assertIn("whistory(b.history)", self.page)

    def test_the_module_ships_in_the_image(self):
        self.assertIn("holdings.py", (HERE / "Dockerfile").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

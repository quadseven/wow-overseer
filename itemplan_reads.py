"""The reads behind the item plan shadow's inputs (#1973).

`itemplan_data` holds the SQL and the pure readers; `itemplan_shadow` builds the
plan. This module is the thin step between them: it runs each read, hands the
rows to the reader and returns an `itemplan_shadow.Extras`. It writes nothing.

EACH INPUT IS READ ON ITS OWN. A failed read never raises and never takes
another input down: that field stays None and `Extras.unread` records the
exception's class name, so the tick line says `ran without: <input> [read
failed: <Class>]` and the plan fails closed on it. An input that read fine but
came back empty is a real answer and is not reported as missing, except auction
prices, where nothing listed means the plan has no price at all.

WHERE EACH INPUT COMES FROM.

  quest log            `itemplan_data.QUEST_LOG_SQL` and `QUEST_TEMPLATE_SQL`.
  worn gear verdicts   `EQUIPPED_SQL` with `ITEM_TEMPLATE_SQL` for the carried
                       gear's inventory type, item level and required level.
  binding              `ITEM_TEMPLATE_SQL`, `item_template.bonding` by entry,
                       for every carried row (the carried query holds none).
  auction prices       `LISTINGS_SQL` in the family's house and the neutral
                       house, then `bankforecast.HISTORY_SQL`.
  bank contents        the bank pass's own read (`bank.members_from_rows` over
                       the rows it reads), so the free count is the one that
                       logs "<name>'s bank has N free slot(s)".
  guild bank room      the bank pass's guild setup read and `bank._guild_tabs`:
                       free slots per purchased tab. When no family member's
                       rank may deposit, every tab reads as full.
  guild roster         the guild pass's roster read: guildmates outside the
                       family and the trades they work.
"""

from __future__ import annotations

import auction
import bank
import bankforecast
import itemplan
import itemplan_data
import itemplan_shadow as shadow


def _marks(values) -> str:
    return ",".join(["%s"] * len(values))


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class _Reads:
    """Collects what each read found and why one did not."""

    def __init__(self) -> None:
        self.unread: dict = {}

    def attempt(self, name: str, fn):
        """`fn()`'s answer, or None with the failure recorded under `name`."""
        try:
            return fn()
        except Exception as exc:  # a read must never reach the economy pass
            self.unread[name] = "read failed: %s" % type(exc).__name__
            return None


def _fetch(cur, sql: str, params) -> list:
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def _quest_log(cur, names) -> dict:
    log_rows = _fetch(cur, itemplan_data.QUEST_LOG_SQL % _marks(names), list(names))
    quests = sorted({_int(r.get("quest")) for r in log_rows} - {0})
    templates = (
        _fetch(cur, itemplan_data.QUEST_TEMPLATE_SQL % _marks(quests), quests)
        if quests
        else []
    )
    return itemplan_data.open_quest_items(log_rows, templates)


def _templates(cur, entries) -> dict:
    if not entries:
        return {}
    rows = _fetch(cur, itemplan_data.ITEM_TEMPLATE_SQL % _marks(entries), list(entries))
    return itemplan_data.item_templates(rows)


def _worn(cur, names) -> dict:
    rows = _fetch(cur, itemplan_data.EQUIPPED_SQL % _marks(names), list(names))
    return itemplan_data.equipped(rows)


def _prices(cur, names, entries) -> tuple:
    """(prices, why empty): live buyouts first, then history, no price invented."""
    races = _fetch(
        cur,
        "SELECT race FROM characters WHERE name IN (%s) ORDER BY name LIMIT 1"  # noqa: S608 - placeholders from a COUNT, values still bound
        % _marks(names),
        list(names),
    )
    team = auction.team_of(_int(races[0].get("race"), 0)) if races else ""
    house = auction.TEAM_HOUSE.get(team, 0)
    wanted = set(entries)
    listings: list = []
    for h in sorted({house, auction.HOUSE_NEUTRAL} - {0}):
        listings += [
            r
            for r in _fetch(cur, itemplan_data.LISTINGS_SQL, (h,))
            if _int(r.get("entry")) in wanted
        ]
    history: list = []
    if entries:
        try:
            history = _fetch(
                cur,
                bankforecast.HISTORY_SQL % _marks(entries),
                list(entries),
            )
        except Exception:
            history = []  # no history table is not a failed live read
    prices = itemplan_data.auction_prices(listings, history, house)
    return prices, itemplan_data.absent_reason(listings, history)


def _bank_free(names, bank_rows) -> dict:
    members = bank.members_from_rows(bank_rows(list(names)), list(names))
    return {m.name: m.bank_free for m in members}


def _guild_free(names, family, guild_setup):
    """(family, tab) -> free slots, or None when there is no guild bank setup."""
    guild = guild_setup(list(names))
    if not guild:
        return None
    depositors, tabs = bank._guild_tabs(guild)
    may = bool(depositors & set(names))
    return {(family, tab): (free if may else 0) for tab, free in tabs.items()}


def _crafters(names, roster) -> tuple | None:
    """((name, trade, skill), ...) for guildmates outside the family."""
    members = list(roster(list(names)))
    if not members:
        return None
    out = []
    for m in members:
        if m.family or m.name in names:
            continue
        for line, trade in itemplan.TRADE_OF_SKILL.items():
            value = m.rank_in(line)
            if value > 0 and line != itemplan.FISHING:
                out.append((m.name, trade, value))
    return tuple(sorted(out))


def read(
    names,
    family,
    rows,
    gear_rows,
    worn_rows,
    *,
    connect,
    bank_rows,
    guild_setup,
    roster,
):
    """Every input the plan can use, read now. Never raises.

    `connect` returns a DB-API connection whose cursor yields dict rows;
    `bank_rows(names)`, `guild_setup(names)` and `roster(names)` are the bank
    pass's and the guild pass's own reads.
    """
    names = sorted(str(n) for n in names)
    reads = _Reads()
    entries = sorted({_int(r.get("entry")) for r in rows} - {0})
    got: dict = {}
    cursor_inputs = (
        shadow.QUEST_LOG,
        shadow.BINDING,
        shadow.WORN_GEAR,
        shadow.AUCTION_PRICES,
    )
    try:
        with connect() as conn, conn.cursor() as cur:
            got[shadow.QUEST_LOG] = reads.attempt(
                shadow.QUEST_LOG, lambda: _quest_log(cur, names)
            )
            got[shadow.BINDING] = reads.attempt(
                shadow.BINDING, lambda: _templates(cur, entries)
            )
            got[shadow.WORN_GEAR] = reads.attempt(
                shadow.WORN_GEAR, lambda: _worn(cur, names)
            )
            got[shadow.AUCTION_PRICES] = reads.attempt(
                shadow.AUCTION_PRICES, lambda: _prices(cur, names, entries)
            )
    except Exception as exc:
        for name in cursor_inputs:
            got[name] = None
            reads.unread.setdefault(name, "read failed: %s" % type(exc).__name__)
    quest, templates = got.get(shadow.QUEST_LOG), got.get(shadow.BINDING)
    worn, priced = got.get(shadow.WORN_GEAR), got.get(shadow.AUCTION_PRICES)
    market = None
    if priced is not None:
        market = priced[0]
        if priced[1]:
            reads.unread[shadow.AUCTION_PRICES] = priced[1]
    if templates is None and worn is not None:
        reads.unread.setdefault(
            shadow.WORN_GEAR, "needs the binding read, which failed"
        )
    bank_free = reads.attempt(
        shadow.BANK_CONTENTS, lambda: _bank_free(names, bank_rows)
    )
    guild_free = reads.attempt(
        shadow.GUILD_ROOM, lambda: _guild_free(names, family, guild_setup)
    )
    if guild_free is None:
        reads.unread.setdefault(shadow.GUILD_ROOM, "no guild bank setup was read")
    crafters = reads.attempt(shadow.GUILD_ROSTER, lambda: _crafters(names, roster))
    if crafters is None:
        reads.unread.setdefault(shadow.GUILD_ROSTER, "no guild roster rows were read")
    return shadow.Extras(
        open_quest_items=quest,
        worn=worn,
        market=market,
        guild_free=guild_free,
        guild_crafters=crafters,
        templates=templates,
        bank_free=bank_free,
        unread=dict(reads.unread),
    )

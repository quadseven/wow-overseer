"""Where a craft errand's missing reagents come from, before it is judged fed.

Pure module: counts in, a plan and one sentence out. Nothing here talks to
MySQL, to Discord or to the worldserver.

WHY THIS EXISTS (#774, #769). Read from the dev realm's bridge log on
2026-11-13: eight crafters were re-aimed at a recipe every five minutes for
three hours and cast nothing. Every errand named a reagent with 0 in the
bags, and DriveCraft reads the bags only. The reagents were often not missing
from the world at all: one alchemist carried her herbs and had 34 Empty Vials
in her own bank, and one blacksmith stood short of a Rough Stone while his
guild's vault held 35. Nothing asked where a short reagent could come from,
so nothing fetched it.

WHAT IT DECIDES. For the recipe a crafter is aimed at, every reagent it eats
(the gathered half from `craft_rhythm.feeds`, the bought half from
`craft_supply.REAGENT` and `REAGENTS`), whether one cast's worth is in the
bags, and for each one that is not, the first place that holds it, in the
order a person at the counter would look:

    bank        the crafter's own bank holds a cast's worth
    mail        unopened post to the crafter holds it
    guild bank  the crafter's guild vault holds it
    vendor      a vendor sells it (bought with earned gold)
    gather      a family member's gathering trade, or roaming for a kill drop
    auction     nobody can gather or buy it from a vendor

The last two answers are `craft_rhythm.route_request`'s, the same routing the
module's own material requests get (#476), so the two cannot disagree.

WHAT IT NEVER DOES. It grants nothing: no item, no skill. It writes nothing.
`bank_wants` and `vault_withdrawals` hand the bank and guild bank passes the
stacks to take out; those passes keep their own walks, range gates and rank
rules.
"""

from __future__ import annotations

from dataclasses import dataclass

import craft_rhythm
import craft_supply
import guildbank

BANK = "bank"
MAIL = "mail"
GUILD_BANK = "guild bank"
VENDOR = "vendor"
GATHER = "gather"
AUCTION = "auction"

# The overseer_command source of a vault stack taken out for a craft. The
# house's reader of withdrawn stacks (bankforecast.WITHDRAWN_SQL) skips it, so
# a crafter's stone is never listed for sale.
VAULT_SOURCE = "guildbank-craft"


@dataclass(frozen=True)
class Reagent:
    """One reagent a recipe eats per cast; `vendor` when a vendor sells it."""

    entry: int
    label: str
    per_cast: int
    vendor: bool = False


@dataclass(frozen=True)
class Stock:
    """How much of one reagent sits where, for one crafter."""

    bags: int = 0
    bank: int = 0
    mail: int = 0
    guild_bank: int = 0


@dataclass(frozen=True)
class Short:
    """One reagent the bags hold less than a cast of, and where it comes from."""

    reagent: Reagent
    have: Stock
    source: str
    who: str
    why: str
    # The house was read and lists none of this reagent (#2523): the source is
    # still the auction, because choosing a source is not this flag's job, but
    # the line says there is nothing to buy.
    house_empty: bool = False


@dataclass(frozen=True)
class Plan:
    """One crafter's errand against its reagents.

    `judged` is False for a recipe with no reagent table here: this module has
    no opinion, and the errand stands as it always did.
    """

    name: str
    spell: int
    judged: bool = False
    casts: int = 0
    shorts: tuple = ()

    @property
    def fed(self) -> bool:
        return not self.judged or self.casts > 0


def reagents(spell: int) -> tuple:
    """Every reagent `spell` eats per cast, gathered half first."""
    spell = int(spell or 0)
    out: dict = {}
    fed = craft_rhythm.BOLT_FED.get(spell)
    if fed is not None:
        weave, bolt = fed
        out[int(bolt.entry)] = Reagent(int(bolt.entry), bolt.label, int(bolt.per_cast))
        for r in craft_rhythm.feeds(weave):
            out[int(r.entry)] = Reagent(
                int(r.entry), r.label, int(r.per_cast) * int(bolt.per_cast)
            )
    for r in craft_rhythm.feeds(spell):
        out[int(r.entry)] = Reagent(int(r.entry), r.label, int(r.per_cast))
    single = craft_supply.REAGENT.get(spell)
    if single is not None:
        entry, label, _price = single
        out[int(entry)] = Reagent(int(entry), label, 1, vendor=True)
    for entry, label, _price, qty in craft_supply.REAGENTS.get(spell, ()):
        out[int(entry)] = Reagent(int(entry), label, int(qty), vendor=True)
    return tuple(out.values())


def _source(name, spell, reagent, have, short, kinds, skills):
    """(source, who, why) for one short reagent."""
    if have.bank >= short:
        return (
            BANK,
            name,
            "%d in %s's bank, fetched at the next banker" % (have.bank, name),
        )
    if have.mail >= short:
        return (
            MAIL,
            name,
            "%d in %s's mailbox, collected at the next mailbox" % (have.mail, name),
        )
    if have.guild_bank >= short:
        return (
            GUILD_BANK,
            name,
            (
                "%d in the guild bank, which %s takes out at the next vault stop"
                % (have.guild_bank, name)
            ),
        )
    if reagent.vendor:
        return VENDOR, name, "a vendor sells it, so %s buys it" % name
    how, who, why = craft_rhythm.route_request(
        craft_rhythm.MaterialRequest(
            character=name,
            recipe=int(spell),
            entry=reagent.entry,
            label=reagent.label,
            short=short,
            need=reagent.per_cast,
        ),
        kinds.get(reagent.entry),
        skills,
    )
    if how == craft_rhythm.ROUTE_GATHER:
        return GATHER, who, why
    return AUCTION, who, why


def _house_none(have: Stock, label: str, short: int) -> str:
    """Why a reagent that fell through to an empty house has no source yet."""
    if have.guild_bank > 0:
        nxt = "the guild vault holds %d, short of the %d it needs" % (
            have.guild_bank,
            short,
        )
    else:
        nxt = "no corps mail or guild vault holds any, so nothing feeds it"
    return "the house lists none of %s; %s" % (label, nxt)


def house_none_notes(wants, listed) -> list:
    """One sentence per (crafter, reagent) the house lists none of.

    `wants` is [(crafter, label, entry)] and `listed` is entry -> live
    listings (None when the house was not read, which says nothing). Each pair
    is said once however often it is wanted.
    """
    if listed is None:
        return []
    out, seen = [], set()
    for name, label, entry in wants or ():
        if (name, int(entry)) in seen or listed.get(int(entry), 0) > 0:
            continue
        seen.add((name, int(entry)))
        out.append(
            "%s is short of %s and the house lists none of it, so a "
            "purchase has nothing to buy" % (name, label)
        )
    return out


def plan(
    name: str, spell: int, stock: dict, kinds: dict, skills: dict, listed=None
) -> Plan:
    """`name`'s errand `spell` against `stock` (entry -> Stock).

    `kinds` is entry -> (item class, subclass), `skills` is the family's
    name -> {trade: value}; both only matter for a reagent no bank, mailbox,
    vault or vendor answers. `listed` is entry -> live auction listings, or
    None when the house was not read: a reagent that falls through to the
    house with none listed says so (`Short.house_empty`).
    """
    eaten = reagents(spell)
    if not eaten:
        return Plan(name, int(spell or 0))
    fed = craft_rhythm.BOLT_FED.get(int(spell or 0))
    bolt_entry = int(fed[1].entry) if fed is not None else 0
    bolt_need = max(1, int(fed[1].per_cast)) if fed is not None else 0
    bolt_have = (stock.get(bolt_entry) or Stock()) if fed is not None else Stock()
    short_bolts = max(0, bolt_need - bolt_have.bags)
    bolt_stored = short_bolts > 0 and (
        bolt_have.bank >= short_bolts
        or bolt_have.mail >= short_bolts
        or bolt_have.guild_bank >= short_bolts
    )
    weave_feeds = (
        {int(r.entry): max(1, int(r.per_cast)) for r in craft_rhythm.feeds(fed[0])}
        if fed is not None
        else {}
    )
    casts = None
    shorts = []
    for reagent in eaten:
        if reagent.entry in weave_feeds:
            if short_bolts == 0 or bolt_stored:
                continue
            per = short_bolts * weave_feeds[reagent.entry]
            reagent = Reagent(reagent.entry, reagent.label, per, reagent.vendor)
        else:
            per = max(1, reagent.per_cast)
        have = stock.get(reagent.entry) or Stock()
        if reagent.entry not in weave_feeds:
            casts = have.bags // per if casts is None else min(casts, have.bags // per)
        if have.bags >= per:
            continue
        if reagent.entry == bolt_entry and not bolt_stored and weave_feeds:
            continue
        source, who, why = _source(
            name, spell, reagent, have, per - have.bags, kinds, skills
        )
        empty = (
            source == AUCTION
            and listed is not None
            and listed.get(reagent.entry, 0) <= 0
        )
        if empty:
            why = _house_none(have, reagent.label, per - have.bags)
        shorts.append(Short(reagent, have, source, who, why, empty))
    return Plan(name, int(spell), True, casts or 0, tuple(shorts))


def line(p: Plan) -> str:
    """One plain sentence: what the craft is missing and where it comes from."""
    parts = [
        (
            "%s %d of %d in the bags, %s"
            % (s.reagent.label, s.have.bags, s.reagent.per_cast, s.why)
            if s.house_empty
            else "%s %d of %d in the bags, from the %s: %s"
            % (s.reagent.label, s.have.bags, s.reagent.per_cast, s.source, s.why)
        )
        for s in p.shorts
    ]
    return "%s cannot cast spell %d yet - %s" % (p.name, p.spell, "; ".join(parts))


def bank_wants(plans) -> dict:
    """name -> the entries its own bank is to hand back for its craft."""
    out: dict = {}
    for p in plans or ():
        entries = {s.reagent.entry for s in p.shorts if s.source == BANK}
        if entries:
            out[p.name] = frozenset(entries)
    return out


@dataclass(frozen=True)
class VaultWithdrawal:
    """One guild vault stack a crafter takes out for its own craft.

    Shaped like `bankforecast.Withdrawal` (`character`, `command`, `line`) so
    the guild bank pass queues it the same way, plus its own `source`.
    """

    character: str
    stack: object
    item: str
    spell: int
    source: str = VAULT_SOURCE

    @property
    def command(self) -> str:
        return guildbank.format_item_withdraw(
            item_guid=int(self.stack.guid), tab=int(self.stack.tab)
        )

    @property
    def line(self) -> str:
        return "%s takes %s x%d (guid %d) from tab %d for its craft (spell %d)" % (
            self.character,
            self.item,
            int(self.stack.count),
            int(self.stack.guid),
            int(self.stack.tab),
            self.spell,
        )


def vault_withdrawals(plans, stacks_by_name: dict, takers) -> tuple:
    """(withdrawals, notes) for every short the guild bank answers.

    `stacks_by_name` is name -> the vault stacks of that member's guild
    (`bankforecast.Stack`); `takers` are `bankforecast.Withdrawer`s. The
    crafter takes the stack itself, one per short, the largest first, only
    with a free bag slot and a withdrawal left on that tab today. Anything
    else is a note, never a guess.
    """
    by_name = {t.name: t for t in takers or ()}
    room = {t.name: int(t.free_slots) for t in takers or ()}
    used: dict = {}
    out, notes = [], []
    for p in plans or ():
        for s in p.shorts:
            if s.source != GUILD_BANK:
                continue
            stacks = sorted(
                (
                    st
                    for st in stacks_by_name.get(p.name, ())
                    if int(st.entry) == s.reagent.entry
                ),
                key=lambda st: (-int(st.count), int(st.guid)),
            )
            taker = by_name.get(p.name)
            chosen = None
            for st in stacks:
                left = taker.left(st.tab) if taker is not None else 0
                if left is None or used.get((p.name, int(st.tab)), 0) < left:
                    chosen = st
                    break
            if taker is None or chosen is None:
                notes.append(
                    "%s may not take %s out of the guild bank today, so "
                    "its craft (spell %d) waits" % (p.name, s.reagent.label, p.spell)
                )
                continue
            if room.get(p.name, 0) <= 0:
                notes.append(
                    "%s has no free bag slot to take %s out of the guild "
                    "bank, so its craft (spell %d) waits"
                    % (p.name, s.reagent.label, p.spell)
                )
                continue
            room[p.name] -= 1
            key = (p.name, int(chosen.tab))
            used[key] = used.get(key, 0) + 1
            out.append(VaultWithdrawal(p.name, chosen, s.reagent.label, p.spell))
    return tuple(out), tuple(notes)

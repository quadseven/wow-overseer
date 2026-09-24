"""What to do with a protected non-gear item, asked of Jev in shadow (#232).

WHY. `item_disposition` (jev_items) judges carried GEAR only. Everything else
a character carries is kept or routed by fixed rules: the vendor pass refuses
anything a quest needs, any reagent, any stack a family trade uses, anything
above common and anything with no vendor price (bag_pressure.sellable), and
the bridge logs the count as "economy: carried inventory protection summary".
Measured 2026-09-23: a level 60 priest at 0 free slots of 30 carried 48 uncut
gems, 8 recipes for trades she does not have, 3 lockboxes, 25 Empty Vial, 20
Silverleaf and a pile of quest items no open quest needs, all protected. Jev
had never been asked about any of them.

THE QUESTION. One Choice per protected non-gear stack: keep it, deposit it in
the guild bank, sell it, give it to somebody who can use it, or destroy it.
Offered only where the world allows it: a bound copy cannot be banked or
given, and a stack with no vendor price cannot be sold. The facts are the
ones a player would look at: the holder's class, level, trades and skill,
free bag slots, who in the family or guild can use the item, whether an open
quest needs it, the vendor and auction prices and the stack size.

THE HEURISTIC'S ANSWER is what the shipped passes do with the stack, read off
their own plans and never re-decided here: `clearance` hands a gem or recipe
over, lists it or sells it; `lockbox` hands a box to the family rogue or sells
it; everything else the protection keeps.

ACT ON TWO ROUTES, SHADOW ON THE REST (#267). A day of shadow answers on the
dev realm showed where Jev's choice is well-founded and an executor exists:

  bank     the most common disagreement, reversible, and it cleared 0.6
           mostly on recipes for trades nobody in the family works and cloth
           or herbs the holder does not work. Carried out by the guild bank
           pass's item deposits (bank.Move to GUILD), with that pass's own
           depositor and tab-room gates.
  give     a stack handed to someone `who_else_can_use_it` names. Carried out
           by the guild gift writer (a give in trade range, else a letter).

Both act only where the protection would otherwise keep the stack
(`actable_routes`): never over a live clearance, lockbox or destroy plan,
never on a stack an open quest needs or a bound one, and a bank never takes
what somebody in the holder's family, or the holder, works a trade with. Each
route has its own threshold (`ROUTE_THRESHOLDS`, JEV_THRESHOLD_ITEM_KEEP_BANK
and JEV_THRESHOLD_ITEM_KEEP_GIVE), which the kind's own
JEV_THRESHOLD_ITEM_KEEP does not override.

`sell` and `destroy` stay in shadow. Both are irreversible, and neither
cleared a safe bar: sell peaked at 0.73 on a quest key, and every confident
destroy was a released quest item the destroy pass (#243) takes anyway, which
`routes_from_plans` now labels `destroy` so the two agree on the record.

An answer arrives after the pass that asked it has moved on, so an act is an
`Order` the bridge keeps and the next pass's executors carry out, for as long
as the same stack is still carried (`live_orders`).

ASKED SPARINGLY. The economy pass runs every 90 seconds and a full bag holds
dozens of protected stacks. `due` picks at most `limit` stacks per pass, never
asked first and then the longest waiting, and skips any stack asked within
`interval` seconds. The client's own cache answers an unchanged question for
free on top of that.

PURE: rows in, questions and Judgments out. The only I/O is the Jev client the
caller hands in.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace

import bank
import clearance
import goals
import guildshare
import jev
import lockbox
import materials
import raidlineup
from jev_items import Judgment

KIND = "item_keep"

KEEP = "keep"
BANK = "bank"
SELL = "sell"
DESTROY = "destroy"
GIVE_PREFIX = "give:"

# Routes Jev's answer may be carried out through, each with an executor (see
# the module docstring). A `give:<name>` answer is the GIVE route.
GIVE = "give"
ACTABLE: frozenset = frozenset({BANK, GIVE})
# Each actable route's own default confidence floor. Over one day of shadow
# answers on stacks the protection kept, 23 bank answers cleared 0.6 (the best
# 0.67, on recipes and cloth or herbs the holder does not work) and no give
# answer did (the best 0.54), so give acts only once Jev is surer than it has
# been. Below 0.6 the answers were near coin tosses between bank and a give.
ROUTE_THRESHOLDS = {BANK: 0.6, GIVE: 0.6}
# How long an order waits for its executor before it is dropped unread.
ORDER_MINUTES = 60

DEFAULT_THRESHOLD = 0.85
# Environment knobs the bridge reads for this kind, besides JEV_MODE_ITEM_KEEP
# and JEV_THRESHOLD_ITEM_KEEP (read by jev.policy).
LIMIT_ENV = "JEV_ITEM_KEEP_LIMIT"
INTERVAL_ENV = "JEV_ITEM_KEEP_INTERVAL_MINUTES"
DEFAULT_LIMIT = 8
DEFAULT_INTERVAL_MINUTES = 180

# item_template.class values. Gear (2, 4) is item_disposition's; containers
# (1) are the surplus-bag pass's.
CONTAINER, WEAPON, GEM, ARMOR, REAGENT, TRADE_GOODS = 1, 2, 3, 4, 5, 7
RECIPE, QUEST, KEY, MISC = 9, 12, 13, 15
NOT_ASKED = frozenset({CONTAINER, WEAPON, ARMOR})
_CLASS_WORDS = {
    0: "consumable",
    GEM: "gem",
    REAGENT: "reagent",
    6: "projectile",
    TRADE_GOODS: "trade good",
    RECIPE: "recipe",
    11: "quiver",
    QUEST: "quest item",
    KEY: "key",
    MISC: "miscellaneous",
    16: "glyph",
}
_QUALITY = {0: "poor", 1: "common", 2: "uncommon", 3: "rare", 4: "epic", 5: "legendary"}
# item_template.bonding: 1 binds when picked up, 4 is a quest item's binding.
_BOUND = (1, 4)
LOCKPICKING = lockbox.LOCKPICKING
_TRADE_IDS = dict(goals.SKILL_IDS)
_TRADE_NAMES = {number: name for name, number in _TRADE_IDS.items()}
# How many people who could use an item are shown and offered a give.
MAX_USERS = 4


def policy(environ=None) -> jev.Policy:
    """Act by default; each ACTABLE route then has its own floor
    (`route_rule`), and every other route is recorded and never carried out."""
    return jev.policy(
        KIND,
        environ=environ,
        default_mode=jev.ACT,
        default_threshold=DEFAULT_THRESHOLD,
        act_supported=bool(ACTABLE),
    )


def route_of(answer: str) -> str:
    """The route an answer takes: `give:<name>` is GIVE, the rest themselves."""
    return GIVE if str(answer).startswith(GIVE_PREFIX) else str(answer)


def route_rule(rule: jev.Policy, answer: str, environ=None) -> jev.Policy:
    """`rule` with the floor of the route `answer` takes.

    JEV_THRESHOLD_ITEM_KEEP_<ROUTE> sets it; unset, the route's
    ROUTE_THRESHOLDS default. A route with no act path keeps the kind's own,
    which only ever decides whether an agreeing answer is recorded as BOTH.
    """
    route = route_of(answer)
    if route not in ROUTE_THRESHOLDS:
        return rule
    return replace(
        rule,
        threshold=jev.threshold(
            "%s_%s" % (KIND, route), environ, ROUTE_THRESHOLDS[route]
        ),
    )


def knobs(environ) -> tuple:
    """(limit per pass, interval in seconds) from the environment.

    Unreadable or negative values fall back to the defaults: a typo must not
    turn the pass into one that asks about every stack every cycle.
    """

    def number(key, default):
        try:
            value = int(str(environ.get(key, "") or default).strip())
        except ValueError:
            return default
        return value if value >= 0 else default

    return (
        number(LIMIT_ENV, DEFAULT_LIMIT),
        number(INTERVAL_ENV, DEFAULT_INTERVAL_MINUTES) * 60,
    )


# ---------------------------------------------------------------------------
# WHICH STACKS ARE ASKED ABOUT


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def protection(row: dict) -> tuple:
    """Why the vendor pass refuses this stack, in words; () when it would not.

    The same five refusals as bag_pressure.sellable, read off the same row
    flags the bridge sets in _fetch_vendor_items. A row missing a flag is
    protected for that reason, the direction the sale selector fails in too.
    """
    reasons = []
    if bool(row.get("quest_item", True)):
        reasons.append("an open quest needs it")
    if bool(row.get("reagent", True)):
        reasons.append("it is a reagent")
    if bool(row.get("profession_needed", True)):
        reasons.append("a family trade uses it")
    quality = _int(row.get("quality"), -1)
    if quality < 0:
        reasons.append("its quality is unknown")
    elif quality > 1:
        reasons.append("it is %s quality" % _QUALITY.get(quality, str(quality)))
    if _int(row.get("sell_price"), 0) <= 0:
        reasons.append("no vendor pays for it")
    return tuple(reasons)


def protected(rows) -> list:
    """The carried non-gear rows the protection keeps, with a readable key."""
    out = []
    for row in rows or ():
        if _int(row.get("item_class"), -1) in NOT_ASKED:
            continue
        if _int(row.get("item_guid")) <= 0 or not str(row.get("holder") or ""):
            continue
        if protection(row):
            out.append(row)
    return out


def _key(row: dict) -> tuple:
    return (str(row["holder"]), _int(row["item_guid"]))


def due(rows, asked: dict, now: float, interval: float, limit: int) -> list:
    """At most `limit` rows to ask about this pass.

    `asked` maps (holder, item guid) to when it was last asked. A stack asked
    within `interval` seconds waits; the rest go never asked first, then the
    longest waiting, then by holder and guid so the order is stable.
    """
    waiting = [
        r for r in rows if _key(r) not in asked or now - asked[_key(r)] >= interval
    ]
    waiting.sort(key=lambda r: (asked.get(_key(r), float("-inf")), _key(r)))
    return waiting[: max(0, int(limit))]


# ---------------------------------------------------------------------------
# WHAT THE SHIPPED PASSES DO


def routes_from_plans(clear=(), locks=None, destroys=()) -> dict:
    """item guid -> (answer, why) from the clearance, lockbox and destroy plans.

    A guid absent from the result is one no pass routes: the protection
    keeps it. clearance's WAIT is a keep (the stack stays until its taker is
    online); a box its own holder can pick stays with the holder. `destroys`
    are bag_pressure.destroy_candidates: released quest items no vendor buys,
    which the destroy pass (#243) queues for the world's destroy verb.
    """
    out = {}
    for candidate in destroys or ():
        out[int(candidate.item_guid)] = (
            DESTROY,
            "destroy pass: a released quest item no vendor will buy",
        )
    for r in clear or ():
        if r.route in clearance.GIVEN:
            answer = GIVE_PREFIX + r.taker
        elif r.route in (clearance.AUCTION, clearance.VENDOR):
            answer = SELL
        else:
            answer = KEEP
        out[int(r.stack.guid)] = (answer, "clearance %s: %s" % (r.route, r.why))
    if locks is not None:
        for hand in locks.hands:
            out[int(hand.box.guid)] = (GIVE_PREFIX + hand.taker, "lockbox: " + hand.why)
        for box in locks.sell:
            out[int(box.guid)] = (SELL, "lockbox: nobody in the family can pick it")
    return out


def heuristic(row: dict, routes: dict) -> tuple:
    """(answer, why): what the shipped passes do with this stack."""
    routed = routes.get(_int(row.get("item_guid")))
    if routed is not None:
        return routed
    return KEEP, "protected: " + "; ".join(protection(row))


# ---------------------------------------------------------------------------
# THE FACTS


@dataclass(frozen=True)
class Holder:
    """One carrier: class, level, free slots and every skill line's value."""

    name: str
    class_id: int = 0
    level: int = 0
    free_slots: int = -1
    skills: dict | None = None

    def rank(self, skill: int) -> int:
        return _int((self.skills or {}).get(int(skill), 0))

    def trades(self) -> dict:
        """trade name -> skill, for the trades this holder has at all."""
        return {
            _TRADE_NAMES[s]: _int(v)
            for s, v in sorted((self.skills or {}).items())
            if s in _TRADE_NAMES and _int(v) > 0
        }


def trades_using(row: dict, reagent_trades: dict) -> tuple:
    """The trades whose own recipes use this item: the craft tables' claim by
    entry (bridge.REAGENT_TRADES) and materials.REAGENTS' by name."""
    found = list(reagent_trades.get(_int(row.get("entry")), ()))
    by_name = materials.REAGENTS.get(str(row.get("name") or ""))
    if by_name and by_name not in found:
        found.append(by_name)
    return tuple(found)


def _stack(row: dict, template: dict) -> clearance.Stack:
    return clearance.Stack(
        holder=str(row["holder"]),
        guid=_int(row["item_guid"]),
        entry=_int(row.get("entry")),
        name=str(row.get("name") or ""),
        item_class=_int(row.get("item_class")),
        count=_int(row.get("count"), 1) or 1,
        quality=_int(row.get("quality")),
        sell_price=_int(row.get("sell_price")),
        required_skill=_int(template.get("required_skill")),
        required_rank=_int(template.get("required_rank")),
    )


def use_for(person, row: dict, template: dict, trades: tuple) -> str:
    """Why `person` (a clearance.Person) could use this item, or ''."""
    stack = _stack(row, template)
    why = clearance.can_use(stack, person)
    if why:
        return why
    if stack.item_class == MISC and _int(template.get("lock_id")) > 0:
        need = lockbox.LOCK_SKILL.get(
            _int(template.get("lock_id")), lockbox.UNKNOWN_LOCK_SKILL
        )
        if person.rank(LOCKPICKING) >= need:
            return "%s can pick it (Lockpicking %d)" % (
                person.name,
                person.rank(LOCKPICKING),
            )
        return ""
    for trade in trades:
        skill = _TRADE_IDS.get(trade)
        if skill and person.rank(skill) > 0:
            return "%s works %s at %d" % (person.name, trade, person.rank(skill))
    return ""


def users(row: dict, template: dict, people, trades: tuple) -> list:
    """(person, why) for everyone but the holder who could use the item:
    family first, then online guildmates, then the rest, by name."""
    found = []
    for person in people or ():
        if person.name == row.get("holder"):
            continue
        why = use_for(person, row, template, trades)
        if why:
            found.append((person, why))
    found.sort(key=lambda p: (not p[0].family, not p[0].online, p[0].name))
    return found


def _money(copper) -> str:
    copper = _int(copper)
    gold, silver, rest = copper // 10000, copper // 100 % 100, copper % 100
    parts = []
    if gold:
        parts.append("%dg" % gold)
    if silver:
        parts.append("%ds" % silver)
    if rest or not parts:
        parts.append("%dc" % rest)
    return " ".join(parts)


def bound(template: dict) -> bool:
    return _int(template.get("bonding")) in _BOUND


def options(row: dict, template: dict, who: list, heuristic_answer: str) -> dict:
    """Every route this stack can take, as a Choice's criteria.

    `keep` and `destroy` always; `bank` and `give:<name>` only for a copy
    that is not bound; `sell` only when a vendor pays. The heuristic's own
    answer is always offered, so the two can be compared.
    """
    holder = str(row["holder"])
    name = str(row.get("name") or "the item")
    count = _int(row.get("count"), 1) or 1
    what = "%d %s" % (count, name) if count > 1 else name
    out = {KEEP: "%s keeps %s in their bags." % (holder, what)}
    if not bound(template):
        out[BANK] = (
            "%s deposits %s in the guild bank, freeing the slot; any guildmate "
            "can take it out later." % (holder, what)
        )
    price = _int(row.get("sell_price"))
    if price > 0:
        out[SELL] = "%s sells %s for %s each at a vendor, or lists it at auction." % (
            holder,
            what,
            _money(price),
        )
    if not bound(template):
        for person, why in who[:MAX_USERS]:
            out[GIVE_PREFIX + person.name] = "%s gives %s to %s (%s)." % (
                holder,
                what,
                person.name,
                why,
            )
    out[DESTROY] = "%s destroys %s to free the slot; nothing is gained for it." % (
        holder,
        what,
    )
    if heuristic_answer in out:
        return out
    if heuristic_answer.startswith(GIVE_PREFIX):
        taker = heuristic_answer[len(GIVE_PREFIX) :]
        out[heuristic_answer] = "%s gives %s to %s." % (holder, what, taker)
    elif heuristic_answer == SELL:
        out[SELL] = "%s lists %s on the auction house." % (holder, what)
    return out


def state_for(
    row: dict, template: dict, holder: Holder, who: list, trades: tuple, market: dict
) -> dict:
    """What Jev is shown about one stack."""
    item_class = _int(row.get("item_class"))
    item = {
        "name": str(row.get("name") or ""),
        "kind": _CLASS_WORDS.get(item_class, "class %d" % item_class),
        "quality": _QUALITY.get(_int(row.get("quality"), -1), "unknown"),
        "stack_size": _int(row.get("count"), 1) or 1,
        "max_stack": _int(template.get("stackable"), 1) or 1,
        "binds_to_holder": bound(template),
        "vendor_price_each": _money(row.get("sell_price")),
        "auction_price_each": (
            _money(market[_int(row.get("entry"))])
            if market.get(_int(row.get("entry")))
            else "not known"
        ),
        "an_open_quest_needs_it": bool(row.get("quest_item", False)),
        "why_it_is_protected": list(protection(row)),
    }
    if trades:
        item["used_by_trades"] = list(trades)
        item["holder_works_one_of_them"] = any(
            holder.rank(_TRADE_IDS.get(t, 0)) > 0 for t in trades
        )
    if item_class == RECIPE and _int(template.get("required_skill")):
        skill = _int(template.get("required_skill"))
        item["teaches"] = {
            "trade": _TRADE_NAMES.get(skill, "skill %d" % skill),
            "skill_needed": _int(template.get("required_rank")),
            "holder_skill": holder.rank(skill),
        }
    if item_class == MISC and _int(template.get("lock_id")) > 0:
        item["locked_box"] = True
    return {
        "holder": {
            "name": holder.name,
            "class": raidlineup.CLASS_NAMES.get(holder.class_id, "unknown"),
            "level": holder.level,
            "free_bag_slots": holder.free_slots
            if holder.free_slots >= 0
            else "unknown",
            "trades": holder.trades() or "none",
        },
        "item": item,
        "who_else_can_use_it": [
            {
                "name": p.name,
                "in_holders_family": bool(p.family),
                "online": bool(p.online),
                "why": why,
            }
            for p, why in who[:MAX_USERS]
        ]
        or "nobody in the family or guild",
    }


INSTRUCTIONS = (
    "`holder` is a World of Warcraft character carrying `item` in their bags. "
    "They adventure with a family of characters who share a guild, and bag "
    "space is scarce. Choose what a thoughtful player would do with `item` "
    "now: keep carrying it if the holder will use it soon, deposit it in the "
    "guild bank if it is worth keeping but not worth a bag slot, sell it if "
    "nobody will use it and it is worth something, give it to someone in "
    "`who_else_can_use_it` who would use it, or destroy it if it is worthless "
    "to everyone. An item an open quest needs should normally be kept."
)


def question(state: dict, offered: dict) -> dict:
    return {"route": jev.choice(INSTRUCTIONS, offered)}


def facts_line(state: dict) -> str:
    """The facts column: the state, compact, within the column's 1000."""
    text = json.dumps(state, separators=(",", ":"), sort_keys=True)
    return text if len(text) <= 1000 else text[:997] + "..."


# ---------------------------------------------------------------------------
# THE RECORD


@dataclass(frozen=True)
class KeepJudgment(Judgment):
    """A jev_items.Judgment that also carries the facts it was asked with,
    the routes Jev may carry out for this stack (`actable_routes`) and the
    stack's size, which an order needs."""

    facts: str = ""
    actable: tuple = ()
    count: int = 1


def actable_routes(row: dict, template: dict, who: list, holder, trades, answer):
    """The answers Jev may carry out for this stack: (), or some of `bank`
    and `give:<name>`. See the module docstring for why each guard exists.
    """
    if answer != KEEP or bool(row.get("quest_item", True)) or bound(template):
        return ()
    out = []
    family_uses = any(p.family for p, _why in who)
    holder_uses = any(holder.rank(_TRADE_IDS.get(t, 0)) > 0 for t in trades)
    if not family_uses and not holder_uses:
        out.append(BANK)
    out.extend(GIVE_PREFIX + p.name for p, _why in who[:MAX_USERS])
    return tuple(out)


def crafter_users(row: dict, takers: dict) -> list | None:
    """(person, why) for a recipe the designated-crafters register ranked (#248).

    `takers` maps an item guid to `crafters.candidates` for it, best first.
    None when the register did not rank this stack, so `users` answers. The
    holder is left out: keeping is already an option of its own.
    """
    ranked = (takers or {}).get(_int(row.get("item_guid")))
    if ranked is None:
        return None
    holder = str(row.get("holder") or "")
    return [
        (
            clearance.Person(
                name=p.taker,
                skills={},
                family=p.seat in ("family", "holder"),
                online=bool(p.online),
            ),
            p.why,
        )
        for p in ranked
        if p.taker and p.taker != holder
    ]


def designated_for(template: dict, register: dict) -> list:
    """The register's seats for a recipe's trade, as Jev is shown them."""
    seats = (register or {}).get(_int(template.get("required_skill")), ())
    return [{"name": s.name, "skill": s.rank, "seat": s.seat} for s in seats]


def asks(
    rows,
    *,
    templates,
    holders,
    people,
    routes,
    market,
    reagent_trades,
    mode,
    takers=None,
    register=None,
):
    """(KeepJudgment, state, questions) per row, in the order given.

    `takers` and `register` come from the designated-crafters register
    (#248): a recipe's `give:` options follow its ranking, and the state
    names the trade's designated crafters.
    """
    out = []
    for row in rows:
        entry = _int(row.get("entry"))
        template = templates.get(entry) or {}
        holder = holders.get(str(row["holder"])) or Holder(str(row["holder"]))
        trades = trades_using(row, reagent_trades)
        who = crafter_users(row, takers)
        if who is None:
            who = users(row, template, people, trades)
        answer, why = heuristic(row, routes)
        offered = options(row, template, who, answer)
        allowed = tuple(
            a
            for a in actable_routes(row, template, who, holder, trades, answer)
            if a in offered
        )
        state = state_for(row, template, holder, who, trades, market or {})
        seats = designated_for(template, register)
        if seats and "teaches" in state["item"]:
            state["item"]["teaches"]["designated_crafters"] = seats
        out.append(
            (
                KeepJudgment(
                    kind=KIND,
                    subject=holder.name,
                    holder=holder.name,
                    item_guid=_int(row["item_guid"]),
                    item_entry=entry,
                    item_name=str(row.get("name") or ""),
                    heuristic=answer,
                    heuristic_why=why,
                    mode=mode,
                    status="",
                    acted=jev.HEURISTIC,
                    facts=facts_line(state),
                    actable=allowed,
                    count=_int(row.get("count"), 1) or 1,
                ),
                state,
                question(state, offered),
            )
        )
    return out


def judged(
    base: KeepJudgment, outcome: jev.Outcome, rule: jev.Policy, environ=None
) -> KeepJudgment:
    """The judgment with Jev's answer and who acted.

    Jev acts only on an answer in the stack's own `actable`, at or above that
    route's floor (`route_rule`); anything else is recorded as the heuristic's.
    """
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers["route"]
    return replace(
        base,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        acted=route_rule(rule, answer.choice, environ).acted(
            base.heuristic,
            answer.choice,
            answer.confidence,
            can_act=answer.choice in base.actable
            and route_of(answer.choice) in ACTABLE,
        ),
    )


async def shadow_pass(client, pending, rule: jev.Policy, environ=None) -> list:
    """Ask Jev about each (judgment, state, questions); the judgments.

    Each question queues for a free client slot for up to the client's own
    deadline: nothing waits on this pass, and 162 of 950 questions in one day
    met `busy` behind another kind's burst (#267).
    """
    if rule.mode == jev.OFF:
        return []
    gate = asyncio.Semaphore(max(1, int(getattr(client, "concurrency", 1))))
    wait = float(getattr(client, "timeout", 0.0))

    async def one(ask):
        base, state, questions = ask
        async with gate:
            outcome = await client.ask(KIND, state, questions, wait=wait)
        return judged(base, outcome, rule, environ)

    return list(await asyncio.gather(*(one(a) for a in pending)))


# ---------------------------------------------------------------------------
# CARRYING AN ACT OUT (#267)


@dataclass(frozen=True)
class Order:
    """One stack Jev chose to bank or give, waiting for its executor."""

    holder: str
    guid: int
    entry: int
    name: str
    count: int
    route: str  # BANK or GIVE
    taker: str  # the receiver of a GIVE; '' for a BANK
    confidence: float
    at: float  # when it was decided, on the caller's clock

    @property
    def key(self) -> tuple:
        return (self.holder, self.guid)

    def said(self) -> str:
        """The one log line an order is announced with."""
        where = "the guild bank" if self.route == BANK else self.taker
        return "jev-keep: acting on %s's %d %s: %s to %s (conf %.2f)" % (
            self.holder,
            self.count,
            self.name,
            self.route,
            where,
            self.confidence,
        )


def orders_from(judgments, now: float) -> list:
    """An Order for every judgment Jev acted on, in the order given."""
    out = []
    for j in judgments:
        if j.acted != jev.JEV or route_of(j.jev) not in ACTABLE:
            continue
        taker = j.jev[len(GIVE_PREFIX) :] if route_of(j.jev) == GIVE else ""
        out.append(
            Order(
                holder=j.holder,
                guid=int(j.item_guid),
                entry=int(j.item_entry),
                name=j.item_name,
                count=int(getattr(j, "count", 1) or 1),
                route=route_of(j.jev),
                taker=taker,
                confidence=float(j.confidence or 0.0),
                at=now,
            )
        )
    return out


def live_orders(orders: dict, rows, now: float, names=None) -> tuple:
    """(orders still to carry out, what was dropped and why).

    `orders` maps (holder, guid) to an Order; `rows` are this pass's carried
    rows (bridge._fetch_vendor_items). An order whose stack is no longer
    carried by its holder, whose count changed, or that is older than
    ORDER_MINUTES is dropped: the world moved on, and a stale order must not
    act on a stack Jev never judged. `names`, when given, keeps only this
    family's orders and leaves the rest out of both results.
    """
    carried = {
        (str(r.get("holder") or ""), _int(r.get("item_guid"))): _int(r.get("count"), 1)
        for r in rows or ()
    }
    live, dropped = [], []
    for key, order in sorted(orders.items()):
        if names is not None and order.holder not in names:
            continue
        if now - order.at > ORDER_MINUTES * 60:
            dropped.append((order, "older than %d minutes" % ORDER_MINUTES))
        elif key not in carried:
            dropped.append((order, "no longer carried (done, or moved on)"))
        elif carried[key] != order.count:
            dropped.append((order, "the stack changed size"))
        else:
            live.append(order)
    return live, dropped


def gifts(orders) -> list:
    """The GIVE orders as guildshare.Gifts for the guild gift writer."""
    return [
        guildshare.Gift(
            holder=o.holder,
            taker=o.taker,
            item=o.name,
            entry=o.entry,
            count=o.count,
            guid=o.guid,
            need="Jev chose %s for it (conf %.2f)" % (o.taker, o.confidence),
            reason="Jev chose to give it (#267)",
        )
        for o in orders
        if o.route == GIVE and o.taker
    ]


def deposits(orders, depositors, room: int, planned=()) -> tuple:
    """(bank.Moves to the guild bank, notes) for the BANK orders.

    The guild bank pass's own gates, applied the way bank.plan applies them:
    only a holder whose rank may deposit on tab 0, only while the tab has
    `room` left, and never a stack `planned` (the keeper rule's own guild
    moves) already sends.
    """
    already = {int(m.guid) for m in planned}
    moves, notes = [], []
    for o in orders:
        if o.route != BANK or o.guid in already:
            continue
        if o.holder not in depositors:
            notes.append("%s's rank cannot deposit %s" % (o.holder, o.name))
            continue
        if room <= 0:
            notes.append("the guild bank's tab is full; %s stays" % o.name)
            continue
        room -= 1
        moves.append(
            bank.Move(
                character=o.holder,
                verb=bank.DEPOSIT,
                guid=o.guid,
                item=o.name,
                count=o.count,
                why="Jev chose to bank %s (conf %.2f)" % (o.name, o.confidence),
                to=bank.GUILD,
            )
        )
    return moves, notes


def summary(judgments, considered: int, limit: int, interval: float) -> str:
    """The pass's one log line. `jev-keep:` is this kind's own prefix."""
    answered = [j for j in judgments if j.jev]
    return (
        "jev-keep: asked %d of %d protected non-gear stack(s), %d answered, "
        "%d agree, %d differ, %d carried out as Jev's (limit %d, every %d min)"
        % (
            len(judgments),
            considered,
            len(answered),
            sum(1 for j in answered if j.agree),
            sum(1 for j in answered if not j.agree),
            sum(1 for j in judgments if j.acted == jev.JEV),
            limit,
            int(interval // 60),
        )
    )

"""A guild member's own profession loop, and the ride for a rare node (dark).

WHY IT EXISTS. profloop.py runs a FAMILY through gather, town, craft and train
and names its own seam: `decide` reads facts keyed by member name, so it can be
asked for one member. The guild members are not a family and do not travel as
one, and each already has its own ladder of steps (guildjobs.py: train, tool,
craft, post, sell, farm), which `GUILD_FOCUS=<guild>:craft` points at every
member of a guild. What no member could do is the one thing a person does when
the open world has nothing left for a trade: join a group going to an instance
that holds the node, pick it, and leave.

WHAT THIS MODULE ADDS, all of it pure (rows in, answers out; the bridge reads,
writes and keeps the clock):

  trade     `pick_trade`: the gathering trade a member works, by the skills it
            holds (mining 186, herbalism 182, skinning 393). Furthest behind
            first, the rule profloop.gather_job gives a family, so a member
            raises its weakest trade; skinning is a trade here too, though no
            node holds it.
  rare      `rare_nodes`: the nodes the open world does not have at all (a lock
            with a spawn only on an instance map), plus any lock the operator
            adds (`MEMBER_LOOP_RARE_LOCKS`), because a walk through the open
            world cannot reach them.
  ride      `rare_needs`: for a member whose skill opens a rare node that still
            gives it skill, and whose bags have room (profloop's own measured
            TOWN_FREE_SLOTS, asked through `profloop.decide`), one
            guildsocial.Need per instance door that holds the node. The social
            layer then does what it does for any need: the member answers a
            guildmate's ask for that door as a passenger in a damage seat, or
            asks for it. Nobody is ever seated who did not say yes, and no run
            is started here. A run still goes through guildrun's gates.
  leave     `plan_leaves`: once the run is over and the rider stands outside the
            instance, mod-overseer's `leave-group` (strayfollow.VERB) takes it
            out of the group, so it goes back to its own loop.

NORTH STAR. Nothing here grants, teaches, teleports or gives; the only verbs are
a player's own. OFF BY DEFAULT: MEMBER_PROFESSION_LOOP names the guilds in the
loop, comma-separated, matched without regard to case; empty means none.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import farmjob
import gatherband
import guildcorps
import guildsocial
import profloop
import strayfollow

ENV_SWITCH = "MEMBER_PROFESSION_LOOP"
ENV_EXTRA_LOCKS = "MEMBER_LOOP_RARE_LOCKS"
SOURCE = "overseer:memberloop"
VERB = strayfollow.VERB

MINING, HERBALISM, SKINNING = "mining", "herbalism", "skinning"
# The order a tie is broken in: the same as profloop.FARM_TRADES, then skinning.
TRADES = (MINING, HERBALISM, SKINNING)
SKILL_IDS = {
    MINING: guildcorps.MINING,
    HERBALISM: guildcorps.HERBALISM,
    SKINNING: guildcorps.SKINNING,
}
# Only these two have nodes a ride can reach; skinning comes off corpses.
NODE_TRADES = (MINING, HERBALISM)

# What a passenger's answer is worth: guildsocial.NEED_NODE, over an answer for the
# sake of XP and under a gear upgrade at the same door.
NEED_NODE = guildsocial.NEED_NODE

# How long the leave pass lets the same member alone after a leave row.
COOLDOWN_MINUTES = 30
LEAVES_PER_PASS = 3
# A rider is remembered this long without a group to leave; then it is dropped.
RIDER_MEMORY_MINUTES = 6 * 60


def guilds(env=None) -> frozenset:
    """The guild names MEMBER_PROFESSION_LOOP names, lower-cased."""
    raw = (os.environ if env is None else env).get(ENV_SWITCH, "")
    return frozenset(p.strip().lower() for p in str(raw).split(",") if p.strip())


def enabled_for(guild, env=None) -> bool:
    """Whether the guild is in the loop. Unset, no guild is."""
    key = str(guild or "").strip().lower()
    return bool(key) and key in guilds(env)


def extra_locks(env=None) -> frozenset:
    """Lock ids the operator treats as rare, from MEMBER_LOOP_RARE_LOCKS."""
    raw = (os.environ if env is None else env).get(ENV_EXTRA_LOCKS, "")
    out = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return frozenset(out)


def pick_trade(skills) -> tuple:
    """(trade, why) a member works, from {trade: value}; ("", why) for none.

    The gathering trade it holds at the LOWEST value, so a member raises its
    weakest first; a tie goes in the order of TRADES.
    """
    held = {}
    for trade in TRADES:
        try:
            value = int((skills or {}).get(trade) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            held[trade] = value
    if not held:
        return "", "it holds no gathering trade"
    trade = min(held, key=lambda t: (held[t], TRADES.index(t)))
    return trade, "%s is furthest behind (%d)" % (trade, held[trade])


@dataclass(frozen=True)
class Node:
    """One node kind on one map: a lock and the name its template carries."""

    map_id: int
    lock_id: int
    name: str = ""


def rare_nodes(instance_rows, open_locks, extra=frozenset()) -> tuple:
    """The nodes worth a ride: on an instance map, and either a lock the open
    world has no spawn of or one the operator named.

    `instance_rows`: dicts with map_id, lock_id, name, one per (map, lock) at
    least. `open_locks`: lock ids with a spawn off every instance map. Locks
    that gatherband does not know are dropped: a lock with no band has no skill
    to judge.
    """
    open_ = {int(x) for x in open_locks or ()}
    out = {}
    for row in instance_rows or ():
        lock = int(row.get("lock_id") or 0)
        if not any(gatherband.band_for(lock, t) is not None for t in NODE_TRADES):
            continue
        if lock in open_ and lock not in extra:
            continue
        key = (int(row["map_id"]), lock)
        out.setdefault(key, Node(key[0], lock, str(row.get("name") or "")))
    return tuple(sorted(out.values(), key=lambda n: (n.map_id, n.lock_id)))


def node_trade(lock_id) -> tuple:
    """(trade, band) a node's lock demands, or ("", 0)."""
    name, band = farmjob.skill_of_lock(lock_id)
    return (name or "", int(band or 0))


def usable(node: Node, skills) -> bool:
    """Whether the member can open the node and it still gives it skill."""
    trade, band = node_trade(node.lock_id)
    if trade not in NODE_TRADES:
        return False
    try:
        value = int((skills or {}).get(trade) or 0)
    except (TypeError, ValueError):
        return False
    return value > 0 and band <= value < band + farmjob.GREY_AFTER


def bags_have_room(name, free_slots, now=0.0) -> bool:
    """Whether profloop would keep this member gathering rather than send it to
    town: the same measured bar, asked through the same `decide`. An unread
    bag is no reason to stop a ride, so None passes."""
    if free_slots is None:
        return True
    facts = profloop.Facts(
        now=now, jobs={name: "quest"}, free_slots={name: int(free_slots)}
    )
    step = profloop.decide(profloop.State(phase=profloop.GATHER, since=now), facts)
    return step.state.phase != profloop.TOWN


def rare_needs(name, skills, free_slots, nodes, doors, now=0.0) -> tuple:
    """One guildsocial.Need per door whose map holds a rare node this member
    can use, best band first; () when it should not ride at all."""
    if not bags_have_room(name, free_slots, now):
        return ()
    out = []
    for door in doors or ():
        best = None
        for node in nodes or ():
            if int(node.map_id) != int(door.map_id) or not usable(node, skills):
                continue
            _trade, band = node_trade(node.lock_id)
            if best is None or band > best[0]:
                best = (band, node)
        if best is not None:
            out.append(
                guildsocial.Need(
                    member=name,
                    keyword=door.keyword,
                    item=best[1].name or "a rare node",
                    node=True,
                )
            )
    return tuple(out)


def merge_needs(existing, extra) -> list:
    """`existing` needs with `extra` added, best first (guildsocial.Need.rank)."""
    return sorted(list(existing or ()) + list(extra or ()), key=lambda n: n.rank)


@dataclass(frozen=True)
class Rider:
    """A member that went to a door for a node, and where it stands now."""

    name: str
    keyword: str
    grouped: bool
    in_instance: bool
    in_combat: bool
    run_live: bool


def leave_why(r: Rider) -> str:
    """Why this rider leaves its group now, or "" when it stays."""
    if not r.grouped or r.in_instance or r.in_combat or r.run_live:
        return ""
    return "the %s run is over and it stands outside" % r.keyword


def plan_leaves(riders, recent) -> tuple:
    """(rows, lines): a `leave-group` row and a line for each rider whose run is
    over, off its cooldown (`recent`: name -> minutes since its last row), at
    most LEAVES_PER_PASS, by name."""
    due = []
    for r in sorted(riders or (), key=lambda r: r.name):
        why = leave_why(r)
        if not why:
            continue
        last = (recent or {}).get(r.name)
        if last is not None and int(last) < COOLDOWN_MINUTES:
            continue
        due.append((r, why))
    rows, lines = [], []
    for r, why in due[:LEAVES_PER_PASS]:
        rows.append(strayfollow.Row(r.name, VERB, "%s:%s" % (SOURCE, r.name)))
        lines.append("%s leaves its group: %s" % (r.name, why))
    return tuple(rows), tuple(lines)


def forget(riders: dict, now: float, grouped_now) -> dict:
    """The remembered riders still worth tracking: name -> (keyword, since).
    One no longer grouped has left, and one older than RIDER_MEMORY_MINUTES is
    let go."""
    keep = {}
    for name, (keyword, since) in (riders or {}).items():
        if name not in grouped_now:
            continue
        if now - since > RIDER_MEMORY_MINUTES * 60.0:
            continue
        keep[name] = (keyword, since)
    return keep

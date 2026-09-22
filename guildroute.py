"""The guild hand-over rows (#174): how they are keyed, and what the Bags page says.

WHO GETS A GUILDMATE'S LOOT IS NOT DECIDED HERE. `gear.rank_receivers`,
`gear.route_plan` and `gear.route_deliverable` decide it, through
`bag_pressure`'s adapters, because gear.py is the one opinion about what is
an upgrade and bag_pressure is the one place rows become its shapes. This
module owns only the two ends of the row the bridge writes:

    source   "guildroute:<gain>" on every overseer_command row the pass
             writes, so its retry window and the Bags page find its rows and
             the page can say why the item moved without a second table.
    view     one sentence per recent row, for the Bags tab.

And one decision of its own (#185): which holder to WALK to a mailbox so a
route that is waiting on one can be posted. `plan_mail_runs` below.

PURE MODULE: no MySQL and no clock. Times are passed in.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import dungeonplan
import travel

SOURCE = "guildroute"

# The verb a posted hand-over is written with (kind='mail'), and the only two
# kinds a hand-over row may carry: a trade between two characters standing
# together, or a letter. Never 'give', which moves an item across any distance.
MAIL = "mail"
VERBS = ("trade", MAIL)

VIEW_LABEL = "guild hand-overs"
VIEW_INDEX = "04"
VIEW_EMPTY = (
    "Nothing handed over across the guild lately. A guildmate's item moves "
    "only by a trade when the two are together, or by post from a mailbox."
)

_ITEM_GUID = re.compile(r"(?:^|\s)(?:guid|item):(\d+)")
_STATUS_WORDS = {
    "pending": "waiting for the world",
    "claimed": "under way",
    "delivered": "done",
}


def source_for(gain) -> str:
    """The `source` a hand-over row is written with."""
    return "%s:%d" % (SOURCE, max(0, int(gain)))


def gain_of(source) -> int:
    """The gain a row's `source` carries, 0 when it carries none."""
    text = str(source or "")
    if not text.startswith(SOURCE + ":"):
        return 0
    tail = text[len(SOURCE) + 1 :]
    return int(tail) if tail.isdigit() else 0


def guid_of(command) -> int:
    """The item_instance guid a trade or mail command names, 0 for none."""
    match = _ITEM_GUID.search(str(command or ""))
    return int(match.group(1)) if match else 0


def view(rows, item_names=None) -> dict:
    """One sentence per hand-over row, in the order given, for the Bags page.

    `rows` are overseer_command rows this pass wrote (target_name, target_arg,
    kind, command, status, detail, source). `item_names` maps item guid to the
    item's name, read by the caller; a guid it does not know is named by
    number rather than dropped. A delivered letter is POSTED, not received:
    the receiver still has to reach a mailbox, and the page says so.
    """
    names = dict(item_names or {})
    lines = []
    for row in rows or ():
        guid = guid_of(row.get("command"))
        item = names.get(guid) or ("item %d" % guid if guid else "an item")
        posted = row.get("kind") == MAIL
        status = str(row.get("status") or "")
        if status == "delivered" and posted:
            outcome = "posted, waiting at the mailbox"
        elif status == "error":
            outcome = "refused: %s" % (row.get("detail") or "no reason given")
        else:
            outcome = _STATUS_WORDS.get(status, status or "unknown")
        lines.append(
            "%s to %s: %s %s, +%d item levels - %s"
            % (
                row.get("target_name") or "?",
                row.get("target_arg") or "?",
                item,
                "by post" if posted else "by trade",
                gain_of(row.get("source")),
                outcome,
            )
        )
    return {
        "index": VIEW_INDEX,
        "label": VIEW_LABEL,
        "lines": lines,
        "empty": VIEW_EMPTY,
    }


# ---------------------------------------------------------------------------
# THE MAIL RUN (#185)
#
# A route waits when the holder is beside no receiver and at no mailbox. On
# the dev realm that was every one of 59 routes. A player in that position
# walks to the nearest mailbox and posts the item; this is that walk, and
# nothing else. It is never a `give`: when no walk is possible the item stays
# where it is and one note says why.
#
# WHO CAN BE WALKED. mod-overseer walks a character through
# `overseer_roster.travel_npc`, and only a family's LEADER, the one carrying
# `new rpg` (the town slot refuses anybody else). A guild bot off the roster
# cannot be walked by anything in the module today: the aim book reads roster
# rows only, and upstream's `go` command returns at its first line for a bot
# with no master. quadseven/mod-overseer#569 is the module gap. Until it lands
# such a holder waits for a mailbox or a receiver it reaches by itself, and
# the note says so.
#
# THE BOUNDS. One run per holder at a time. The nearest mailbox on the
# holder's own map, and only within MAIL_RUN_YARDS. At most MAIL_RUNS_PER_DAY
# runs in any day. Never a holder in combat or inside an instance. Each run is
# logged with the gain that justified it. The letter itself is written by the
# ordinary route pass once the holder stands at the box, and the receiving
# family collects it on its own mail pass, the town trip's mailbox stop.

# The town slot's claimant name for a mail run.
MAIL_RUN_CLAIMANT = "guild route"
# The furthest mailbox worth a walk, in yards on the holder's own map.
MAIL_RUN_YARDS = 600.0
# Mail runs the realm may start in any 24 hours.
MAIL_RUNS_PER_DAY = 6
# A run that has not posted in this long is over, and its holder may be sent
# again once the day allows it.
MAIL_RUN_SECONDS = 1800.0
DAY_SECONDS = 86400.0

# Why a holder off the roster waits (the module gap above).
OFF_ROSTER = (
    "a guild bot off the roster, which nothing in mod-overseer can walk yet "
    "(quadseven/mod-overseer#569)"
)
NOT_LEADING = "follows its family's leader, and only a leader can be walked"


@dataclass(frozen=True)
class Walker:
    """What the pass knows about one holder it might walk to a mailbox.

    `unwalkable` is "" when the module can walk this holder, else the reason
    it cannot. `cohort` names the family whose town slot the walk goes
    through. `yards` and `aim` describe the nearest mailbox on the holder's
    map; `aim` is "" when there is none that can be named.
    """

    name: str
    map_id: int | None = None
    in_combat: bool = False
    unwalkable: str = ""
    cohort: str = ""
    yards: float | None = None
    aim: str = ""
    no_aim: str = ""


def walker_from(name, state, leader_of, roster, spawn) -> Walker:
    """One Walker out of the facts the bridge read.

    `state` is the holder's fresh snapshot row (map_id, in_combat) or None.
    `leader_of` maps a roster family leader to its family key; `roster` holds
    every roster name. `spawn` is the nearest mailbox row, with `d2` measured
    from this holder, or None.
    """
    name = str(name)
    if name in leader_of:
        unwalkable, cohort = "", str(leader_of[name])
    elif name in roster:
        unwalkable, cohort = NOT_LEADING, ""
    else:
        unwalkable, cohort = OFF_ROSTER, ""
    if not state:
        return Walker(name=name, unwalkable=unwalkable, cohort=cohort)
    try:
        map_id = int(state.get("map_id"))
    except (TypeError, ValueError):
        map_id = None
    yards = None
    if spawn and spawn.get("d2") is not None:
        try:
            yards = math.sqrt(max(0.0, float(spawn["d2"])))
        except (TypeError, ValueError):
            yards = None
    post = travel.mailbox_aim(spawn, map_id)
    no_aim = post.refused or ""
    if not spawn:
        no_aim = "no mailbox is spawned on map %s" % map_id
    return Walker(
        name=name,
        map_id=map_id,
        in_combat=bool(int(state.get("in_combat") or 0)),
        unwalkable=unwalkable,
        cohort=cohort,
        yards=yards,
        aim=post.aim or "",
        no_aim=no_aim,
    )


@dataclass(frozen=True)
class MailRun:
    """One holder walked to one mailbox to post one item to one receiver."""

    holder: str
    taker: str
    item: str
    guid: int
    gain: int
    cohort: str
    aim: str
    yards: float

    @property
    def said(self) -> str:
        """The log line: who walks where, with what, for whom, and the gain."""
        return (
            "%s walks %d yards to the mailbox at %s to post %s (item %d) to %s, +%d item levels"
            % (
                self.holder,
                int(round(self.yards)),
                self.aim,
                self.item,
                int(self.guid),
                self.taker,
                int(self.gain),
            )
        )


@dataclass(frozen=True)
class MailRunPlan:
    runs: tuple = ()
    notes: tuple = ()


def live_runs(running, now, seconds=MAIL_RUN_SECONDS) -> dict:
    """The runs still under way: holder -> start time, the stale ones dropped."""
    return {
        str(name): float(start)
        for name, start in dict(running or {}).items()
        if float(now) - float(start) < float(seconds)
    }


def runs_today(starts, now, posted=0) -> int:
    """Runs spent from today's budget.

    `starts` are the start times this process remembers; `posted` is how many
    route letters the command log holds for the same day, which survives a
    restart that the memory does not. The larger of the two is spent.
    """
    recent = sum(1 for t in starts or () if float(now) - float(t) < DAY_SECONDS)
    return max(recent, int(posted or 0))


def _family_option(route):
    """The best-ranked family receiver on this route, or None."""
    for option in (route,) + tuple(getattr(route, "alternates", ()) or ()):
        if option.family:
            return option
    return None


def plan_mail_runs(
    routes,
    walkers,
    running,
    spent,
    max_yards=MAIL_RUN_YARDS,
    per_day=MAIL_RUNS_PER_DAY,
) -> MailRunPlan:
    """Which waiting routes start a walk to a mailbox this pass.

    `routes` are the routes that could not happen in the world this pass,
    best gain first. `walkers` maps holder name to Walker. `running` holds
    the holders already on a run, `spent` the runs used today. Only a family
    receiver is posted to, because only the family's mail pass collects.
    One note per route that does not start a run, and never a `give`.
    """
    runs, notes = [], []
    busy = {str(n) for n in running or ()}
    budget = max(0, int(per_day) - int(spent))
    for route in routes or ():
        option = _family_option(route)
        if option is None:
            continue
        holder = str(route.holder)
        wait = "%s stays with %s" % (route.name, holder)
        if holder in busy:
            if not any(r.holder == holder for r in runs):
                notes.append("%s: %s is already walking to a mailbox" % (wait, holder))
            continue
        walker = walkers.get(holder)
        why = _cannot_walk(walker, holder, max_yards)
        if why:
            notes.append("%s: %s" % (wait, why))
            continue
        if len(runs) >= budget:
            notes.append(
                "%s: %d mail runs a day is the limit, and it is spent"
                % (wait, int(per_day))
            )
            continue
        runs.append(
            MailRun(
                holder=holder,
                taker=option.taker,
                item=route.name,
                guid=int(route.guid),
                gain=int(option.gain),
                cohort=walker.cohort,
                aim=walker.aim,
                yards=float(walker.yards),
            )
        )
        busy.add(holder)
    return MailRunPlan(runs=tuple(runs), notes=tuple(notes))


def _cannot_walk(walker, holder, max_yards) -> str:
    """Why this holder is not walked to a mailbox now, "" when it can be."""
    if walker is None or walker.map_id is None:
        return "%s is not in the world" % holder
    if walker.unwalkable:
        return "%s is %s" % (holder, walker.unwalkable)
    if walker.in_combat:
        return "%s is in combat" % holder
    if walker.map_id not in dungeonplan.CONTINENT_MAPS:
        return "%s is inside an instance" % holder
    if not walker.aim or walker.yards is None:
        return "no mailbox can be walked to: %s" % (walker.no_aim or "none on its map")
    if walker.yards > float(max_yards):
        return "the nearest mailbox is %d yards away, past the %d a run may walk" % (
            int(round(walker.yards)),
            int(max_yards),
        )
    return ""

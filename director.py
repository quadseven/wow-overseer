"""The Watcher's director: who the observer character follows, and when it moves.

Pure module, the same seam as relay and guildrun: rows in, decisions out. No
database, no network, no clock read except the `now` the caller passes. The
bridge owns the loop and the writes (`_watch_loop`), the map server owns the
operator's HTTP door; both hand the SAME mandate row to this module.

WHAT THE WATCHER IS. One real client session logged in as a GM character, kept
invisible and flying, that the operator points at somebody ("watch Grug",
"watch dungeon ragefire") so the stream of that session shows them. It is a
camera, not a player: it never fights, loots, speaks or joins a group.

THE ONE CHANNEL. A dot-command reaches a client character the way every other
GM line in this project does: an `overseer_command` row of kind 'gm', which
mod-overseer runs through that character's own session at its own security
level (DoGmCommand). Nothing here opens a second road. `/follow` is different
in kind: it is a CLIENT command the worldserver never sees, so no row can carry
it. This module therefore does its smooth following with `.appear` and says,
as a hint, what the client-side command would be.

WHY AN ALLOW-LIST OF OBSERVER COMMANDS AND NOT relay.GM_ALLOWED_PREFIXES. That
list is generous on purpose (it moves and heals other characters, and admits
`group`). The Watcher must be able to do exactly two things to the world: put
itself into the observer state, and move itself next to someone. `observer_allows`
is that list, in full, and the bridge refuses to queue any line that fails it.

WHAT THE CORE DOES WITH `.appear` (azerothcore-wotlk cs_misc.cpp, the pinned
build):

  - to yourself: refused.
  - to a target in a battleground or arena: only with `.gm on`; the GM is added
    to that battleground. This module refuses arenas outright, because walking
    into a rated match as a participant is not observing it.
  - to a target in a dungeon: refused when the GM is in a group that is not the
    target's, and refused when the GM is not in GM mode and has no group. In
    GM mode the entry checks (level, key, full instance, raid in combat) are
    all bypassed (MapMgr::PlayerCannotEnter, InstanceMap::CannotEnter).
  - the GM is bound to the target's instance when it has no bind for that
    map and difficulty. A bind it already holds WINS: the GM is sent to its
    own bound instance, not the target's. Hence `.instance unbind all` before
    every appear into an instance from outside it (it skips the map the GM is
    standing in, so it cannot be run from inside).
  - a teleport to the SAME map id is a near teleport and stays in the GM's own
    instance, so moving between two instances of one map needs a hop out first.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

WATCHER_NAME = os.environ.get("OVERSEER_WATCHER_NAME", "Watcher").strip() or "Watcher"

_NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")

# ---------------------------------------------------------------- allow-list --

MAX_SPEED = 6.0
FLY_SPEED = 3.0

# The state the Watcher is put in at every login. GM mode makes it unattackable
# and bots and creatures ignore it; `visible off` hides it from every non-GM;
# `chat off` drops the staff badge; `whispers off` stops anyone talking to it;
# `fly on` lets it hover over anything; `cheat god on` is the belt to GM mode's
# braces. All names checked against the live `command` table.
BOOT_COMMANDS = (
    ".gm on",
    ".gm visible off",
    ".gm chat off",
    ".whispers off",
    ".gm fly on",
    ".cheat god on",
    f".modify speed all {FLY_SPEED:g}",
)

# Where a hop out of an instance lands. Eastern Kingdoms, so never an instance.
HOP_COMMAND = ".tele stormwind"
UNBIND_COMMAND = ".instance unbind all"

_FIXED = frozenset(
    c.lstrip(".")
    for c in BOOT_COMMANDS
    if not c.startswith(".modify")
) | {HOP_COMMAND.lstrip("."), UNBIND_COMMAND.lstrip(".")}
_APPEAR_RE = re.compile(r"^appear [a-z]{2,12}$")
_SPEED_RE = re.compile(r"^modify speed all ([0-9]{1,2}(?:\.[0-9])?)$")
_WS = re.compile(r"\s+")


def _normalize(command: str) -> str:
    return _WS.sub(" ", (command or "").strip().lstrip(".").strip()).lower()


def observer_allows(command: str) -> bool:
    """Is this the Watcher's to run? Whole-line match, never a prefix."""
    body = _normalize(command)
    if body in _FIXED or _APPEAR_RE.match(body):
        return True
    m = _SPEED_RE.match(body)
    return bool(m) and 0.1 <= float(m.group(1)) <= MAX_SPEED


def is_watcher(name: str) -> bool:
    return (name or "").strip().lower() == WATCHER_NAME.lower()


# ------------------------------------------------------------------- the world --

BATTLEGROUND_MAPS = frozenset({30, 489, 529, 566, 607, 628})
ARENA_MAPS = frozenset({559, 562, 572, 617, 618})
RAID_MAPS = frozenset({
    249, 309, 409, 469, 509, 531, 532, 533, 534, 544, 548, 550, 564, 565, 568,
    580, 603, 615, 616, 624, 631, 649, 724,
})
# Instance maps by id, for the one case instance_id cannot answer: a target on
# an instance map whose instance has not been assigned a row yet.
INSTANCE_MAPS = BATTLEGROUND_MAPS | ARENA_MAPS | RAID_MAPS | frozenset({
    33, 34, 36, 43, 47, 48, 70, 90, 109, 129, 189, 209, 229, 230, 289, 329,
    349, 389, 429, 540, 542, 543, 545, 546, 547, 552, 553, 554, 555, 556, 557,
    558, 560, 574, 575, 576, 578, 585, 595, 599, 600, 601, 602, 604, 608, 619,
    632, 650, 658, 668,
})

# /follow gives up past about forty yards; inside this the camera is held.
FOLLOW_RANGE = 35.0
MIN_APPEAR_GAP = 15.0
APPEAR_BUDGET = (12, 600.0)  # at most 12 moves in any 600 seconds
MANDATE_TTL = 1800  # seconds an order lives without being renewed
BOOT_SETTLE = 8.0  # seconds after queuing the boot lines before moving

# Refusal codes. The text is what the operator reads.
R_WATCHER_OFFLINE = "watcher_offline"
R_TARGET_OFFLINE = "target_offline"
R_SELF = "self"
R_ARENA = "arena"
R_GROUPED = "watcher_grouped"
R_UNRESOLVED = "instance_unresolved"
R_NO_TARGET = "no_target"
R_RATE = "rate_limited"
R_SETTLING = "settling"

REFUSALS = {
    R_WATCHER_OFFLINE: "the Watcher is not in the world (its client is not logged in)",
    R_TARGET_OFFLINE: "the target is not in the world",
    R_SELF: "the target is the Watcher itself",
    R_ARENA: "the target is in an arena; the Watcher does not enter a match as a participant",
    R_GROUPED: "the Watcher is in a group, and the core refuses `.appear` into a dungeon "
               "unless the GM is in the target's own group; the Watcher never joins one, "
               "so a group means something invited it and it must leave first",
    R_UNRESOLVED: "the target stands on an instance map whose instance is not resolved yet; "
                  "trying again when it is",
    R_NO_TARGET: "nothing to watch matches that",
    R_RATE: "moves are rate limited",
    R_SETTLING: "the Watcher is still taking up its observer state",
}


@dataclass(frozen=True)
class Spot:
    """One character's row in the world snapshot, only what the director reads."""

    name: str
    map_id: int = 0
    instance_id: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    in_combat: bool = False
    group_leader: int = 0

    @property
    def place(self) -> tuple[int, int]:
        return (self.map_id, self.instance_id)

    def distance(self, other: "Spot") -> float:
        return math.dist((self.x, self.y, self.z), (other.x, other.y, other.z))


def spot_from_row(row: Mapping) -> Spot:
    return Spot(
        name=str(row["name"]),
        map_id=int(row.get("map_id") or 0),
        instance_id=int(row.get("instance_id") or 0),
        x=float(row.get("pos_x") or 0),
        y=float(row.get("pos_y") or 0),
        z=float(row.get("pos_z") or 0),
        in_combat=bool(row.get("in_combat")),
        group_leader=int(row.get("group_leader") or 0),
    )


@dataclass(frozen=True)
class Run:
    """A guild run as overseer_guild_run records it."""

    id: int
    guild: str
    keyword: str
    tank: str
    members: tuple[str, ...]
    state: str
    created: float = 0.0


def run_from_row(row: Mapping) -> Run:
    members = tuple(
        part.split(":", 1)[0] for part in str(row.get("members") or "").split(",") if part
    )
    created = row.get("created")
    return Run(
        id=int(row["id"]),
        guild=str(row.get("guild") or ""),
        keyword=str(row.get("keyword") or ""),
        tank=str(row.get("tank") or ""),
        members=members,
        state=str(row.get("state") or ""),
        created=float(created) if created is not None else 0.0,
    )


# ------------------------------------------------------------------- the order --

KINDS = ("character", "family", "guild", "run", "dungeon", "bg", "raid", "off")

USAGE = (
    "watch <character> | family [key] | guild <name> | run <id> | "
    "dungeon <keyword> | bg | raid | off"
)


@dataclass(frozen=True)
class Spec:
    kind: str
    arg: str = ""

    def text(self) -> str:
        return f"{self.kind} {self.arg}".strip()


@dataclass(frozen=True)
class SpecError:
    why: str


@dataclass(frozen=True)
class WatchDirective:
    """The operator's order, as Discord or the HTTP door hands it over."""

    spec: str
    source: str


_KEYWORDS = {"family", "guild", "run", "dungeon", "bg", "battleground", "raid",
             "off", "stop", "clear", "character", "char"}
_WORD_RE = re.compile(r"^[a-z][a-z-]{1,31}$")
_GUILD_RE = re.compile(r"^[A-Za-z][A-Za-z' ]{1,23}$")


def parse_watch(text: str) -> Spec | SpecError:
    """The grammar of an order. `watch` in front is optional."""
    words = (text or "").strip().split()
    if words and words[0].lower() == "watch":
        words = words[1:]
    if not words:
        return SpecError(f"watch what? {USAGE}")
    head, rest = words[0].lower(), " ".join(words[1:]).strip()
    if head in ("off", "stop", "clear"):
        return Spec("off")
    if head in ("bg", "battleground"):
        return Spec("bg")
    if head == "raid":
        return Spec("raid")
    if head in ("character", "char"):
        return Spec("character", rest) if _NAME_RE.match(rest) else SpecError(
            f"'{rest}' is not a character name. {USAGE}")
    if head == "family":
        if rest and not _WORD_RE.match(rest.lower()):
            return SpecError(f"'{rest}' is not a family key. {USAGE}")
        return Spec("family", rest.lower())
    if head == "guild":
        return Spec("guild", rest) if _GUILD_RE.match(rest) else SpecError(
            f"'{rest}' is not a guild name. {USAGE}")
    if head == "run":
        return Spec("run", rest) if rest.isdigit() and len(rest) <= 9 else SpecError(
            f"'{rest}' is not a run id. {USAGE}")
    if head == "dungeon":
        return Spec("dungeon", rest.lower()) if _WORD_RE.match(rest.lower()) else SpecError(
            f"'{rest}' is not a dungeon keyword. {USAGE}")
    if not rest and _NAME_RE.match(words[0]) and head not in _KEYWORDS:
        return Spec("character", words[0])
    return SpecError(f"I do not know how to watch '{text.strip()}'. {USAGE}")


def parse_watch_message(text: str):
    """A Discord line that starts with `watch`, or None for anything else."""
    stripped = (text or "").strip()
    if not stripped.lower().startswith("watch") or (
        len(stripped) > 5 and not stripped[5].isspace()
    ):
        return None
    return stripped


# -------------------------------------------------------------- target choice --


@dataclass(frozen=True)
class Pick:
    name: str
    why: str


@dataclass(frozen=True)
class Refused:
    code: str
    text: str


def _present(names: Iterable[str], by_name: Mapping[str, Spot]) -> list[str]:
    return [n for n in names if n in by_name]


def _fight_centre(spots: Sequence[Spot]) -> Spot:
    """The player with the most fighters within 40 yards, in-combat first.

    A flag carrier is not in the snapshot, and nothing here pretends it is: the
    fight is the next best thing to point a camera at.
    """
    def crowd(s: Spot) -> int:
        return sum(1 for o in spots if o.in_combat and s.distance(o) <= 40.0)

    return sorted(spots, key=lambda s: (-int(s.in_combat), -crowd(s), s.name))[0]


def _biggest_place(spots: Sequence[Spot]) -> list[Spot]:
    places: dict = {}
    for s in spots:
        places.setdefault(s.place, []).append(s)
    if not places:
        return []
    return sorted(places.values(), key=lambda g: (-len(g), g[0].place))[0]


def _run_pick(runs: Sequence[Run], by_name: Mapping[str, Spot], current: str, label: str):
    inside = [r for r in runs if r.state == "inside"]
    if not inside:
        return Refused(R_NO_TARGET, f"no {label} run is inside a dungeon right now")

    def here(r: Run) -> list[str]:
        return [
            n for n in dict.fromkeys((r.tank, *r.members))
            if n in by_name and by_name[n].instance_id > 0
        ]

    ranked = sorted(inside, key=lambda r: (-len(here(r)), -r.created, -r.id))
    for run in ranked:
        names = here(run)
        if names:
            keep = current if current in names else names[0]
            who = "tank" if keep == run.tank else "member"
            return Pick(keep, f"{who} of {run.guild} run {run.id} ({run.keyword})")
    return Refused(R_NO_TARGET, f"no {label} run has a member inside yet")


def pick_target(
    spec: Spec,
    spots: Sequence[Spot],
    *,
    runs: Sequence[Run] = (),
    seats: Sequence[tuple[str, str]] = (),
    heads: Mapping[str, str] | None = None,
    current: str = "",
) -> Pick | Refused:
    """Who the Watcher should be beside, from the order and the world."""
    by_name = {s.name: s for s in spots if not is_watcher(s.name)}
    kind = spec.kind
    if kind == "character":
        lowered = {n.lower(): n for n in by_name}
        name = lowered.get(spec.arg.lower())
        if name is None:
            return Refused(R_TARGET_OFFLINE, f"{spec.arg} is not in the world")
        return Pick(name, "the named character")
    if kind == "family":
        table = dict(heads or {})
        if not table:
            return Refused(R_NO_TARGET, "no family has a head on record")
        key = spec.arg or next(iter(table))
        head = table.get(key)
        if head is None:
            return Refused(R_NO_TARGET, f"no family '{key}' ({', '.join(table)})")
        if head not in by_name:
            return Refused(R_TARGET_OFFLINE, f"{head}, head of the {key} family, is not in the world")
        return Pick(head, f"head of the {key} family")
    if kind == "guild":
        mine = [r for r in runs if r.guild.lower() == spec.arg.lower()]
        return _run_pick(mine, by_name, current, spec.arg)
    if kind == "dungeon":
        mine = [r for r in runs if spec.arg in r.keyword.lower()]
        return _run_pick(mine, by_name, current, spec.arg)
    if kind == "run":
        run = next((r for r in runs if r.id == int(spec.arg)), None)
        if run is None:
            return Refused(R_NO_TARGET, f"there is no run {spec.arg}")
        if run.state != "inside":
            return Refused(R_NO_TARGET, f"run {run.id} is {run.state or 'not inside'}, not in a dungeon")
        return _run_pick([run], by_name, current, f"run {run.id}")
    if kind == "bg":
        group = _biggest_place([s for s in by_name.values() if s.map_id in BATTLEGROUND_MAPS])
        if not group:
            return Refused(R_NO_TARGET, "no battleground has anyone in it")
        names = [s.name for s in group]
        if current in names:
            return Pick(current, "still in the biggest battleground")
        return Pick(_fight_centre(group).name, "the middle of the fight in the fullest battleground")
    if kind == "raid":
        group = _biggest_place([s for s in by_name.values() if s.map_id in RAID_MAPS])
        if not group:
            return Refused(R_NO_TARGET, "no raid has anyone in it")
        names = [s.name for s in group]
        if current in names:
            return Pick(current, "still in the fullest raid")
        tanks = [n for n, role in seats if role == "tank" and n in names]
        if tanks:
            return Pick(sorted(tanks)[0], "a tank of the fullest raid")
        return Pick(_fight_centre(group).name, "the middle of the fight in the fullest raid")
    return Refused(R_NO_TARGET, USAGE)


# ----------------------------------------------------------------- the decision --

BOOT, HOLD, FOLLOW, HOP, APPEAR, REFUSE = "boot", "hold", "follow", "hop", "appear", "refuse"


@dataclass(frozen=True)
class Decision:
    action: str
    commands: tuple[str, ...] = ()
    reason: str = ""
    code: str = ""
    client_hint: str = ""


def _is_instance(spot: Spot) -> bool:
    return spot.instance_id > 0 or spot.map_id in INSTANCE_MAPS


def _budget_left(moves: Sequence[float], now: float) -> bool:
    count, window = APPEAR_BUDGET
    return sum(1 for t in moves if now - t < window) < count


def _refuse(code: str) -> Decision:
    return Decision(REFUSE, reason=REFUSALS[code], code=code)


def decide(
    watcher: Spot | None,
    target: Spot | None,
    *,
    now: float,
    moves: Sequence[float] = (),
    booted_at: float | None = None,
    new_target: bool = False,
) -> Decision:
    """What to do this tick. The only function that turns a world into commands.

    `moves` are the times of the Watcher's past `.appear`/hop commands, the
    rate limiter's whole memory. `booted_at` is when the observer lines were
    last queued (None means they have not been since the last login).
    """
    if watcher is None:
        return _refuse(R_WATCHER_OFFLINE)
    if target is None:
        return _refuse(R_TARGET_OFFLINE)
    if is_watcher(target.name):
        return _refuse(R_SELF)
    if target.map_id in ARENA_MAPS:
        return _refuse(R_ARENA)
    if watcher.group_leader:
        return _refuse(R_GROUPED)
    if booted_at is None:
        return Decision(BOOT, BOOT_COMMANDS, "putting the Watcher into its observer state")
    if now - booted_at < BOOT_SETTLE:
        return Decision(HOLD, reason=REFUSALS[R_SETTLING], code=R_SETTLING)
    if target.map_id in INSTANCE_MAPS and target.instance_id == 0:
        return _refuse(R_UNRESOLVED)

    hint = f"/follow {target.name}"
    if watcher.place == target.place and watcher.distance(target) <= FOLLOW_RANGE:
        return Decision(FOLLOW, reason=f"within {FOLLOW_RANGE:g} yards of {target.name}",
                        client_hint=hint)

    last = max(moves, default=None)
    if not new_target and last is not None and now - last < MIN_APPEAR_GAP:
        return Decision(HOLD, reason=REFUSALS[R_RATE], code=R_RATE)
    if not _budget_left(moves, now):
        return Decision(HOLD, reason=REFUSALS[R_RATE] + " (budget spent)", code=R_RATE)

    appear = f".appear {target.name}"
    if _is_instance(target):
        if watcher.map_id == target.map_id and watcher.instance_id != target.instance_id:
            return Decision(HOP, (HOP_COMMAND,),
                            f"leaving this instance of map {watcher.map_id} first, because "
                            "a teleport within a map stays in the instance the GM is in",
                            client_hint=hint)
        if watcher.place == target.place:
            return Decision(APPEAR, (appear,), f"{target.name} moved away", client_hint=hint)
        if target.map_id in BATTLEGROUND_MAPS:
            # Battlegrounds take no instance bind, so there is nothing to drop.
            return Decision(APPEAR, (appear,), f"into {target.name}'s battleground",
                            client_hint=hint)
        return Decision(APPEAR, (UNBIND_COMMAND, appear),
                        f"into {target.name}'s instance (stale binds dropped first)",
                        client_hint=hint)
    return Decision(APPEAR, (appear,), f"to {target.name}", client_hint=hint)


def commands_ok(commands: Iterable[str]) -> bool:
    return all(observer_allows(c) for c in commands)


# --------------------------------------------------------------------- storage --

CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_watch ("
    " id TINYINT UNSIGNED NOT NULL,"
    " spec VARCHAR(48) NOT NULL,"
    " set_by VARCHAR(48) NOT NULL,"
    " set_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " expires_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " target VARCHAR(12) NOT NULL DEFAULT '',"
    " note VARCHAR(255) NOT NULL DEFAULT '',"
    " PRIMARY KEY (id)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)

# One row, id 1. The order and its renewal; the loop writes target and note.
SET_SQL = (
    "INSERT INTO overseer_watch (id, spec, set_by, set_at, expires_at, target, note) "
    "VALUES (1, %s, %s, NOW(), NOW() + INTERVAL %s SECOND, '', 'ordered') "
    "ON DUPLICATE KEY UPDATE spec = VALUES(spec), set_by = VALUES(set_by), "
    "set_at = VALUES(set_at), expires_at = VALUES(expires_at), target = '', note = 'ordered'"
)
CLEAR_SQL = "UPDATE overseer_watch SET expires_at = NOW(), target = '', note = 'stopped' WHERE id = 1"
READ_SQL = (
    "SELECT spec, set_by, target, note, "
    "GREATEST(0, UNIX_TIMESTAMP(expires_at) - UNIX_TIMESTAMP()) AS ttl "
    "FROM overseer_watch WHERE id = 1"
)
NOTE_SQL = "UPDATE overseer_watch SET target = %s, note = %s WHERE id = 1 AND spec = %s"


def mandate_active(row: Mapping | None) -> bool:
    return bool(row) and int(row.get("ttl") or 0) > 0


@dataclass
class Memory:
    """What the loop remembers between ticks (in memory: a restart re-boots)."""

    target: str = ""
    spec: str = ""
    moves: list[float] = field(default_factory=list)
    booted_at: float | None = None
    was_present: bool = False

    def on_presence(self, present: bool) -> None:
        """A fresh login needs the observer lines again: the state is not
        guaranteed to survive a relog, and the lines are idempotent."""
        if present and not self.was_present:
            self.booted_at = None
        self.was_present = present

    def on_order(self, spec: str) -> bool:
        """True when the order changed, which resets the target."""
        changed = spec != self.spec
        if changed:
            self.spec, self.target = spec, ""
        return changed

    def record_move(self, now: float) -> None:
        self.moves = [t for t in self.moves if now - t < APPEAR_BUDGET[1]] + [now]

"""How a family gets itself moving again, asked of Jev the way players decide.

WHY THIS EXISTS. The operator: "Please use Jev for movement decisions like a
human." mod-overseer already walks, routes, flies, holds a leader for a
straggler and gives up a walk that stops closing, each by a fixed rule. What
no rule does is the thing a group of players does when the rules have run
out: a member stuck at the bottom of a crater hearths home, a family that
keeps dying on the way to an errand drops it, a family scattered across a
zone meets at the inn. Each of those has a road the world already carries
out, which makes the choice between them a closed Choice, and that is Jev's
shape.

WHAT JEV IS OFFERED. Only what can be carried out now (`options`):

  carry_on          change nothing. The module's own catch-up walk, regroup
                    hold, route planning and stall give-up go on. Always
                    offered, and today's answer (`heuristic`).
  hearth_straggler  one member who is far from the leader and not moving
                    uses the hearthstone (kind='hearth'). Offered only when
                    that member stands still, is alive, is out of combat, has
                    not hearthed in the last hour, and is bound somewhere on
                    the leader's map that is nearer the leader than it is now.
  hearth_family     every member hearths, and the family meets at the inn.
                    Offered only when every member is bound within
                    INN_YARDS of one another, all are alive, out of combat,
                    standing still, and none hearthed in the last hour.
  hearth_to_leader  every member far from the leader whose hearthstone point
                    is within INN_YARDS of where the leader stands hearths,
                    walking or not (#297). Offered for those alive, out of
                    combat, not in flight, and not hearthed in the last hour.
                    A player bound at the inn the family waits at does not
                    walk 5,000 yards back to it.
  drop_errand       the leader's walk is given up: the travel column is
                    released (compare-and-swap on the aim) and the pass that
                    wrote it is not given that aim again for townslot's
                    SPENT_SECONDS. Offered only while the column holds an aim
                    this process wrote.

WHEN IT IS ASKED. Only when something is wrong (`trouble`): a member far from
the leader and not moving, a member far from a leader who stands at its
hearthstone point, a leader stuck or circling with a goal it has not reached,
or the family dying. Never during a dungeon run or a dungeon job:
those belong to run recovery and the campaign's own staging.

ACT BY DEFAULT, behind DEFAULT_THRESHOLD (JEV_MODE_MOVEMENT and
JEV_THRESHOLD_MOVEMENT override both). Below it, or with no answer, the
heuristic stands, and the heuristic is carry_on, so a low-confidence answer
changes nothing in the world.

PURE: facts in, questions and judgments out; the only I/O is the client the
caller hands in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

import jev
import situation

KIND = "movement"
DEFAULT_THRESHOLD = 0.75
SOURCE = "overseer:movement"

CARRY_ON = "carry_on"
HEARTH_STRAGGLER = "hearth_straggler"
HEARTH_FAMILY = "hearth_family"
HEARTH_TO_LEADER = "hearth_to_leader"
DROP_ERRAND = "drop_errand"
OPTIONS = (CARRY_ON, HEARTH_STRAGGLER, HEARTH_FAMILY, HEARTH_TO_LEADER, DROP_ERRAND)

# A member this far from the leader, and not moving, is stranded.
STRANDED_YARDS = 300.0
# Every member bound within this of the first is bound at one inn.
INN_YARDS = 100.0
# Deaths in the situation's window that make a family "dying".
DYING_DEATHS = 2
# The hearthstone's own cooldown in 3.3.5a.
HEARTH_COOLDOWN_SECONDS = 3600
# At most one question per family this often, and after an act, nothing
# again for this long, so a choice has time to play out.
ASK_SECONDS = 300.0
ACT_COOLDOWN_SECONDS = 1200.0

NOT_MOVING = frozenset({situation.STILL, situation.STUCK})
# A hearthstone cannot be used on a flight or mid-teleport.
IN_TRANSIT = frozenset({situation.FLYING, situation.TELEPORTED})
LOST = frozenset({situation.STUCK, situation.CIRCLING})


def policy(environ=None) -> jev.Policy:
    return jev.policy(
        KIND,
        environ=environ,
        default_mode=jev.ACT,
        default_threshold=DEFAULT_THRESHOLD,
    )


@dataclass(frozen=True)
class Facts:
    """Everything the question carries about one family, read this cycle.

    `where` is the family's situation.Situation. `binds` maps a member to its
    hearthstone point (character_homebind) as a situation.Point. `hearthed`
    is the members that used a hearthstone in the last hour. `errand` is the
    travel column holder's aim when this process wrote it, else "".
    """

    family: str
    where: situation.Situation
    binds: dict = field(default_factory=dict)
    hearthed: frozenset = frozenset()
    errand: str = ""
    claimant: str = ""


def _body(f: Facts, name: str):
    return next((b for b in f.where.bodies if b.name == name), None)


def _free_to_hearth(f: Facts, name: str) -> bool:
    """Alive, seen, out of combat, not in transit, and its hearthstone ready."""
    b = _body(f, name)
    return (
        b is not None
        and b.at is not None
        and not b.dead
        and not b.in_combat
        and f.where.progress.get(name) not in IN_TRANSIT
        and name not in f.hearthed
        and name in f.binds
    )


def _ready(f: Facts, name: str) -> bool:
    """Free to hearth, and standing still."""
    return _free_to_hearth(f, name) and f.where.progress.get(name) in NOT_MOVING


def stranded(f: Facts) -> str:
    """The farthest member who is stranded and whose inn is nearer the leader,
    or ""."""
    lead = f.where.lead_body
    if lead is None or lead.at is None:
        return ""
    best, best_yards = "", 0.0
    for b in f.where.bodies:
        if b.name == f.where.leader or not _ready(f, b.name):
            continue
        d = situation.yards(lead.at, b.at)
        far = 1e9 if d is None else d
        if far < STRANDED_YARDS:
            continue
        home = situation.yards(lead.at, f.binds[b.name])
        if home is None or home >= far:
            continue
        if far > best_yards:
            best, best_yards = b.name, far
    return best


def homeward(f: Facts) -> tuple:
    """Far members whose hearthstone lands them at the leader, sorted (#297).

    Walking or not. Measured on wow-dev 2026-09-24: the Horde leader stood 68
    yards from the hearth point three of its four members share, and they
    walked 3,900 to 6,600 yards back to it, one through a hostile town where it
    died twice. Neither hearth option was offered, because `stranded` wants a
    member standing still and `one_inn` wants every member bound at one inn.

    THE LEADER MUST BE STANDING THERE, not passing by: a member hearthed to an
    inn the leader walks on from is a member left behind somewhere new. The
    live leader was held still for the regroup.
    """
    lead = f.where.lead_body
    if lead is None or lead.at is None:
        return ()
    if f.where.progress.get(f.where.leader) not in NOT_MOVING:
        return ()
    out = []
    for b in f.where.bodies:
        if b.name == f.where.leader or not _free_to_hearth(f, b.name):
            continue
        d = situation.yards(lead.at, b.at)
        if d is not None and d < STRANDED_YARDS:
            continue
        home = situation.yards(lead.at, f.binds[b.name])
        if home is not None and home <= INN_YARDS:
            out.append(b.name)
    return tuple(sorted(out))


def one_inn(f: Facts) -> bool:
    """Every member ready to hearth, and all bound at one inn."""
    names = [b.name for b in f.where.bodies]
    if not names or not all(_ready(f, n) for n in names):
        return False
    first = f.binds[names[0]]
    gaps = [situation.yards(first, f.binds[n]) for n in names]
    return all(g is not None and g <= INN_YARDS for g in gaps)


def trouble(f: Facts) -> str:
    """Why the family's movement needs a decision now, or ""."""
    why = []
    far = f.where.cohesion.get("far_from_leader") or []
    if far and any(f.where.progress.get(n) in NOT_MOVING for n in _far_names(f)):
        why.append("a member is far from the leader and not moving")
    home = homeward(f)
    if home:
        why.append(
            "%s far from the leader, who stands at %s hearthstone point"
            % (", ".join(home), "its" if len(home) == 1 else "their")
        )
    if f.where.progress.get(f.where.leader) in LOST and f.where.goal is not None:
        why.append("the leader is %s" % f.where.progress[f.where.leader])
    deaths = (f.where.deaths or {}).get("count", 0)
    if deaths >= DYING_DEATHS:
        why.append("%d deaths in the last 30 minutes" % deaths)
    return "; ".join(why)


def _far_names(f: Facts) -> list:
    lead = f.where.lead_body
    if lead is None or lead.at is None:
        return []
    out = []
    for b in f.where.bodies:
        if b.name == f.where.leader or b.at is None:
            continue
        d = situation.yards(lead.at, b.at)
        if d is None or d > situation.FAR_YARDS:
            out.append(b.name)
    return out


def options(f: Facts) -> dict:
    """option -> what it means, for this family now. carry_on always."""
    out = {
        CARRY_ON: "Change nothing: keep walking, following and holding for "
        "stragglers the way the family already is."
    }
    who = stranded(f)
    if who:
        out[HEARTH_STRAGGLER] = (
            "%s, far from the leader and not moving, uses the hearthstone to "
            "get back to its inn, which is nearer the family, and walks on "
            "from there." % who
        )
    home = homeward(f)
    if home:
        out[HEARTH_TO_LEADER] = (
            "%s, far from the leader, %s the hearthstone and %s back beside "
            "the leader, who stands at %s hearthstone point, instead of "
            "walking the whole way."
            % (
                ", ".join(home),
                "uses" if len(home) == 1 else "use",
                "is" if len(home) == 1 else "are",
                "its" if len(home) == 1 else "their",
            )
        )
    if one_inn(f):
        out[HEARTH_FAMILY] = (
            "Everybody uses the hearthstone and the family meets again at "
            "the inn they are all bound to."
        )
    if f.errand:
        out[DROP_ERRAND] = (
            "The leader gives up the walk to %s for now, and the family goes "
            "back to what it was doing." % f.errand
        )
    return out


def heuristic(f: Facts) -> tuple:
    """Today's rules: the module's own drives decide. (answer, why)."""
    return CARRY_ON, "the module's catch-up walk, regroup hold and stall give-up"


def question(f: Facts, offered: dict):
    """(state, questions) for "what does the family do about how it moves"."""
    state = {
        "family": f.family,
        "situation": f.where.state(),
        "why_now": trouble(f),
    }
    if f.errand:
        state["errand_in_the_travel_column"] = {
            "aim": f.errand,
            "written_by": f.claimant or "unknown",
        }
    instructions = (
        "`family` is a group of World of Warcraft (3.3.5a) adventurers who "
        "play together the way a group of real human players does, and "
        "something is wrong with how they are moving (`why_now`). Choose what "
        "they do about it, as sensible players would: a member stuck far "
        "away with no way back uses the hearthstone; members far away whose "
        "hearthstone would put them beside the leader use it rather than "
        "walk the whole way; a family scattered "
        "across a zone or dying over and over meets again at its inn; a walk "
        "the family keeps failing to finish, or keeps dying on, is given up "
        "for now; and when the trouble is already being handled (the leader "
        "is waiting for a straggler who is walking back, or the family is "
        "moving and closing on its goal) they carry on." + situation.INSTRUCTION
    )
    return state, {"movement": jev.choice(instructions, dict(offered))}


# Read before the class: its `jev` field shadows the module in the class body.
_HEURISTIC = jev.HEURISTIC


@dataclass(frozen=True)
class Judgment:
    """One movement choice, shaped for overseer_jev_judgment."""

    subject: str
    heuristic: str
    heuristic_why: str
    mode: str
    status: str
    item_name: str = ""
    facts: str = ""
    jev: str = ""
    confidence: float | None = None
    probabilities: dict | None = None
    latency_ms: int = 0
    model: str = ""
    acted: str = _HEURISTIC
    kind: str = KIND
    item_guid: int = 0
    item_entry: int = 0
    straggler: str = ""
    homeward: tuple = ()

    @property
    def holder(self) -> str:
        return self.subject

    @property
    def agree(self) -> bool | None:
        return None if not self.jev else self.jev == self.heuristic

    def probabilities_json(self, limit: int = 1000) -> str:
        if not self.probabilities:
            return ""
        ranked = sorted(self.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
        text = json.dumps({k: round(v, 4) for k, v in ranked}, separators=(",", ":"))
        return text if len(text) <= limit else ""

    @property
    def carried_out(self) -> str:
        """The option to carry out, or "" when nothing changes."""
        if self.acted != jev.JEV or self.jev == CARRY_ON:
            return ""
        return self.jev

    def line(self) -> str:
        answer = (
            "jev=%s conf=%.2f" % (self.jev, self.confidence or 0.0)
            if self.jev
            else "jev=-"
        )
        chose = (
            "Jev chose %s" % self.jev
            if self.acted == jev.JEV
            else "today's rules stand (%s)" % self.heuristic
        )
        return (
            "movement: family=%s %s; kind=%s heuristic=%s %s status=%s "
            "latency_ms=%d mode=%s acted=%s why_now=%r facts=%r"
            % (
                self.subject,
                chose,
                self.kind,
                self.heuristic,
                answer,
                self.status,
                self.latency_ms,
                self.mode,
                self.acted,
                self.item_name,
                self.facts,
            )
        )


async def ask(client, f: Facts, rule: jev.Policy) -> Judgment | None:
    """Ask Jev how the family moves on; None when there is nothing to ask:
    the kind is off, nothing is wrong, or carry_on is the only option."""
    if rule.mode == jev.OFF:
        return None
    why = trouble(f)
    offered = options(f)
    if not why or len(offered) < 2:
        return None
    current, heuristic_why = heuristic(f)
    base = Judgment(
        subject=f.family,
        heuristic=current,
        heuristic_why=heuristic_why,
        mode=rule.mode,
        status="",
        item_name=why[:120],
        facts=f.where.line(1000),
        straggler=stranded(f),
        homeward=homeward(f),
    )
    state, questions = question(f, offered)
    outcome = await client.ask(KIND, state, questions)
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers["movement"]
    return replace(
        base,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        acted=rule.acted(
            current, answer.choice, answer.confidence, can_act=answer.choice in offered
        ),
    )

"""Step a wiping family down to a dungeon it can clear, and back up (mod-overseer#767).

WHY THIS EXISTS. For forty hours on wow-dev (2026-09-26 to 09-27) both
families ran the same doors and wiped: 2 of 273 recorded runs completed, 406
deaths in a day, and nobody gained a level. The queue re-asserted the
operator's door after every wipe, so the party walked back into the same
instance on a timer. A group of players does the other thing: after two wipes
it drops to an easier dungeon it can clear, farms it for gear and experience,
and comes back when it has grown.

WHAT IS JUDGED, PER DOOR. Only the runs that fought (`FOUGHT`): a staging,
reset or split failure never met a mob and says nothing about the door. The
runs counted are the ones since the queue entry last started, so a door the
family comes back to starts with a clean record.

  * a door is UNCLEARABLE after `STREAK_WIPES` wipes in a row, or when at
    least `RATE_MIN_RUNS` fought runs hold a wipe rate of `RATE_LIMIT` or more
    (`viability`);
  * a door is NOT READY when the weakest member is below the level it wants
    (`readiness`). Empty slots and a missing weapon are reported alongside,
    and given to Jev, but they gate nothing here: the gear hold (#146) owns
    that gate, and a second one would hold the family twice for one cause.

WHAT HAPPENS (`decide`).

  STEP DOWN   the door is unclearable or not ready: a planner entry for the
              hardest easier door the family can clear goes AHEAD of it in the
              queue (`STEP_DOWN_RUNS` runs). The operator's entry keeps its
              place, count and order; it is put back to `queued`, so it
              starts fresh when the step-down ends.
  FURTHER     the step-down door is itself unclearable: it is finished and the
              next easier door is queued ahead instead.
  STEP UP     a named change since the family stepped down (a level gained,
              an upgrade equipped) and the harder door is ready: the
              step-down entry is finished early and the operator's door runs
              next. Never on a timer.
  EXTEND      the step-down entry reached its count with no named change:
              it runs `STEP_DOWN_RUNS` more rather than send the family back
              into a door it wiped in with nothing changed.
  QUEST       no easier door can be cleared (the Horde family is already in
              Ragefire Chasm, the lowest rung): the family quests at its level
              until a named change and readiness bring it back. The queue
              entry stays active; only the job changes.
  RELEASE     the questing fallback ends the same way a step-up does.

WHICH EASIER DOOR (`candidates`, `ladder`). Every Run below the failing one in
campaignplan.RUNS (lowest band first), that council.door_refusal allows, whose
floor the weakest member has reached, that a key does not lock, and that the
weakest has not outgrown by more than `OUTGROWN_GRACE` levels. The ladder
picks the hardest. Jev is asked the same question over the same candidates
(a Choice with a confidence score) and is carried out past its floor
(`policy`); below it, or when Jev is off or slow, the ladder stands.

PURE MODULE: rows in, decisions and sentences out. The bridge reads, writes and
asks Jev; nothing here touches MySQL or the network except the Jev client the
caller hands in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

import campaignplan
import council
import jev

KIND = "dungeon_step"
DEFAULT_THRESHOLD = 0.6

# The source every step-down queue entry carries, so the queue line, the site
# and the Decree can tell it from an operator's order or the planner's.
SOURCE = campaignplan.SOURCE_STEPDOWN

# The job source for the questing fallback's writes.
JOB_SOURCE = "overseer:pace"

# Outcomes of a run that met the dungeon. Staging, reset, split and bag
# evacuation failures never fought anything.
FOUGHT = frozenset({"wipe", "complete", "left", "emptied", "stalled"})
WIPE = "wipe"
COMPLETE = "complete"

STREAK_WIPES = 2
RATE_MIN_RUNS = 3
RATE_LIMIT = 0.5
# How many of the latest fought runs the rate is taken over.
RATE_WINDOW = 6
# Runs older than this never count, even inside one long queue entry.
WINDOW_HOURS = 48

STEP_DOWN_RUNS = 5
# A run whose band tops out this many levels under the weakest member is still
# worth farming for gear while the family grows; past it, it is outgrown.
OUTGROWN_GRACE = 3
# An upgrade: a slot filled, or the worn item levels rising by this much.
UPGRADE_ITEM_LEVELS = 5

# Decisions, as the record names them.
STEP_DOWN = "step_down"
FURTHER = "further_down"
STEP_UP = "step_up"
EXTEND = "extend"
QUEST = "quest"
RELEASE = "release"
NOTHING = ""
# Decisions that leave a stretch open, to be closed by a step-up or release.
OPENS = (STEP_DOWN, FURTHER, QUEST)

# The Choice option that means "keep the door" when the rule allows it.
STAY = "stay"
# The Choice option for the questing fallback, offered only with no door.
LEVEL = "quest"

TABLE = "overseer_dungeon_pace"
CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_dungeon_pace ("
    " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " family VARCHAR(32) NOT NULL DEFAULT '',"
    " decision VARCHAR(16) NOT NULL,"
    " door VARCHAR(32) NOT NULL DEFAULT '',"
    " target VARCHAR(32) NOT NULL DEFAULT '',"
    " queue_id INT UNSIGNED NOT NULL DEFAULT 0,"
    " chosen_by VARCHAR(16) NOT NULL DEFAULT 'rule',"
    " confidence FLOAT NULL DEFAULT NULL,"
    " reason VARCHAR(255) NOT NULL DEFAULT '',"
    " baseline VARCHAR(1000) NOT NULL DEFAULT '',"
    " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " closed_at TIMESTAMP NULL DEFAULT NULL,"
    " outcome VARCHAR(255) NOT NULL DEFAULT '',"
    " PRIMARY KEY (id), KEY idx_family_open (family, closed_at)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)
OPEN_SQL = (
    "SELECT id, decision, door, target, queue_id, baseline, created_at "
    "FROM overseer_dungeon_pace WHERE family = %s AND closed_at IS NULL "
    "AND decision IN ('step_down', 'further_down', 'quest') "
    "ORDER BY id DESC LIMIT 1"
)
INSERT_SQL = (
    "INSERT INTO overseer_dungeon_pace (family, decision, door, target, "
    "queue_id, chosen_by, confidence, reason, baseline) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
CLOSE_SQL = (
    "UPDATE overseer_dungeon_pace SET closed_at = NOW(), outcome = %s "
    "WHERE id = %s AND closed_at IS NULL"
)
# A step-up's outcome is the first run that fights the harder door after it.
UNSCORED_SQL = (
    "SELECT id, door, created_at FROM overseer_dungeon_pace "
    "WHERE family = %s AND decision IN ('step_up', 'release') AND outcome = '' "
    "ORDER BY id"
)
SCORE_SQL = (
    "UPDATE overseer_dungeon_pace SET outcome = %s, closed_at = NOW() "
    "WHERE id = %s AND outcome = ''"
)
# The last time the family went back to each door: a door's record restarts there.
LAST_BACK_SQL = (
    "SELECT door, MAX(created_at) AS at FROM overseer_dungeon_pace "
    "WHERE family = %s AND decision IN ('step_up', 'release') GROUP BY door"
)
RUNS_SQL = (
    "SELECT id, map_id, outcome, started_at FROM overseer_dungeon_run "
    "WHERE state = 'ended' AND leader_name IN ({holes}) "
    "AND started_at >= NOW() - INTERVAL %s HOUR ORDER BY id"
)
QUEUE_STARTED_SQL = (
    "SELECT id, started_at FROM overseer_dungeon_queue WHERE id IN ({holes})"
)
MAIN_HAND_SQL = (
    "SELECT c.name FROM character_inventory ci JOIN characters c "
    "ON c.guid = ci.guid WHERE ci.bag = 0 AND ci.slot = 15 AND c.name IN ({holes})"
)
# Step down: make room at the head, queue the easier door there, and put the
# operator's running entry back to `queued` so it starts fresh after it.
SHIFT_SQL = (
    "UPDATE overseer_dungeon_queue SET position = position + 1 "
    "WHERE family = %s AND status IN ('queued', 'active')"
)
REQUEUE_SQL = (
    "UPDATE overseer_dungeon_queue SET status = 'queued', started_at = NULL "
    "WHERE id = %s AND status = 'active'"
)
EXTEND_SQL = (
    "UPDATE overseer_dungeon_queue SET runs_wanted = LEAST(runs_wanted + %s, "
    "65535) WHERE id = %s AND status = 'active' AND source = %s"
)


def holes(count: int) -> str:
    return ", ".join(["%s"] * max(int(count), 1))


def policy(environ=None) -> jev.Policy:
    """Act by default, at a 0.6 floor (JEV_MODE_/JEV_THRESHOLD_DUNGEON_STEP)."""
    return jev.policy(
        KIND,
        environ=environ,
        default_mode=jev.ACT,
        default_threshold=DEFAULT_THRESHOLD,
        on_agreement=True,
    )


# --- the record of a door -------------------------------------------------------


@dataclass(frozen=True)
class Viability:
    """What the fought runs on one door say."""

    fought: int
    wipes: int
    complete: int
    streak: int

    @property
    def rate(self) -> float:
        return self.wipes / self.fought if self.fought else 0.0

    @property
    def hard(self) -> bool:
        """Two wipes in a row: the next attempt waits for a named change."""
        return self.streak >= STREAK_WIPES

    @property
    def clearable(self) -> bool:
        if self.hard:
            return False
        return not (self.fought >= RATE_MIN_RUNS and self.rate >= RATE_LIMIT)

    def line(self) -> str:
        if not self.fought:
            return "no fought run yet"
        return "%d fought, %d wiped (%d%%), %d cleared, %d wipe%s in a row" % (
            self.fought,
            self.wipes,
            round(100 * self.rate),
            self.complete,
            self.streak,
            "" if self.streak == 1 else "s",
        )


def since(started, back):
    """The later of a queue entry's start and the family's last step back to it."""
    known = [t for t in (started, back) if t is not None]
    return max(known) if known else None


def viability(runs, map_id: int, since=None) -> Viability:
    """The door's record from ledger rows, oldest first.

    `since` drops rows that started before the queue entry did, compared as
    the database gave them (both are its own timestamps).
    """
    fought = [
        str(r.get("outcome") or "")
        for r in runs or ()
        if int(r.get("map_id") or 0) == int(map_id)
        and str(r.get("outcome") or "") in FOUGHT
        and (since is None or r.get("started_at") is None or r["started_at"] >= since)
    ]
    streak = 0
    for outcome in reversed(fought):
        if outcome != WIPE:
            break
        streak += 1
    window = fought[-RATE_WINDOW:]
    return Viability(
        fought=len(window),
        wipes=sum(1 for o in window if o == WIPE),
        complete=sum(1 for o in window if o == COMPLETE),
        streak=streak,
    )


# --- the family -----------------------------------------------------------------


@dataclass(frozen=True)
class Member:
    name: str
    level: int
    worn: int | None = None  # gear slots filled, None unread
    item_levels: float | None = None  # sum of worn item levels, None unread
    main_hand: bool | None = None


def members_from_rows(level_rows, gear_rows, main_hand_rows) -> tuple:
    """Members off LEVEL_ROWS_SQL, campaignplan.GEAR_SQL and MAIN_HAND_SQL."""
    gear = {str(r.get("name")): r for r in gear_rows or ()}
    armed = (
        None if main_hand_rows is None else {str(r.get("name")) for r in main_hand_rows}
    )
    out = []
    for row in level_rows or ():
        name = str(row.get("name") or "")
        if not name:
            continue
        g = gear.get(name)
        worn = None if gear_rows is None else int((g or {}).get("worn") or 0)
        total = (
            None
            if gear_rows is None
            else round(float((g or {}).get("item_level") or 0) * (worn or 0), 1)
        )
        out.append(
            Member(
                name=name,
                level=int(row.get("level") or 0),
                worn=worn,
                item_levels=total,
                main_hand=None if armed is None else name in armed,
            )
        )
    return tuple(sorted(out, key=lambda m: m.name))


def weakest(members) -> tuple:
    known = [(m.level, m.name) for m in members if m.level > 0]
    if not known:
        return "", 0
    level, name = min(known)
    return name, level


def readiness(keyword: str, members) -> tuple:
    """(gates, notes) for sending the family through `keyword`'s door.

    Gates hold the door: the weakest member below the level it wants. Notes
    are reported with them and never hold it: slots empty, no main-hand
    weapon (the gear hold, #146, owns those).
    """
    gates, notes = [], []
    who, level = weakest(members)
    floor = (
        campaignplan.BY_KEYWORD[keyword].floor
        if keyword in campaignplan.BY_KEYWORD
        else 0
    )
    if who and floor and level < floor:
        gates.append(
            "%s is level %d and %s wants %d"
            % (who, level, council.keyword_place(keyword), floor)
        )
    bare = sorted(m.name for m in members if m.main_hand is False)
    if bare:
        notes.append("no main-hand weapon: %s" % ", ".join(bare))
    empty = [
        "%s %d" % (m.name, len(campaignplan.GEAR_SLOTS) - m.worn)
        for m in members
        if m.worn is not None and len(campaignplan.GEAR_SLOTS) - m.worn >= 6
    ]
    if empty:
        notes.append("six or more empty slots: %s" % ", ".join(sorted(empty)))
    return tuple(gates), tuple(notes)


def baseline(members) -> str:
    """The family as it stands, for `named_change` to compare against later."""
    return json.dumps(
        {m.name: [m.level, m.worn, m.item_levels] for m in members},
        separators=(",", ":"),
        sort_keys=True,
    )[:1000]


def named_change(saved: str, members) -> str:
    """What has changed since `saved` that is worth another try, or ""."""
    try:
        before = json.loads(saved or "{}")
    except ValueError:
        return ""
    levels, upgrades = [], []
    for m in members:
        was = before.get(m.name)
        if not was:
            continue
        level, worn, total = (list(was) + [None, None, None])[:3]
        if level is not None and m.level > int(level):
            levels.append("%s %d -> %d" % (m.name, int(level), m.level))
        if worn is not None and m.worn is not None and m.worn > int(worn):
            upgrades.append("%s filled %d slot(s)" % (m.name, m.worn - int(worn)))
        elif (
            total is not None
            and m.item_levels is not None
            and m.item_levels - float(total) >= UPGRADE_ITEM_LEVELS
        ):
            upgrades.append(
                "%s +%d item levels" % (m.name, round(m.item_levels - float(total)))
            )
    parts = []
    if levels:
        parts.append("level gained: " + ", ".join(levels))
    if upgrades:
        parts.append("upgrade equipped: " + ", ".join(upgrades))
    return "; ".join(parts)


# --- the easier doors -----------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    keyword: str
    place: str
    floor: int
    ceiling: int
    record: str = ""

    def said(self) -> str:
        return "%s (levels %d-%d%s)" % (
            self.place,
            self.floor,
            self.ceiling,
            "; " + self.record if self.record else "",
        )


def _index(keyword: str) -> int:
    return next(
        (i for i, r in enumerate(campaignplan.RUNS) if r.keyword == keyword), -1
    )


def candidates(below: str, level_rows, keys, runs=None, avoid=()) -> list:
    """Every door easier than `below` the family can clear now, hardest first.

    `keys` is the door-key entries anybody carries (None unread, which locks
    every keyed door). `runs` is the ledger in the window: a door on a map no
    other wing shares is left out when its own record there is unclearable.
    `avoid` names doors to leave out (the one that just failed).
    """
    top = _index(below)
    if top <= 0:
        return []
    known = [
        int(r.get("level") or 0)
        for r in level_rows or ()
        if int(r.get("level") or 0) > 0
    ]
    if not known:
        return []
    level = min(known)
    out = []
    for run in campaignplan.RUNS[:top]:
        if run.keyword in avoid:
            continue
        if council.door_refusal(run.keyword, list(level_rows)):
            continue
        if level < run.floor or run.ceiling + OUTGROWN_GRACE < level:
            continue
        need = campaignplan.DOOR_KEYS.get(run.keyword)
        if need is not None and (keys is None or need[0] not in keys):
            continue
        record = ""
        if runs is not None and not campaignplan.shares_map(run):
            v = viability(runs, run.map_id)
            if not v.clearable:
                continue
            record = v.line() if v.fought else ""
        out.append(Candidate(run.keyword, run.place, run.floor, run.ceiling, record))
    out.reverse()
    return out


def ladder(cands) -> Candidate | None:
    """The hardest easier door: the one that still teaches the family most."""
    return cands[0] if cands else None


# --- the decision ---------------------------------------------------------------


@dataclass(frozen=True)
class Facts:
    """One family's pass, read by the bridge.

    head       the queue's first pending row (keyword, status, source, id)
    door       the operator's door the pace is about: the head, or the entry
               after a step-down head
    door_row   that entry's row
    record     Viability of the head since it started
    members    Member tuple
    gates      readiness gates for `door`
    notes      readiness notes for `door`
    open       the open pace row, or None
    changed    named_change against the open row's baseline, or ""
    done       the leader's dungeon_runs_done
    cands      candidates easier than the head
    """

    family: str
    head: dict
    door: str
    door_row: dict
    record: Viability
    members: tuple
    gates: tuple
    notes: tuple
    open: dict | None
    changed: str
    done: int | None
    cands: tuple


@dataclass(frozen=True)
class Decision:
    kind: str
    target: str = ""
    why: str = ""
    offer: tuple = ()  # Choice options Jev may pick among: keywords, STAY, LEVEL

    @property
    def acts(self) -> bool:
        return bool(self.kind)


def is_step_down(row: dict | None) -> bool:
    return bool(row) and str(row.get("source") or "") == SOURCE


def decide(f: Facts) -> Decision:
    """What the ladder does this pass. See the module docstring."""
    head_kw = str(f.head.get("keyword") or "")
    stepping = is_step_down(f.head)
    place = council.keyword_place(head_kw)
    if f.open is not None and str(f.open.get("decision")) == QUEST:
        if f.cands:
            pick = ladder(f.cands)
            return Decision(
                STEP_DOWN,
                pick.keyword,
                "an easier door opened while questing: %s" % pick.place,
                tuple(c.keyword for c in f.cands),
            )
        if f.changed and not f.gates:
            return Decision(RELEASE, "", "%s, so back to %s" % (f.changed, place))
        return Decision(
            NOTHING,
            "",
            "questing until a named change: %s"
            % ("; ".join(f.gates) or "no level or upgrade since the last wipe"),
        )
    if f.open is not None and not stepping:
        return Decision(
            STEP_UP,
            head_kw,
            "the step-down entry ran its count, so %s is next" % place,
        )
    if stepping:
        status = str(f.head.get("status") or "")
        if status != "active":
            return Decision(NOTHING, "", "%s is about to start" % place)
        if not f.record.clearable:
            if f.cands:
                pick = ladder(f.cands)
                return Decision(
                    FURTHER,
                    pick.keyword,
                    "%s is not clearable either (%s)" % (place, f.record.line()),
                    tuple(c.keyword for c in f.cands),
                )
            return Decision(
                QUEST,
                "",
                "%s is not clearable (%s) and no easier door is"
                % (place, f.record.line()),
                (LEVEL,),
            )
        if f.changed and not f.gates:
            return Decision(
                STEP_UP,
                f.door,
                "%s, and %s is ready" % (f.changed, council.keyword_place(f.door)),
            )
        wanted = int(f.head.get("runs_wanted") or 0)
        if f.done is not None and wanted and f.done >= wanted and not f.changed:
            return Decision(
                EXTEND,
                head_kw,
                "%s is at %d of %d with no level or upgrade since stepping "
                "down, so it runs %d more" % (place, f.done, wanted, STEP_DOWN_RUNS),
            )
        return Decision(NOTHING, "", "farming %s (%s)" % (place, f.record.line()))
    if head_kw not in campaignplan.BY_KEYWORD:
        return Decision(NOTHING, "", "%s is not on the dungeon ladder" % place)
    status = str(f.head.get("status") or "")
    if status == "active" and not f.record.clearable:
        why = "%s is not clearable: %s" % (place, f.record.line())
    elif f.gates:
        why = "%s is not ready: %s" % (place, "; ".join(f.gates))
    else:
        return Decision(NOTHING, "", "%s holds (%s)" % (place, f.record.line()))
    if f.cands:
        offer = tuple(c.keyword for c in f.cands)
        # A high rate with no two-wipe streak and no gate is a judgment call:
        # Jev may keep the door. Two wipes in a row or a gate never may.
        if not f.record.hard and not f.gates:
            offer = offer + (STAY,)
        return Decision(STEP_DOWN, ladder(f.cands).keyword, why, offer)
    return Decision(QUEST, "", why + "; no easier door can be cleared", (LEVEL,))


# --- Jev ----------------------------------------------------------------------


# Read before the class: its `jev` field shadows the module in the class body.
_HEURISTIC = jev.HEURISTIC


@dataclass(frozen=True)
class Judgment:
    """One step choice, shaped for overseer_jev_judgment (jev_activity's columns)."""

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

    def line(self) -> str:
        answer = (
            "jev=%s conf=%.2f" % (self.jev, self.confidence or 0.0)
            if self.jev
            else "jev=-"
        )
        return (
            "pace: family=%s kind=%s heuristic=%s %s status=%s latency_ms=%d "
            "mode=%s acted=%s why=%r facts=%r"
            % (
                self.subject,
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


def facts_line(f: Facts) -> str:
    who, level = weakest(f.members)
    parts = [
        "door %s (%s)"
        % (council.keyword_place(str(f.head.get("keyword") or "")), f.record.line()),
        "weakest %s %d" % (who or "?", level),
    ]
    if f.gates:
        parts.append("gates: " + "; ".join(f.gates))
    if f.notes:
        parts.append("; ".join(f.notes))
    if f.cands:
        parts.append("easier: " + ", ".join(c.said() for c in f.cands))
    return "; ".join(parts)[:1000]


def question(f: Facts, d: Decision):
    """(state, questions) for "which dungeon does the family run next"."""
    by_kw = {c.keyword: c for c in f.cands}
    criteria = {}
    for option in d.offer:
        if option == STAY:
            criteria[STAY] = "Keep trying %s: the losses may be bad luck." % (
                council.keyword_place(str(f.head.get("keyword") or ""))
            )
        elif option == LEVEL:
            criteria[LEVEL] = "Quest together at their level until they grow."
        elif option in by_kw:
            c = by_kw[option]
            criteria[option] = "Farm %s for gear and experience." % c.said()
    state = {
        "family": [
            {
                "name": m.name,
                "level": m.level,
                "gear_slots_filled": "unknown" if m.worn is None else m.worn,
                "has_main_hand_weapon": "unknown"
                if m.main_hand is None
                else m.main_hand,
            }
            for m in f.members
        ],
        "dungeon_they_are_failing": council.keyword_place(
            str(f.head.get("keyword") or "")
        ),
        "its_record_since_this_campaign_began": f.record.line(),
        "readiness": list(f.gates) + list(f.notes) or ["ready"],
        "why_now": d.why,
    }
    instructions = (
        "`family` is a group of World of Warcraft (3.3.5a) adventurers who "
        "play the way real players do. They keep wiping in "
        "`dungeon_they_are_failing`. Choose the dungeon they run next, as a "
        "sensible group would: the hardest one they can actually clear with "
        "their levels and gear, so each run still gives experience and gear, "
        "and never one they would keep dying in."
    )
    return state, {"dungeon": jev.choice(instructions, criteria)}


async def ask(client, f: Facts, d: Decision, rule: jev.Policy) -> Judgment | None:
    """Jev's pick among the offered doors, or None when there is nothing to ask."""
    if rule.mode == jev.OFF or len(d.offer) < 2:
        return None
    heuristic = d.target or (LEVEL if d.kind == QUEST else STAY)
    base = Judgment(
        subject=f.family,
        heuristic=heuristic,
        heuristic_why=d.why[:300],
        mode=rule.mode,
        status="",
        item_name=d.kind,
        facts=facts_line(f),
    )
    state, questions = question(f, d)
    outcome = await client.ask(KIND, state, questions)
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers["dungeon"]
    return replace(
        base,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        acted=rule.acted(
            heuristic,
            answer.choice,
            answer.confidence,
            can_act=answer.choice in d.offer,
        ),
    )


def carried(d: Decision, judgment: Judgment | None) -> Decision:
    """The decision to carry out: Jev's pick where it acted, the ladder's otherwise."""
    if judgment is None or judgment.acted != jev.JEV:
        return d
    if judgment.jev == STAY:
        return Decision(NOTHING, "", "Jev keeps the door: %s" % d.why)
    if judgment.jev == LEVEL:
        return Decision(QUEST, "", d.why)
    return replace(d, target=judgment.jev)


def chooser(judgment: Judgment | None) -> tuple:
    """(chosen_by, confidence) for the record."""
    if judgment is None or not judgment.jev:
        return "rule", None
    return (
        "jev" if judgment.acted in (jev.JEV, jev.BOTH) else "rule"
    ), judgment.confidence


# --- outcomes -------------------------------------------------------------------


def stretch_outcome(runs, map_id: int, since, changed: str) -> str:
    """What a step-down or questing stretch came to, for its record."""
    v = viability(runs, map_id, since) if map_id else None
    parts = []
    if v is not None and v.fought:
        parts.append(
            "%d fought, %d cleared, %d wiped" % (v.fought, v.complete, v.wipes)
        )
    parts.append(changed or "no level or upgrade")
    return "; ".join(parts)[:255]


def first_fight_after(runs, map_id: int, since) -> str:
    """The first fought run on `map_id` after `since`, as its outcome, or ""."""
    for r in runs or ():
        if (
            int(r.get("map_id") or 0) == int(map_id)
            and str(r.get("outcome") or "") in FOUGHT
            and r.get("started_at") is not None
            and r["started_at"] >= since
        ):
            return "first run back: %s" % r["outcome"]
    return ""


def line(family: str, d: Decision, by: str) -> str:
    """The one log line a carried-out decision is said with."""
    target = council.keyword_place(d.target) if d.target else ""
    said = {
        STEP_DOWN: "steps down to %s" % target,
        FURTHER: "steps further down to %s" % target,
        STEP_UP: "steps back up to %s" % target,
        EXTEND: "farms %s %d more runs" % (target, STEP_DOWN_RUNS),
        QUEST: "quests at its level",
        RELEASE: "stops questing and goes back to its queue",
    }.get(d.kind, "holds")
    return "%s %s (%s); chosen by %s" % (
        "%s's family" % family if family else "the family",
        said,
        d.why,
        by,
    )

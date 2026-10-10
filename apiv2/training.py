"""GET /api/v2/training?name=X: what a member has learned, can train now, and cannot yet.

The profile's Standing card. Two kinds of thing a trainer sells:

  class spells   every spell the world's class trainers (trainer.Type 0, the
                 member's class) teach. Learned: in character_spell. Trainable
                 now: not learned, its level is reached, and every spell it
                 requires first (ReqAbility) is learned. Needs another spell
                 first: its level is reached but a required spell (a talent, an
                 earlier rank not bought) is missing. Above level: its level is
                 over the member's and within the realm's level cap
                 (campaignplan.LEVEL_CAP). The world's tables carry no spell
                 names, so each spell is given by id, level and cost.
  trade ranks    every trade the member holds that guildjobs.RANKS knows the
                 ranks of, judged by guildjobs.next_rank, the bridge's own rule:
                 its next rank is trainable now, above level (the rank asks a
                 higher level), or waits on more skill. A trade at its top rank,
                 or one with no rank table, is learned.

Gated like every v2 read that takes a name: a family guild member, or a 404.
The trainer rows do not change under a running server and are kept per class.
"""

from __future__ import annotations

import threading

import campaignplan
import classtrain
import guildjobs
from panel import _CLASS_NAMES

from ._scope import NOT_A_MEMBER, guarded, guild_member, wanted_name

CHAR_SQL = (
    "SELECT guid, level, class AS class_id, money FROM characters WHERE name = %s"
)
KNOWN_SQL = "SELECT spell FROM character_spell WHERE guid = %s"
SKILLS_SQL = "SELECT skill, value, max FROM character_skills WHERE guid = %s"
TRAINER_SQL = (
    "SELECT ts.SpellId AS spell, MIN(ts.ReqLevel) AS level, "
    "MIN(ts.MoneyCost) AS cost, MAX(ts.ReqAbility1) AS req1, "
    "MAX(ts.ReqAbility2) AS req2, MAX(ts.ReqAbility3) AS req3 "
    "FROM acore_world.trainer_spell ts "
    "JOIN acore_world.trainer t ON t.Id = ts.TrainerId "
    "WHERE t.Type = 0 AND t.Requirement = %s GROUP BY ts.SpellId"
)

_TRAINERS: dict = {}
_LOCK = threading.Lock()


def _trainer_rows(ctx, cur, class_id: int) -> list:
    """A class's trainer rows, read once. The lock guards the dict only: the
    read itself runs outside it, so one class's first read never holds up a
    request for another (two first reads of one class both read, and agree)."""
    with _LOCK:
        kept = _TRAINERS.get(class_id)
    if kept is not None:
        return kept
    rows = guarded(ctx, cur, TRAINER_SQL, (class_id,), "trainer_spell")
    if rows:
        with _LOCK:
            _TRAINERS.setdefault(class_id, rows)
    return rows


def fetch(ctx, name: str) -> dict | None:
    """The member's row, its spells and skills, and its class's trainer rows."""
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            chars = guarded(ctx, cur, CHAR_SQL, (name,), "characters")
            if not chars:
                return None
            char = chars[0]
            guid = int(char["guid"])
            known = guarded(ctx, cur, KNOWN_SQL, (guid,), "character_spell")
            skills = guarded(ctx, cur, SKILLS_SQL, (guid,), "character_skills")
            trainer = _trainer_rows(ctx, cur, int(char.get("class_id") or 0))
    finally:
        conn.close()
    return {"char": char, "known": known, "skills": skills, "trainer": trainer}


# --------------------------------------------------------------------- pure --


# THE RULE IS classtrain's, which the guild training pass also walks members
# by, so the Standing card and the pass cannot disagree about a spell.
spell_state = classtrain.spell_state


def spells(trainer: list, known: set, level: int, cap: int) -> dict:
    """The class spells, sorted into the four states, each by level."""
    out: dict = {"learned": [], "trainable": [], "needs": [], "above": []}
    for row in sorted(
        trainer or (), key=lambda r: (int(r.get("level") or 0), int(r["spell"]))
    ):
        state = spell_state(row, known, level, cap)
        if state:
            out[state].append(
                {
                    "spell": int(row["spell"]),
                    "level": int(row.get("level") or 0),
                    "cost": int(row.get("cost") or 0),
                }
            )
    out["trainable_cost"] = sum(s["cost"] for s in out["trainable"])
    out["next_level"] = min((s["level"] for s in out["above"]), default=None)
    return out


def trade_state(skill: int, value: int, ceiling: int, level: int) -> dict:
    """One held trade: its state and, when there is one, the next rank."""
    ranks = guildjobs.RANKS.get(skill, ())
    upper = next((r for r in ranks if r.cap > ceiling), None)
    if upper is None:
        return {"state": "learned", "next": None}
    rank = guildjobs.next_rank(skill, value, ceiling, level)
    nxt = {
        "cap": upper.cap,
        "level": upper.level,
        "needs": upper.needs,
        "cost": upper.cost,
    }
    if rank is not None:
        return {"state": "trainable", "next": nxt}
    if level < upper.level:
        return {"state": "above", "next": nxt}
    return {"state": "skill", "next": nxt}


def trades(skill_rows: list, level: int) -> list:
    """Every held trade the bridge names, with its state."""
    out = []
    for row in skill_rows or ():
        skill = int(row["skill"])
        name = guildjobs.SKILL_NAMES.get(skill)
        if not name or int(row.get("max") or 0) <= 0:
            continue
        value, ceiling = int(row.get("value") or 0), int(row.get("max") or 0)
        out.append(
            dict(
                trade_state(skill, value, ceiling, level),
                skill=skill,
                name=name,
                value=value,
                max=ceiling,
            )
        )
    out.sort(key=lambda t: t["name"])
    return out


def build(name: str, f: dict, cap: int = campaignplan.LEVEL_CAP) -> dict:
    char = f["char"]
    level = int(char.get("level") or 0)
    known = {int(r["spell"]) for r in f.get("known") or ()}
    s = spells(f.get("trainer") or [], known, level, cap)
    t = trades(f.get("skills") or [], level)
    line = "%d learned, %d trainable now, %d above level" % (
        len(s["learned"]) + sum(1 for x in t if x["state"] == "learned"),
        len(s["trainable"]) + sum(1 for x in t if x["state"] == "trainable"),
        len(s["above"]) + sum(1 for x in t if x["state"] == "above"),
    )
    return {
        "name": name,
        "level": level,
        "class": _CLASS_NAMES.get(int(char.get("class_id") or 0), ""),
        "money": int(char.get("money") or 0),
        "cap": cap,
        "spells": s,
        "trades": t,
        "line": line,
        "basis": (
            "Class spells are the world's class trainer lists, by id: this "
            "world's tables carry no spell names. Trade ranks follow the "
            "bridge's own rank rule."
        ),
    }


def training(query: dict, ctx) -> tuple[int, dict]:
    name = wanted_name(query)
    if not guild_member(ctx, name):
        return 404, dict(NOT_A_MEMBER)
    f = fetch(ctx, name)
    if f is None:
        return 404, dict(NOT_A_MEMBER)
    return 200, build(name, f)


ROUTES = {"/api/v2/training": training}

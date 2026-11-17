"""Is a character's job producing? One row per member, from facts already kept.

The question this answers is the owner's: "per character, is its job actually
producing?". Before this module nobody could say. Skill points gained and
gathers were recorded nowhere, a craft was one event row, and the reason a
member was not producing sat in a dozen separate log lines.

WHAT IS RECORDED, AND WHERE
  last craft        the module's own `craft` event rows (overseer_event).
  last skill gain   `observe`: the bridge's profession loop reads every
                    member's trade skills each cycle and keeps, per member, the
                    values it last saw and when one last ROSE. Kept in the
                    bridge memo store (kind MEMO_KIND), so a restart keeps it.
  last gather       the same record, for a rise in a gathering skill (Mining,
                    Herbalism, Skinning). A gather that raised no skill is not
                    seen, so this is a floor and never a count.
A member the bridge has not yet watched, or has watched only once, has no
time: it reads None, which the page says as "not measured", never as zero.

WHY A MEMBER IS NOT PRODUCING (`stuck_because`) is built only from facts the
passes already compute and record: the roster row (job, craft order), the
trade skills, and the `craft-deferred` and `material-request` event rows the
craft pass writes when it cannot cast. No new judgement is made here, so the
line cannot disagree with the pass that wrote the fact. An empty string means
no recorded reason, not "all is well": `producing` says whether the job made
something lately.
"""

from __future__ import annotations

MEMO_KIND = "production"
# A memo outlives a quiet month so a long stall keeps its last-gain time.
KEEP_SECONDS = 30 * 24 * 3600
# A job made something "lately" when it did so within this window.
PRODUCING_SECONDS = 6 * 3600

GATHER_SKILLS = frozenset({"mining", "herbalism", "skinning"})
# The roster job a family sits on while it gathers or crafts; any other job
# (quest, rest, ...) is not a production job and is never judged here.
CRAFT_JOB = "craft"
FARM_PREFIX = "farm:"
# The gathering skill a farm job needs, by the job's own word.
FARM_SKILL = {
    "mining": "mining",
    "herbalism": "herbalism",
    "herb": "herbalism",
    "skinning": "skinning",
}


def observe(previous: dict | None, skills: dict, now: float) -> dict:
    """The record after seeing `skills` ({profession: value}) at `now`.

    `previous` is the record this returned last time, or None for a member
    never seen. The first sight only takes a baseline: it cannot say when
    anything rose, so both times stay None. A value that rose moves
    `skill_at`, and `gather_at` too when a gathering skill is the one that
    rose; a value that fell (a trade unlearned) or held moves nothing.
    """
    seen = {str(k).lower(): int(v) for k, v in (skills or {}).items()}
    if not previous or "skills" not in previous:
        return {"skills": seen, "skill_at": None, "gather_at": None}
    before = previous["skills"]
    skill_at = previous.get("skill_at")
    gather_at = previous.get("gather_at")
    for name, value in seen.items():
        if value > int(before.get(name, value)):
            skill_at = now
            if name in GATHER_SKILLS:
                gather_at = now
    return {"skills": seen, "skill_at": skill_at, "gather_at": gather_at}


def job_kind(job: str) -> str:
    """'craft', 'gather' or 'other' for a roster job word."""
    job = (job or "").strip().lower()
    if job == CRAFT_JOB:
        return "craft"
    if job.startswith(FARM_PREFIX):
        return "gather"
    return "other"


def _farm_skill(job: str) -> str:
    return FARM_SKILL.get(job.strip().lower()[len(FARM_PREFIX) :], "")


def stuck_because(
    *,
    job: str,
    enabled: bool,
    craft_spell: int,
    skills: dict,
    craft_at: int | None,
    request: dict | None,
    deferred: dict | None,
    now: float,
) -> str:
    """One line on why the job is not making anything, or "" for none recorded.

    `request` and `deferred` are the newest `material-request` and
    `craft-deferred` rows ({"at", "subject", "detail"}) or None. A reason older
    than the member's last craft is not a reason: the craft came after it.
    """
    kind = job_kind(job)
    if kind == "other":
        return ""
    if not enabled:
        return "the roster row is disabled"
    held = {str(k).lower() for k in skills}
    if kind == "gather":
        need = _farm_skill(job)
        if need and need not in held:
            return "holds no %s, so the family job %s gives it nothing to gather" % (
                need.capitalize(),
                job,
            )
        return ""
    if not craft_spell:
        return "no craft order is written for it"
    after = craft_at or 0
    for row, said in (
        (deferred, "its craft waits"),
        (request, "its craft is short of material"),
    ):
        if row and int(row.get("at") or 0) > after:
            return "%s: %s%s" % (
                said,
                row.get("subject") or "a recipe",
                " (%s)" % row["detail"] if row.get("detail") else "",
            )
    if craft_at is None:
        return "no craft recorded in the last week and no reason recorded"
    if now - craft_at > PRODUCING_SECONDS:
        return "no craft for %d hours and no reason recorded" % int(
            (now - craft_at) // 3600
        )
    return ""


def producing(job: str, craft_at, gather_at, now: float) -> bool | None:
    """Whether the job made something lately; None for a job not judged."""
    kind = job_kind(job)
    if kind == "other":
        return None
    at = craft_at if kind == "craft" else gather_at
    return at is not None and now - at <= PRODUCING_SECONDS


def build(members: list, skills: dict, events: dict, memos: dict, now: float) -> list:
    """The report rows, in the roster's order.

    `members`: roster rows ({name, family, job, craft_spell, enabled}).
    `skills`: {name: {profession: (value, max)}}.
    `events`: {name: {"craft": at, "request": row, "deferred": row}}.
    `memos`: {name: the record `observe` keeps}.
    """
    out = []
    for member in members:
        name = member["name"]
        held = skills.get(name) or {}
        seen = events.get(name) or {}
        memo = memos.get(name) or {}
        craft_at = seen.get("craft")
        gather_at = memo.get("gather_at")
        out.append(
            {
                "name": name,
                "family": member.get("family") or "",
                "job": member.get("job") or "",
                "job_kind": job_kind(member.get("job") or ""),
                "professions": [
                    {"name": prof, "value": int(v[0]), "max": int(v[1])}
                    for prof, v in sorted(held.items())
                ],
                "last_craft_at": craft_at,
                "last_skill_gain_at": memo.get("skill_at"),
                "last_gather_at": gather_at,
                "measured": bool(memo),
                "producing": producing(
                    member.get("job") or "", craft_at, gather_at, now
                ),
                "stuck_because": stuck_because(
                    job=member.get("job") or "",
                    enabled=bool(member.get("enabled", 1)),
                    craft_spell=int(member.get("craft_spell") or 0),
                    skills=held,
                    craft_at=craft_at,
                    request=seen.get("request"),
                    deferred=seen.get("deferred"),
                    now=now,
                ),
            }
        )
    return out

"""The family's priorities: a short, fixed list the operator ranks (#1559).

The site already says what the family is doing right now (agenda.py) and the
decree console can set a job, but nothing recorded what the operator wants
the family to care about MOST, in order. "Dungeons before professions this
week" had to be said one job at a time and was lost on the next pass. This
module owns that order.

A FIXED LIST, NOT FREE TEXT. Every priority has a stable id, a short label and
one exact sentence. The operator ranks them and can do nothing else: no
priority is typed, added or reworded from the page, so what reaches the model
stays typed and the sentence the site shows is the sentence Jev reads.

ONE ORDER FOR THE WHOLE REALM. Not per member and not per family: a
priority is what the operator wants, and the families carry it out each in
their own place.

AN ORDER IS A FULL PERMUTATION OR IT IS REFUSED. An order that leaves a
priority out, names one twice or names one nobody has heard of is refused and
nothing is stored. It is never repaired: a guess at what a broken order meant
would be the page inventing a ranking nobody gave.

TWO READERS, both in the bridge:

  * every Jev Choice request (jev_choices.py) carries the ranked sentences
    word for word, in the state and as the prompt line `prompt_line` renders;
  * the goal pass breaks a tie with `job_contest` when more than one active
    goal wants to set the family's job in the same pass: the goal whose
    priority ranks higher sets it, and the others wait. The contest is per
    family (the family whose job the goal would set), and a goal that waits
    is held back whole - its progress row too - so it drives on the first
    pass the contest lets it.

PURE MODULE, the same seam as decree.py and agenda.py: ids and rows in,
decisions and sentences out. No MySQL, no HTTP, no LLM. map_server.py runs
the write through the decree console's own path (decree.PRIORITIES), and the
bridge reads the row back with SELECT_SQL.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- the list ----------------------------------------------------------------

ALIVE = "alive"
GEAR = "gear"
QUEST = "quest"
DUNGEONS = "dungeons"
PROFESSIONS = "professions"
GOLD = "gold"
GUILD = "guild"


@dataclass(frozen=True)
class Priority:
    """One thing the family can care about.

    `id` is what is stored and never changes once shipped: renaming one would
    turn every stored order into an order that no longer matches the list.
    `sentence` is the one sentence the page shows, Jev reads and the log
    carries. It is written for a model and a person at once, so it says what
    to do rather than naming a system.
    """

    id: str
    label: str
    sentence: str


PRIORITIES = (
    Priority(
        ALIVE,
        "Stay alive",
        "Keep every member alive: rest, retreat or pick an easier fight "
        "rather than risk a wipe.",
    ),
    Priority(
        GEAR,
        "Gear up",
        "Improve what the family wears, filling empty slots and replacing "
        "the weakest pieces first.",
    ),
    Priority(
        QUEST,
        "Quest",
        "Finish the quests the family holds together, in level order.",
    ),
    Priority(
        DUNGEONS,
        "Dungeons",
        "Run the dungeons that suit the weakest member's level.",
    ),
    Priority(
        PROFESSIONS,
        "Professions",
        "Level the family's professions and gather what they need.",
    ),
    Priority(
        GOLD,
        "Gold",
        "Earn and keep gold for training, repairs and the guild bank.",
    ),
    Priority(
        GUILD,
        "Guild",
        "Do what the guild needs: its bank, its runs and its members.",
    ),
)

_BY_ID = {p.id: p for p in PRIORITIES}

IDS = tuple(p.id for p in PRIORITIES)

# The order a realm that has never set one uses, and what Reset puts back.
DEFAULT_ORDER = IDS

PROMPT_HEAD = "Priorities (highest first):"


def priority(pid: str) -> Priority:
    """The priority named by `pid`. KeyError for an id that is not on the list."""
    return _BY_ID[pid]


# --- validation ---------------------------------------------------------------

REFUSALS = {
    "shape": (
        "Send the order as a list of the priorities, highest first, each named once."
    ),
    "unknown": "%s %s not one of the family's priorities.",
    "twice": "%s %s named more than once.",
    "missing": "%s %s left out.",
}


def _said(ids) -> str:
    return ", ".join('"%s"' % i for i in ids)


def validate(order) -> tuple:
    """(order, "") for a full permutation of IDS, or (None, refusal).

    STRICT: the order must name every priority exactly once, and nothing
    else. It is never repaired - not reordered, not padded, not trimmed - so
    a refusal leaves whatever was stored exactly as it was.
    """
    if not isinstance(order, (list, tuple)) or not all(
        isinstance(i, str) for i in order
    ):
        return None, REFUSALS["shape"]
    unknown = [i for i in order if i not in _BY_ID]
    if unknown:
        return None, REFUSALS["unknown"] % (
            _said(unknown),
            "is" if len(unknown) == 1 else "are",
        )
    seen = set()
    twice = []
    for i in order:
        if i in seen and i not in twice:
            twice.append(i)
        seen.add(i)
    if twice:
        return None, REFUSALS["twice"] % (
            _said(twice),
            "is" if len(twice) == 1 else "are",
        )
    missing = [i for i in IDS if i not in seen]
    if missing:
        return None, REFUSALS["missing"] % (
            _said(missing),
            "is" if len(missing) == 1 else "are",
        )
    return tuple(order), ""


def move(order, pid: str, rank: int) -> tuple:
    """`order` with `pid` moved to `rank` (1 is highest), the rest SHIFTED.

    Not a swap: moving the fifth priority to first pushes the old first to
    second, the old second to third, and so on, which is what dragging a row
    up a list does. `order` must already be valid, and `rank` must be on the
    list; anything else is a ValueError, because a caller that gets here with
    either has a bug rather than an operator's mistake.
    """
    checked, refusal = validate(order)
    if checked is None:
        raise ValueError(refusal)
    if pid not in _BY_ID:
        raise ValueError("unknown priority %r" % pid)
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise ValueError("rank must be a whole number")
    if not 1 <= rank <= len(checked):
        raise ValueError("rank %d is not between 1 and %d" % (rank, len(checked)))
    rest = [i for i in checked if i != pid]
    rest.insert(rank - 1, pid)
    return tuple(rest)


# --- what the readers are handed ------------------------------------------------


def sentences(order) -> tuple:
    """The ranked sentences, highest first, word for word."""
    return tuple(_BY_ID[i].sentence for i in order)


def prompt_line(order) -> str:
    """The one line every Jev request and the log carry.

    "Priorities (highest first): 1. ... 2. ..." - the sentences verbatim,
    numbered, so the page, the request and the trace say the same thing.
    """
    return " ".join(
        [PROMPT_HEAD]
        + ["%d. %s" % (n, s) for n, s in enumerate(sentences(order), start=1)]
    )


# The instruction that goes beside the line in a Jev request. Deliberately a
# tie-breaker and not a veto: the question's own facts still decide which
# options are sensible at all.
INSTRUCTION = (
    " The operator ranked the family's priorities in `priorities`, highest "
    "first. When two options are otherwise close, prefer the one that serves "
    "a higher priority."
)

# The id order as the trace stores it beside a judgment: short, and exact.
ID_SEPARATOR = ">"


def trace(order) -> str:
    """The order in the record's facts line: "alive>gear>quest>..."."""
    return ID_SEPARATOR.join(order)


# --- the store ------------------------------------------------------------------
#
# ONE ROW, id = 1. The order is stored as the ids joined by commas, which is
# short, readable in a SELECT and checked by `validate` on the way back out.
# `source` is the surface that wrote it (map_server.WEB_SOURCE for the
# console), the same audit column every other decree write carries.

TABLE = "overseer_family_priorities"
ROW_ID = 1
STORE_SEPARATOR = ","

CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_family_priorities ("
    " id TINYINT UNSIGNED NOT NULL,"
    " ranked VARCHAR(255) NOT NULL,"
    " source VARCHAR(64) NOT NULL DEFAULT '',"
    " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    " ON UPDATE CURRENT_TIMESTAMP,"
    " PRIMARY KEY (id)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)

SELECT_SQL = (
    "SELECT ranked, source, updated_at FROM overseer_family_priorities WHERE id = 1"
)

# An unchanged order reports 0 rows changed (no CLIENT_FOUND_ROWS), which
# decree.order_result already says honestly: the same order pressed twice.
UPSERT_SQL = (
    "INSERT INTO overseer_family_priorities (id, ranked, source) "
    "VALUES (1, %s, %s) "
    "ON DUPLICATE KEY UPDATE ranked = VALUES(ranked), source = VALUES(source)"
)


def stored_value(order) -> str:
    """The column value for a validated order."""
    checked, refusal = validate(order)
    if checked is None:
        raise ValueError(refusal)
    return STORE_SEPARATOR.join(checked)


# How a stored row reads back.
STORED = "stored"
UNSET = "unset"
UNREADABLE = "unreadable"


def read_stored(rows) -> tuple:
    """(order, state) from SELECT_SQL's rows.

    No row is a realm that has never set an order: the default, and UNSET.
    A row whose value is no longer a full permutation (a priority added to
    the list after it was saved) falls back to the default and says
    UNREADABLE rather than being patched up, for the same reason `validate`
    never repairs.
    """
    rows = list(rows or [])
    if not rows:
        return DEFAULT_ORDER, UNSET
    raw = str(rows[0].get("ranked") or "")
    order, _refusal = validate([i for i in raw.split(STORE_SEPARATOR) if i])
    if order is None:
        return DEFAULT_ORDER, UNREADABLE
    return order, STORED


# --- the scheduler's tie-break ---------------------------------------------------
#
# Which priority each goal kind serves (goals.GOAL_KINDS). A level or a quest
# goal is questing; a skill goal is a profession; a dungeon goal is a dungeon.
GOAL_PRIORITY = {
    "level": QUEST,
    "quest": QUEST,
    "skill": PROFESSIONS,
    "dungeon": DUNGEONS,
}


def rank_of(order, pid: str) -> int:
    """1-based rank of `pid` in `order`; after the last for an unknown id."""
    try:
        return list(order).index(pid) + 1
    except ValueError:
        return len(order) + 1


@dataclass(frozen=True)
class Contest:
    """Which goal sets the family's job this pass, and which wait.

    `winner` is None when nothing competed. `waiting` keeps the candidates'
    own order. `line` is the sentence the log carries, empty with no tie.
    """

    winner: object
    waiting: tuple
    line: str


def job_contest(candidates, order) -> Contest:
    """The tie-break when more than one goal wants the job in one pass.

    candidates  (key, goal kind) pairs, in the order the pass met them; the
                bridge hands active goals oldest first
    order       the stored priority order

    The goal whose kind serves the higher-ranked priority wins. Two goals
    serving the same priority keep the order they arrived in, so the older
    goal wins - stable, and never decided by a dict's iteration order. One
    candidate or none is not a contest and waits nobody.
    """
    candidates = list(candidates)
    if not candidates:
        return Contest(None, (), "")
    if len(candidates) == 1:
        return Contest(candidates[0][0], (), "")
    ranked = sorted(
        enumerate(candidates),
        key=lambda pair: (rank_of(order, GOAL_PRIORITY.get(pair[1][1], "")), pair[0]),
    )
    winner_key, winner_kind = ranked[0][1]
    waiting = tuple(key for key, _kind in candidates if key != winner_key)
    pid = GOAL_PRIORITY.get(winner_kind)
    said = _BY_ID[pid].label if pid in _BY_ID else winner_kind
    line = (
        "%d goals want the family's job; the %s goal %s sets it, because %s ranks highest, and %s wait%s, unchanged, until no higher-ranked goal wants the job"
        % (
            len(candidates),
            winner_kind,
            winner_key,
            said,
            ", ".join(str(k) for k in waiting),
            "s" if len(waiting) == 1 else "",
        )
    )
    return Contest(winner_key, waiting, line)


# --- the panel ------------------------------------------------------------------

SUBMIT = "Save this order"
RESET_LABEL = "Reset to default"

# When a saved order takes effect, said where the operator presses the
# button. The bridge reads the row on its next pass; nothing that is already
# running is stopped by a new order.
TAKES_EFFECT = (
    "The next pass uses the new order: the next choice the family asks Jev "
    "to make carries it word for word, and the next goal pass breaks ties "
    "with it. Nothing already under way is stopped."
)

STATE_SAYS = {
    STORED: "Saved from this console.",
    UNSET: "No order has been saved, so the default order is used.",
    UNREADABLE: (
        "The saved order no longer matches the list of priorities, so the "
        "default order is used until a new one is saved."
    ),
}


def _when(value) -> str | None:
    if value is None or not hasattr(value, "strftime"):
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def view(rows=None) -> dict:
    """The Priorities panel's JSON, from SELECT_SQL's rows ([] with no table)."""
    rows = list(rows or [])
    order, state = read_stored(rows)
    return {
        "order": list(order),
        "default": list(DEFAULT_ORDER),
        "is_default": tuple(order) == DEFAULT_ORDER,
        "entries": [
            {
                "id": pid,
                "rank": n,
                "label": _BY_ID[pid].label,
                "sentence": _BY_ID[pid].sentence,
            }
            for n, pid in enumerate(order, start=1)
        ],
        "line": prompt_line(order),
        "state": state,
        "state_says": STATE_SAYS[state],
        "saved_at": _when(rows[0].get("updated_at")) if state == STORED else None,
        "takes_effect": TAKES_EFFECT,
        "submit": SUBMIT,
        "reset_label": RESET_LABEL,
    }

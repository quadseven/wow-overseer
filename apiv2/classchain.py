"""GET /api/v2/classchain?name=X: a member's class quest chains, step by step.

THE BRIDGE'S OWN BOOK. classquest builds its table of class quests from the
world at run time (QUESTS_SQL): a quest is a class quest when it names one
class, and a reward quest when it grants a spell; its chain is the PrevQuestID
links back to the first quest. This reads the same rows and lays out, for one
member, every reward chain of its class and race the way classquest does:

  a reward a trainer sells for coin is not a class quest's (TRAINED_SQL), and
  a quest nothing in the world starts (no creature, gameobject or item, and no
  earlier quest) is retired, so neither is listed.

EACH STEP'S STATE, from the member's own rows and nothing inferred:

  done        rewarded (character_queststatus_rewarded)
  ready       in the log and complete, waiting to be handed in
  in progress in the log, not complete
  blocked     the member's latest class quest ask (overseer_guild_ask) names it
              and is under members.ASK_LIVE_SECONDS old
  locked      not taken, and its level is above the member's
  open        not taken, and its level is reached

A chain is done when the member knows its reward spell or was rewarded any
quest that grants it (classquest.has_reward's rule).

Gated like every v2 read that takes a name. The world rows are read once.
"""

from __future__ import annotations

import threading

import classquest
from panel import _CLASS_NAMES

from . import members as roster
from ._scope import NOT_A_MEMBER, guarded, guild_member, holes, wanted_name

CHAR_SQL = "SELECT guid, level, class AS class_id, race FROM characters WHERE name = %s"
KNOWN_SQL = "SELECT spell FROM character_spell WHERE guid = %s"
STARTED_SQL = (
    "SELECT quest FROM acore_world.creature_queststarter WHERE quest IN ({holes}) "
    "UNION SELECT quest FROM acore_world.gameobject_queststarter WHERE quest IN ({holes}) "
    "UNION SELECT startquest FROM acore_world.item_template WHERE startquest IN ({holes})"
)
ASK_SQL = (
    "SELECT asker, target, target_label, state, UNIX_TIMESTAMP(created_at) AS at "
    "FROM overseer_guild_ask WHERE kind = 'quest' AND asker = %s "
    "AND created_at > NOW() - INTERVAL %s DAY ORDER BY created_at, id"
)

_WORLD: dict = {}
_LOCK = threading.Lock()


def _world(ctx, cur) -> dict:
    """The class quest rows, which of them something starts, and the reward
    spells a trainer sells: read once and kept."""
    with _LOCK:
        if _WORLD:
            return _WORLD
        quests = guarded(ctx, cur, classquest.QUESTS_SQL, (), "quest_template")
        ids = [int(r["id"]) for r in quests]
        started, trained = [], []
        if ids:
            h = holes(len(ids))
            started = guarded(
                ctx,
                cur,
                STARTED_SQL.format(holes=h),
                tuple(ids) * 3,
                "creature_queststarter",
            )
            spells = sorted(
                {int(r.get(k) or 0) for r in quests for k in ("reward", "display")}
                - {0}
            )
            if spells:
                trained = guarded(
                    ctx,
                    cur,
                    classquest.TRAINED_SQL.format(spells=holes(len(spells))),
                    tuple(spells),
                    "trainer_spell",
                )
        found = {
            "quests": quests,
            "started": {int(r["quest"]) for r in started},
            "trained": trained,
        }
        if quests:
            _WORLD.update(found)
        return found


def fetch(ctx, name: str) -> dict | None:
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            world = _world(ctx, cur)
            chars = guarded(ctx, cur, CHAR_SQL, (name,), "characters")
            if not chars:
                return None
            char = chars[0]
            guid = int(char["guid"])
            ids = [int(r["id"]) for r in world["quests"]]
            log, rewarded = [], []
            if ids:
                h = holes(len(ids))
                log = guarded(
                    ctx,
                    cur,
                    classquest.LOG_SQL.format(guids="%s", quests=h),
                    (guid, *ids),
                    "character_queststatus",
                )
                rewarded = guarded(
                    ctx,
                    cur,
                    classquest.REWARDED_SQL.format(guids="%s", quests=h),
                    (guid, *ids),
                    "character_queststatus_rewarded",
                )
            known = guarded(ctx, cur, KNOWN_SQL, (guid,), "character_spell")
            asks = guarded(
                ctx, cur, ASK_SQL, (name, roster.ASK_DAYS), "overseer_guild_ask"
            )
            cur.execute("SELECT UNIX_TIMESTAMP() AS now_at")
            now_at = int(cur.fetchone()["now_at"])
    finally:
        conn.close()
    return dict(
        world,
        char=char,
        log=log,
        rewarded=rewarded,
        known=known,
        asks=asks,
        now_at=now_at,
    )


# --------------------------------------------------------------------- pure --


def book_of(quest_rows, started: set, trained_rows) -> classquest.Book:
    """classquest's Book, with retired quests (nothing starts them) left out."""
    book = classquest.build(quest_rows, [], [], [], trained_rows)
    keep = {qid: q for qid, q in book.quests.items() if qid in started or q.prev}
    groups = {k: [q for q in v if q in keep] for k, v in book.groups.items()}
    return classquest.Book(keep, {k: v for k, v in groups.items() if v}, book.trained)


def blocked_quest(asks, now_at: int) -> int:
    """The quest the member's live class quest ask names, 0 when none."""
    run = next(iter(roster.ask_streaks(asks).values()), [])
    if not run or now_at - int(run[-1].get("at") or 0) > roster.ASK_LIVE_SECONDS:
        return 0
    head, _, tail = str(run[-1].get("target") or "").partition(":")
    return int(tail) if head == "quest" and tail.isdigit() else 0


def step_state(q, status: dict, done: set, blocked: int, level: int) -> str:
    if q.id in done:
        return "done"
    if q.id == blocked:
        return "blocked"
    if q.id in status:
        return "ready" if status[q.id] == classquest.STATUS_COMPLETE else "in progress"
    return "locked" if q.min_level > level else "open"


def _variant(book, rewards: list, race: int, status: dict, done: set):
    """The variant of a reward group this member follows: one already begun,
    else the lowest level one its race may take."""
    options = [book.quests[q] for q in rewards if book.quests[q].admits(race)]
    if not options:
        return None
    for q in options:
        if any(s in status or s in done for s in classquest.chain(book, q.id)):
            return q
    return min(options, key=lambda q: (q.min_level, q.id))


def chains(book, char: dict, status: dict, done: set, known: set, blocked: int) -> list:
    klass, race = int(char.get("class_id") or 0), int(char.get("race") or 0)
    level = int(char.get("level") or 0)
    out = []
    for key, rewards in book.groups.items():
        if key[0] != klass or book.trained.intersection(key[1]):
            continue
        last = _variant(book, rewards, race, status, done)
        if last is None:
            continue
        learned = any(s in known for s in key[1]) or any(q in done for q in rewards)
        steps = [book.quests[i] for i in classquest.chain(book, last.id)]
        out.append(
            {
                "title": last.title,
                "done": learned,
                "opens": steps[0].min_level if steps else last.min_level,
                "steps": [
                    {
                        "id": q.id,
                        "title": q.title,
                        "level": q.min_level,
                        "state": "done"
                        if learned and q.id not in status
                        else step_state(q, status, done, blocked, level),
                    }
                    for q in steps
                ],
            }
        )
    out.sort(key=lambda c: (c["opens"], c["title"]))
    return without_prefixes(out)


def without_prefixes(found: list) -> list:
    """Drop a chain that is the opening of a longer one: two reward groups on
    one road (a pet's taming, then its training) are drawn once."""
    ids = [[s["id"] for s in c["steps"]] for c in found]
    keep = []
    for i, c in enumerate(found):
        mine = ids[i]
        if any(
            j != i and len(o) > len(mine) and o[: len(mine)] == mine
            for j, o in enumerate(ids)
        ):
            continue
        keep.append(c)
    return keep


def build(name: str, f: dict) -> dict:
    char = f["char"]
    book = book_of(f["quests"], f["started"], f["trained"])
    status = {int(r["quest"]): int(r["status"]) for r in f.get("log") or ()}
    done = {int(r["quest"]) for r in f.get("rewarded") or ()}
    known = {int(r["spell"]) for r in f.get("known") or ()}
    blocked = blocked_quest(f.get("asks") or [], int(f.get("now_at") or 0))
    found = chains(book, char, status, done, known, blocked)
    finished = sum(1 for c in found if c["done"])
    return {
        "name": name,
        "level": int(char.get("level") or 0),
        "class": _CLASS_NAMES.get(int(char.get("class_id") or 0), ""),
        "chains": found,
        "line": "%d of %d class quest chains done" % (finished, len(found)),
        "basis": (
            "The bridge's own class quest book: every reward chain of this class "
            "and race the world starts, and not the rewards a trainer sells."
        ),
    }


def classchain(query: dict, ctx) -> tuple[int, dict]:
    name = wanted_name(query)
    if not guild_member(ctx, name):
        return 404, dict(NOT_A_MEMBER)
    f = fetch(ctx, name)
    if f is None:
        return 404, dict(NOT_A_MEMBER)
    return 200, build(name, f)


ROUTES = {"/api/v2/classchain": classchain}

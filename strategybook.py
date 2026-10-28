"""The runtime strategies the operator set on each member, kept across a roll.

WHY THIS EXISTS (#1553, carried over from mod-overseer#520). When the
worldserver restarts, every bot logs back in and PlayerbotAI::ResetStrategies
rebuilds its strategy lists from the AiFactory defaults. A strategy the
operator turned on or off at runtime (`@Name nc +grind`, `@Name co -flee`)
is gone, and nothing says so. The module cannot keep it: a manual toggle is
volatile in the core, and the strategy the operator wants is the bridge's to
know, because the bridge is where the order arrived.

So the bridge keeps a book. Every operator strategy order is folded into it,
one page per member: engine -> strategy -> '+' or '-', the last word on each
strategy winning. It is stored as one memo row per member, engine and
strategy (`rows`), and read back into pages (`book`). When the bridge sees a NEW worldserver start, it owes every
member in the book a replay, and pays it once per member as soon as that
member is back in the world under the AI and its rows are written. No new
start, no replay. The start is saved only once every member is paid, so a
bridge restart in between owes the replay again rather than losing it.

The bridge's own strategy writers (the life loop, the goal supervisor) are
not recorded here: they re-assert on their own cadence already. Only orders
that came from a person are, because nothing else would ever send them again.

A `~` toggle is not recorded: replaying a toggle onto a freshly reset list
flips it the other way from what the operator saw.

Pure: strings and dicts in, strings out. No database, no clock.
"""

from __future__ import annotations

# The engines a whispered strategy command can name: `nc` non-combat, `co`
# combat, `de` dead, `react` reaction. Anything else is not a strategy order.
ENGINES = ("nc", "co", "de", "react")

# Where the book lives in the bridge's memo store (overseer_bridge_memo.kind).
MEMO_KIND = "strategy_book"
# The worldserver start the book was last replayed for (or first seen at).
START_MEMO_KIND = "strategy_start"
START_SUBJECT = "worldserver"

# The source the replayed rows carry, so the bridge never records its own
# replay back into the book and the command table says where a row came from.
REAPPLY_SOURCE = "overseer:reapply"


def parse(command) -> tuple | None:
    """`nc +grind,-loot` -> ("nc", {"grind": "+", "loot": "-"}).

    None for anything that is not a strategy order with at least one `+` or
    `-` item. `~` items are skipped (see the module docstring)."""
    words = " ".join(str(command or "").lower().split())
    engine, _, rest = words.partition(" ")
    if engine not in ENGINES or not rest:
        return None
    changes = {}
    for item in rest.split(","):
        item = item.strip()
        sign = item[:1]
        name = item[1:].strip()
        if sign in ("+", "-") and name:
            changes[name] = sign
    if not changes:
        return None
    return engine, changes


def canonical(name) -> str:
    """The one spelling a member's page is kept under: `grug`, `GRUG` and
    `Grug` are one character. core accepts an order's target in any case, and
    the worldserver stores and reports a name first letter up, the rest down
    (normalizePlayerName), which is the form the replay side reads back from
    overseer_snapshot. Keying the book on the raw target meant an order for
    `grug` was never replayed for `Grug` (#1553)."""
    return str(name or "").strip().capitalize()


def is_operator(source) -> bool:
    """A row a person ordered, from Discord."""
    return str(source or "").startswith("discord:")


def rows(name, command) -> list:
    """The memo rows one order writes: [(subject, sign)], one per strategy.

    One row per member, engine and strategy rather than one page per member,
    so an order is a plain upsert: nothing is read first, so a failed read can
    never write a page back with the older strategies missing."""
    parsed = parse(command)
    if parsed is None:
        return []
    engine, changes = parsed
    name = canonical(name)
    if not name:
        return []
    return [(f"{name}|{engine}|{strategy}", sign) for strategy, sign in changes.items()]


def book(memo) -> dict:
    """{name: page} from the memo rows ({subject: (sign, since)}) `rows`
    wrote. A subject or sign that does not parse is skipped. Names are
    folded to `canonical`, so rows written under another spelling join the
    member's one page; where two disagree on a strategy, the newer wins."""
    out: dict = {}
    when: dict = {}
    for subject, (sign, since) in (memo or {}).items():
        name, _, rest = str(subject).partition("|")
        name = canonical(name)
        engine, _, strategy = rest.partition("|")
        if not name or engine not in ENGINES or not strategy:
            continue
        if sign not in ("+", "-"):
            continue
        key = (name, engine, strategy)
        try:
            since = float(since)
        except (TypeError, ValueError):
            since = 0.0
        if key in when and when[key] > since:
            continue
        when[key] = since
        out.setdefault(name, {}).setdefault(engine, {})[strategy] = sign
    return out


def replay(entry) -> list:
    """The commands that put one member's page back on a reset bot, one per
    engine, in a stable order."""
    out = []
    for engine in ENGINES:
        strategies = (entry or {}).get(engine) or {}
        items = [
            f"{sign}{name}"
            for name, sign in sorted(strategies.items())
            if sign in ("+", "-")
        ]
        if items:
            out.append(f"{engine} {','.join(items)}")
    return out


class Reapplier:
    """Owes a replay to every member in the book after a new worldserver start.

    `seen` is the start the bridge last saved, restored from the memo store,
    or None when it has never looked. A first look with nothing seen only
    seeds it: the bridge cannot tell a fresh realm from a roll it missed, and
    replaying then would re-send orders to a world that never lost them.

    The owed set lives only in memory, so the new start is saved only once
    nobody is owed (`settled`, #1584). A bridge restart before every member
    is back reads the old start, sees the new one as new, and owes the whole
    book again: a member already paid gets its page a second time, which
    sets the strategies it already has, and a member not yet back is not
    lost. A member is paid only when the bridge says its rows were written
    (`paid`), so a row the command table refused is sent again next pass.
    """

    def __init__(self, seen=None):
        self.seen = seen
        self._owed: set = set()
        self._unsaved = None

    def due(self, start, book, in_world) -> list:
        """[(name, command)] to send now: every page owed a replay whose
        member is in `in_world`. A member stays owed, and is offered again on
        the next call, until `paid` says its rows were written.
        Names match in any case (`canonical`); a command carries the spelling
        `in_world` reported.
        `start` None (uptime unreadable) changes nothing."""
        if start is not None and start != self.seen:
            if self.seen is not None:
                self._owed = {
                    canonical(name) for name, page in book.items() if replay(page)
                }
            self.seen = start
            self._unsaved = start
        pages = {canonical(name): page for name, page in book.items()}
        present = {canonical(name): name for name in in_world}
        commands = []
        for key in sorted(self._owed & set(present)):
            commands.extend((present[key], c) for c in replay(pages.get(key)))
        return commands

    def paid(self, name) -> None:
        """`name`'s replay rows were written: it is owed nothing more."""
        self._owed.discard(canonical(name))

    def settled(self):
        """The start to save now, else None: the newest start, once, as soon
        as nobody is owed a replay for it."""
        if self._unsaved is None or self._owed:
            return None
        start, self._unsaved = self._unsaved, None
        return start

    def owed(self) -> set:
        """Members still waiting for their replay."""
        return set(self._owed)

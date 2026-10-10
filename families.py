"""Who the families are, the guilds they play in, and who the site may
answer about.

One module for a question the site used to answer in eight places with four
different fallbacks. Its interface:

  families()        {family key: [names, lead first]}, the default family
                    first and the rest by key.
  names()           every family's names, in that order.
  default()         the family a page opens on when the request names none:
                    bonds' leader when the roster has that family, otherwise
                    the first key alphabetically. "" when there is no family.
  guilds()          [{"name", "family"}] for every guild a family member is
                    in, as the database reports it, in family order. A guild
                    belongs to the family with the most members in it.
  may_answer(name)  THE CLOSED SET. True only for a name of the world's shape
                    that is a family member or a member of a family guild.
                    Every read that takes a name answers for nobody else.
  request()         a context manager: inside it the roster and the guilds
                    are read at most once. The map server opens one around
                    every GET, so a page's handlers and the v2 reads under it
                    share one reading. Outside it every call reads afresh.

THE ONE FALLBACK. A roster that names no family at all reads as bonds' one
family, keyed by its head, so a page always has a family to open on; with no
bonds family either there is no family and nobody may be answered about.

No value from a request reaches SQL text: a name is checked against the
world's name rule first and then bound, like every family name.
"""

from __future__ import annotations

import collections
import contextlib
import re
import threading
from typing import Callable, Iterator

NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")

_ROSTER_SQL = (
    "SELECT name, family, `lead` FROM overseer_roster "
    "WHERE family IS NOT NULL AND family <> '' "
    "ORDER BY `lead` DESC, name"
)
# S608 on both: {holes} is a run of %s placeholders sized by a count; every
# value is bound by the driver.
_GUILDS_SQL = (
    "SELECT g.guildid, g.name, c.name AS member FROM guild g "
    "JOIN guild_member gm ON gm.guildid = g.guildid "
    "JOIN characters c ON c.guid = gm.guid WHERE c.name IN ({holes})"
)
_MEMBER_SQL = (
    "SELECT 1 FROM characters c JOIN guild_member gm ON gm.guid = c.guid "
    "WHERE c.name = %s AND gm.guildid IN ({holes}) LIMIT 1"
)


def _holes(n: int) -> str:
    return ", ".join(["%s"] * n)


class SqlStore:
    """The realm's tables, through `connect()` (a pymysql-shaped connection
    with a dict cursor). One connection per read, closed after it."""

    def __init__(self, connect: Callable[[], object]) -> None:
        self._connect = connect

    def _rows(self, sql: str, params: tuple = ()) -> list:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
        finally:
            conn.close()

    def roster(self) -> list[dict]:
        """{name, family} rows for every roster row with a family, lead first."""
        return self._rows(_ROSTER_SQL)

    def guilds_of(self, names: list[str]) -> list[dict]:
        """{guildid, name, member} for each of `names` that is in a guild."""
        if not names:
            return []
        return self._rows(_GUILDS_SQL.format(holes=_holes(len(names))), tuple(names))  # noqa: S608

    def in_guilds(self, name: str, guild_ids: list) -> bool:
        if not guild_ids:
            return False
        sql = _MEMBER_SQL.format(holes=_holes(len(guild_ids)))  # noqa: S608
        return bool(self._rows(sql, (name, *guild_ids)))


class MemoryStore:
    """The same three reads over plain data: {family: [names]} and
    {guild: [member names]}. For tests, and for anything that must not touch
    a database."""

    def __init__(self, families: dict, guilds: dict | None = None) -> None:
        self._families = {k: list(v) for k, v in families.items()}
        self._guilds = {k: list(v) for k, v in (guilds or {}).items()}

    def roster(self) -> list[dict]:
        return [
            {"name": n, "family": k}
            for k, names in self._families.items()
            for n in names
        ]

    def guilds_of(self, names: list[str]) -> list[dict]:
        return [
            {"guildid": g, "name": g, "member": m}
            for g, members in self._guilds.items()
            for m in members
            if m in names
        ]

    def in_guilds(self, name: str, guild_ids: list) -> bool:
        return any(name in self._guilds.get(g, ()) for g in guild_ids)


def _by_family(rows: list) -> dict:
    out: dict = {}
    for row in rows:
        out.setdefault(row["family"], []).append(row["name"])
    return out


def _default_of(keys, leaders: list) -> str:
    for name in leaders:
        if name in keys:
            return name
    return min(keys) if keys else ""


def _guild_rows(rows: list, family_of: dict, order: list) -> list:
    """[(guildid, name, family)] in family order, then by guild name."""
    counts: dict = {}
    names: dict = {}
    for row in rows:
        names[row["guildid"]] = row["name"]
        counts.setdefault(row["guildid"], collections.Counter())[
            family_of.get(row["member"])
        ] += 1
    rank = {key: i for i, key in enumerate(order)}
    out = []
    for gid, counter in counts.items():
        # Most members wins; a tie goes to the family that comes first.
        family = min(counter, key=lambda k: (-counter[k], rank.get(k, len(rank))))
        out.append((gid, names[gid], family))
    out.sort(key=lambda g: (rank.get(g[2], len(rank)), g[1]))
    return out


class Families:
    """One realm's families and family guilds (see the module docstring)."""

    def __init__(self, store, fallback: Callable[[], list]) -> None:
        self._store = store
        self._fallback = fallback
        self._local = threading.local()

    @contextlib.contextmanager
    def request(self) -> Iterator["Families"]:
        if getattr(self._local, "memo", None) is not None:
            yield self
            return
        self._local.memo = {}
        try:
            yield self
        finally:
            self._local.memo = None

    def _once(self, key, read: Callable[[], object]):
        memo = getattr(self._local, "memo", None)
        if memo is None:
            return read()
        if key not in memo:
            memo[key] = read()
        return memo[key]

    def _families(self) -> dict:
        return self._once("families", self._read_families)

    def _read_families(self) -> dict:
        by_family = _by_family(self._store.roster())
        leaders = list(self._fallback())
        if not by_family:
            return {leaders[0]: leaders} if leaders else {}
        first = _default_of(by_family, leaders)
        return {
            k: by_family[k]
            for k in [first] + sorted(k for k in by_family if k != first)
        }

    def _guilds(self) -> list:
        return self._once("guilds", self._read_guilds)

    def _read_guilds(self) -> list:
        fams = self._families()
        family_of = {n: key for key, names in fams.items() for n in names}
        return _guild_rows(
            self._store.guilds_of(list(family_of)), family_of, list(fams)
        )

    def families(self) -> dict[str, list[str]]:
        return {key: list(names) for key, names in self._families().items()}

    def names(self) -> list[str]:
        return [n for names in self._families().values() for n in names]

    def default(self) -> str:
        return next(iter(self._families()), "")

    def guilds(self) -> list[dict]:
        return [
            {"name": name, "family": family} for _gid, name, family in self._guilds()
        ]

    def may_answer(self, name) -> bool:
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            return False
        if name in self.names():
            return True
        return self._once(("member", name), lambda: self._is_guild_member(name))

    def _is_guild_member(self, name: str) -> bool:
        ids = [gid for gid, _name, _family in self._guilds()]
        return self._store.in_guilds(name, ids)

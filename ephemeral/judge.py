"""`eph judge`: run a decree's act timeline, decide a verdict, write the result.

Three verdicts, never two:

- PASS: every precondition held and every check held.
- FAIL: every precondition held and a check failed. A real defect sighting.
- INVALID: the scenario was never reached (a precondition did not hold, an act
  step never fired, a query timed out, the guard refused, the seed handoff is
  missing). INVALID never counts as a pass and never closes anything.

What the judge may write, in total: `overseer_command` rows in the world's own
database (an operator's order, through `GuardedConnection.insert_command`) and
one ConfigMap named `eph-result-<run-id>` in its own namespace. Every read goes
through the same guard the seed uses (loopback MySQL only, ephemeral namespace,
one marker row), and every observation is re-checked as a single SELECT against
the world's live schema before it runs. A job goes in as a command row, never a
direct roster write (measured: a roster UPDATE has no effect).

Seams: `Judge` takes the world, the clock and the log as arguments, so the
whole verdict logic runs in unit tests with no database and no cluster.
"""

import hashlib
import json
import os
import pathlib
import re
import ssl
import time
import urllib.error
import urllib.request

from . import acts, dbschema, gamedata, guard, lint
from . import anchors as anchors_mod
from .miniyaml import YamlError, loads
from .seedrun import LIVE_SCHEMA_SQL, inputs_from_env
from .sqlgen import SeedError

PASS, FAIL, INVALID = "PASS", "FAIL", "INVALID"
POLL_SECONDS = 10
CREDIT_DB, CREDIT_TABLE = "acore_characters", "log_encounter"
_MASK_BOSSES = frozenset(
    boss
    for boss, (map_name, _) in gamedata.INSTANCE_ENCOUNTERS.items()
    if map_name in gamedata.ENCOUNTER_MASK_MAPS
)
_DATA_SAVE_SQL = "SELECT data FROM instance WHERE id = @instance_id AND map = @map_id"
_MASK_SAVE_SQL = (
    "SELECT completedEncounters FROM instance WHERE id = @instance_id AND map = @map_id"
)
QUERY_TIMEOUT_SECONDS = 30
# The world's port opens before the family has logged in (measured: one to two
# minutes later), so `start` preconditions are polled for up to this long.
START_WAIT_SECONDS = 600
MAX_SAMPLE_ROWS = 20
MAX_MATCHED_LINES = 20
MAX_CELL_CHARS = 300
RESULT_CAP_BYTES = 256 * 1024
# MySQL: 3024 max_execution_time, 1317 interrupted, 2013 lost connection (client read timeout)
TIMEOUT_CODES = (3024, 1317, 2013)
# The result write retries for this long (seconds), backing off 2, 4, 8 ... up to the cap.
WRITE_RETRY_SECONDS = 300
WRITE_BACKOFF_START = 2
WRITE_BACKOFF_CAP = 30
HTTP_TIMEOUT_SECONDS = 15
SA_DIR = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount")


class JudgeError(Exception):
    """The judge refused or the harness broke."""


class QueryTimeout(Exception):
    """An observation did not answer in time."""


# -- the world -------------------------------------------------------------------


class GuardedWorldDb:
    """The judge's only door to the database: reads and guarded scenario acts."""

    def __init__(self, guarded, schema):
        if not isinstance(guarded, guard.GuardedConnection):
            raise guard.GuardError(
                "the judge needs a GuardedConnection from open_guarded"
            )
        self._g = guarded
        self._schema = schema

    def select(self, sql):
        problems = dbschema.check_select(sql, self._schema)
        if problems:
            raise JudgeError("; ".join(problems))
        try:
            return self._read(sql)
        except Exception as exc:
            if exc.args and exc.args[0] in TIMEOUT_CODES:
                raise QueryTimeout(str(exc)) from exc
            raise

    def _read(self, sql):
        """One read, then end its transaction: every look sees the world as it is now."""
        try:
            return self._g.query(sql)
        finally:
            self._g.end_read()

    def db_now(self):
        return str(self._read("SELECT NOW()")[0][0])[:19]

    def insert_command(self, target, kind, text):
        return self._g.insert_command(target, kind, text)

    def write_travel_guard(self, target, enabled, *, expected=None):
        return self._g.write_travel_guard(target, enabled, expected=expected)


# -- expectations and rendering --------------------------------------------------

_ROWS = re.compile(r"^(>=|<=|>|<|=)?\s*(\d+)$")
_SCALAR = re.compile(r"^(=|!=|<>|<=|>=|<|>) (-?\d+(?:\.\d+)?)$")
_STR = re.compile(r"'(?:[^'\\]|\\.|'')*'")
_VAR = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 _.,:\-]*$")
_LIST = re.compile(r"^[0-9, ]+$")
_OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<>": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def expectation_holds(expect, rows):
    """(held, observed-text) for {rows: ...} or {scalar: '<op> <n>'}."""
    if "rows" in expect:
        want = expect["rows"]
        m = _ROWS.match(str(want))
        if not m:
            raise JudgeError(f"bad rows expectation {want!r}")
        return _OPS[m.group(1) or "="](len(rows), int(m.group(2))), f"rows={len(rows)}"
    m = _SCALAR.match(str(expect.get("scalar")))
    if not m:
        raise JudgeError(f"bad scalar expectation {expect!r}")
    if len(rows) != 1 or len(rows[0]) != 1:
        shape = f"{len(rows)} rows" + (f" of {len(rows[0])} columns" if rows else "")
        raise JudgeError(f"a scalar expectation needs exactly one value, got {shape}")
    value = rows[0][0]
    if value is None:
        return False, "scalar=none"
    return _OPS[m.group(1)](float(value), float(m.group(2))), f"scalar={value}"


def log_bound_holds(expect, count):
    """Whether `count` matching log lines satisfy a log assertion's bound.

    A bound the lint would refuse raises: an unreadable bound is INVALID, never
    a pass.
    """
    problem = lint.log_bound_problem(expect)
    if problem:
        raise JudgeError(f"bad log expectation {expect!r}: {problem}")
    fewest, most = lint.log_bound_range(expect)
    return count >= fewest and (most is None or count <= most)


def render_sql(sql, variables):
    """Fill @name from the seed handoff; refuses a name it does not know."""

    def fill(chunk):
        def one(m):
            name = m.group(1)
            if name not in variables:
                raise JudgeError(f"unknown variable @{name}")
            v = variables[name]
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                raise JudgeError(f"variable @{name} is not a plain value")
            if isinstance(v, str):
                if _LIST.match(v):
                    return v
                if not _SAFE_VALUE.match(v):
                    raise JudgeError(
                        f"variable @{name} holds characters a query may not carry"
                    )
                return "'" + v + "'"
            return str(v)

        return _VAR.sub(one, chunk)

    out, pos = [], 0
    for m in _STR.finditer(sql):
        out.append(fill(sql[pos : m.start()]))
        out.append(m.group())
        pos = m.end()
    out.append(fill(sql[pos:]))
    return "".join(out)


def _cell(v, limit=MAX_CELL_CHARS):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if v is None:
        return None
    return str(v)[:limit]


def _sample(rows):
    return [[_cell(c) for c in row] for row in rows[:MAX_SAMPLE_ROWS]]


# -- the judge -------------------------------------------------------------------


_TIME_BOUND = re.compile(r"^(?:(\w+)\.)?time\s*>=?\s*@t0$", re.I)
_MAP_BOUND = re.compile(r"^(?:(\w+)\.)?map\s*=\s*(\d+)$", re.I)
_WHERE_END = re.compile(r"\b(?:group\s+by|order\s+by|having|limit)\b", re.I)


def _run_bound_problems(bare, maps, alias=None, sole=True):
    """Why the WHERE clause may not bound every counted row to this run.

    Accepts one shape only: a single SELECT whose WHERE is a flat AND chain with
    no parentheses, OR, NOT, XOR, BETWEEN, UNION or subquery, and in which one
    conjunct is `time >= @t0` (or `>`) and one is `map = <the arranged map>`.
    Anything else could let a row from an earlier run satisfy the check.
    """
    flat = re.sub(r"\s+", " ", bare)
    if len(re.findall(r"\bselect\b", flat, re.I)) != 1 or re.search(
        r"\b(?:union|intersect|except)\b", flat, re.I
    ):
        return ["is not a single plain SELECT, so its bounds may be skipped"]
    parts = re.split(r"\bwhere\b", flat, flags=re.I)
    if len(parts) != 2:
        return ["has no single WHERE clause bounding it to this run"]
    where = _WHERE_END.split(parts[1], maxsplit=1)[0].strip()
    if re.search(r"[()]|\|\||&&|\b(?:or|not|xor|between)\b", where, re.I):
        return [
            "has a WHERE clause that is not a flat AND chain "
            "(no parentheses, OR, NOT, XOR or BETWEEN), so the bounds may not apply"
        ]
    conjuncts = [c.strip() for c in re.split(r"\band\b", where, flags=re.I)]
    problems = []

    def on_the_credit_table(qualifier):
        # unqualified only when it is the only table; otherwise the one alias
        if qualifier is None:
            return sole
        return alias is not None and qualifier.lower() == alias.lower()

    if not any(
        (m := _TIME_BOUND.match(c)) and on_the_credit_table(m.group(1))
        for c in conjuncts
    ):
        problems.append(
            "is not bounded to this run (needs time >= @t0 in its AND chain)"
        )
    found = {
        int(m.group(2))
        for c in conjuncts
        if (m := _MAP_BOUND.match(c)) and on_the_credit_table(m.group(1))
    }
    if not found or (maps and not found & maps):
        problems.append(
            "is not bounded to this run's instance map (needs map = <id> in its AND chain)"
        )
    return problems


def _encounter_done(rows, boss):
    """Read the selected encounter slots from the pinned core's instance save."""
    map_name, slots = gamedata.INSTANCE_ENCOUNTERS[boss]
    if map_name in gamedata.ENCOUNTER_MASK_MAPS:
        return _encounter_mask_done(rows, map_name)
    if len(rows) != 1 or len(rows[0]) != 1 or not isinstance(rows[0][0], str):
        raise JudgeError(f"expected one {map_name} instance save")
    save = rows[0][0]
    if not save:
        return False, "instance save is empty"
    fields = save.split()
    if map_name == "Blackrock Depths":
        if len(fields) not in (7, 8, 9) or any(
            not re.fullmatch(r"[0-9]+", f) for f in fields
        ):
            raise JudgeError("malformed Blackrock Depths instance save")
        # The six encounter states come first. Magmus sets TYPE_IRON_HALL.
        state = fields[slots[0]]
        return state == "3", f"Iron Hall state={state}"

    # Both supported core pins serialize the MC header one character at a time
    # and write ten boss states. Unsummoned bosses can remain TO_BE_DECIDED (5).
    states = fields[2:]
    if (
        fields[:2] != ["M", "C"]
        or len(states) != 10
        or any(state not in {"0", "1", "2", "3", "4", "5"} for state in states)
    ):
        raise JudgeError("malformed Molten Core instance save")
    selected = [states[slot] for slot in slots]
    return "3" in selected, f"{boss} state={' '.join(selected)}"


def _encounter_mask_done(rows, map_name):
    """Read the core's completed-encounter mask for an instance with no boss save."""
    if len(rows) != 1 or len(rows[0]) != 1:
        raise JudgeError(f"expected one {map_name} instance row")
    mask = rows[0][0]
    if isinstance(mask, str) and re.fullmatch(r"[0-9]+", mask):
        mask = int(mask)
    if type(mask) is not int or not 0 <= mask < 1 << 32:
        raise JudgeError(f"malformed {map_name} completed-encounter mask")
    return mask != 0, f"completedEncounters={mask}"


class Judge:
    def __init__(
        self,
        decree,
        world,
        handoff,
        log_text=lambda: "",
        clock=time.monotonic,
        sleep=time.sleep,
        poll=POLL_SECONDS,
        run_id="",
        sha="",
        arm="",
        schema=None,
        start_wait=0,
    ):
        self.start_wait = start_wait
        self.start_waited = 0
        self.t0 = None
        self.decree = decree
        self.world = world
        self.handoff = handoff
        self.log_text = log_text
        self.clock = clock
        self.sleep = sleep
        self.poll = poll
        self.run_id = run_id
        self.sha = sha
        self.arm = arm
        self.schema = schema or dbschema.Schema.load()
        self.records = {}
        self._guard_aims = {}
        self.act_rows = []

    # -- entry --
    def run(self):
        started = self.clock()
        try:
            self.t0 = self.world.db_now()
            reasons = self._execute(self.t0, started)
        except JudgeError as exc:
            reasons = [f"harness refused: {exc}"]
            self._mark_unreached(reasons)
        return self._result(self.t0, self.clock() - started, reasons)

    def _mark_unreached(self, reasons):
        for row in self.act_rows:
            row.setdefault("fired", False)

    def _result(self, t0, elapsed, invalid_reasons):
        records = list(self.records.values())
        fail_reasons = []
        if not invalid_reasons:
            for r in records:
                if r["role"] == "check" and r["status"] == "violated":
                    fail_reasons.append(
                        f"check {r['name']} violated: {r.get('observed', '')}"
                    )
        verdict = INVALID if invalid_reasons else FAIL if fail_reasons else PASS
        return {
            "verdict": verdict,
            "reasons": invalid_reasons or fail_reasons,
            "decree": self.decree.get("id", ""),
            "decree_sha256": self.sha,
            "run_id": self.run_id,
            "arm": self.arm,
            "t0": t0,
            "elapsed_s": int(elapsed),
            "start_wait_s": int(self.start_waited),
            "assertions": records,
            "acts": self.act_rows,
        }

    # -- setup --
    def _execute(self, t0, started):
        duration, steps = self._prepare(t0)
        # The family logs in after the port opens: wait for the start
        # preconditions, then start every clock (t0, the act timeline, the window).
        started = self._await_start(started)
        # start observations, once, before any order is given
        for name, o in self.observes.items():
            if o.get("when") == "start":
                self._observe(name, started)
        if any(self._unheld_precondition(r) for r in self.records.values()):
            return self._invalid_reasons()
        for name, observation in self.observes.items():
            if "encounter" in observation:
                rec = self._evaluate(name)
                if rec["status"] == "held":
                    return [
                        f"precondition {name}: {observation['encounter']['boss']} was already complete before the first act"
                    ]
                if rec["status"] != "violated":
                    return [
                        f"precondition {name}: {self._phrase(rec)} reading starting instance state"
                    ]
        self._window(steps, duration, started)
        for name, o in self.observes.items():
            if o.get("when") == "end" or "log" in o:
                self._observe(name, started)
        return self._invalid_reasons()

    def _await_start(self, started):
        """Poll the `start` preconditions until they hold, for at most `start_wait`.

        Nothing is recorded and no order is given while waiting: a look that
        fails (violated, timed out, errored) is simply "not yet". When the wait
        ends, held or not, the normal single start sampling follows and decides:
        a precondition that still does not hold is INVALID, naming it. Returns
        the new clock origin for the act timeline and the window.
        """
        names = [
            n
            for n, o in self.observes.items()
            if o.get("when") == "start" and o.get("role") == "precondition"
        ]
        if names and self.start_wait > 0:
            waiting_from = self.clock()
            while True:
                if all(self._evaluate(n)["status"] == "held" for n in names):
                    break
                waited = self.clock() - waiting_from
                if waited >= self.start_wait:
                    break
                self.sleep(min(self.poll, self.start_wait - waited))
            self.start_waited = self.clock() - waiting_from
            started = self.clock()
            self.t0 = self.world.db_now()
            self.rendered = self._render(
                self.observes, {**self.handoff["variables"], "t0": self.t0}
            )
        return started

    @staticmethod
    def _unheld_precondition(r):
        return r["role"] == "precondition" and r["status"] != "held"

    def _prepare(self, t0):
        """Validate and render everything before the first order is given."""
        if not isinstance(self.handoff, dict) or "variables" not in self.handoff:
            raise JudgeError("the seed handoff is missing, so the cast is unknown")
        variables = {**self.handoff["variables"], "t0": t0}
        observes = {o["name"]: o for o in self.decree.get("observe") or []}
        duration = lint.duration_seconds(self.decree.get("duration"))
        if duration is None:
            raise JudgeError("decree has no valid duration")
        rendered = self._render(observes, variables)
        steps = self._plan_acts(observes)
        self.observes, self.rendered = observes, rendered
        return duration, steps

    def _render(self, observes, variables):
        rendered = {}
        for name, o in observes.items():
            if "sql" in o:
                sql = render_sql(o["sql"], variables)
            elif o.get("online") == "cast":
                sql = render_sql(
                    "SELECT guid FROM characters WHERE guid IN (@cast) AND online = 1",
                    variables,
                )
            elif "encounter" in o:
                source = lint.encounter_instance(self.decree, o)
                if source is None:
                    raise JudgeError(
                        f"observation {name}: needs a cast-bound seed instance"
                    )
                alias, map_id = source
                instance_id = variables.get(alias)
                if type(instance_id) is not int or instance_id <= 0:
                    raise JudgeError(
                        f"observation {name}: needs a positive instance ID for {alias}"
                    )
                sql = render_sql(
                    _MASK_SAVE_SQL
                    if o["encounter"]["boss"] in _MASK_BOSSES
                    else _DATA_SAVE_SQL,
                    {
                        "instance_id": instance_id,
                        "map_id": map_id,
                    },
                )
            else:
                continue
            problems = dbschema.check_select(sql, self.schema)
            if problems:
                raise JudgeError(f"observation {name}: " + "; ".join(problems))
            rendered[name] = sql
        return rendered

    def _window(self, steps, duration, started):
        """The measured window: fire due acts, sample continuous observations."""
        pending = list(steps)
        while True:
            elapsed = self.clock() - started
            for step in list(pending):
                if self._due(step, elapsed):
                    self._fire(step, elapsed)
                    pending.remove(step)
            for name, o in self.observes.items():
                if o.get("when") == "continuous":
                    self._observe(name, started)
            if elapsed >= duration:
                return
            self.sleep(min(self.poll, duration - elapsed))

    def _invalid_reasons(self):
        why = []
        for r in self.records.values():
            if r["role"] == "precondition" and r["status"] != "held":
                missing = r.get("missing_members") or []
                if missing:
                    why.append(
                        f"precondition {r['name']} is waiting for cast members to log in: "
                        + ", ".join(missing)
                    )
                else:
                    why.append(
                        f"precondition {r['name']} {self._phrase(r)}: the scenario was never reached"
                    )
            elif r["role"] == "check" and r["status"] in ("timeout", "error"):
                why.append(f"check {r['name']} {self._phrase(r)}")
        why.extend(self._credit_reasons())
        for row in self.act_rows:
            if not row["fired"]:
                trigger = row.get("when") or f"at {row.get('at')}"
                why.append(
                    f"act step {row['index']} never fired (waited for {trigger})"
                )
        return why

    def _credit_reasons(self):
        """A run that arranges an instance needs the core's own credited encounter record.

        The evidence is a held encounter observation of the fresh bound instance,
        or a held precondition that reads `log_encounter`. The observation must be
        positive and bounded to this run:
        an expectation that holds at zero credits, or a query that could count
        an earlier run's credits, proves nothing. A decree that arranges an
        instance without such an observation cannot PASS.
        """
        instances = [
            step["instance"]
            for step in self.decree.get("arrange") or []
            if "instance" in step
        ]
        if not instances:
            return []
        maps = {
            gamedata.INSTANCE_MAPS[instance["map"]]
            for instance in instances
            if instance.get("map") in gamedata.INSTANCE_MAPS
        }
        problems = []
        for name, sql in self.rendered.items():
            rec = self.records.get(name, {})
            if "encounter" in self.observes[name] and rec.get("status") == "held":
                return []
            if (CREDIT_DB, CREDIT_TABLE) not in dbschema.tables_read(sql, self.schema):
                continue
            if rec.get("role") != "precondition":
                problems.append(
                    f"{name} reads {CREDIT_TABLE} but is not a precondition"
                )
                continue
            if rec["status"] != "held":
                continue  # its own failure is already reported
            bad = self._credit_shape_problems(
                self.observes[name], maps, self.rendered[name]
            )
            if not bad:
                return []
            problems.append(f"{name} {'; '.join(bad)}")
        if problems:
            return ["no encounter credit evidence: " + "; ".join(problems)]
        return [
            "no encounter credit evidence: a bound encounter observation or a "
            "run-scoped log_encounter precondition must hold"
        ]

    def _credit_shape_problems(self, obs, maps, rendered):
        """Why this observation could hold without a credit earned in this run."""
        bad = []
        bare = _STR.sub("''", obs["sql"])
        # What the query returns when no credit was earned: an aggregate with no
        # GROUP BY still returns ONE row (holding 0), a row list returns none.
        aggregate = re.search(
            r"\b(?:count|sum|min|max|avg)\s*\(", bare, re.I
        ) and not re.search(r"\bgroup\s+by\b", bare, re.I)
        zero = [(0,)] if aggregate else []
        try:
            if expectation_holds(obs["expect"], zero)[0]:
                bad.append("holds at zero credits, so it needs a positive expectation")
        except JudgeError:
            bad.append("has an expectation the judge cannot evaluate")
        refs = dbschema.table_refs(rendered, self.schema)
        mine = [r for r in refs if (r[1], r[2]) == (CREDIT_DB, CREDIT_TABLE)]
        if len(mine) != 1:
            bad.append(
                f"reads {CREDIT_TABLE} {len(mine)} times; a credit observation reads it exactly once, with no self-join"
            )
            return bad
        bad.extend(_run_bound_problems(bare, maps, mine[0][0], len(refs) == 1))
        return bad

    @staticmethod
    def _phrase(r):
        return {
            "violated": f"did not hold ({r.get('observed', '')})",
            "timeout": "timed out",
            "error": f"could not be evaluated ({r.get('detail', '')})",
        }.get(r["status"], r["status"])

    # -- acts --
    def _plan_acts(self, observes):
        steps = []
        for i, cmd in enumerate(acts.act_commands(self.decree)):
            travel_guard = cmd["kind"] == acts.TRAVEL_GUARD and "guard_enabled" in cmd
            if cmd["kind"] not in guard.COMMAND_KINDS and not travel_guard:
                raise JudgeError(
                    f"act step {i}: command kind {cmd['kind']!r} is not allowed"
                )
            if "when" in cmd and cmd["when"] not in observes:
                raise JudgeError(
                    f"act step {i}: waits for unknown observation {cmd['when']!r}"
                )
            who = cmd["who"]
            targets = self._targets(who, i)
            if travel_guard and not self._is_named_target(who, targets):
                raise JudgeError(
                    f"act step {i}: travel_guard needs one named cast member"
                )
            at = lint.duration_seconds(cmd["at"]) if "at" in cmd else None
            if "at" in cmd and at is None:
                raise JudgeError(f"act step {i}: bad time {cmd['at']!r}")
            row = {
                "index": i, "who": who, "targets": targets, "kind": cmd["kind"],
                "text": cmd["text"], "fired": False,
            }  # fmt: skip
            if travel_guard:
                row["guard_enabled"] = cmd["guard_enabled"]
            row["at" if "at" in cmd else "when"] = cmd.get("at", cmd.get("when"))
            self.act_rows.append(row)
            steps.append((row, at))
        return steps

    def _is_named_target(self, who, targets):
        return targets == [who] and any(
            member["who"] == who for member in self.handoff.get("members", [])
        )

    def _targets(self, who, i):
        members = self.handoff.get("members") or []
        m = re.match(r"^cast\[(\d+)\]$", who)
        if m:
            names = [x["name"] for x in members if x["cast_index"] == int(m.group(1))]
        else:
            names = [x["name"] for x in members if x["who"] == who]
            names = names or [x["name"] for x in members if x["name"] == who]
        if not names:
            raise JudgeError(f"act step {i}: {who!r} is not in the seeded cast")
        return names

    def _due(self, step, elapsed):
        row, at = step
        if at is not None:
            return elapsed >= at
        rec = self._evaluate(row["when"])
        return rec["status"] == "held"

    def _fire(self, step, elapsed):
        row, _ = step
        if "guard_enabled" in row:
            self._fire_travel_guard(row)
        else:
            for name in row["targets"]:
                self.world.insert_command(name, row["kind"], row["text"])
        row["fired"] = True
        row["fired_s"] = int(elapsed)

    def _fire_travel_guard(self, row):
        name = row["who"]
        enabled = row["guard_enabled"]
        expected = self._guard_aims.get(name)
        if enabled and expected is not None:
            raise JudgeError(f"{name} already has a guard from this run")
        if not enabled and expected is None:
            raise JudgeError(f"{name} has no guard from this run to clear")
        try:
            aim = self.world.write_travel_guard(name, enabled, expected=expected)
        except guard.GuardError as exc:
            operation = "set" if enabled else "clear"
            row["error"] = f"could not {operation} travel guard for {name}: {exc}"
            raise JudgeError(row["error"]) from exc
        if enabled:
            self._guard_aims[name] = aim
        else:
            del self._guard_aims[name]
        row["text"] = aim
        row["fired_at"] = self.world.db_now()

    # -- observations --
    def _evaluate(self, name):
        """One look at one observation: a record dict, not yet merged."""
        o = self.observes[name]
        role = o["role"]
        if o.get("online") == "cast":
            return self._evaluate_cast_online(name, o)
        rec = {
            "name": name,
            "role": role,
        }
        if "log" in o:
            rec["expect"] = o["log"]["expect"]
            rec["when"] = "log"
            pattern = re.compile(o["log"]["pattern"])
            try:
                text = self.log_text()
            except JudgeError as exc:
                rec["status"], rec["detail"] = "error", str(exc)[:MAX_CELL_CHARS]
                return rec
            lines = [ln for ln in text.splitlines() if pattern.search(ln)]
            rec["pattern"] = o["log"]["pattern"]
            rec["matched"] = [ln[:MAX_CELL_CHARS] for ln in lines[:MAX_MATCHED_LINES]]
            rec["observed"] = f"count={len(lines)}"
            try:
                held = log_bound_holds(o["log"]["expect"], len(lines))
            except JudgeError as exc:
                rec["status"], rec["detail"] = "error", str(exc)[:MAX_CELL_CHARS]
                return rec
            rec["status"] = "held" if held else "violated"
            return rec
        rec["when"] = o["when"]
        rec["sql"] = self.rendered[name]
        encounter = o.get("encounter")
        rec["expect"] = (
            {"encounter": f"{encounter['boss']} DONE"} if encounter else o["expect"]
        )
        try:
            rows = self.world.select(rec["sql"])
            held, observed = (
                _encounter_done(rows, encounter["boss"])
                if encounter
                else expectation_holds(o["expect"], rows)
            )
            rec["status"] = "held" if held else "violated"
            rec["observed"] = observed
            rec["sample"] = _sample(rows)
        except QueryTimeout as exc:
            rec["status"], rec["detail"] = "timeout", str(exc)[:MAX_CELL_CHARS]
        except Exception as exc:  # noqa: BLE001 - any failure to look is INVALID, never a pass
            rec["status"], rec["detail"] = "error", repr(exc)[:MAX_CELL_CHARS]
        return rec

    def _evaluate_cast_online(self, name, observation):
        rec = {
            "name": name,
            "role": observation["role"],
            "when": "start",
            "online": "cast",
        }
        members = self.handoff.get("members") or []
        try:
            rows = self.world.select(self.rendered[name])
            online = {int(row[0]) for row in rows}
            missing = [
                member["name"]
                for member in members
                if int(member["guid"]) not in online
            ]
            rec["status"] = "held" if not missing else "violated"
            rec["observed"] = f"online={len(members) - len(missing)}/{len(members)}"
            rec["missing_members"] = missing
        except QueryTimeout as exc:
            rec["status"], rec["detail"] = "timeout", str(exc)[:MAX_CELL_CHARS]
        except Exception as exc:  # noqa: BLE001 - a failed look cannot release the act gate
            rec["status"], rec["detail"] = "error", repr(exc)[:MAX_CELL_CHARS]
        return rec

    _SEVERITY = {"held": 0, "violated": 1, "timeout": 2, "error": 2}

    def _observe(self, name, started):
        """Look, and fold the look into the observation's running record.

        The worst look wins and never improves: a timeout or error is sticky
        (it outranks a later violation or a clean sample, so the run is
        INVALID, never a FAIL or PASS on partial evidence), and a violation
        outranks a later clean sample.
        """
        rec = self._evaluate(name)
        old = self.records.get(name)
        rec["samples"] = (old["samples"] if old else 0) + 1
        if old and self._SEVERITY[old["status"]] >= self._SEVERITY[rec["status"]]:
            old["samples"] = rec["samples"]
            return
        if rec["status"] == "violated":
            rec["first_violation_s"] = int(self.clock() - started)
        self.records[name] = rec


# -- the result ------------------------------------------------------------------


def encode_result(result):
    """JSON text within the ConfigMap cap; trims evidence, never the verdict."""
    doc = json.loads(json.dumps(result, default=str))
    body = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    if len(body.encode("utf-8")) <= RESULT_CAP_BYTES:
        return body

    def shrink_reasons():
        doc["reasons"] = [r[:200] for r in doc.get("reasons", [])[:20]]

    def drop_evidence():
        for a in doc.get("assertions", []):
            a.pop("sample", None)
            a.pop("matched", None)
            a.pop("sql", None)

    def names_only():
        doc["assertions"] = [
            {k: a[k] for k in ("name", "role", "status") if k in a}
            for a in doc.get("assertions", [])
        ]
        doc["acts"] = []

    doc["truncated"] = True
    for a in doc.get("assertions", []):
        a["sample"] = [[str(c)[:100] for c in row] for row in a.get("sample", [])[:3]]
        a["matched"] = [m[:100] for m in a.get("matched", [])[:5]]
    for stage in (lambda: None, shrink_reasons, drop_evidence, names_only):
        stage()
        body = json.dumps(doc, sort_keys=True, separators=(",", ":"))
        if len(body.encode("utf-8")) <= RESULT_CAP_BYTES:
            return body
    return json.dumps({"verdict": doc.get("verdict"), "truncated": True})


def _label(value):
    v = re.sub(r"[^A-Za-z0-9_.-]", "-", str(value))[:63]
    return v.strip("-_.")


def result_configmap(result, namespace):
    run_id = result.get("run_id", "")
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": f"eph-result-{run_id}",
            "namespace": namespace,
            "labels": {
                "eph/decree": _label(result.get("decree", "")),
                "eph/arm": _label(result.get("arm", "")),
                "eph/verdict": result.get("verdict", ""),
            },
        },
        "data": {
            "verdict": result.get("verdict", ""),
            "result.json": encode_result(result),
        },
    }


RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_NAME = re.compile(r"^eph-result-[a-z0-9]([-a-z0-9.]*[a-z0-9])?$")


def urllib_http(ca_path=None):
    ctx = ssl.create_default_context(cafile=str(ca_path) if ca_path else None)

    def call(method, url, headers, body):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310 - https to the API server only
        try:
            opened = urllib.request.urlopen(  # noqa: S310 - https to the API server only
                req, context=ctx, timeout=HTTP_TIMEOUT_SECONDS
            )
            with opened as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    return call


class ConfigMapStore:
    """Creates the result ConfigMap, and nothing else, in the world's own namespace."""

    def __init__(
        self,
        base_url,
        token,
        namespace,
        http,
        sleep=time.sleep,
        log=print,
        retry_seconds=WRITE_RETRY_SECONDS,
    ):
        self.base_url, self.token, self.namespace, self.http = (
            base_url,
            token,
            namespace,
            http,
        )
        self.sleep, self.log, self.retry_seconds = sleep, log, retry_seconds

    @classmethod
    def in_cluster(cls, namespace=None, env=None, sa_dir=SA_DIR):
        """The API server address comes from the pod environment, never from the source."""
        env = os.environ if env is None else env
        host = env.get("KUBERNETES_SERVICE_HOST")
        port = env.get("KUBERNETES_SERVICE_PORT")
        if not host or not port:
            raise JudgeError(
                "KUBERNETES_SERVICE_HOST and KUBERNETES_SERVICE_PORT are not set: "
                "this is not a pod, so the result cannot be written"
            )
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        sa_dir = pathlib.Path(sa_dir)
        token_path = sa_dir / "token"

        def read_token():
            try:
                token = token_path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                raise JudgeError("result service-account token unreadable") from None
            if not token:
                raise JudgeError("result service-account token is empty")
            return token

        # Fail early if the token is missing. Kubelet can rotate it while the judge runs.
        read_token()
        ns = namespace or (sa_dir / "namespace").read_text(encoding="utf-8").strip()
        ca = sa_dir / "ca.crt"
        http = urllib_http(ca if ca.exists() else None)
        return cls(f"https://{host}:{port}", read_token, ns, http)

    def write(self, cm):
        meta = cm.get("metadata", {})
        if cm.get("kind") != "ConfigMap" or not _NAME.match(str(meta.get("name", ""))):
            raise JudgeError(
                "the judge writes a ConfigMap named eph-result-<run-id> only"
            )
        if meta.get("namespace") != self.namespace:
            raise JudgeError("the judge writes into its own namespace only")
        url = f"{self.base_url}/api/v1/namespaces/{self.namespace}/configmaps"
        payload = json.dumps(cm).encode("utf-8")
        spent, delay, attempt = 0.0, WRITE_BACKOFF_START, 0
        while True:
            attempt += 1
            began = time.monotonic()
            token = self.token() if callable(self.token) else self.token
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            try:
                status = self.http("POST", url, headers, payload)[0]
                problem = None if status not in RETRYABLE_STATUS else f"HTTP {status}"
            except OSError as exc:  # URLError, connect and read timeouts
                status, problem = None, f"{type(exc).__name__}: {exc}"
            spent += time.monotonic() - began
            if problem is None:
                break
            self.log(f"result write attempt {attempt} failed: {problem}")
            if spent + delay > self.retry_seconds:
                raise JudgeError(
                    f"result ConfigMap not written after {attempt} attempts: {problem}"
                )
            self.sleep(delay)
            spent += delay
            delay = min(delay * 2, WRITE_BACKOFF_CAP)
        # A retry after a lost answer finds the ConfigMap already there: it is written.
        if status in (200, 201) or (status == 409 and attempt > 1):
            return
        raise JudgeError(f"result ConfigMap refused with HTTP {status}")


# -- the entry point -------------------------------------------------------------


class _Wall:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


def _invalid(decree_id, env, sha, reason):
    return {
        "verdict": INVALID, "reasons": [reason], "decree": decree_id,
        "decree_sha256": sha, "run_id": env.get("EPH_RUN_ID", ""),
        "arm": env.get("EPH_ARM", ""), "t0": None, "elapsed_s": 0,
        "assertions": [], "acts": [],
    }  # fmt: skip


def start_wait_from_env(env):
    """EPH_START_WAIT_SECONDS, or the default when unset, unreadable or negative."""
    try:
        value = int(env.get("EPH_START_WAIT_SECONDS", ""))
    except ValueError:
        return START_WAIT_SECONDS
    return value if value >= 0 else START_WAIT_SECONDS


def _read_log(path):
    """The worldserver log, or a refusal: a log we cannot read must never read as zero matches."""
    if not path:
        raise JudgeError("no worldserver log file was given")
    try:
        return pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise JudgeError(f"worldserver log unreadable: {exc}") from exc


def log_reader(decree, log_path, bridge_log_path=None):
    """The callable the log assertions read: the worldserver log, plus the bridge log on a bridge-on decree.

    The bridge sidecar writes its own file, so a line it logs is never in the
    worldserver log. A bridge-on decree reads both; an unreadable or unnamed
    bridge log refuses, so a forbidden line can never read as absent for want of a file.
    """
    world = decree.get("world") if isinstance(decree, dict) else None
    bridge_on = isinstance(world, dict) and world.get("bridge") == "on"

    def read():
        text = _read_log(log_path)
        if not bridge_on:
            return text
        if not bridge_log_path:
            raise JudgeError("no bridge log file was given")
        try:
            extra = pathlib.Path(bridge_log_path).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError as exc:
            raise JudgeError(f"bridge log unreadable: {exc}") from exc
        return text + "\n" + extra

    return read


def run(
    decree_path, env, connect=None, store=None, log_path=None, out=print,
    clock=None, anchors_path=None, bridge_log_path=None,
):  # fmt: skip
    """Returns 0 once a verdict is written (INVALID included), 2 when the harness broke."""
    clock = clock or _Wall
    try:
        ns = (
            env.get("EPH_NAMESPACE")
            or (SA_DIR / "namespace").read_text(encoding="utf-8").strip()
        )
        store = store or ConfigMapStore.in_cluster(ns, env)
    except (JudgeError, OSError) as exc:
        # Nowhere to write the verdict: say INVALID on stdout and exit as a broken harness.
        result = _invalid("", env, "", f"the result cannot be written: {exc}")
        out(f"INVALID: {'; '.join(result['reasons'])}")
        out(encode_result(result))
        return 2
    try:
        raw = pathlib.Path(decree_path).read_bytes()
    except OSError as exc:
        result = _invalid("", env, "", f"decree unreadable: {exc}")
    else:
        sha = hashlib.sha256(raw).hexdigest()
        result = _judge(
            raw, sha, env, connect, log_path, clock, anchors_path, bridge_log_path
        )
    out(
        f"{result['verdict']}: {result['decree'] or decree_path} "
        + "; ".join(result["reasons"])
    )
    try:
        store.write(result_configmap(result, ns))
    except JudgeError as exc:
        out(f"harness error: result not written: {exc}")
        out(encode_result(result))
        return 2
    return 0


def _judge(raw, sha, env, connect, log_path, clock, anchors_path, bridge_log_path=None):
    try:
        decree = loads(raw.decode("utf-8"))
        anchors_doc = loads(
            pathlib.Path(anchors_path or anchors_mod.DEFAULT_PATH).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, YamlError, UnicodeDecodeError) as exc:
        return _invalid("", env, sha, f"decree or anchors unreadable: {exc}")
    decree_id = decree.get("id", "") if isinstance(decree, dict) else ""
    snapshot = dbschema.Schema.load()
    anchors = anchors_mod.Anchors((anchors_doc or {}).get("anchors") or {})
    errors = [
        f for f in lint.lint_document(decree, anchors, snapshot) if f.level == "error"
    ]
    if errors:
        return _invalid(
            decree_id, env, sha, "decree does not lint: " + "; ".join(map(str, errors))
        )
    try:
        handoff = json.loads(
            pathlib.Path(env.get("EPH_VARS_FILE", "")).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return _invalid(
            decree_id, env, sha, "the seed handoff is missing, so the cast is unknown"
        )
    try:
        g = guard.open_guarded(
            inputs_from_env(env),
            connect or _default_connect,
            snapshot,
            user=env.get("EPH_MYSQL_USER", "root"),
            password=env.get("EPH_MYSQL_PASSWORD", ""),
            database="acore_characters",
        )
    except SeedError as exc:
        return _invalid(decree_id, env, sha, f"guard refused: {exc}")
    try:
        live = dbschema.Schema.from_rows(g.query(LIVE_SCHEMA_SQL))
        g.use_schema(live)
        g.set_query_timeout(QUERY_TIMEOUT_SECONDS)
        return Judge(
            decree, GuardedWorldDb(g, live), handoff,
            log_text=log_reader(decree, log_path, bridge_log_path),
            clock=clock.monotonic, sleep=clock.sleep,
            run_id=env.get("EPH_RUN_ID", ""), sha=sha, arm=env.get("EPH_ARM", ""),
            schema=live, start_wait=start_wait_from_env(env),
        ).run()  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - a broken world is INVALID, never a verdict on the fix
        return _invalid(decree_id, env, sha, f"the world could not be judged: {exc!r}")
    finally:
        g.close()


def _default_connect(**kw):
    import pymysql  # a dependency of the world image, not of the unit suite

    kw.setdefault("read_timeout", QUERY_TIMEOUT_SECONDS + 10)
    return pymysql.connect(**kw)

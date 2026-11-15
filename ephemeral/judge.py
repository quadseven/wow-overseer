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
import pathlib
import re
import ssl
import time
import urllib.error
import urllib.request

from . import acts, dbschema, guard, lint
from . import anchors as anchors_mod
from .miniyaml import YamlError, loads
from .seedrun import LIVE_SCHEMA_SQL, inputs_from_env
from .sqlgen import SeedError

PASS, FAIL, INVALID = "PASS", "FAIL", "INVALID"
POLL_SECONDS = 10
QUERY_TIMEOUT_SECONDS = 30
MAX_SAMPLE_ROWS = 20
MAX_MATCHED_LINES = 20
MAX_CELL_CHARS = 300
RESULT_CAP_BYTES = 256 * 1024
# MySQL: 3024 max_execution_time, 1317 interrupted, 2013 lost connection (client read timeout)
TIMEOUT_CODES = (3024, 1317, 2013)
SA_DIR = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount")


class JudgeError(Exception):
    """The judge refused or the harness broke."""


class QueryTimeout(Exception):
    """An observation did not answer in time."""


# -- the world -------------------------------------------------------------------


class GuardedWorldDb:
    """The judge's only door to the database: reads, and queued orders."""

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
            return self._g.query(sql)
        except Exception as exc:
            if exc.args and exc.args[0] in TIMEOUT_CODES:
                raise QueryTimeout(str(exc)) from exc
            raise

    def db_now(self):
        return str(self._g.query("SELECT NOW()")[0][0])[:19]

    def insert_command(self, target, kind, text):
        return self._g.insert_command(target, kind, text)


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
    if not rows or not rows[0] or rows[0][0] is None:
        return False, "scalar=none"
    value = rows[0][0]
    return _OPS[m.group(1)](float(value), float(m.group(2))), f"scalar={value}"


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
    ):
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
        self.act_rows = []

    # -- entry --
    def run(self):
        started = self.clock()
        t0 = None
        try:
            t0 = self.world.db_now()
            reasons = self._execute(t0, started)
        except JudgeError as exc:
            reasons = [f"harness refused: {exc}"]
            self._mark_unreached(reasons)
        return self._result(t0, self.clock() - started, reasons)

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
            "assertions": records,
            "acts": self.act_rows,
        }

    # -- setup --
    def _execute(self, t0, started):
        if not isinstance(self.handoff, dict) or "variables" not in self.handoff:
            raise JudgeError("the seed handoff is missing, so the cast is unknown")
        variables = {**self.handoff["variables"], "t0": t0}
        observes = {o["name"]: o for o in self.decree.get("observe") or []}
        duration = lint.duration_seconds(self.decree.get("duration"))
        if duration is None:
            raise JudgeError("decree has no valid duration")
        rendered = {}
        for name, o in observes.items():
            if "sql" in o:
                sql = render_sql(o["sql"], variables)
                problems = dbschema.check_select(sql, self.schema)
                if problems:
                    raise JudgeError(f"observation {name}: " + "; ".join(problems))
                rendered[name] = sql
        steps = self._plan_acts(observes)
        self.observes, self.rendered = observes, rendered

        # start observations, once, before any order is given
        for name, o in observes.items():
            if o.get("when") == "start":
                self._observe(name, started)
        bad = [
            r
            for r in self.records.values()
            if r["role"] == "precondition" and r["status"] != "held"
        ]
        if bad:
            return self._invalid_reasons()

        pending = list(steps)
        while True:
            elapsed = self.clock() - started
            for step in list(pending):
                if self._due(step, elapsed):
                    self._fire(step, elapsed)
                    pending.remove(step)
            for name, o in observes.items():
                if o.get("when") == "continuous":
                    self._observe(name, started)
            if elapsed >= duration:
                break
            self.sleep(min(self.poll, duration - elapsed))
        for name, o in observes.items():
            if o.get("when") == "end" or "log" in o:
                self._observe(name, started)
        return self._invalid_reasons()

    def _invalid_reasons(self):
        why = []
        for r in self.records.values():
            if r["role"] == "precondition" and r["status"] != "held":
                why.append(
                    f"precondition {r['name']} {self._phrase(r)}: the scenario was never reached"
                )
            elif r["role"] == "check" and r["status"] in ("timeout", "error"):
                why.append(f"check {r['name']} {self._phrase(r)}")
        for row in self.act_rows:
            if not row["fired"]:
                trigger = row.get("when") or f"at {row.get('at')}"
                why.append(
                    f"act step {row['index']} never fired (waited for {trigger})"
                )
        return why

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
            if cmd["kind"] not in guard.COMMAND_KINDS:
                raise JudgeError(
                    f"act step {i}: command kind {cmd['kind']!r} is not allowed"
                )
            if "when" in cmd and cmd["when"] not in observes:
                raise JudgeError(
                    f"act step {i}: waits for unknown observation {cmd['when']!r}"
                )
            targets = self._targets(cmd["who"], i)
            at = lint.duration_seconds(cmd["at"]) if "at" in cmd else None
            if "at" in cmd and at is None:
                raise JudgeError(f"act step {i}: bad time {cmd['at']!r}")
            row = {
                "index": i, "who": cmd["who"], "targets": targets, "kind": cmd["kind"],
                "text": cmd["text"], "fired": False,
            }  # fmt: skip
            row["at" if "at" in cmd else "when"] = cmd.get("at", cmd.get("when"))
            self.act_rows.append(row)
            steps.append((row, at))
        return steps

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
        for name in row["targets"]:
            self.world.insert_command(name, row["kind"], row["text"])
        row["fired"] = True
        row["fired_s"] = int(elapsed)

    # -- observations --
    def _evaluate(self, name):
        """One look at one observation: a record dict, not yet merged."""
        o = self.observes[name]
        role = o["role"]
        rec = {
            "name": name,
            "role": role,
            "expect": o["expect"] if "expect" in o else o["log"]["expect"],
        }
        if "log" in o:
            rec["when"] = "log"
            pattern = re.compile(o["log"]["pattern"])
            lines = [ln for ln in self.log_text().splitlines() if pattern.search(ln)]
            rec["pattern"] = o["log"]["pattern"]
            rec["matched"] = [ln[:MAX_CELL_CHARS] for ln in lines[:MAX_MATCHED_LINES]]
            rec["observed"] = f"count={len(lines)}"
            rec["status"] = (
                "held" if len(lines) == o["log"]["expect"]["count"] else "violated"
            )
            return rec
        rec["when"] = o["when"]
        rec["sql"] = self.rendered[name]
        try:
            rows = self.world.select(rec["sql"])
            held, observed = expectation_holds(o["expect"], rows)
            rec["status"] = "held" if held else "violated"
            rec["observed"] = observed
            rec["sample"] = _sample(rows)
        except QueryTimeout as exc:
            rec["status"], rec["detail"] = "timeout", str(exc)[:MAX_CELL_CHARS]
        except Exception as exc:  # noqa: BLE001 - any failure to look is INVALID, never a pass
            rec["status"], rec["detail"] = "error", repr(exc)[:MAX_CELL_CHARS]
        return rec

    def _observe(self, name, started):
        """Look, and fold the look into the observation's running record."""
        rec = self._evaluate(name)
        old = self.records.get(name)
        elapsed = int(self.clock() - started)
        rec["samples"] = (old["samples"] if old else 0) + 1
        if old:
            if old["status"] == "violated":
                return self._keep(old, rec)
            if old["status"] in ("timeout", "error") and rec["status"] != "violated":
                return self._keep(old, rec)
        if rec["status"] == "violated":
            rec["first_violation_s"] = elapsed
        self.records[name] = rec
        return None

    def _keep(self, old, rec):
        old["samples"] = rec["samples"]
        return None


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


_NAME = re.compile(r"^eph-result-[a-z0-9]([-a-z0-9.]*[a-z0-9])?$")


def urllib_http(ca_path=None):
    ctx = ssl.create_default_context(cafile=str(ca_path) if ca_path else None)

    def call(method, url, headers, body):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310 - https to the API server only
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:  # noqa: S310
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    return call


class ConfigMapStore:
    """Creates the result ConfigMap, and nothing else, in the world's own namespace."""

    def __init__(self, base_url, token, namespace, http):
        self.base_url, self.token, self.namespace, self.http = (
            base_url,
            token,
            namespace,
            http,
        )

    @classmethod
    def in_cluster(cls, namespace=None):
        token = (SA_DIR / "token").read_text(encoding="utf-8").strip()
        ns = namespace or (SA_DIR / "namespace").read_text(encoding="utf-8").strip()
        return cls(
            "https://kubernetes.default.svc", token, ns, urllib_http(SA_DIR / "ca.crt")
        )

    def write(self, cm):
        meta = cm.get("metadata", {})
        if cm.get("kind") != "ConfigMap" or not _NAME.match(str(meta.get("name", ""))):
            raise JudgeError(
                "the judge writes a ConfigMap named eph-result-<run-id> only"
            )
        if meta.get("namespace") != self.namespace:
            raise JudgeError("the judge writes into its own namespace only")
        status, body = self.http(
            "POST",
            f"{self.base_url}/api/v1/namespaces/{self.namespace}/configmaps",
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            json.dumps(cm).encode("utf-8"),
        )
        if status not in (200, 201):
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


def _read_log(path):
    try:
        return pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def run(
    decree_path, env, connect=None, store=None, log_path=None, out=print,
    clock=None, anchors_path=None,
):  # fmt: skip
    """Returns 0 once a verdict is written (INVALID included), 2 when the harness broke."""
    clock = clock or _Wall
    raw = pathlib.Path(decree_path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    result = _judge(raw, sha, env, connect, log_path, clock, anchors_path)
    out(
        f"{result['verdict']}: {result['decree'] or decree_path} "
        + "; ".join(result["reasons"])
    )
    try:
        ns = (
            env.get("EPH_NAMESPACE")
            or (SA_DIR / "namespace").read_text(encoding="utf-8").strip()
        )
        (store or ConfigMapStore.in_cluster(ns)).write(result_configmap(result, ns))
    except (JudgeError, OSError) as exc:
        out(f"harness error: result not written: {exc}")
        out(encode_result(result))
        return 2
    return 0


def _judge(raw, sha, env, connect, log_path, clock, anchors_path):
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
            log_text=lambda: _read_log(log_path) if log_path else "",
            clock=clock.monotonic, sleep=clock.sleep,
            run_id=env.get("EPH_RUN_ID", ""), sha=sha, arm=env.get("EPH_ARM", ""),
            schema=live,
        ).run()  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - a broken world is INVALID, never a verdict on the fix
        return _invalid(decree_id, env, sha, f"the world could not be judged: {exc!r}")
    finally:
        g.close()


def _default_connect(**kw):
    import pymysql  # a dependency of the world image, not of the unit suite

    kw.setdefault("read_timeout", QUERY_TIMEOUT_SECONDS + 10)
    return pymysql.connect(**kw)

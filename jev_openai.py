"""Jev on a small OpenAI model: the spend ledger, the compare report and the bar.

The operator has a monthly OpenAI API credit (100 USD) and wants a working
decision model on it with no way to overspend and no kind acting before it has
shown it is good enough (#2899). Three things live here, and `jev.Client`
calls all of them:

  SPEND. Every OpenAI call is priced from the token usage the response carries
  and the pinned price table below, never from a provider meter, and recorded
  through a store (overseer_jev_spend in the bridge, so a restart does not
  reset the month). `Spend.refusal` refuses a call once the month (UTC) is
  within a margin of the cap. The cap is CAP_USD (90 USD), or a lower
  JEV_OPENAI_CAP_USD; a higher one is ignored. A model with no pinned price is
  refused, and a call whose usage cannot be read is charged UNKNOWN_CALL_USD,
  never zero, so a change in the usage shape cannot let calls run uncounted.
  The ledger design is the station's spend ledger (bus/openai_budget.py there),
  ported here with a store in place of a file.

  REPORT. Per kind, over a trailing window: answer rate, p50 and p95 latency,
  agreement with the heuristic, and cost per 1,000 calls (`report`,
  `summary_line`), logged hourly and shown on the Jev card.

  THE BAR. A kind may act only where `misses` is empty for it: enough calls,
  and an answer rate, latency, agreement and cost per 1,000 calls that all
  clear the numbers in BAR. `ActGate` holds the last verdict and `jev.mode`
  asks it, so `JEV_MODE_<KIND>=act` runs as compare until then.

Model free text is never kept. `clean_reason` strips any text that must be
stored to a strict charset, so a crafted answer cannot smuggle markup, an
at-mention or an issue reference into a place that renders it.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from typing import Any, Callable, Mapping, NamedTuple, Optional

log = logging.getLogger("wow-overseer.jev")

# Standard tier, USD per million tokens, from the official pricing page on the
# day named. A model missing here is refused: an unpriced call cannot be held
# under the cap.
PRICES_SOURCE = "https://developers.openai.com/api/docs/pricing"
PRICES_READ = "2026-11-17"
# A prompt over this many input tokens is billed at the long-context rates.
LONG_CONTEXT_OVER = 272_000


class Price(NamedTuple):
    input: float
    cached: float
    output: float
    long_input: float
    long_cached: float
    long_output: float


PRICES: dict = {
    # Priced, but POST /v1/decisions answers 404 model_not_found for it
    # (probed 2026-11-17), so it is never a default.
    "gpt-5-nano": Price(0.05, 0.005, 0.40, 0.05, 0.005, 0.40),
    "gpt-6-luna": Price(0.10, 0.01, 0.50, 0.20, 0.02, 0.75),
}
# The models POST /v1/decisions accepts, per the Decisions guide and a live
# probe on 2026-11-17. Any other model answers 404 model_not_found.
DECISIONS_MODELS = ("gpt-6-luna",)
DEFAULT_MODEL = "gpt-6-luna"
# The reasoning effort sent by default: none. /v1/decisions has no `reasoning`
# parameter and answers 400 unknown_parameter when one is sent.
DEFAULT_REASONING = ""
# The hard ceiling: JEV_OPENAI_CAP_USD may lower it, never raise it.
CAP_USD = 90.0
CREDIT_USD = 100.0
# Calls are skipped once spend plus this margin reaches the cap, so calls in
# flight when the line is reached still land under it.
MARGIN_USD = 1.0
UNKNOWN_CALL_USD = 0.25
HOLD_SECONDS = 60.0
# How long a read of the month's total from the store may be reused.
REFRESH_SECONDS = 30.0


class Unpriced(ValueError):
    """The model has no pinned price."""


class UsageUnknown(ValueError):
    """The response carried no readable token usage."""


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UsageUnknown("token count is not a number")
    if not math.isfinite(value) or value < 0:
        raise UsageUnknown("token count out of range")
    return int(value)


def _optional(value: Any) -> int:
    return 0 if value is None else _count(value)


class Usage(NamedTuple):
    """Tokens of one call: uncached input, cached input, output (reasoning
    included)."""

    input: int
    cached: int
    output: int

    @classmethod
    def from_openai(cls, usage: Any) -> "Usage":
        """The usage object of a Chat Completions or Responses style answer."""
        if not isinstance(usage, dict):
            raise UsageUnknown("no usage object")
        if "prompt_tokens" in usage or "completion_tokens" in usage:
            prompt, out = usage.get("prompt_tokens"), usage.get("completion_tokens")
            details = usage.get("prompt_tokens_details")
        elif "input_tokens" in usage or "output_tokens" in usage:
            prompt, out = usage.get("input_tokens"), usage.get("output_tokens")
            details = usage.get("input_tokens_details")
        else:
            raise UsageUnknown("usage has no token counts")
        prompt, out = _count(prompt), _count(out)
        cached = (
            _optional(details.get("cached_tokens")) if isinstance(details, dict) else 0
        )
        cached = min(cached, prompt)
        return cls(prompt - cached, cached, out)


def price_of(model: str, prices: Optional[Mapping[str, Price]] = None) -> Price:
    table = PRICES if prices is None else prices
    found = table.get(model)
    if found is None:
        raise Unpriced("no pinned price for %s (jev_openai.PRICES)" % model)
    return found


def cost(
    model: str, usage: Usage, prices: Optional[Mapping[str, Price]] = None
) -> float:
    p = price_of(model, prices)
    if usage.input + usage.cached > LONG_CONTEXT_OVER:
        rates = (p.long_input, p.long_cached, p.long_output)
    else:
        rates = (p.input, p.cached, p.output)
    return (
        usage.input * rates[0] + usage.cached * rates[1] + usage.output * rates[2]
    ) / 1e6


def month_of(now: float) -> str:
    return time.strftime("%Y-%m", time.gmtime(now))


def cap_usd(env: Mapping[str, str]) -> float:
    """CAP_USD, or a lower JEV_OPENAI_CAP_USD. ValueError when it does not parse."""
    raw = str(env.get("JEV_OPENAI_CAP_USD", "") or "").strip()
    if not raw:
        return CAP_USD
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value < 0:
        raise ValueError("JEV_OPENAI_CAP_USD is not a dollar amount")
    return min(value, CAP_USD)


def margin_usd(env: Mapping[str, str]) -> float:
    """MARGIN_USD, or JEV_OPENAI_CAP_MARGIN_USD when it parses and is not negative."""
    raw = str(env.get("JEV_OPENAI_CAP_MARGIN_USD", "") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return MARGIN_USD
    return value if math.isfinite(value) and value >= 0 else MARGIN_USD


# ---------------------------------------------------------------------------
# MODEL FREE TEXT: ONLY A STRICT CHARSET EVER SURVIVES

REASON_CHARS = re.compile(r"[^A-Za-z0-9 .,:\-]")
REASON_LIMIT = 120


def clean_reason(text: Any, limit: int = REASON_LIMIT) -> str:
    """`text` reduced to letters, digits, space and . , : - and capped.

    Every character outside that set is dropped, so `<!--`, `-->`, `@`, `#`,
    backticks, brackets and newlines cannot survive. A run of dashes is
    collapsed to one, so no comment marker can be rebuilt from what is left.
    """
    out = REASON_CHARS.sub("", str(text or ""))
    out = re.sub(r"-{2,}", "-", out)
    out = re.sub(r" {2,}", " ", out).strip()
    return out[: max(0, int(limit))].strip()


# ---------------------------------------------------------------------------
# THE LEDGER


class MemoryStore:
    """A store that lives and dies with the process (tests, and a bridge whose
    database is unreachable: the cap still holds until a restart)."""

    def __init__(self) -> None:
        self.rows: list = []

    def load(self, month: str) -> tuple:
        mine = [r for r in self.rows if r.get("month") == month]
        return round(sum(r["cost_usd"] for r in mine), 6), len(mine)

    def append(self, row: dict) -> None:
        self.rows.append(row)


class Refusal(NamedTuple):
    code: str  # stable, so a repeating refusal is logged once an hour
    text: str


class Spend:
    """What the OpenAI calls cost this month, and whether another may go out."""

    def __init__(
        self,
        store=None,
        env: Optional[Mapping[str, str]] = None,
        clock: Callable[[], float] = time.time,
        prices: Optional[Mapping[str, Price]] = None,
    ) -> None:
        self.store = store if store is not None else MemoryStore()
        self.env = env if env is not None else {}
        self._clock = clock
        self._prices = prices
        self._lock = threading.Lock()
        self._month = ""
        self._base = 0.0
        self._local = 0.0
        self._read_at = -math.inf
        # Expiry times of calls cleared to go out whose cost is not recorded
        # yet; each counts UNKNOWN_CALL_USD against the cap so concurrent asks
        # cannot all pass the same check. An expiry means a leaked hold (a
        # cancelled ask) cannot shrink the headroom for ever.
        self._holds: list = []

    def _held_usd(self, now: float) -> float:
        self._holds = [t for t in self._holds if t > now]
        return round(len(self._holds) * UNKNOWN_CALL_USD, 6)

    def release(self) -> None:
        """Give back the hold of a call that was cleared but never sent."""
        with self._lock:
            if self._holds:
                self._holds.pop(0)

    def _total(self, now: float) -> tuple:
        """(month, usd). The store's total is re-read at most every
        REFRESH_SECONDS, so two clients on one database agree, and what this
        client recorded since is added on top."""
        month = month_of(now)
        with self._lock:
            if month != self._month or now - self._read_at >= REFRESH_SECONDS:
                try:
                    usd, _calls = self.store.load(month)
                except Exception:
                    # An unreadable store never loosens the cap: the last total
                    # and what this process added since stand.
                    log.exception("jev: spend total unreadable; the last one stands")
                else:
                    # What was recorded since the last read is in the store now.
                    self._base, self._local = float(usd), 0.0
                self._month = month
                self._read_at = now
            return month, round(self._base + self._local, 6)

    def month_usd(self) -> float:
        """The month's spend so far (an exported entry point, also what the
        tests read the ledger back through)."""
        return self._total(self._clock())[1]

    def refusal(self, model: str, hold: bool = False) -> Optional[Refusal]:
        """Why a call must not go out now, or None when it may.

        With `hold` True a call that may go out is also reserved, checked and
        counted under one lock: the next ask sees it, so concurrent asks
        cannot together pass a cap only one of them fits under. `record` (or
        `release`) gives the hold back."""
        try:
            price_of(model, self._prices)
        except Unpriced as err:
            return Refusal("unpriced", str(err))
        try:
            cap = cap_usd(self.env)
        except ValueError as err:
            return Refusal("cap_unreadable", "%s; no OpenAI call goes out" % err)
        margin = margin_usd(self.env)
        now = self._clock()
        month, usd = self._total(now)
        with self._lock:
            usd = round(usd + self._held_usd(now), 6)
            if round(usd + margin, 6) < cap:
                if hold:
                    self._holds.append(now + HOLD_SECONDS)
                return None
        return Refusal(
            "cap",
            "OpenAI spend cap reached: $%.2f spent in %s, margin $%.2f, cap "
            "$%.2f; calls skipped and the heuristic acts until next month"
            % (usd, month, margin, cap),
        )

    def record(
        self,
        kind: str,
        model: str,
        status: str,
        latency_ms: int,
        usage: Optional[Usage] = None,
        charged: bool = True,
        persist: bool = True,
    ) -> dict:
        """Price one call, count it, and (unless `persist` is False, for a
        caller that stores it off its event loop) hand it to the store.

        `charged` False is a call that cost nothing (a refusal before any
        tokens were used, a timeout). A charged call with no readable usage is
        UNKNOWN_CALL_USD."""
        now = self._clock()
        row = {
            "month": month_of(now),
            "kind": str(kind)[:32],
            "model": str(model)[:40],
            "status": str(status)[:16],
            "latency_ms": max(0, int(latency_ms)),
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "cost_usd": 0.0,
            "estimated": 0,
        }
        if usage is not None:
            try:
                row["cost_usd"] = round(cost(model, usage, self._prices), 6)
            except Unpriced:
                row["cost_usd"], row["estimated"] = UNKNOWN_CALL_USD, 1
            row.update(
                input_tokens=usage.input,
                cached_input_tokens=usage.cached,
                output_tokens=usage.output,
            )
        elif charged:
            row["cost_usd"], row["estimated"] = UNKNOWN_CALL_USD, 1
        with self._lock:
            self._local += row["cost_usd"]
            if self._holds:
                self._holds.pop(0)
        if persist:
            self.persist(row)
        return row

    def persist(self, row: dict) -> None:
        try:
            self.store.append(row)
        except Exception:
            log.exception("jev: spend row not stored; it still counts until restart")


# ---------------------------------------------------------------------------
# THE BAR AND THE REPORT


class Bar(NamedTuple):
    min_calls: int = 200
    answer_rate: float = 0.95
    p95_ms: int = 3000
    p50_ms: int = 1500
    agreement: float = 0.80
    min_compared: int = 50
    cost_per_1000: float = 0.50


BAR = Bar()
WINDOW_DAYS = 14
# Statuses of a call that reached the provider; only `answered` is an answer.
ATTEMPTS = ("answered", "error", "timeout", "invalid")


def _percentile(values: list, pct: float) -> int:
    ordered = sorted(values)
    rank = max(1, int(math.ceil(pct / 100.0 * len(ordered))))
    return int(ordered[min(rank, len(ordered)) - 1])


def reviewed(kind: str, env: Optional[Mapping[str, str]]) -> bool:
    """True when the operator has recorded a reviewed sample of this kind's
    disagreements as good enough (JEV_OPENAI_REVIEWED_<KIND>=1)."""
    raw = str((env or {}).get("JEV_OPENAI_REVIEWED_" + kind.upper(), "") or "")
    return raw.strip().lower() in ("1", "true", "yes")


def report(
    calls: list,
    agreement: Mapping[str, tuple],
    bar: Bar = BAR,
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Per kind: calls, answer_rate, p50_ms, p95_ms, agreement (None when
    nothing was compared), cost_per_1000, and `misses`, the bar's measures the
    kind does not clear (empty means it may act).

    `calls` are dicts with kind, status, latency_ms and cost_usd. Only calls
    that reached the provider count. `agreement` maps a kind to (agreed,
    compared).
    """
    by_kind: dict = {}
    for c in calls:
        if str(c.get("status")) in ATTEMPTS:
            by_kind.setdefault(str(c.get("kind") or "?"), []).append(c)
    for kind in agreement:
        by_kind.setdefault(kind, [])
    out: dict = {}
    for kind, rows in sorted(by_kind.items()):
        n = len(rows)
        answered = sum(1 for r in rows if r["status"] == "answered")
        agreed, compared = agreement.get(kind, (0, 0))
        latencies = [max(0, int(r.get("latency_ms") or 0)) for r in rows]
        spent = sum(max(0.0, float(r.get("cost_usd") or 0)) for r in rows)
        item = {
            "calls": n,
            "answer_rate": (answered / n) if n else None,
            "p50_ms": _percentile(latencies, 50) if n else None,
            "p95_ms": _percentile(latencies, 95) if n else None,
            "compared": int(compared),
            "agreement": (agreed / compared) if compared else None,
            "cost_per_1000": (spent / n * 1000.0) if n else None,
        }
        item["misses"] = misses(item, kind, bar, env)
        out[kind] = item
    return out


def misses(item: dict, kind: str, bar: Bar = BAR, env=None) -> list:
    """The measures of one kind's report that fall short of the bar."""
    if item["calls"] < bar.min_calls:
        return ["calls %d of %d" % (item["calls"], bar.min_calls)]
    short = []
    if item["answer_rate"] < bar.answer_rate:
        short.append("answer_rate %.3f" % item["answer_rate"])
    if item["p95_ms"] >= bar.p95_ms:
        short.append("p95_ms %d" % item["p95_ms"])
    if item["p50_ms"] >= bar.p50_ms:
        short.append("p50_ms %d" % item["p50_ms"])
    if item["cost_per_1000"] > bar.cost_per_1000:
        short.append("cost_per_1000 %.3f" % item["cost_per_1000"])
    if not reviewed(kind, env):
        if item["compared"] < bar.min_compared:
            short.append("compared %d of %d" % (item["compared"], bar.min_compared))
        elif item["agreement"] < bar.agreement:
            short.append("agreement %.3f" % item["agreement"])
    return short


def _fmt(value, spec: str) -> str:
    return "-" if value is None else spec % value


def summary_line(kind: str, item: dict) -> str:
    """One hourly log line for a kind, `-` where there is nothing to measure."""
    verdict = (
        "clears" if not item["misses"] else "short(" + ",".join(item["misses"]) + ")"
    )
    return (
        "jev: openai report kind=%s calls=%d answer_rate=%s p50_ms=%s p95_ms=%s "
        "agreement=%s compared=%d cost_per_1000=%s bar=%s"
        % (
            kind,
            item["calls"],
            _fmt(item["answer_rate"], "%.3f"),
            _fmt(item["p50_ms"], "%d"),
            _fmt(item["p95_ms"], "%d"),
            _fmt(item["agreement"], "%.3f"),
            item["compared"],
            _fmt(item["cost_per_1000"], "%.3f"),
            verdict,
        )
    )


class ActGate:
    """The last verdict on which kinds clear the bar. Nothing clears until a
    report has run, so a restart starts every kind in compare mode."""

    def __init__(self) -> None:
        self._cleared: set = set()
        self.reported = False

    def update(self, rep: Mapping[str, dict]) -> None:
        self._cleared = {k for k, v in rep.items() if not v["misses"]}
        self.reported = True

    def __call__(self, kind: str) -> bool:
        return kind in self._cleared


# The SQL both the bridge and the Decree read, kept beside the report it feeds.
TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_jev_spend ("
    " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " month CHAR(7) NOT NULL,"
    " kind VARCHAR(32) NOT NULL,"
    " model VARCHAR(40) NOT NULL,"
    " status VARCHAR(16) NOT NULL,"
    " latency_ms INT UNSIGNED NOT NULL DEFAULT 0,"
    " input_tokens INT UNSIGNED NULL DEFAULT NULL,"
    " cached_input_tokens INT UNSIGNED NULL DEFAULT NULL,"
    " output_tokens INT UNSIGNED NULL DEFAULT NULL,"
    " cost_usd DECIMAL(12,6) NOT NULL DEFAULT 0,"
    " estimated TINYINT NOT NULL DEFAULT 0,"
    " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " PRIMARY KEY (id), KEY idx_month (month),"
    " KEY idx_kind_time (kind, created_at)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)
INSERT_SQL = (
    "INSERT INTO overseer_jev_spend (month, kind, model, status, latency_ms, "
    "input_tokens, cached_input_tokens, output_tokens, cost_usd, estimated) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
MONTH_SQL = (
    "SELECT COALESCE(SUM(cost_usd), 0) AS usd, COUNT(*) AS n "
    "FROM overseer_jev_spend WHERE month = %s"
)
CALLS_SQL = (
    "SELECT id, kind, status, latency_ms, cost_usd FROM overseer_jev_spend "
    "WHERE created_at > NOW() - INTERVAL %s DAY AND id < %s "
    "ORDER BY id DESC LIMIT %s"
)
AGREE_SQL = (
    "SELECT kind, COALESCE(SUM(agree = 1), 0) AS agreed, COUNT(agree) AS compared "
    "FROM overseer_jev_judgment WHERE backend = 'openai' AND agree IS NOT NULL "
    "AND created_at > NOW() - INTERVAL %s DAY GROUP BY kind"
)
CALLS_PAGE = 5000
PRUNE_DAYS = 100
PRUNE_SQL = "DELETE FROM overseer_jev_spend WHERE created_at < NOW() - INTERVAL %s DAY"


def row_args(row: dict) -> tuple:
    return (
        row["month"],
        row["kind"],
        row["model"],
        row["status"],
        row["latency_ms"],
        row["input_tokens"],
        row["cached_input_tokens"],
        row["output_tokens"],
        row["cost_usd"],
        row["estimated"],
    )


class SqlStore:
    """The spend ledger in overseer_jev_spend. `connect` returns a pymysql
    connection usable as a context manager with a dict cursor."""

    def __init__(self, connect: Callable) -> None:
        self._connect = connect

    def load(self, month: str) -> tuple:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(MONTH_SQL, (month,))
            row = cur.fetchone() or {}
        return float(row.get("usd") or 0), int(row.get("n") or 0)

    def append(self, row: dict) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(INSERT_SQL, row_args(row))


def fetch_calls(cur, page: int = CALLS_PAGE) -> list:
    """Every call in the window, read a page at a time by id so no row is
    dropped however many calls the window holds."""
    calls: list = []
    before = 2**63 - 1
    while True:
        cur.execute(CALLS_SQL, (WINDOW_DAYS, before, page))
        rows = list(cur.fetchall())
        calls.extend(rows)
        if len(rows) < page:
            return calls
        before = min(int(r["id"]) for r in rows)


def fetch_report(cur, env=None, bar: Bar = BAR) -> dict:
    """The per-kind report from the two tables, through an open cursor."""
    calls = fetch_calls(cur)
    cur.execute(AGREE_SQL, (WINDOW_DAYS,))
    agreement = {
        str(r["kind"]): (int(r["agreed"]), int(r["compared"])) for r in cur.fetchall()
    }
    return report(calls, agreement, bar, env)


class Reporter:
    """Runs the report once an hour: logs one line per kind, refreshes the
    gate. The database read stays the caller's; `publish` takes the report."""

    def __init__(
        self,
        gate: ActGate,
        clock: Callable[[], float] = time.monotonic,
        period: float = 3600.0,
    ) -> None:
        self.gate = gate
        self._clock = clock
        self._period = period
        self._next = -math.inf
        self.latest: dict = {}
        self._lock = threading.Lock()

    def due(self) -> bool:
        with self._lock:
            now = self._clock()
            if now < self._next:
                return False
            self._next = now + self._period
            return True

    def publish(self, rep: dict) -> list:
        self.latest = rep
        self.gate.update(rep)
        lines = [summary_line(k, v) for k, v in rep.items()]
        for line in lines:
            log.info("%s", line)
        return lines

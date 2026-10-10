"""A judgment client for TypeSafe's Jev, built so that nothing ever waits on it.

WHAT JEV IS, SO IT IS NOT MISAPPLIED (#88, #95). Jev returns typed judgments
and nothing else: a Choice (one option out of a set the caller defines), a
Score (a position along a rubric the caller defines) or a Noul (the
probability that a statement holds). It never returns free text and it never
acts. It is called at a decision point where the options already exist in
code, and the caller decides what, if anything, the answer changes.

THE CONTRACT EVERY CALLER RELIES ON: `ask` returns an `Outcome`, and its
`answers` is None whenever Jev did not produce a complete, well-typed answer.
Slow, down, rate limited, no key, a malformed body, an option nobody offered:
all of them are None, with the reason in `status`. A caller keeps its own
heuristic answer on None, so a Jev outage costs a log line and nothing else.

WHY THE STANDARD LIBRARY AND NOT THE `typesafe-sdk` PACKAGE. The SDK retries a
429 or 529 with backoff by default, which is the right default for a batch job
and the wrong one here: a shadow judgment that arrives after the pass has moved
on is worth nothing, so this client has one hard deadline and no retry. The
bridge already talks HTTP to its language model through `urllib.request`
(bridge._ask_llm), and the unit suite is stdlib-only by design (check.yml
installs nothing), so a plain POST keeps both true without a new dependency.

BOUNDED IN THREE WAYS:

  * TIME. Every call has one deadline (`JEV_TIMEOUT_SECONDS`, 3 by default)
    covering the whole request. Past it the caller gets `timeout`.
  * CONCURRENCY. At most `JEV_CONCURRENCY` requests are in flight. A caller
    that finds them all busy gets `busy` at once rather than queueing, and a
    request abandoned at its deadline keeps its slot until its thread really
    ends, so a slow API cannot pile threads up behind the limit.
  * REPETITION. An identical question (same model, state and questions) is
    answered from a bounded cache. The bag pass asks about the same carried
    items every cycle, and the answer to an unchanged question is unchanged.

MODES, PER DECISION KIND. `mode(kind)` reads `JEV_MODE_<KIND>`: `off` asks
nothing, `shadow` (the default) asks and records the answer beside the
heuristic's while the heuristic acts, and `act` carries Jev's answer out when
its confidence reaches that kind's threshold (`JEV_THRESHOLD_<KIND>`, see
`policy`). Below the threshold, or with no answer at all, the heuristic acts.
A kind whose act path is not built yet says so and runs as shadow (see
`effective_mode`). The modes belong to the KIND, not the backend: a backend
swap keeps each kind's coded default, and `JEV_MODE_<KIND>=off|shadow` is the
per-kind kill switch (an environment change, no code change).

BACKENDS (#820). `Client.ask` is one contract with interchangeable adapters,
chosen by `JEV_BACKEND` (default `jev`):

  jev     TypeSafe's Jev. TYPESAFE_API_KEY, JEV_URL, JEV_MODEL.
  clef    Cloudflare Clef or Clef-flash on Workers AI, the Jev request body.
          CLEF_ACCOUNT_ID (the account), CLEF_TOKEN_FILE (a mounted secret
          file holding an API token with Workers AI access; the token is
          read from the file and never from code, logs or argv), CLEF_MODEL
          (default @cf/cloudflare/clef; set @cf/cloudflare/clef-flash for the
          fast one), CLEF_URL (override of the whole URL).
  openai  OpenAI Decisions API. OPENAI_API_KEY_FILE (mounted secret file),
          OPENAI_DECISIONS_MODEL (default gpt-6-luna), OPENAI_DECISIONS_URL.
          noul/choice/score are translated to predicate/choice/score and back.

A backend with no token answers `no_key` and the heuristic acts. The Strands
Decider is a local CLI/Python model with no HTTP server, so it has no adapter
here (ticketed follow-up).

COMPARE (opt-in). `JEV_COMPARE_BACKEND=<name>` asks a second backend the same
question alongside the active one, off the caller's path, and hands one row
per question to `Client.compare_sink` (the bridge writes it to
overseer_jev_judgment with mode `compare` and the backend name). It never acts
and never delays or changes the active answer.

HOURLY TALLY. `TALLY` counts answered, disagreed and error per backend and
kind, and `maybe_log` writes one line per kind per hour. A repeating failure
(a 402 on every call) is logged once an hour, not once per call (#797).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import time
import threading
import urllib.error
import urllib.request
from collections import OrderedDict
import dataclasses
from dataclasses import dataclass

log = logging.getLogger("wow-overseer.jev")

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT_SECONDS = 3.0
CONCURRENCY = 4
CACHE_SIZE = 512
CLEF_BASE = "https://api.cloudflare.com/client/v4/accounts/%s/ai/run/%s"
CLEF_MODEL = "@cf/cloudflare/clef"
OPENAI_URL = "https://api.openai.com/v1/decisions"
OPENAI_MODEL = "gpt-6-luna"
TALLY_SECONDS = 3600.0
# How often a pass queued for a free slot looks again (see Client.ask's wait).
SLOT_POLL_SECONDS = 0.05

OFF, SHADOW, ACT = "off", "shadow", "act"
MODES = (OFF, SHADOW, ACT)
DEFAULT_MODE = SHADOW

# Outcome.status values. Only ANSWERED and CACHED carry answers.
ANSWERED = "answered"
CACHED = "cached"
NO_KEY = "no_key"
BUSY = "busy"
TIMEOUT = "timeout"
ERROR = "error"
INVALID = "invalid"


def mode(kind: str, environ=None, default: str = DEFAULT_MODE) -> str:
    """off / shadow / act for one decision kind, from JEV_MODE_<KIND>.

    An unset value is `default` (SHADOW unless the caller names the kind's
    own default). An unreadable one is SHADOW, whatever the default: shadow
    never changes what the world does, so a typo in the switch can cost a log
    line and never an action.
    """
    env = os.environ if environ is None else environ
    raw = str(env.get("JEV_MODE_" + kind.upper(), "") or "").strip().lower()
    if not raw:
        return default if default in MODES else DEFAULT_MODE
    if raw not in MODES:
        log.warning(
            "jev: JEV_MODE_%s=%r is not one of %s; using %s",
            kind.upper(),
            raw,
            "/".join(MODES),
            DEFAULT_MODE,
        )
        return DEFAULT_MODE
    return raw


def effective_mode(kind: str, act_supported: bool, environ=None) -> str:
    """`mode`, with ACT downgraded to SHADOW where no act path exists yet.

    Said out loud rather than done silently: an operator who set act and sees
    nothing change must be able to read why in the log.
    """
    chosen = mode(kind, environ)
    if chosen == ACT and not act_supported:
        log.warning(
            "jev: JEV_MODE_%s=act, but no act path is built for %s yet; running shadow",
            kind.upper(),
            kind,
        )
        return SHADOW
    return chosen


# ---------------------------------------------------------------------------
# WHO ACTS: THE THRESHOLD, PER KIND

# The record's `acted` column. JEV: Jev's answer was carried out where the
# heuristic's differed. BOTH: the two agreed and that answer was carried out.
# HEURISTIC: the heuristic's answer was carried out (shadow, below threshold,
# no answer, or no act path for what Jev chose).
JEV = "jev"
BOTH = "both"
HEURISTIC = "heuristic"
ACTED = (JEV, BOTH, HEURISTIC)


@dataclass(frozen=True)
class Policy:
    """One kind's switch and threshold, read once per pass.

    `on_agreement` is the narrow rule for a kind whose confidence runs low
    even where it is right: an answer that AGREES with the heuristic counts
    as Jev's at any confidence. It changes no action (the two answers are the
    same one); it changes only what the record says acted.
    """

    kind: str
    mode: str
    threshold: float
    on_agreement: bool = False

    def acted(self, heuristic: str, answer: str, confidence, can_act=True) -> str:
        """JEV, BOTH or HEURISTIC for one comparison. `can_act` is False when
        no act path exists for Jev's answer, so the heuristic stands."""
        if self.mode != ACT or not answer or confidence is None:
            return HEURISTIC
        confident = float(confidence) >= self.threshold
        if answer == heuristic:
            return BOTH if (confident or self.on_agreement) else HEURISTIC
        return JEV if (confident and can_act) else HEURISTIC


def threshold(kind: str, environ=None, default: float = 1.0) -> float:
    """JEV_THRESHOLD_<KIND> as a probability, or `default`.

    Unreadable or out of [0, 1] is `default`, said once per call. A default of
    1.0 means Jev is never confident enough, which is the safe reading.
    """
    env = os.environ if environ is None else environ
    raw = str(env.get("JEV_THRESHOLD_" + kind.upper(), "") or "").strip()
    if not raw:
        return float(default)
    try:
        value = _unit(float(raw))
    except ValueError:
        value = None
    if value is None:
        log.warning(
            "jev: JEV_THRESHOLD_%s=%r is not a probability; using %.2f",
            kind.upper(),
            raw,
            float(default),
        )
        return float(default)
    return value


def policy(
    kind: str,
    *,
    default_mode: str = DEFAULT_MODE,
    default_threshold: float = 1.0,
    on_agreement: bool = False,
    act_supported: bool = True,
    environ=None,
) -> Policy:
    """The Policy for one kind, from its two environment switches."""
    chosen = mode(kind, environ, default=default_mode)
    if chosen == ACT and not act_supported:
        chosen = effective_mode(kind, False, {"JEV_MODE_" + kind.upper(): ACT})
    return Policy(
        kind=kind,
        mode=chosen,
        threshold=threshold(kind, environ, default_threshold),
        on_agreement=on_agreement,
    )


# ---------------------------------------------------------------------------
# QUESTIONS AND TYPED ANSWERS


def choice(instructions, criteria: dict) -> dict:
    """A Choice question. `criteria` maps each option to what it means."""
    return {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}


def score(instructions, levels: list) -> dict:
    """A Score question over ordered levels, lowest first."""
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


def noul(instructions, criteria: dict | None = None) -> dict:
    """A Noul question: the probability that the statement holds."""
    q = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = dict(criteria)
    return q


@dataclass(frozen=True)
class Choice:
    choice: str
    probabilities: dict
    confidence: float


@dataclass(frozen=True)
class Score:
    score: float
    probabilities: dict
    confidence: float


@dataclass(frozen=True)
class Noul:
    noul: float


def _unit(value) -> float | None:
    """A finite number in [0, 1], or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        return None
    return number


def _distribution(raw, keys) -> dict | None:
    """Every expected key mapped to a probability, or None."""
    if not isinstance(raw, dict) or set(raw) != set(keys):
        return None
    out = {}
    for key in keys:
        p = _unit(raw[key])
        if p is None:
            return None
        out[key] = p
    return out


def _parse_choice(question: dict, answer: dict) -> Choice | None:
    options = list(question["criteria"])
    picked = answer.get("choice")
    probabilities = _distribution(answer.get("probabilities"), options)
    confidence = _unit(answer.get("confidence"))
    if picked not in options or probabilities is None or confidence is None:
        return None
    return Choice(picked, probabilities, confidence)


def _parse_score(question: dict, answer: dict) -> Score | None:
    levels = [str(n) for n in range(len(question["criteria"]))]
    probabilities = _distribution(answer.get("probabilities"), levels)
    confidence = _unit(answer.get("confidence"))
    value = answer.get("score")
    if probabilities is None or confidence is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not 0 <= float(value) <= len(levels) - 1:
        return None
    return Score(float(value), probabilities, confidence)


def _parse_noul(_question: dict, answer: dict) -> Noul | None:
    value = _unit(answer.get("noul"))
    return None if value is None else Noul(value)


_PARSERS = {"choice": _parse_choice, "score": _parse_score, "noul": _parse_noul}


def parse(question: dict, answer) -> Choice | Score | Noul | None:
    """One answer, checked against the question that was asked, or None.

    NOTHING IS TAKEN ON TRUST. A Choice must name an option the question
    offered and carry a probability for every option; a Score must land
    inside its own levels; a Noul must be a probability. Anything else is
    None, and the caller keeps its own answer.
    """
    if not isinstance(answer, dict) or answer.get("type") != question.get("type"):
        return None
    parser = _PARSERS.get(question["type"])
    return parser(question, answer) if parser else None


# ---------------------------------------------------------------------------
# THE CLIENT


@dataclass(frozen=True)
class Outcome:
    """What one `ask` produced. `answers` is None unless status is answered
    or cached; `model` is the versioned id that answered, when one did."""

    status: str
    latency_ms: int
    answers: dict | None = None
    model: str = ""
    detail: str = ""
    backend: str = ""


def _urllib_post(url: str, body: bytes, headers: dict, timeout: float) -> tuple:
    """POST and return (http status, body bytes). Runs in a worker thread.

    Only an https URL is ever opened: `Client` refuses any other scheme when
    it is built, so a `file:` or custom scheme from the environment cannot
    reach urlopen.
    """
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310 - https only, enforced in Client.__init__
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https only, enforced in Client.__init__
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read() or b""
        finally:
            exc.close()


# ---------------------------------------------------------------------------
# BACKENDS: how one request is built and one response read


def _answers_of(data):
    """The answers object of a Jev-shaped body, unwrapping the Workers AI
    `result` envelope when there is one."""
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data if isinstance(data, dict) else {}


class JevBackend:
    """TypeSafe's Jev: the request and response this module was built on."""

    name = "jev"

    def request(self, url, model, key, state, questions) -> tuple:
        body = json.dumps(
            {"state": state, "model": model, "questions": questions}
        ).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        }
        return url, body, headers

    def read(self, questions: dict, data) -> tuple:
        """(typed answers or None, model id). None when any is not well-typed."""
        data = _answers_of(data)
        raw = data.get("answers")
        if not isinstance(raw, dict):
            return None, ""
        answers = {}
        for qid, question in questions.items():
            typed = parse(question, raw.get(qid))
            if typed is None:
                return None, str(data.get("model") or "")
            answers[qid] = typed
        return answers, str(data.get("model") or "")


class ClefBackend(JevBackend):
    """Cloudflare Clef on Workers AI. The same body as Jev (the vendor calls
    it Jev-API compatible); the body's model is the last segment of the
    Workers AI model id, as in the vendor's example."""

    name = "clef"

    def request(self, url, model, key, state, questions) -> tuple:
        return super().request(
            url, str(model).rsplit("/", 1)[-1], key, state, questions
        )


class OpenAIBackend:
    """OpenAI Decisions: noul is a predicate, choice keeps its options, score
    keeps its ordered levels; answers come back in a list keyed by name."""

    name = "openai"

    def request(self, url, model, key, state, questions) -> tuple:
        sent = []
        for qid, q in questions.items():
            kind = q["type"]
            if kind == "choice":
                sent.append(
                    {
                        "type": "choice",
                        "name": qid,
                        "instructions": q["instructions"],
                        "choices": [
                            {"value": k, "description": str(v)}
                            for k, v in q["criteria"].items()
                        ],
                    }
                )
            elif kind == "score":
                sent.append(
                    {
                        "type": "score",
                        "name": qid,
                        "instructions": q["instructions"],
                        "levels": [
                            {"label": str(v), "description": str(v)}
                            for v in q["criteria"]
                        ],
                    }
                )
            else:
                text = q["instructions"]
                if q.get("criteria"):
                    text += " " + "; ".join(
                        "%s: %s" % kv for kv in q["criteria"].items()
                    )
                sent.append({"type": "predicate", "name": qid, "instructions": text})
        text = (
            state
            if isinstance(state, str)
            else json.dumps(state, sort_keys=True, default=str)
        )
        body = json.dumps({"model": model, "input": text, "questions": sent}).encode(
            "utf-8"
        )
        headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        }
        return url, body, headers

    def read(self, questions: dict, data) -> tuple:
        if not isinstance(data, dict) or not isinstance(data.get("answers"), list):
            return None, ""
        by_name = {a.get("name"): a for a in data["answers"] if isinstance(a, dict)}
        answers = {}
        for qid, question in questions.items():
            typed = parse(question, self._translate(question, by_name.get(qid)))
            if typed is None:
                return None, ""
            answers[qid] = typed
        return answers, str(data.get("model") or "")

    @staticmethod
    def _translate(question: dict, answer):
        """One OpenAI answer as the Jev-shaped dict `parse` checks."""
        if not isinstance(answer, dict):
            return None
        kind = question["type"]
        if kind == "noul":
            if answer.get("type") != "predicate":
                return None
            return {"type": "noul", "noul": answer.get("probability")}
        if answer.get("type") != kind:
            return None
        listed = answer.get("probabilities")
        if not isinstance(listed, list) or not all(isinstance(p, dict) for p in listed):
            return None
        probabilities = {str(p.get("value")): p.get("probability") for p in listed}
        out = {
            "type": kind,
            "probabilities": probabilities,
            "confidence": answer.get("confidence"),
        }
        out["choice" if kind == "choice" else "score"] = answer.get(
            "choice" if kind == "choice" else "score"
        )
        return out


JEV_BACKEND = JevBackend()
CLEF = ClefBackend()
OPENAI = OpenAIBackend()
BACKENDS = {b.name: b for b in (JEV_BACKEND, CLEF, OPENAI)}


def backend_name(environ=None, var: str = "JEV_BACKEND") -> str:
    """The named backend, or `jev` when unset or unknown (said once)."""
    env = os.environ if environ is None else environ
    raw = str(env.get(var, "") or "").strip().lower()
    if not raw:
        return "jev" if var == "JEV_BACKEND" else ""
    if raw not in BACKENDS:
        log.warning(
            "jev: %s=%r is not one of %s; ignored", var, raw, "/".join(BACKENDS)
        )
        return "jev" if var == "JEV_BACKEND" else ""
    return raw


def _read_secret(path: str) -> str:
    """The first line of a mounted secret file, or "" (the value is never
    logged, and an unreadable file only says so)."""
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError as exc:
        log.warning("jev: secret file unreadable (%s)", type(exc).__name__)
        return ""


def _settings(name: str, env) -> dict:
    """Client keyword arguments for one backend, from the environment."""
    if name == "clef":
        model = env.get("CLEF_MODEL", "") or CLEF_MODEL
        account = str(env.get("CLEF_ACCOUNT_ID", "") or "").strip()
        url = env.get("CLEF_URL", "") or CLEF_BASE % (account or "unset", model)
        key = _read_secret(env.get("CLEF_TOKEN_FILE", ""))
        if not account and not env.get("CLEF_URL"):
            key = ""
        return {"api_key": key, "url": url, "model": model}
    if name == "openai":
        return {
            "api_key": _read_secret(env.get("OPENAI_API_KEY_FILE", "")),
            "url": env.get("OPENAI_DECISIONS_URL", "") or OPENAI_URL,
            "model": env.get("OPENAI_DECISIONS_MODEL", "") or OPENAI_MODEL,
        }
    return {
        "api_key": env.get("TYPESAFE_API_KEY", ""),
        "url": env.get("JEV_URL", URL) or URL,
        "model": env.get("JEV_MODEL", MODEL) or MODEL,
    }


# ---------------------------------------------------------------------------
# THE HOURLY TALLY


class Tally:
    """Per backend and kind: answered, disagreed and error counts, one log
    line per kind per hour, and one line per hour per repeating failure."""

    def __init__(self, clock=time.monotonic, period: float = TALLY_SECONDS):
        self._clock = clock
        self._period = period
        self._lock = threading.Lock()
        self._since = clock()
        self._counts: dict = {}
        self._backend = "jev"
        self._failures: dict = {}

    def status(self, backend: str, kind: str, status: str) -> None:
        with self._lock:
            self._backend = backend
            c = self._counts.setdefault(
                kind, {"answered": 0, "disagreed": 0, "errors": 0}
            )
            if status in (ANSWERED, CACHED):
                c["answered"] += 1
            elif status in (ERROR, TIMEOUT, INVALID):
                c["errors"] += 1

    def agreement(self, kind: str, agree) -> None:
        if agree is False:
            with self._lock:
                c = self._counts.setdefault(
                    kind, {"answered": 0, "disagreed": 0, "errors": 0}
                )
                c["disagreed"] += 1

    def first_failure(self, key: tuple) -> int | None:
        """None when `key` was already said inside the hour; else how many
        were swallowed since it was last said (0 the first time)."""
        with self._lock:
            now = self._clock()
            said, held = self._failures.get(key, (None, 0))
            if said is not None and now - said < self._period:
                self._failures[key] = (said, held + 1)
                return None
            self._failures[key] = (now, 0)
            return held

    def lines(self) -> list:
        with self._lock:
            now = self._clock()
            if now - self._since < self._period:
                return []
            out = [
                "jev: hourly backend=%s kind=%s answered=%d disagreed=%d errors=%d"
                % (self._backend, kind, c["answered"], c["disagreed"], c["errors"])
                for kind, c in sorted(self._counts.items())
            ]
            self._counts = {}
            self._since = now
            return out

    def maybe_log(self) -> None:
        for line in self.lines():
            log.info("%s", line)


TALLY = Tally()


def top_answer(answer) -> str:
    """One typed answer as a short string for a comparison row."""
    if isinstance(answer, Choice):
        return answer.choice
    if isinstance(answer, Score):
        return str(int(round(answer.score)))
    if isinstance(answer, Noul):
        return "yes" if answer.noul >= 0.5 else "no"
    return ""


def _confidence_of(answer):
    if isinstance(answer, Noul):
        return max(answer.noul, 1.0 - answer.noul)
    return getattr(answer, "confidence", None)


def compare_rows(kind, questions, active, shadow, active_name, shadow_name) -> list:
    """One row per question: both backends' answers on the identical
    question. `agree` is None unless both answered."""
    rows = []
    for qid in questions:
        a = (active.answers or {}).get(qid)
        b = (shadow.answers or {}).get(qid)
        mine, theirs = top_answer(a), top_answer(b)
        probs = getattr(b, "probabilities", None)
        rows.append(
            {
                "kind": kind,
                "question": qid,
                "backend": shadow_name,
                "active_backend": active_name,
                "active_answer": mine,
                "answer": theirs,
                "confidence": _confidence_of(b),
                "probabilities": probs,
                "status": shadow.status,
                "latency_ms": shadow.latency_ms,
                "model": shadow.model,
                "agree": (mine == theirs) if (mine and theirs) else None,
            }
        )
    return rows


def _cache_key(model: str, state, questions: dict) -> str:
    text = json.dumps(
        {"model": model, "state": state, "questions": questions},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Client:
    """The one door to Jev. See the module docstring for the contract."""

    def __init__(
        self,
        api_key: str,
        *,
        url: str = URL,
        model: str = MODEL,
        timeout: float = TIMEOUT_SECONDS,
        concurrency: int = CONCURRENCY,
        cache_size: int = CACHE_SIZE,
        transport=None,
        clock=time.monotonic,
        backend=None,
        shadow=None,
        compare_sink=None,
    ):
        if not str(url).lower().startswith("https://"):
            raise ValueError("Jev URL must be https: %r" % url)
        self._key = (api_key or "").strip()
        self.url = url
        self.model = model
        self.timeout = max(0.1, float(timeout))
        self._slots = max(1, int(concurrency))
        # Public so a caller fanning questions out can size its own gate to
        # this and never meet `busy` from its own burst.
        self.concurrency = self._slots
        self._in_flight = 0
        self._cache: OrderedDict = OrderedDict()
        self._cache_size = max(0, int(cache_size))
        self._transport = transport or _urllib_post
        self._clock = clock
        self._said_no_key = False
        self.backend = backend or JEV_BACKEND
        # The opt-in comparison (see the module docstring): a second client
        # asked the same questions, and where its rows go.
        self.shadow = shadow
        self.compare_sink = compare_sink
        self._compares: set = set()

    @classmethod
    def from_env(cls, environ=None, **kw) -> "Client":
        env = os.environ if environ is None else environ
        name = kw.pop("backend_name", None) or backend_name(env)
        common = dict(
            timeout=float(env.get("JEV_TIMEOUT_SECONDS", TIMEOUT_SECONDS)),
            concurrency=int(env.get("JEV_CONCURRENCY", CONCURRENCY)),
        )
        settings = _settings(name, env)
        other = backend_name(env, "JEV_COMPARE_BACKEND")
        if other and other != name and "shadow" not in kw:
            kw["shadow"] = cls.from_env(
                env, backend_name=other, transport=kw.get("transport")
            )
            # A second backend never gets a sink of its own.
        return cls(
            settings.pop("api_key"), backend=BACKENDS[name], **settings, **common, **kw
        )

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def ready(self, kind: str) -> bool:
        """True when a key is set. Without one, says so ONCE per process."""
        if self._key:
            return True
        if not self._said_no_key:
            log.warning(
                "jev: no TYPESAFE_API_KEY; %s and every other judgment keeps "
                "the heuristic",
                kind,
            )
            self._said_no_key = True
        return False

    def _remember(self, key: str, value: tuple) -> None:
        if not self._cache_size:
            return
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _release(self, _future) -> None:
        self._in_flight -= 1

    async def _free_slot(self, wait: float) -> bool:
        """True once a request slot is free, waiting at most `wait` seconds.

        Every kind shares the one client, so a background pass that fires
        while another kind's burst holds every slot met `busy` at once: 26 of
        607 guild_recipient and 162 of 950 item_keep questions in one day on
        the dev realm (#267). A pass nothing waits on can afford to queue
        briefly; one the world waits on passes 0 and keeps the old answer.
        """
        deadline = self._clock() + max(0.0, float(wait))
        while self._in_flight >= self._slots:
            if self._clock() >= deadline:
                return False
            await asyncio.sleep(SLOT_POLL_SECONDS)
        return True

    async def ask(
        self, kind: str, state, questions: dict, wait: float = 0.0
    ) -> Outcome:
        """The active backend's answer; with a comparison backend set, the
        same question is also put to it, off this call's path."""
        outcome = await self._ask_one(kind, state, questions, wait)
        if self.shadow is not None and self.compare_sink is not None:
            self._start_compare(kind, state, questions, outcome)
        return outcome

    def _start_compare(self, kind, state, questions, active: Outcome) -> None:
        # Bounded: the comparison client has its own slots and answers `busy`
        # at once, and no more tasks than four times its slots are held.
        if len(self._compares) >= 4 * self.shadow.concurrency:
            return
        task = asyncio.ensure_future(self._compare(kind, state, questions, active))
        self._compares.add(task)
        task.add_done_callback(self._compares.discard)

    async def _compare(self, kind, state, questions, active: Outcome) -> None:
        try:
            other = await self.shadow._ask_one(kind, state, questions)
            # A repeat (cached) was recorded when it was first asked; busy
            # and no_key asked nothing.
            if other.status in (CACHED, BUSY, NO_KEY):
                return
            rows = compare_rows(
                kind,
                questions,
                active,
                other,
                self.backend.name,
                self.shadow.backend.name,
            )
            await self.compare_sink(rows)
        except Exception:
            log.exception("jev: comparison for %s was not recorded", kind)

    async def drain_compare(self) -> None:
        """Wait for comparisons in flight (tests, shutdown)."""
        if self._compares:
            await asyncio.gather(*list(self._compares), return_exceptions=True)

    async def _ask_one(
        self, kind: str, state, questions: dict, wait: float = 0.0
    ) -> Outcome:
        """Ask every question about `state` in one request.

        All or nothing: every question must come back well-typed, or
        `answers` is None. A partial answer would have the caller act on half
        a judgment, and the other half is exactly the one that went wrong.

        `wait` is how long to queue for a free slot before answering `busy`;
        0, the default, answers `busy` at once.
        """
        started = self._clock()

        def elapsed() -> int:
            return int(round((self._clock() - started) * 1000))

        if not self.ready(kind):
            return Outcome(NO_KEY, 0)
        key = _cache_key(self.backend.name + ":" + self.model, state, questions)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return Outcome(CACHED, 0, answers=hit[0], model=hit[1])
        # No await between a free slot and taking it (`_in_flight += 1`
        # below): on one event loop no other ask can run in that gap, so a
        # woken waiter cannot overfill the slots.
        if not await self._free_slot(wait):
            log.info("jev: kind=%s status=busy in_flight=%d", kind, self._in_flight)
            return Outcome(BUSY, elapsed())
        # The deadline starts when the request is sent, not while it queued.
        started = self._clock()
        url, body, headers = self.backend.request(
            self.url, self.model, self._key, state, questions
        )
        self._in_flight += 1
        task = asyncio.ensure_future(
            asyncio.to_thread(self._transport, url, body, headers, self.timeout)
        )
        # The slot is freed when the THREAD ends, not when this call gives up
        # on it, so an abandoned request still counts against the limit.
        task.add_done_callback(self._release)
        task.add_done_callback(_consume)
        try:
            status, raw = await asyncio.wait_for(asyncio.shield(task), self.timeout)
        except asyncio.TimeoutError:
            return self._said(kind, Outcome(TIMEOUT, elapsed()))
        except Exception as exc:  # the transport's own failure, of any kind
            return self._said(
                kind, Outcome(ERROR, elapsed(), detail=type(exc).__name__)
            )
        if status != 200:
            return self._said(
                kind, Outcome(ERROR, elapsed(), detail="http %s" % status)
            )
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return self._said(kind, Outcome(INVALID, elapsed(), detail="not json"))
        answers, model = self.backend.read(questions, data)
        if answers is None:
            return self._said(
                kind, Outcome(INVALID, elapsed(), detail="no typed answers")
            )
        self._remember(key, (answers, model))
        return self._said(
            kind, Outcome(ANSWERED, elapsed(), answers=answers, model=model)
        )

    def _said(self, kind: str, outcome: Outcome) -> Outcome:
        outcome = dataclasses.replace(outcome, backend=self.backend.name)
        TALLY.status(self.backend.name, kind, outcome.status)
        TALLY.maybe_log()
        if outcome.answers is None:
            # A failure that repeats is said once an hour with the count it
            # swallowed, not once per call (#797).
            held = TALLY.first_failure(
                (self.backend.name, outcome.status, outcome.detail)
            )
            if held is None:
                return outcome
            log.warning(
                "jev: backend=%s kind=%s status=%s%s (%d like it held back this hour)",
                self.backend.name,
                kind,
                outcome.status,
                (" detail=" + outcome.detail) if outcome.detail else "",
                held,
            )
            return outcome
        log.info(
            "jev: kind=%s status=%s latency_ms=%d model=%s%s",
            kind,
            outcome.status,
            outcome.latency_ms,
            outcome.model or "-",
            (" detail=" + outcome.detail) if outcome.detail else "",
        )
        return outcome


def _consume(future) -> None:
    """Read an abandoned request's exception so asyncio does not warn."""
    if not future.cancelled():
        future.exception()

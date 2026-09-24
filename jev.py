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
`effective_mode`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass

log = logging.getLogger("wow-overseer.jev")

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT_SECONDS = 3.0
CONCURRENCY = 4
CACHE_SIZE = 512
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

    @classmethod
    def from_env(cls, environ=None, **kw) -> "Client":
        env = os.environ if environ is None else environ
        return cls(
            env.get("TYPESAFE_API_KEY", ""),
            url=env.get("JEV_URL", URL) or URL,
            model=env.get("JEV_MODEL", MODEL) or MODEL,
            timeout=float(env.get("JEV_TIMEOUT_SECONDS", TIMEOUT_SECONDS)),
            concurrency=int(env.get("JEV_CONCURRENCY", CONCURRENCY)),
            **kw,
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
        key = _cache_key(self.model, state, questions)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return Outcome(CACHED, 0, answers=hit[0], model=hit[1])
        if not await self._free_slot(wait):
            log.info("jev: kind=%s status=busy in_flight=%d", kind, self._in_flight)
            return Outcome(BUSY, elapsed())
        # The deadline starts when the request is sent, not while it queued.
        started = self._clock()
        body = json.dumps(
            {"state": state, "model": self.model, "questions": questions}
        ).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + self._key,
            "Content-Type": "application/json",
        }
        self._in_flight += 1
        task = asyncio.ensure_future(
            asyncio.to_thread(self._transport, self.url, body, headers, self.timeout)
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
        answers_raw = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers_raw, dict):
            return self._said(kind, Outcome(INVALID, elapsed(), detail="no answers"))
        answers = {}
        for qid, question in questions.items():
            typed = parse(question, answers_raw.get(qid))
            if typed is None:
                return self._said(
                    kind, Outcome(INVALID, elapsed(), detail="bad answer for " + qid)
                )
            answers[qid] = typed
        model = str(data.get("model") or "")
        self._remember(key, (answers, model))
        return self._said(
            kind, Outcome(ANSWERED, elapsed(), answers=answers, model=model)
        )

    def _said(self, kind: str, outcome: Outcome) -> Outcome:
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

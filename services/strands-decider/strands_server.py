"""A localhost HTTP wrapper that serves the Strands Decider with the Jev body (#822).

WHAT IT IS. The Strands Decider is an open decision model: it answers typed
questions (noul, choice, score) about a state and never generates text. This
service loads it once, in process, and answers the SAME request and response
body that jev.py's JevBackend sends and reads, so the bridge's `strands`
adapter is a thin JevBackend subclass and nothing in jev.py has to translate.

THE CONTRACT.

  POST /  and  POST /v1/ask
    request   {"state": ..., "model": ..., "questions": {qid: question}}
              A question is what jev.choice / jev.noul / jev.score build:
              {"type": "choice", "instructions": ..., "criteria": {option: text}}
              {"type": "noul",   "instructions": ..., "criteria": {"true"/"false": text}}
              {"type": "score",  "instructions": ..., "criteria": [level, ...]}
              "model" is accepted and ignored: one process serves one model,
              and the response names it.
    200       {"model": "<model id>", "answers": {qid: answer}, "latency_ms": n}
              choice  {"type": "choice", "choice": label,
                       "probabilities": {option: p}, "confidence": c}
              noul    {"type": "noul", "noul": p}
              score   {"type": "score", "score": x,
                       "probabilities": {"0": p, ...}, "confidence": c}
              Exactly the shapes jev.parse accepts. A question kind the loaded
              decider does not support is left out of "answers", so jev.parse
              returns None for it and the heuristic acts. latency_ms is the
              decider's own time for the request, in milliseconds.
    400       the body is not JSON, or not a well-formed Jev request
    408       the whole body did not arrive within 30 seconds of the headers
              (a total deadline, so a slow trickle is cut off too), or the
              connection went 30 seconds without a byte
    501       the loaded decider does not declare which question kinds it answers
    413       the body is larger than STRANDS_MAX_BODY_BYTES
    422       the decider refused the request (a prompt it cannot fit)
    500       the decider failed
    503       the model is not loaded (still loading, or its load failed)

  GET /healthz
    200       {"status": "ok", "model": "<model id>"} once the model is loaded
    503       {"status": "loading"} or {"status": "error", "error": ...}

  Every error body is {"error": "<reason>"}. jev treats any non-200 as a
  failed ask, which is None and the heuristic.

NO AUTHENTICATION. It binds 127.0.0.1 by default and is meant to be reached
only from the same node (or the same pod). BIND overrides the address; binding
anything wider is the operator's choice and the operator's network policy.

ENVIRONMENT.

  BIND                    address to bind (default 127.0.0.1)
  PORT                    port (default 8790)
  STRANDS_DECIDER         `library` (default): the strands-decider package,
                          in process. `fake`: a deterministic stand-in with no
                          model, for smoke tests only; it answers choice and
                          noul and leaves score out.
  STRANDS_CHECKPOINT      Hugging Face model id or a local checkpoint folder
                          (default StrandsAgents/strands-decider-2B-qwen3.5-v1-2610)
  STRANDS_DEVICE          cpu (default), cuda, mps or mlx
  STRANDS_MODEL_NAME      the model id answers carry (default: the
                          checkpoint's last path segment)
  STRANDS_MAX_BODY_BYTES  largest request body accepted (default 1048576)

  The library downloads the weights to the Hugging Face cache on first load
  (HF_HOME); mount that as a volume so a restart does not download again.

WHY THE STANDARD LIBRARY. The package ships its own FastAPI server
(`strands-decider serve`, POST /v1/systemone). This wrapper exists anyway for
the contract above: the jev routes, a /healthz that is 503 until the model is
loaded (a readiness probe, not just a liveness one), a 400 on a malformed
body instead of a framework's 422, request size limits, and a fake decider
that lets the repo's stdlib-only test suite drive the whole HTTP contract with
no torch installed. Only the decider itself needs the package, and it is
imported lazily, inside LibraryDecider.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("strands-decider")

DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8790
DEFAULT_CHECKPOINT = "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"
DEFAULT_DEVICE = "cpu"
DEFAULT_MAX_BODY = 1 << 20
REQUEST_TIMEOUT_SECONDS = 30.0

ASK_PATHS = ("/", "/v1/ask")
HEALTH_PATH = "/healthz"

KINDS = ("choice", "noul", "score")
MAX_CHOICE_OPTIONS = 255
MIN_SCORE_LEVELS = 2
MAX_SCORE_LEVELS = 10


class BadRequest(ValueError):
    """The body is not a well-formed Jev request."""


# ---------------------------------------------------------------------------
# REQUEST VALIDATION


def _is_content(value) -> bool:
    """A state, instructions or option text: a string or structured data."""
    return isinstance(value, (str, dict, list))


def _check_choice(qid: str, criteria) -> None:
    if not isinstance(criteria, dict):
        raise BadRequest(f"choice {qid!r} needs criteria as an object")
    if not 2 <= len(criteria) <= MAX_CHOICE_OPTIONS:
        raise BadRequest(
            f"choice {qid!r} needs 2 to {MAX_CHOICE_OPTIONS} options, "
            f"got {len(criteria)}"
        )
    if any(text is not None and not _is_content(text) for text in criteria.values()):
        raise BadRequest(f"choice {qid!r} has an option that is not text")


def _check_score(qid: str, criteria) -> None:
    if not isinstance(criteria, list) or not all(
        isinstance(level, str) for level in criteria
    ):
        raise BadRequest(f"score {qid!r} needs criteria as a list of strings")
    if not MIN_SCORE_LEVELS <= len(criteria) <= MAX_SCORE_LEVELS:
        raise BadRequest(
            f"score {qid!r} needs {MIN_SCORE_LEVELS} to {MAX_SCORE_LEVELS} "
            f"levels, got {len(criteria)}"
        )


def _check_noul(qid: str, criteria) -> None:
    if criteria is None:
        return
    if not isinstance(criteria, dict) or not set(criteria) <= {"true", "false"}:
        raise BadRequest(f"noul {qid!r} criteria keys must be true/false")


_CRITERIA_CHECKS = {"choice": _check_choice, "score": _check_score, "noul": _check_noul}


def _check_question(qid: str, question) -> None:
    if not isinstance(question, dict):
        raise BadRequest(f"question {qid!r} is not an object")
    kind = question.get("type")
    if kind not in _CRITERIA_CHECKS:
        raise BadRequest(f"question {qid!r} has type {kind!r}, not one of {KINDS}")
    if not _is_content(question.get("instructions")):
        raise BadRequest(f"question {qid!r} has no instructions")
    _CRITERIA_CHECKS[kind](qid, question.get("criteria"))


def parse_request(raw: bytes) -> tuple:
    """(state, questions) from a request body, or BadRequest."""
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BadRequest(f"body is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise BadRequest("body is not a JSON object")
    if "state" not in body or not _is_content(body["state"]):
        raise BadRequest("state is missing or not a string, object or list")
    questions = body.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise BadRequest("questions must be a non-empty object")
    for qid, question in questions.items():
        _check_question(qid, question)
    return body["state"], questions


# ---------------------------------------------------------------------------
# ANSWER SHAPING: exactly what jev.parse accepts, nothing taken on trust


def _unit(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return None
    return number


def _distribution(raw, keys) -> dict | None:
    if not isinstance(raw, dict) or set(raw) != set(keys):
        return None
    out = {}
    for key in keys:
        p = _unit(raw[key])
        if p is None:
            return None
        out[key] = p
    return out


def shape_answer(question: dict, answer) -> dict | None:
    """The decider's answer in the Jev shape for its question, or None.

    A None leaves the qid out of the response, which jev reads as no answer.
    The decider is checked the same way jev checks a remote API: an option
    nobody offered, a missing probability or a score outside its levels is
    not passed on.
    """
    if not isinstance(answer, dict):
        return None
    kind = question["type"]
    if kind == "noul":
        p = _unit(answer.get("noul"))
        return None if p is None else {"type": "noul", "noul": p}
    if kind == "choice":
        options = list(question["criteria"])
        picked = answer.get("choice")
        probabilities = _distribution(answer.get("probabilities"), options)
        confidence = _unit(answer.get("confidence"))
        if picked not in options or probabilities is None or confidence is None:
            return None
        return {
            "type": "choice",
            "choice": picked,
            "probabilities": probabilities,
            "confidence": confidence,
        }
    levels = [str(n) for n in range(len(question["criteria"]))]
    probabilities = _distribution(answer.get("probabilities"), levels)
    confidence = _unit(answer.get("confidence"))
    value = answer.get("score")
    if probabilities is None or confidence is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or not 0 <= value <= len(levels) - 1:
        return None
    return {
        "type": "score",
        "score": float(value),
        "probabilities": probabilities,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# DECIDERS: `model`, `kinds` and `decide(state, questions) -> {qid: answer}`


class LibraryDecider:
    """The strands-decider package, loaded once, called in process.

    The package's engine answers all three kinds with the Jev field names
    (strands_decider.schema: NoulAnswer, ChoiceAnswer, ScoreAnswer), so
    `decide` only dumps its pydantic answers to dicts.
    """

    kinds = frozenset(KINDS)

    def __init__(self, checkpoint: str, device: str, model_name: str = ""):
        from strands_decider.infer import load_engine
        from strands_decider.schema import SystemOneRequest

        self._request = SystemOneRequest
        self._engine = load_engine(checkpoint, device=device)
        self.model = (
            model_name or os.path.basename(checkpoint.rstrip("/")) or checkpoint
        )
        self._engine.cfg.model_name = self.model

    def decide(self, state, questions: dict) -> dict:
        # The package's own pydantic validation raises ValidationError, a
        # ValueError, as does an engine that cannot fit the prompt: both 422.
        request = self._request(state=state, questions=questions)
        response = self._engine.evaluate(request)
        return {qid: answer.model_dump() for qid, answer in response.answers.items()}


class FakeDecider:
    """A deterministic stand-in with no model, for tests and smoke checks.

    A choice leans on its options in the order given (the first is the most
    likely), a noul is `noul`, and a score, when supported, leans on the
    middle level. Any kind outside `kinds` gets no answer.
    """

    def __init__(
        self,
        model: str = "strands-fake",
        kinds=("choice", "noul"),
        noul: float = 0.75,
        delay: float = 0.0,
        error: Exception | None = None,
    ):
        self.model = model
        self.kinds = frozenset(kinds)
        self.noul = noul
        self.delay = delay
        self.error = error
        self.calls = []

    def decide(self, state, questions: dict) -> dict:
        self.calls.append((state, questions))
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        out = {}
        for qid, question in questions.items():
            kind = question["type"]
            if kind == "noul":
                out[qid] = {"type": "noul", "noul": self.noul}
            elif kind == "choice":
                options = list(question["criteria"])
                weights = list(range(len(options), 0, -1))
                total = float(sum(weights))
                probabilities = {
                    o: w / total for o, w in zip(options, weights, strict=True)
                }
                top = weights[0] / total
                n = len(options)
                out[qid] = {
                    "type": "choice",
                    "choice": options[0],
                    "probabilities": probabilities,
                    "confidence": (n * top - 1.0) / (n - 1.0),
                }
            else:
                n = len(question["criteria"])
                mid = (n - 1) // 2
                probabilities = {str(i): (1.0 if i == mid else 0.0) for i in range(n)}
                out[qid] = {
                    "type": "score",
                    "score": float(mid),
                    "probabilities": probabilities,
                    "confidence": 1.0,
                }
        return out


# ---------------------------------------------------------------------------
# THE SERVICE: holds the decider once it is loaded


class Service:
    """The loaded decider (or why there is none) and one ask."""

    def __init__(self, decider=None):
        self.decider = decider
        self.error = ""
        # One forward at a time: the model owns the device, and on mps two
        # overlapping calls abort the process (the package's own server
        # serialises there too). Jev's own in-flight cap keeps the queue short.
        self._lock = threading.Lock()

    def load(self, factory) -> None:
        """Build the decider with `factory()`; a failure is kept and served as 503."""
        try:
            self.decider = factory()
            log.info("strands-decider: loaded %s", self.decider.model)
        except Exception as exc:  # noqa: BLE001 - any load failure is a 503 with its reason
            self.error = f"{type(exc).__name__}: {exc}"
            log.exception("strands-decider: model load failed")

    def health(self) -> tuple:
        if self.decider is not None:
            return 200, {"status": "ok", "model": self.decider.model}
        if self.error:
            return 503, {"status": "error", "error": self.error}
        return 503, {"status": "loading"}

    def ask(self, raw: bytes) -> tuple:
        decider = self.decider
        if decider is None:
            return 503, {"error": self.error or "model is not loaded yet"}
        try:
            state, questions = parse_request(raw)
        except BadRequest as exc:
            return 400, {"error": str(exc)}
        kinds = getattr(decider, "kinds", None)
        if kinds is None:
            return 501, {
                "error": "the loaded decider does not declare its question kinds"
            }
        supported = {q: v for q, v in questions.items() if v["type"] in kinds}
        answers = {}
        started = time.perf_counter()
        if supported:
            try:
                with self._lock:
                    raw_answers = decider.decide(state, supported)
            except ValueError as exc:
                return 422, {"error": str(exc)}
            except Exception as exc:  # noqa: BLE001 - the caller gets a 500, the log the trace
                log.exception("strands-decider: decide failed")
                return 500, {"error": f"{type(exc).__name__}: {exc}"}
            if not isinstance(raw_answers, dict):
                raw_answers = {}
            for qid, question in supported.items():
                shaped = shape_answer(question, raw_answers.get(qid))
                if shaped is not None:
                    answers[qid] = shaped
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return 200, {
            "model": decider.model,
            "answers": answers,
            "latency_ms": latency_ms,
        }


# ---------------------------------------------------------------------------
# HTTP


class Handler(BaseHTTPRequestHandler):
    """The routes. make_handler binds a Service and the limits to a subclass."""

    service: Service
    max_body: int = DEFAULT_MAX_BODY
    server_version = "strands-decider"
    # A socket timeout per connection: a client that announces a body and
    # stops sending gives up its thread after this many seconds instead of
    # holding it (StreamRequestHandler applies it to the socket).
    timeout = REQUEST_TIMEOUT_SECONDS
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        if self._path() == HEALTH_PATH:
            self._send(*self.service.health())
        else:
            self._send(404, {"error": "not found"})

    def _refuse(self, status: int, error: str) -> None:
        # Whatever of the body is unread would be parsed as the next
        # request, so a refused body also ends the connection.
        self.close_connection = True
        self._send(status, {"error": error})

    def _read_within_deadline(self, length: int) -> bytes | None:
        """Read `length` bytes within `self.timeout` seconds in total, or None.

        The deadline starts when the body read starts, so a client that
        trickles one byte at a time cannot hold the thread past it. A peer
        that closes early returns the short bytes (the caller answers 400).
        """
        deadline = time.monotonic() + self.timeout
        chunks = []
        remaining = length
        try:
            while remaining > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self.connection.settimeout(left)
                chunk = self.rfile.read1(min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except TimeoutError:
            return None
        finally:
            self.connection.settimeout(self.timeout)
        return b"".join(chunks)

    def _body(self) -> bytes | None:
        """The request body, or None once a refusal has been sent."""
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._refuse(411, "Content-Length is required")
            return None
        if length < 0:
            self._refuse(400, "Content-Length is negative")
            return None
        if length > self.max_body:
            self._refuse(413, f"body is over {self.max_body} bytes")
            return None
        raw = self._read_within_deadline(length)
        if raw is None:
            self._refuse(408, "body not received in time")
            return None
        if len(raw) < length:
            self._refuse(400, "body is shorter than Content-Length")
            return None
        return raw

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        if self._path() not in ASK_PATHS:
            self._send(404, {"error": "not found"})
            return
        raw = self._body()
        if raw is not None:
            self._send(*self.service.ask(raw))

    def log_message(self, format, *args) -> None:  # noqa: A002 - http.server's signature
        log.debug("%s %s", self.address_string(), format % args)


def make_handler(
    service: Service,
    max_body: int = DEFAULT_MAX_BODY,
    request_timeout: float = REQUEST_TIMEOUT_SECONDS,
):
    """A Handler subclass bound to one service and its limits."""
    return type(
        "BoundHandler",
        (Handler,),
        {"service": service, "max_body": max_body, "timeout": request_timeout},
    )


def make_server(
    service: Service,
    bind: str,
    port: int,
    max_body: int = DEFAULT_MAX_BODY,
    request_timeout: float = REQUEST_TIMEOUT_SECONDS,
):
    return ThreadingHTTPServer(
        (bind, port), make_handler(service, max_body, request_timeout)
    )


def decider_factory(environ):
    """A no-argument callable that builds the decider the environment names."""
    kind = str(environ.get("STRANDS_DECIDER", "") or "library").strip().lower()
    if kind == "fake":
        return lambda: FakeDecider(
            model=environ.get("STRANDS_MODEL_NAME") or "strands-fake"
        )
    if kind != "library":
        raise SystemExit(f"STRANDS_DECIDER={kind!r} is not library or fake")
    checkpoint = environ.get("STRANDS_CHECKPOINT") or DEFAULT_CHECKPOINT
    device = environ.get("STRANDS_DEVICE") or DEFAULT_DEVICE
    name = environ.get("STRANDS_MODEL_NAME") or ""
    return lambda: LibraryDecider(checkpoint, device, name)


def main(environ=None) -> None:
    env = os.environ if environ is None else environ
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    bind = env.get("BIND") or DEFAULT_BIND
    port = int(env.get("PORT") or DEFAULT_PORT)
    max_body = int(env.get("STRANDS_MAX_BODY_BYTES") or DEFAULT_MAX_BODY)
    factory = decider_factory(env)
    service = Service()
    server = make_server(service, bind, port, max_body)
    # Serve /healthz (503) while the model loads: a load takes seconds to
    # minutes (a first start downloads the weights), and a readiness probe
    # should see "loading", not a refused connection.
    threading.Thread(target=service.load, args=(factory,), daemon=True).start()
    log.info("strands-decider: listening on %s:%d", bind, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

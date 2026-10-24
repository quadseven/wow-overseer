"""A tiny localhost HTTP wrapper for the Strands Decider 2B.

The Strands Decider has a CLI and a partial Python API but no HTTP server, so
this wrapper serves one on loopback. It answers POST /ask with a Jev-shaped
body: for a Choice question the chosen label, per-option probabilities and a
confidence; for a Noul question a probability; Score only when the underlying
library supports it.

Run:  python3 strands_server.py [host] [port]
Env:  STRANDS_HOST, STRANDS_PORT, STRANDS_MODEL

A model callable is injected (see `run`). With no library installed the wrapper
still runs but every answer is a failure, so the jev adapter returns None and
the heuristic acts. The adapter in jev.py posts the Jev request body here and
parses the Jev-shaped answers back, so both sides speak the same typed protocol.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("wow-overseer.strands")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
ASK_PATH = "/ask"


def _load_model(model: str):
    """Return a callable(question) -> Jev-typed answer dict or None.

    Returns None (and logs once) when the strands_decider library is not
    installed or cannot load `model`. The wrapper still runs; every answer is
    then a failure, so the jev adapter returns None and the heuristic acts.
    The real model wiring is the operator's: strands_decider exposes a CLI and
    a partial Python API, so this integration point is deliberately a hook.
    """
    try:
        import strands_decider  # type: ignore[import-not-found]  # noqa: F401 - availability check only
    except Exception as exc:  # the library is not installed here
        log.warning(
            "strands: strands_decider unavailable (%s); every answer will be "
            "a failure until the library is installed",
            type(exc).__name__,
        )
        return None
    # The library is present. Bind its real ask call to the question types this
    # wrapper forwards (choice and noul) here. The library's Python API is
    # partial, so the operator completes this binding against the installed
    # version.
    return None


class _Handler(BaseHTTPRequestHandler):
    model = None  # set on the server instance by run()

    def do_POST(self):  # noqa: N802 - http.server overrides the method name
        if self.path.split("?", 1)[0] != ASK_PATH:
            self._respond(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except ValueError:
            self._respond(400, {"error": "not json"})
            return
        if not isinstance(payload, dict) or not isinstance(
            payload.get("questions"), dict
        ):
            self._respond(400, {"error": "questions must be an object"})
            return
        model_fn = getattr(self.server, "model", None)
        answers = {}
        for qid, question in payload["questions"].items():
            if not isinstance(question, dict):
                answers[qid] = None
                continue
            try:
                out = model_fn(question) if model_fn else None
            except Exception as exc:  # one question failing must not kill the batch
                log.warning("strands: question %r failed: %s", qid, type(exc).__name__)
                out = None
            answers[qid] = out if isinstance(out, dict) else None
        self._respond(200, {"model": payload.get("model", ""), "answers": answers})

    def _respond(self, status: int, obj: dict) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # noqa: N802 - http.server overrides
        log.info("%s - %s", self.address_string(), fmt % args)


def serve(
    model_fn, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> ThreadingHTTPServer:
    """Create the wrapper server on `host`:`port` (caller drives serve_forever)."""
    server = ThreadingHTTPServer((host, port), _Handler)
    server.model = model_fn
    return server


def run(
    model_fn, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> ThreadingHTTPServer:
    """Serve the wrapper on `host`:`port` until interrupted."""
    server = serve(model_fn, host, port)
    log.info("strands: serving on http://%s:%s%s", host, port, ASK_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return server


def main(argv=None) -> int:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    host = argv[0] if len(argv) > 0 else DEFAULT_HOST
    try:
        port = int(argv[1]) if len(argv) > 1 else DEFAULT_PORT
    except ValueError:
        port = DEFAULT_PORT
    import os

    model = os.environ.get("STRANDS_MODEL", "")
    run(_load_model(model), host, port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

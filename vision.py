"""What a head's own screen shows, read by a small local vision model.

WHY THIS EXISTS. Jev reads text only: TypeSafe's docs say state is a string,
a JSON object or an array of text values, with no image input, and that
anything else is to be turned into text or structured fields first. The two
family heads have real game clients, and a frame of one shows things no table
holds: a loading screen, a dialog left open, a character facing a wall, a
ghost walking back. So a frame is turned into a handful of typed fields here,
and those fields ride in the Jev state beside the movement facts
(`situation.Situation.vision`).

WHERE THE FRAME COMES FROM. The map server already keeps the last JPEG each
character's capture agent posted (`/api/frame`, frames.py). This module reads
it from there and never captures anything itself. No frame, or a stale one,
is a status and no fields, never a guess.

WHO READS IT. A vision model behind the operator's model gateway (Ollama's
chat API), with a JSON schema so the answer is typed. The schema's first
field is a free sentence (`seen`): measured on the dev world's frames, a
schema of bare enums answered "dungeon_interior" for a snowy outpost and a
desert canyon alike, and letting the model say what it sees first fixed that.

BOUNDED THE WAY jev.Client IS. One look per head per LOOK_SECONDS at most,
answered from the last look in between; one hard deadline; no retry. A slow
or absent model costs the question its `leader_screen` field and nothing else.

NOT ATTESTATION. frames.py says it: anything on the network can post a frame
under any name. A small model's reading of one frame can also simply be
wrong. The state says so in `source`, and nothing here acts on it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("wow-overseer.vision")

FRAME_URL = "http://wow-map:8080/api/frame"
MODEL = "qwen3-vl:4b-32k"
TIMEOUT_SECONDS = 20.0
# At most one look per head this often.
LOOK_SECONDS = 60.0
# A frame older than this is not what the screen shows now.
FRESH_SECONDS = 120

SCREENS = ("in_world", "loading_screen", "login_screen", "disconnected", "blank")
FLAGS = ("dead", "fighting", "swimming", "window_open", "facing_obstacle")
SEEN_CHARS = 160

SCHEMA = {
    "type": "object",
    "properties": dict(
        {
            "seen": {"type": "string"},
            "screen": {"type": "string", "enum": list(SCREENS)},
        },
        **{flag: {"type": "boolean"} for flag in FLAGS},
    ),
    "required": ["seen", "screen", *FLAGS],
}

PROMPT = (
    "One frame of a World of Warcraft (3.3.5a) client, seen from behind the "
    "player's character. Answer as JSON. "
    '"seen": one sentence saying what you see. '
    '"screen": in_world, loading_screen, login_screen, disconnected or blank. '
    '"dead": true if the world is grey (a ghost) or a release-spirit or '
    "resurrect box shows. "
    '"fighting": true if the character or its party is attacking or being '
    "attacked. "
    '"swimming": true if the character is in water. '
    '"window_open": true if a vendor, quest, gossip, bag, map or error window '
    "covers the middle of the screen (the chat box, quest tracker and minimap "
    "do not count). "
    '"facing_obstacle": true if a wall, cliff, tree or rock fills the view '
    "right in front of the character."
)

SOURCE = "a small vision model's reading of one frame; it can be wrong"

# Look.status values. Only SEEN carries fields.
SEEN = "seen"
OFF = "off"
NO_FRAME = "no_frame"
STALE = "stale"
FAILED = "failed"
INVALID = "invalid"


def enabled(environ=None) -> bool:
    """VISION_MODE=off turns every look off; anything else leaves it on."""
    env = os.environ if environ is None else environ
    return str(env.get("VISION_MODE", "") or "").strip().lower() != "off"


def heads(environ=None) -> frozenset:
    """The characters with a game client, from WOW_STREAMED_CHARACTERS.

    UNSET MEANS NOBODY HERE, unlike the Watch tab's reading (family.py), where
    unset means every character gets a stream URL to try. A look costs a
    model call, and a character with no client has no frame to look at.
    """
    env = os.environ if environ is None else environ
    raw = str(env.get("WOW_STREAMED_CHARACTERS", "") or "")
    return frozenset(n.strip() for n in raw.split(",") if n.strip())


def _ascii(text: str) -> str:
    """Printable ASCII only, one line. A small model can drift into another
    script mid-sentence, and the sentence is only ever a hint."""
    return " ".join("".join(c for c in text if 32 <= ord(c) < 127).split())


def parse(raw) -> dict | None:
    """The model's answer as typed fields, or None. Nothing is taken on trust:
    every key must be present with its type, and the screen one of SCREENS."""
    if isinstance(raw, (bytes, str)):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(raw, dict):
        return None
    screen = raw.get("screen")
    seen = raw.get("seen")
    if screen not in SCREENS or not isinstance(seen, str):
        return None
    out = {"screen": screen}
    for flag in FLAGS:
        value = raw.get(flag)
        if not isinstance(value, bool):
            return None
        out[flag] = value
    out["seen"] = _ascii(seen)[:SEEN_CHARS]
    return out


def answer_text(body: dict) -> str:
    """The answer out of an Ollama chat reply. With a `format` schema and
    thinking off, Ollama has been measured putting the JSON in `thinking`
    and leaving `content` empty, so both are read."""
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or message.get("thinking") or "")


def request_body(model: str, jpeg: bytes) -> dict:
    return {
        "model": model,
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "num_predict": 300},
        "messages": [
            {
                "role": "user",
                "content": PROMPT,
                "images": [base64.b64encode(jpeg).decode("ascii")],
            }
        ],
    }


@dataclass(frozen=True)
class Look:
    """One look at one head's screen. `fields` is None unless status is SEEN."""

    name: str
    status: str
    at: float
    fields: dict | None = None
    frame_age: int | None = None
    latency_ms: int = 0

    def state(self, now: float) -> dict | None:
        """What the Jev state carries, or None when nothing was seen."""
        if self.fields is None:
            return None
        age = int(now - self.at) + int(self.frame_age or 0)
        return dict(self.fields, seconds_old=max(0, age), source=SOURCE)


def _http(url: str, body: bytes | None, timeout: float) -> tuple:
    """GET (body None) or POST JSON; (status, bytes). Runs in a thread."""
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(  # noqa: S310 - operator-configured in-cluster URLs
        url, data=body, headers=headers, method="POST" if body is not None else "GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-configured in-cluster URLs
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read() or b""
        finally:
            exc.close()


def vision_url(environ) -> str:
    """VISION_URL, else the Ollama chat path beside the bridge's own LLM_URL.

    One gateway, named once: the bridge already talks to the model gateway's
    OpenAI path, and the same gateway serves Ollama's `/api/chat`, which is
    the path that takes images and a JSON schema. "" (off) when neither says.
    """
    explicit = str(environ.get("VISION_URL", "") or "").strip()
    if explicit:
        return explicit
    llm = str(environ.get("LLM_URL", "") or "").strip()
    suffix = "/v1/chat/completions"
    if llm.endswith(suffix):
        return llm[: -len(suffix)] + "/api/chat"
    return ""


class Seer:
    """Looks at a head's last frame, at most once per LOOK_SECONDS."""

    def __init__(
        self,
        *,
        frame_url: str = FRAME_URL,
        vision_url: str = "",
        model: str = MODEL,
        timeout: float = TIMEOUT_SECONDS,
        every: float = LOOK_SECONDS,
        on: bool = True,
        transport=None,
        clock=time.monotonic,
    ):
        self.frame_url = frame_url
        self.vision_url = vision_url
        self.model = model
        self.timeout = max(1.0, float(timeout))
        self.every = float(every)
        self.on = bool(on) and bool(vision_url)
        self._transport = transport or _http
        self._clock = clock
        self._last: dict = {}
        self._busy: set = set()

    @classmethod
    def from_env(cls, environ=None, **kw) -> "Seer":
        env = os.environ if environ is None else environ
        return cls(
            frame_url=env.get("VISION_FRAME_URL", FRAME_URL) or FRAME_URL,
            vision_url=vision_url(env),
            model=env.get("VISION_MODEL", MODEL) or MODEL,
            timeout=float(env.get("VISION_TIMEOUT_SECONDS", TIMEOUT_SECONDS)),
            every=float(env.get("VISION_LOOK_SECONDS", LOOK_SECONDS)),
            on=enabled(env),
            **kw,
        )

    def last(self, name: str) -> Look | None:
        return self._last.get(name)

    async def look(self, name: str) -> Look:
        """The head's screen now, or the last look if it is recent enough."""
        now = self._clock()
        if not self.on:
            return Look(name, OFF, now)
        prior = self._last.get(name)
        if prior is not None and now - prior.at < self.every:
            return prior
        if name in self._busy:
            return prior or Look(name, FAILED, now)
        self._busy.add(name)
        try:
            found = await asyncio.wait_for(
                asyncio.to_thread(self._look_now, name, now), self.timeout + 5.0
            )
        except asyncio.TimeoutError:
            found = Look(name, FAILED, now)
        except Exception as exc:  # the transport's own failure, of any kind
            log.info("vision: %s look failed: %s", name, type(exc).__name__)
            found = Look(name, FAILED, now)
        finally:
            self._busy.discard(name)
        self._last[name] = found
        log.info(
            "vision: %s status=%s frame_age=%s latency_ms=%d%s",
            name,
            found.status,
            found.frame_age,
            found.latency_ms,
            (" screen=" + found.fields["screen"]) if found.fields else "",
        )
        return found

    def _look_now(self, name: str, now: float) -> Look:
        sep = "&" if "?" in self.frame_url else "?"
        status, raw = self._transport(
            "%s%sname=%s&meta=1" % (self.frame_url, sep, name), None, self.timeout
        )
        if status != 200:
            return Look(name, NO_FRAME, now)
        try:
            meta = json.loads(raw)
        except (TypeError, ValueError):
            return Look(name, NO_FRAME, now)
        age = meta.get("captured_seconds_ago") if isinstance(meta, dict) else None
        if not isinstance(meta, dict) or not meta.get("has_frame") or age is None:
            return Look(name, NO_FRAME, now)
        if int(age) > FRESH_SECONDS:
            return Look(name, STALE, now, frame_age=int(age))
        status, jpeg = self._transport(
            "%s%sname=%s" % (self.frame_url, sep, name), None, self.timeout
        )
        if status != 200 or not jpeg:
            return Look(name, NO_FRAME, now)
        started = self._clock()
        body = json.dumps(request_body(self.model, jpeg)).encode("utf-8")
        status, raw = self._transport(self.vision_url, body, self.timeout)
        latency = int(round((self._clock() - started) * 1000))
        if status != 200:
            return Look(name, FAILED, now, frame_age=int(age), latency_ms=latency)
        try:
            reply = json.loads(raw)
        except (TypeError, ValueError):
            return Look(name, INVALID, now, frame_age=int(age), latency_ms=latency)
        fields = parse(answer_text(reply))
        if fields is None:
            return Look(name, INVALID, now, frame_age=int(age), latency_ms=latency)
        return Look(
            name, SEEN, now, fields=fields, frame_age=int(age), latency_ms=latency
        )

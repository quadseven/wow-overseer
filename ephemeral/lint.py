"""`eph lint`: decree schema v1 and the rules that keep a decree honest.

No cluster is needed. Errors make the decree unusable; warnings mark a decree
that is well formed but not ready (a TODO issue number, an anchor whose
position has not been captured yet).
"""

import re
from dataclasses import dataclass

from . import anchors as anchors_mod
from . import dbschema, gamedata
from .miniyaml import YamlError, loads

TOP_KEYS = {
    "decree", "id", "family", "proves", "fix", "world", "runs", "duration",
    "cast", "arrange", "act", "observe",
}  # fmt: skip
SET_KEYS = {
    "level", "alive", "health_pct", "money", "skills", "spells_add", "spells_remove",
    "items", "quests", "homebind", "at", "corpse_at",
}  # fmt: skip
GRANT_KEYS = ("money", "skills", "spells_add", "items")  # level has its own range check
ANCHOR_KINDS = (
    "creature",
    "gameobject",
    "areatrigger",
    "graveyard",
    "with",
    "captured",
)
AH_FAMILY = "auction-house"

_KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_NAME = re.compile(r"^[A-Z][a-z]{1,11}$")
_FAMILY = re.compile(r"^family:[a-z]+$")
_GUILD = re.compile(r"^guild:[A-Za-z][A-Za-z ]*:[a-z]+$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_DURATION = re.compile(r"^(\d+)([smh])$")
_PR = re.compile(r"^[A-Za-z0-9_.-]+#\d+$")
_CONFIG_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")
_COORD_KEY = re.compile(
    r"^(x|y|z|o|orientation|position|pos|coords?|coordinates|pos_?[xyzo]|position_?[xyzo])$",
    re.I,
)
_COORD_SQL = re.compile(
    r"\b(position_[xyz]|pos_[xyz]|pos[XYZ]|orientation)\b\s*(=|<|>|<=|>=|<>)\s*-?\d",
    re.I,
)
_CAST_REF = re.compile(r"^cast\[(\d+)\]$")
_AUCTION_WORD = re.compile(r"auction", re.I)
_CEILING_RANGE = re.compile(r"levels?\s+(\d+)\s+to\s+(\d+)", re.I)


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    path: str
    rule: str
    message: str

    def __str__(self):
        return f"{self.level}: {self.path}: [{self.rule}] {self.message}"


def duration_seconds(text):
    m = _DURATION.match(text) if isinstance(text, str) else None
    if not m:
        return None
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)]


class _Lint:
    def __init__(self, anchors, schema):
        self.anchors = anchors
        self.schema = schema
        self.findings = []

    def err(self, path, rule, msg):
        self.findings.append(Finding("error", path, rule, msg))

    def warn(self, path, rule, msg):
        self.findings.append(Finding("warning", path, rule, msg))

    def keys(self, path, obj, allowed, required=()):
        if not isinstance(obj, dict):
            self.err(path, "schema", "must be a mapping")
            return False
        for k in sorted(set(obj) - set(allowed)):
            self.err(f"{path}.{k}", "schema", "unknown key")
        for k in required:
            if k not in obj:
                self.err(f"{path}.{k}", "schema", "required")
        return True


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def lint_document(doc, anchors=None, schema=None):
    """Lint a parsed decree. Returns a list of Finding."""
    lint = _Lint(anchors if anchors is not None else anchors_mod.Anchors.load(),
                 schema if schema is not None else dbschema.Schema.load())  # fmt: skip
    if not lint.keys("decree", doc, TOP_KEYS, ("decree", "id", "proves", "fix", "world",
                                               "runs", "duration", "cast", "observe")):  # fmt: skip
        return lint.findings
    _header(lint, doc)
    whos = _cast(lint, doc)
    aliases = _arrange(lint, doc, whos)
    names = _observe_names(doc)
    _act(lint, doc, whos, names)
    _walk_auction(lint, doc, "cast", doc.get("cast"))
    _observe(lint, doc, whos, aliases)
    _cross_rules(lint, doc)
    _scan_coordinates(lint, doc)
    return lint.findings


def lint_text(text, anchors=None, schema=None):
    try:
        doc = loads(text)
    except YamlError as exc:
        return [Finding("error", "decree", "yaml", str(exc))]
    return lint_document(doc, anchors, schema)


def lint_path(path, anchors=None, schema=None):
    with open(path, encoding="utf-8") as f:
        return lint_text(f.read(), anchors, schema)


def _header(lint, doc):
    if doc.get("decree") != "v1":
        lint.err("decree.decree", "schema", "must be the literal v1")
    if (
        not isinstance(doc.get("id"), str)
        or not _KEBAB.match(doc["id"])
        or len(doc["id"]) > 64
    ):
        lint.err("decree.id", "schema", "must be kebab-case, at most 64 characters")
    if "family" in doc and (
        not isinstance(doc["family"], str) or not _KEBAB.match(doc["family"])
    ):
        lint.err("decree.family", "schema", "must be a kebab-case word")

    proves = doc.get("proves")
    if not isinstance(proves, list) or not proves:
        lint.err("decree.proves", "schema", "must be a non-empty list")
    else:
        for i, p in enumerate(proves):
            path = f"decree.proves[{i}]"
            if lint.keys(
                path, p, ("repo", "issue", "criterion"), ("repo", "issue", "criterion")
            ):
                if not isinstance(p.get("repo"), str) or not _REPO.match(p["repo"]):
                    lint.err(f"{path}.repo", "schema", "must be owner/name")
                _todo_or(
                    lint,
                    f"{path}.issue",
                    p.get("issue"),
                    lambda v: _is_int(v) and v > 0,
                    "a positive integer",
                )
                if (
                    not isinstance(p.get("criterion"), str)
                    or not p["criterion"].strip()
                ):
                    lint.err(
                        f"{path}.criterion", "schema", "must be the live-check box text"
                    )

    fix = doc.get("fix")
    if lint.keys("decree.fix", fix, ("repo", "commit"), ("repo", "commit")):
        if not isinstance(fix.get("repo"), str) or not _REPO.match(fix["repo"]):
            lint.err("decree.fix.repo", "schema", "must be owner/name")
        _todo_or(lint, "decree.fix.commit", fix.get("commit"),
                 lambda v: isinstance(v, str) and bool(_SHA.match(v)), "a hex commit sha")  # fmt: skip

    world = doc.get("world")
    if lint.keys("decree.world", world, ("class", "image", "bridge", "random_bots", "config"),
                 ("class", "image", "bridge")):  # fmt: skip
        if world.get("class") not in ("lean", "full"):
            lint.err("decree.world.class", "schema", "must be lean or full")
        img = world.get("image")
        if img != "follow-dev" and not (
            isinstance(img, dict)
            and set(img) == {"pr"}
            and isinstance(img["pr"], str)
            and _PR.match(img["pr"])
        ):
            lint.err(
                "decree.world.image", "schema", "must be follow-dev or {pr: <repo>#<n>}"
            )
        if world.get("bridge") not in ("on", "off"):
            lint.err("decree.world.bridge", "schema", "must be on or off (quote it: bare on and off are booleans in YAML)" if isinstance(world.get("bridge"), bool) else "must be on or off")  # fmt: skip
        rb = world.get("random_bots", 0)
        if not _is_int(rb) or not 0 <= rb <= 2600:
            lint.err(
                "decree.world.random_bots",
                "schema",
                "must be an integer from 0 to 2600",
            )
        cfg = world.get("config", {})
        if cfg is None:
            cfg = {}
        if not isinstance(cfg, dict):
            lint.err("decree.world.config", "schema", "must be a mapping")
        else:
            for k, v in cfg.items():
                p = f"decree.world.config.{k}"
                if not _CONFIG_KEY.match(str(k)):
                    lint.err(p, "schema", "not a config key name")
                elif k in gamedata.BASELINE_CONFIG_KEYS:
                    lint.err(
                        p,
                        "config",
                        "owned by the world baseline; a decree may not set it",
                    )
                elif (
                    k.startswith("AuctionHouseBot.") and doc.get("family") != AH_FAMILY
                ):
                    lint.err(
                        p,
                        "auction",
                        "the auction house bot stays off outside an auction-house decree",
                    )
                if isinstance(v, (dict, list)):
                    lint.err(p, "schema", "must be a scalar")

    runs = doc.get("runs")
    if lint.keys(
        "decree.runs", runs, ("control", "treatment"), ("control", "treatment")
    ):
        for k in ("control", "treatment"):
            if not _is_int(runs.get(k)) or not 1 <= runs[k] <= 9:
                lint.err(f"decree.runs.{k}", "schema", "must be an integer from 1 to 9")

    secs = duration_seconds(doc.get("duration"))
    if secs is None or not 60 <= secs <= 4 * 3600:
        lint.err(
            "decree.duration", "schema", "must be like 20m or 1h, between 1m and 4h"
        )


def _todo_or(lint, path, value, ok, what):
    if value == "TODO":
        lint.warn(path, "todo", "placeholder still to be filled in")
    elif not ok(value):
        lint.err(path, "schema", f"must be {what}")


def _who_ok(w):
    return isinstance(w, str) and bool(
        _NAME.match(w) or _FAMILY.match(w) or _GUILD.match(w)
    )


def _cast(lint, doc):
    cast = doc.get("cast")
    whos = []
    if not isinstance(cast, list) or not cast:
        lint.err("decree.cast", "schema", "must be a non-empty list")
        return whos
    for i, entry in enumerate(cast):
        path = f"decree.cast[{i}]"
        if not lint.keys(path, entry, ("who", "set", "ceiling"), ("who", "set")):
            continue
        who = entry.get("who")
        if not _who_ok(who):
            lint.err(
                f"{path}.who",
                "schema",
                "must be a character name, family:<name> or guild:<Guild>:<role>",
            )
        else:
            whos.append(who)
        s = entry.get("set")
        if not lint.keys(f"{path}.set", s, SET_KEYS):
            continue
        _cast_set(lint, path, entry, s)
    return whos


def _cast_set(lint, path, entry, s):
    sp = f"{path}.set"
    if "level" in s and (not _is_int(s["level"]) or not 1 <= s["level"] <= 80):
        lint.err(f"{sp}.level", "schema", "must be an integer from 1 to 80")
    if "alive" in s and not isinstance(s["alive"], bool):
        lint.err(f"{sp}.alive", "schema", "must be true or false")
    if "health_pct" in s and (
        not _is_int(s["health_pct"]) or not 1 <= s["health_pct"] <= 100
    ):
        lint.err(f"{sp}.health_pct", "schema", "must be an integer from 1 to 100")
    if "money" in s and (
        not _is_int(s["money"]) or not 0 <= s["money"] <= 4_000_000_000
    ):
        lint.err(f"{sp}.money", "schema", "must be copper, 0 to 4000000000")
    if "skills" in s:
        sk = s["skills"]
        if not isinstance(sk, dict):
            lint.err(f"{sp}.skills", "schema", "must be a mapping")
        else:
            for name, v in sk.items():
                p = f"{sp}.skills.{name}"
                if name not in gamedata.SKILLS:
                    lint.err(
                        p, "schema", f"unknown skill; known: {sorted(gamedata.SKILLS)}"
                    )
                value = v.get("value") if isinstance(v, dict) else v
                mx = v.get("max", value) if isinstance(v, dict) else v
                if isinstance(v, dict) and not set(v) <= {"value", "max"}:
                    lint.err(p, "schema", "only value and max are allowed")
                elif not (_is_int(value) and _is_int(mx) and 1 <= value <= mx <= 450):
                    lint.err(
                        p, "schema", "needs integers with 1 <= value <= max <= 450"
                    )
    for key in ("spells_add", "spells_remove"):
        if key in s and not (
            isinstance(s[key], list) and all(_is_int(x) and x > 0 for x in s[key])
        ):
            lint.err(f"{sp}.{key}", "schema", "must be a list of spell ids")
    if "items" in s:
        items = s["items"]
        if not isinstance(items, list):
            lint.err(f"{sp}.items", "schema", "must be a list")
        else:
            for j, it in enumerate(items):
                p = f"{sp}.items[{j}]"
                if lint.keys(p, it, ("name", "count"), ("name",)):
                    if not isinstance(it["name"], str) or not it["name"]:
                        lint.err(
                            f"{p}.name",
                            "schema",
                            "must be an item name (names, not entry ids)",
                        )
                    if "count" in it and (
                        not _is_int(it["count"]) or not 1 <= it["count"] <= 1000
                    ):
                        lint.err(
                            f"{p}.count", "schema", "must be an integer from 1 to 1000"
                        )
    if "quests" in s:
        q = s["quests"]
        if not isinstance(q, dict):
            lint.err(f"{sp}.quests", "schema", "must be a mapping of quest to state")
        else:
            for k, v in q.items():
                if v not in ("incomplete", "complete", "rewarded"):
                    lint.err(
                        f"{sp}.quests.{k}",
                        "schema",
                        "state must be incomplete, complete or rewarded",
                    )
    for key in ("at", "homebind", "corpse_at"):
        if key in s:
            _anchor(
                lint,
                f"{sp}.{key}",
                s[key],
                nearest=(key == "at"),
                has_corpse="corpse_at" in s,
            )
    if s.get("alive") is False and "corpse_at" not in s:
        lint.err(f"{sp}.alive", "schema", "a dead character needs corpse_at")
    if "corpse_at" in s and s.get("alive") is not False:
        lint.err(
            f"{sp}.corpse_at", "schema", "corpse_at only applies with alive: false"
        )

    grants = [k for k in GRANT_KEYS if k in s]
    ceiling = entry.get("ceiling")
    if ("level" in s or grants) and not (isinstance(ceiling, str) and ceiling.strip()):
        lint.err(
            f"{path}.ceiling",
            "ceiling",
            "required whenever set grants anything (level, money, skills, spells, items)",
        )
    if isinstance(ceiling, str):
        if (
            grants
            and re.search(r"nothing granted", ceiling, re.I)
            and not re.search(r"nothing granted but", ceiling, re.I)
        ):
            lint.err(
                f"{path}.ceiling",
                "ceiling",
                f"says nothing is granted but set grants {grants}",
            )
        if grants and re.search(r"nothing granted but position", ceiling, re.I):
            lint.err(
                f"{path}.ceiling",
                "ceiling",
                f"allows only position but set grants {grants}",
            )
        m = _CEILING_RANGE.search(ceiling)
        if (
            m
            and _is_int(s.get("level"))
            and not int(m.group(1)) <= s["level"] <= int(m.group(2))
        ):
            lint.err(
                f"{sp}.level",
                "ceiling",
                f"level {s['level']} is outside the stated ceiling {m.group(1)} to {m.group(2)}",
            )


def _anchor(lint, path, val, nearest=False, has_corpse=False):
    if (
        not isinstance(val, dict)
        or len(val) != 1
        or next(iter(val)) not in ANCHOR_KINDS
    ):
        lint.err(
            path,
            "coordinates",
            "must be one anchor: "
            + ", ".join(ANCHOR_KINDS)
            + " (no literal coordinates)",
        )
        return
    kind, v = next(iter(val.items()))
    if kind in ("creature", "gameobject", "with"):
        if not isinstance(v, str) or not v.strip():
            lint.err(path, "schema", f"{kind} anchor needs a name")
        elif v.startswith("<"):
            lint.warn(
                path, "todo", f"{kind} name is a placeholder still to be filled in"
            )
    elif kind == "areatrigger":
        if not _is_int(v) or v <= 0:
            lint.err(path, "schema", "areatrigger anchor needs an id")
    elif kind == "graveyard":
        if v == "nearest":
            if not nearest or not has_corpse:
                lint.err(
                    path,
                    "schema",
                    "graveyard: nearest is only for `at` beside a corpse_at",
                )
        elif not _is_int(v) or v <= 0:
            lint.err(path, "schema", "graveyard anchor needs an id or nearest")
    elif kind == "captured":
        if not isinstance(v, str) or not lint.anchors.has(v):
            lint.err(path, "anchor", f"captured anchor {v!r} is not in anchors.yaml")
        elif lint.anchors.is_pending(v):
            lint.warn(
                path,
                "anchor",
                f"captured anchor {v!r} is pending: its position is not captured yet",
            )


def _arrange(lint, doc, whos):
    aliases = set()
    arrange = doc.get("arrange")
    if arrange is None:
        return aliases
    if not isinstance(arrange, list):
        lint.err("decree.arrange", "schema", "must be a list")
        return aliases
    for i, entry in enumerate(arrange):
        path = f"decree.arrange[{i}]"
        if not isinstance(entry, dict) or len(entry) != 1:
            lint.err(
                path, "schema", "must be a one-key mapping: instance, group or creature"
            )
            continue
        kind, v = next(iter(entry.items()))
        if _AUCTION_WORD.search(str(kind)):
            _auction(lint, doc, f"{path}.{kind}")
            continue
        if kind == "instance":
            if lint.keys(f"{path}.instance", v, ("map", "as", "bind"), ("map", "as")):
                if v["map"] not in gamedata.INSTANCE_MAPS:
                    lint.err(
                        f"{path}.instance.map",
                        "schema",
                        f"unknown instance map; known: {sorted(gamedata.INSTANCE_MAPS)}",
                    )
                if not isinstance(v["as"], str) or not re.match(
                    r"^[a-z][a-z0-9_]*$", v["as"]
                ):
                    lint.err(
                        f"{path}.instance.as",
                        "schema",
                        "alias must be lowercase letters, digits, underscore",
                    )
                else:
                    aliases.add(v["as"])
                if "bind" in v and v["bind"] not in whos:
                    lint.err(
                        f"{path}.instance.bind", "schema", "must name a cast member"
                    )
        elif kind == "group":
            if lint.keys(
                f"{path}.group", v, ("members", "leader"), ("members", "leader")
            ):
                if v["members"] not in whos:
                    lint.err(
                        f"{path}.group.members", "schema", "must name a cast member"
                    )
                if not _NAME.match(str(v["leader"])):
                    lint.err(
                        f"{path}.group.leader", "schema", "must be a character name"
                    )
        elif kind == "creature":
            if lint.keys(
                f"{path}.creature", v, ("name", "in", "state"), ("name", "in", "state")
            ):
                if not isinstance(v["name"], str) or not v["name"]:
                    lint.err(f"{path}.creature.name", "schema", "names, not entry ids")
                if v["state"] != "dead":
                    lint.err(
                        f"{path}.creature.state", "schema", "only dead is supported"
                    )
                if v["in"] not in aliases:
                    lint.err(
                        f"{path}.creature.in",
                        "schema",
                        "must name an earlier instance alias",
                    )
        else:
            lint.err(path, "schema", f"unknown arrange kind {kind!r}")
    return aliases


def _auction(lint, doc, path):
    if doc.get("family") != AH_FAMILY:
        lint.err(
            path,
            "auction",
            "auction rows may be seeded only when family is auction-house",
        )


def _observe_names(doc):
    obs = doc.get("observe")
    if not isinstance(obs, list):
        return {}
    return {
        o["name"]: o
        for o in obs
        if isinstance(o, dict) and isinstance(o.get("name"), str)
    }


def _act(lint, doc, whos, names):
    act = doc.get("act")
    if act is None:
        return
    if not isinstance(act, list):
        lint.err("decree.act", "schema", "must be a list")
        return
    bridge_on = (
        isinstance(doc.get("world"), dict) and doc["world"].get("bridge") == "on"
    )
    for i, step in enumerate(act):
        path = f"decree.act[{i}]"
        if not lint.keys(path, step, ("at", "when", "roster", "command"), ()):
            continue
        if ("at" in step) == ("when" in step):
            lint.err(path, "schema", "needs exactly one of at or when")
        if "at" in step and (duration_seconds(step["at"]) is None):
            lint.err(f"{path}.at", "schema", "must be like 0s or 5m")
        if "when" in step and step["when"] not in names:
            lint.err(f"{path}.when", "schema", "must name an observation in observe")
        if ("roster" in step) == ("command" in step):
            lint.err(path, "schema", "needs exactly one of roster or command")
        if "roster" in step:
            r = step["roster"]
            if lint.keys(f"{path}.roster", r, ("who", "job"), ("who", "job")):
                _act_who(lint, f"{path}.roster.who", r["who"], whos)
                if not isinstance(r["job"], str) or not re.match(
                    r"^[a-z ]+(:[a-z0-9_-]+)?$", r["job"]
                ):
                    lint.err(
                        f"{path}.roster.job",
                        "schema",
                        "must be a job such as quest or dungeon:blackrockdepths",
                    )
            if bridge_on:
                lint.err(f"{path}.roster", "bridge",
                         "with the bridge on it owns overseer_roster; order the job with a command of kind job")  # fmt: skip
        if "command" in step:
            c = step["command"]
            if lint.keys(
                f"{path}.command", c, ("who", "kind", "text"), ("who", "kind", "text")
            ):
                _act_who(lint, f"{path}.command.who", c["who"], whos)
                if str(c["kind"]).lower() == "gm":
                    lint.err(
                        f"{path}.command.kind",
                        "gm",
                        "kind gm is rejected: bot sessions are SEC_PLAYER and it silently does nothing",
                    )
                elif c["kind"] not in gamedata.COMMAND_KINDS:
                    lint.err(
                        f"{path}.command.kind",
                        "schema",
                        f"unknown command kind; known: {gamedata.COMMAND_KINDS}",
                    )
                if not isinstance(c["text"], str) or not c["text"]:
                    lint.err(f"{path}.command.text", "schema", "must be non-empty text")
    _walk_auction(lint, doc, "act", act)


def _act_who(lint, path, who, whos):
    m = _CAST_REF.match(who) if isinstance(who, str) else None
    if m:
        if int(m.group(1)) >= len(whos):
            lint.err(path, "schema", "cast index out of range")
    elif not _who_ok(who):
        lint.err(path, "schema", "must be a cast member, cast[N], or a who form")


def _walk_auction(lint, doc, path, node):
    if doc.get("family") == AH_FAMILY:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "kind" and v == "auction":
                continue  # a real bot's own auction verb, not seeding
            if isinstance(k, str) and _AUCTION_WORD.search(k):
                _auction(lint, doc, f"decree.{path}.{k}")
            _walk_auction(lint, doc, f"{path}.{k}", v)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_auction(lint, doc, f"{path}[{i}]", v)
    elif isinstance(node, str) and re.search(r"auctionhouse", node, re.I):
        _auction(lint, doc, f"decree.{path}")


_EXPECT_SCALAR = re.compile(r"^(=|!=|<>|<=|>=|<|>) -?\d+(\.\d+)?$")
_EXPECT_ROWS = re.compile(r"^(>=|<=|>|<|=)?\s*\d+$")


def _observe(lint, doc, whos, aliases):
    obs = doc.get("observe")
    if not isinstance(obs, list):
        if obs is not None:
            lint.err("decree.observe", "schema", "must be a list")
        return
    roles = []
    seen = set()
    cast_names = {w for w in whos if _NAME.match(w)}
    n = len(whos)

    def known_var(name):
        if name in ("t0", "cast", "money_start", "seed_skill_value", "seed_skill_max"):
            return True
        m = re.match(r"^cast(\d+)$", name)
        if m:
            return int(m.group(1)) < n
        if name.startswith("skill_"):
            return name[6:] in {s.lower().replace(" ", "_") for s in gamedata.SKILLS}
        return name in aliases or name in cast_names

    for i, o in enumerate(obs):
        path = f"decree.observe[{i}]"
        if not lint.keys(
            path, o, ("name", "role", "sql", "log", "expect", "when"), ("name", "role")
        ):
            continue
        name = o.get("name")
        if not isinstance(name, str) or not _KEBAB.match(name):
            lint.err(f"{path}.name", "schema", "must be kebab-case")
        elif name in seen:
            lint.err(f"{path}.name", "schema", "duplicate observation name")
        seen.add(name)
        role = o.get("role")
        if role not in ("precondition", "check"):
            lint.err(f"{path}.role", "schema", "must be precondition or check")
        roles.append(role)
        if ("sql" in o) == ("log" in o):
            lint.err(path, "schema", "needs exactly one of sql or log")
        if "sql" in o:
            _observe_sql(lint, path, o, known_var)
        if "log" in o:
            lg = o["log"]
            if role != "check":
                lint.err(
                    f"{path}.log",
                    "schema",
                    "a log assertion is a check, not a precondition",
                )
            if lint.keys(
                f"{path}.log", lg, ("pattern", "expect"), ("pattern", "expect")
            ):
                try:
                    re.compile(lg["pattern"])
                except (re.error, TypeError) as exc:
                    lint.err(f"{path}.log.pattern", "schema", f"bad regex: {exc}")
                ex = lg["expect"]
                if not (
                    isinstance(ex, dict)
                    and set(ex) == {"count"}
                    and _is_int(ex["count"])
                    and ex["count"] >= 0
                ):
                    lint.err(f"{path}.log.expect", "schema", "must be {count: <n>}")
            if "when" in o:
                lint.err(f"{path}.when", "schema", "a log assertion has no when")
    if "precondition" not in roles:
        lint.err(
            "decree.observe",
            "preconditions",
            "needs at least one precondition (a vacuous pass must be impossible)",
        )
    if "check" not in roles:
        lint.err("decree.observe", "preconditions", "needs at least one check")


def _observe_sql(lint, path, o, known_var):
    sql = o["sql"]
    if not isinstance(sql, str):
        lint.err(f"{path}.sql", "schema", "must be a string")
        return
    if o.get("when") not in ("start", "end", "continuous"):
        lint.err(f"{path}.when", "schema", "must be start, end or continuous")
    ex = o.get("expect")
    if not isinstance(ex, dict) or len(ex) != 1:
        lint.err(
            f"{path}.expect",
            "schema",
            "must be {rows: <n or >=n>} or {scalar: '<op> <n>'}",
        )
    else:
        k, v = next(iter(ex.items()))
        if k == "rows" and not (
            _is_int(v) or (isinstance(v, str) and _EXPECT_ROWS.match(v))
        ):
            lint.err(f"{path}.expect.rows", "schema", "must be a count or '>=1'")
        elif k == "scalar" and not (isinstance(v, str) and _EXPECT_SCALAR.match(v)):
            lint.err(
                f"{path}.expect.scalar", "schema", "must be '<op> <n>' such as '>= 1'"
            )
        elif k not in ("rows", "scalar"):
            lint.err(f"{path}.expect", "schema", "must use rows or scalar")
    for problem in dbschema.check_select(sql, lint.schema, known_var):
        lint.err(f"{path}.sql", "sql", problem)
    if _COORD_SQL.search(sql):
        lint.err(
            f"{path}.sql",
            "coordinates",
            "compares a coordinate column to a literal number",
        )


def _cross_rules(lint, doc):
    fix = doc.get("fix") if isinstance(doc.get("fix"), dict) else {}
    world = doc.get("world") if isinstance(doc.get("world"), dict) else {}
    repo = str(fix.get("repo", ""))
    if repo.endswith("/wow-overseer") and world.get("bridge") != "on":
        lint.err(
            "decree.world.bridge",
            "bridge",
            "a fix in wow-overseer lives in bridge code the world must run: bridge must be on",
        )


def _scan_coordinates(lint, doc):
    def walk(path, node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and _COORD_KEY.match(k):
                    lint.err(
                        f"{path}.{k}",
                        "coordinates",
                        "literal coordinates are not allowed; name an anchor",
                    )
                walk(f"{path}.{k}", v)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(f"{path}[{i}]", v)

    for part in ("cast", "arrange", "act"):
        walk(f"decree.{part}", doc.get(part))


def has_errors(findings):
    return any(f.level == "error" for f in findings)

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
    "decree", "id", "family", "proves", "box", "fix", "world", "runs", "duration",
    "cast", "arrange", "act", "observe",
}  # fmt: skip
REQUIRED_TOP = (
    "decree",
    "id",
    "proves",
    "fix",
    "world",
    "runs",
    "duration",
    "cast",
    "observe",
)
SET_KEYS = {
    "level", "alive", "health_pct", "money", "skills", "spells_add", "spells_remove",
    "items", "quests", "homebind", "at", "at_each", "corpse_at", "free_backpack_slots",
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
_EXPECT_SCALAR = re.compile(r"^(=|!=|<>|<=|>=|<|>) -?\d+(\.\d+)?$")
_EXPECT_ROWS = re.compile(r"^(>=|<=|>|<|=)?\s*\d+$")
_JOB = re.compile(r"^[a-z ]+(:[a-z0-9_-]+)?$")
_ALIAS = re.compile(r"^[a-z][a-z0-9_]*$")


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

    def ensure(self, cond, path, rule, msg):
        """Record an error unless `cond` holds."""
        if not cond:
            self.err(path, rule, msg)
        return bool(cond)

    def keys(self, path, obj, allowed, required=()):
        """True only when `obj` is a mapping holding every required key.

        Unknown and missing keys are recorded as findings. A caller indexes the
        required keys after a True, so a mapping that lacks one returns False.
        """
        if not isinstance(obj, dict):
            self.err(path, "schema", "must be a mapping")
            return False
        for k in sorted(set(obj) - set(allowed), key=str):
            self.err(f"{path}.{k}", "schema", "unknown key")
        missing = [k for k in required if k not in obj]
        for k in missing:
            self.err(f"{path}.{k}", "schema", "required")
        return not missing


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _has(container, v):
    """`v in container`, false (not a crash) for an unhashable junk value."""
    try:
        return v in container
    except TypeError:
        return False


def _is_repo(v):
    return isinstance(v, str) and bool(_REPO.match(v))


def lint_document(doc, anchors=None, schema=None):
    """Lint a parsed decree. Returns a list of Finding."""
    lint = _Lint(
        anchors if anchors is not None else anchors_mod.Anchors.load(),
        schema if schema is not None else dbschema.Schema.load(),
    )
    if not lint.keys("decree", doc, TOP_KEYS, REQUIRED_TOP):
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


# -- header: id, proves, fix, world, runs, duration ---------------------------


def _header(lint, doc):
    _header_id(lint, doc)
    _header_proves(lint, doc)
    _header_fix(lint, doc)
    _header_world(lint, doc)
    _header_runs(lint, doc)
    secs = duration_seconds(doc.get("duration"))
    lint.ensure(
        secs is not None and 60 <= secs <= 4 * 3600,
        "decree.duration",
        "schema",
        "must be like 20m or 1h, between 1m and 4h",
    )


def _header_id(lint, doc):
    lint.ensure(
        doc.get("decree") == "v1", "decree.decree", "schema", "must be the literal v1"
    )
    ident = doc.get("id")
    lint.ensure(
        isinstance(ident, str) and bool(_KEBAB.match(ident)) and len(ident) <= 64,
        "decree.id",
        "schema",
        "must be kebab-case, at most 64 characters",
    )
    fam = doc.get("family", "x")
    lint.ensure(
        isinstance(fam, str) and bool(_KEBAB.match(fam)),
        "decree.family",
        "schema",
        "must be a kebab-case word",
    )


def _todo_or(lint, path, value, ok, what):
    if value == "TODO":
        lint.warn(path, "todo", "placeholder still to be filled in")
    elif not ok(value):
        lint.err(path, "schema", f"must be {what}")


def _header_proves(lint, doc):
    proves = doc.get("proves")
    if _is_int(proves):
        lint.ensure(
            proves > 0,
            "decree.proves",
            "schema",
            "must be a positive issue number",
        )
        box = doc.get("box")
        lint.ensure(
            isinstance(box, str) and bool(box.strip()),
            "decree.box",
            "schema",
            "is required with numeric proves and must name one checkbox",
        )
        return
    if not isinstance(proves, list) or not proves:
        lint.err("decree.proves", "schema", "must be a non-empty list")
        return
    if "box" in doc:
        lint.err("decree.box", "schema", "requires numeric proves")
    fields = ("repo", "issue", "criterion")
    for i, p in enumerate(proves):
        path = f"decree.proves[{i}]"
        if not lint.keys(path, p, fields, fields):
            continue
        lint.ensure(
            _is_repo(p.get("repo")), f"{path}.repo", "schema", "must be owner/name"
        )
        _todo_or(
            lint,
            f"{path}.issue",
            p.get("issue"),
            lambda v: _is_int(v) and v > 0,
            "a positive integer",
        )
        lint.ensure(
            isinstance(p.get("criterion"), str) and bool(p["criterion"].strip()),
            f"{path}.criterion",
            "schema",
            "must be the live-check box text",
        )


def _header_fix(lint, doc):
    fix = doc.get("fix")
    if not lint.keys("decree.fix", fix, ("repo", "commit"), ("repo", "commit")):
        return
    lint.ensure(
        _is_repo(fix.get("repo")), "decree.fix.repo", "schema", "must be owner/name"
    )
    _todo_or(
        lint,
        "decree.fix.commit",
        fix.get("commit"),
        lambda v: isinstance(v, str) and bool(_SHA.match(v)),
        "a hex commit sha",
    )


def _image_ok(img):
    if img == "follow-dev":
        return True
    return (
        isinstance(img, dict)
        and set(img) == {"pr"}
        and isinstance(img["pr"], str)
        and bool(_PR.match(img["pr"]))
    )


def _header_world(lint, doc):
    world = doc.get("world")
    keys = ("class", "image", "bridge", "random_bots", "config")
    if not lint.keys("decree.world", world, keys, ("class", "image", "bridge")):
        return
    lint.ensure(
        world.get("class") in ("lean", "full"),
        "decree.world.class",
        "schema",
        "must be lean or full",
    )
    lint.ensure(
        _image_ok(world.get("image")),
        "decree.world.image",
        "schema",
        "must be follow-dev or {pr: <repo>#<n>}",
    )
    lint.ensure(
        world.get("bridge") in ("on", "off"),
        "decree.world.bridge",
        "schema",
        "must be the string on or off (quote it: bare on and off may read as booleans)",
    )
    rb = world.get("random_bots", 0)
    lint.ensure(
        _is_int(rb) and 0 <= rb <= 2600,
        "decree.world.random_bots",
        "schema",
        "must be an integer from 0 to 2600",
    )
    _world_config(lint, doc, world.get("config") or {})


def _world_config(lint, doc, cfg):
    if not isinstance(cfg, dict):
        lint.err("decree.world.config", "schema", "must be a mapping")
        return
    for k, v in cfg.items():
        p = f"decree.world.config.{k}"
        if not _CONFIG_KEY.match(str(k)):
            lint.err(p, "schema", "not a config key name")
        elif k in gamedata.BASELINE_CONFIG_KEYS:
            lint.err(
                p, "config", "owned by the world baseline; a decree may not set it"
            )
        elif k.startswith("AuctionHouseBot.") and doc.get("family") != AH_FAMILY:
            lint.err(
                p,
                "auction",
                "the auction house bot stays off outside an auction-house decree",
            )
        lint.ensure(not isinstance(v, (dict, list)), p, "schema", "must be a scalar")


def _header_runs(lint, doc):
    runs = doc.get("runs")
    if not lint.keys(
        "decree.runs", runs, ("control", "treatment"), ("control", "treatment")
    ):
        return
    for k in ("control", "treatment"):
        lint.ensure(
            _is_int(runs.get(k)) and 1 <= runs[k] <= 9,
            f"decree.runs.{k}",
            "schema",
            "must be an integer from 1 to 9",
        )


# -- cast ----------------------------------------------------------------------


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
        if _who_ok(who):
            whos.append(who)
            _guild_role(lint, f"{path}.who", who)
        else:
            lint.err(
                f"{path}.who",
                "schema",
                "must be a character name, family:<name> or guild:<Guild>:<role>",
            )
        s = entry.get("set")
        if lint.keys(f"{path}.set", s, SET_KEYS):
            _cast_set(lint, path, entry, s)
    _scattered_with(lint, cast)
    return whos


def _scattered_with(lint, cast):
    """Refuse a `with` anchor that names a family placed by at_each.

    Such a family has one position per member, not one of its own, so there is
    no single spot for `with` to mean.
    """
    scattered = {
        e["who"]: i
        for i, e in enumerate(cast)
        if isinstance(e, dict)
        and isinstance(e.get("who"), str)
        and isinstance(e.get("set"), dict)
        and "at_each" in e["set"]
    }
    for i, entry in enumerate(cast):
        s = entry.get("set") if isinstance(entry, dict) else None
        if not isinstance(s, dict):
            continue
        for key in ("at", "homebind", "corpse_at"):
            a = s.get(key)
            if isinstance(a, dict) and len(a) == 1 and a.get("with") in scattered:
                lint.err(
                    f"decree.cast[{i}].set.{key}",
                    "scatter",
                    f"with: {a['with']!r} names the family placed by at_each in "
                    f"decree.cast[{scattered[a['with']]}]; its members have separate "
                    "positions, so there is no single anchor to follow",
                )


def _guild_role(lint, path, who):
    if who.startswith("guild:"):
        lint.ensure(
            who.rsplit(":", 1)[1] in gamedata.ROLE_SKILLS,
            path,
            "schema",
            f"unknown guild role; known: {sorted(gamedata.ROLE_SKILLS)}",
        )


def _cast_set(lint, path, entry, s):
    sp = f"{path}.set"
    _set_scalars(lint, sp, s)
    _set_skills(lint, sp, s.get("skills"))
    for key in ("spells_add", "spells_remove"):
        ok = key not in s or (
            isinstance(s[key], list) and all(_is_int(x) and x > 0 for x in s[key])
        )
        lint.ensure(ok, f"{sp}.{key}", "schema", "must be a list of spell ids")
    _set_items(lint, sp, s.get("items"))
    lint.ensure(
        "free_backpack_slots" not in s
        or (_is_int(s["free_backpack_slots"]) and 1 <= s["free_backpack_slots"] <= 16),
        f"{sp}.free_backpack_slots",
        "schema",
        "must be an integer from 1 to 16",
    )
    _set_quests(lint, sp, s.get("quests"))
    _set_places(lint, sp, s, entry.get("who"))
    _set_ceiling(lint, path, entry, s)


def _set_scalars(lint, sp, s):
    checks = (
        (
            "level",
            lambda v: _is_int(v) and 1 <= v <= 80,
            "must be an integer from 1 to 80",
        ),
        ("alive", lambda v: isinstance(v, bool), "must be true or false"),
        (
            "health_pct",
            lambda v: _is_int(v) and 1 <= v <= 100,
            "must be an integer from 1 to 100",
        ),
        (
            "money",
            lambda v: _is_int(v) and 0 <= v <= 4_000_000_000,
            "must be copper, 0 to 4000000000",
        ),
    )
    for key, ok, msg in checks:
        if key in s:
            lint.ensure(ok(s[key]), f"{sp}.{key}", "schema", msg)


def _skill_ok(v):
    if isinstance(v, dict):
        if not set(v) <= {"value", "max"}:
            return False
        value, mx = v.get("value"), v.get("max", v.get("value"))
    else:
        value = mx = v
    return _is_int(value) and _is_int(mx) and 1 <= value <= mx <= 450


def _set_skills(lint, sp, skills):
    if skills is None:
        return
    if not isinstance(skills, dict):
        lint.err(f"{sp}.skills", "schema", "must be a mapping")
        return
    for name, v in skills.items():
        p = f"{sp}.skills.{name}"
        lint.ensure(
            name in gamedata.SKILLS,
            p,
            "schema",
            f"unknown skill; known: {sorted(gamedata.SKILLS)}",
        )
        lint.ensure(
            _skill_ok(v), p, "schema", "needs integers with 1 <= value <= max <= 450"
        )


def _set_items(lint, sp, items):
    if items is None:
        return
    if not isinstance(items, list):
        lint.err(f"{sp}.items", "schema", "must be a list")
        return
    for j, it in enumerate(items):
        p = f"{sp}.items[{j}]"
        if not lint.keys(p, it, ("name", "count"), ("name",)):
            continue
        lint.ensure(
            isinstance(it["name"], str) and bool(it["name"]),
            f"{p}.name",
            "schema",
            "must be an item name (names, not entry ids)",
        )
        count = it.get("count", 1)
        lint.ensure(
            _is_int(count) and 1 <= count <= 1000,
            f"{p}.count",
            "schema",
            "must be an integer from 1 to 1000",
        )


def _set_quests(lint, sp, quests):
    if quests is None:
        return
    if not isinstance(quests, dict):
        lint.err(f"{sp}.quests", "schema", "must be a mapping of quest to state")
        return
    for k, v in quests.items():
        lint.ensure(
            v in ("incomplete", "complete", "rewarded"),
            f"{sp}.quests.{k}",
            "schema",
            "state must be incomplete, complete or rewarded",
        )


def _set_places(lint, sp, s, who):
    for key in ("at", "homebind", "corpse_at"):
        if key in s:
            _anchor(
                lint,
                f"{sp}.{key}",
                s[key],
                nearest=(key == "at"),
                has_corpse="corpse_at" in s,
            )
    if "at_each" in s:
        anchors = s["at_each"]
        lint.ensure(
            isinstance(who, str) and bool(_FAMILY.match(who)),
            f"{sp}.at_each",
            "scatter",
            "at_each is only valid for a family selector",
        )
        lint.ensure(
            "at" not in s,
            f"{sp}.at_each",
            "scatter",
            "at_each cannot be combined with at",
        )
        if not isinstance(anchors, list):
            lint.err(
                f"{sp}.at_each", "scatter", "must be a list of at least two anchors"
            )
        else:
            lint.ensure(
                len(anchors) >= 2,
                f"{sp}.at_each",
                "scatter",
                "needs at least two anchors",
            )
            seen = []
            for i, anchor in enumerate(anchors):
                path = f"{sp}.at_each[{i}]"
                _anchor(
                    lint,
                    path,
                    anchor,
                    allowed_kinds=("creature", "gameobject", "areatrigger"),
                )
                if isinstance(anchor, dict) and len(anchor) == 1:
                    if any(anchor == previous for previous in seen):
                        lint.err(path, "scatter", "anchor reference is repeated")
                    else:
                        seen.append(anchor)
    lint.ensure(
        s.get("alive") is not False or "corpse_at" in s,
        f"{sp}.alive",
        "schema",
        "a dead character needs corpse_at",
    )
    lint.ensure(
        "corpse_at" not in s or s.get("alive") is False,
        f"{sp}.corpse_at",
        "schema",
        "corpse_at only applies with alive: false",
    )


def _set_ceiling(lint, path, entry, s):
    grants = [k for k in GRANT_KEYS if k in s]
    ceiling = entry.get("ceiling")
    has_text = isinstance(ceiling, str) and bool(ceiling.strip())
    if ("level" in s or grants) and not has_text:
        lint.err(
            f"{path}.ceiling",
            "ceiling",
            "required whenever set grants anything (level, money, skills, spells, items)",
        )
    if not has_text:
        return
    cp = f"{path}.ceiling"
    if grants and re.search(r"nothing granted(?! but)", ceiling, re.I):
        lint.err(cp, "ceiling", f"says nothing is granted but set grants {grants}")
    if grants and re.search(r"nothing granted but position", ceiling, re.I):
        lint.err(cp, "ceiling", f"allows only position but set grants {grants}")
    m = _CEILING_RANGE.search(ceiling)
    level = s.get("level")
    if m and _is_int(level) and not int(m.group(1)) <= level <= int(m.group(2)):
        lint.err(
            f"{path}.set.level",
            "ceiling",
            f"level {level} is outside the stated ceiling {m.group(1)} to {m.group(2)}",
        )


# -- anchors ---------------------------------------------------------------------


def _anchor(lint, path, val, nearest=False, has_corpse=False, allowed_kinds=None):
    kinds = ANCHOR_KINDS if allowed_kinds is None else allowed_kinds
    if not isinstance(val, dict) or len(val) != 1 or next(iter(val)) not in kinds:
        lint.err(
            path,
            "coordinates",
            "must be one anchor: " + ", ".join(kinds) + " (no literal coordinates)",
        )
        return
    kind, v = next(iter(val.items()))
    if kind in ("creature", "gameobject", "with"):
        _anchor_name(lint, path, kind, v)
    elif kind == "areatrigger":
        lint.ensure(
            _is_int(v) and v > 0, path, "schema", "areatrigger anchor needs an id"
        )
    elif kind == "graveyard":
        _anchor_graveyard(lint, path, v, nearest, has_corpse)
    else:
        _anchor_captured(lint, path, v)


def _anchor_name(lint, path, kind, v):
    if not isinstance(v, str) or not v.strip():
        lint.err(path, "schema", f"{kind} anchor needs a name")
    elif v.startswith("<"):
        lint.warn(path, "todo", f"{kind} name is a placeholder still to be filled in")


def _anchor_graveyard(lint, path, v, nearest, has_corpse):
    if v == "nearest":
        lint.ensure(
            nearest and has_corpse,
            path,
            "schema",
            "graveyard: nearest is only for `at` beside a corpse_at",
        )
    else:
        lint.ensure(
            _is_int(v) and v > 0,
            path,
            "schema",
            "graveyard anchor needs an id or nearest",
        )


def _anchor_captured(lint, path, v):
    if not isinstance(v, str) or not lint.anchors.has(v):
        lint.err(path, "anchor", f"captured anchor {v!r} is not in anchors.yaml")
    elif lint.anchors.is_pending(v):
        lint.warn(
            path,
            "anchor",
            f"captured anchor {v!r} is pending: its position is not captured yet",
        )


# -- arrange ---------------------------------------------------------------------


def _arrange(lint, doc, whos):
    aliases = set()
    raid_seats_seen = False
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
                path,
                "schema",
                "must be a one-key mapping: instance, group, creature or raid_seats",
            )
            continue
        kind, v = next(iter(entry.items()))
        if _AUCTION_WORD.search(str(kind)):
            _auction(lint, doc, f"{path}.{kind}")
        elif kind == "instance":
            _arrange_instance(lint, f"{path}.instance", v, whos, aliases)
        elif kind == "group":
            _arrange_group(lint, f"{path}.group", v, whos)
        elif kind == "creature":
            _arrange_creature(lint, f"{path}.creature", v, aliases)
        elif kind == "raid_seats":
            seat_path = f"{path}.raid_seats"
            lint.ensure(
                not raid_seats_seen, seat_path, "schema", "may appear only once"
            )
            raid_seats_seen = True
            _arrange_raid_seats(lint, seat_path, v, whos)
        else:
            lint.err(path, "schema", f"unknown arrange kind {kind!r}")
    return aliases


def _arrange_raid_seats(lint, path, v, whos):
    fields = ("family", "keyword", "seats")
    if not lint.keys(path, v, fields, fields):
        return
    family, keyword, seats = (v[k] for k in fields)
    lint.ensure(
        isinstance(family, str) and _NAME.fullmatch(family),
        f"{path}.family",
        "schema",
        "must be a family name",
    )
    lint.ensure(
        isinstance(keyword, str) and len(keyword) <= 20 and _ALIAS.fullmatch(keyword),
        f"{path}.keyword",
        "schema",
        "must be a lowercase raid keyword of at most 20 characters",
    )
    if not isinstance(seats, list) or not seats:
        lint.err(f"{path}.seats", "schema", "must be a nonempty list")
        return
    seen = set()
    for i, seat in enumerate(seats):
        seat_path = f"{path}.seats[{i}]"
        if lint.keys(seat_path, seat, ("who", "role"), ("who", "role")):
            who = seat["who"]
            if isinstance(who, str) and who in whos:
                lint.ensure(
                    who not in seen,
                    f"{seat_path}.who",
                    "schema",
                    "duplicate seat selector",
                )
                seen.add(who)
            else:
                lint.err(f"{seat_path}.who", "schema", "must name a cast entry")
            lint.ensure(
                seat["role"] in ("tank", "healer", "dps"),
                f"{seat_path}.role",
                "schema",
                "must be tank, healer or dps",
            )


def _arrange_instance(lint, path, v, whos, aliases):
    if not lint.keys(path, v, ("map", "as", "bind"), ("map", "as")):
        return
    lint.ensure(
        _has(gamedata.INSTANCE_MAPS, v["map"]),
        f"{path}.map",
        "schema",
        f"unknown instance map; known: {sorted(gamedata.INSTANCE_MAPS)}",
    )
    alias = v["as"]
    if isinstance(alias, str) and _ALIAS.match(alias):
        lint.ensure(
            alias not in aliases,
            f"{path}.as",
            "schema",
            f"duplicate instance alias {alias!r}",
        )
        aliases.add(alias)
    else:
        lint.err(
            f"{path}.as",
            "schema",
            "alias must be lowercase letters, digits, underscore",
        )
    lint.ensure(
        "bind" not in v or v["bind"] in whos,
        f"{path}.bind",
        "schema",
        "must name a cast member",
    )


def _arrange_group(lint, path, v, whos):
    if not lint.keys(path, v, ("members", "leader"), ("members", "leader")):
        return
    lint.ensure(
        v["members"] in whos, f"{path}.members", "schema", "must name a cast member"
    )
    lint.ensure(
        bool(_NAME.match(str(v["leader"]))),
        f"{path}.leader",
        "schema",
        "must be a character name",
    )


def _arrange_creature(lint, path, v, aliases):
    if not lint.keys(path, v, ("name", "in", "state"), ("name", "in", "state")):
        return
    lint.ensure(
        isinstance(v["name"], str) and bool(v["name"]),
        f"{path}.name",
        "schema",
        "names, not entry ids",
    )
    lint.ensure(
        v["state"] == "dead", f"{path}.state", "schema", "only dead is supported"
    )
    lint.ensure(
        _has(aliases, v["in"]),
        f"{path}.in",
        "schema",
        "must name an earlier instance alias",
    )


def _auction(lint, doc, path):
    if doc.get("family") != AH_FAMILY:
        lint.err(
            path,
            "auction",
            "auction rows may be seeded only when family is auction-house",
        )


# -- act -----------------------------------------------------------------------


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
        if lint.keys(path, step, ("at", "when", "roster", "command"), ()):
            _act_step(lint, path, step, whos, names, bridge_on)
    _walk_auction(lint, doc, "act", act)


def _act_step(lint, path, step, whos, names, bridge_on):
    lint.ensure(
        ("at" in step) != ("when" in step),
        path,
        "schema",
        "needs exactly one of at or when",
    )
    if "at" in step:
        lint.ensure(
            duration_seconds(step["at"]) is not None,
            f"{path}.at",
            "schema",
            "must be like 0s or 5m",
        )
    if "when" in step:
        lint.ensure(
            _has(names, step["when"]),
            f"{path}.when",
            "schema",
            "must name an observation in observe",
        )
    lint.ensure(
        ("roster" in step) != ("command" in step),
        path,
        "schema",
        "needs exactly one of roster or command",
    )
    if "roster" in step:
        _act_roster(lint, f"{path}.roster", step["roster"], whos)
    if "command" in step:
        _act_command(lint, f"{path}.command", step["command"], whos)


def _act_roster(lint, path, r, whos):
    if lint.keys(path, r, ("who", "job"), ("who", "job")):
        _act_who(lint, f"{path}.who", r["who"], whos)
        lint.ensure(
            isinstance(r["job"], str) and bool(_JOB.match(r["job"])),
            f"{path}.job",
            "schema",
            "must be a job such as quest or dungeon:blackrockdepths",
        )


def _act_command(lint, path, c, whos):
    if not lint.keys(path, c, ("who", "kind", "text"), ("who", "kind", "text")):
        return
    _act_who(lint, f"{path}.who", c["who"], whos)
    if str(c["kind"]).lower() == "gm":
        lint.err(
            f"{path}.kind",
            "gm",
            "kind gm is rejected: bot sessions are SEC_PLAYER and it silently does nothing",
        )
    else:
        lint.ensure(
            c["kind"] in gamedata.COMMAND_KINDS,
            f"{path}.kind",
            "schema",
            f"unknown command kind; known: {gamedata.COMMAND_KINDS}",
        )
    lint.ensure(
        isinstance(c["text"], str) and bool(c["text"]),
        f"{path}.text",
        "schema",
        "must be non-empty text",
    )


def _act_who(lint, path, who, whos):
    m = _CAST_REF.match(who) if isinstance(who, str) else None
    if m:
        lint.ensure(
            int(m.group(1)) < len(whos), path, "schema", "cast index out of range"
        )
    else:
        lint.ensure(
            _who_ok(who),
            path,
            "schema",
            "must be a cast member, cast[N], or a who form",
        )


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


# -- observe -----------------------------------------------------------------------


def _known_var_fn(whos, aliases):
    cast_names = {w for w in whos if _NAME.match(w)}
    skills = {s.lower().replace(" ", "_") for s in gamedata.SKILLS}
    fixed = ("t0", "cast", "money_start", "seed_skill_value", "seed_skill_max")

    def known_var(name):
        if name in fixed:
            return True
        m = re.match(r"^cast(\d+)$", name)
        if m:
            return int(m.group(1)) < len(whos)
        if name.startswith("skill_"):
            return name[6:] in skills
        return name in aliases or name in cast_names

    return known_var


def _observe(lint, doc, whos, aliases):
    obs = doc.get("observe")
    if not isinstance(obs, list):
        lint.ensure(obs is None, "decree.observe", "schema", "must be a list")
        return
    known_var = _known_var_fn(whos, aliases)
    roles = []
    seen = set()
    for i, o in enumerate(obs):
        path = f"decree.observe[{i}]"
        if lint.keys(
            path,
            o,
            ("name", "role", "sql", "log", "expect", "when", "online", "encounter"),
            ("name", "role"),
        ):
            roles.append(o.get("role"))
            _observe_one(lint, path, o, seen, known_var, doc)
    lint.ensure(
        "precondition" in roles,
        "decree.observe",
        "preconditions",
        "needs at least one precondition (a vacuous pass must be impossible)",
    )
    lint.ensure(
        "check" in roles, "decree.observe", "preconditions", "needs at least one check"
    )


def _observe_one(lint, path, o, seen, known_var, doc):
    name = o.get("name")
    if not isinstance(name, str) or not _KEBAB.match(name):
        lint.err(f"{path}.name", "schema", "must be kebab-case")
    elif name in seen:
        lint.err(f"{path}.name", "schema", "duplicate observation name")
    if isinstance(name, str):
        seen.add(name)
    lint.ensure(
        o.get("role") in ("precondition", "check"),
        f"{path}.role",
        "schema",
        "must be precondition or check",
    )
    if "encounter" in o:
        lint.ensure(
            encounter_instance(doc, o) is not None,
            f"{path}.encounter",
            "schema",
            "requires an end precondition for a supported boss in the only arranged, cast-bound instance of its map",
        )
        return
    if "online" in o:
        _observe_online(lint, path, o)
        return
    lint.ensure(
        ("sql" in o) != ("log" in o), path, "schema", "needs exactly one of sql or log"
    )
    if "sql" in o:
        _observe_sql(lint, path, o, known_var)
    if "log" in o:
        _observe_log(lint, path, o)


def _encounter_selector(observation):
    """Read a supported end precondition's instance alias and boss map."""
    encounter = observation.get("encounter")
    if (
        not isinstance(encounter, dict)
        or set(encounter) != {"boss", "instance"}
        or not isinstance(encounter["boss"], str)
        or encounter["boss"] not in gamedata.INSTANCE_ENCOUNTERS
        or not isinstance(encounter["instance"], str)
        or observation.get("role") != "precondition"
        or observation.get("when") != "end"
        or {"sql", "log", "online", "expect"} & observation.keys()
    ):
        return None
    map_name, _ = gamedata.INSTANCE_ENCOUNTERS[encounter["boss"]]
    return encounter["instance"], map_name


def encounter_instance(doc, observation):
    """The alias and map ID of the one cast-bound save this selector can read."""
    selector = _encounter_selector(observation)
    if selector is None:
        return None
    alias, map_name = selector
    arrange, cast = doc.get("arrange"), doc.get("cast")
    if not isinstance(arrange, list) or not isinstance(cast, list):
        return None
    instances = [
        e["instance"] for e in arrange if isinstance(e, dict) and "instance" in e
    ]
    if len(instances) != 1 or not isinstance(instances[0], dict):
        return None
    instance = instances[0]
    bound = instance.get("bind")
    if (
        instance.get("as") == alias
        and instance.get("map") == map_name
        and isinstance(bound, str)
        and any(isinstance(e, dict) and e.get("who") == bound for e in cast)
    ):
        return alias, gamedata.INSTANCE_MAPS[map_name]
    return None


def _observe_online(lint, path, o):
    lint.ensure(
        o.get("online") == "cast",
        f"{path}.online",
        "online",
        "must be cast",
    )
    lint.ensure(
        o.get("role") == "precondition" and o.get("when") == "start",
        f"{path}.online",
        "online",
        "cast online is a start precondition",
    )
    lint.ensure(
        not any(key in o for key in ("sql", "log", "expect")),
        f"{path}.online",
        "online",
        "cannot be combined with sql, log or expect",
    )


def _observe_log(lint, path, o):
    lg = o["log"]
    scenario = o.get("role") == "precondition"
    if scenario:
        lint.ensure(
            o.get("when") == "end",
            f"{path}.when",
            "schema",
            "a log precondition requires when: end",
        )
    else:
        lint.ensure(
            "when" not in o, f"{path}.when", "schema", "a log check has no when"
        )
    lint.ensure(
        "expect" not in o,
        f"{path}.expect",
        "schema",
        "put a log expectation inside log.expect",
    )
    if not lint.keys(f"{path}.log", lg, ("pattern", "expect"), ("pattern", "expect")):
        return
    pattern = lg["pattern"]
    if not isinstance(pattern, str):
        lint.err(f"{path}.log.pattern", "schema", "must be a regex string")
    else:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            lint.err(f"{path}.log.pattern", "schema", f"bad regex: {exc}")
        else:
            if scenario and (not pattern.strip() or regex.search("") is not None):
                lint.err(
                    f"{path}.log.pattern",
                    "schema",
                    "a log witness must match nonempty evidence",
                )
    problem = log_bound_problem(lg["expect"])
    if problem:
        lint.err(f"{path}.log.expect", "schema", problem)
    elif scenario and log_bound_range(lg["expect"])[0] == 0:
        lint.err(
            f"{path}.log.expect",
            "schema",
            "a log precondition must require at least one match",
        )


LOG_EXACT_KEYS = ("count", "exactly")
LOG_RANGE_KEYS = ("at_least", "at_most")
LOG_BOUND_FORM = (
    "must be {count: <n>}, {exactly: <n>}, {at_least: <n>}, {at_most: <n>} "
    "or {at_least: <n>, at_most: <m>}"
)


def log_bound_problem(ex):
    """Why a log assertion's `expect` is not a bound, or None when it is one.

    `count` and `exactly` both mean an exact number of matching lines and stand
    alone. `at_least` requires a line, `at_most` caps one, and the two together
    are a range. Every bound is a whole number, zero or more.
    """
    if not isinstance(ex, dict) or not ex:
        return LOG_BOUND_FORM
    unknown = sorted(str(k) for k in ex if k not in LOG_EXACT_KEYS + LOG_RANGE_KEYS)
    if unknown:
        return f"unknown bound {', '.join(unknown)}: {LOG_BOUND_FORM}"
    for key, value in ex.items():
        if not _is_int(value) or value < 0:
            return f"{key} must be a whole number, zero or more"
    if len(ex) > 1 and any(k in ex for k in LOG_EXACT_KEYS):
        return "count and exactly stand alone: " + LOG_BOUND_FORM
    if ex.get("at_least") == 0:
        return "at_least: 0 always holds, so it checks nothing"
    if "at_least" in ex and "at_most" in ex and ex["at_least"] > ex["at_most"]:
        return "at_least is above at_most, so the check can never hold"
    return None


def log_bound_range(ex):
    """(fewest, most) matching lines a linted log bound allows; most is None for no cap."""
    for key in LOG_EXACT_KEYS:
        if key in ex:
            return ex[key], ex[key]
    return ex.get("at_least", 0), ex.get("at_most")


def _expect_ok(ex):
    if not isinstance(ex, dict) or len(ex) != 1:
        return False
    k, v = next(iter(ex.items()))
    if k == "rows":
        return _is_int(v) or (isinstance(v, str) and bool(_EXPECT_ROWS.match(v)))
    if k == "scalar":
        return isinstance(v, str) and bool(_EXPECT_SCALAR.match(v))
    return False


def _observe_sql(lint, path, o, known_var):
    sql = o["sql"]
    if not isinstance(sql, str):
        lint.err(f"{path}.sql", "schema", "must be a string")
        return
    lint.ensure(
        o.get("when") in ("start", "end", "continuous"),
        f"{path}.when",
        "schema",
        "must be start, end or continuous",
    )
    lint.ensure(
        _expect_ok(o.get("expect")),
        f"{path}.expect",
        "schema",
        "must be {rows: <n or '>=n'>} or {scalar: '<op> <n>'}",
    )
    for problem in dbschema.check_select(sql, lint.schema, known_var):
        lint.err(f"{path}.sql", "sql", problem)
    lint.ensure(
        not _COORD_SQL.search(sql),
        f"{path}.sql",
        "coordinates",
        "compares a coordinate column to a literal number",
    )


# -- whole-decree rules -----------------------------------------------------------


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

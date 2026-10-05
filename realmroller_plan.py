"""The realm roller's act side, the pure half: what to write, never the writing.

#590 phase 2. `realmroller.tick` decides the one next step; this module turns
that step into data: the build's inputs, the digests a build log names, the
files of the ONE deploy-repo commit a roll makes, the files of the commit that
reverts it, the verdict on a PR, and the release-state moves the roller keeps
between ticks. It reads no network, cluster or git; `realmroller_act.py` does
that and hands the texts in.

DEPLOYMENT VALUES COME FROM THE CHANNEL FILE'S `act` BLOCK, never from this
source: which workflow builds a component, which image repositories its push
lines name, which deploy-repo lines a roll moves (as regex edits), which
submodule pointers move, where the throwaway prove pod runs and which logs
the verify step reads. `parse_act` checks that block.

THE STATUS. Between ticks the roller keeps a small JSON status (a ConfigMap
in the cluster): `out_since` for the settle gate, and the releases it has
moved since the deploy repo last recorded them (building, built, proven, live,
verified). A status copy of a release is used only while its history extends
the deploy repo's copy, so a person's edit to a release file always wins. The
deploy repo changes only in a roll, a rollback or a pause commit, and each of
those commits carries the states the status held.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import realmroller as rr

# The GitHub Actions log prefix: an RFC 3339 time, then one space.
_LOG_TIME = re.compile(r"^\S+Z ")
_PAIR_LINE = re.compile(r"refers to repository|digest: sha256")
_REFERS = re.compile(r"The push refers to repository \[([^\]]+)\]")
_PUSHED = re.compile(r"^(\S+): digest: (sha256:[0-9a-f]{64}) size: \d+$")
_PLACE = re.compile(r"\{(source|image):([A-Za-z0-9_.-]+)\}|\{(release|run)\}")
_PIN_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_K8S_NAME = re.compile(r"[^a-z0-9-]+")

# A check run in one of these failed; anything not completed is pending.
_FAILED = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
_PASSED = {"success", "neutral", "skipped"}


class PairingError(ValueError):
    """A build log whose digests cannot be tied to their images. Never guessed."""


class PlanError(ValueError):
    """A commit the roller must not write: the deploy repo is not where the release says."""


# --- the act block of the channel file ---------------------------------------


@dataclass(frozen=True)
class Build:
    """How one component is built: a dispatched workflow and the images it pushes."""

    workflow: str
    ref: str
    pin_keys: dict[str, str]  # source name -> the workflow's pin key
    image_repos: dict[str, str]  # image name -> the repository its push names
    tag_pattern: str


@dataclass(frozen=True)
class Edit:
    """One regex edit a roll makes to a deploy-repo file.

    `{source:NAME}`, `{image:NAME}`, `{release}` and `{run}` in `pattern`
    stand for the CURRENT release's values (escaped); in `replace`, for the
    rolling release's. `count` is the exact number of matches required: any
    other number means the file is not where the current release says, and the
    roll is refused. The edit applies only when `if_source` changed or
    `if_component` is touched (one of the two is required).
    """

    path: str
    pattern: str
    replace: str
    count: int
    if_source: str
    if_component: str


@dataclass(frozen=True)
class Gitlink:
    path: str
    source: str


@dataclass(frozen=True)
class Watch:
    """Where a component runs: its Deployment and the container that runs `image`."""

    namespace: str
    deployment: str
    container: str
    image: str
    selector: str


@dataclass(frozen=True)
class LogSource:
    namespace: str
    selector: str
    container: str


@dataclass(frozen=True)
class Act:
    base: str
    branch_prefix: str
    required_checks: tuple[str, ...]
    builds: dict[str, Build]  # component -> build
    prove_namespace: str
    prove_within: timedelta
    binaries: dict[str, str]  # image -> the file a prove grep reads
    watch: dict[str, Watch]  # component -> where it runs
    logs: dict[str, LogSource]  # log name -> pods and container
    edits: tuple[Edit, ...]
    gitlinks: tuple[Gitlink, ...]


def _str(d: dict, key: str, problems: list[str], where: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or not value:
        problems.append("%s%s must be a non-empty string" % (where, key))
        return ""
    return value


def _str_map(d: dict, key: str, problems: list[str], where: str) -> dict[str, str]:
    value = d.get(key)
    if (
        not isinstance(value, dict)
        or not value
        or not all(isinstance(v, str) and v for v in value.values())
    ):
        problems.append("%s%s must be an object of non-empty strings" % (where, key))
        return {}
    return dict(value)


def parse_act(data: object, channel: rr.Channel) -> Act:
    """The channel file's `act` block, checked against the channel. Raises rr.Invalid."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise rr.Invalid("act", ["the channel file has no act block"])
    sources = set(channel.sources)
    components = {c.name: c for c in channel.components}
    images = {i for c in channel.components for i in c.images}
    base = _str(data, "base", problems, "act.")
    prefix = _str(data, "branch_prefix", problems, "act.")
    if prefix and not prefix.endswith("/"):
        problems.append("act.branch_prefix must end with /")
    checks = data.get("required_checks")
    if not isinstance(checks, list) or not all(isinstance(c, str) for c in checks):
        problems.append("act.required_checks must be a list of check names")
        checks = []
    builds = _parse_builds(data.get("builds"), components, sources, problems)
    raw_prove = data.get("prove")
    prove: dict = raw_prove if isinstance(raw_prove, dict) else {}
    if not prove:
        problems.append("act.prove must be an object")
    prove_namespace = _str(prove, "namespace", problems, "act.prove.")
    binaries = _str_map(prove, "binaries", problems, "act.prove.")
    problems.extend(
        "act.prove.binaries.%s is not an image of any component" % i
        for i in binaries
        if i not in images
    )
    try:
        within = rr.duration(prove.get("within"))
    except ValueError as exc:
        problems.append("act.prove.within: %s" % exc)
        within = timedelta(0)
    watch = _parse_watch(data.get("watch"), components, problems)
    logs = _parse_logs(data.get("logs"), problems)
    edits = _parse_edits(data.get("edits"), sources, components, problems)
    gitlinks = _parse_gitlinks(data.get("gitlinks", []), sources, problems)
    if problems:
        raise rr.Invalid("act", problems)
    return Act(
        base=base,
        branch_prefix=prefix,
        required_checks=tuple(checks),
        builds=builds,
        prove_namespace=prove_namespace,
        prove_within=within,
        binaries=binaries,
        watch=watch,
        logs=logs,
        edits=edits,
        gitlinks=gitlinks,
    )


def _parse_builds(raw, components, sources, problems) -> dict[str, Build]:
    if not isinstance(raw, dict) or not raw:
        problems.append("act.builds must name at least one component")
        return {}
    out = {}
    for comp, spec in raw.items():
        where = "act.builds.%s." % comp
        if comp not in components:
            problems.append("%s is not a component" % where[:-1])
            continue
        if not isinstance(spec, dict):
            problems.append("%s must be an object" % where[:-1])
            continue
        keys = _str_map(spec, "pin_keys", problems, where)
        missing = [s for s in components[comp].sources if s not in keys]
        if missing:
            problems.append("%spin_keys lacks %s" % (where, ", ".join(missing)))
        problems.extend(
            "%spin_keys.%s is not a source of %s" % (where, s, comp)
            for s in keys
            if s not in components[comp].sources
        )
        problems.extend(
            "%spin_keys.%s must be an UPPER_CASE key" % (where, s)
            for s, k in keys.items()
            if not _PIN_KEY.match(k)
        )
        repos = _str_map(spec, "image_repos", problems, where)
        if repos and set(repos) != set(components[comp].images):
            problems.append(
                "%simage_repos must name exactly %s"
                % (where, ", ".join(components[comp].images))
            )
        tag = _str(spec, "tag_pattern", problems, where)
        if tag:
            try:
                re.compile(tag)
            except re.error as exc:
                problems.append("%stag_pattern: %s" % (where, exc))
        out[comp] = Build(
            workflow=_str(spec, "workflow", problems, where),
            ref=_str(spec, "ref", problems, where),
            pin_keys=keys,
            image_repos=repos,
            tag_pattern=tag,
        )
    return out


def _parse_watch(raw, components, problems) -> dict[str, Watch]:
    if not isinstance(raw, dict):
        problems.append("act.watch must be an object")
        return {}
    out = {}
    for comp, spec in raw.items():
        where = "act.watch.%s." % comp
        if comp not in components or not isinstance(spec, dict):
            problems.append("%s must be an object for a component" % where[:-1])
            continue
        image = _str(spec, "image", problems, where)
        if image and image not in components[comp].images:
            problems.append("%simage %s is not an image of %s" % (where, image, comp))
        out[comp] = Watch(
            namespace=_str(spec, "namespace", problems, where),
            deployment=_str(spec, "deployment", problems, where),
            container=_str(spec, "container", problems, where),
            image=image,
            selector=_str(spec, "selector", problems, where),
        )
    missing = [c for c in components if c not in out]
    if missing:
        problems.append("act.watch lacks %s" % ", ".join(missing))
    return out


def _parse_logs(raw, problems) -> dict[str, LogSource]:
    if not isinstance(raw, dict) or not raw:
        problems.append("act.logs must name at least one log")
        return {}
    out = {}
    for name, spec in raw.items():
        where = "act.logs.%s." % name
        if not isinstance(spec, dict):
            problems.append("%s must be an object" % where[:-1])
            continue
        out[name] = LogSource(
            namespace=_str(spec, "namespace", problems, where),
            selector=_str(spec, "selector", problems, where),
            container=_str(spec, "container", problems, where),
        )
    return out


def _parse_edits(raw, sources, components, problems) -> tuple[Edit, ...]:
    if not isinstance(raw, list):
        problems.append("act.edits must be a list")
        return ()
    out = []
    for n, e in enumerate(raw):
        where = "act.edits[%d]." % n
        if not isinstance(e, dict):
            problems.append("%s must be an object" % where[:-1])
            continue
        if_source = e.get("if_source", "")
        if_component = e.get("if_component", "")
        if bool(if_source) == bool(if_component):
            problems.append("%s needs exactly one of if_source or if_component" % where)
        if if_source and if_source not in sources:
            problems.append("%sif_source %s is not a source" % (where, if_source))
        if if_component and if_component not in components:
            problems.append(
                "%sif_component %s is not a component" % (where, if_component)
            )
        pattern = _str(e, "pattern", problems, where)
        replace = e.get("replace")
        if not isinstance(replace, str):
            problems.append("%sreplace must be a string" % where)
            replace = ""
        for text in (pattern, replace):
            for m in _PLACE.finditer(text):
                if m.group(1) == "source" and m.group(2) not in sources:
                    problems.append(
                        "%s{source:%s} is not a source" % (where, m.group(2))
                    )
        try:
            re.compile(_fill(pattern, _probe_values(pattern), escape=True))
        except re.error as exc:
            problems.append("%spattern: %s" % (where, exc))
        count = e.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            problems.append("%scount must be a positive integer" % where)
            count = 1
        out.append(
            Edit(
                path=_str(e, "path", problems, where),
                pattern=pattern,
                replace=replace,
                count=count,
                if_source=if_source or "",
                if_component=if_component or "",
            )
        )
    return tuple(out)


def _probe_values(text: str) -> dict[str, str]:
    """Stand-in values, so a pattern's regex can be compiled at parse time."""
    return {_key(m): "x" for m in _PLACE.finditer(text)}


def _parse_gitlinks(raw, sources, problems) -> tuple[Gitlink, ...]:
    if not isinstance(raw, list):
        problems.append("act.gitlinks must be a list")
        return ()
    out = []
    for n, g in enumerate(raw):
        where = "act.gitlinks[%d]." % n
        if not isinstance(g, dict):
            problems.append("%s must be an object" % where[:-1])
            continue
        source = _str(g, "source", problems, where)
        if source and source not in sources:
            problems.append("%ssource %s is not a source" % (where, source))
        out.append(Gitlink(_str(g, "path", problems, where), source))
    return tuple(out)


def check_logs(act: Act, releases: dict[str, rr.Release]) -> None:
    """Every verify check names a log the act block knows how to read."""
    problems = [
        "%s: %s check reads log %s, which act.logs does not name"
        % (rel.name, c.pr, c.verify.log)
        for rel in releases.values()
        for c in rel.changes
        if c.verify and c.verify.log not in act.logs
    ]
    if problems:
        raise rr.Invalid("act", problems)


# --- release state between ticks ---------------------------------------------


def advance(raw: dict, to: str, at: datetime, note: str, **build) -> dict:
    """A copy of a release file's JSON moved to `to`, with the event appended.

    `build` may set `run` and `images` in the release's build block. Refuses a
    move the state machine does not allow.
    """
    here = str(raw.get("state"))
    if to not in rr.NEXT.get(here, ()):
        raise PlanError("%s cannot move %s -> %s" % (raw.get("release"), here, to))
    out = copy.deepcopy(raw)
    out["state"] = to
    block = out.setdefault("build", {})
    if "run" in build:
        block["run"] = build["run"]
    if "images" in build:
        block["images"] = dict(build["images"])
    out.setdefault("history", []).append(
        {"at": at.isoformat(), "to": to, "by": "roller", "note": note}
    )
    return out


def _events(raw: dict) -> list[tuple]:
    return [(e.get("to"), e.get("at")) for e in raw.get("history", [])]


def overlay(main: dict[str, dict], held: dict[str, dict]) -> tuple[dict, list[str]]:
    """The release files the tick reads: the deploy repo's, moved on by the status.

    A status copy is used only when the deploy repo's history is a strict
    prefix of it: the roller moved the release on and has not committed that
    yet. Anything else (a person edited the file, or a commit already carries
    the moves) drops the status copy, and the deploy repo wins. Returns the
    files and the names whose status copy was dropped.
    """
    out = dict(main)
    dropped = []
    for name, raw in held.items():
        base = main.get(name)
        ours, theirs = _events(raw), _events(base) if base else None
        if (
            theirs is not None
            and len(ours) > len(theirs)
            and ours[: len(theirs)] == theirs
        ):
            out[name] = raw
        else:
            dropped.append(name)
    return out, dropped


def parse_set(
    channel_raw: dict, release_raws: dict[str, dict]
) -> tuple[rr.Channel, dict[str, rr.Release]]:
    """The channel and release JSON, parsed and checked as one set."""
    channel = rr.parse_channel(channel_raw)
    releases = {}
    for name, raw in release_raws.items():
        rel = rr.parse_release(raw, channel)
        if rel.name != name:
            raise rr.Invalid("releases/%s.json" % name, ["holds release %s" % rel.name])
        releases[name] = rel
    rr.check_set(channel, releases)
    return channel, releases


def dumps(data: dict) -> str:
    """How the roller writes a JSON file: two-space indent, key order kept, newline."""
    return json.dumps(data, indent=2) + "\n"


# --- the build ----------------------------------------------------------------


def build_inputs(build: Build, release: rr.Release) -> dict[str, str]:
    """The dispatch inputs: the release name and every pin, KEY=SHA, space-separated."""
    pins = " ".join(
        "%s=%s" % (build.pin_keys[s], release.sources[s])
        for s in sorted(build.pin_keys)
    )
    return {"release": release.name, "pins": pins}


def build_log_lacks(log_text: str, build: Build, release: rr.Release) -> list[str]:
    """The sources whose SHA the build log never names: the pins did not take."""
    return [
        s for s in sorted(build.pin_keys) if release.sources[s][:12] not in log_text
    ]


def read_digests(log_text: str, build: Build) -> dict[str, str]:
    """{image: digest} from one build's log, paired by repository, never by position.

    THE SAFE WAY, as the hand roll does it: keep only the "The push refers to
    repository [R]" and "TAG: digest: sha256:D size: N" lines, then take each
    digest line as belonging to the refers line directly before it. Everything
    else in the log (buildx's own sha256 lines, layer pushes) is dropped first,
    so it cannot sit between a repository and its digest.

    Refused, never guessed: a digest line with no refers line before it, a
    refers line with no digest after it, two different digests for one image
    (its build tag and :latest must agree), no push under the build's tag, or
    images pushed under different tags (not one build pair).
    """
    lines = [_LOG_TIME.sub("", raw).strip() for raw in log_text.splitlines()]
    lines = [ln for ln in lines if _PAIR_LINE.search(ln)]
    pushes: list[tuple[str, str, str]] = []  # (repository, tag, digest)
    problems = []
    repo = None
    for ln in lines:
        m = _REFERS.search(ln)
        if m:
            if repo is not None:
                problems.append("push to %s has no digest line" % repo)
            repo = m.group(1)
            continue
        m = _PUSHED.match(ln)
        if not m:
            continue  # "digest: sha256" inside some other line: not a push result
        if repo is None:
            problems.append("digest line with no repository before it: %s" % ln)
            continue
        pushes.append((repo, m.group(1), m.group(2)))
        repo = None
    if repo is not None:
        problems.append("push to %s has no digest line" % repo)
    out, tags = {}, {}
    for image, want in sorted(build.image_repos.items()):
        mine = [(t, d) for r, t, d in pushes if r == want]
        tagged = [(t, d) for t, d in mine if re.fullmatch(build.tag_pattern, t)]
        digests = {d for _, d in mine}
        if not tagged:
            problems.append("no push of %s under a build tag" % want)
        elif len(digests) != 1:
            problems.append(
                "%s pushed with %d different digests" % (want, len(digests))
            )
        else:
            out[image] = tagged[0][1]
            tags[image] = tagged[0][0]
    if len(set(tags.values())) > 1:
        problems.append(
            "images pushed under different tags: %s"
            % ", ".join("%s=%s" % kv for kv in sorted(tags.items()))
        )
    if problems:
        raise PairingError("; ".join(problems))
    return out


# --- the prove pod --------------------------------------------------------------


def k8s_name(*parts: str) -> str:
    """A DNS-1123 name from parts: lowercase, dashes, at most 63 characters."""
    name = _K8S_NAME.sub("-", "-".join(parts).lower()).strip("-")
    return name[:63].rstrip("-")


# grep -c prints 0 and exits 1 when nothing matches, so the count is captured
# and printed whatever grep's status. A missing or unreadable binary prints
# `count=` with no number, which reads as inconclusive, never as a pass.
PROVE_SCRIPT = (
    'bin="$1"; shift; for t in "$@"; do '
    'n=$(grep -a -c -F -e "$t" "$bin" 2>/dev/null); echo "count=$n"; done'
)


def prove_greps(release: rr.Release) -> dict[str, list[str]]:
    """{image: [grep, ...]} over the release's changes, in change order."""
    out: dict[str, list[str]] = {}
    for c in release.changes:
        if c.prove:
            out.setdefault(c.prove[0], []).append(c.prove[1])
    return out


def prove_pod(act: Act, release: rr.Release, image: str, repo: str) -> dict:
    """The throwaway pod that greps the built binary: no token, no secrets, read-only."""
    greps = prove_greps(release)[image]
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": k8s_name("prove", release.name, image),
            "namespace": act.prove_namespace,
            "labels": {"app": "realm-roller-prove"},
        },
        "spec": {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            "activeDeadlineSeconds": int(act.prove_within.total_seconds()),
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 65534,
                "runAsGroup": 65534,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "prove",
                    "image": "%s@%s" % (repo, release.images[image]),
                    "command": ["sh", "-c", PROVE_SCRIPT, "prove", act.binaries[image]]
                    + greps,
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "resources": {
                        "requests": {"cpu": "50m", "memory": "64Mi"},
                        "limits": {"memory": "256Mi"},
                    },
                }
            ],
        },
    }


def prove_counts(log_text: str, want: int) -> list[int] | None:
    """The per-grep counts a prove pod printed, or None when it is not `want` numbers."""
    counts = []
    for ln in log_text.splitlines():
        if ln.startswith("count="):
            value = ln[len("count=") :].strip()
            if not value.isdigit():
                return None
            counts.append(int(value))
    return counts if len(counts) == want else None


# --- the roll commit ----------------------------------------------------------


def _key(m: re.Match) -> str:
    return "%s:%s" % (m.group(1), m.group(2)) if m.group(1) else m.group(3)


def values(release: rr.Release) -> dict[str, str]:
    """A release's placeholder values: every source and image, its name and build run."""
    out = {"source:%s" % k: v for k, v in release.sources.items()}
    out.update({"image:%s" % k: v for k, v in release.images.items()})
    out["release"] = release.name
    out["run"] = str(release.run)
    return out


def _fill(text: str, vals: dict[str, str], escape: bool) -> str:
    def one(m: re.Match) -> str:
        key = _key(m)
        if key not in vals:
            raise PlanError("no value for {%s}" % key)
        return re.escape(vals[key]) if escape else vals[key]

    return _PLACE.sub(one, text)


def applies(edit: Edit, changed: set[str], touched: set[str]) -> bool:
    return edit.if_source in changed if edit.if_source else edit.if_component in touched


def apply_edits(
    texts: dict[str, str],
    edits: tuple[Edit, ...],
    old: dict[str, str],
    new: dict[str, str],
    changed: set[str],
    touched: set[str],
) -> dict[str, str]:
    """`texts` ({path: content}) with every applicable edit made, in order.

    Raises PlanError listing every edit whose match count is not its `count`:
    a deploy repo that does not hold the current release's values is not one
    the roller may write over.
    """
    out = dict(texts)
    problems = []
    for e in edits:
        if not applies(e, changed, touched):
            continue
        if e.path not in out:
            problems.append("%s: file not read" % e.path)
            continue
        pattern = re.compile(_fill(e.pattern, old, escape=True), re.M)
        replacement = _fill(e.replace, new, escape=False)
        text, n = pattern.subn(lambda m, r=replacement: m.expand(r), out[e.path])
        if n != e.count:
            problems.append(
                "%s: /%s/ matched %d time(s), expected %d"
                % (e.path, e.pattern, n, e.count)
            )
            continue
        out[e.path] = text
    if problems:
        raise PlanError("; ".join(problems))
    return out


@dataclass(frozen=True)
class FoldFile:
    """One file of a queued config PR: its blob at the PR's merge base, on base now, at head.

    None means absent at that point. The fold takes the head blob only when
    the base branch still holds the merge-base blob: nothing else changed the
    file since the PR branched.
    """

    path: str
    at_merge_base: str | None
    on_base: str | None
    at_head: str | None
    gitlink: bool = False


def fold_entries(
    pr: str, files: list[FoldFile], forbidden: tuple[str, ...]
) -> dict[str, str | None]:
    """{path: blob sha or None (delete)} that folds a queued config PR into the roll."""
    problems, out = [], {}
    for f in files:
        if f.gitlink:
            problems.append("%s moves the submodule %s" % (pr, f.path))
        elif any(
            f.path == p or f.path.startswith(p.rstrip("/") + "/") for p in forbidden
        ):
            problems.append("%s touches %s, which the roller owns" % (pr, f.path))
        elif f.on_base != f.at_merge_base:
            problems.append(
                "%s: %s changed on the base branch since it branched" % (pr, f.path)
            )
        else:
            out[f.path] = f.at_head
    if problems:
        raise PlanError("; ".join(problems))
    return out


def roll_roller_files(
    roller_path: str,
    channel_raw: dict,
    raws: dict[str, dict],
    head: str,
    supersedes: tuple[str, ...],
    at: datetime,
) -> dict[str, str]:
    """The roller's own files in a roll commit: the channel and every release it moves."""
    cur = channel_raw["current"]
    files = {}
    files["%s/releases/%s.json" % (roller_path, head)] = dumps(
        advance(raws[head], "rolling", at, "roll commit")
    )
    # The release rolled off carries what the status held (live, verified).
    files["%s/releases/%s.json" % (roller_path, cur)] = dumps(raws[cur])
    for name in supersedes:
        files["%s/releases/%s.json" % (roller_path, name)] = dumps(
            advance(raws[name], "superseded", at, "superseded by %s" % head)
        )
    channel = copy.deepcopy(channel_raw)
    channel["previous"] = cur
    channel["current"] = head
    channel["queue"] = [
        q for q in channel_raw.get("queue", []) if q != head and q not in supersedes
    ]
    files["%s/channel.json" % roller_path] = dumps(channel)
    return files


def rollback_roller_files(
    roller_path: str,
    channel_raw: dict,
    raws: dict[str, dict],
    failed: str,
    target: str,
    why: str,
    at: datetime,
) -> dict[str, str]:
    """The roller's own files in a rollback commit: the failed release, and a paused channel."""
    channel = copy.deepcopy(channel_raw)
    channel["current"] = target
    channel["previous"] = target
    channel["paused"] = True
    channel["paused_reason"] = "rolled back %s at %s: %s" % (
        failed,
        at.strftime("%Y-%m-%dT%H:%MZ"),
        why,
    )
    return {
        "%s/releases/%s.json" % (roller_path, failed): dumps(
            advance(raws[failed], "rolled_back", at, why)
        ),
        "%s/channel.json" % roller_path: dumps(channel),
    }


def pause_files(
    roller_path: str, channel_raw: dict, why: str, at: datetime
) -> dict[str, str]:
    """The channel file, paused, with the reason and the time."""
    channel = copy.deepcopy(channel_raw)
    channel["paused"] = True
    channel["paused_reason"] = "%s (%s)" % (why, at.strftime("%Y-%m-%dT%H:%MZ"))
    return {"%s/channel.json" % roller_path: dumps(channel)}


@dataclass(frozen=True)
class Side:
    """One path in the roll commit's parent, the roll commit, and the base branch now.

    Each is (mode, sha) or None when the path is absent there.
    """

    path: str
    before: tuple[str, str] | None
    rolled: tuple[str, str] | None
    now: tuple[str, str] | None


def revert_entries(
    sides: list[Side], roller_path: str
) -> dict[str, tuple[str, str] | None]:
    """{path: (mode, sha) or None} that undoes the roll commit's deploy changes.

    The roller's own files are left to rollback_roller_files. Refuses when a
    path changed again after the roll: undoing it would also undo that change.
    """
    problems, out = [], {}
    for s in sides:
        if s.path.startswith(roller_path.rstrip("/") + "/"):
            continue
        if s.now != s.rolled:
            problems.append("%s changed after the roll commit" % s.path)
            continue
        out[s.path] = s.before
    if problems:
        raise PlanError("; ".join(problems))
    return out


# --- pull requests ---------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    kind: str  # ready | pending | failed | conflict | closed | merged
    why: str


def pr_verdict(
    pr: dict,
    checks: list[dict],
    statuses: list[dict],
    open_threads: int,
    required: tuple[str, ...],
    threads_block: bool = True,
) -> Verdict:
    """Whether a roller PR may merge now.

    `checks` are check runs ({name, status, conclusion}); `statuses` commit
    statuses ({context, state}); `open_threads` the unresolved review threads.
    Ready only when every check and status passed, every required check is
    among them, and (for a roll) no review thread is open.
    """
    if pr.get("merged"):
        return Verdict("merged", "merged")
    if pr.get("state") != "open":
        return Verdict("closed", "closed without merging")
    if pr.get("mergeable") is False or pr.get("mergeable_state") == "dirty":
        return Verdict("conflict", "conflicts with the base branch")
    failed = sorted(
        {
            c["name"]
            for c in checks
            if c.get("status") == "completed" and c.get("conclusion") in _FAILED
        }
        | {s["context"] for s in statuses if s.get("state") in ("failure", "error")}
    )
    if failed:
        return Verdict("failed", "failing: %s" % ", ".join(failed))
    names = {c["name"] for c in checks} | {s["context"] for s in statuses}
    missing = [r for r in required if r not in names]
    if missing:
        return Verdict("pending", "waiting for %s" % ", ".join(missing))
    running = sorted(
        {
            c["name"]
            for c in checks
            if c.get("status") != "completed" or c.get("conclusion") not in _PASSED
        }
        | {s["context"] for s in statuses if s.get("state") != "success"}
    )
    if running:
        return Verdict("pending", "running: %s" % ", ".join(running))
    if threads_block and open_threads:
        return Verdict("pending", "%d review thread(s) open" % open_threads)
    if pr.get("mergeable") is None:
        return Verdict("pending", "mergeability not computed yet")
    return Verdict("ready", "checks passed")


def roll_body(
    release: rr.Release,
    cur: rr.Release,
    touched: list[str],
    supersedes: tuple[str, ...],
    folds: list[str],
    tracker: str,
) -> str:
    """The roll PR's body, in the shape the review bot's readiness check reads."""
    changes = (
        "\n".join("- %s: %s" % (c.pr, c.what) for c in release.changes)
        or "- (no changes listed)"
    )
    moved = [
        s for s in sorted(release.sources) if release.sources[s] != cur.sources.get(s)
    ]
    sources = (
        "\n".join(
            "- %s `%s` -> `%s`"
            % (s, cur.sources.get(s, "")[:8], release.sources[s][:8])
            for s in moved
        )
        or "- (no source moves)"
    )
    images = "\n".join("- %s `%s`" % (i, d) for i, d in sorted(release.images.items()))
    extra = ""
    if supersedes:
        extra += (
            "\nSupersedes %s (coalesced; only the newest proven release rolls).\n"
            % ", ".join(supersedes)
        )
    if folds:
        extra += (
            "\nFolds the queued config change(s) %s into this restart.\n"
            % ", ".join(folds)
        )
    return (
        "## Why\n\n"
        "Realm roller release `%s` (%s), proposed by %s. Its build was proven "
        "by a throwaway pod grep, and the gates were open when this PR was "
        "written. Roller design: %s.\n\n"
        "## What\n\n"
        "One commit for %s: the source pins, both digests from build run %d, "
        "the runtime banner, deployed_dev and the banner test literal, and the "
        "channel and release files.\n\n%s\n\nImages:\n\n%s\n\nChanges:\n\n%s\n%s\n"
        "## Acceptance\n\n"
        "- CI passes and no review thread is open; the roller merges only while every gate is open.\n"
        "- The restarted component reports Ready within the channel's ready window.\n"
        "- Every verify check passes on live logs; a failure reverts this commit and pauses the channel.\n\n"
        "Size: XS\n\n"
        "## Out of scope\n\n"
        "- Promotion to any other realm.\n"
        "- Releases still queued behind this one.\n"
    ) % (
        release.name,
        release.summary,
        release.proposed_by,
        tracker,
        ", ".join(touched) or "nothing",
        release.run,
        sources,
        images,
        changes,
        extra,
    )


def rollback_body(
    failed: str, target: str, why: str, roll_pr: str, tracker: str
) -> str:
    return (
        "## Why\n\n"
        "Realm roller release `%s` failed on the realm: %s. Roller design: %s.\n\n"
        "## What\n\n"
        "Reverts the deploy changes of %s, so the realm returns to `%s`, records "
        "`%s` as rolled back, and pauses the channel until a person looks.\n\n"
        "## Acceptance\n\n"
        "- Every deploy-repo line the roll moved is back to its value before the roll.\n"
        "- The channel names `%s` as current and is paused with the reason.\n"
        "- CI passes on this PR.\n\n"
        "Size: XS\n\n"
        "## Out of scope\n\n"
        "- Diagnosing the failure.\n"
        "- Unpausing the channel.\n"
    ) % (failed, why, tracker, roll_pr, target, failed, target)


def pause_body(why: str, tracker: str) -> str:
    return (
        "## Why\n\n"
        "The realm roller stopped: %s. Roller design: %s.\n\n"
        "## What\n\n"
        "Sets `paused` in the channel file, with the reason, so nothing rolls "
        "until a person looks.\n\n"
        "## Acceptance\n\n"
        "- The channel file says paused, with the reason and the time.\n"
        "- No other file changes.\n"
        "- CI passes on this PR.\n\n"
        "Size: XS\n\n"
        "## Out of scope\n\n"
        "- Fixing what stopped the roller.\n"
        "- Unpausing the channel.\n"
    ) % (why, tracker)


# --- live logs -----------------------------------------------------------------


def scan(
    lines, checks: list[rr.Check], signatures: tuple[str, ...]
) -> tuple[set[str], str | None]:
    """(labels of checks whose text was seen, the first fatal signature seen or None)."""
    seen: set[str] = set()
    bad = None
    for line in lines:
        for c in checks:
            if c.text in line:
                seen.add(c.label)
        if bad is None:
            for sig in signatures:
                if sig in line:
                    bad = sig
                    break
    return seen, bad

"""`eph due`: open `awaiting-live-check` issues that have a runnable proof.

An issue body names its decree with one line, `Proof: decree <id>`. A ticket is
due when that decree is on the default branch, proves that issue, and nothing
under `<results_dir>/<decree>/` exists yet (no batch record, no result).
Discovery is read-only. `submit --due` preflights the selected proofs before
submitting through the ordinary suspended-Job path.
"""

import base64
import pathlib
import re
from dataclasses import dataclass

from . import ghx, kube, lint, submit
from .miniyaml import YamlError, loads

LABEL_WAITING = "awaiting-live-check"
ACTIVE_STAGES = {"loom:briefed", "loom:running", "loom:pr"}
PROOF_RE = re.compile(
    r"^[ \t]*Proof:[ \t]+decree[ \t]+([a-z0-9][a-z0-9-]*)[ \t]*$", re.M
)


def proof_decree(body):
    """The decree id named by the first Proof line of an issue body, or ''."""
    m = PROOF_RE.search(body or "")
    return m.group(1) if m else ""


def _targets(decree, decree_repo):
    """The valid issue references named in `proves`, in declaration order."""
    proves = (decree or {}).get("proves")
    if type(proves) is int and proves > 0:
        return ((decree_repo.lower(), proves),)
    if not isinstance(proves, list):
        return ()
    targets = {}
    for p in proves:
        if isinstance(p, dict):
            repo, n = p.get("repo", decree_repo), p.get("issue")
            if lint._is_repo(repo) and type(n) is int and n > 0:
                targets[(repo.lower(), n)] = None
    return tuple(targets)


def proves_issue(decree, repo, n, decree_repo=None):
    """True when the decree's `proves` names issue n of repo."""
    return (repo.lower(), n) in _targets(decree, decree_repo or repo)


def has_submission(results_dir, decree_id):
    d = pathlib.Path(results_dir) / decree_id
    return d.is_dir() and any(d.iterdir())


def _load_decree(gh, repo, decree_id):
    """Raw bytes and parsed decree from the default branch, if valid."""
    # The Contents API uses the repository's default branch when ref is absent.
    doc = gh.api(
        f"repos/{repo}/contents/data/decrees/{decree_id}.yaml", missing_ok=True
    )
    if not isinstance(doc, dict) or doc.get("encoding") != "base64":
        return None
    content = doc.get("content")
    if not isinstance(content, str):
        return None
    try:
        raw = base64.b64decode("".join(content.split()), validate=True)
        decree = loads(raw.decode("utf-8"))
    except (YamlError, ValueError):
        return None
    if not isinstance(decree, dict) or decree.get("id") != decree_id:
        return None
    return raw, decree


@dataclass(frozen=True)
class _Proof:
    repo: str
    issue: int
    decree_id: str
    raw: bytes
    targets: tuple[tuple[str, int], ...]


def _waiting_issues(gh, repos):
    out = []
    for repo in repos:
        issues = (
            gh.api(
                f"repos/{repo}/issues?state=open&labels={LABEL_WAITING}"
                "&sort=created&direction=asc&per_page=100",
                paginate=True,
            )
            or []
        )
        out.extend((repo, it) for it in issues if "pull_request" not in it)
    # GitHub uses sortable UTC timestamps. Python's stable sort keeps the
    # list order when equal or missing timestamps need a tie break.
    out.sort(key=lambda item: item[1].get("created_at") or "9999")
    return out


def _discover(gh, cfg, repos):
    decrees = {}
    repos = repos or getattr(cfg, "proof_repos", ()) or (cfg.decree_repo,)
    for repo, it in _waiting_issues(gh, repos):
        did = proof_decree(it.get("body"))
        if not did or has_submission(cfg.results_dir, did):
            continue
        if did not in decrees:
            decrees[did] = _load_decree(gh, cfg.decree_repo, did)
        if decrees[did] is None:
            continue
        raw, decree = decrees[did]
        if proves_issue(decree, repo, it["number"], cfg.decree_repo):
            yield _Proof(
                repo, it["number"], did, raw, _targets(decree, cfg.decree_repo)
            )


def due(gh, cfg, repos=None):
    """[(repo, issue number, decree id)] oldest issue first."""
    return [(p.repo, p.issue, p.decree_id) for p in _discover(gh, cfg, repos)]


def _hold(labels):
    claims = [label for label in labels if label.startswith("claim:")]
    if claims:
        return ", ".join(sorted(claims))
    lanes = [label for label in labels if label.startswith("lane:")]
    if lanes and ACTIVE_STAGES.intersection(labels):
        return ", ".join(sorted(lanes))
    return ""


def _read_target(gh, repo, number):
    row = gh.issue(repo, number)
    if (
        not isinstance(row, dict)
        or row.get("number") != number
        or row.get("state") not in ("open", "closed")
        or "pull_request" in row
    ):
        raise ValueError("invalid issue response")
    labels = row.get("labels")
    if not isinstance(labels, list) or any(
        not isinstance(label, dict) or not isinstance(label.get("name"), str)
        for label in labels
    ):
        raise ValueError("unreadable issue labels")
    return row, {label["name"] for label in labels}


def _target_blocker(gh, proofs):
    """Check all collector targets and confirm an original candidate is still due."""
    eligible = False
    candidate = proofs[0]
    waiting = {(p.repo.lower(), p.issue) for p in proofs}
    for repo, number in candidate.targets:
        target = f"{repo}#{number}"
        try:
            row, names = _read_target(gh, repo, number)
        except (ghx.GhError, ValueError) as exc:
            return f"{target}: could not read the target issue ({exc})"
        if hold := _hold(names):
            return f"{target} ({hold})"
        body = row.get("body")
        if (
            row["state"] == "open"
            and (repo, number) in waiting
            and LABEL_WAITING in names
            and isinstance(body, str)
            and proof_decree(body) == candidate.decree_id
        ):
            eligible = True
    return "" if eligible else "no linked issue is still waiting for this proof"


def submit_due(gh, cfg, cluster, limit, args, out=print):
    """Select up to limit distinct unheld proofs that pass preflight."""
    by_decree = {}
    for proof in _discover(gh, cfg, None):
        by_decree.setdefault(proof.decree_id, []).append(proof)

    options = {**args, "control": "auto"}
    for decree_id, proofs in by_decree.items():
        if limit == 0:
            break
        if blocker := _target_blocker(gh, proofs):
            out(f"skip {decree_id}: {blocker}")
            continue
        path = f"data/decrees/{decree_id}.yaml"
        raw = proofs[0].raw
        try:
            submit.submit(
                cfg, cluster, gh, path, {**options, "dry_run": True}, decree_bytes=raw
            )
        except (submit.SubmitError, kube.KubeError, ghx.GhError) as exc:
            out(f"skip {decree_id}: {exc}")
            continue
        if blocker := _target_blocker(gh, proofs):
            out(f"skip {decree_id}: {blocker}")
            continue
        if has_submission(cfg.results_dir, decree_id):
            out(f"skip {decree_id}: a submission appeared during preflight")
            continue
        if not options.get("dry_run"):
            submit.submit(cfg, cluster, gh, path, options, decree_bytes=raw)
        limit -= 1

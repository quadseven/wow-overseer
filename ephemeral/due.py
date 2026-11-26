"""`eph due`: open `awaiting-live-check` issues that have a runnable proof.

An issue body names its decree with one line, `Proof: decree <id>`. A ticket is
due when that decree is on the default branch, proves that issue, and nothing
under `<results_dir>/<decree>/` exists yet (no batch record, no result).
Read-only: it lists, it never writes to GitHub or the cluster.
"""

import base64
import pathlib
import re

from .miniyaml import YamlError, loads

LABEL_WAITING = "awaiting-live-check"
PROOF_RE = re.compile(r"^[ \t]*Proof:[ \t]+decree[ \t]+([a-z0-9][a-z0-9-]*)[ \t]*$", re.M)


def proof_decree(body):
    """The decree id named by the first Proof line of an issue body, or ''."""
    m = PROOF_RE.search(body or "")
    return m.group(1) if m else ""


def proves_issue(decree, repo, n):
    """True when the decree's `proves` names issue n of repo."""
    proves = (decree or {}).get("proves")
    if isinstance(proves, int) and not isinstance(proves, bool):
        return proves == n
    if not isinstance(proves, list):
        return False
    for p in proves:
        if isinstance(p, dict) and p.get("issue") == n and p.get("repo", repo) == repo:
            return True
    return False


def has_submission(results_dir, decree_id):
    d = pathlib.Path(results_dir) / decree_id
    return d.is_dir() and any(d.iterdir())


def load_decree(gh, repo, decree_id):
    """The decree parsed from the default branch, or None when absent or unreadable."""
    doc = gh.api(f"repos/{repo}/contents/data/decrees/{decree_id}.yaml?ref=main", missing_ok=True)
    if not doc or doc.get("encoding") != "base64":
        return None
    try:
        return loads(base64.b64decode(doc["content"]).decode("utf-8"))
    except (YamlError, ValueError):
        return None


def due(gh, cfg, repos=None):
    """[(repo, issue number, decree id)] oldest issue first."""
    out = []
    for repo in repos or [cfg.decree_repo]:
        issues = gh.api(
            f"repos/{repo}/issues?state=open&labels={LABEL_WAITING}"
            "&sort=created&direction=asc&per_page=100",
            paginate=True,
        ) or []
        for it in issues:
            if "pull_request" in it:
                continue
            did = proof_decree(it.get("body"))
            if not did or has_submission(cfg.results_dir, did):
                continue
            if proves_issue(load_decree(gh, cfg.decree_repo, did), repo, it["number"]):
                out.append((repo, it["number"], did))
    return out

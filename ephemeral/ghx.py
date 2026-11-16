"""GitHub through `gh api`, with an injectable runner and an identity guard.

Every write refuses unless the process carries a non-empty `GH_TOKEN` and an
explicit `GH_CONFIG_DIR`: an empty token makes `gh` fall back to a stored
personal login without a word. After a post, the comment's author is read back
and must be the configured App; anything else raises.
"""

import json

from .kube import subprocess_runner


class GhError(Exception):
    """gh failed, the identity is wrong, or an answer was not what was needed."""


def require_identity(env):
    if not (env.get("GH_TOKEN") or "").strip():
        raise GhError("GH_TOKEN is empty: refusing to write as a personal login")
    if not (env.get("GH_CONFIG_DIR") or "").strip():
        raise GhError("GH_CONFIG_DIR is not set: gh could use a stored personal login")


class Gh:
    def __init__(self, runner=subprocess_runner, env=None, author="", write=True):
        self.runner = runner
        self.env = env if env is not None else {}
        self.author = author
        self.write = write

    def api(self, path, method="GET", body=None, missing_ok=False):
        if method != "GET":
            if not self.write:
                raise GhError("this client is read-only")
            require_identity(self.env)
        argv = ["gh", "api", path]
        if method != "GET":
            argv += ["-X", method]
        if body is not None:
            argv += ["--input", "-"]
        rc, out, err = self.runner(argv, json.dumps(body) if body is not None else None)
        if rc != 0:
            if missing_ok and "404" in err:
                return None
            raise GhError(f"gh api {method} {path} failed: {err.strip()[:200]}")
        return json.loads(out) if out.strip() else None

    # -- reads
    def compare(self, repo, base, head):
        doc = self.api(f"repos/{repo}/compare/{base}...{head}", missing_ok=True)
        return (doc or {}).get("status", "")

    def issue(self, repo, n):
        return self.api(f"repos/{repo}/issues/{n}")

    def comments(self, repo, n):
        return self.api(f"repos/{repo}/issues/{n}/comments?per_page=100") or []

    def label_exists(self, repo, name):
        return self.api(f"repos/{repo}/labels/{name}", missing_ok=True) is not None

    # -- writes
    def comment(self, repo, n, text):
        made = self.api(f"repos/{repo}/issues/{n}/comments", "POST", {"body": text})
        login = ((made or {}).get("user") or {}).get("login", "")
        if self.author and login != self.author:
            raise GhError(
                f"the comment was posted as {login!r}, not {self.author!r}: stop and fix the identity"
            )
        return made

    def edit_body(self, repo, n, body):
        self.api(f"repos/{repo}/issues/{n}", "PATCH", {"body": body})

    def remove_label(self, repo, n, name):
        self.api(f"repos/{repo}/issues/{n}/labels/{name}", "DELETE", missing_ok=True)

    def add_label(self, repo, n, name):
        self.api(f"repos/{repo}/issues/{n}/labels", "POST", {"labels": [name]})

    def close_completed(self, repo, n):
        self.api(
            f"repos/{repo}/issues/{n}",
            "PATCH",
            {"state": "closed", "state_reason": "completed"},
        )

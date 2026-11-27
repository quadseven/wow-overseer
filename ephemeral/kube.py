"""A thin kubectl wrapper with an injectable runner.

Every cluster read and write the runner makes goes through `Kubectl`, so a test
swaps the runner for a fake and sees the exact argv. Nothing here names a host:
the cluster comes from the kubeconfig the operator already uses.
"""

import json
import re
import subprocess

_API_NAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
_DELETE_API = {"configmaps": "/api/v1", "jobs": "/apis/batch/v1"}


class KubeError(Exception):
    """kubectl failed, or answered something that is not JSON."""

    def __init__(self, message, rc=1, stderr=""):
        super().__init__(message)
        self.rc = rc
        self.stderr = stderr


def subprocess_runner(argv, input_text=None):
    """(returncode, stdout, stderr). A missing kubectl is a KubeError, not a crash."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv list, never a shell
            argv,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KubeError(f"could not run {argv[0]}: {exc}") from exc
    return proc.returncode, proc.stdout, proc.stderr


class Kubectl:
    def __init__(self, namespace, runner=subprocess_runner, kubeconfig=None):
        self.namespace = namespace
        self.runner = runner
        self.kubeconfig = kubeconfig

    def _argv(self, *args, namespace=None):
        """namespace None means this client's own; "" means cluster scoped."""
        argv = ["kubectl"]
        if self.kubeconfig:
            argv += ["--kubeconfig", self.kubeconfig]
        ns = self.namespace if namespace is None else namespace
        if ns:
            argv += ["-n", ns]
        return argv + list(args)

    def _run(self, argv, input_text=None, missing_ok=False):
        rc, out, err = self.runner(argv, input_text)
        if rc != 0:
            if missing_ok and "NotFound" in err:
                return None
            raise KubeError(
                f"kubectl {' '.join(argv[1:4])} failed: {err.strip()[:300]}", rc, err
            )
        return out

    @staticmethod
    def _json(text, what):
        try:
            return json.loads(text)
        except (TypeError, ValueError) as exc:
            raise KubeError(f"{what}: kubectl did not answer JSON") from exc

    def get(self, kind, name, namespace=None, missing_ok=False):
        argv = self._argv("get", kind, name, "-o", "json", namespace=namespace)
        out = self._run(argv, missing_ok=missing_ok)
        return None if out is None else self._json(out, f"get {kind}/{name}")

    def list(self, kind, selector=None, namespace=None):
        argv = self._argv("get", kind, "-o", "json", namespace=namespace)
        if selector:
            argv += ["-l", selector]
        doc = self._json(self._run(argv), f"list {kind}")
        return doc.get("items", [])

    def raw(self, path):
        out = self._run(self._argv("get", "--raw", path, namespace=""))
        return self._json(out, f"raw {path}")

    def dry_run_json(self, text):
        """Let kubectl turn manifest text into one JSON object, creating nothing."""
        out = self._run(
            self._argv("create", "--dry-run=client", "-o", "json", "-f", "-"), text
        )
        return self._json(out, "dry-run create")

    def create(self, manifest):
        out = self._run(
            self._argv("create", "-o", "json", "-f", "-"), json.dumps(manifest)
        )
        return self._json(out, "create")

    def replace(self, manifest):
        out = self._run(
            self._argv("replace", "-o", "json", "-f", "-"), json.dumps(manifest)
        )
        return self._json(out, "replace")

    def patch_merge(self, kind, name, patch):
        self._run(
            self._argv("patch", kind, name, "--type=merge", "-p", json.dumps(patch))
        )

    def delete(self, kind, name):
        self._run(
            self._argv("delete", kind, name, "--ignore-not-found=true", "--wait=false")
        )

    def delete_configmap_version(self, cm):
        """Cascade deletion only while the observed ConfigMap UID and version match."""
        self.delete_version("configmaps", cm)

    def delete_version(self, kind, resource):
        """Delete an observed Job or ConfigMap without touching its replacement."""
        if kind not in _DELETE_API:
            raise KubeError(f"conditional deletion is not supported for {kind}")
        meta = resource["metadata"]
        ns, name = meta.get("namespace"), meta.get("name")
        if ns != self.namespace or not all(
            isinstance(value, str) and _API_NAME.fullmatch(value)
            for value in (ns, name)
        ):
            raise KubeError(f"refusing {kind} deletion with an invalid scope or name")
        version = {key: meta.get(key) for key in ("uid", "resourceVersion")}
        if not all(isinstance(value, str) and value for value in version.values()):
            raise KubeError(f"refusing {kind} deletion without its UID and version")
        options = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "preconditions": version,
            "propagationPolicy": "Background",
        }
        url = f"{_DELETE_API[kind]}/namespaces/{ns}/{kind}/{name}"
        self._run(
            self._argv("delete", "--raw", url, "-f", "-", namespace=""),
            json.dumps(options),
            missing_ok=True,
        )

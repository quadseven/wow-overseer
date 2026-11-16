"""Read the commit an image was built from, out of the image's own config.

The bridge image bakes `OVERSEER_COMMIT` (the full commit, from the build). A
bridge-fix decree needs that commit per arm to prove the fix is present in the
treatment image and absent from the control one, without anyone typing a pin.

This asks the image's registry for the manifest by digest, then the config blob,
and reads the Env list. Every body is checked against the digest it was asked
for, so a wrong answer is an error, never a guess. Redirects (the blob store)
are followed without the registry token. The credential is the namespace's own
pull secret and is never printed or stored.
"""

import base64
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

_REF = re.compile(
    r"^(?P<host>[a-z0-9][a-z0-9.-]*(?::\d+)?)/(?P<path>[a-z0-9][a-z0-9._/-]*)"
    r"@(?P<digest>sha256:[a-f0-9]{64})$"
)
_SHA = re.compile(r"^[a-f0-9]{40}$")
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
MAX_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 3


class RegistryError(Exception):
    """The image's commit could not be read."""


def valid_sha(text):
    """The text if it is a full lowercase hex commit, else None."""
    return text if isinstance(text, str) and _SHA.match(text) else None


def parse_ref(ref):
    m = _REF.match(str(ref))
    if not m:
        raise RegistryError("image reference must be host/path@sha256:<64 hex>")
    return m["host"], m["path"], m["digest"]


def credentials(secret, host):
    """(user, password) for the host from a dockerconfigjson Secret object, or None."""
    try:
        raw = base64.b64decode(secret["data"][".dockerconfigjson"])
        entry = json.loads(raw)["auths"][host]
    except (TypeError, KeyError, ValueError):
        return None
    if entry.get("username") and entry.get("password"):
        return entry["username"], entry["password"]
    try:
        user, _, password = base64.b64decode(entry["auth"]).decode().partition(":")
    except (KeyError, ValueError):
        return None
    return (user, password) if user and password else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a, **_k):
        return None


def urlfetch(url, headers):
    """(status, lowercase response headers, body); redirects are returned, not followed."""
    if not url.startswith("https://"):
        raise RegistryError("registry requests must be https")
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=20) as resp:
            return (
                resp.status,
                {k.lower(): v for k, v in resp.headers.items()},
                resp.read(MAX_BYTES + 1),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, b""
    except (urllib.error.URLError, OSError) as exc:
        raise RegistryError(f"registry unreachable: {type(exc).__name__}") from exc


def _get(fetch, url, headers):
    for _ in range(MAX_REDIRECTS + 1):
        status, resp_headers, body = fetch(url, headers)
        if status in (301, 302, 303, 307, 308) and resp_headers.get(
            "location", ""
        ).startswith("https://"):
            url = resp_headers["location"]
            headers = {k: v for k, v in headers.items() if k != "Authorization"}
            continue
        if status != 200:
            raise RegistryError(f"registry answered {status}")
        if len(body) > MAX_BYTES:
            raise RegistryError("registry body too large")
        return body
    raise RegistryError("too many redirects")


def _verified(fetch, url, headers, digest):
    body = _get(fetch, url, headers)
    if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
        raise RegistryError("registry content does not match its digest")
    try:
        return json.loads(body)
    except ValueError as exc:
        raise RegistryError("registry content is not JSON") from exc


def image_env(ref, creds, fetch=None):
    """The image config's Env as a dict. `creds` is (user, password) or None (anonymous)."""
    fetch = fetch or urlfetch
    host, path, digest = parse_ref(ref)
    q = urllib.parse.urlencode(
        {"service": host, "scope": f"repository:{path}:pull"}, safe=":/"
    )
    auth = {}
    if creds:
        auth["Authorization"] = (
            "Basic " + base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode()
        )
    try:
        token = json.loads(_get(fetch, f"https://{host}/token?{q}", auth))["token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RegistryError("registry gave no token") from exc
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT}
    base = f"https://{host}/v2/{path}"
    doc = _verified(fetch, f"{base}/manifests/{digest}", headers, digest)
    if isinstance(doc, dict) and "manifests" in doc:
        pick = next(
            (
                m for m in doc["manifests"]
                if (m.get("platform") or {}).get("os") == "linux"
                and (m.get("platform") or {}).get("architecture") == "amd64"
            ),
            None,
        )  # fmt: skip
        if not pick or not _DIGEST.match(str(pick.get("digest"))):
            raise RegistryError("no linux/amd64 entry in the image index")
        doc = _verified(
            fetch, f"{base}/manifests/{pick['digest']}", headers, pick["digest"]
        )
    try:
        cfg_digest = doc["config"]["digest"]
    except (KeyError, TypeError) as exc:
        raise RegistryError("manifest has no config") from exc
    if not _DIGEST.match(str(cfg_digest)):
        raise RegistryError("manifest config digest is malformed")
    cfg = _verified(fetch, f"{base}/blobs/{cfg_digest}", headers, cfg_digest)
    env = {}
    for item in (cfg.get("config") or {}).get("Env") or []:
        k, _, v = str(item).partition("=")
        env[k] = v
    return env

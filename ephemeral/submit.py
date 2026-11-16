"""`eph submit`: turn a decree into suspended Jobs, one per run.

Nothing here starts a world. A Job is created with `suspend: true`; only
`eph dispatch` unsuspends one. Each run also gets ConfigMap `eph-run-<id>`
holding the decree and the merged config files the pod mounts, owned by its
Job so the Job's TTL removes both.

Refusals (an error, never a quiet downgrade): a decree that does not lint, an
image other than `follow-dev`, a bridge-on decree whose template has no
bridge sidecar (or whose sidecar could reach a secret or the API), a fix that is wrongly present or absent in an arm's image, a
template whose tokens this code does not know.
"""

import hashlib
import json
import pathlib
import re
import time

from . import anchors as anchors_mod
from . import confmerge, dbschema, lint, runids
from .kube import KubeError
from .miniyaml import YamlError, loads

REALM_RANGE = range(100, 200)
BASE_DEADLINE_PAD = 15 * 60
BRIDGE = "bridge"  # the sidecar's container name in the template
BRIDGE_PULL_SECRET = "ghcr"  # the bridge image is a private package
BRIDGE_DEPLOYMENT = "wow-overseer"  # the base realm's bridge, where the live digest is read
BRIDGE_CONTAINER = "overseer"
# What fills {{BRIDGE_IMAGE}} on a bridge-off run, where the container is then removed.
BRIDGE_OFF_IMAGE = "bridge-off.invalid/not-run@sha256:" + "0" * 64
CM_LIMIT_BYTES = 900 * 1024
_TOKEN = re.compile(r"\{\{([A-Z_]+)\}\}")
_DURATION = re.compile(r"^(\d+)([smh])$")
_DIGEST_REF = re.compile(r"^[^\s@]+@sha256:[a-f0-9]{64}$")
_SHA = re.compile(r"^[a-f0-9]{40}$")
_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
BASELINE = {
    "Overseer.RequireClient": 0,
    "Overseer.Raid.RequireHeadClient": 0,
    "OllamaChat.Enable": 0,
}


class SubmitError(Exception):
    """The decree cannot be submitted as written."""


def parse_duration(text):
    m = _DURATION.match(str(text))
    if not m:
        raise SubmitError(f"duration {text!r} is not like 20m")
    return int(m[1]) * {"s": 1, "m": 60, "h": 3600}[m[2]]


# -- reads -------------------------------------------------------------------------


def read_template(kube):
    cm = kube.get("configmaps", runids.TEMPLATE_CM, missing_ok=True)
    if cm is None:
        raise SubmitError(f"ConfigMap {runids.TEMPLATE_CM} is not in the namespace")
    data = cm.get("data") or {}
    for key in ("job.yaml", "classes.json", "tokens.txt"):
        if key not in data:
            raise SubmitError(f"{runids.TEMPLATE_CM} has no {key}")
    try:
        classes = json.loads(data["classes.json"])
    except ValueError as exc:
        raise SubmitError(f"{runids.TEMPLATE_CM} classes.json is not JSON") from exc
    listed = set()
    for line in data["tokens.txt"].splitlines():
        if line.strip() and not line.lstrip().startswith("#") and ":" in line:
            listed.add(line.split(":", 1)[0].strip())
    used = set(_TOKEN.findall(data["job.yaml"]))
    if used != listed:
        raise SubmitError(
            "template tokens and tokens.txt differ: " + ", ".join(sorted(used ^ listed))
        )
    return data["job.yaml"], classes, used


def read_live(cfg, kube):
    """Image refs, module pins and base override files, from the running base realm."""
    dep = kube.get("deployments", cfg.source_deployment, namespace=cfg.source_namespace)
    spec = dep["spec"]["template"]["spec"]
    ws = next(
        (c for c in spec.get("containers", []) if c["name"] == "worldserver"), None
    )
    db = next(
        (c for c in spec.get("initContainers", []) if c["name"] == "db-upgrade"), None
    )
    if not ws or not db:
        raise SubmitError(
            "the base worldserver Deployment has no worldserver or db-upgrade container"
        )
    images = {"worldserver": ws["image"], "dbimport": db["image"]}
    for k, ref in images.items():
        if not _DIGEST_REF.match(ref):
            raise SubmitError(f"the base realm's {k} image is not pinned by digest")
    pins = {
        e["name"]: e.get("value", "")
        for e in ws.get("env", [])
        if e["name"].startswith("OVERSEER_PIN_")
    }
    files = {}
    for vol in spec.get("volumes", []):
        name = vol.get("name", "")
        group = name.removesuffix("-overrides")
        if (
            name.endswith("-overrides")
            and group in confmerge.FILES
            and "configMap" in vol
        ):
            cm = kube.get(
                "configmaps", vol["configMap"]["name"], namespace=cfg.source_namespace
            )
            files[group] = (cm.get("data") or {}).get(confmerge.FILES[group], "")
    return images, pins, files


def read_bridge_image(cfg, kube):
    """The base realm's running bridge image, by digest (the treatment arm's default)."""
    dep = kube.get(
        "deployments", BRIDGE_DEPLOYMENT, namespace=cfg.source_namespace, missing_ok=True
    )
    if dep is None:
        raise SubmitError("the base realm has no bridge Deployment to read the image from")
    spec = dep["spec"]["template"]["spec"]
    c = next((c for c in spec.get("containers", []) if c["name"] == BRIDGE_CONTAINER), None)
    if not c or not _DIGEST_REF.match(c.get("image", "")):
        raise SubmitError("the base realm's bridge image is not pinned by digest")
    return c["image"]


# -- fix presence ------------------------------------------------------------------


def fix_presence(gh, fix, pin):
    """present | absent | unchecked: is the fix an ancestor of the commit the image was built from."""
    commit = str((fix or {}).get("commit", ""))
    if not _SHA.match(commit) or not _SHA.match(str(pin or "")):
        return "unchecked"
    status = gh.compare(fix["repo"], commit, pin)
    if status in ("ahead", "identical"):
        return "present"
    if status in ("behind", "diverged"):
        return "absent"
    return "unchecked"


# -- rendering ---------------------------------------------------------------------


def _images_for(arm, live_images, args, live_bridge=None):
    """Each arm's images. A bridge image is present only when the decree turns the bridge on."""
    if arm == "treatment":
        img = dict(live_images)
        if live_bridge is not None:
            img["bridge"] = args.get("treatment_bridge") or live_bridge
    else:
        if not (args.get("control_worldserver") and args.get("control_dbimport")):
            raise SubmitError(
                "a control arm needs --control-worldserver and --control-dbimport (by digest)"
            )
        img = {
            "worldserver": args["control_worldserver"],
            "dbimport": args["control_dbimport"],
        }
        if live_bridge is not None:
            if not args.get("control_bridge"):
                raise SubmitError(
                    "a control arm with bridge: on needs --control-bridge (the image before the fix, by digest)"
                )
            img["bridge"] = args["control_bridge"]
    for k, ref in img.items():
        if not _DIGEST_REF.match(ref):
            raise SubmitError(f"{arm} {k} image must be name@sha256:<64 hex>")
    return img


def _apply_bridge(job, image):
    """Keep the template's bridge sidecar and its pull secret (image set) or remove both (None)."""
    spec = job.get("spec", {}).get("template", {}).get("spec", {})
    inits = spec.get("initContainers", [])
    mine = [c for c in inits if c.get("name") == BRIDGE]
    if image is None:
        spec["initContainers"] = [c for c in inits if c.get("name") != BRIDGE]
        if "imagePullSecrets" in spec:
            spec["imagePullSecrets"] = [
                p for p in spec["imagePullSecrets"] if p.get("name") != BRIDGE_PULL_SECRET
            ]
        if BRIDGE_OFF_IMAGE in json.dumps(job):
            raise SubmitError("the bridge placeholder image is outside the bridge sidecar")
        return
    if len(mine) != 1:
        raise SubmitError("the world template has no bridge sidecar")
    c = mine[0]
    text = json.dumps(c)
    if (
        c.get("image") != image
        or c.get("restartPolicy") != "Always"
        or "secretKeyRef" in text
        or "serviceaccount" in text
        or "api-token" in text
        or c.get("ports")
    ):
        raise SubmitError(
            "the bridge sidecar must be a native sidecar at the arm's image with no secret, API token or port"
        )


def _render(template, values, used):
    text = template
    for tok in used:
        if tok not in values:
            raise SubmitError(f"no value for template token {tok}")
        text = text.replace("{{" + tok + "}}", str(values[tok]))
    if _TOKEN.search(text):
        raise SubmitError("a template token was left unfilled")
    return text


def _load_decree(decree_path, args):
    raw = pathlib.Path(decree_path).read_bytes()
    try:
        decree = loads(raw.decode("utf-8"))
        anchors_doc = loads(
            pathlib.Path(args.get("anchors") or anchors_mod.DEFAULT_PATH).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, YamlError, UnicodeDecodeError) as exc:
        raise SubmitError(f"decree or anchors unreadable: {exc}") from exc
    anchors = anchors_mod.Anchors((anchors_doc or {}).get("anchors") or {})
    found = lint.lint_document(decree, anchors, dbschema.Schema.load())
    errors = [f for f in found if f.level == "error"]
    if errors:
        raise SubmitError("decree does not lint: " + "; ".join(map(str, errors)))
    return raw, decree


def submit(cfg, kube, gh, decree_path, args=None, clock=time.time, out=print):
    """Create the suspended Jobs. Returns the submission record (also saved)."""
    args = dict(args or {})
    arm_arg = args.get("arm", "both")
    if arm_arg not in ("control", "treatment", "both"):
        raise SubmitError("--arm must be control, treatment or both")
    raw, decree = _load_decree(decree_path, args)
    sha = hashlib.sha256(raw).hexdigest()
    world = decree["world"]
    if world["image"] != "follow-dev":
        raise SubmitError(
            "only image: follow-dev can be submitted yet (PR images are not built)"
        )
    bridge_on = world["bridge"] == "on"
    decree_id = decree["id"]
    if not _LABEL.match(decree_id):
        raise SubmitError("decree id is not a label-safe name")
    klass = world["class"]
    node = _pick_node(cfg, klass, args.get("node"))
    template, classes, used = read_template(kube)
    if klass not in classes:
        raise SubmitError(f"the template has no numbers for class {klass}")
    live_images, pins, base_files = read_live(cfg, kube)
    live_bridge = read_bridge_image(cfg, kube) if bridge_on else None
    files, deltas = _config_for(world, base_files, bridge_on)
    arms = ["control", "treatment"] if arm_arg == "both" else [arm_arg]
    presence = _presence(cfg, gh, decree, arms, args, pins)

    batch = hashlib.sha256(f"{sha}:{clock()}".encode()).hexdigest()[:6]
    duration = parse_duration(decree["duration"])
    plan = [
        (arm, n)
        for n in range(1, max(decree["runs"][a] for a in arms) + 1)
        for arm in arms
        if n <= decree["runs"][arm]
    ]
    free = [r for r in REALM_RANGE if r not in _used_realms(kube)]
    if len(free) < len(plan):
        raise SubmitError("no free realm ids")
    nodecfg = cfg.nodes[node]
    runs, pending = [], []
    for (arm, n), realm in zip(plan, free, strict=False):
        rid = runids.run_id(batch, arm, n)
        img = _images_for(arm, live_images, args, live_bridge)
        values = {
            "RUN_ID": rid, "DECREE_ID": decree_id, "ARM": arm, "CLASS": klass,
            "BATCH": batch, "REALM_ID": realm,
            "DEADLINE_SECONDS": duration + BASE_DEADLINE_PAD,
            "WORLDSERVER_IMAGE": img["worldserver"], "DBIMPORT_IMAGE": img["dbimport"],
            "TOOLS_IMAGE": cfg.tools_image, "TEMPLATE_IMAGE": cfg.template_images[klass],
            "CLIENT_DATA_CLAIM": nodecfg.claim, **classes[klass],
            "BRIDGE_IMAGE": img.get("bridge", BRIDGE_OFF_IMAGE),
        }  # fmt: skip
        job = kube.dry_run_json(_render(template, values, used))
        _apply_bridge(job, img.get("bridge"))
        _check_job(job, rid, nodecfg.claim, cfg.namespace)
        runs.append(
            {
                "run_id": rid,
                "arm": arm,
                "n": n,
                "realm_id": realm,
                "node": node,
                "images": img,
            }
        )
        pending.append((job, rid, arm, realm))
    record = {
        "batch": batch, "decree_id": decree_id, "decree_sha256": sha,
        "decree_path": str(decree_path), "decree_pr": args.get("decree_pr"),
        "submitted_at": int(clock()), "class": klass, "proves": decree["proves"],
        "fix": decree["fix"], "runs_wanted": {a: decree["runs"][a] for a in arms},
        "presence": presence, "fidelity_deltas": deltas, "runs": runs,
    }  # fmt: skip
    if args.get("dry_run"):
        out(
            f"dry run: {len(runs)} runs for {decree_id} in batch {batch}; nothing created"
        )
        return record
    for job, rid, arm, realm in pending:
        _create_run(kube, job, rid, arm, realm, batch, decree_id, raw, files, sha)
        out(f"queued {rid} ({arm}) on {node}")
    save_record(cfg, record)
    return record


def _config_for(world, base_files, bridge_on=False):
    changes = dict(BASELINE)
    bots = int(world.get("random_bots", 0))
    changes["Playerbots.MinRandomBots"] = bots
    changes["Playerbots.MaxRandomBots"] = bots
    changes.update(world.get("config") or {})
    try:
        files, deltas = confmerge.merge(base_files, changes)
    except confmerge.ConfError as exc:
        raise SubmitError(str(exc)) from exc
    deltas += [
        (
            "bridge: on (headless sidecar on the world's loopback, no Discord)"
            if bridge_on
            else "bridge: off (the base realm runs it)"
        ),
        f"random bots: {bots}",
        "clients: none (every character is headless)",
    ]
    return files, deltas


def _presence(cfg, gh, decree, arms, args, pins):
    pin_var = cfg.fix_pin_env.get(decree["fix"]["repo"], "")
    presence = {}
    for arm in arms:
        if arm == "control":
            pin = args.get("control_pin")
        else:
            pin = args.get("treatment_pin") or pins.get(pin_var)
        state = fix_presence(gh, decree["fix"], pin)
        presence[arm] = {"pin": pin or "", "state": state}
        want = "present" if arm == "treatment" else "absent"
        if state not in (want, "unchecked"):
            raise SubmitError(
                f"fix presence is wrong for the {arm} image: expected {want}, found {state}"
            )
    return presence


def _pick_node(cfg, klass, wanted):
    if wanted:
        n = cfg.nodes.get(wanted)
        if n is None:
            raise SubmitError(f"node {wanted!r} is not in the runner config")
        if klass not in n.classes:
            raise SubmitError(f"node {wanted!r} does not take class {klass}")
        return wanted
    for name, n in cfg.nodes.items():
        if klass in n.classes:
            return name
    raise SubmitError(f"no configured node takes class {klass}")


def _used_realms(kube):
    used = set()
    for cm in kube.list("configmaps", selector=runids.JOB_LABEL_REALM):
        try:
            used.add(int(cm["metadata"]["labels"][runids.JOB_LABEL_REALM]))
        except (KeyError, ValueError):
            continue
    return used


def _check_job(job, rid, claim, namespace):
    meta, spec = job.get("metadata", {}), job.get("spec", {})
    if job.get("kind") != "Job" or meta.get("name") != runids.job_name(rid):
        raise SubmitError("the rendered template is not the expected Job")
    if meta.get("namespace") != namespace:
        raise SubmitError("the rendered Job is not in the ephemeral namespace")
    if spec.get("suspend") is not True:
        raise SubmitError("the rendered Job is not suspended: refusing to create it")
    claims = [
        v["persistentVolumeClaim"].get("claimName")
        for v in spec.get("template", {}).get("spec", {}).get("volumes", [])
        if "persistentVolumeClaim" in v
    ]
    if claims != [claim]:
        raise SubmitError(
            "the rendered Job does not use the chosen node's client-data claim"
        )


def _create_run(kube, job, rid, arm, realm, batch, decree_id, raw, files, sha):
    data = {"decree.yaml": raw.decode("utf-8")}
    data.update(
        {confmerge.FILES[g]: t for g, t in files.items() if g in confmerge.FILES}
    )
    if sum(len(v.encode("utf-8")) for v in data.values()) > CM_LIMIT_BYTES:
        raise SubmitError("run inputs are too large for a ConfigMap")
    made = kube.create(job)
    cm = {
        "apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {
            "name": runids.run_cm_name(rid), "namespace": made["metadata"]["namespace"],
            "labels": {
                "eph/run": rid, runids.JOB_LABEL_BATCH: batch,
                runids.JOB_LABEL_ARM: arm, runids.JOB_LABEL_DECREE: decree_id,
                runids.JOB_LABEL_REALM: str(realm),
            },
            "annotations": {"eph/decree-sha256": sha},
            "ownerReferences": [{
                "apiVersion": "batch/v1", "kind": "Job", "name": made["metadata"]["name"],
                "uid": made["metadata"]["uid"], "blockOwnerDeletion": False,
            }],
        },
        "data": data,
    }  # fmt: skip
    try:
        kube.create(cm)
    except KubeError:
        kube.delete("jobs", runids.job_name(rid))
        raise


def record_path(cfg, decree_id, batch):
    return pathlib.Path(cfg.results_dir) / decree_id / f"batch-{batch}.json"


def save_record(cfg, record):
    p = record_path(cfg, record["decree_id"], record["batch"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return p

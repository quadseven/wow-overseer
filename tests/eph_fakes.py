"""Fake kubectl and fake gh for the runner's tests: they parse the real argv."""

import copy
import json

from ephemeral import runcfg

SHA = "a" * 40
FIX = "b" * 40
OLD = "c" * 40
WS = "registry.example.com/ws@sha256:" + "1" * 64
DB = "registry.example.com/db@sha256:" + "2" * 64
OLD_WS = "registry.example.com/ws@sha256:" + "3" * 64
OLD_DB = "registry.example.com/db@sha256:" + "4" * 64
TOOLS = "registry.example.com/tools@sha256:" + "5" * 64

TOKENS = (
    "RUN_ID DECREE_ID ARM CLASS BATCH REALM_ID DEADLINE_SECONDS WORLDSERVER_IMAGE "
    "DBIMPORT_IMAGE TOOLS_IMAGE TEMPLATE_IMAGE CLIENT_DATA_CLAIM WS_CPU_REQUEST "
    "WS_CPU_LIMIT WS_MEMORY MYSQL_MEMORY BUFFER_POOL DATADIR_LIMIT EPHEMERAL_REQUEST "
    "EPHEMERAL_LIMIT"
).split()

# JSON is valid YAML, and the fake's dry-run reads JSON: the shape of the real
# template (suspended Job, one claim, sized emptyDirs) with example names.
TEMPLATE = json.dumps(
    {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": "eph-{{RUN_ID}}",
            "namespace": "wow-ephemeral",
            "labels": {
                "eph/decree": "{{DECREE_ID}}",
                "eph/arm": "{{ARM}}",
                "eph/class": "{{CLASS}}",
                "eph/batch": "{{BATCH}}",
            },
        },
        "spec": {
            "suspend": True,
            "activeDeadlineSeconds": "{{DEADLINE_SECONDS}}",
            "template": {
                "spec": {
                    "initContainers": [
                        {
                            "name": "worldserver",
                            "image": "{{WORLDSERVER_IMAGE}}",
                            "restartPolicy": "Always",
                            "resources": {
                                "requests": {
                                    "cpu": "{{WS_CPU_REQUEST}}",
                                    "memory": "{{WS_MEMORY}}",
                                },
                            },
                        },
                        {
                            "name": "mysql",
                            "image": "{{DBIMPORT_IMAGE}}",
                            "restartPolicy": "Always",
                            "resources": {
                                "requests": {
                                    "cpu": "250m",
                                    "memory": "{{MYSQL_MEMORY}}",
                                }
                            },
                        },
                        {
                            "name": "x",
                            "image": "{{TOOLS_IMAGE}}",
                            "args": [
                                "{{BUFFER_POOL}}",
                                "{{EPHEMERAL_REQUEST}}",
                                "{{EPHEMERAL_LIMIT}}",
                                "{{REALM_ID}}",
                                "{{WS_CPU_LIMIT}}",
                            ],
                        },
                    ],
                    "containers": [
                        {
                            "name": "judge",
                            "image": "{{TOOLS_IMAGE}}",
                            "resources": {
                                "requests": {"cpu": "150m", "memory": "256Mi"}
                            },
                        }
                    ],
                    "volumes": [
                        {
                            "name": "eph-template",
                            "image": {"reference": "{{TEMPLATE_IMAGE}}"},
                        },
                        {
                            "name": "client-data",
                            "persistentVolumeClaim": {
                                "claimName": "{{CLIENT_DATA_CLAIM}}"
                            },
                        },
                        {
                            "name": "datadir",
                            "emptyDir": {"sizeLimit": "{{DATADIR_LIMIT}}"},
                        },
                        {"name": "logs", "emptyDir": {"sizeLimit": "256Mi"}},
                    ],
                }
            },
        },
    }
)
CLASSES = {
    "lean": {
        "WS_CPU_REQUEST": "1", "WS_CPU_LIMIT": "2", "WS_MEMORY": "3584Mi",
        "MYSQL_MEMORY": "1280Mi", "BUFFER_POOL": "768M", "DATADIR_LIMIT": "2560Mi",
        "EPHEMERAL_REQUEST": "2Gi", "EPHEMERAL_LIMIT": "3Gi",
    },
    "full": {
        "WS_CPU_REQUEST": "2", "WS_CPU_LIMIT": "3", "WS_MEMORY": "6Gi",
        "MYSQL_MEMORY": "1536Mi", "BUFFER_POOL": "1G", "DATADIR_LIMIT": "5Gi",
        "EPHEMERAL_REQUEST": "4Gi", "EPHEMERAL_LIMIT": "6Gi",
    },
}  # fmt: skip

PLAYERBOTS = "Playerbots.Enabled = 1\nPlayerbots.MaxRandomBots = 2600\nPlayerbots.MinRandomBots = 2600\n"
OVERSEER = 'Overseer.HeadlessRoster = "Grug,Zug"\n'


def make_cfg(results_dir):
    return runcfg.from_dict(
        {
            "results_dir": str(results_dir),
            "tools_image": TOOLS,
            "template_images": {"lean": "registry.example.com/t:lean-1", "full": "registry.example.com/t:full-1"},
            "nodes": {
                "node-a": {"claim": "client-data-a", "max_worlds": 5, "classes": ["lean", "full"]},
                "node-b": {"claim": "client-data-b", "max_worlds": 1, "classes": ["lean"]},
            },
            "never_nodes": ["node-organic"],
        }
    )  # fmt: skip


class FakeCluster:
    """A kubectl runner over an in-memory object store."""

    def __init__(self):
        self.objs = {}
        self.calls = []
        self.node_stats = {}
        self.seq = 0
        self.now = "2026-11-15T10:00:00Z"
        self.fail = {}
        self._seed()

    def _seed(self):
        self.put("configmaps", "wow-ephemeral", "eph-world-template", {
            "data": {
                "job.yaml": TEMPLATE,
                "classes.json": json.dumps(CLASSES),
                "tokens.txt": "# tokens\n" + "\n".join(f"{t}: x" for t in TOKENS) + "\n",
            }
        })  # fmt: skip
        for g, text in (
            ("playerbots", PLAYERBOTS),
            ("overseer", OVERSEER),
            ("worldserver", "MaxPlayerLevel = 60\n"),
        ):
            self.put(
                "configmaps",
                "wow-dev",
                f"{g}-overrides-h1",
                {"data": {f"{g}.overrides.conf": text}},
            )
        vols = [
            {"name": f"{g}-overrides", "configMap": {"name": f"{g}-overrides-h1"}}
            for g in ("playerbots", "overseer", "worldserver")
        ]
        self.put("deployments", "wow-dev", "worldserver", {"spec": {"template": {"spec": {
            "initContainers": [{"name": "db-upgrade", "image": DB}],
            "containers": [{"name": "worldserver", "image": WS, "env": [
                {"name": "OVERSEER_PIN_OVERSEER", "value": SHA},
                {"name": "OVERSEER_PIN_DUNGEON_CLEAR", "value": SHA},
            ]}],
            "volumes": vols,
        }}}})  # fmt: skip

    def put(self, plural, ns, name, obj):
        obj = copy.deepcopy(obj)
        meta = obj.setdefault("metadata", {})
        meta.update(name=name, namespace=ns)
        self.seq += 1
        meta.setdefault("uid", f"uid-{self.seq}")
        meta.setdefault("creationTimestamp", self.now)
        meta.setdefault("resourceVersion", str(self.seq))
        self.objs[(plural, ns, name)] = obj
        return obj

    def of(self, plural, ns=None):
        return [
            o
            for (p, n, _), o in sorted(self.objs.items())
            if p == plural and (ns is None or n == ns)
        ]

    # -- the runner ---------------------------------------------------------------
    def __call__(self, argv, input_text=None):
        self.calls.append((list(argv), input_text))
        a = list(argv[1:])
        ns = ""
        while a and a[0] in ("--kubeconfig", "-n"):
            if a[0] == "-n":
                ns = a[1]
            a = a[2:]
        verb, rest = a[0], a[1:]
        for key, rc in self.fail.items():
            if key == verb or key in " ".join(a) or key in (input_text or ""):
                return rc, "", f"forced failure for {key}"
        return getattr(self, "v_" + verb)(ns, rest, input_text)

    def v_get(self, ns, rest, _in):
        if rest[0] == "--raw":
            node = rest[1].split("/")[4]
            if node not in self.node_stats:
                return 1, "", "NotFound: no stats"
            return 0, json.dumps(self.node_stats[node]), ""
        kind = rest[0]
        sel = rest[rest.index("-l") + 1] if "-l" in rest else None
        name = rest[1] if len(rest) > 1 and not rest[1].startswith("-") else None
        if name:
            o = self.objs.get((kind, ns, name))
            return (
                (0, json.dumps(o), "")
                if o
                else (1, "", f'Error from server (NotFound): {kind} "{name}" not found')
            )
        items = [o for o in self.of(kind, ns) if self._match(o, sel)]
        return 0, json.dumps({"items": items}), ""

    @staticmethod
    def _match(o, sel):
        if not sel:
            return True
        labels = o["metadata"].get("labels", {})
        for part in sel.split(","):
            k, _, v = part.partition("=")
            if k not in labels or (v and labels[k] != v):
                return False
        return True

    def v_create(self, ns, rest, text):
        if "--dry-run=client" in rest:
            try:
                return 0, json.dumps(json.loads(text)), ""
            except ValueError:
                return 1, "", "not json"
        obj = json.loads(text)
        kind = {
            "Job": "jobs",
            "ConfigMap": "configmaps",
            "Lease": "leases.coordination.k8s.io",
        }[obj["kind"]]
        ns = obj["metadata"].get("namespace", ns)
        if (kind, ns, obj["metadata"]["name"]) in self.objs:
            return 1, "", "AlreadyExists"
        made = self.put(
            kind, ns, obj["metadata"]["name"], {**obj, "metadata": {**obj["metadata"]}}
        )
        return 0, json.dumps(made), ""

    def v_replace(self, ns, rest, text):
        obj = json.loads(text)
        kind = "leases.coordination.k8s.io"
        key = (kind, obj["metadata"].get("namespace", ns), obj["metadata"]["name"])
        cur = self.objs.get(key)
        if not cur or cur["metadata"]["resourceVersion"] != obj["metadata"].get(
            "resourceVersion"
        ):
            return 1, "", "Conflict"
        self.seq += 1
        obj["metadata"]["resourceVersion"] = str(self.seq)
        self.objs[key] = obj
        return 0, json.dumps(obj), ""

    def v_patch(self, ns, rest, _in):
        kind, name = rest[0], rest[1]
        patch = json.loads(rest[rest.index("-p") + 1])
        o = self.objs[(kind, ns, name)]
        for k, v in patch.get("spec", {}).items():
            o.setdefault("spec", {})[k] = v
        return 0, "", ""

    def v_delete(self, ns, rest, _in):
        kind, name = rest[0], rest[1]
        job = self.objs.pop((kind, ns, name), None)
        if job and kind == "jobs":
            uid = job["metadata"]["uid"]
            for key, o in list(self.objs.items()):
                if any(
                    r.get("uid") == uid
                    for r in o["metadata"].get("ownerReferences", [])
                ):
                    del self.objs[key]
        return 0, "", ""


class FakeGh:
    """gh api over canned answers; records writes so tests can read them back."""

    def __init__(self):
        self.answers = {}
        self.calls = []
        self.comments = {}
        self.next_id = 100

    def __call__(self, argv, input_text=None):
        self.calls.append((list(argv), input_text))
        args = argv[1:]
        method = "GET"
        if "-X" in args:
            method = args[args.index("-X") + 1]
        path = next(
            x for x in args[1:] if not x.startswith("-") and "/" in x and x != method
        )
        body = json.loads(input_text) if input_text else {}
        key = (method, path)
        if key in self.answers:
            v = self.answers[key]
            return (0, json.dumps(v), "") if not isinstance(v, tuple) else v
        base = path.split("?")[0]
        if method == "POST" and base.endswith("/comments"):
            self.next_id += 1
            c = {"id": self.next_id, "html_url": f"https://github.com/x/y/issues/1#c{self.next_id}",
                 "user": {"login": self.author}, "body": body["body"]}  # fmt: skip
            self.comments.setdefault(base, []).append(c)
            return 0, json.dumps(c), ""
        if method == "GET" and base.endswith("/comments"):
            return 0, json.dumps(self.comments.get(base, [])), ""
        if method != "GET":
            return 0, "{}", ""
        return 1, "", f"HTTP 404 no canned answer for {method} {path}"

    author = "agent-anthropic-claude-code[bot]"

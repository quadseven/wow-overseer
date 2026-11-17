"""Runner settings: everything specific to one deployment, read from a JSON file.

The repository names no host, node, registry or path. An operator copies
`ephemeral/eph.config.example.json`, fills it in, and points `--config` or
`EPH_CONFIG` at it. A missing or malformed file is an error, never a guess.
"""

import json
import os
import pathlib
from dataclasses import dataclass, field

DEFAULT_FIX_PIN_ENV = {
    "quadseven/mod-overseer": "OVERSEER_PIN_OVERSEER",
    "quadseven/mod-dungeon-clear": "OVERSEER_PIN_DUNGEON_CLEAR",
    "quadseven/mod-playerbots": "OVERSEER_PIN_PLAYERBOTS",
    # The bridge's own repo: not a worldserver env var but the commit baked into
    # the bridge image (its Env), read per arm from the image itself.
    "quadseven/wow-overseer": "OVERSEER_COMMIT",
}


class ConfigError(Exception):
    """The runner settings are missing or unusable."""


@dataclass
class Node:
    name: str
    claim: str
    max_worlds: int
    classes: tuple


@dataclass
class Config:
    namespace: str = "wow-ephemeral"
    source_namespace: str = ""
    source_deployment: str = "worldserver"
    kubeconfig: str = ""
    results_dir: str = ""
    ledger_path: str = ""
    tools_image: str = ""
    template_images: dict = field(default_factory=dict)
    nodes: dict = field(default_factory=dict)
    never_nodes: tuple = ()
    min_free_percent: int = 20
    decree_repo: str = "quadseven/wow-overseer"
    author_login: str = "agent-anthropic-claude-code[bot]"
    fix_pin_env: dict = field(default_factory=lambda: dict(DEFAULT_FIX_PIN_ENV))
    lease_seconds: int = 60
    head_wait_seconds: int = 30 * 60
    settle_seconds: int = 180
    result_keep_days: int = 14


def load(path=None, env=None):
    env = os.environ if env is None else env
    path = path or env.get("EPH_CONFIG")
    if not path:
        raise ConfigError("no runner config: pass --config or set EPH_CONFIG")
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"runner config unreadable: {exc}") from exc
    return from_dict(raw)


def _node(name, spec, never):
    if not isinstance(spec, dict) or not spec.get("claim"):
        raise ConfigError(f"node {name!r} needs a client-data claim")
    if name in never:
        raise ConfigError(f"node {name!r} is listed as never-use")
    mx = spec.get("max_worlds")
    if not isinstance(mx, int) or isinstance(mx, bool) or mx < 1:
        raise ConfigError(f"node {name!r} needs max_worlds of at least 1")
    classes = tuple(spec.get("classes") or ("lean",))
    if not set(classes) <= {"lean", "full"}:
        raise ConfigError(f"node {name!r} classes must be lean and/or full")
    return Node(name, spec["claim"], mx, classes)


def _check(cfg):
    claims = [n.claim for n in cfg.nodes.values()]
    if len(set(claims)) != len(claims):
        raise ConfigError("two nodes share one client-data claim")
    if "@sha256:" not in str(cfg.tools_image):
        raise ConfigError("tools_image must be pinned by digest (name@sha256:...)")
    if set(cfg.template_images) != {"lean", "full"}:
        raise ConfigError("template_images needs both lean and full")
    if not cfg.source_namespace:
        raise ConfigError("source_namespace (the base realm's namespace) is required")
    if not cfg.results_dir:
        raise ConfigError("results_dir is required")
    if not 1 <= int(cfg.min_free_percent) <= 90:
        raise ConfigError("min_free_percent must be between 1 and 90")


def from_dict(raw):
    if not isinstance(raw, dict):
        raise ConfigError("runner config must be a JSON object")
    extra = sorted(set(raw) - set(Config.__dataclass_fields__))
    if extra:
        raise ConfigError(f"unknown runner config keys: {', '.join(extra)}")
    skip = ("nodes", "never_nodes")
    cfg = Config(**{k: v for k, v in raw.items() if k not in skip})
    cfg.never_nodes = tuple(raw.get("never_nodes") or ())
    nodes = raw.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise ConfigError("runner config needs a non-empty nodes mapping")
    for name, spec in nodes.items():
        cfg.nodes[name] = _node(name, spec, cfg.never_nodes)
    _check(cfg)
    return cfg

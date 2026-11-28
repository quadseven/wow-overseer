"""`eph withdraw <batch>`: ask the dispatcher to drop a batch that has not started.

A session may not `kubectl delete`, so the request is data: one ConfigMap labelled
with the batch id. The dispatcher reads it on its next pass, deletes the batch's
suspended Jobs with an INVALID result each, and then deletes the request.
"""

from . import runids
from .kube import KubeError


class WithdrawError(Exception):
    """The batch id is malformed."""


def request(cfg, kube, batch):
    """Create the request ConfigMap. Returns "requested" or "already requested"."""
    if not runids.BATCH_RE.match(batch or ""):
        raise WithdrawError(f"not a batch id (six lowercase hex characters): {batch!r}")
    cm = {
        "apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {
            "name": runids.withdraw_name(batch), "namespace": cfg.namespace,
            "labels": {runids.LABEL_WITHDRAW: batch},
        },
        "data": {"batch": batch},
    }  # fmt: skip
    try:
        kube.create(cm)
    except KubeError as exc:
        if "AlreadyExists" in exc.stderr or "AlreadyExists" in str(exc):
            return "already requested"
        raise
    return "requested"

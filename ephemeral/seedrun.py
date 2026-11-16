"""`eph seed`: the in-world step that guards, compiles and applies a decree.

Everything it needs comes from the pod's environment, none of it from the
decree: the decree cannot name a host, a database or a credential.

    EPH_MYSQL_HOST       must be the loopback address (default: the loopback address)
    EPH_MYSQL_PORT       default 3306
    EPH_MYSQL_USER       default root
    EPH_MYSQL_PASSWORD   the world's own random root password
    EPH_WORLD_LABEL      the namespace's world label value, from the pod spec
    EPH_HARNESS_GRANTS   the harness ConfigMap's grants line
"""

import pathlib

from . import anchors as anchors_mod
from . import dbschema, guard
from .compiler import compile_seed
from .miniyaml import YamlError, loads
from .resolve import SqlResolver
from .sqlgen import SeedError

LIVE_SCHEMA_SQL = (
    "SELECT table_schema, table_name, column_name FROM information_schema.columns "
    "WHERE table_schema IN ('acore_characters', 'acore_world', 'acore_playerbots') "
    "ORDER BY table_schema, table_name, ordinal_position"
)


def inputs_from_env(env):
    return guard.GuardInputs(
        mysql_host=env.get("EPH_MYSQL_HOST", guard.LOOPBACK),
        mysql_port=int(env.get("EPH_MYSQL_PORT", "3306")),
        world_label=env.get("EPH_WORLD_LABEL", ""),
        harness_grants=env.get("EPH_HARNESS_GRANTS", ""),
    )


def _default_connect(**kw):
    import pymysql  # a dependency of the world image, not of the unit suite

    return pymysql.connect(**kw)


def run(decree_path, env, dry_run=False, anchors_path=None, connect=None, out=print):
    """Returns 0 on success, 3 when the run is INVALID (guard or seed refused)."""
    try:
        decree = loads(pathlib.Path(decree_path).read_text(encoding="utf-8"))
        anchors_doc = loads(
            pathlib.Path(anchors_path or anchors_mod.DEFAULT_PATH).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, YamlError) as exc:
        out(f"INVALID: {exc}")
        return 3
    problems = anchors_mod.validate(anchors_doc)
    if problems:
        out("INVALID: anchors.yaml: " + "; ".join(problems))
        return 3
    anchors = anchors_mod.Anchors(anchors_doc.get("anchors") or {})
    snapshot = dbschema.Schema.load()
    try:
        inputs = inputs_from_env(env)
    except ValueError:
        out("INVALID: EPH_MYSQL_PORT must be an integer")
        return 3
    try:
        g = guard.open_guarded(
            inputs,
            connect or _default_connect,
            snapshot,
            user=env.get("EPH_MYSQL_USER", "root"),
            password=env.get("EPH_MYSQL_PASSWORD", ""),
        )
    except SeedError as exc:
        out(f"INVALID: guard refused: {exc}")
        return 3
    except Exception as exc:  # noqa: BLE001 - any driver or socket failure is INVALID, not a traceback
        out(f"INVALID: could not reach the world database ({type(exc).__name__})")
        return 3
    rc = _seed_and_report(g, decree, anchors, dry_run, out)
    try:
        g.close()
    except Exception as exc:  # noqa: BLE001 - a failed close must not turn into a traceback or a success
        out(
            f"INVALID: closing the world database connection failed ({type(exc).__name__})"
        )
        return 3
    return rc


def _seed_and_report(g, decree, anchors, dry_run, out):
    """Compile and apply on an open guarded connection; 0 on success, 3 when INVALID."""
    try:
        live = dbschema.Schema.from_rows(g.query(LIVE_SCHEMA_SQL))
        g.use_schema(live)  # statements are checked against THIS world's schema
        plan = compile_seed(decree, SqlResolver(g), live, anchors)
        out(plan.render())
        if not dry_run:
            out(f"applied {guard.apply_plan(plan, g)} statements")
        return 0
    except SeedError as exc:
        out(f"INVALID: {exc}")
        return 3
    except Exception as exc:  # noqa: BLE001 - a database error mid-seed is INVALID (apply rolled back)
        out(f"INVALID: database error while seeding ({type(exc).__name__})")
        return 3

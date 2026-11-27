"""Read the durable records of actions taken before a wedge."""

import deathask
import dungeonstall


_DEATH_ASKS_SQL = (
    "SELECT COUNT(*) AS n FROM overseer_guild_ask "
    "WHERE created_at > NOW() - INTERVAL 24 HOUR AND created_at <= NOW() "
    "AND kind = %s AND LOCATE(%s, said) = 1"
)
_RESTART_STAND_DOWNS_SQL = (
    "SELECT COUNT(*) AS n FROM overseer_dungeon_pace "
    "WHERE created_at > NOW() - INTERVAL 24 HOUR AND created_at <= NOW() "
    "AND decision IN (%s, %s) AND LOCATE(%s, reason) > 0"
)


def _count(reader, sql: str, params: tuple, table: str) -> int | None:
    rows = reader.rows(sql, params, what=table)
    return int(rows[0]["n"]) if rows else None


def pre_wedge(_query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/pre-wedge: recorded death and restart slope actions in the past 24 hours."""
    return 200, {
        "death_slope_asks": _count(
            ctx.read,
            _DEATH_ASKS_SQL,
            (deathask.KIND, deathask.SLOPE_ASK_PREFIX),
            "overseer_guild_ask",
        ),
        "restart_slope_stand_downs": _count(
            ctx.read,
            _RESTART_STAND_DOWNS_SQL,
            (
                dungeonstall.DECISION,
                dungeonstall.ORDER_DECISION,
                dungeonstall.RESTART_SLOPE_REASON,
            ),
            "overseer_dungeon_pace",
        ),
    }


ROUTES = {"/api/v2/pre-wedge": pre_wedge}

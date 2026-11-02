"""The guild's work orders, kept between bridge passes (#1487).

WHY. workorders.py plans an order and moves it requested -> assigned ->
complete, but it is pure: an order lived for one pass. Nothing could ask for
a consumable or farming order and nothing remembered who had taken one, so a
second pass could hand the same order to someone else. This is the memory: one
row per order in a table the bridge owns, the way the campaign queue
(campaignqueue.py) and the order record (orderrecord.py) keep theirs.

THE GUARDS ARE IN THE STATEMENTS, not only in workorders.py. ASSIGN_SQL moves
a row only while it is still requested, so an assigned order keeps its
assignee whatever plan is saved over it. COMPLETE_SQL moves a row only while
it is assigned AND the reporter is its assignee, so a report from anyone else
changes nothing. Each returns the rows it moved, and the caller reads 0 as
"refused".

ONE OPEN ORDER PER (kind, item). `request` returns the id of an open order of
the same kind and item (case folded) instead of adding a second, so an intake
that asks every pass (raidsupply.fire_potion_order) asks once. A completed
order is not open, so the next shortfall is a new order.

The statements run on any DB-API cursor that takes `%s` placeholders and
returns rows as dicts: the bridge's pymysql DictCursor, and the test suite's
SQLite cursor. Nothing here crafts, gathers or writes a worldserver row.

WHERE IT RUNS. bridge._ensure_order_store creates the table at start-up. The
guild pass does not read or write it yet: reading the open orders into its
plan, saving the assignments and taking reports is the next step.
"""

from __future__ import annotations

import workorders

TABLE = "overseer_work_order"

# Widths: an item_template name fits 64; a character name fits 12, and
# requested_by holds a source such as `raidsupply` or `discord:<id>`.
CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_work_order ("
    " id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " kind ENUM('consumable','farming','cooldown') NOT NULL,"
    " item VARCHAR(64) NOT NULL,"
    " quantity INT UNSIGNED NOT NULL DEFAULT 0,"
    " zone VARCHAR(64) NOT NULL DEFAULT '',"
    " requested_by VARCHAR(64) NOT NULL DEFAULT '',"
    " status ENUM('requested','assigned','complete') NOT NULL"
    " DEFAULT 'requested',"
    " assigned_to VARCHAR(32) NOT NULL DEFAULT '',"
    " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " assigned_at TIMESTAMP NULL DEFAULT NULL,"
    " completed_at TIMESTAMP NULL DEFAULT NULL,"
    " PRIMARY KEY (id), KEY idx_status (status, id)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
    " COMMENT='Guild work orders and who took each (wow-overseer#1487)'"
)

INSERT_SQL = (
    "INSERT INTO overseer_work_order"
    " (kind, item, quantity, zone, requested_by, status, assigned_to)"
    " VALUES (%s, %s, %s, %s, %s, 'requested', '')"
)

# The columns from_row reads, spelled out in each read: literal SQL only.
SELECT_OPEN_SQL = (
    "SELECT id, kind, item, quantity, zone, requested_by, status, assigned_to"
    " FROM overseer_work_order"
    " WHERE status IN ('requested', 'assigned') ORDER BY id"
)

SELECT_ONE_SQL = (
    "SELECT id, kind, item, quantity, zone, requested_by, status, assigned_to"
    " FROM overseer_work_order WHERE id = %s"
)

ASSIGN_SQL = (
    "UPDATE overseer_work_order"
    " SET status = 'assigned', assigned_to = %s, assigned_at = CURRENT_TIMESTAMP"
    " WHERE id = %s AND status = 'requested'"
)

COMPLETE_SQL = (
    "UPDATE overseer_work_order"
    " SET status = 'complete', completed_at = CURRENT_TIMESTAMP"
    " WHERE id = %s AND status = 'assigned' AND assigned_to = %s"
    " AND assigned_to <> ''"
)


def from_row(row: dict) -> workorders.WorkOrder:
    """The WorkOrder a stored row describes."""
    return workorders.WorkOrder(
        kind=str(row["kind"]),
        item=str(row["item"]),
        quantity=int(row["quantity"] or 0),
        zone=str(row["zone"] or ""),
        requested_by=str(row["requested_by"] or ""),
        status=str(row["status"]),
        assigned_to=str(row["assigned_to"] or ""),
        order_id=int(row["id"]),
    )


def open_orders(cur) -> list:
    """Every requested or assigned order, oldest first."""
    cur.execute(SELECT_OPEN_SQL)
    return [from_row(r) for r in cur.fetchall()]


def get(cur, order_id: int) -> workorders.WorkOrder | None:
    """The order stored under `order_id`, or None."""
    cur.execute(SELECT_ONE_SQL, (int(order_id),))
    row = cur.fetchone()
    return None if row is None else from_row(row)


def _same(a: workorders.WorkOrder, b: workorders.WorkOrder) -> bool:
    return (a.kind, a.item.strip().casefold()) == (b.kind, b.item.strip().casefold())


def request(cur, order: workorders.WorkOrder) -> int:
    """Store a requested order and return its id.

    An open order of the same kind and item is kept as it is and its id
    returned, so asking twice is asking once.
    """
    if order.kind not in workorders.KINDS:
        raise ValueError("unknown work order kind %r" % (order.kind,))
    for held in open_orders(cur):
        if _same(held, order):
            return held.order_id
    cur.execute(
        INSERT_SQL,
        (
            order.kind,
            order.item.strip()[:64],
            max(0, int(order.quantity)),
            order.zone.strip()[:64],
            str(order.requested_by)[:64],
        ),
    )
    return int(cur.lastrowid)


def save_plan(cur, work_plan: workorders.WorkOrderPlan) -> int:
    """Record each assignment of a stored order; return how many rows moved.

    An assignment of an order the store does not hold (order_id 0, such as a
    standing cooldown order) is skipped, and one of an order no longer
    requested moves nothing (ASSIGN_SQL's guard).
    """
    moved = 0
    for assignment in work_plan.assignments:
        order_id = int(assignment.order.order_id)
        if not order_id:
            continue
        cur.execute(ASSIGN_SQL, (str(assignment.taker)[:32], order_id))
        moved += max(0, int(cur.rowcount))
    return moved


def report(cur, order_id: int, reporter: str) -> bool:
    """Complete an assigned order on its assignee's report; False if refused."""
    cur.execute(COMPLETE_SQL, (int(order_id), str(reporter or "")))
    return int(cur.rowcount) == 1

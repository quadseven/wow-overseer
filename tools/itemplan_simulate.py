#!/usr/bin/env python3
"""Run itemplan over a dump of both families and print one block per member.

Usage: itemplan_simulate.py INVENTORY.tsv MEMBERS_SKILLS.tsv [GUILDBANK.tsv]

Offline: reads the TSV files given and nothing else. The inventory columns are
family, member, level, class, ok, loc, entry, name, item class, subclass,
quality, count, vendor sell price (copper per unit), binding, required level,
item level, stackable. The skills file has family, name, level, class, race,
gold, bank bag slots bought, then one row per skill: skill id, value, max.
The guild bank file has guild, tab, slot, entry, name, class, subclass,
quality, count, sell.

The quest log is not in the dump, so every quest-class stack is kept. No
market price is in the dump, so the vendor price is the floor and no stack is
auctioned. Both are stated in docs/ITEM_PLAN.md.
"""

from __future__ import annotations

import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import guildbank  # noqa: E402
import itemplan  # noqa: E402

BAR = 8


def read_tsv(path: str) -> list:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def load(inv_path: str, skills_path: str):
    inv = read_tsv(inv_path)
    sk = read_tsv(skills_path)
    skills: dict = {}
    meta: dict = {}
    for r in sk:
        meta[r["name"]] = r
        skills.setdefault(r["name"], []).append(
            (int(r["skill"]), int(r["value"]), int(r["max"]))
        )
    stacks: list = []
    counter: dict = {}
    for r in inv:
        idx = counter.get(r["member"], 0)
        counter[r["member"]] = idx + 1
        stacks.append(
            itemplan.Stack(
                holder=r["member"],
                loc=r["loc"],
                entry=int(r["entry"]),
                name=r["name"],
                item_class=int(r["iclass"]),
                subclass=int(r["isub"]),
                quality=int(r["q"]),
                count=int(r["count"]),
                sell=int(r["sell"]),
                bind=int(r["bind"]),
                req_level=int(r["reqlvl"]),
                item_level=int(r["ilvl"]),
                stackable=int(r["stackable"]),
                index=idx,
            )
        )
    members = []
    for name in sorted(meta):
        m = meta[name]
        worn = [s for s in stacks if s.holder == name and s.loc == itemplan.WORN]
        carried, bank, empty, _bags = itemplan.capacities(worn, int(m["bankSlots"]))
        members.append(
            itemplan.Member(
                name=name,
                family=m["family"],
                level=int(m["level"]),
                class_id=int(m["class"]),
                skills=tuple(sorted(skills[name])),
                carried_slots=carried,
                bank_slots=bank,
                empty_bank_positions=empty,
            )
        )
    return stacks, members


def guild_free(path: str | None, members: list) -> dict:
    """(family, tab) -> free slots. Which guild a family banks in is not in
    the dump, so a family gets the roomiest guild's free count for the tab."""
    if not path:
        return {}
    used: dict = {}
    for r in read_tsv(path):
        key = (r["guild"], int(r["TabId"]))
        used[key] = used.get(key, 0) + 1
    out: dict = {}
    for fam in {m.family for m in members}:
        for tab in {t for _g, t in used} | {t.tab_id for t in guildbank.TABS}:
            free = [itemplan.TAB_SLOTS - n for (g, t), n in used.items() if t == tab]
            out[(fam, tab)] = max(free, default=0)
    return out


def report(stacks, members, plan_, out) -> dict:
    results = {}
    for m in members:
        mine = [s for s in stacks if s.holder == m.name]
        decisions = plan_.by_holder(m.name)
        now = itemplan.free_now(m, mine)
        after = itemplan.free_after(plan_, m, mine)
        no_sales = itemplan.free_after(plan_, m, mine, sales=False)
        by_route: dict = {}
        gold = 0
        for d in decisions:
            if d.from_loc == itemplan.WORN:
                continue
            moved = d.route != itemplan.KEEP_CARRY and d.from_loc in itemplan.CARRIED
            moved = moved or (
                d.route != itemplan.BANK_PERSONAL and d.from_loc in itemplan.BANKED
            )
            if moved or d.route not in (itemplan.KEEP_CARRY, itemplan.BANK_PERSONAL):
                by_route[d.route] = by_route.get(d.route, 0) + 1
            if d.route == itemplan.SELL_VENDOR:
                gold += d.value
        bank_used = sum(
            1
            for d in decisions
            if d.route == itemplan.BANK_PERSONAL and d.from_loc != itemplan.WORN
        )
        keep = sorted(
            (
                d
                for d in decisions
                if d.route == itemplan.KEEP_CARRY and d.from_loc != itemplan.WORN
            ),
            key=lambda d: (-itemplan.TIER[d.goal], -d.value, d.name),
        )
        results[m.name] = (now, after, no_sales, by_route, gold, bank_used)
        out.write(
            "%s (%s, level %d, class %d): carried slots %d, free now %d, free after %d (%d with no vendor), bank %d/%d after, bar %d: %s\n"
            % (
                m.name,
                m.family,
                m.level,
                m.class_id,
                m.carried_slots,
                now,
                after,
                no_sales,
                bank_used,
                m.bank_slots,
                BAR,
                "REACHED" if after >= BAR else "NOT REACHED",
            )
        )
        out.write(
            "  routes: %s\n"
            % (", ".join("%s %d" % kv for kv in sorted(by_route.items())) or "none")
        )
        out.write("  vendor gold realized: %.2f\n" % (gold / 10000))
        out.write("  kept in the bags (top 10):\n")
        for d in keep[:10]:
            out.write(
                "    %-34s x%-3d %-26s %s\n"
                % (d.name[:34], d.count, d.goal, d.reason[:60])
            )
    tab_report(plan_, out)
    return results


def tab_report(plan_, out) -> None:
    """What a second guild bank tab would hold and what it costs."""
    wanted = [
        d
        for d in plan_.decisions
        if itemplan.GUILD_BANK in d.options and d.route != itemplan.GUILD_BANK
    ]
    cost, per_slot = itemplan.tab_slot_cost(1)
    value = sum(d.value for d in wanted)
    out.write(
        "\nguild bank: %d stacks wanted a tab and found none (vendor value %.2f gold); "
        "tab 2 costs %.0f gold, %.2f gold a slot\n"
        % (len(wanted), value / 10000, cost / 10000, per_slot / 10000)
    )


def main(argv: list) -> int:
    if len(argv) < 3:
        sys.stderr.write(__doc__)
        return 2
    stacks, members = load(argv[1], argv[2])
    ctx = itemplan.Context(
        guild_free=guild_free(argv[3] if len(argv) > 3 else None, members)
    )
    plan_ = itemplan.plan(stacks, members, ctx)
    report(stacks, members, plan_, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

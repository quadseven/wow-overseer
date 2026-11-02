"""Maintenance members recover capacity with owned bags or paid vendor bags."""

from __future__ import annotations

from dataclasses import dataclass

import bag_pressure
import bag_upgrade
import classic
import guildcorps
import guildjobs
import guildroute


@dataclass(frozen=True)
class Recovery:
    step: guildcorps.Step
    yards: float = 0.0

    @property
    def far(self) -> bool:
        return self.yards > guildroute.TRAINER_WALK_YARDS


def eligible(member: guildjobs.Member, recent=()) -> bool:
    return (
        member.role == guildjobs.MAINTENANCE
        and member.eligible
        and member.online
        and member.alive
        and not member.in_combat
        and member.map_id is not None
        and not classic.is_expansion_map(member.map_id)
        and member.x is not None
        and member.y is not None
        and member.free_slots is not None
        and 0 <= member.free_slots <= bag_pressure.TOWN_RUN_FREE_SLOTS
        and not guildjobs._cooling(member, guildjobs.BAG_ACTION, recent)
    )


def plan(members, containers, vendors, cap=guildroute.MAIL_RUN_YARDS):
    """One bounded bag step per member; all prices and stock come from the world."""
    inventory = {m.name: m for m in containers}
    steps, notes = {}, []
    for member in sorted(members, key=lambda m: m.name):
        bags = inventory.get(member.name)
        if not eligible(member) or bags is None:
            continue
        source = guildjobs.source_for(guildjobs.BAG_ACTION, member.name)
        moves = bag_upgrade.self_equips([bags])
        if moves:
            move = moves[0]
            steps[member.name] = Recovery(
                guildcorps.Step(
                    member.name,
                    guildjobs.BAG_ACTION,
                    move.entry,
                    move.said,
                    rows=(guildcorps.Row("bot", move.command, "", source),),
                )
            )
            continue
        positions = bag_pressure.open_bag_positions([bags]).get(member.name, 0)
        if positions <= 0:
            continue
        buyer = bag_pressure.BagBuyer(
            member.name, member.level, member.money, positions, member.free_slots
        )
        here = bag_pressure.Standing(member.name, member.map_id, member.x, member.y)
        trip = bag_pressure.bag_vendor_trip(
            [buyer],
            vendors.get(member.name, ()),
            leader=member.name,
            standing={member.name: here},
            max_yards=cap,
        )
        if trip.vendor is None:
            notes.append("%s: %s" % (member.name, trip.why_not))
            continue
        buyer = bag_pressure.BagBuyer(
            member.name,
            member.level,
            member.money,
            positions,
            member.free_slots,
            frozenset(o.entry for o in trip.vendor.offers),
        )
        purchases, refused = bag_pressure.bag_purchases([buyer], trip.vendor.offers)
        notes.extend(refused)
        for purchase in purchases:
            steps[member.name] = Recovery(
                guildcorps.Step(
                    member.name,
                    guildjobs.BAG_ACTION,
                    purchase.entry,
                    "%s buys %s for up to %d copper to recover bag space"
                    % (member.name, purchase.name, purchase.price),
                    rows=(
                        guildcorps.Row("buy", purchase.command, "", source),
                        guildcorps.Row("bot", purchase.equip_command, "", source),
                    ),
                    walk=guildcorps.Row(
                        "buy",
                        "walk-to-vendor item:%d%s"
                        % (purchase.entry, guildroute.errand_cap_word(cap)),
                        "",
                        guildjobs.source_for(
                            guildjobs.BAG_ACTION + "-walk", member.name
                        ),
                    ),
                ),
                yards=trip.vendor.yards,
            )
    return steps, tuple(notes)

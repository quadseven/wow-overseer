"""Maintenance members recover capacity with owned bags or paid vendor bags.

Any member, whatever its role, wears a better bag it already carries: the
guild corps posts its ladder bags to the whole guild (#1591), and wearing
one is not a purchase, so the equip half is not gated on the maintenance
role or on being short of space. Buying still is."""

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
        and not classic.stands_outside(member)
        and member.x is not None
        and member.y is not None
        and member.free_slots is not None
        and 0 <= member.free_slots <= bag_pressure.TOWN_RUN_FREE_SLOTS
        and not guildjobs._cooling(member, guildjobs.BAG_ACTION, recent)
    )


def equip_eligible(member: guildjobs.Member, recent=()) -> bool:
    """Whether a member may be told to wear a bag it already carries.

    Wearing is not buying: the bag is already the member's own, no purse
    opens and no vendor walk is asked, so neither the maintenance role
    nor the short-of-space bar on `eligible` applies. The corps posts
    its ladder bags to the whole guild (#1591), and a raider, a summoner
    or a member with room to spare who collected one still needs this
    step to put it on; without it the bag rides as cargo for good.
    Everything else `eligible` asks (a natural member, standing in the
    world, off the bag cooldown) still holds."""
    return (
        member.eligible
        and member.online
        and member.alive
        and not member.in_combat
        and member.map_id is not None
        and not classic.stands_outside(member)
        and member.x is not None
        and member.y is not None
        and not guildjobs._cooling(member, guildjobs.BAG_ACTION, recent)
    )


def plan(members, containers, vendors, cap=guildroute.MAIL_RUN_YARDS):
    """One bounded bag step per member; all prices and stock come from the world."""
    inventory = {m.name: m for m in containers}
    steps, notes = {}, []
    for member in sorted(members, key=lambda m: m.name):
        bags = inventory.get(member.name)
        if bags is None:
            continue
        source = guildjobs.source_for(guildjobs.BAG_ACTION, member.name)
        if equip_eligible(member):
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
        if not eligible(member):
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

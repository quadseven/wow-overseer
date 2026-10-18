"""Guild members put on what they already carry (guild equip pass).

The family's own pass (`bridge._equip_upgrades`) names five characters, so a
guild member carrying an upgrade, or leaving a slot empty beside a carried
piece, was never asked to wear it. What is pinned here: the guild adapter
equips only what a member already owns, judges each member alone (no party
role, no hand-off to a guildmate), leaves the family to its own pass, and the
bridge writes the same kind='bot' `e` row through `_insert_equip` for both the
Alliance and the Horde guild, to members observed online.
"""

import asyncio
import pathlib
import re
import textwrap
import types
import unittest
from unittest.mock import AsyncMock, Mock

import bag_pressure

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

PALADIN, PRIEST = 2, 5
ANY_CLASS = -1
FAMILY = ["Bork", "Grog"]


def worn(name, class_id, level, **slots):
    """Equipped rows for one member, as _FAMILY_EQUIPPED_SQL returns them."""
    if not slots:
        return [
            dict(
                name=name,
                class_id=class_id,
                level=level,
                inventory_type=None,
                item_level=None,
            )
        ]
    return [
        dict(
            name=name,
            class_id=class_id,
            level=level,
            inventory_type=int(inv.lstrip("i")),
            item_level=int(ilvl),
        )
        for inv, ilvl in slots.items()
    ]


def carried(holder="Blammo", **kw):
    """One carried gear row: a mail chest at item level 50, soulbound."""
    base = dict(
        holder=holder,
        level=60,
        item_guid=9001,
        entry=7527,
        count=1,
        instance_flags=1,
        name="Cabalist Chestpiece",
        quality=2,
        sell_price=3000,
        required_level=45,
        bonding=2,
        item_class=4,
        item_subclass=3,
        item_level=50,
        allowable_class=ANY_CLASS,
        inventory_type=5,
    )
    base.update(kw)
    return base


def guild_equips(gear_rows, equipped_rows, members, family=FAMILY, keep=()):
    return bag_pressure.guild_equips(
        gear_rows, equipped_rows, members, family, keep_names=keep
    )


class TheGuildMemberPutsItOn(unittest.TestCase):
    def test_a_carried_upgrade_is_equipped(self):
        got = guild_equips([carried()], worn("Blammo", PALADIN, 60, i5=41), ["Blammo"])
        self.assertEqual(
            [(e.holder, e.name) for e in got], [("Blammo", "Cabalist Chestpiece")]
        )
        self.assertEqual(got[0].command, "e Hitem:7527:0")

    def test_an_empty_slot_is_filled(self):
        got = guild_equips([carried()], worn("Blammo", PALADIN, 60), ["Blammo"])
        self.assertEqual([(e.holder, e.worn_level) for e in got], [("Blammo", 0)])

    def test_every_member_is_judged_on_their_own_bags(self):
        rows = [
            carried(),
            carried("Hexmama", item_guid=9002, entry=7528, item_subclass=1),
        ]
        equipped = worn("Blammo", PALADIN, 60, i5=41) + worn(
            "Hexmama", PRIEST, 60, i5=41
        )
        got = guild_equips(rows, equipped, ["Blammo", "Hexmama"])
        self.assertEqual(
            {(e.holder, e.guid) for e in got}, {("Blammo", 9001), ("Hexmama", 9002)}
        )

    def test_a_piece_is_never_left_for_a_guildmate_to_claim(self):
        """A guildmate better placed to wear it does not stop the holder: the
        pass never hands anything on."""
        rows = [carried(holder="Blammo", item_level=45)]
        equipped = worn("Blammo", PALADIN, 60, i5=41) + worn("Rotgut", PALADIN, 60)
        got = guild_equips(rows, equipped, ["Blammo", "Rotgut"])
        self.assertEqual([e.holder for e in got], ["Blammo"])


class OnlyWhatTheyOwn(unittest.TestCase):
    def test_the_family_is_left_to_its_own_pass(self):
        rows = [carried(holder="Grog")]
        got = guild_equips(rows, worn("Grog", PALADIN, 60, i5=41), ["Grog"])
        self.assertEqual(got, ())

    def test_not_an_upgrade_is_left_alone(self):
        got = guild_equips(
            [carried(item_level=41)], worn("Blammo", PALADIN, 60, i5=41), ["Blammo"]
        )
        self.assertEqual(got, ())

    def test_an_unknown_member_stays(self):
        self.assertEqual(guild_equips([carried()], [], ["Blammo"]), ())

    def test_the_owners_mark_is_honoured(self):
        got = guild_equips(
            [carried()],
            worn("Blammo", PALADIN, 60, i5=41),
            ["Blammo"],
            keep=("Cabalist Chestpiece",),
        )
        self.assertEqual(got, ())


def _block(signature: str) -> str:
    src = BRIDGE.read_text()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


class TheBridgeRunsItForEveryGuild(unittest.TestCase):
    def test_the_pass_reads_the_guild_and_writes_through_insert_equip(self):
        body = _block("    async def _guild_equip_once(self")
        self.assertIn("_fetch_guild_roster", body)
        self.assertIn("bag_pressure.guild_equips(", body)
        self.assertIn("self._write_equips(", body)
        self.assertIn("m.online", body)
        self.assertIn("_insert_equip", _block("    async def _write_equips(self"))

    def test_the_share_loop_runs_it_for_this_family_and_every_other(self):
        body = _block("    async def _guild_share_loop(self")
        self.assertIn("self._guild_equip_once()", body)
        self.assertIn(
            '_for_other_families("guild equip", self._guild_equip_once)', body
        )


def _guild_pass(roster):
    """Run bridge._guild_equip_once against two online guildmates, Ezzo and
    Blammo, each carrying an upgrade, with `roster` as the enabled roster read
    (a Mock side effect when it is an exception). Returns the fake bridge, so a
    test can read what `_write_equips` was asked to write, and the log."""
    body = textwrap.dedent(_block("    async def _guild_equip_once(self"))
    reader = Mock(side_effect=roster) if isinstance(roster, Exception) else None
    namespace = {
        "asyncio": asyncio,
        "bag_pressure": bag_pressure,
        "OWNER_KEEPS": (),
        "EQUIP_MEMORY_HOURS": 24,
        "EQUIP_TRY_WINDOW_HOURS": 2,
        "_names_of": Mock(return_value=list(FAMILY)),
        "_fetch_guild_roster": Mock(
            return_value=[
                types.SimpleNamespace(name="Ezzo", online=True),
                types.SimpleNamespace(name="Blammo", online=True),
            ]
        ),
        "_fetch_surplus_gear": Mock(
            return_value=[carried("Ezzo", item_guid=9002), carried("Blammo")]
        ),
        "_fetch_family_equipped": Mock(
            return_value=worn("Ezzo", PALADIN, 60, i5=41)
            + worn("Blammo", PALADIN, 60, i5=41)
        ),
        "_fetch_shield_tanks": Mock(return_value=set()),
        "_fetch_enabled_roster_names": reader or Mock(return_value=set(roster)),
        "_equip_history": Mock(return_value=[]),
        "_level_changes": Mock(return_value={}),
        "pymysql": Mock(err=Mock(MySQLError=OSError)),
        "log": Mock(),
    }
    # Compiles a slice of our own bridge.py source, never external input.
    exec(body, namespace)  # noqa: S102
    bridge = Mock(
        _scored_equips=AsyncMock(side_effect=lambda wanted, *a, **k: tuple(wanted)),
        _write_equips=AsyncMock(),
    )
    asyncio.run(namespace["_guild_equip_once"](bridge))
    return bridge, namespace["log"]


class TheModulesGearDriveOwnsTheRoster(unittest.TestCase):
    """#1089: a roster member's gear is the module's gear drive's to put on
    (#896). The family pass already left it there; the guild pass did not, so
    another family's turn asked Ezzo to wear a staff the drive does not pick,
    the world answered with a refusal, and the third one held Ezzo "trying to
    wear" it for the whole 24 hour memory window."""

    def test_a_roster_member_is_left_to_the_gear_drive(self):
        bridge, _log = _guild_pass(roster={"Ezzo"})
        bridge._write_equips.assert_awaited_once()
        wanted = bridge._write_equips.await_args.args[0]
        self.assertEqual([e.holder for e in wanted], ["Blammo"])
        self.assertEqual(bridge._write_equips.await_args.kwargs["holders"], ["Blammo"])

    def test_a_member_off_the_roster_is_still_asked(self):
        bridge, _log = _guild_pass(roster=set())
        wanted = bridge._write_equips.await_args.args[0]
        self.assertEqual({e.holder for e in wanted}, {"Ezzo", "Blammo"})

    def test_a_failed_roster_read_writes_nothing(self):
        """Ownership unknown: nobody is asked, the same as the family pass."""
        bridge, log = _guild_pass(roster=OSError("read failed"))
        bridge._write_equips.assert_not_awaited()
        log.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()

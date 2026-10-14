"""The bridge writes only `kind='guild'` verbs mod-overseer handles (#967).

#961 made the bridge write `bg-leave <bg>` rows. The module has no handler for
that verb, every one was refused, and nothing in the tests compared what the
bridge writes with what the module reads. This does."""

import unittest

import classparty
import guildbank
import guildjobs
import pvpgear


def verb_of(command: str) -> str:
    return command.split()[0]


def an_aim():
    return pvpgear.Aim(
        "Auren", "Cave", 60, 19325, "Don Julio's Band", 5000, 0, pvpgear.BATTLEGROUNDS["wsg"]
    )


def a_member():
    return guildjobs.Member(
        name="Auren", guild="Cave", role=guildjobs.RAIDER, level=60,
        online=True, map_id=0, x=0.0, y=0.0, eligible=True,
    )  # fmt: skip


class TheGuildVerbsTheBridgeWrites(unittest.TestCase):
    def guild_commands(self):
        aim = an_aim()
        # finder-run and the tabard row are built by classes that need a whole
        # run to construct; their verbs are listed and pinned by the module.
        out = {
            "queue_command": pvpgear.queue_command(aim),
            "party up": classparty.up_command(["Bel", "Cor"]),
            "party disband": classparty.DISBAND,
            "bank deposit-item": guildbank.format_item_deposit(item_guid=7, tab=0),
            "bank deposit-item entry": guildbank.format_item_deposit(entry=7, tab=2),
            "bank withdraw-item": guildbank.format_item_withdraw(item_guid=7, tab=1),
            "invite": "invite Bel",
        }
        for kind in (pvpgear.QUEUE, pvpgear.BUY):
            step = guildjobs.pvp_step(a_member(), aim, pvpgear.Move(kind, "x"), 0)
            for row in step.rows:
                if row.kind == "guild":
                    out["pvp_step %s" % kind] = row.command
        return out

    def test_every_guild_command_starts_with_a_verb_the_module_handles(self):
        for label, command in self.guild_commands().items():
            with self.subTest(label):
                self.assertIn(verb_of(command), pvpgear.MODULE_GUILD_VERBS, command)

    def test_leave_stays_defined_but_unlisted(self):
        self.assertEqual("bg-leave wsg", pvpgear.leave_command(an_aim()))
        self.assertNotIn("bg-leave", pvpgear.MODULE_GUILD_VERBS)


if __name__ == "__main__":
    unittest.main()

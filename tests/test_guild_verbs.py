"""The bridge writes only the kind='guild' verbs mod-overseer handles (#967).

#961 made the guild jobs write `bg-leave <bg>` rows, a verb no module build
handles: each reached DoGuild, which refused it, and the refusal was counted as
a leave. Every one of #961's tests passed, because nothing checked a guild verb
the bridge writes against the module. This does, two ways:

  * every place in the bridge that writes a guild row is found in the source
    (a `Row("guild", ...)`, an `_insert_guild` call, a raw INSERT of kind
    'guild'), and must be one this file knows how to build a sample for;
  * every sample, built by the bridge's own builder wherever one exists,
    starts with a verb in guildcorps.MODULE_GUILD_VERBS.

So a new guild writer, or `pvpgear.leave_command` written again, fails here
until the module handles its verb and the verb is listed.
"""

import ast
import pathlib
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import bank  # noqa: E402
import classparty  # noqa: E402
import guildbank  # noqa: E402
import guildcorps  # noqa: E402
import guildfund  # noqa: E402
import guildjobs  # noqa: E402
import guildrun  # noqa: E402
import pvpgear  # noqa: E402
import tabard  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Not bridge code: the suites, the module's own checkout, the game addons.
SKIP = ("tests", "mod-overseer", "wow-addons")


def _aim(key="wsg"):
    return pvpgear.Aim(
        "MemberA", "GuildA", 60, 19325, "Test item", 5000, 0,
        pvpgear.BATTLEGROUNDS[key], "Test vendor", "Alliance",
    )  # fmt: skip


def _member():
    return guildjobs.Member(
        name="MemberA", guild="GuildA", role=guildjobs.RAIDER, level=60,
        online=True, map_id=0, x=0.0, y=0.0, eligible=True,
    )  # fmt: skip


def _composition():
    # Only the names reach the command.
    m = types.SimpleNamespace
    return guildrun.Composition(
        m(name="TankA"),
        m(name="HealerA"),
        (m(name="DamageA"), m(name="DamageB"), m(name="DamageC")),
    )  # pyright: ignore[reportArgumentType]


def _guild_deposit():
    return bank.Move(
        "MemberA", bank.DEPOSIT, 77, "Test item", 20, "kept", bank.GUILD, 0
    )


def _setup():
    actions = guildbank.plan_setup(
        leader="MemberA", purchased_tabs=1, rank_ids=(1, 2), tab_names={0: "x"}
    )
    return [a.command for a in actions]


# (file, enclosing function, the command expression as written) -> the
# commands that writer can put in a guild row. Built by the bridge's own
# builder where it has one; the planners that format their command inline
# (recruit, team sync, the deposits) are given in the shape they write.
WRITERS = {
    ("guildjobs.py", "pvp_step", "pvpgear.queue_command(aim)"): lambda: [
        pvpgear.queue_command(_aim(k)) for k in pvpgear.BATTLEGROUNDS
    ],
    ("bridge.py", "_class_party_form", "classparty.up_command(run.helpers)"): lambda: [
        classparty.up_command(["HealerA", "DamageA"])
    ],
    ("bridge.py", "_class_party_disband_row", "classparty.DISBAND"): lambda: [
        classparty.DISBAND
    ],
    ("bridge.py", "_start_guild_run", "comp.command(door.keyword)"): lambda: [
        _composition().command("dm")
    ],
    (
        "bridge.py",
        "_start_social_run",
        "comp.command(door.keyword) + guildpug.pug_tail(form.pugs)",
    ): lambda: [_composition().command("dm")],
    ("bridge.py", "_tabard_once", "design.command()"): lambda: [
        tabard.Design({f.name: 1 for f in tabard.FIELDS}, {}, "MemberA").command()
    ],
    ("bridge.py", "_fund_withdraw", "guildfund.withdraw_command(plan.withdraw)"): (
        lambda: [guildfund.withdraw_command(5000)]
    ),
    ("bridge.py", "_raid_supply_market", "'bank withdraw %d' % copper"): lambda: [
        "bank withdraw %d" % 5000
    ],
    ("bridge.py", "_guild_bank_once", "action.command"): _setup,
    ("bridge.py", "_guild_bank_once", "command"): lambda: ["bank deposit 5000"],
    ("bridge.py", "_guild_bank_passing_once", "command"): lambda: ["bank deposit 5000"],
    ("bridge.py", "_queue_guild_items", "command"): lambda: [
        bank.command(_guild_deposit())
    ],
    ("bridge.py", "_queue_guild_withdrawals", "command"): lambda: [
        guildbank.format_item_withdraw(item_guid=77, tab=0)
    ],
    ("bridge.py", "_recruit_once", "action.command"): lambda: [
        "shortlist 5",
        "invite MemberA",
    ],
    # teamsync's "rename" and "reset" go through other kinds, not here.
    ("bridge.py", "_team_sync_once", "action.kind"): lambda: ["invite", "remove"],
    # The writer itself: its callers are the rows above.
    ("bridge.py", "_insert_guild", "command"): lambda: [],
}


def _command_of(call: ast.Call):
    """The command expression of a call that writes a guild row, else None."""
    func, args = ast.unparse(call.func), call.args
    if func.split(".")[-1] == "Row" and len(args) > 1:
        if isinstance(args[0], ast.Constant) and args[0].value == "guild":
            return args[1]
    if (
        len(args) > 2
        and isinstance(args[0], ast.Name)
        and args[0].id == "_insert_guild"
    ):
        return args[2]
    if func == "_insert_guild" and len(args) > 1:
        return args[1]
    if func.endswith("execute") and len(args) > 1 and isinstance(args[1], ast.Tuple):
        sql = ast.unparse(args[0])
        if "INSERT INTO overseer_command" in sql and "'guild'" in sql:
            return args[1].elts[1]
    return None


def guild_writers(path: pathlib.Path) -> set:
    """(file, enclosing function, command expression) for each guild row write."""
    found = set()

    def visit(node, function):
        for child in ast.iter_child_nodes(node):
            inner = function
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = child.name
            if isinstance(child, ast.Call):
                command = _command_of(child)
                if command is not None:
                    found.add((path.name, function, ast.unparse(command)))
            visit(child, inner)

    visit(ast.parse(path.read_text(encoding="utf-8"), str(path)), "")
    return found


def all_guild_writers() -> set:
    found = set()
    for path in sorted(ROOT.rglob("*.py")):
        if path.relative_to(ROOT).parts[0] not in SKIP:
            found |= guild_writers(path)
    return found


def verb(command: str) -> str:
    return command.split(" ", 1)[0]


class EveryGuildRowIsAModuleVerb(unittest.TestCase):
    def test_every_guild_writer_is_known(self):
        found = all_guild_writers()
        self.assertEqual(
            set(),
            found - set(WRITERS),
            "a guild row writer this file does not know: add it to WRITERS "
            "with the commands it can write",
        )

    def test_no_known_writer_is_stale(self):
        self.assertEqual(set(), set(WRITERS) - all_guild_writers())

    def test_every_built_command_starts_with_a_module_verb(self):
        for writer, build in WRITERS.items():
            for command in build():
                with self.subTest(writer=writer, command=command):
                    self.assertIn(verb(command), guildcorps.MODULE_GUILD_VERBS)

    def test_every_pvp_move_writes_only_module_verbs(self):
        # "leave" is the kind #961 gave its leave move: a step built for it
        # again must not write a guild row the module refuses.
        kinds = (
            pvpgear.INSIDE, pvpgear.CARRIED, pvpgear.BUY, pvpgear.WAITING,
            pvpgear.QUEUE, pvpgear.GATHERING, pvpgear.COOLING, "leave",
        )  # fmt: skip
        for kind in kinds:
            step = guildjobs.pvp_step(_member(), _aim(), pvpgear.Move(kind, ""), 0)
            rows = (step.rows + ((step.walk,) if step.walk else ())) if step else ()
            for row in rows:
                if row.kind == "guild":
                    with self.subTest(kind=kind, command=row.command):
                        self.assertIn(verb(row.command), guildcorps.MODULE_GUILD_VERBS)

    def test_bg_leave_is_not_a_module_verb(self):
        self.assertNotIn(
            verb(pvpgear.leave_command(_aim())), guildcorps.MODULE_GUILD_VERBS
        )


class TheScanFindsAGuildRow(unittest.TestCase):
    """The scan reads each form a guild row is written in."""

    def scan(self, source):
        commands = (
            _command_of(n)
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call)
        )
        return {ast.unparse(c) for c in commands if c is not None}

    def test_a_step_row(self):
        source = 'guildcorps.Row(\n    "guild", pvpgear.leave_command(aim), "", s\n)'
        self.assertEqual({"pvpgear.leave_command(aim)"}, self.scan(source))

    def test_an_insert_guild_call(self):
        source = "asyncio.to_thread(_insert_guild, who, 'bg-leave wsg', 'pvp')"
        self.assertEqual({"'bg-leave wsg'"}, self.scan(source))

    def test_a_raw_insert(self):
        source = (
            'cur.execute("INSERT INTO overseer_command (target_name, command, '
            "kind, source) VALUES (%s, %s, 'guild', %s)\", (who, cmd, src))"
        )
        self.assertEqual({"cmd"}, self.scan(source))

    def test_another_kind_is_not_a_guild_row(self):
        self.assertEqual(set(), self.scan('guildcorps.Row("buy", "entry:1", "", s)'))


class GuildCharterDesign(unittest.TestCase):
    """Keep the charter alternative grounded in module behavior and a test plan."""

    def test_charter_document_records_blocker_and_verification_steps(self):
        from pathlib import Path

        document = Path("mod-overseer/docs/design/guild-charter-founding.md")
        text = document.read_text()
        for required in (
            "UNIT_NPC_FLAG_PETITIONER",
            "CONFIG_MIN_PETITION_SIGNS",
            "CMSG_PETITION_SIGN",
            "5863",
            "guild_member",
            "charter route remains a documented alternative",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()

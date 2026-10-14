"""Every kind='guild' row the bridge writes starts with a verb mod-overseer
handles (#967).

#961 wrote `bg-leave <bg>` rows that the module has no handler for. Every
leave was refused, the members stayed queued in the game, and the refused rows
still put them in the leave cooldown. Its tests all passed, because nothing
checked that a verb the bridge writes exists in the module.

Two halves. The builders: each command a guild row can carry, built by the
code that builds it, starts with a verb in guildcorps.GUILD_VERBS. The write
sites: every place in the bridge's own sources that writes a guild row
(guildcorps.Row("guild", ...), _insert_guild through asyncio.to_thread, and
the raw INSERTs of the guild runs) names its command with an expression this
file knows, and so has a builder checked above. A new write site, or one that
writes pvpgear.leave_command again, fails here until its verb is one the
module handles.
"""

import ast
import pathlib
import types
import unittest
from typing import Any

import bankforecast
import classparty
import guildbank
import guildcorps
import guildfund
import guildpug
import guildrun
import pvpgear
import recruit
import tabard

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _aim():
    return pvpgear.Aim(
        "Auren", "Cave", 60, 19325, "Don Julio's Band", 5000, 0, pvpgear.AV
    )


def _composition():
    def one(name):
        return types.SimpleNamespace(name=name)

    comp: Any = types.SimpleNamespace(healer=one("Mend"), dps=(one("Ash"), one("Bo")))
    return guildrun.Composition.command(comp, "rfc")


def _recruit(**kw):
    base: dict[str, Any] = dict(
        actors=["Master"], shortlist=[], shortlist_age_minutes=None,
        shortlist_asked_minutes_ago=None, asked=set(),
        minutes_since_last_invite=None, member_count=1, target_size=10,
    )  # fmt: skip
    base.update(kw)
    return recruit.plan_recruit(**base).command


def _withdrawal():
    stack = types.SimpleNamespace(guid=7, tab=1)
    return bankforecast.Withdrawal.command.fget(types.SimpleNamespace(stack=stack))


# Each guild write site's command expression, as written at the site, and
# the commands it can carry, built by the builder that site calls.
KNOWN = {
    "pvpgear.queue_command(aim)": lambda: [pvpgear.queue_command(_aim())],
    "classparty.up_command(run.helpers)": lambda: [classparty.up_command(["Ash"])],
    "classparty.DISBAND": lambda: [classparty.DISBAND],
    # bridge.py's tabard pass: tabard.Design.command.
    "design.command()": lambda: [
        tabard.Design({f.name: f.low for f in tabard.FIELDS}, {}, "Master").command()
    ],
    "guildfund.withdraw_command(plan.withdraw)": lambda: [
        guildfund.withdraw_command(100)
    ],
    # bridge.py's raid supply withdrawal, written in place.
    "'bank withdraw %d' % copper": lambda: ["bank withdraw %d" % 100],
    # The guild bank's setup (guildbank.plan_setup) and the recruit sweep
    # (recruit.plan_recruit) both hand over `action.command`.
    "action.command": lambda: (
        [
            a.command
            for a in guildbank.plan_setup(
                leader="Master", purchased_tabs=1, rank_ids=(2,), tab_names={}
            )
        ]
        + [
            _recruit(),
            _recruit(
                shortlist=["Zed"],
                shortlist_age_minutes=1,
                shortlist_asked_minutes_ago=1,
            ),
        ]
    ),
    # The money deposits are written in place in bridge.py; a kept item is
    # bank.command of a GUILD move, which is guildbank.format_item_deposit; a
    # vault stack is bankforecast.Withdrawal.command.
    "command": lambda: [
        "bank deposit %d" % 100,
        guildbank.format_item_deposit(item_guid=7),
        guildbank.format_item_deposit(item_guid=7, tab=1),
        _withdrawal(),
    ],
    # The team sync's guild rows: a teamsync.Action that is neither a rename
    # nor a reset, which go to other kinds.
    "action.kind": lambda: ["invite", "remove"],
    # The guild runs' raw INSERTs (bridge.py), targeted at the tank.
    "comp.command(door.keyword)": lambda: [_composition()],
    "comp.command(door.keyword) + guildpug.pug_tail(form.pugs)": lambda: [
        _composition() + guildpug.pug_tail(("Pug",))
    ],
}


def _verb(command: str) -> str:
    words = command.split()
    return words[0] if words else ""


def _sql_text(node) -> str:
    """The text of a string literal, or of adjacent literals Python joined."""
    return node.value if isinstance(node, ast.Constant) else ""


class _Sites(ast.NodeVisitor):
    """(file, line, command expression) of every guild row a source writes."""

    def __init__(self, path):
        self.path, self.found, self._in_insert_guild = path, [], False

    def visit_FunctionDef(self, node):
        # _insert_guild is the writer its callers below hand their command to.
        inside = self._in_insert_guild
        self._in_insert_guild = inside or node.name == "_insert_guild"
        self.generic_visit(node)
        self._in_insert_guild = inside

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        func, args = ast.unparse(node.func), node.args
        if (
            func.split(".")[-1] == "Row"
            and len(args) > 1
            and isinstance(args[0], ast.Constant)
            and args[0].value == "guild"
        ):
            self._add(node, args[1])
        elif (
            func.endswith("to_thread")
            and args
            and ast.unparse(args[0]) == "_insert_guild"
        ):
            self._add(node, args[2])
        elif func == "_insert_guild" and len(args) > 1:
            self._add(node, args[1])
        elif (
            func.endswith(".execute")
            and len(args) > 1
            and "INSERT INTO overseer_command" in _sql_text(args[0])
            and "'guild'" in _sql_text(args[0])
            and not self._in_insert_guild
            and isinstance(args[1], ast.Tuple)
        ):
            self._add(node, args[1].elts[1])
        self.generic_visit(node)

    def _add(self, node, expr):
        self.found.append((self.path.name, node.lineno, ast.unparse(expr)))


def guild_write_sites():
    sites = []
    for path in sorted(ROOT.glob("*.py")):
        visitor = _Sites(path)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), str(path)))
        sites.extend(visitor.found)
    return sites


class TheBuilders(unittest.TestCase):
    def test_every_guild_command_starts_with_a_module_verb(self):
        for site, build in KNOWN.items():
            for command in build():
                with self.subTest(site=site, command=command):
                    self.assertIn(_verb(command), guildcorps.GUILD_VERBS)

    def test_the_leave_the_module_never_handled_is_not_listed(self):
        self.assertEqual("bg-leave av", pvpgear.leave_command(_aim()))
        self.assertNotIn(_verb(pvpgear.leave_command(_aim())), guildcorps.GUILD_VERBS)


class TheWriteSites(unittest.TestCase):
    def test_every_guild_write_site_has_a_checked_builder(self):
        sites = guild_write_sites()
        self.assertTrue(sites, "no guild write site found: the scan is broken")
        for path, line, expr in sites:
            with self.subTest(at="%s:%d" % (path, line)):
                self.assertTrue(
                    expr in KNOWN,
                    "%s:%d writes a kind='guild' row with %r, which this test "
                    "does not know. Add it to KNOWN with the commands it can "
                    "carry; its verb must be one mod-overseer handles "
                    "(guildcorps.GUILD_VERBS)." % (path, line, expr),
                )  # fmt: skip

    def test_every_known_site_is_still_written(self):
        written = {expr for _, _, expr in guild_write_sites()}
        self.assertEqual(set(), set(KNOWN) - written)

    def test_nothing_writes_a_battleground_leave(self):
        exprs = [expr for _, _, expr in guild_write_sites()]
        self.assertFalse([e for e in exprs if "leave_command" in e])


if __name__ == "__main__":
    unittest.main()

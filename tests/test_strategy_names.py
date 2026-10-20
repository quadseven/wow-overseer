"""Every strategy the bridge asks for exists in the pinned build (#1298).

Engine::addStrategy does nothing when no strategy context has a creator for
the name, and the bot still accepts the command. So a strategy upstream
deletes or renames keeps being sent, keeps being accepted, and changes
nothing. That is what `co +flee` did from roll 65 (mod-playerbots 40884e9c,
where upstream #2825 had deleted the flee strategy) until this test existed:
the module's read-back logged "CHANGED NOTHING" for every family member every
ten minutes, and nothing on this side noticed.

The names come from tests/fixtures/strategy_names.txt, which
tools/gen_strategy_names.py writes from the pinned mod-playerbots tree with
the deploy repo's patches applied. When the pin moves, regenerate it; this
test then names every command the new build no longer understands.
"""

from __future__ import annotations

import itertools
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import goals  # noqa: E402
import voice  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "strategy_names.txt"
ENGINES = ("nc", "co")


def _fixture():
    """Return (module sha, names every bot has, {class: names})."""
    sha, shared, by_class = "", set(), {}
    for line in FIXTURE.read_text(encoding="ascii").splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("module "):
            sha = line.split()[1]
            continue
        scope, name = line.split("\t", 1)
        if scope == "all":
            shared.add(name)
        else:
            by_class.setdefault(scope, set()).add(name)
    return sha, shared, by_class


def _names(command: str) -> list:
    """`nc +grind,-loot` -> ['grind', 'loot']; [] for a non-strategy command."""
    engine, _, rest = command.partition(" ")
    if engine not in ENGINES:
        return []
    return [
        item.strip().lstrip("+-~").strip() for item in rest.split(",") if item.strip()
    ]


def _bridge_commands() -> set:
    """Every strategy command the bridge sends on its own account."""
    commands = set(goals.GATHER_STRATEGIES)
    commands.add(goals.strategy_for({"kind": "level"}))
    commands.update((goals.LIFE_STRATEGY, goals.GRIND_OFF, goals.RETREAT_STRATEGY))
    flags = ("leads", "aimed", "travelling", "gathering", "in_town", "campaign")
    for values in itertools.product((False, True), repeat=len(flags)):
        commands.update(goals.life_strategies(**dict(zip(flags, values))))
    # The vocabulary the inner voice may pick verbatim is sent as-is too.
    commands.update(c for c in voice.VOCABULARY if c.partition(" ")[0] in ENGINES)
    return commands


class TheFixtureIsReadable(unittest.TestCase):
    def test_it_names_the_module_it_was_read_from(self):
        sha, _, _ = _fixture()
        self.assertRegex(sha, r"^[0-9a-f]{40}$")

    def test_it_holds_the_shared_strategies_the_bridge_has_always_used(self):
        """A generator that silently read nothing would pass every check below."""
        _, shared, _ = _fixture()
        for name in ("new rpg", "grind", "follow", "loot", "gather"):
            self.assertIn(name, shared)

    def test_flee_is_gone_from_the_pinned_build(self):
        """Upstream #2825. If this ever fails the pin moved back past it."""
        _, shared, by_class = _fixture()
        self.assertNotIn("flee", shared.union(*by_class.values()))


class EveryStrategyTheBridgeSendsExists(unittest.TestCase):
    def test_the_command_parser_reads_lists_and_signs(self):
        self.assertEqual(_names("nc +grind,-loot"), ["grind", "loot"])
        self.assertEqual(_names("co +retreat from danger"), ["retreat from danger"])
        self.assertEqual(_names("follow"), [])

    def test_every_name_is_in_a_context_every_member_carries(self):
        """Shared contexts only: the family mixes classes, so a class-only
        strategy sent to all of them is a no-op for most."""
        _, shared, _ = _fixture()
        commands = _bridge_commands()
        self.assertTrue(commands)
        for command in sorted(commands):
            for name in _names(command):
                with self.subTest(command=command):
                    self.assertTrue(
                        name in shared,
                        f"{command!r} names no strategy in the pinned build",
                    )

    def test_self_preservation_rides_the_patched_retreat(self):
        """Patch 0007's RetreatFromDangerStrategy: its critical-health trigger
        needs no combat target, so it works on the combat engine too."""
        self.assertEqual(goals.RETREAT_STRATEGY, "co +retreat from danger")


if __name__ == "__main__":
    unittest.main()

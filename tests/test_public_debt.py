"""Committed scripts and docs carry no deployment names (#1847).

This repo is public and reusable (AGENTS.md). The regeneration recipes in
`tools/` and the ship procedure in `docs/ROLLS.md` used to spell out one
deployment's namespace, database pod and agent ServiceAccount in every
`kubectl` line, two docstrings pointed into a private manifests tree by
relative path, and `overhear.py` quoted the operator. These tests keep each
of those from coming back without naming the old values themselves: every
`kubectl` namespace, exec target, copy source and token subject must be a
shell placeholder, and the docs must say what each placeholder means.

They also pin the output directories: AGENTS.md names the producer and
consumer of `logs/review-ledger.jsonl`, no report under `reports/` is
tracked, and `.gitignore` keeps new output in both directories local.
"""

import ast
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

KUBECTL_FILES = (
    "docs/ROLLS.md",
    "tools/craftbook_from_dbc.py",
    "tools/race_spells_from_dbc.py",
    "tools/raid_consumables_from_dbc.py",
    "tools/spell_bands_from_dbc.py",
    "tools/spell_focus_from_dbc.py",
    "tools/seed_roster.py",
    "tools/gather_bands_from_dbc.py",
    "tools/item_extended_cost_from_dbc.py",
    "tools/taxi_nodes_from_dbc.py",
)

# A value a reader supplies: `$NAME`, `"$NAME"`, `"${NAME#pod/}"` or `<name>`.
PLACEHOLDER = r"""(?:"?\$\{?[A-Z_]+(?![A-Za-z0-9_])|<[^>]+>)"""
# The whole value is one placeholder: `$NAME`, `"$NAME"`, `"${NAME}"` or `<name>`.
# A brace or a quote opens only with its pair.
WHOLE_PLACEHOLDER = (
    r"""(?:(?P<quote>")?\$(?P<brace>\{)?(?P<name>[A-Z_]+)(?(brace)\})(?(quote)")"""
    r"""|<[^>]+>)"""
)
# The names docs/ROLLS.md explains before its steps.
ROLLS_PLACEHOLDERS = ("NAMESPACE", "DB_POD", "READER_SA", "MANIFESTS_DIR")


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _kubectl_commands(text):
    """Each kubectl command, with backslash continuations joined."""
    joined = re.sub(r"\\\\?\s*\n\s*", " ", text)
    return re.findall(r"kubectl\s+[^`\n]*", joined)


def _docstrings(source):
    tree = ast.parse(source)
    nodes = [tree] + [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    return [doc for doc in (ast.get_docstring(n) for n in nodes) if doc]


class WholePlaceholderShape(unittest.TestCase):
    def test_accepts_each_complete_form(self):
        for value in ("$NAME", '"$NAME"', "${NAME}", '"${NAME}"', "<name>"):
            with self.subTest(value=value):
                self.assertIsNotNone(re.fullmatch(WHOLE_PLACEHOLDER, value))

    def test_refuses_an_unpaired_brace_or_quote(self):
        for value in ("${NAME", "$NAME}", '"$NAME', '$NAME"', "name"):
            with self.subTest(value=value):
                self.assertIsNone(re.fullmatch(WHOLE_PLACEHOLDER, value))


class KubectlLinesUsePlaceholders(unittest.TestCase):
    def test_every_namespace_is_a_placeholder(self):
        for rel in KUBECTL_FILES:
            for command in _kubectl_commands(_read(rel)):
                for value in re.findall(r"\s-n\s+(\S+)", command):
                    with self.subTest(file=rel, command=command):
                        found = re.fullmatch(WHOLE_PLACEHOLDER, value)
                        self.assertIsNotNone(found, value)
                        self.assertIn(found.group("name"), (None, "NAMESPACE"))

    def test_every_exec_target_and_copy_source_is_a_placeholder(self):
        for rel in KUBECTL_FILES:
            for command in _kubectl_commands(_read(rel)):
                verb = re.search(r"\s(exec|cp)\s", command)
                if not verb:
                    continue
                rest = command[verb.end() :]
                words = [w for w in rest.split() if not w.startswith("-")]
                # `-n X` and `-c X` take a value; drop those values too.
                for flag in re.findall(r"(?:^|\s)-[nc]\s+(\S+)", rest):
                    if flag in words:
                        words.remove(flag)
                target = words[0] if words else ""
                with self.subTest(file=rel, command=command):
                    # `deploy/<name>` names this product's own workload, and
                    # `...` is prose eliding a command shown in full above.
                    self.assertRegex(
                        target, r"^(?:deploy/\S+|\.\.\.|" + PLACEHOLDER + ")"
                    )

    def test_every_token_subject_and_render_path_is_a_placeholder(self):
        for rel in KUBECTL_FILES:
            for command in _kubectl_commands(_read(rel)):
                found = re.search(r"(?:create token|kustomize)\s+(\S+)", command)
                if found:
                    with self.subTest(file=rel, command=command):
                        whole = re.fullmatch(WHOLE_PLACEHOLDER, found.group(1))
                        self.assertIsNotNone(whole, found.group(1))
                        self.assertIn(whole.group("name"), (None,) + ROLLS_PLACEHOLDERS)

    def test_the_rolls_doc_explains_each_placeholder(self):
        text = _read("docs/ROLLS.md")
        for name in ROLLS_PLACEHOLDERS:
            with self.subTest(placeholder=name):
                self.assertIn(f"`${name}`", text.split("## 1. Steps", 1)[0])

    def test_the_rolls_doc_uses_only_explained_placeholders(self):
        used = set()
        for command in _kubectl_commands(_read("docs/ROLLS.md")):
            used |= set(re.findall(r"\$\{?([A-Z_]+)", command))
        self.assertEqual(sorted(used - set(ROLLS_PLACEHOLDERS)), [])

    def test_each_tool_explains_its_placeholders(self):
        # A name the recipe assigns itself (`POD=$(...)`) or reads inside the
        # pod (the database's own root password variable) is not the reader's.
        for rel in KUBECTL_FILES[1:]:
            text = _read(rel)
            supplied = set()
            for command in _kubectl_commands(text):
                supplied |= set(re.findall(r"\$\{?([A-Z_]+)", command))
            supplied -= set(re.findall(r"\b([A-Z_]+)=\$\(", text))
            supplied.discard("MYSQL_ROOT_PASSWORD")
            self.assertIn("NAMESPACE", supplied, rel)
            for name in sorted(supplied):
                with self.subTest(file=rel, placeholder=name):
                    self.assertIn(f"`${name}` is ", text)


class NoPrivatePathsOrQuotes(unittest.TestCase):
    def test_no_relative_path_into_a_manifests_tree(self):
        # Docstrings and comments alike: basepath.py held one in a comment.
        for rel in ("cast.py", "tools/seed_roster.py", "basepath.py"):
            with self.subTest(file=rel):
                self.assertIsNone(re.search(r"(\.\./)+\S*manifests", _read(rel)))

    def test_overhear_docstrings_quote_no_chat_line(self):
        for doc in _docstrings(_read("overhear.py")):
            quoted = re.findall(r'"([^"<]{20,})"', doc)
            self.assertEqual(quoted, [], "a docstring quotes a typed chat line")

    def test_overhear_docstrings_use_the_role_word(self):
        for doc in _docstrings(_read("overhear.py")):
            self.assertIsNone(
                re.search(r"\b(?:he|his|him)\b", doc, re.I),
                "say the operator, not a pronoun that guesses at a person",
            )


class TrackedOutputIsDocumented(unittest.TestCase):
    def test_agents_md_names_the_ledger_producer_and_consumer(self):
        own = _read("AGENTS.md").split("<!-- repo-specific below -->", 1)[1]
        line = next(
            (ln for ln in own.splitlines() if "`logs/review-ledger.jsonl`" in ln), ""
        )
        self.assertIn("Producer:", line)
        self.assertIn("Consumer:", line)
        self.assertIn("tools/realm_state_audit.py", own)

    def test_no_report_is_tracked(self):
        tracked = subprocess.run(
            ["git", "ls-files", "reports"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        self.assertEqual(tracked, [], "reports have no reader; keep them local")

    def test_gitignore_keeps_new_output_local(self):
        lines = _read(".gitignore").splitlines()
        for directory in ("logs/", "reports/"):
            with self.subTest(directory=directory):
                self.assertIn(directory, lines)


if __name__ == "__main__":
    unittest.main()

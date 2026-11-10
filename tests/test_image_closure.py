"""The image ships the entry-point import closure and every required data file."""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"


def _copied_image_files() -> dict[pathlib.Path, pathlib.PurePosixPath]:
    copied: dict[pathlib.Path, pathlib.PurePosixPath] = {}
    instruction: list[str] = []
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not instruction and not stripped.upper().startswith("COPY "):
            continue
        instruction.append(stripped)
        if instruction[-1].endswith("\\"):
            instruction[-1] = instruction[-1][:-1].rstrip()
            continue
        copied.update(_copy_instruction_entries(instruction))
        instruction.clear()
    return copied


def _copy_instruction_entries(
    instruction: list[str],
) -> dict[pathlib.Path, pathlib.PurePosixPath]:
    parts = shlex.split(" ".join(instruction))
    if len(parts) < 3:
        return {}
    sources = parts[1:-1]
    while sources and sources[0].startswith("--"):
        sources = sources[1:]
    if not sources or any(part.startswith("--from") for part in parts[1:-1]):
        return {}
    destination = pathlib.PurePosixPath(parts[-1])
    directory = parts[-1].endswith("/") or len(sources) > 1
    entries: dict[pathlib.Path, pathlib.PurePosixPath] = {}
    for source in sources:
        entries.update(_copy_source_entries(source, destination, directory))
    return entries


def _copy_source_entries(
    source: str,
    destination: pathlib.PurePosixPath,
    directory: bool,
) -> dict[pathlib.Path, pathlib.PurePosixPath]:
    path = ROOT / source
    if path.is_dir():
        return {
            child.relative_to(ROOT): destination / child.relative_to(path)
            for child in path.rglob("*")
            if child.is_file()
        }
    if not path.is_file():
        return {}
    target = destination / path.name if directory else destination
    return {path.relative_to(ROOT): target}


def _local_module(name: str) -> pathlib.Path | None:
    base = ROOT.joinpath(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    package = path.relative_to(ROOT).with_suffix("").parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parent = package[: len(package) - node.level + 1]
                module_parts = node.module.split(".") if node.module else ()
                base = ".".join((*parent, *module_parts))
            else:
                base = node.module or ""
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _entrypoint_closure() -> set[pathlib.Path]:
    # apiv2 imports its endpoint modules by package scan at startup, so those
    # are part of the runtime closure even though they are not direct imports.
    todo = [ROOT / "bridge.py", ROOT / "map_server.py"]
    todo.extend(sorted((ROOT / "apiv2").glob("*.py")))
    visited: set[pathlib.Path] = set()
    while todo:
        path = todo.pop()
        if path in visited:
            continue
        visited.add(path)
        for name in _imports(path):
            local = _local_module(name)
            if local is not None:
                todo.append(local)
    return {path.relative_to(ROOT) for path in visited}


def _served_files() -> set[pathlib.Path]:
    tree = ast.parse((ROOT / "map_server.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_send_file"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value != "app file"
        ):
            names.add(pathlib.Path(node.args[0].value))
    return names


def _per_module_dockerfile_assertions() -> list[str]:
    offenders = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr not in {"assertIn", "assertNotIn"} or len(node.args) < 2:
                continue
            needle = node.args[0]
            if not isinstance(needle, ast.Constant) or not isinstance(
                needle.value, str
            ):
                continue
            if not re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\.py\b", needle.value):
                continue
            target = ast.dump(node.args[1]).lower()
            if "dockerfile" in target:
                offenders.append(path.relative_to(ROOT).as_posix())
                break
    return offenders


def _world_data_paths(path: pathlib.Path) -> set[pathlib.Path]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=str(path))

    def parts(node: ast.expr) -> list[str]:
        if isinstance(node, ast.Name) and node.id == "DATA_ROOT":
            return []
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return parts(node.left) + parts(node.right)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        return []

    paths = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        if any(
            isinstance(child, ast.Name) and child.id == "DATA_ROOT"
            for child in ast.walk(node)
        ):
            names = parts(node)
            if names:
                paths.add(pathlib.Path(*names))
    return paths


class ImageClosureTests(unittest.TestCase):
    def test_relative_imports_resolve_from_the_module_package(self):
        imports = _imports(ROOT / "apiv2" / "classchain.py")

        self.assertIn("apiv2.members", imports)
        self.assertIn("apiv2._scope", imports)
        self.assertEqual(_local_module("apiv2.members"), ROOT / "apiv2" / "members.py")

    def test_entrypoint_import_closure_is_in_the_copy_list(self):
        copied = _copied_image_files()
        closure = _entrypoint_closure()
        missing = sorted(
            str(path)
            for path in closure
            if copied.get(path) != pathlib.PurePosixPath("/app") / path.as_posix()
        )
        self.assertEqual(
            missing, [], "entrypoint imports missing from image: " + ", ".join(missing)
        )
        required = set().union(*(_world_data_paths(path) for path in closure))
        required.update(_served_files())
        absent = []
        for source in required:
            target = ROOT / source
            if target.is_file():
                expected = pathlib.PurePosixPath("/app") / source.as_posix()
                if copied.get(source) != expected:
                    absent.append(str(source))
            elif target.is_dir():
                contents = {
                    path.relative_to(ROOT)
                    for path in target.rglob("*")
                    if path.is_file()
                }
                absent.extend(
                    str(path)
                    for path in sorted(contents)
                    if copied.get(path)
                    != pathlib.PurePosixPath("/app") / path.as_posix()
                )
            else:
                absent.append(str(source))
        absent.sort()
        self.assertEqual(
            absent,
            [],
            "entrypoint data files missing from image: " + ", ".join(absent),
        )

    def test_every_shipped_module_imports_and_every_data_file_opens(self):
        copied = _copied_image_files()
        module_paths = sorted(
            path for path in copied if path.suffix == ".py" and path.parts[0] != "app"
        )
        data_paths = sorted(
            {
                path
                for path in copied
                if path.suffix == ".json" or path.parts[0] == "data"
            }
            | _served_files()
        )

        module_names = []
        for path in module_paths:
            parts = path.with_suffix("").parts
            module_names.append(
                ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            )
        code = """
import importlib
import json
import sys
import types
from _stub_modules import PYMYSQL, stub_modules

discord = types.ModuleType('discord')
discord.Client = type('Client', (), {})
with stub_modules(discord=discord, pymysql=PYMYSQL):
    for name in json.loads(sys.argv[1]):
        importlib.import_module(name)
"""
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as temporary:
            image_root = pathlib.Path(temporary)
            for source, target in copied.items():
                destination = image_root / target.relative_to("/")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / source).read_bytes())
            env["PYTHONPATH"] = os.pathsep.join(
                (str(ROOT / "tests"), str(image_root / "app"))
            )
            result = subprocess.run(
                [sys.executable, "-B", "-c", code, json.dumps(module_names)],
                cwd=image_root / "app",
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for path in data_paths:
                image_path = image_root / copied[path].relative_to("/")
                contents = image_path.read_bytes()
                self.assertTrue(contents, f"empty shipped data file: {path}")
                if path.suffix == ".json":
                    json.loads(contents)

    def test_module_membership_uses_the_central_image_closure(self):
        self.assertEqual([], _per_module_dockerfile_assertions())


if __name__ == "__main__":
    unittest.main()

"""The offline control inventory command reads only the five dist locations."""

import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


_IMAGE = "ghcr.io/example/worldserver@sha256:" + "a" * 64
_ETC = "azerothcore/env/ref/etc"
_WORLD = f"{_ETC}/worldserver.conf.dist"


class ControlConfig(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.archive = Path(directory) / "world.tar"

    def write_tar(self, files, nonregular=()):
        with tarfile.open(self.archive, "w") as archive:
            for name, data in files:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            for name, kind in nonregular:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = "unused-target"
                archive.addfile(member)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "ephemeral.controlconfig", *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def inventory(self, image=_IMAGE):
        return self.run_cli("--worldserver", image, "--archive", str(self.archive))

    def assert_rejected(self, result, message):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn(message, result.stderr)
        self.assertNotIn(_WORLD, result.stderr)
        self.assertNotIn("sample-private-value", result.stderr)

    def test_cli_outputs_sorted_key_metadata_and_omits_absent_groups(self):
        self.write_tar(
            [
                (
                    f"./{_WORLD}",
                    b"Zeta = sample-private-value\n \t# Alpha.Key_1 = 2\n"
                    b"Alpha.Key_1 = 3\n## DoubleHash = 4\n// Slash = 5\n"
                    b"Bad-Key = 6\n# Just prose\n",
                ),
                (f"{_ETC}/modules/mod_overseer.conf.dist", b"Overseer.Toggle = 0\n"),
                (f"{_ETC}/modules/mod_dungeon_clear.conf.dist", b"DungeonClear.On = 0"),
                (f"{_ETC}/modules/mod_ollama_chat.conf.dist", b"OllamaChat.On = 0"),
                ("other/playerbots.conf.dist", b"Other = sample-private-value"),
            ]
        )
        result = self.inventory()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        expected = {
            "worldserver": _IMAGE,
            "platform": "linux/amd64",
            "groups": {
                "worldserver": ["Alpha.Key_1", "Zeta"],
                "overseer": ["Overseer.Toggle"],
                "dungeon-clear": ["DungeonClear.On"],
                "ollama-chat": ["OllamaChat.On"],
            },
        }
        self.assertEqual(result.stdout, json.dumps(expected, sort_keys=True) + "\n")

    def test_recognizes_playerbots_dist_and_allows_directory_entries(self):
        self.write_tar(
            [
                (_WORLD, b"Server.Key = 1"),
                (f"{_ETC}/modules/playerbots.conf.dist", b"Playerbots.Enabled = 1"),
            ],
            nonregular=[(f"./{_ETC}/modules/", tarfile.DIRTYPE)],
        )
        result = self.inventory()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["groups"],
            {"playerbots": ["Playerbots.Enabled"], "worldserver": ["Server.Key"]},
        )

    def test_worldserver_is_required_and_each_present_dist_needs_keys(self):
        playerbots = f"{_ETC}/modules/playerbots.conf.dist"
        cases = (
            ([(playerbots, b"Playerbots.Enabled = 1")], "worldserver dist is missing"),
            ([(_WORLD, b"# prose only")], "dist has no supported keys"),
            (
                [(_WORLD, b"Server.Instance = 1"), (playerbots, b"## Ignored = 1")],
                "dist has no supported keys",
            ),
        )
        for files, message in cases:
            with self.subTest(message=message, filenames=[name for name, _ in files]):
                self.write_tar(files)
                self.assert_rejected(self.inventory(), message)

    def test_canonical_and_single_dot_prefix_cannot_duplicate_a_dist(self):
        self.write_tar([(_WORLD, b"First = 1"), (f"./{_WORLD}", b"Second = 2")])
        self.assert_rejected(self.inventory(), "duplicate dist file")

    def test_dangerous_dist_candidates_are_rejected(self):
        for name in (f"/{_WORLD}", f"outside/../{_WORLD}", _WORLD.replace("/", "\\")):
            with self.subTest(name=name):
                self.write_tar([(name, b"Server.Key = sample-private-value")])
                self.assert_rejected(self.inventory(), "unsafe dist path or type")
        unsafe_types = (
            (_WORLD, tarfile.SYMTYPE),
            (_WORLD, tarfile.LNKTYPE),
            (_WORLD, tarfile.DIRTYPE),
            (_ETC, tarfile.SYMTYPE),
        )
        for name, kind in unsafe_types:
            with self.subTest(name=name, kind=kind):
                self.write_tar([], nonregular=[(name, kind)])
                self.assert_rejected(self.inventory(), "unsafe dist path or type")

    def test_read_errors_have_no_paths_or_content(self):
        for payload in (None, b"sample-private-value"):
            with self.subTest(payload=payload):
                if payload is not None:
                    self.archive.write_bytes(payload)
                self.assert_rejected(
                    self.inventory(), "could not read the dist archive"
                )
        self.write_tar([(_WORLD, b"Key = \xff sample-private-value")])
        self.assert_rejected(self.inventory(), "could not read the dist archive")

    def test_cli_requires_a_digest_and_archive(self):
        missing = self.run_cli()
        self.assert_rejected(missing, "--worldserver, --archive")
        for image in (
            "ghcr.io/example/worldserver:latest",
            _IMAGE[:-1],
            f"https://{_IMAGE}",
        ):
            with self.subTest(image=image):
                self.assert_rejected(self.inventory(image), "digest-pinned image")

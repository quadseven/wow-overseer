"""The localhost probe in tests/sandbox_caps.py tells a denied socket apart.

Every test that binds or connects a localhost port skips when
sandbox_caps.LOCALHOST is False (the lane check sandbox denies localhost), so
the probe must say False when the sandbox refuses a socket, and must never say
False on CI, where a wrong probe would hide those tests behind a skip.

The guard below keeps it that way: a test module that opens a localhost
socket must use the probe, and with sockets denied every such module must
skip those tests rather than error (#1488).
"""

from __future__ import annotations

import os
import pathlib
import re
import socket
import subprocess
import sys
import unittest
from unittest import mock

from tests import sandbox_caps


def _denied(*args, **kwargs):
    raise PermissionError(1, "Operation not permitted")


class LocalhostProbe(unittest.TestCase):
    def test_a_denied_socket_reads_as_no_localhost(self):
        with mock.patch.object(socket, "socket", _denied):
            self.assertFalse(sandbox_caps._connects_to_localhost())

    def test_a_denied_connection_reads_as_no_localhost(self):
        # The lane sandbox shape: the bind works, the connect is refused.
        with mock.patch.object(socket, "create_connection", _denied):
            self.assertFalse(sandbox_caps._connects_to_localhost())

    def test_the_probe_agrees_with_the_module_flag(self):
        self.assertIs(sandbox_caps._connects_to_localhost(), sandbox_caps.LOCALHOST)

    @unittest.skipUnless(os.environ.get("GITHUB_ACTIONS") == "true", "runs on CI only")
    def test_ci_allows_localhost_so_nothing_hides_behind_a_skip(self):
        self.assertTrue(sandbox_caps.LOCALHOST)


TESTS = pathlib.Path(__file__).resolve().parent

# Code that binds or connects a real port. A name passed as a string to a
# mock (no call parenthesis) is not a match.
OPENS_A_PORT = re.compile(
    r"\b(?:Threading)?HTTPServer\("
    r"|\b(?:Threading)?TCPServer\("
    r"|\bserve_forever\(\)"
    r"|\.bind\(\("
    r"|\bcreate_connection\("
    r"|\bstart_server\("
    r"|\bcreate_server\("
    r"|\bTestServer\("
    r"|\bTCPSite\("
    r"|\bAioHTTPTestCase\b"
    r"|\buvicorn\.run\("
)

# Runs the named test modules with every IPv4/IPv6 bind and connect refused,
# the way the lane check sandbox refuses them.
DENIED_RUN = """
import socket, sys, unittest

class Denied(socket.socket):
    def _deny(self):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise PermissionError(1, "Operation not permitted")
    def bind(self, address):
        self._deny()
        return super().bind(address)
    def connect(self, address):
        self._deny()
        return super().connect(address)
    def connect_ex(self, address):
        self._deny()
        return super().connect_ex(address)

socket.socket = Denied
unittest.main(module=None, argv=["unittest", *sys.argv[1:]])
"""


def modules_that_open_a_port():
    found = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        if OPENS_A_PORT.search(path.read_text()):
            found.append(path)
    return found


class EveryLocalhostTestUsesTheProbe(unittest.TestCase):
    def test_the_scan_finds_the_known_port_openers(self):
        names = {p.stem for p in modules_that_open_a_port()}
        for known in ("test_strands_server", "test_jev_strands"):
            self.assertIn(known, names)

    def test_a_module_that_opens_a_port_skips_on_the_probe(self):
        for path in modules_that_open_a_port():
            with self.subTest(module=path.stem):
                self.assertTrue(
                    "sandbox_caps.LOCALHOST" in path.read_text(),
                    "%s opens a localhost port but never checks"
                    " sandbox_caps.LOCALHOST; put"
                    " @unittest.skipUnless(sandbox_caps.LOCALHOST,"
                    " sandbox_caps.NO_LOCALHOST) on each test that does" % path.name,
                )

    def test_with_sockets_denied_they_skip_and_never_error(self):
        modules = [p.stem for p in modules_that_open_a_port()]
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(TESTS), env.get("PYTHONPATH")])
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", DENIED_RUN, *modules],
            cwd=TESTS.parent,
            env=env,
            text=True,
            capture_output=True,
            timeout=600,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output[-4000:])
        self.assertIn("skipped=", output)


if __name__ == "__main__":
    unittest.main()

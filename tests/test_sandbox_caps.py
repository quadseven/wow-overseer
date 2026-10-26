"""The localhost probe in tests/sandbox_caps.py tells a denied socket apart.

The Strands server, overseer CLI and realmroller world tests skip when
sandbox_caps.LOCALHOST is False (the lane check sandbox denies localhost), so
the probe must say False when the sandbox refuses a socket, and must never say
False on CI, where a wrong probe would hide those tests behind a skip.
"""

from __future__ import annotations

import os
import socket
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


if __name__ == "__main__":
    unittest.main()

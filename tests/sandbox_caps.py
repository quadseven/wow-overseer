"""What the process running the tests may do.

A lane's pre-PR check (.loom/validation.conf) runs this suite inside a
sandbox that denies connections to localhost, so the tests that serve a fake
site on a localhost port skip there. CI runs outside it and runs them.
"""

import socket


def _connects_to_localhost():
    try:
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            with socket.create_connection(server.getsockname(), timeout=5):
                return True
    except OSError:
        return False


LOCALHOST = _connects_to_localhost()
NO_LOCALHOST = "needs a localhost connection, which the lane check sandbox denies"

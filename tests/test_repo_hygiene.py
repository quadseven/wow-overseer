"""Repository hygiene checks."""

import subprocess
from pathlib import Path
import unittest


class RepositoryHygiene(unittest.TestCase):
    def test_no_tracked_tmp_files(self):
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.tmp"],
            check=True,
            capture_output=True,
        )
        tracked_files = result.stdout.decode().split("\0")
        existing_files = [
            path for path in tracked_files if path and Path(path).exists()
        ]
        self.assertEqual(existing_files, [], "tracked *.tmp files found")


if __name__ == "__main__":
    unittest.main()

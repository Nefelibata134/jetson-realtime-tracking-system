import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseValidationTest(unittest.TestCase):
    def test_repository_satisfies_release_contract(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/validate_release.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("status=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_release", ROOT / "scripts" / "validate_release.py"
)
assert SPEC is not None and SPEC.loader is not None
VALIDATE_RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATE_RELEASE)


class ReleaseValidationTest(unittest.TestCase):
    def test_local_markdown_link_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.md"
            target.write_text("target", encoding="utf-8")
            document = root / "document.md"
            document.write_text(
                "[valid](target.md) [external](https://example.com) ",
                encoding="utf-8",
            )
            self.assertEqual(VALIDATE_RELEASE.local_markdown_links(document), [])
            document.write_text("[missing](missing.md)", encoding="utf-8")
            self.assertEqual(
                VALIDATE_RELEASE.local_markdown_links(document),
                [(root / "missing.md").resolve()],
            )


if __name__ == "__main__":
    unittest.main()

import importlib.util
import tempfile
import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_release", ROOT / "scripts" / "validate_release.py"
)
assert SPEC is not None and SPEC.loader is not None
VALIDATE_RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATE_RELEASE)


class ReleaseValidationTest(unittest.TestCase):
    def test_current_readme_sections_and_runtime_guide(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        headings = set(re.findall(r"^##\s+(.+?)\s*$", readme, re.MULTILINE))
        self.assertFalse(VALIDATE_RELEASE.REQUIRED_README_HEADINGS - headings)
        self.assertIn("docs/runtime_guide.md", VALIDATE_RELEASE.REQUIRED_FILES)
        self.assertIn("(docs/runtime_guide.md)", readme)
        self.assertTrue((ROOT / "docs/runtime_guide.md").is_file())

    def test_split_document_links_resolve(self) -> None:
        for name in ("README.md", "docs/runtime_guide.md"):
            with self.subTest(name=name):
                self.assertEqual(VALIDATE_RELEASE.local_markdown_links(ROOT / name), [])

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

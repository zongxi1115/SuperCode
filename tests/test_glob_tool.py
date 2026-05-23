import tempfile
import unittest
from pathlib import Path

from agent.tools import ToolContext
from coding_agent.tools import GlobFileTool


class GlobFileToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-glob-"))
        self.context = ToolContext(workspace=self.workspace)
        (self.workspace / "src" / "components").mkdir(parents=True)
        (self.workspace / "src" / "components" / "button.tsx").write_text("export {}\n", encoding="utf-8")
        (self.workspace / "src" / "components" / "card.tsx").write_text("export {}\n", encoding="utf-8")
        (self.workspace / "src" / "index.ts").write_text("export * from './components/button'\n", encoding="utf-8")
        (self.workspace / "node_modules" / "pkg").mkdir(parents=True)
        (self.workspace / "node_modules" / "pkg" / "index.ts").write_text("ignored\n", encoding="utf-8")

    def test_glob_returns_matching_files(self) -> None:
        output = GlobFileTool().run({"pattern": "src/**/*.tsx"}, self.context)

        self.assertIn("# Pattern: src/**/*.tsx", output)
        self.assertIn("src/components/button.tsx", output)
        self.assertIn("src/components/card.tsx", output)
        self.assertNotIn("node_modules/pkg/index.ts", output)

    def test_glob_can_target_subdirectory_pattern(self) -> None:
        output = GlobFileTool().run({"pattern": "**/*.tsx", "search_path": "src"}, self.context)

        self.assertIn("src/components/button.tsx", output)
        self.assertIn("src/components/card.tsx", output)

    def test_glob_truncates_results_at_limit(self) -> None:
        output = GlobFileTool().run({"pattern": "src/**/*.tsx", "limit": 1}, self.context)

        self.assertIn("# Truncated: true", output)
        self.assertIn("# Note: results truncated", output)


if __name__ == "__main__":
    unittest.main()

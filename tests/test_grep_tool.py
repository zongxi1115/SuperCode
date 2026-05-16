import tempfile
import unittest
from pathlib import Path

from agent.tools import ToolContext
from coding_agent.tools import GrepFileTool


class GrepFileToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-grep-"))
        self.context = ToolContext(workspace=self.workspace)
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "alpha.py").write_text(
            "first line\nneedle here\nthird line\nneedle again\n",
            encoding="utf-8",
        )
        (self.workspace / "src" / "beta.py").write_text(
            "no match\nneedle in beta\n",
            encoding="utf-8",
        )
        (self.workspace / "node_modules").mkdir()
        (self.workspace / "node_modules" / "left-pad").mkdir()
        (self.workspace / "node_modules" / "left-pad" / "index.js").write_text(
            "needle from dependency\n",
            encoding="utf-8",
        )
        (self.workspace / "dist").mkdir()
        (self.workspace / "dist" / "bundle.js").write_text(
            "needle from bundle\n",
            encoding="utf-8",
        )

    def test_grep_returns_only_matching_lines(self) -> None:
        tool = GrepFileTool()

        output = tool.run({"regex": "needle", "search_path": "src"}, self.context)

        self.assertEqual(
            output,
            "\n".join(
                [
                    "# File: src/alpha.py",
                    "2 | needle here",
                    "4 | needle again",
                    "# File: src/beta.py",
                    "2 | needle in beta",
                ]
            ),
        )

    def test_grep_returns_not_found_message(self) -> None:
        tool = GrepFileTool()

        output = tool.run({"regex": "missing", "search_path": "src"}, self.context)

        self.assertEqual(output, "未找到匹配项: missing")

    def test_grep_ignores_generated_directories_by_default(self) -> None:
        tool = GrepFileTool()

        output = tool.run({"regex": "needle", "search_path": "."}, self.context)

        self.assertIn("# File: src/alpha.py", output)
        self.assertNotIn("node_modules/left-pad/index.js", output)
        self.assertNotIn("dist/bundle.js", output)

    def test_grep_can_include_ignored_directories(self) -> None:
        tool = GrepFileTool()

        output = tool.run({"regex": "needle", "search_path": ".", "include_ignored": True}, self.context)

        self.assertIn("# File: node_modules/left-pad/index.js", output)
        self.assertIn("1 | needle from dependency", output)
        self.assertIn("# File: dist/bundle.js", output)

    def test_grep_can_target_ignored_directory_explicitly(self) -> None:
        tool = GrepFileTool()

        output = tool.run({"regex": "needle", "search_path": "node_modules"}, self.context)

        self.assertEqual(
            output,
            "\n".join(
                [
                    "# File: node_modules/left-pad/index.js",
                    "1 | needle from dependency",
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()

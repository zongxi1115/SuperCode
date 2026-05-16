import tempfile
import unittest
from pathlib import Path

from agent.tools import ToolContext
from coding_agent.tools import ListFileTool


class ListFileToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-list-"))
        self.context = ToolContext(workspace=self.workspace)
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "app.ts").write_text("console.log('hi')\n", encoding="utf-8")
        (self.workspace / "node_modules").mkdir()
        (self.workspace / "node_modules" / "left-pad").mkdir()
        (self.workspace / "node_modules" / "left-pad" / "index.js").write_text(
            "module.exports = () => 'x';\n",
            encoding="utf-8",
        )
        (self.workspace / "dist").mkdir()
        (self.workspace / "dist" / "bundle.js").write_text("built\n", encoding="utf-8")

    def test_list_file_ignores_generated_directories_by_default(self) -> None:
        output = ListFileTool().run({}, self.context)
        visible_lines = [
            line for line in output.splitlines()
            if not line.startswith("# Ignored:")
        ]
        visible_output = "\n".join(visible_lines)

        self.assertIn("# Path: .", output)
        self.assertIn("src/", visible_output)
        self.assertIn("src/app.ts", visible_output)
        self.assertNotIn("node_modules/", visible_output)
        self.assertNotIn("dist/", visible_output)

    def test_list_file_can_include_ignored_directories(self) -> None:
        output = ListFileTool().run({"include_ignored": True}, self.context)

        self.assertIn("node_modules/", output)
        self.assertIn("node_modules/left-pad/index.js", output)
        self.assertIn("dist/bundle.js", output)

    def test_list_file_can_target_ignored_directory_explicitly(self) -> None:
        output = ListFileTool().run({"path": "node_modules"}, self.context)

        self.assertIn("# Path: node_modules", output)
        self.assertIn("node_modules/left-pad/", output)
        self.assertIn("node_modules/left-pad/index.js", output)


if __name__ == "__main__":
    unittest.main()

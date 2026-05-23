import tempfile
import unittest
from pathlib import Path

from agent.tools import ToolContext
from coding_agent.tools import ApplyPatchTool, delete_file_in_workspace


class ApplyPatchToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-patch-"))
        self.context = ToolContext(workspace=self.workspace)
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "a.ts").write_text(
            "const before = 1;\nconst keep = 2;\n",
            encoding="utf-8",
        )

    def test_apply_patch_updates_existing_file(self) -> None:
        tool = ApplyPatchTool()

        result = tool.run(
            {
                "filename": "src/a.ts",
                "start_line": 1,
                "end_line": 1,
                "new_content": "const after = 1;"
            },
            self.context,
        )

        self.assertEqual(result["files"], ["src/a.ts"])
        self.assertEqual(
            (self.workspace / "src" / "a.ts").read_text(encoding="utf-8"),
            "const after = 1;\nconst keep = 2;\n",
        )

    def test_apply_patch_out_of_bounds(self) -> None:
        tool = ApplyPatchTool()

        with self.assertRaisesRegex(ValueError, "超出文件总行数"):
            tool.run(
                {
                    "filename": "src/a.ts",
                    "start_line": 5,
                    "end_line": 6,
                    "new_content": "const after = 1;"
                },
                self.context,
            )

    def test_apply_patch_invalid_range(self) -> None:
        tool = ApplyPatchTool()

        with self.assertRaisesRegex(ValueError, "start_line 不能大于 end_line \\+ 1"):
            tool.run(
                {
                    "filename": "src/a.ts",
                    "start_line": 3,
                    "end_line": 1,
                    "new_content": "const after = 1;"
                },
                self.context,
            )


class DeleteFileInWorkspaceTests(unittest.TestCase):
    def test_delete_file_in_workspace_removes_target_file(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-delete-"))
        target = workspace / "demo.ts"
        target.write_text("export const value = 1;\n", encoding="utf-8")

        message = delete_file_in_workspace("demo.ts", workspace)

        self.assertEqual(message, "已删除文件: demo.ts")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()

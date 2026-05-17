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
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: src/a.ts\n"
                    "@@\n"
                    "-const before = 1;\n"
                    "+const after = 1;\n"
                    " const keep = 2;\n"
                    "*** End Patch"
                )
            },
            self.context,
        )

        self.assertEqual(result["files"], ["src/a.ts"])
        self.assertEqual(
            (self.workspace / "src" / "a.ts").read_text(encoding="utf-8"),
            "const after = 1;\nconst keep = 2;\n",
        )

    def test_apply_patch_rejects_add_file_operations(self) -> None:
        tool = ApplyPatchTool()

        with self.assertRaisesRegex(ValueError, "只支持 \\*\\*\\* Update File"):
            tool.run(
                {
                    "patch": (
                        "*** Begin Patch\n"
                        "*** Add File: src/new.ts\n"
                        "+export const value = 1;\n"
                        "*** End Patch"
                    )
                },
                self.context,
            )

    def test_apply_patch_rejects_final_code_pasted_without_diff_markers(self) -> None:
        tool = ApplyPatchTool()

        with self.assertRaisesRegex(ValueError, "没有任何 '\\+' 或 '-' 变更行"):
            tool.run(
                {
                    "patch": (
                        "*** Begin Patch\n"
                        "*** Update File: src/a.ts\n"
                        " const after = 1;\n"
                        " const keep = 2;\n"
                        "*** End Patch"
                    )
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

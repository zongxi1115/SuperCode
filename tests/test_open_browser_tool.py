import tempfile
import unittest
from pathlib import Path

from agent.tools import ToolContext
from coding_agent.tools import OpenBrowserTool


class OpenBrowserToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-browser-")).resolve()
        self.context = ToolContext(workspace=self.workspace)

    def test_url_does_not_require_session_id(self) -> None:
        tool = OpenBrowserTool()

        result = tool.run({"url": "localhost:5173"}, self.context)

        self.assertEqual(result["resolved_url"], "http://localhost:5173")
        self.assertEqual(result["source_type"], "network_url")

    def test_local_path_still_requires_session_id(self) -> None:
        tool = OpenBrowserTool()
        preview_file = self.workspace / "index.html"
        preview_file.write_text("<h1>hi</h1>", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "缺少 session_id"):
            tool.run({"path": "index.html"}, self.context)


if __name__ == "__main__":
    unittest.main()

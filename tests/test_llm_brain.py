import unittest

from agent.llm_brain import OpenAICompatibleBrain


class ParseJsonOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brain = OpenAICompatibleBrain(client=object())

    def test_parse_single_json_object(self) -> None:
        payload = self.brain._parse_json_output(
            '{"action":"final","thought":"done","final_answer":"ok"}'
        )

        self.assertEqual(payload["action"], "final")
        self.assertEqual(payload["final_answer"], "ok")

    def test_parse_first_json_object_from_mixed_output(self) -> None:
        raw_output = """{"action":"tool","thought":"先写文件","tool_name":"write_file","tool_arguments":{"filename":"sudoku.py","content":"print(1)"}}\n</think>\n\n{"action":"final","thought":"结束","final_answer":"done"}"""

        payload = self.brain._parse_json_output(raw_output)

        self.assertEqual(payload["action"], "tool")
        self.assertEqual(payload["tool_name"], "write_file")

    def test_parse_skips_non_decision_dicts(self) -> None:
        raw_output = """分析过程里先出现了一个普通对象 {"filename":"demo.py","content":"print(1)"}，真正的决策在后面 {"action":"final","thought":"结束","final_answer":"ok"}"""

        payload = self.brain._parse_json_output(raw_output)

        self.assertEqual(payload["action"], "final")
        self.assertEqual(payload["final_answer"], "ok")

    def test_to_decision_can_infer_tool_action(self) -> None:
        decision = self.brain._to_decision(
            {
                "thought": "直接调用工具",
                "tool_name": "read_file",
                "tool_arguments": {"filename": "README.md"},
            }
        )

        self.assertEqual(decision.action, "tool")
        self.assertEqual(decision.tool_name, "read_file")

    def test_to_decision_can_infer_final_action(self) -> None:
        decision = self.brain._to_decision(
            {
                "thought": "直接结束",
                "final_answer": "done",
            }
        )

        self.assertEqual(decision.action, "final")
        self.assertEqual(decision.final_answer, "done")


if __name__ == "__main__":
    unittest.main()

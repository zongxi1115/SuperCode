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


if __name__ == "__main__":
    unittest.main()

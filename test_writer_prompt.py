import json
import sys
import types
import unittest

sys.modules.setdefault("requests", types.ModuleType("requests"))

from agents import WriterEditorAgent


class WriterPromptTest(unittest.TestCase):
    def test_writer_prompt_adapts_to_ai_coding_tool_topics(self):
        captured_system_prompts = []
        captured_prompts = []
        title_prompts = []

        class FakeRouter:
            def call_llm(self, prompt, system_prompt="You are a helpful assistant.", model="gpt-4.1-mini", response_format="text"):
                captured_system_prompts.append(system_prompt)
                captured_prompts.append(prompt)
                if response_format == "json_object":
                    title_prompts.append(prompt)
                    if "请从候选标题中选出一个" in prompt or "score" in prompt:
                        return json.dumps({"title": "多智能体正在重塑AI编程工具的工作流"})
                    if "请给出 5 个公众号标题候选" in prompt or "titles" in prompt:
                        return json.dumps({
                            "titles": [
                                "主流AI编程工具为什么都在上多智能体",
                                "多智能体正在重塑AI编程工具的工作流",
                                "AI编程工具里的多智能体，到底解决了什么"
                            ]
                        })
                    return json.dumps({"title": "主流AI编程工具中的多智能体实践"})
                if "播客/视频脚本" in system_prompt:
                    return "口播脚本"
                if "请优化以下草稿" in prompt:
                    return prompt.split("请优化以下草稿:\n\n", 1)[1]
                return "## 背景介绍\n\n正文内容"

        agent = WriterEditorAgent(
            {
                "CAPABILITY_ROUTER": FakeRouter(),
            }
        )
        result = agent.process(
            {
                "topic": "主流ai编程工具中多智能体的应用",
                "tone": "实践导向",
                "audience": "一线开发者",
            },
            "研究资料"
        )

        writer_prompt = next(
            prompt for prompt in captured_system_prompts
            if "资深软件工程与 AI 编程工具内容创作者" in prompt
        )
        editor_prompt = next(
            prompt for prompt in captured_system_prompts
            if "你是一个资深软件工程技术编辑" in prompt
        )

        self.assertIn("软件工程", writer_prompt)
        self.assertIn("背景介绍", writer_prompt)
        self.assertIn("原理分析", writer_prompt)
        self.assertIn("实践建议", writer_prompt)
        self.assertIn("软件工程", editor_prompt)
        self.assertIn("背景介绍", editor_prompt)
        self.assertIn("原理分析", editor_prompt)
        self.assertIn("实践建议", editor_prompt)
        self.assertGreaterEqual(len(title_prompts), 2)
        self.assertTrue(any("候选标题" in prompt for prompt in title_prompts))
        self.assertTrue(any("从候选标题中选出一个" in prompt for prompt in title_prompts))
        self.assertEqual(result["title"], "多智能体正在重塑AI编程工具的工作流")
        self.assertGreaterEqual(len(result["title_candidates"]), 3)


if __name__ == "__main__":
    unittest.main()

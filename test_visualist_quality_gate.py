import os
import sys
import types
import unittest

sys.modules.setdefault("requests", types.ModuleType("requests"))

from agents import VisualistAgent


class QualityGateRouter:
    def __init__(self, review_plan):
        self.review_plan = list(review_plan)
        self.calls = []

    def call_llm(self, *args, **kwargs):
        return "Create a clean, modern cover prompt"

    def generate_image(self, prompt, aspect_ratio="1:1", model=None):
        self.calls.append(("generate", model, aspect_ratio, prompt))
        return f"{model or 'default'}".encode("utf-8")

    def review_image(self, prompt, image_bytes, aspect_ratio="1:1", title="", topic="", image_role="cover"):
        verdict = self.review_plan.pop(0)
        self.calls.append(("review", image_bytes.decode("utf-8"), image_role, verdict))
        return verdict


class GenerateOnlyRouter:
    def __init__(self):
        self.calls = []

    def call_llm(self, *args, **kwargs):
        return "Create a clean, modern cover prompt"

    def generate_image(self, prompt, aspect_ratio="1:1", model=None):
        self.calls.append(("generate", model, aspect_ratio, prompt))
        return f"{model or 'default'}".encode("utf-8")


class PromptInspectRouter:
    def __init__(self):
        self.generate_calls = []
        self.review_calls = []

    def call_llm(self, prompt, system_prompt="You are a helpful assistant.", model="gpt-4.1-mini", response_format="text"):
        if response_format == "json_object":
            if "候选标题" in prompt or "titles" in prompt:
                return '{"titles":["多智能体正在重塑AI编程工具的工作流"]}'
            return '{"title":"多智能体正在重塑AI编程工具的工作流"}'
        return "A clean cover prompt"

    def generate_image(self, prompt, aspect_ratio="1:1", model=None):
        self.generate_calls.append((model, aspect_ratio, prompt))
        return b"image-bytes"

    def review_image(self, prompt, image_bytes, aspect_ratio="1:1", title="", topic="", image_role="cover"):
        self.review_calls.append((prompt, image_role))
        return {"approved": True, "reason": "ok", "score": 0.99}


class VisualistQualityGateTest(unittest.TestCase):
    def test_visualist_upgrades_model_until_review_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = tmpdir
            router = QualityGateRouter(
                review_plan=[
                    {"approved": True, "reason": "cover ok"},
                    {"approved": False, "reason": "too generic"},
                    {"approved": True, "reason": "good enough"},
                ]
            )
            agent = VisualistAgent({"CAPABILITY_ROUTER": router})
            article = {
                "title": "主流AI编程工具中的多智能体实践",
                "topic": "主流ai编程工具中多智能体的应用",
                "body": "## 背景介绍\n\n正文内容\n\n[IMAGE: show a workflow diagram of multiple coding agents collaborating]\n",
                "image_prompts": ["show a workflow diagram of multiple coding agents collaborating"],
            }

            result = agent.process(article, os.path.join(tmp_path, "_visuals"), reuse_existing_visuals=False)

            generate_calls = [call for call in router.calls if call[0] == "generate"]
            review_calls = [call for call in router.calls if call[0] == "review"]

            self.assertEqual(generate_calls[1][1], "imagen-4.0-fast-generate-001")
            self.assertEqual(generate_calls[2][1], "imagen-4.0-generate-001")
            self.assertEqual(review_calls[1][1], "imagen-4.0-fast-generate-001")
            self.assertEqual(review_calls[2][1], "imagen-4.0-generate-001")
            self.assertTrue(os.path.exists(os.path.join(tmp_path, "_visuals", "visual_1.png")))
            self.assertIn("![show a workflow diagram", result["body"])

    def test_visualist_discards_image_after_three_failed_reviews(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            router = QualityGateRouter(
                review_plan=[
                    {"approved": True, "reason": "cover ok"},
                    {"approved": False, "reason": "off topic"},
                    {"approved": False, "reason": "too blurry"},
                    {"approved": False, "reason": "text unreadable"},
                ]
            )
            agent = VisualistAgent({"CAPABILITY_ROUTER": router})
            article = {
                "title": "主流AI编程工具中的多智能体实践",
                "topic": "主流ai编程工具中多智能体的应用",
                "body": "## 背景介绍\n\n正文内容\n\n[IMAGE: show a workflow diagram of multiple coding agents collaborating]\n",
                "image_prompts": ["show a workflow diagram of multiple coding agents collaborating"],
            }

            result = agent.process(article, os.path.join(tmpdir, "_visuals"), reuse_existing_visuals=False)

            self.assertFalse(os.path.exists(os.path.join(tmpdir, "_visuals", "visual_1.png")))
            self.assertNotIn("[IMAGE:", result["body"])
            self.assertNotIn("![show a workflow diagram", result["body"])

    def test_visualist_fails_closed_when_review_is_unavailable(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            router = GenerateOnlyRouter()
            agent = VisualistAgent({"CAPABILITY_ROUTER": router})
            article = {
                "title": "主流AI编程工具中的多智能体实践",
                "topic": "主流ai编程工具中多智能体的应用",
                "body": "## 背景介绍\n\n正文内容\n\n[IMAGE: show a workflow diagram of multiple coding agents collaborating]\n",
                "image_prompts": ["show a workflow diagram of multiple coding agents collaborating"],
            }

            result = agent.process(article, os.path.join(tmpdir, "_visuals"), reuse_existing_visuals=False)

            self.assertFalse(os.path.exists(os.path.join(tmpdir, "_visuals", "visual_1.png")))
            self.assertNotIn("![show a workflow diagram", result["body"])

    def test_visualist_prompts_emphasize_no_text_and_icon_based_diagrams(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            router = PromptInspectRouter()
            agent = VisualistAgent({"CAPABILITY_ROUTER": router})
            article = {
                "title": "主流AI编程工具中的多智能体实践",
                "topic": "主流ai编程工具中多智能体的应用",
                "body": "## 背景介绍\n\n正文内容\n\n[IMAGE: show a workflow diagram with labels and arrows]\n\n[TABLE_IMAGE: compare single agent and multi-agent workflows]\n",
                "image_prompts": [
                    "show a workflow diagram with labels and arrows",
                    "compare single agent and multi-agent workflows",
                ],
            }

            agent.process(article, os.path.join(tmpdir, "_visuals"), reuse_existing_visuals=False)

            cover_prompt = router.generate_calls[0][2].lower()
            chapter_prompt = router.generate_calls[1][2].lower()
            table_prompt = router.generate_calls[2][2].lower()

            for prompt in (cover_prompt, chapter_prompt, table_prompt):
                self.assertIn("no text", prompt)
                self.assertIn("no labels", prompt)
                self.assertIn("no numbers", prompt)

            self.assertIn("editorial illustration", cover_prompt)
            self.assertIn("conceptual illustration", chapter_prompt)
            self.assertIn("comparison infographic", table_prompt)


if __name__ == "__main__":
    unittest.main()

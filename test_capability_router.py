import json
import os
import sys
import types
import unittest


class DummyRequests(types.ModuleType):
    def __init__(self):
        super().__init__("requests")
        self.get = lambda *args, **kwargs: None
        self.post = lambda *args, **kwargs: None


sys.modules.setdefault("requests", DummyRequests())


class DummyOpenAI:
    def __init__(self):
        raise AssertionError("OpenAI fallback should not be used in this test")


class CapabilityRouterTest(unittest.TestCase):
    def setUp(self):
        self._original_env = os.environ.copy()
        self._original_modules = dict(sys.modules)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._original_env)
        for key in list(sys.modules.keys()):
            if key not in self._original_modules:
                del sys.modules[key]

    def test_native_runtime_is_preferred_for_text(self):
        import capabilities

        module = types.ModuleType("fake_runtime_text")

        class Runtime:
            def call_llm(self, **kwargs):
                return "native-text"

        module.Runtime = Runtime
        sys.modules["fake_runtime_text"] = module
        os.environ["OPENCLAW_RUNTIME"] = "fake_runtime_text:Runtime"
        sys.modules["openai"] = types.ModuleType("openai")
        sys.modules["openai"].OpenAI = DummyOpenAI

        router = capabilities.CapabilityRouter.from_env()
        result = router.call_llm("hello", "system prompt")

        self.assertEqual(result, "native-text")
        self.assertEqual(router.trace[-1]["provider"], "openclaw")

    def test_auto_detects_loaded_runtime_module(self):
        import capabilities

        module = types.ModuleType("openclaw_runtime")

        class Runtime:
            def call_llm(self, **kwargs):
                return "auto-detected-runtime"

        module.Runtime = Runtime
        sys.modules["openclaw_runtime"] = module
        os.environ.pop("OPENCLAW_RUNTIME", None)
        os.environ.pop("OPENCLAW_LLM_RUNTIME", None)

        router = capabilities.CapabilityRouter.from_env()
        result = router.call_llm("hello", "system prompt")

        self.assertEqual(result, "auto-detected-runtime")
        self.assertEqual(router.trace[-1]["provider"], "openclaw")

    def test_search_falls_back_to_tavily(self):
        import capabilities

        tavily_module = types.ModuleType("tavily")

        class TavilyClient:
            def __init__(self, api_key: str):
                self.api_key = api_key

            def search(self, query: str, search_depth: str = "advanced", max_results: int = 3):
                return {
                    "results": [
                        {"title": "Result A", "content": "Body A", "url": "https://example.com/a"}
                    ]
                }

        tavily_module.TavilyClient = TavilyClient
        sys.modules["tavily"] = tavily_module
        os.environ["TAVILY_API_KEY"] = "fake-tavily-key"

        router = capabilities.CapabilityRouter.from_env()
        result = router.search("multi agent coding")

        self.assertIn("Result A", result)
        self.assertEqual(router.trace[-1]["provider"], "tavily")

    def test_local_fallback_normalizes_ai_topic_title(self):
        import capabilities

        os.environ.pop("OPENCLAW_RUNTIME", None)
        os.environ.pop("OPENCLAW_LLM_RUNTIME", None)
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)

        router = capabilities.CapabilityRouter.from_env()
        result = router.call_llm(
            "用户输入: 帮我写一篇关于\"主流ai编程工具中多智能体的应用\"的公众号文章，面向一线开发者。",
            "你是一个内容架构师。",
            response_format="json_object",
        )

        self.assertEqual(json.loads(result)["title"], "主流ai编程工具中多智能体的应用")

    def test_runtime_factory_can_accept_config(self):
        import capabilities

        module = types.ModuleType("fake_runtime_factory")

        def build_runtime(config):
            class Runtime:
                def call_llm(self, **kwargs):
                    return config["MARKER"]

            return Runtime()

        module.build_runtime = build_runtime
        sys.modules["fake_runtime_factory"] = module
        os.environ["OPENCLAW_RUNTIME"] = "fake_runtime_factory:build_runtime"
        os.environ["MARKER"] = "factory-ok"

        router = capabilities.CapabilityRouter.from_env()
        result = router.call_llm("hello", "system")

        self.assertEqual(result, "factory-ok")

    def test_publish_uses_native_runtime_when_available(self):
        import capabilities

        module = types.ModuleType("fake_runtime_publish")

        class Runtime:
            def publish_wechat_draft(self, **kwargs):
                return {"status": "success", "draft_id": "native-draft"}

        module.Runtime = Runtime
        sys.modules["fake_runtime_publish"] = module
        os.environ["OPENCLAW_RUNTIME"] = "fake_runtime_publish:Runtime"

        router = capabilities.CapabilityRouter.from_env()
        result = router.publish_wechat_draft("title", "<p>body</p>", "/tmp/cover.png")

        self.assertEqual(result["draft_id"], "native-draft")
        self.assertEqual(router.trace[-1]["provider"], "openclaw")

    def test_review_image_uses_native_runtime_when_available(self):
        import capabilities

        module = types.ModuleType("fake_runtime_review")

        class Runtime:
            def review_image(self, **kwargs):
                return {"approved": True, "reason": "native-ok", "model": kwargs.get("model")}

        module.Runtime = Runtime
        sys.modules["fake_runtime_review"] = module
        os.environ["OPENCLAW_RUNTIME"] = "fake_runtime_review:Runtime"

        router = capabilities.CapabilityRouter.from_env()
        result = router.review_image(
            "cover prompt",
            b"image-bytes",
            aspect_ratio="16:9",
            image_role="cover",
        )

        self.assertTrue(result["approved"])
        self.assertEqual(router.trace[-1]["provider"], "openclaw")

    def test_review_image_rejects_low_score_even_when_approved(self):
        import capabilities

        module = types.ModuleType("fake_runtime_review_score")

        class Runtime:
            def review_image(self, **kwargs):
                return {"approved": True, "reason": "looks okay", "score": 0.42}

        module.Runtime = Runtime
        sys.modules["fake_runtime_review_score"] = module
        os.environ["OPENCLAW_RUNTIME"] = "fake_runtime_review_score:Runtime"

        router = capabilities.CapabilityRouter.from_env()
        result = router.review_image(
            "cover prompt",
            b"image-bytes",
            aspect_ratio="16:9",
            image_role="cover",
        )

        self.assertFalse(result["approved"])
        self.assertIn("score", result["reason"].lower())


if __name__ == "__main__":
    unittest.main()

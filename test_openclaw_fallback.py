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

import agents


class OpenAIStub:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(
                create=self._create
            )
        )

    def _create(self, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=self.response_text))]
        )


class OpenClawRuntimeSuccess:
    def __init__(self):
        self.calls = []

    def call_llm(self, **kwargs):
        self.calls.append(kwargs)
        return "openclaw-response"


class OpenClawRuntimeFailure:
    def call_llm(self, **kwargs):
        raise RuntimeError("openclaw unavailable")


class OpenClawFallbackTest(unittest.TestCase):
    def setUp(self):
        self._original_env = os.environ.copy()
        self._original_modules = dict(sys.modules)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._original_env)
        for key in list(sys.modules.keys()):
            if key not in self._original_modules:
                del sys.modules[key]

    def test_prefers_openclaw_runtime(self):
        module = types.ModuleType("fake_openclaw_success")
        module.Runtime = OpenClawRuntimeSuccess
        sys.modules["fake_openclaw_success"] = module
        os.environ["OPENCLAW_RUNTIME"] = "fake_openclaw_success:Runtime"

        class UnexpectedOpenAI:
            def __init__(self):
                raise AssertionError("OpenAI fallback should not be used")

        sys.modules["openai"] = types.ModuleType("openai")
        sys.modules["openai"].OpenAI = UnexpectedOpenAI

        result = agents.call_llm("prompt", "system")
        self.assertEqual(result, "openclaw-response")

    def test_falls_back_to_openai_when_openclaw_fails(self):
        module = types.ModuleType("fake_openclaw_failure")
        module.Runtime = OpenClawRuntimeFailure
        sys.modules["fake_openclaw_failure"] = module
        os.environ["OPENCLAW_RUNTIME"] = "fake_openclaw_failure:Runtime"
        os.environ["OPENAI_API_KEY"] = "sk-test-openai"

        sys.modules["openai"] = types.ModuleType("openai")
        sys.modules["openai"].OpenAI = lambda: OpenAIStub("openai-response")

        result = agents.call_llm("prompt", "system")
        self.assertEqual(result, "openai-response")


if __name__ == "__main__":
    unittest.main()

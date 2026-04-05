import json
import os
import sys
import types
import unittest


class DummyRequests(types.ModuleType):
    def __init__(self):
        super().__init__("requests")
        self.post = lambda *args, **kwargs: None


sys.modules.setdefault("requests", DummyRequests())

import agents
import capabilities


class GeminiResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def _decode_payload(kwargs):
    payload = kwargs.get("json") or kwargs.get("data")
    if isinstance(payload, (bytes, bytearray)):
        return json.loads(payload.decode("utf-8"))
    return payload


class GeminiTextFallbackTest(unittest.TestCase):
    def setUp(self):
        self._original_env = os.environ.copy()
        self._original_requests_post = capabilities.requests.post
        self._original_openai = sys.modules.get("openai")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._original_env)
        capabilities.requests.post = self._original_requests_post
        if self._original_openai is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = self._original_openai

    def test_uses_gemini_before_openai(self):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        os.environ.pop("OPENCLAW_RUNTIME", None)
        os.environ.pop("OPENCLAW_LLM_RUNTIME", None)

        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["payload"] = _decode_payload(kwargs)
            return GeminiResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "gemini-response"}
                                ]
                            }
                        }
                    ]
                }
            )

        capabilities.requests.post = fake_post

        class UnexpectedOpenAI:
            def __init__(self):
                raise AssertionError("OpenAI fallback should not be used when Gemini is available")

        sys.modules["openai"] = types.ModuleType("openai")
        sys.modules["openai"].OpenAI = UnexpectedOpenAI

        result = agents.call_llm("hello", "system prompt")

        self.assertEqual(result, "gemini-response")
        self.assertIn("generativelanguage.googleapis.com", captured["url"])
        self.assertIn("generationConfig", captured["payload"])

    def test_gemini_json_mode_requests_json_output(self):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        os.environ.pop("OPENCLAW_RUNTIME", None)
        os.environ.pop("OPENCLAW_LLM_RUNTIME", None)

        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["payload"] = _decode_payload(kwargs)
            return GeminiResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": '{"title":"AI编程多智能体实践"}'}
                                ]
                            }
                        }
                    ]
                }
            )

        capabilities.requests.post = fake_post
        sys.modules["openai"] = types.ModuleType("openai")
        sys.modules["openai"].OpenAI = lambda: (_ for _ in ()).throw(AssertionError("OpenAI fallback should not be used"))

        result = agents.call_llm("hello", "system prompt", response_format="json_object")

        self.assertEqual(result, '{"title":"AI编程多智能体实践"}')
        self.assertEqual(
            captured["payload"]["generationConfig"]["responseMimeType"],
            "application/json",
        )

    def test_image_generation_defaults_to_fast_model(self):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        os.environ.pop("GEMINI_IMAGE_MODEL", None)
        os.environ.pop("GEMINI_IMAGE_MODEL_PRIORITY", None)

        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["payload"] = _decode_payload(kwargs)
            return GeminiResponse(
                {
                    "predictions": [
                        {
                            "bytesBase64Encoded": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
                        }
                    ]
                }
            )

        capabilities.requests.post = fake_post

        router = capabilities.CapabilityRouter.from_env()
        result = router.generate_image("cover prompt", "16:9")

        self.assertIsInstance(result, bytes)
        self.assertIn("imagen-4.0-fast-generate-001", captured["url"])
        self.assertEqual(captured["payload"]["parameters"]["aspectRatio"], "16:9")

    def test_image_priority_defaults_to_three_imagen_models(self):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        os.environ.pop("GEMINI_IMAGE_MODEL", None)
        os.environ.pop("GEMINI_IMAGE_MODEL_PRIORITY", None)

        router = capabilities.CapabilityRouter.from_env()
        self.assertEqual(
            router.image_model_priority(),
            [
                "imagen-4.0-fast-generate-001",
                "imagen-4.0-generate-001",
                "imagen-4.0-ultra-generate-001",
            ],
        )

    def test_image_generation_falls_back_to_flash_image_model(self):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        os.environ["GEMINI_IMAGE_MODEL_PRIORITY"] = "imagen-4.0-fast-generate-001,imagen-4.0-generate-001,imagen-4.0-ultra-generate-001,gemini-2.5-flash-image"

        captured_urls = []

        def fake_post(url, **kwargs):
            captured_urls.append(url)
            payload = _decode_payload(kwargs)
            if "imagen-4.0-fast-generate-001" in url:
                return GeminiResponse({"error": {"message": "fail"}}, status_code=400)
            if "gemini-2.5-flash-image" in url:
                return GeminiResponse(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "inline_data": {
                                                "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
            raise AssertionError(f"Unexpected URL: {url} / payload={payload}")

        capabilities.requests.post = fake_post

        router = capabilities.CapabilityRouter.from_env()
        result = router.generate_image("cover prompt", "1:1")

        self.assertIsInstance(result, bytes)
        self.assertIn("imagen-4.0-fast-generate-001", captured_urls[0])
        self.assertIn("gemini-2.5-flash-image", captured_urls[-1])

    def test_image_review_uses_gemini_vision_model_when_native_runtime_missing(self):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        os.environ.pop("OPENCLAW_RUNTIME", None)
        os.environ.pop("OPENCLAW_LLM_RUNTIME", None)

        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["payload"] = _decode_payload(kwargs)
            return GeminiResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": '{"approved": true, "reason": "clear and on topic", "score": 0.98}'
                                    }
                                ]
                            }
                        }
                    ]
                }
            )

        capabilities.requests.post = fake_post

        router = capabilities.CapabilityRouter.from_env()
        result = router.review_image(
            "cover prompt",
            b"fake-image-bytes",
            aspect_ratio="16:9",
            image_role="cover",
            title="AI编程新范式",
            topic="主流ai编程工具中多智能体的应用",
        )

        self.assertTrue(result["approved"])
        self.assertIn("gemini-2.5-flash", captured["url"])
        self.assertEqual(captured["payload"]["generationConfig"]["responseMimeType"], "application/json")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib
import inspect
import json
import logging
import os
import re
import sys
import builtins
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency in minimal envs
    requests = None

from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger(__name__)


@dataclass
class CapabilityTraceEntry:
    capability: str
    provider: str
    status: str
    detail: str = ""


class CapabilityRouter:
    """
    Route content-related capabilities through the best available provider.

    Priority:
    1. Native host/runtime capability
    2. Token/API fallback
    3. Final fallback where applicable
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.trace: list[dict[str, Any]] = []
        self._runtime = None
        self._runtime_loaded = False

    @classmethod
    def from_env(cls) -> "CapabilityRouter":
        return cls(dict(os.environ))

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "CapabilityRouter":
        return cls(config)

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.trace)

    def clear_trace(self) -> None:
        self.trace.clear()

    def _record(self, capability: str, provider: str, status: str, detail: str = "") -> None:
        self.trace.append(
            {
                "capability": capability,
                "provider": provider,
                "status": status,
                "detail": detail,
            }
        )

    def _runtime_path(self) -> Optional[str]:
        for value in (
            self.config.get("OPENCLAW_RUNTIME"),
            self.config.get("OPENCLAW_LLM_RUNTIME"),
            os.environ.get("OPENCLAW_RUNTIME"),
            os.environ.get("OPENCLAW_LLM_RUNTIME"),
        ):
            if self._is_placeholder_runtime_path(value):
                continue
            if value:
                return str(value).strip()
        return None

    def _is_placeholder_runtime_path(self, value: Any) -> bool:
        if not value:
            return False
        text = str(value).strip()
        if not text:
            return False
        return "your_" in text or "placeholder" in text.lower() or "example" in text.lower()

    def _runtime_candidates(self) -> list[str]:
        raw = self.config.get("CAPABILITY_RUNTIME_CANDIDATES") or os.environ.get("CAPABILITY_RUNTIME_CANDIDATES")
        if raw:
            parsed = [item.strip() for item in re.split(r"[\s,]+", str(raw)) if item.strip()]
            if parsed:
                return parsed
        return [
            "openclaw_runtime",
            "codex_runtime",
            "host_runtime",
            "agent_runtime",
            "runtime",
        ]

    def _candidate_objects(self) -> list[object]:
        candidates: list[object] = []
        injected = [
            self.config.get("CAPABILITY_RUNTIME"),
            self.config.get("HOST_RUNTIME"),
            self.config.get("NATIVE_RUNTIME"),
            getattr(builtins, "CAPABILITY_RUNTIME", None),
            getattr(builtins, "HOST_RUNTIME", None),
            getattr(builtins, "NATIVE_RUNTIME", None),
        ]
        candidates.extend([item for item in injected if item is not None])

        main_module = sys.modules.get("__main__")
        if main_module is not None:
            for name in ("CAPABILITY_RUNTIME", "HOST_RUNTIME", "NATIVE_RUNTIME", "runtime", "openclaw_runtime", "capability_router"):
                value = getattr(main_module, name, None)
                if value is not None:
                    candidates.append(value)

        for module_name in self._runtime_candidates():
            module = sys.modules.get(module_name)
            if module is None:
                try:
                    module = importlib.import_module(module_name)
                except Exception:
                    continue
            candidates.append(module)
            for attr_name in ("Runtime", "runtime", "HostRuntime", "OpenClawRuntime", "CapabilityRuntime", "Adapter", "build_runtime", "create_runtime"):
                value = getattr(module, attr_name, None)
                if value is not None:
                    candidates.append(value)

        return candidates

    def _coerce_runtime(self, target: object) -> Optional[object]:
        if inspect.isclass(target):
            try:
                return target()
            except TypeError:
                return target(self.config)

        if callable(target):
            try:
                return target()
            except TypeError:
                return target(self.config)

        return target

    def _looks_like_runtime(self, target: object) -> bool:
        return any(
            hasattr(target, name)
            for name in ("call_llm", "complete", "generate", "chat", "invoke", "search", "read_text", "generate_image", "review_image", "publish_wechat_draft", "post_to_draft", "__call__")
        )

    def _load_runtime_from_explicit_path(self, runtime_path: str) -> object:
        if ":" not in runtime_path:
            raise RuntimeError("OPENCLAW_RUNTIME must use module:ClassOrFactory format")

        module_name, attr_name = runtime_path.split(":", 1)
        module = importlib.import_module(module_name)
        target = getattr(module, attr_name, None)
        if target is None:
            raise RuntimeError(f"{attr_name} not found in {module_name}")
        runtime = self._coerce_runtime(target)
        if runtime is None:
            raise RuntimeError(f"{attr_name} in {module_name} could not be constructed")
        return runtime

    def _auto_detect_runtime(self) -> Optional[object]:
        for candidate in self._candidate_objects():
            runtime = self._coerce_runtime(candidate)
            if runtime is not None and self._looks_like_runtime(runtime):
                return runtime
        return None

    def _load_runtime(self) -> Optional[object]:
        if self._runtime_loaded:
            return self._runtime

        self._runtime_loaded = True

        runtime_path = self._runtime_path()
        if runtime_path:
            self._runtime = self._load_runtime_from_explicit_path(runtime_path)
            return self._runtime

        self._runtime = self._auto_detect_runtime()
        return self._runtime

    def _load_method(self, runtime: object, candidates: list[str]) -> Optional[Any]:
        for name in candidates:
            if hasattr(runtime, name):
                return getattr(runtime, name)
        return None

    def _maybe_call_runtime(self, capability: str, candidates: list[str], **kwargs: Any) -> Optional[Any]:
        runtime = self._load_runtime()
        if runtime is None:
            return None

        method = self._load_method(runtime, candidates)
        if method is None:
            self._record(capability, "openclaw", "miss", "native runtime does not expose a supported method")
            return None

        call_kwargs = kwargs
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            signature = None
        if signature is not None:
            parameters = signature.parameters
            if not any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
                call_kwargs = {key: value for key, value in kwargs.items() if key in parameters}

        result = method(**call_kwargs)
        self._record(capability, "openclaw", "ok")
        return result

    def _stringify(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, bytes):
            return result.decode("utf-8", errors="ignore")
        if isinstance(result, dict):
            for key in ("text", "content", "output", "message"):
                value = result.get(key)
                if isinstance(value, str):
                    return value
            return json.dumps(result, ensure_ascii=False)
        return str(result)

    def _post_json(self, url: str, payload: Dict[str, Any], timeout: int) -> tuple[int, str]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if requests is not None:
            response = requests.post(url, data=body, headers=headers, timeout=timeout)
            return response.status_code, response.text

        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib_request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8", errors="ignore")
                return resp.getcode(), data
        except urllib_error.HTTPError as exc:
            data = exc.read().decode("utf-8", errors="ignore")
            return exc.code, data

    def _image_model_priority(self) -> list[str]:
        raw = self.config.get("GEMINI_IMAGE_MODEL_PRIORITY") or os.environ.get("GEMINI_IMAGE_MODEL_PRIORITY")
        models: list[str] = []
        if raw:
            models = [item.strip() for item in re.split(r"[\s,]+", str(raw)) if item.strip()]

        single = self.config.get("GEMINI_IMAGE_MODEL") or os.environ.get("GEMINI_IMAGE_MODEL")
        if single:
            single = str(single).strip()
            if single and single not in models:
                models.insert(0, single)

        if not models:
            models = [
                "imagen-4.0-fast-generate-001",
                "imagen-4.0-generate-001",
                "imagen-4.0-ultra-generate-001",
            ]

        normalized: list[str] = []
        seen = set()
        for model in models:
            code = str(model).strip()
            if code.startswith("models/"):
                code = code.split("/", 1)[1]
            if not code or code in seen:
                continue
            seen.add(code)
            normalized.append(code)
        return normalized

    def image_model_priority(self) -> list[str]:
        return list(self._image_model_priority())

    def _extract_inline_image_bytes(self, data: Dict[str, Any]) -> Optional[bytes]:
        candidates = data.get("candidates") or []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content", {})
            parts = content.get("parts", []) if isinstance(content, dict) else []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline_data = part.get("inline_data") or part.get("inlineData")
                if not isinstance(inline_data, dict):
                    continue
                blob = inline_data.get("data")
                if isinstance(blob, bytes):
                    return blob
                if isinstance(blob, str) and blob.strip():
                    import base64

                    return base64.b64decode(blob)
        return None

    def _call_imagen_predict(self, api_key: str, model: str, prompt: str, aspect_ratio: str) -> Optional[bytes]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict?key={api_key}"
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": aspect_ratio,
            },
        }
        status_code, text = self._post_json(url, payload, timeout=90)
        if status_code != 200:
            self._record("image", "gemini", "error", f"HTTP {status_code}")
            logger.error("Image generation failed (%s): %s", status_code, text[:200])
            return None

        try:
            data = json.loads(text)
        except Exception as exc:
            self._record("image", "gemini", "error", str(exc))
            logger.error("Imagen response was not valid JSON: %s", exc)
            return None

        predictions = data.get("predictions") or []
        if predictions:
            first = predictions[0]
            if isinstance(first, dict):
                blob = first.get("bytesBase64Encoded")
                if isinstance(blob, str) and blob.strip():
                    import base64

                    self._record("image", "gemini", "ok")
                    return base64.b64decode(blob)

        self._record("image", "gemini", "error", "prediction payload missing image bytes")
        logger.error("Imagen response missing image bytes: %s", text[:200])
        return None

    def _call_gemini_flash_image(self, api_key: str, model: str, prompt: str, aspect_ratio: str) -> Optional[bytes]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["Image"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                },
            },
        }
        status_code, text = self._post_json(url, payload, timeout=90)
        if status_code != 200:
            self._record("image", "gemini", "error", f"HTTP {status_code}")
            logger.error("Gemini image generation failed (%s): %s", status_code, text[:200])
            return None

        try:
            data = json.loads(text)
        except Exception as exc:
            self._record("image", "gemini", "error", str(exc))
            logger.error("Gemini image response was not valid JSON: %s", exc)
            return None

        img = self._extract_inline_image_bytes(data)
        if img is None:
            self._record("image", "gemini", "error", "response missing inline image bytes")
            logger.error("Gemini image response missing inline image bytes: %s", text[:200])
            return None

        self._record("image", "gemini", "ok")
        return img

    def _gemini_text_model(self, model: str) -> str:
        return model if model.startswith("gemini-") else self.config.get("GEMINI_TEXT_MODEL") or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")

    def _has_openai_key(self) -> bool:
        key = self.config.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            return False
        key = str(key).strip()
        return bool(key) and "your_openai_api_key_here" not in key

    def _extract_topic(self, prompt: str, system_prompt: str) -> str:
        patterns = [
            r"主题[:：]\s*(.+)",
            r"文章主题[:：]\s*(.+)",
            r"Article title:\s*(.+)",
            r"用户输入[:：]\s*(.+)",
        ]
        for text in (prompt, system_prompt):
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    return self._normalize_topic(match.group(1))
        return self._normalize_topic(prompt.strip().splitlines()[0] if prompt.strip() else "AI 编程工具与多智能体")

    def _normalize_topic(self, text: str) -> str:
        topic = str(text).strip()
        if not topic:
            return "AI 编程工具与多智能体"

        for pattern in (r"“([^”]+)”", r'"([^"]+)"', r"『([^』]+)』", r"'([^']+)'"):
            match = re.search(pattern, topic)
            if match:
                topic = match.group(1).strip()
                break

        topic = re.sub(
            r"^(帮我写(?:一篇)?(?:关于)?|请写(?:一篇)?(?:关于)?|请围绕|围绕|关于|写一篇关于)",
            "",
            topic,
        ).strip()
        topic = re.sub(
            r"(的公众号文章|公众号文章|的公众号稿件|公众号稿件|的文章|文章|深度技术文章|技术文章)$",
            "",
            topic,
        ).strip()
        topic = topic.strip("：:，。,.!！?？")
        topic = re.sub(r"\s+", " ", topic)
        return topic[:80] if topic else "AI 编程工具与多智能体"

    def _local_text_fallback(self, prompt: str, system_prompt: str, response_format: str) -> str:
        topic = self._extract_topic(prompt, system_prompt)
        topic_lower = topic.lower()
        is_ai_tool_topic = any(
            keyword in topic_lower
            for keyword in ("ai", "agent", "编程", "代码", "开发", "工程", "cod", "cursor", "copilot", "claude")
        ) or "多智能体" in topic or "智能体" in topic

        if response_format == "json_object":
            title = topic
            if len(title) < 10:
                title = f"主流AI编程工具中的{topic}实践"
            return json.dumps({"title": title[:24]}, ensure_ascii=False)

        if "播客/视频脚本" in system_prompt:
            return (
                "今天我们聊的是主流 AI 编程工具里为什么越来越强调多智能体。"
                "简单说，复杂代码任务不是单轮问答能稳定解决的，它需要有人规划、有人实现、有人审查、有人验证。"
                "把这些角色拆开以后，开发者就能更快完成重构、调试和评审。"
            )

        if "请优化以下草稿" in prompt:
            draft = prompt.split("请优化以下草稿:\n\n", 1)[-1].strip()
            if draft:
                return draft

        if "Create a compelling cover image prompt" in prompt or "cover image prompt" in prompt.lower():
            return (
                f"Create a wide, professional cover illustration for an article about {topic}. "
                "Use a modern software engineering aesthetic, layered workspace metaphor, "
                "multiple agent panels connected by arrows, code snippets, review notes, "
                "and a clean high-contrast editorial style. No text overlay."
            )

        if is_ai_tool_topic:
            return """## 背景介绍

主流 AI 编程工具正在从“单次问答式助手”走向“多智能体协作系统”。对于一线开发者来说，这不是概念升级，而是工作方式变化：需求拆解、上下文检索、代码生成、测试补齐和代码审查，开始被拆分到不同角色中分别完成。

## 原理分析

多智能体的核心不是“多开几个模型窗口”，而是把复杂开发任务拆成多个职责明确的步骤：规划者负责分解目标，执行者负责产出代码，研究者负责查资料，审查者负责做交叉验证。这样做的好处，是把长链路任务里的不确定性压缩到更小的局部，减少单轮生成的偶然性。

[IMAGE: A workflow diagram showing planning, coding, reviewing, and testing agents collaborating on a software task.]

## 主流工具实践

在实际工具里，这种模式通常表现为代码库理解、重构建议、测试生成、PR 审查和文档同步几个环节协同运转。开发者真正受益的地方，不是“模型更聪明”，而是“任务流更像一个小型团队”。

[IMAGE: A side-by-side comparison of single-agent versus multi-agent coding workflow in a developer IDE.]

## 一线开发者怎么用

如果你在处理一个跨文件重构，最适合把任务拆成三类：先让一个角色梳理改动范围，再让一个角色生成第一版实现，最后让另一个角色检查边界条件和测试覆盖。这样做比反复追问一个模型更稳定。

## 局限与边界

多智能体并不自动等于更好。任务拆分不合理会造成协作成本上升，上下文传递不清晰会让结果碎片化，验证环节缺失也会让错误被层层放大。

## 结语

对开发者来说，多智能体的价值在于把软件工程里的分工协作显式化。它更像一种新的工作流，而不只是一个更会聊天的模型。
"""

        return (
            f"围绕“{topic}”撰写一篇结构清晰的技术文章，重点解释背景、原理、实践和局限。"
        )

    def call_llm(self, prompt: str, system_prompt: str = "You are a helpful assistant.", model: str = "gpt-4.1-mini", response_format: str = "text") -> str:
        runtime_result = None
        try:
            runtime_result = self._maybe_call_runtime(
                "text",
                ["call_llm", "complete", "generate", "chat", "invoke", "__call__"],
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                response_format=response_format,
            )
        except Exception as exc:
            self._record("text", "openclaw", "error", str(exc))
            logger.warning("OpenClaw text call failed, falling back to Gemini/OpenAI: %s", exc)

        if runtime_result is not None:
            return self._stringify(runtime_result)

        if self.config.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY"):
            try:
                return self._call_gemini_text(prompt, system_prompt, model, response_format)
            except Exception as exc:
                self._record("text", "gemini", "error", str(exc))
                logger.warning("Gemini text call failed, falling back to OpenAI: %s", exc)

        if not self._has_openai_key():
            self._record("text", "local", "ok")
            return self._local_text_fallback(prompt, system_prompt, response_format)

        try:
            from openai import OpenAI

            client = OpenAI()
            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            }
            if response_format == "json_object":
                kwargs["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            self._record("text", "openai", "ok")
            return content
        except Exception as exc:
            self._record("text", "openai", "error", str(exc))
            self._record("text", "local", "ok")
            return self._local_text_fallback(prompt, system_prompt, response_format)

    def _call_gemini_text(self, prompt: str, system_prompt: str, model: str, response_format: str) -> str:
        api_key = self.config.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        gemini_model = self._gemini_text_model(model)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
        payload: Dict[str, Any] = {
            "systemInstruction": {
                "role": "system",
                "parts": [{"text": system_prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
            },
        }
        if response_format == "json_object":
            payload["generationConfig"]["responseMimeType"] = "application/json"

        status_code, text = self._post_json(url, payload, timeout=60)
        if status_code >= 400:
            raise RuntimeError(f"Gemini request failed with status {status_code}: {text[:300]}")

        try:
            data = json.loads(text)
        except Exception as exc:
            raise RuntimeError(f"Gemini response was not valid JSON: {exc}")
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini response missing candidates: {json.dumps(data, ensure_ascii=False)[:300]}")

        content = candidates[0].get("content", {}) if isinstance(candidates[0], dict) else {}
        parts = content.get("parts", []) if isinstance(content, dict) else []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
        if not text:
            text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini response did not contain text content")
        self._record("text", "gemini", "ok")
        return text

    def search(self, query: str, max_results: int = 3) -> str:
        try:
            runtime_result = self._maybe_call_runtime(
                "search",
                ["search", "web_search", "research", "lookup"],
                query=query,
                max_results=max_results,
            )
        except Exception as exc:
            self._record("search", "openclaw", "error", str(exc))
            logger.warning("OpenClaw search failed, falling back to Tavily: %s", exc)
            runtime_result = None

        if runtime_result is not None:
            return self._stringify(runtime_result)

        api_key = self.config.get("TAVILY_API_KEY") or os.environ.get("TAVILY_API_KEY")
        if not api_key:
            self._record("search", "tavily", "miss", "TAVILY_API_KEY is not set")
            return f"关于 {query} 的基础信息（由于未配置搜索 API，此处为占位符）。"

        try:
            from tavily import TavilyClient

            tavily = TavilyClient(api_key=api_key)
            response = tavily.search(query=query, search_depth="advanced", max_results=max_results)
            context = f"关于 '{query}' 的研究资料：\n\n"
            for result in response.get("results", []):
                context += f"标题: {result.get('title')}\n"
                context += f"内容: {result.get('content')}\n"
                context += f"来源: {result.get('url')}\n\n"
            self._record("search", "tavily", "ok")
            return context
        except Exception as exc:
            self._record("search", "tavily", "error", str(exc))
            logger.error("Tavily search failed: %s", exc)
            return f"搜索失败，仅提供关于 {query} 的基础框架思考。"

    def read_text(self, path: str) -> str:
        try:
            runtime_result = self._maybe_call_runtime(
                "read",
                ["read_file", "read", "open_file", "load_file"],
                path=path,
            )
        except Exception as exc:
            self._record("read", "openclaw", "error", str(exc))
            runtime_result = None

        if runtime_result is not None:
            return self._stringify(runtime_result)

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self._record("read", "local", "ok")
        return content

    def generate_image(self, prompt: str, aspect_ratio: str = "1:1", model: Optional[str] = None) -> Optional[bytes]:
        try:
            runtime_result = self._maybe_call_runtime(
                "image",
                ["generate_image", "create_image", "image_generate", "render_image"],
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                model=model,
            )
        except Exception as exc:
            self._record("image", "openclaw", "error", str(exc))
            runtime_result = None

        if runtime_result is not None:
            if isinstance(runtime_result, bytes):
                return runtime_result
            if isinstance(runtime_result, str) and os.path.exists(runtime_result):
                with open(runtime_result, "rb") as f:
                    return f.read()
            if isinstance(runtime_result, dict):
                if isinstance(runtime_result.get("bytes"), bytes):
                    return runtime_result["bytes"]
                if isinstance(runtime_result.get("path"), str) and os.path.exists(runtime_result["path"]):
                    with open(runtime_result["path"], "rb") as f:
                        return f.read()
            return None

        api_key = self.config.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self._record("image", "gemini", "miss", "GEMINI_API_KEY is not set")
            return None

        models = [model] if model else self._image_model_priority()
        for model_name in models:
            try:
                if model_name.startswith("imagen-"):
                    img = self._call_imagen_predict(api_key, model_name, prompt, aspect_ratio)
                else:
                    img = self._call_gemini_flash_image(api_key, model_name, prompt, aspect_ratio)
                if img is not None:
                    return img
            except Exception as exc:
                self._record("image", "gemini", "error", str(exc))
                logger.error("Image generation failed for model %s: %s", model_name, exc)
        return None

    def _call_gemini_image_review(
        self,
        api_key: str,
        model: str,
        prompt: str,
        image_bytes: bytes,
        aspect_ratio: str,
        image_role: str,
        title: str,
        topic: str,
    ) -> Dict[str, Any]:
        import base64

        review_prompt = (
            "You are a strict visual quality reviewer for a Chinese tech article image.\n"
            "Decide whether the image matches the prompt and is suitable for publication.\n"
            "Return JSON only with keys: approved (boolean), reason (string), score (number 0-1).\n"
            "Reject images that are off-topic, text-heavy, blurry, cluttered, or visually weak.\n"
            f"Image role: {image_role}\n"
            f"Article title: {title}\n"
            f"Topic: {topic}\n"
            f"Prompt: {prompt}\n"
            f"Target aspect ratio: {aspect_ratio}"
        )
        payload = {
            "systemInstruction": {
                "role": "system",
                "parts": [{"text": "You are an exacting multimodal judge."}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": review_prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(image_bytes).decode("utf-8"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        status_code, text = self._post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            payload,
            timeout=90,
        )
        if status_code != 200:
            raise RuntimeError(f"Gemini image review failed with status {status_code}: {text[:300]}")

        try:
            data = json.loads(text)
        except Exception as exc:
            raise RuntimeError(f"Gemini image review response was not valid JSON: {exc}")

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini image review missing candidates: {json.dumps(data, ensure_ascii=False)[:300]}")

        content = candidates[0].get("content", {}) if isinstance(candidates[0], dict) else {}
        parts = content.get("parts", []) if isinstance(content, dict) else []
        text_parts = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
        if not text_parts:
            raise RuntimeError("Gemini image review did not return text content")

        try:
            result = json.loads(text_parts)
        except Exception as exc:
            raise RuntimeError(f"Gemini image review text was not valid JSON: {exc}")
        if not isinstance(result, dict):
            raise RuntimeError("Gemini image review payload must be a JSON object")
        self._record("review", "gemini", "ok")
        return result

    def review_image(
        self,
        prompt: str,
        image_bytes: bytes,
        aspect_ratio: str = "1:1",
        image_role: str = "cover",
        title: str = "",
        topic: str = "",
    ) -> Dict[str, Any]:
        try:
            runtime_result = self._maybe_call_runtime(
                "review",
                ["review_image", "judge_image", "analyze_image", "inspect_image", "vision_review", "vision_analyze"],
                prompt=prompt,
                image_bytes=image_bytes,
                aspect_ratio=aspect_ratio,
                image_role=image_role,
                title=title,
                topic=topic,
            )
        except Exception as exc:
            self._record("review", "openclaw", "error", str(exc))
            logger.warning("OpenClaw image review failed, falling back to Gemini: %s", exc)
            runtime_result = None

        if runtime_result is not None:
            if isinstance(runtime_result, dict):
                result = dict(runtime_result)
                try:
                    score = float(result.get("score")) if result.get("score") is not None else None
                except (TypeError, ValueError):
                    score = None
                approved = result.get("approved")
                if isinstance(approved, str):
                    approved = approved.strip().lower() in {"true", "yes", "approved", "pass"}
                if score is not None and score < 0.85:
                    approved = False
                    reason = str(result.get("reason") or "score below threshold").strip()
                    if "score" not in reason.lower():
                        reason = f"{reason} (score {score:.2f} below 0.85 threshold)"
                    result["reason"] = reason
                result["approved"] = bool(approved)
                result.setdefault("provider", "openclaw")
                return result
            if isinstance(runtime_result, bool):
                return {"approved": runtime_result, "reason": "", "provider": "openclaw"}
            if isinstance(runtime_result, str):
                lowered = runtime_result.strip().lower()
                if lowered in {"true", "approved", "pass", "yes"}:
                    return {"approved": True, "reason": runtime_result, "provider": "openclaw"}
                if lowered in {"false", "rejected", "reject", "no"}:
                    return {"approved": False, "reason": runtime_result, "provider": "openclaw"}
                return {"approved": False, "reason": runtime_result, "provider": "openclaw"}
            return {"approved": False, "reason": self._stringify(runtime_result), "provider": "openclaw"}

        api_key = self.config.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self._record("review", "gemini", "miss", "GEMINI_API_KEY is not set")
            return {"approved": False, "reason": "GEMINI_API_KEY is not set", "provider": "local"}

        review_model = (
            self.config.get("GEMINI_VISION_MODEL")
            or os.environ.get("GEMINI_VISION_MODEL")
            or "gemini-2.5-flash"
        )
        try:
            result = self._call_gemini_image_review(
                api_key,
                str(review_model).strip(),
                prompt,
                image_bytes,
                aspect_ratio,
                image_role,
                title,
                topic,
            )
            try:
                score = float(result.get("score")) if result.get("score") is not None else None
            except (TypeError, ValueError):
                score = None
            if score is not None and score < 0.85:
                result["approved"] = False
                reason = str(result.get("reason") or "score below threshold").strip()
                if "score" not in reason.lower():
                    reason = f"{reason} (score {score:.2f} below 0.85 threshold)"
                result["reason"] = reason
            result.setdefault("provider", "gemini")
            return result
        except Exception as exc:
            self._record("review", "gemini", "error", str(exc))
            logger.error("Gemini image review failed: %s", exc)
            return {"approved": False, "reason": str(exc), "provider": "gemini"}

    def publish_wechat_draft(self, title: str, html: str, thumb_media_id: Optional[str]) -> Optional[Dict[str, Any]]:
        try:
            runtime_result = self._maybe_call_runtime(
                "publish",
                ["publish_wechat_draft", "post_to_draft", "publish_draft", "wechat_post", "publish"],
                title=title,
                html=html,
                thumb_media_id=thumb_media_id,
            )
        except Exception as exc:
            self._record("publish", "openclaw", "error", str(exc))
            logger.warning("OpenClaw publish failed, falling back to WeChat API: %s", exc)
            runtime_result = None

        if runtime_result is not None:
            if isinstance(runtime_result, dict):
                return runtime_result
            return {"status": "success", "platform": "wechat", "draft_id": self._stringify(runtime_result)}

        self._record("publish", "wechat_api", "miss", "native publish capability unavailable")
        return None

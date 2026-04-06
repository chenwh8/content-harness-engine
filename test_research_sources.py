import json
import sys
import types
from types import SimpleNamespace

sys.modules.setdefault("requests", types.ModuleType("requests"))

import agents


class FakeRouter:
    def search(self, query, max_results=3):
        return (
            "标题: Example One\n"
            "内容: First summary.\n"
            "来源: https://example.com/one\n\n"
            "标题: Example Two\n"
            "内容: Second summary.\n"
            "来源: https://example.com/two\n"
        )

    def call_llm(self, prompt, system_prompt="You are a helpful assistant.", model="gpt-4.1-mini", response_format="text"):
        return "这是一个可引用的研究摘要。"


def test_researcher_returns_sources_and_summary(monkeypatch):
    monkeypatch.setattr(agents, "CapabilityRouter", SimpleNamespace(from_config=lambda config: FakeRouter()))
    researcher = agents.ResearcherAgent({})

    result = researcher.process({"topic": "主流ai编程工具中多智能体的应用"})

    assert result["query"] == "主流ai编程工具中多智能体的应用"
    assert result["summary"] == "这是一个可引用的研究摘要。"
    assert len(result["sources"]) == 2
    assert result["sources"][0]["url"].startswith("https://example.com/")

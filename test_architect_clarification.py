import json
import sys
import types
from types import SimpleNamespace

sys.modules.setdefault("requests", types.ModuleType("requests"))

import agents


class FakeRouter:
    def call_llm(self, prompt, system_prompt="You are a helpful assistant.", model="gpt-4.1-mini", response_format="text"):
        payload = {
            "needs_more_info": False,
            "topic": "最近伊朗国际形式与油价、金价的联动",
            "audience": "通用读者",
            "angle": "实践指南",
            "outline": [
                "背景",
                "原理",
                "实践",
                "结论",
            ],
        }
        return json.dumps(payload, ensure_ascii=False)


def test_architect_asks_for_clarification_when_request_is_too_broad(monkeypatch):
    monkeypatch.setattr(agents, "CapabilityRouter", SimpleNamespace(from_config=lambda config: FakeRouter()))
    architect = agents.ArchitectAgent({})

    result = architect.process("帮我写一篇关于最近伊朗国际形式与油价、金价的联动的深度文章，发布到微信公众号", {})

    assert result["needs_more_info"] is True
    assert "受众" in result["message"] or "角度" in result["message"] or "大纲" in result["message"]

import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

sys.modules.setdefault("requests", types.ModuleType("requests"))
yaml_stub = types.ModuleType("yaml")
yaml_stub.safe_load = lambda value: {}
yaml_stub.dump = lambda data, allow_unicode=True, default_flow_style=False: ""
sys.modules.setdefault("yaml", yaml_stub)

import orchestrator as orchestrator_module
from orchestrator import Orchestrator


class FakeRouter:
    def snapshot(self):
        return [{"provider": "fake", "kind": "text"}]


class FakeArchitect:
    def __init__(self, config):
        self.config = config

    def process(self, user_input, context):
        return {
            "needs_more_info": False,
            "requirements": {
                "topic": "主流ai编程工具中多智能体的应用",
                "audience": "一线开发者",
                "tone": "实践导向",
                "platforms": ["wechat"],
                "status": "draft",
            },
        }


class FakeResearcher:
    def __init__(self, config):
        self.config = config

    def process(self, requirements):
        return "research"


class FakeWriterEditor:
    def __init__(self, config):
        self.config = config

    def process(self, requirements, research_context):
        return {
            "title": "主流AI编程工具中的多智能体实践",
            "topic": requirements["topic"],
            "body": "## 背景介绍\n\n正文内容",
            "script": "脚本内容",
            "image_prompts": [],
            "visuals": {},
        }


class FakeVisualist:
    reuse_flags = []

    def __init__(self, config):
        self.config = config

    def process(self, article_data, visuals_dir, reuse_existing_visuals=False):
        self.reuse_flags.append(reuse_existing_visuals)
        return article_data


def test_reuses_most_recent_same_topic_project_and_waits_for_confirmation(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    project_dir = output_dir / "2026-04-04-120000-主流ai编程工具中多智能体的应用"
    visuals_dir = project_dir / "_visuals"
    visuals_dir.mkdir(parents=True)
    (visuals_dir / "visual_0.png").write_bytes(b"cover")
    (project_dir / "main.md").write_text(
        """---
title: 主流AI编程工具中的多智能体实践
topic: 主流ai编程工具中多智能体的应用
date: 2026-04-04
---

# 主流AI编程工具中的多智能体实践
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(orchestrator_module, "CapabilityRouter", SimpleNamespace(from_config=lambda config: FakeRouter()))
    monkeypatch.setattr(orchestrator_module, "ArchitectAgent", FakeArchitect)
    monkeypatch.setattr(orchestrator_module, "ResearcherAgent", FakeResearcher)
    monkeypatch.setattr(orchestrator_module, "WriterEditorAgent", FakeWriterEditor)
    monkeypatch.setattr(orchestrator_module, "VisualistAgent", FakeVisualist)
    monkeypatch.setattr(orchestrator_module, "distribute_content", lambda *args, **kwargs: {"wechat": {"status": "ok"}})
    FakeVisualist.reuse_flags = []

    orch = Orchestrator({"OUTPUT_DIR": str(output_dir)})

    first = orch.handle_input("帮我写一篇关于主流ai编程工具中多智能体的应用的公众号文章")
    assert first["status"] == "asking"
    assert "复用" in first["message"]
    assert str(project_dir) in first["message"]

    second = orch.handle_input("复用")
    assert second["status"] == "completed"
    assert orch.context["project_dir"] == str(project_dir)
    assert orch.context["reuse_existing_project"] is True
    assert FakeVisualist.reuse_flags == [True]
    assert Path(project_dir / "main.md").exists()

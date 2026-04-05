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
                "outline": [
                    "背景：为什么多智能体在 AI 编程工具里越来越重要",
                    "原理：任务拆分、角色分工和上下文管理",
                    "实践：一线开发者怎么用",
                    "边界：质量和协作成本怎么控制",
                ],
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
    assert "大纲" in first["message"]
    assert "确认" in first["message"]

    second = orch.handle_input("确认")
    assert second["status"] == "asking"
    assert "复用" in second["message"]
    assert str(project_dir) in second["message"]

    third = orch.handle_input("复用")
    assert third["status"] == "completed"
    assert "summary" in third
    assert orch.context["project_dir"] == str(project_dir)
    assert orch.context["reuse_existing_project"] is True
    assert FakeVisualist.reuse_flags == [True]
    assert Path(project_dir / "main.md").exists()


def test_reports_progress_and_summary_when_running_end_to_end(tmp_path, monkeypatch):
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

    events = []
    orch = Orchestrator({
        "OUTPUT_DIR": str(output_dir),
        "PROGRESS_CALLBACK": events.append,
    })

    first = orch.handle_input("帮我写一篇关于主流ai编程工具中多智能体的应用的公众号文章")
    assert first["status"] == "asking"
    second = orch.handle_input("确认")
    assert second["status"] == "asking"
    assert "复用" in second["message"]

    third = orch.handle_input("复用")
    assert third["status"] == "completed"
    assert third["summary"]["quality"]["visuals_kept"] >= 1
    assert third["summary"]["distribution"]["wechat"]["status"] == "ok"
    assert any(event["stage"] == "requirements_confirmed" for event in events)
    assert any(event["stage"] == "research_complete" for event in events)
    assert any(event["stage"] == "distribution_complete" for event in events)

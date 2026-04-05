import os
import sys
import types

sys.modules.setdefault("requests", types.ModuleType("requests"))

from agents import VisualistAgent


class FailingRouter:
    def call_llm(self, *args, **kwargs):
        raise AssertionError("Cover prompt generation should not run when reusing visuals")

    def generate_image(self, *args, **kwargs):
        raise AssertionError("Image generation should not run when reusing visuals")


def test_visualist_reuses_existing_images_when_requested(tmp_path):
    visuals_dir = tmp_path / "_visuals"
    visuals_dir.mkdir()
    (visuals_dir / "visual_0.png").write_bytes(b"cover-bytes")
    (visuals_dir / "visual_1.png").write_bytes(b"chapter-bytes")

    agent = VisualistAgent({"CAPABILITY_ROUTER": FailingRouter()})
    article = {
        "title": "主流AI编程工具中的多智能体实践",
        "topic": "主流ai编程工具中多智能体的应用",
        "body": "## 背景介绍\n\n正文内容\n\n[IMAGE: existing chapter image]\n",
        "image_prompts": ["existing chapter image"],
    }

    result = agent.process(article, str(visuals_dir), reuse_existing_visuals=True)

    assert (visuals_dir / "visual_0.png").read_bytes() == b"cover-bytes"
    assert (visuals_dir / "visual_1.png").read_bytes() == b"chapter-bytes"
    assert "![existing chapter image]" in result["body"]
    assert result["visuals"]["visual_0.png"] == b"cover-bytes"
    assert result["visuals"]["visual_1.png"] == b"chapter-bytes"

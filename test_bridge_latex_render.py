import os
from pathlib import Path

from bridge import distribute_content


def test_distribute_content_renders_block_formulas(tmp_path, monkeypatch):
    project_dir = tmp_path / "article"
    visuals_dir = project_dir / "_visuals"
    project_dir.mkdir()
    visuals_dir.mkdir()

    main_md = project_dir / "main.md"
    main_md.write_text(
        "---\n"
        "title: Test\n"
        "platforms:\n"
        "  - wechat\n"
        "---\n"
        "# Test\n\n"
        "$$\n"
        "f(x)=\\sum_{n=-\\infty}^{\\infty} c_n e^{i 2\\pi n x / P}\n"
        "$$\n",
        encoding="utf-8",
    )

    class DummyRouter:
        config = {}

        def publish_wechat_draft(self, title, html, thumb_media_id):
            assert "formula_block_" in html
            assert "$$" not in html
            return {"status": "success", "platform": "wechat", "draft_id": "test"}

    result = distribute_content({"platforms": ["wechat"]}, str(main_md), capability_router=DummyRouter())
    assert result["wechat"]["status"] == "success"
    assert any((visuals_dir / "formulas").glob("formula_block_*.png"))

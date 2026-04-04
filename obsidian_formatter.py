import os
import re
import datetime
import yaml
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ObsidianFormatter:
    """Obsidian 资产化输出：生成符合规范的项目文件夹、Markdown 文件和图片目录。
    
    注意：图片（AI 配图 + LaTeX 公式图）由 Orchestrator 在 VISUALIZING 阶段
    提前生成并保存到 _visuals/ 目录，本模块只负责生成 main.md 文件。
    正文 body 中已经包含了正确的相对路径图片引用（由 Visualist 和 LaTeX renderer 插入）。
    """
    def __init__(self, output_dir: str):
        self.base_output_dir = output_dir
        os.makedirs(self.base_output_dir, exist_ok=True)

    def generate(
        self,
        requirements: Dict[str, Any],
        article_data: Dict[str, Any],
        visuals: Dict[str, bytes],  # 保留兼容性，但图片已由 Orchestrator 保存
        project_dir: Optional[str] = None
    ) -> Dict[str, str]:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")

        raw_title = article_data.get("title", "未命名文章")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", raw_title).strip()[:50]

        # 使用 Orchestrator 预先创建的目录（保证与图片路径一致）
        if project_dir is None:
            dir_name = f"{date_str}-{safe_title}"
            project_dir = os.path.join(self.base_output_dir, dir_name)

        visuals_dir = os.path.join(project_dir, "_visuals")
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(visuals_dir, exist_ok=True)

        # 如果有额外的 visuals bytes（兼容旧流程），保存它们
        for img_name, img_data in visuals.items():
            img_path = os.path.join(visuals_dir, img_name)
            if not os.path.exists(img_path):
                with open(img_path, "wb") as f:
                    f.write(img_data)
                logger.info(f"Saved additional visual: {img_path}")

        # ── YAML Frontmatter ─────────────────────────────────────────────
        frontmatter = {
            "title": raw_title,
            "date": date_str,
            "tags": requirements.get("tags", ["技术", "数学"]),
            "platforms": requirements.get("platforms", ["wechat"]),
            "status": requirements.get("status", "draft"),
            "audience": requirements.get("audience", "通用读者"),
            "tone": requirements.get("tone", "专业且易懂"),
        }
        yaml_content = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)

        # ── 组装 Markdown ────────────────────────────────────────────────
        body = article_data.get("body", "")

        md_content = f"---\n{yaml_content}---\n\n"
        md_content += f"# {raw_title}\n\n"
        md_content += body + "\n\n"
        md_content += "---\n\n"
        md_content += "## 播客/视频脚本\n\n"
        md_content += article_data.get("script", "") + "\n"

        # ── 写入 main.md ─────────────────────────────────────────────────
        main_md_path = os.path.join(project_dir, "main.md")
        with open(main_md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        logger.info(f"Generated Obsidian project at {project_dir}")

        return {
            "project_dir": project_dir,
            "main_md": main_md_path,
            "visuals_dir": visuals_dir
        }

import os
import re
import datetime
import yaml
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ObsidianFormatter:
    """Obsidian 资产化输出：生成符合规范的项目文件夹、Markdown 文件和图片目录。"""
    def __init__(self, output_dir: str):
        self.base_output_dir = output_dir
        os.makedirs(self.base_output_dir, exist_ok=True)

    def generate(self, requirements: Dict[str, Any], article_data: Dict[str, Any], visuals: Dict[str, str]) -> Dict[str, str]:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 处理标题中的特殊字符以生成合法的目录名
        raw_title = article_data.get("title", "未命名文章")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", raw_title).strip()
        dir_name = f"{date_str}-{safe_title}"
        
        project_dir = os.path.join(self.base_output_dir, dir_name)
        visuals_dir = os.path.join(project_dir, "_visuals")
        
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(visuals_dir, exist_ok=True)
        
        # 1. 保存图片到 _visuals 目录
        saved_images = []
        for img_name, img_data in visuals.items():
            img_path = os.path.join(visuals_dir, img_name)
            # 保存图片二进制数据
            with open(img_path, "wb") as f:
                f.write(img_data)
            saved_images.append(img_name)
            logger.info(f"Saved visual to {img_path}")

        # 2. 生成 YAML Frontmatter
        frontmatter = {
            "title": raw_title,
            "date": date_str,
            "tags": requirements.get("tags", ["AI", "Content"]),
            "platforms": requirements.get("platforms", ["wechat"]),
            "status": requirements.get("status", "draft")
        }
        
        yaml_content = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)
        
        # 3. 组装 Markdown 内容
        md_content = f"---\n{yaml_content}---\n\n"
        
        # 插入正文
        md_content += f"# {raw_title}\n\n"
        
        # 插入图片引用（相对路径）
        for img_name in saved_images:
            md_content += f"![{img_name}](./_visuals/{img_name})\n\n"
            
        md_content += article_data.get("body", "") + "\n\n"
        
        # 插入播客/视频脚本模块
        md_content += "## 播客/视频脚本\n\n"
        md_content += article_data.get("script", "") + "\n"
        
        # 4. 写入 main.md
        main_md_path = os.path.join(project_dir, "main.md")
        with open(main_md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        logger.info(f"Generated Obsidian project at {project_dir}")
        
        return {
            "project_dir": project_dir,
            "main_md": main_md_path,
            "visuals_dir": visuals_dir
        }

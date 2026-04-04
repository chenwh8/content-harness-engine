import os
import re
import yaml
import logging
import markdown
from typing import Dict, Any, List
from wechat_poster import WeChatPoster

logger = logging.getLogger(__name__)

def distribute_content(requirements: Dict[str, Any], main_md_path: str) -> Dict[str, Any]:
    """下游分发路由 (Bridge)：读取 YAML platforms 字段，如果是 wechat 则调用 wechat_poster 插件。"""
    
    # 1. 解析 main.md 中的 YAML Frontmatter
    with open(main_md_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # 简单提取 --- 之间的内容
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter_str = parts[1]
            body_content = parts[2]
            try:
                frontmatter = yaml.safe_load(frontmatter_str)
            except yaml.YAMLError as e:
                logger.error(f"Error parsing YAML frontmatter: {e}")
                frontmatter = {}
                body_content = content
        else:
            frontmatter = {}
            body_content = content
    else:
        frontmatter = {}
        body_content = content
        
    platforms: List[str] = frontmatter.get("platforms", [])
    
    results = {}
    
    # 2. 根据 platforms 分发
    if "wechat" in platforms:
        logger.info(f"Distributing to WeChat...")
        
        # Find cover image
        project_dir = os.path.dirname(main_md_path)
        visuals_dir = os.path.join(project_dir, "_visuals")
        cover_image_path = None
        if os.path.exists(visuals_dir):
            for file in os.listdir(visuals_dir):
                if file.endswith(".png") or file.endswith(".jpg"):
                    cover_image_path = os.path.join(visuals_dir, file)
                    break
                    
        # Replace relative image paths with absolute paths for the poster
        def replacer(match):
            rel_path = match.group(1)
            # Remove ./ or ../
            clean_path = rel_path.lstrip("./").lstrip("../")
            abs_path = os.path.join(project_dir, clean_path)
            return match.group(0).replace(rel_path, abs_path)
            
        processed_body = re.sub(r'!\[.*?\]\((.*?)\)', replacer, body_content)
        
        # Convert markdown to HTML
        html_content = markdown.markdown(processed_body)
        
        # We need to upload inline images to WeChat and replace src in HTML
        poster = WeChatPoster()
        
        # Extract img src
        img_pattern = re.compile(r'<img[^>]+src="([^">]+)"')
        for match in img_pattern.finditer(html_content):
            local_src = match.group(1)
            if os.path.exists(local_src):
                try:
                    logger.info(f"Uploading inline image to WeChat: {local_src}")
                    wechat_url = poster._upload_image_for_content(local_src)
                    html_content = html_content.replace(local_src, wechat_url)
                except Exception as e:
                    logger.error(f"Failed to upload inline image: {e}")
        
            title = frontmatter.get("title", "未命名")
        result = poster.post_to_draft(poster._truncate_title(title), html_content, cover_image_path)
        results["wechat"] = result
        
    if "xiaohongshu" in platforms:
        # 预留扩展接口
        logger.info("Xiaohongshu distribution not yet implemented.")
        results["xiaohongshu"] = {"status": "skipped", "platform": "xiaohongshu", "message": "Not implemented"}
        
    return results

import yaml
import logging
from typing import Dict, Any, List

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
            try:
                frontmatter = yaml.safe_load(frontmatter_str)
            except yaml.YAMLError as e:
                logger.error(f"Error parsing YAML frontmatter: {e}")
                frontmatter = {}
        else:
            frontmatter = {}
    else:
        frontmatter = {}
        
    platforms: List[str] = frontmatter.get("platforms", [])
    
    results = {}
    
    # 2. 根据 platforms 分发
    if "wechat" in platforms:
        # 组装标准入参，调用 ClawHub/SkillHub 已有的 wechat_poster 插件
        wechat_input = {
            "title": frontmatter.get("title", "未命名"),
            "content_path": main_md_path,
            # 其他 wechat_poster 需要的参数
        }
        
        # 模拟调用 wechat_poster 插件
        logger.info(f"Calling wechat_poster plugin with input: {wechat_input}")
        # result = call_skill("wechat_poster", wechat_input)
        result = {"status": "success", "platform": "wechat", "message": "Simulated successful post"}
        results["wechat"] = result
        
    if "xiaohongshu" in platforms:
        # 预留扩展接口
        logger.info("Xiaohongshu distribution not yet implemented.")
        results["xiaohongshu"] = {"status": "skipped", "platform": "xiaohongshu", "message": "Not implemented"}
        
    return results

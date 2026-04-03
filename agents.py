import logging
import json
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ArchitectAgent:
    """需求架构师：监听飞书输入，通过多轮对话追问用户需求（受众、调性等），确认后生成 JSON 格式的 requirements。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def process(self, user_input: Optional[str], context: Dict[str, Any]) -> Dict[str, Any]:
        # 简化版：假设用户一次性输入了足够的信息，或者我们直接构造一个 mock requirement
        # 实际实现中，这里会调用 LLM 解析用户输入，判断是否需要追问
        if not user_input or len(user_input) < 10:
            return {
                "needs_more_info": True,
                "message": "请提供更多关于受众、调性、发布平台的信息。"
            }
            
        # 模拟 LLM 提取出的需求
        requirements = {
            "topic": user_input[:50],
            "audience": "通用读者",
            "tone": "专业且易懂",
            "platforms": ["wechat", "xiaohongshu"],
            "status": "draft"
        }
        return {
            "needs_more_info": False,
            "requirements": requirements
        }

class ResearcherAgent:
    """情报员：调用搜索工具获取素材。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def process(self, requirements: Dict[str, Any]) -> str:
        # 模拟调用 Tavily/SerpAPI
        topic = requirements.get("topic", "")
        logger.info(f"Researching topic: {topic}")
        # 实际实现中会调用 search_tool
        return f"这是关于 '{topic}' 的研究资料上下文..."

class WriterEditorAgent:
    """写手与审计：采用 Harness“模块化”理念生成正文。Editor 需对逻辑进行交叉校验。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def process(self, requirements: Dict[str, Any], research_context: str) -> Dict[str, Any]:
        # 模拟 Writer 生成和 Editor 校验
        topic = requirements.get("topic", "未命名主题")
        title = f"深度解析：{topic}"
        
        body = f"这是基于研究资料生成的正文内容。\n\n研究资料摘要：\n{research_context[:100]}"
        
        script = f"大家好，今天我们来聊聊 {topic}..."
        
        return {
            "title": title,
            "body": body,
            "script": script,
            "image_prompts": [f"一张关于 {topic} 的插图，科技感风格"]
        }

class VisualistAgent:
    """配图师：调用 Nano-Banana-Pro API，为文章生成配图，并将图片下载到本地。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("NANO_BANANA_API_KEY")

    def process(self, article_data: Dict[str, Any]) -> Dict[str, str]:
        # 模拟调用 Nano-Banana-Pro API
        prompts = article_data.get("image_prompts", [])
        visuals = {}
        
        for i, prompt in enumerate(prompts):
            # 实际实现中会发送请求并下载图片
            logger.info(f"Generating image for prompt: {prompt}")
            visuals[f"cover_{i}.png"] = f"mock_image_data_for_{prompt}"
            
        return visuals

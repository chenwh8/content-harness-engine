import logging
import json
import os
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 辅助函数：调用 OpenAI 兼容接口 (用于 Architect, Writer, Editor)
# ----------------------------------------------------------------------
def call_llm(prompt: str, system_prompt: str = "You are a helpful assistant.", model: str = "gpt-4.1-mini", response_format: str = "text") -> str:
    try:
        from openai import OpenAI
        # OpenAI client uses OPENAI_API_KEY and OPENAI_BASE_URL from environment automatically
        client = OpenAI()
        
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
        }
        if response_format == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
            
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        raise

# ----------------------------------------------------------------------
# Architect Agent
# ----------------------------------------------------------------------
class ArchitectAgent:
    """需求架构师：监听飞书输入，通过多轮对话追问用户需求（受众、调性等），确认后生成 JSON 格式的 requirements。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def process(self, user_input: Optional[str], context: Dict[str, Any]) -> Dict[str, Any]:
        if not user_input:
            return {"needs_more_info": True, "message": "请输入您想创作的内容主题。"}

        system_prompt = """你是一个内容架构师。你的任务是分析用户的输入，提取内容创作需求。
如果用户输入的信息太少（只有几个字，没有明确主题），请要求用户提供更多信息。
如果用户提供了足够的信息（有明确的主题），请将其结构化为 JSON 格式返回。

JSON 格式要求包含以下字段：
- topic: 创作主题（必须）
- audience: 目标受众（如果用户没说，默认为"通用读者"）
- tone: 内容调性（如果用户没说，默认为"专业且易懂"）
- platforms: 发布平台列表（如果用户没说，默认为["wechat"]）
- status: 状态（默认为"draft"）
- needs_more_info: 布尔值，如果信息不足以开始创作则为 true，否则为 false
- message: 如果 needs_more_info 为 true，这里填写追问用户的话；否则为空字符串。"""

        prompt = f"用户输入: {user_input}"
        
        try:
            response_text = call_llm(prompt, system_prompt, response_format="json_object")
            result = json.loads(response_text)
            
            if result.get("needs_more_info"):
                return {"needs_more_info": True, "message": result.get("message", "请提供更多信息。")}
            
            # 整理 requirements
            requirements = {
                "topic": result.get("topic", user_input[:50]),
                "audience": result.get("audience", "通用读者"),
                "tone": result.get("tone", "专业且易懂"),
                "platforms": result.get("platforms", ["wechat"]),
                "status": result.get("status", "draft")
            }
            return {"needs_more_info": False, "requirements": requirements}
            
        except Exception as e:
            logger.error(f"Architect parsing failed: {e}")
            # Fallback
            return {
                "needs_more_info": False,
                "requirements": {
                    "topic": user_input[:50],
                    "audience": "通用读者",
                    "tone": "专业且易懂",
                    "platforms": ["wechat"],
                    "status": "draft"
                }
            }

# ----------------------------------------------------------------------
# Researcher Agent
# ----------------------------------------------------------------------
class ResearcherAgent:
    """情报员：调用搜索工具获取素材。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("TAVILY_API_KEY") or os.environ.get("TAVILY_API_KEY")

    def process(self, requirements: Dict[str, Any]) -> str:
        topic = requirements.get("topic", "")
        logger.info(f"Researching topic: {topic}")
        
        if not self.api_key:
            logger.warning("TAVILY_API_KEY not found, skipping research.")
            return f"关于 {topic} 的基础信息（由于未配置搜索 API，此处为占位符）。"
            
        try:
            from tavily import TavilyClient
            tavily = TavilyClient(api_key=self.api_key)
            response = tavily.search(query=topic, search_depth="advanced", max_results=3)
            
            context = f"关于 '{topic}' 的研究资料：\n\n"
            for result in response.get("results", []):
                context += f"标题: {result.get('title')}\n"
                context += f"内容: {result.get('content')}\n"
                context += f"来源: {result.get('url')}\n\n"
                
            return context
        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            return f"搜索失败，仅提供关于 {topic} 的基础框架思考。"

# ----------------------------------------------------------------------
# Writer & Editor Agent
# ----------------------------------------------------------------------
class WriterEditorAgent:
    """写手与审计：采用 Harness“模块化”理念生成正文。Editor 需对逻辑进行交叉校验。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def process(self, requirements: Dict[str, Any], research_context: str) -> Dict[str, Any]:
        topic = requirements.get("topic", "未命名主题")
        tone = requirements.get("tone", "专业且易懂")
        audience = requirements.get("audience", "通用读者")
        
        # Writer: Generate Content
        writer_system = (
            f"你是一个精通数学和信号处理的资深技术内容创作者。"
            f"请根据提供的主题和研究资料，写一篇结构清晰、逻辑严谨的深度技术文章。"
            f"调性要求：{tone}，目标受众：{audience}。"
            "要求："
            "1. 必须有一条清晰的主线将全文串联起来，每个章节之间有自然的逻辑过渡；"
            "2. 对数学公式进行本质性推导，不能只列公式而不解释；"
            "3. 所有数学公式必须使用 LaTeX 格式（行内用 $...$，独立公式用 $$...$$）；"
            "4. 每个核心概念必须配有直观解释，帮助读者建立直观图像；"
            "5. 文章长度不少于 2500 字，要有足够的深度和细节；"
            "6. 直接输出正文 Markdown，不要包含文章标题。"
        )
        writer_prompt = (
            f"主题: {topic}\n\n"
            f"用户的具体要求：\n{topic}\n\n"
            f"研究资料（供参考，不要直接拂贴）：\n{research_context}"
        )
        
        logger.info("Writer is generating content...")
        draft_body = call_llm(writer_prompt, writer_system, model="gpt-4.1-mini")
        
        # Editor: Review and refine
        editor_system = (
            "你是一个精通数学和信号处理的技术编辑。请审阅草稿，重点检查："
            "1. 数学公式是否正确（LaTeX 语法、公式逻辑）；"
            "2. 主线逻辑是否清晰，章节过渡是否自然；"
            "3. 对偶性、卷积等核心概念的解释是否准确直观；"
            "4. 语言表达是否严谨且可读。"
            "直接输出修订后的全文 Markdown，不要包含文章标题。"
        )
        editor_prompt = f"请优化以下草稿:\n\n{draft_body}"
        
        logger.info("Editor is reviewing content...")
        final_body = call_llm(editor_prompt, editor_system, model="gpt-4.1-mini")
        
        # Script Writer: Generate podcast/video script
        script_system = "你是一个播客/视频脚本编剧。请根据文章内容，提取核心观点，写一段适合口播的短脚本（约200字）。"
        script_prompt = f"文章内容:\n{final_body}"
        
        logger.info("Generating script...")
        script = call_llm(script_prompt, script_system)
        
        # Generate Title and Image Prompts
        meta_system = "你是一个内容策划。请根据文章内容，生成一个吸引人的标题（不含引号），以及2个用于生成配图的英文Prompt。"
        meta_prompt = f"文章内容:\n{final_body}\n\n请以JSON格式返回：\n{{\"title\": \"...\", \"image_prompts\": [\"prompt1\", \"prompt2\"]}}"
        
        logger.info("Generating metadata...")
        meta_response = call_llm(meta_prompt, meta_system, response_format="json_object")
        try:
            meta_data = json.loads(meta_response)
            title = meta_data.get("title", f"深度解析：{topic}")
            image_prompts = meta_data.get("image_prompts", [f"A professional illustration about {topic}"])
        except:
            title = f"深度解析：{topic}"
            image_prompts = [f"A conceptual illustration of {topic}, high quality, digital art"]
        
        return {
            "title": title,
            "body": final_body,
            "script": script,
            "image_prompts": image_prompts
        }

# ----------------------------------------------------------------------
# Visualist Agent
# ----------------------------------------------------------------------
class VisualistAgent:
    """配图师：调用 Gemini API (支持生图) 为文章生成配图，并将图片下载到本地。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")

    def process(self, article_data: Dict[str, Any]) -> Dict[str, bytes]:
        prompts = article_data.get("image_prompts", [])
        visuals = {}
        
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not found, skipping image generation.")
            # Return a tiny 1x1 transparent PNG as mock
            mock_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDAT\x08\xd7c`\x00\x02\x00\x00\x05\x00\x01^\xf3*:\x00\x00\x00\x00IEND\xaeB`\x82'
            for i in range(len(prompts)):
                visuals[f"cover_{i}.png"] = mock_png
            return visuals
            
        # Call Gemini API for image generation
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        
        # Use imagen-4.0-generate-001 (Nano-Banana-Pro is also available as nano-banana-pro-preview)
        # Prefer imagen-4.0 as it's the stable production model
        imagen_model = "imagen-4.0-generate-001"
        
        for i, prompt in enumerate(prompts):
            logger.info(f"Generating image [{i+1}/{len(prompts)}] with {imagen_model}: {prompt[:60]}...")
            
            imagen_url = f"https://generativelanguage.googleapis.com/v1beta/models/{imagen_model}:predict?key={self.api_key}"
            payload = {
                "instances": [{"prompt": prompt}],
                "parameters": {"sampleCount": 1}
            }
            
            try:
                response = requests.post(imagen_url, headers=headers, json=payload, timeout=90)
                if response.status_code == 200:
                    import base64
                    data = response.json()
                    b64_img = data["predictions"][0]["bytesBase64Encoded"]
                    visuals[f"cover_{i}.png"] = base64.b64decode(b64_img)
                    logger.info(f"Successfully generated image cover_{i}.png")
                else:
                    logger.error(f"Image generation failed ({response.status_code}): {response.text[:200]}")
                    # Fallback to 1x1 transparent PNG placeholder
                    mock_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDAT\x08\xd7c`\x00\x02\x00\x00\x05\x00\x01^\xf3*:\x00\x00\x00\x00IEND\xaeB`\x82'
                    visuals[f"cover_{i}.png"] = mock_png
            except Exception as e:
                logger.error(f"Exception during image generation: {e}")
                mock_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDAT\x08\xd7c`\x00\x02\x00\x00\x05\x00\x01^\xf3*:\x00\x00\x00\x00IEND\xaeB`\x82'
                visuals[f"cover_{i}.png"] = mock_png
                
        return visuals

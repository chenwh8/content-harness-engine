import logging
import json
import os
import re
import requests
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 辅助函数：调用 OpenAI 兼容接口 (用于 Architect, Writer, Editor)
# ----------------------------------------------------------------------
def call_llm(prompt: str, system_prompt: str = "You are a helpful assistant.",
             model: str = "gpt-4.1-mini", response_format: str = "text") -> str:
    try:
        from openai import OpenAI
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
- topic: 创作主题（必须，尽量完整保留用户的原始描述）
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

            requirements = {
                "topic": result.get("topic", user_input[:200]),
                "audience": result.get("audience", "通用读者"),
                "tone": result.get("tone", "专业且易懂"),
                "platforms": result.get("platforms", ["wechat"]),
                "status": result.get("status", "draft")
            }
            return {"needs_more_info": False, "requirements": requirements}

        except Exception as e:
            logger.error(f"Architect parsing failed: {e}")
            return {
                "needs_more_info": False,
                "requirements": {
                    "topic": user_input[:200],
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
        logger.info(f"Researching topic: {topic[:80]}")

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
    """写手与审计：采用 Harness"模块化"理念生成正文。
    
    Writer 生成带 [IMAGE: description] 占位符的正文，
    占位符标记每个章节需要的配图位置和内容描述。
    Editor 对逻辑进行交叉校验并优化。
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def process(self, requirements: Dict[str, Any], research_context: str) -> Dict[str, Any]:
        topic = requirements.get("topic", "未命名主题")
        tone = requirements.get("tone", "专业且易懂")
        audience = requirements.get("audience", "通用读者")

        # ── Writer ──────────────────────────────────────────────────────
        writer_system = f"""你是一个精通数学和信号处理的资深技术内容创作者。
请根据提供的主题和研究资料，写一篇结构清晰、逻辑严谨的深度技术文章。
调性要求：{tone}，目标受众：{audience}。

【核心写作要求】
1. 必须有一条清晰的主线将全文串联起来，每个章节之间有自然的逻辑过渡；
2. 对数学公式进行本质性推导，不能只列公式而不解释其物理/几何意义；
3. 所有数学公式必须使用标准 LaTeX 格式（行内用 $...$，独立公式用 $$...$$）；
4. 每个核心概念必须配有直观解释，帮助读者建立直观图像；
5. 文章长度不少于 2500 字，要有足够的深度和细节；
6. 直接输出正文 Markdown，不要包含文章标题（标题会单独生成）。

【配图占位符规范】
在文章中，每当某个概念或结论特别适合用图来辅助理解时，在该段落之后插入一个配图占位符：
[IMAGE: <用英文描述这张图应该展示什么内容，要具体，例如：A diagram showing the duality between periodic time-domain signal and discrete frequency spectrum, with arrows indicating the Fourier series coefficients>]

配图数量：全文 2-4 张，放在最需要视觉辅助的位置（不要堆在开头或结尾）。
每张图的描述要具体、可视化，能直接作为 AI 生图的 Prompt。

【表格配图规范】
当你在文章中插入包含 3 行及以上数据的对比表格、映射关系表格或分类汇总表格时，
必须在该表格之后紧跟一个专属的表格说明图占位符：
[TABLE_IMAGE: <用英文描述一张能形象说明该表格内容的示意图，要求：可视化、直观、有助于读者理解表格中的规律和关系>]

例如，时域/频域对偶关系表格后，应配：
[TABLE_IMAGE: A 2x2 grid diagram showing the four duality relationships between time-domain and frequency-domain: continuous/aperiodic ↔ continuous/aperiodic, continuous/periodic ↔ discrete/aperiodic, discrete/aperiodic ↔ continuous/periodic, discrete/periodic ↔ discrete/periodic, with color-coded arrows showing the Fourier transform connections]"""

        writer_prompt = (
            f"主题: {topic}\n\n"
            f"用户的具体要求：\n{topic}\n\n"
            f"研究资料（供参考，不要直接复制）：\n{research_context}"
        )

        logger.info("Writer is generating content...")
        draft_body = call_llm(writer_prompt, writer_system, model="gpt-4.1-mini")

        # ── Editor ──────────────────────────────────────────────────────
        editor_system = """你是一个精通数学和信号处理的技术编辑。请审阅草稿，重点检查：
1. 数学公式是否正确（LaTeX 语法、公式逻辑）；
2. 主线逻辑是否清晰，章节过渡是否自然；
3. 对偶性、卷积等核心概念的解释是否准确直观；
4. 语言表达是否严谨且可读；
5. 配图占位符 [IMAGE: ...] 的位置是否合理（不要删除或移动它们，只能微调描述）。

直接输出修订后的全文 Markdown，保留所有 [IMAGE: ...] 占位符，不要包含文章标题。"""

        editor_prompt = f"请优化以下草稿:\n\n{draft_body}"

        logger.info("Editor is reviewing content...")
        final_body = call_llm(editor_prompt, editor_system, model="gpt-4.1-mini")

        # ── Script ──────────────────────────────────────────────────────
        script_system = "你是一个播客/视频脚本编剧。请根据文章内容，提取核心观点，写一段适合口播的短脚本（约200字）。"
        script_prompt = f"文章内容:\n{final_body}"

        logger.info("Generating script...")
        script = call_llm(script_prompt, script_system)

            # ── Metadata ────────────────────────────────────────────
        meta_system = """你是一个全媒体内容策划，擅长为微信公众号写爆款标题。
请根据文章内容，生成一个吸引人的公众号标题。

【标题要求】
1. 长度：15-25个汉字（包含标点符号），不要太短也不要太长
2. 风格：参考以下爆款公式之一，根据文章内容选择最合适的：
   - 悬念式：“为什么XXX？看完这篇文章你就明白了”
   - 利益式：“彻底弄懂XXX，只需这一篇”
   - 数字式：“一文搞懂XXX的N个核心原理”
   - 对比式：“从入门到精通：XXX的完整路径”
   - 知识点式：“XXX的本质，就是这么简单”
3. 不含引号、不含“深度解析”这种老套词
4. 内容准确，能让目标读者一眼看到就想点开

以JSON格式返回：{{"title": "..."}}"""
        meta_prompt = (
            f"文章主题：{topic}\n\n"
            f"文章内容摘要（前500字）：\n{final_body[:500]}"
        )

        logger.info("Generating metadata...")
        meta_response = call_llm(meta_prompt, meta_system, response_format="json_object")
        try:
            meta_data = json.loads(meta_response)
            title = meta_data.get("title", f"彻底弄懂{topic[:10]}，看这一篇就够了")
        except Exception:
             title = f"彻底弄懂{topic[:10]}，看这一篇就够了"

        # 提取所有占位符（[IMAGE: ...] 和 [TABLE_IMAGE: ...]）
        image_placeholders = re.findall(r'\[(?:TABLE_)?IMAGE:\s*(.*?)\]', final_body, re.DOTALL)
        image_prompts = [p.strip() for p in image_placeholders]
        logger.info(f"Found {len(image_prompts)} image placeholders (including table images) in article")

        return {
            "title": title,
            "body": final_body,
            "script": script,
            "image_prompts": image_prompts,
        }


# ----------------------------------------------------------------------
# Visualist Agent
# ----------------------------------------------------------------------
class VisualistAgent:
    """配图师：根据正文中的 [IMAGE: ...] 占位符，调用 Gemini Imagen API 生成配图，
    并将占位符替换为本地图片路径引用。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        self.imagen_model = "imagen-4.0-generate-001"

    def _generate_image(self, prompt: str, aspect_ratio: str = "1:1") -> Optional[bytes]:
        """调用 Gemini Imagen API 生成单张图片，返回 PNG bytes 或 None。
        
        Args:
            prompt: 图片描述
            aspect_ratio: 宽高比，如 "1:1", "9:4", "16:9", "4:3"
        """
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not found, skipping image generation.")
            return None

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.imagen_model}:predict?key={self.api_key}"
        )
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": aspect_ratio,
            }
        }
        try:
            response = requests.post(url, json=payload, timeout=90)
            if response.status_code == 200:
                import base64
                data = response.json()
                b64_img = data["predictions"][0]["bytesBase64Encoded"]
                return base64.b64decode(b64_img)
            else:
                logger.error(f"Image generation failed ({response.status_code}): {response.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"Exception during image generation: {e}")
            return None

    def _build_cover_prompt(self, title: str, topic: str) -> str:
        """为文章生成一个高质量封面图 prompt（小红书/公众号风格，900x383px）"""
        # 调用 LLM 生成专业封面 prompt
        try:
            from openai import OpenAI
            client = OpenAI()
            system = """You are an expert at writing image generation prompts for WeChat article cover images.
The cover must be visually striking, professional, and suitable for a Chinese tech/science article.
Output ONLY the English image generation prompt, nothing else."""
            user_msg = f"""Create a compelling cover image prompt for a WeChat article.
Article title: {title}
Topic: {topic}

Requirements:
- Aspect ratio: 900x383px (wide landscape banner)
- Style: Modern, clean, visually stunning, suitable for a science/math article
- Must convey the essence of the topic visually (NOT just text)
- Use metaphors, abstract visualizations, or beautiful mathematical concepts
- High contrast, vibrant colors, professional quality
- NO text overlays in the image
- Think: what visual metaphor best represents this topic?"""
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg}
                ]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"Failed to generate cover prompt via LLM: {e}, using fallback")
            return (
                f"A stunning wide-format banner image representing '{topic}'. "
                "Abstract mathematical visualization with vibrant colors, "
                "elegant wave patterns, frequency spectrums, and geometric forms. "
                "Modern scientific aesthetic, deep blue and purple gradient background, "
                "glowing mathematical curves. Professional, visually striking, no text."
            )

    def process(self, article_data: Dict[str, Any], visuals_dir: str) -> Dict[str, Any]:
        """
        处理文章中的 [IMAGE: ...] 占位符，并专门生成封面图：
        1. 专门生成高质量封面图（visual_0.png，900x383px 比例）
        2. 为每个 [IMAGE: ...] 占位符生成章节配图（visual_1.png 起）
        3. 将正文中的占位符替换为 Markdown 图片引用

        Args:
            article_data: WriterEditorAgent 的输出
            visuals_dir: 图片保存目录（绝对路径）
        """
        body: str = article_data.get("body", "")
        image_prompts: List[str] = article_data.get("image_prompts", [])
        title: str = article_data.get("title", "")
        topic: str = article_data.get("topic", title)
        visuals: Dict[str, bytes] = {}

        os.makedirs(visuals_dir, exist_ok=True)

        # ── 专门生成封面图（visual_0.png）──────────────────────────────
        cover_filename = "visual_0.png"
        cover_filepath = os.path.join(visuals_dir, cover_filename)
        logger.info(f"Generating dedicated cover image for: {title}")
        cover_prompt = self._build_cover_prompt(title, topic)
        logger.info(f"Cover prompt: {cover_prompt[:100]}...")

        # 封面图使用 aspectRatio 16:9（宽屏横幅，最接近公众号封面 900x383）
        cover_bytes = self._generate_image(cover_prompt, aspect_ratio="16:9")
        if cover_bytes:
            with open(cover_filepath, "wb") as f:
                f.write(cover_bytes)
            visuals[cover_filename] = cover_bytes
            logger.info(f"Cover image saved: {cover_filename} ({len(cover_bytes)} bytes)")
        else:
            logger.warning("Cover image generation failed, will use first article image as fallback")

        # ── 逐一替换 [IMAGE: ...] 占位符（章节配图，从 visual_1 开始）───
        article_img_idx = 1  # 封面图占用 visual_0

        def replace_placeholder(match: re.Match) -> str:
            nonlocal article_img_idx
            prompt = match.group(1).strip()
            idx = article_img_idx
            article_img_idx += 1

            filename = f"visual_{idx}.png"
            filepath = os.path.join(visuals_dir, filename)
            rel_path = f"./_visuals/{filename}"

            logger.info(f"Generating article image [{idx}]: {prompt[:60]}...")
            img_bytes = self._generate_image(prompt)

            if img_bytes:
                with open(filepath, "wb") as f:
                    f.write(img_bytes)
                visuals[filename] = img_bytes
                logger.info(f"Saved article image: {filename} ({len(img_bytes)} bytes)")
                alt_text = prompt[:40] + "..." if len(prompt) > 40 else prompt
                return f"\n\n![{alt_text}]({rel_path})\n\n"
            else:
                logger.warning(f"Article image generation failed for placeholder {idx}, removing.")
                return ""

        # 先处理普通配图 [IMAGE: ...]
        updated_body = re.sub(r'\[IMAGE:\s*(.*?)\]', replace_placeholder, body, flags=re.DOTALL)

        # ── 处理表格配图 [TABLE_IMAGE: ...]（使用 4:3 比例，适合示意图）────────
        def replace_table_image(match: re.Match) -> str:
            nonlocal article_img_idx
            prompt = match.group(1).strip()
            idx = article_img_idx
            article_img_idx += 1

            filename = f"visual_{idx}.png"
            filepath = os.path.join(visuals_dir, filename)
            rel_path = f"./_visuals/{filename}"

            # 表格配图加强 prompt：先清除 LaTeX 公式（Imagen 不识别 LaTeX）
            clean_prompt = re.sub(r'\$[^$]+\$', '', prompt)  # 删除 $...$ 行内公式
            clean_prompt = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', clean_prompt)  # 删除 \cmd{...}
            clean_prompt = re.sub(r'\\[a-zA-Z]+', '', clean_prompt)  # 删除 \cmd
            clean_prompt = re.sub(r'\s+', ' ', clean_prompt).strip()
            enhanced_prompt = (
                f"{clean_prompt}. "
                "Style: clean educational diagram, white or light background, "
                "clear labels, color-coded categories, professional infographic style, "
                "suitable for a science article. High contrast, easy to read."
            )

            logger.info(f"Generating table illustration [{idx}]: {prompt[:60]}...")
            img_bytes = self._generate_image(enhanced_prompt, aspect_ratio="4:3")

            if img_bytes:
                with open(filepath, "wb") as f:
                    f.write(img_bytes)
                visuals[filename] = img_bytes
                logger.info(f"Saved table illustration: {filename} ({len(img_bytes)} bytes)")
                return (
                    f"\n\n<p style=\"text-align:center;color:#888;font-size:12px;margin-top:4px;\">\u56fe：{prompt[:30]}...</p>"
                    f"\n\n![表格示意图]({rel_path})\n\n"
                )
            else:
                logger.warning(f"Table image generation failed for placeholder {idx}, removing.")
                return ""

        updated_body = re.sub(r'\[TABLE_IMAGE:\s*(.*?)\]', replace_table_image, updated_body, flags=re.DOTALL)

        article_data["body"] = updated_body
        article_data["visuals"] = visuals
        return article_data

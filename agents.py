import logging
import json
import os
import re
import struct
import zlib
from typing import Dict, Any, Optional, List

from capabilities import CapabilityRouter

logger = logging.getLogger(__name__)

def _get_router(config: Dict[str, Any]) -> CapabilityRouter:
    router = config.get("CAPABILITY_ROUTER")
    if router is not None:
        return router
    router = CapabilityRouter.from_config(config)
    config["CAPABILITY_ROUTER"] = router
    return router


def call_llm(prompt: str, system_prompt: str = "You are a helpful assistant.",
             model: str = "gpt-4.1-mini", response_format: str = "text") -> str:
    return CapabilityRouter.from_env().call_llm(prompt, system_prompt, model, response_format)


# ----------------------------------------------------------------------
# Architect Agent
# ----------------------------------------------------------------------
class ArchitectAgent:
    """需求架构师：监听飞书输入，通过多轮对话追问用户需求（受众、调性等），确认后生成 JSON 格式的 requirements。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.capabilities = _get_router(config)

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
- outline: 文章大纲（数组，至少 4 条；如果用户没说，请你根据主题生成一份可执行的大纲）
- needs_more_info: 布尔值，如果信息不足以开始创作则为 true，否则为 false
- message: 如果 needs_more_info 为 true，这里填写追问用户的话；否则为空字符串。"""

        prompt = f"用户输入: {user_input}"

        try:
            response_text = self.capabilities.call_llm(prompt, system_prompt, response_format="json_object")
            result = json.loads(response_text)

            if result.get("needs_more_info"):
                return {"needs_more_info": True, "message": result.get("message", "请提供更多信息。")}

            requirements = {
                "topic": result.get("topic", user_input[:200]),
                "audience": result.get("audience", "通用读者"),
                "tone": result.get("tone", "专业且易懂"),
                "platforms": result.get("platforms", ["wechat"]),
                "status": result.get("status", "draft"),
                "outline": result.get("outline", []),
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
                    "status": "draft",
                    "outline": [],
                }
            }


# ----------------------------------------------------------------------
# Researcher Agent
# ----------------------------------------------------------------------
class ResearcherAgent:
    """情报员：调用搜索工具获取素材。"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.capabilities = _get_router(config)

    def process(self, requirements: Dict[str, Any]) -> str:
        topic = requirements.get("topic", "")
        logger.info(f"Researching topic: {topic[:80]}")
        return self.capabilities.search(topic, max_results=3)


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
        self.capabilities = _get_router(config)

    def _topic_is_software_engineering(self, topic: str) -> bool:
        topic_lower = topic.lower()
        software_keywords = [
            "ai", "agent", "智能体", "编程", "代码", "开发", "工程",
            "coding", "cursor", "copilot", "claude code", "vibe coding",
            "tool", "工具", "工作流", "workflow"
        ]
        math_keywords = [
            "傅里叶", "信号", "数学", "卷积", "微积分", "线代", "几何", "概率", "统计"
        ]
        if any(keyword in topic_lower for keyword in math_keywords):
            return False
        return any(keyword in topic_lower for keyword in software_keywords)

    def _build_writer_system_prompt(self, topic: str, tone: str, audience: str) -> str:
        if self._topic_is_software_engineering(topic):
            return f"""你是一个资深软件工程与 AI 编程工具内容创作者。
请根据提供的主题和研究资料，写一篇面向一线开发者的技术文章。
调性要求：{tone}，目标受众：{audience}。

【核心写作要求】
1. 全文必须围绕“背景介绍 -> 原理分析 -> 主流工具实践 -> 实践建议 -> 局限与建议 -> 结论”展开；
2. 背景介绍要说明为什么多智能体在 AI 编程工具中开始变重要；
3. 原理分析要讲清任务拆分、角色分工、上下文管理、并行协作和验证闭环；
4. 实践部分要结合主流 AI 编程工具的工作流，给出可执行的实践建议，不要空谈概念；
5. 重点解释软件工程中的决策、协作、调试和评审流程，不要强行引入数学公式；
6. 文章长度不少于 2200 字，要有足够的深度和细节；
7. 直接输出正文 Markdown，不要包含文章标题（标题会单独生成）。

【配图占位符规范】
在适合图解的位置插入 [IMAGE: ...] 占位符，描述要具体、可直接用于生成配图。
全文建议 2-4 张图，优先放在原理图、流程图、对比图附近。

【表格配图规范】
如果插入 3 行及以上表格，在表格后追加 [TABLE_IMAGE: ...] 占位符，帮助解释表格中的关系。"""

        return f"""你是一个专业技术内容创作者。
请根据提供的主题和研究资料，写一篇结构清晰、逻辑严谨的深度技术文章。
调性要求：{tone}，目标受众：{audience}。

【核心写作要求】
1. 必须有一条清晰的主线将全文串联起来，每个章节之间有自然的逻辑过渡；
2. 文章要围绕主题本身展开，优先解释背景、原理、实践和局限；
3. 如果主题涉及数学或算法，再使用 LaTeX 推导和公式解释；
4. 每个核心概念必须配有直观解释，帮助读者建立直观图像；
5. 文章长度不少于 2200 字，要有足够的深度和细节；
6. 直接输出正文 Markdown，不要包含文章标题（标题会单独生成）。

【配图占位符规范】
在文章中，每当某个概念或结论特别适合用图来辅助理解时，在该段落之后插入一个配图占位符：
[IMAGE: <用英文描述这张图应该展示什么内容，要具体>]

配图数量：全文 2-4 张，放在最需要视觉辅助的位置。

【表格配图规范】
当你在文章中插入包含 3 行及以上数据的对比表格、映射关系表格或分类汇总表格时，
必须在该表格之后紧跟一个专属的表格说明图占位符：
[TABLE_IMAGE: <用英文描述一张能形象说明该表格内容的示意图>]"""

    def _build_editor_system_prompt(self, topic: str) -> str:
        if self._topic_is_software_engineering(topic):
            return """你是一个资深软件工程技术编辑。请审阅草稿，重点检查：
1. 背景介绍是否交代了问题为什么重要；
2. 原理分析是否清楚解释了任务拆分、角色分工、上下文管理、并行协作和验证闭环；
3. 主流工具实践是否贴近一线开发者的真实工作流；
4. 实践建议和局限是否具体、可执行；
5. 语言表达是否严谨且可读；
6. 配图占位符 [IMAGE: ...] 的位置是否合理（不要删除或移动它们，只能微调描述）。

直接输出修订后的全文 Markdown，保留所有 [IMAGE: ...] 占位符，不要包含文章标题。"""

        return """你是一个技术编辑。请审阅草稿，重点检查：
1. 主线逻辑是否清晰，章节过渡是否自然；
2. 核心概念解释是否准确直观；
3. 语言表达是否严谨且可读；
4. 配图占位符 [IMAGE: ...] 的位置是否合理（不要删除或移动它们，只能微调描述）。

直接输出修订后的全文 Markdown，保留所有 [IMAGE: ...] 占位符，不要包含文章标题。"""

    def _build_title_candidate_system_prompt(self, topic: str, tone: str, audience: str) -> str:
        if self._topic_is_software_engineering(topic):
            return f"""你是微信公众号标题策划，擅长为一线开发者写“准确且有点击欲”的标题。
请围绕主题生成 5 个标题候选，要求：
1. 保留核心关键词：AI 编程工具、多智能体、开发流程、工程实践等，只取最关键的词，不要堆砌；
2. 语气自然，不要夸张，不要标题党，不要出现“震惊”“必看”“颠覆全网”等套路词；
3. 长度优先控制在 15-24 个汉字，适合公众号卡片展示；
4. 候选之间要有明显差异，覆盖悬念型、利益型、判断型、结果型几种方向，但都要准确；
5. 目标受众：{audience}，调性：{tone}；
6. 只返回 JSON：{{"titles": ["...", "..."]}}。"""

        return f"""你是微信公众号标题策划，擅长写准确且有点击欲的标题。
请围绕主题生成 5 个标题候选，要求：
1. 保留核心关键词，不要堆砌；
2. 语气自然，不要夸张，不要标题党；
3. 长度优先控制在 15-24 个汉字，适合公众号卡片展示；
4. 候选之间要有明显差异；
5. 目标受众：{audience}，调性：{tone}；
6. 只返回 JSON：{{"titles": ["...", "..."]}}。"""

    def _build_title_picker_system_prompt(self, topic: str, tone: str, audience: str) -> str:
        if self._topic_is_software_engineering(topic):
            return f"""你是微信公众号标题编辑，负责从候选标题中选出最适合发布的一条。
选择标准按优先级排序：
1. 准确反映文章内容，不跑题；
2. 适合公众号卡片，读起来顺；
3. 有一定点击欲，但不浮夸；
4. 尽量保留“AI 编程工具”“多智能体”“开发流程”这类核心词；
5. 长度优先控制在 15-24 个汉字。
目标受众：{audience}，调性：{tone}。
只返回 JSON：{{"title": "..."}}。"""

        return f"""你是微信公众号标题编辑，负责从候选标题中选出最适合发布的一条。
选择标准按优先级排序：
1. 准确反映文章内容，不跑题；
2. 适合公众号卡片，读起来顺；
3. 有一定点击欲，但不浮夸；
4. 长度优先控制在 15-24 个汉字。
目标受众：{audience}，调性：{tone}。
只返回 JSON：{{"title": "..."}}。"""

    def _fallback_title_candidates(self, topic: str) -> List[str]:
        base = topic.strip() or "AI编程工具中的多智能体"
        if self._topic_is_software_engineering(topic):
            return [
                f"AI编程工具为什么都开始用多智能体",
                f"多智能体正在重塑AI编程工具的工作流",
                f"一线开发者该怎么用多智能体做开发",
                f"AI编程新范式：多智能体如何改变流程",
                f"主流AI编程工具里的多智能体实践",
            ]
        return [
            f"彻底弄懂{base}",
            f"{base}，到底解决了什么问题",
            f"{base}的关键变化",
            f"为什么{base}越来越重要",
            f"{base}的实践路线",
        ]

    def _normalize_title_text(self, text: str) -> str:
        value = re.sub(r"\s+", " ", str(text or "").strip())
        value = value.strip("“”\"'`")
        return value

    def _dedupe_titles(self, titles: List[str]) -> List[str]:
        seen = set()
        result = []
        for title in titles:
            normalized = self._normalize_title_text(title)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(normalized)
        return result

    def _parse_title_list(self, response_text: str) -> List[str]:
        data = json.loads(response_text)
        if isinstance(data, dict):
            raw_titles = data.get("titles") or data.get("candidates") or data.get("items") or []
            if isinstance(raw_titles, str):
                raw_titles = [raw_titles]
            if isinstance(raw_titles, list):
                return self._dedupe_titles([str(item) for item in raw_titles])
        return []

    def _generate_title_candidates(
        self,
        topic: str,
        tone: str,
        audience: str,
        article_body: str,
    ) -> List[str]:
        system_prompt = self._build_title_candidate_system_prompt(topic, tone, audience)
        prompt = (
            f"文章主题：{topic}\n\n"
            f"目标受众：{audience}\n"
            f"内容调性：{tone}\n\n"
            f"文章摘要（前800字）：\n{article_body[:800]}\n\n"
            "请给出 5 个公众号标题候选，JSON 里只放 titles 数组。"
        )

        try:
            response = self.capabilities.call_llm(prompt, system_prompt, response_format="json_object")
            candidates = self._parse_title_list(response)
            if candidates:
                return candidates[:7]
        except Exception as exc:
            logger.warning("Title candidate generation failed: %s", exc)
        return self._fallback_title_candidates(topic)

    def _pick_best_title(
        self,
        topic: str,
        tone: str,
        audience: str,
        article_body: str,
        candidates: List[str],
    ) -> str:
        candidate_block = "\n".join(f"- {title}" for title in candidates)
        system_prompt = self._build_title_picker_system_prompt(topic, tone, audience)
        prompt = (
            f"文章主题：{topic}\n\n"
            f"文章摘要（前800字）：\n{article_body[:800]}\n\n"
            f"候选标题：\n{candidate_block}\n\n"
            "请从候选标题中选出一个最适合公众号发布的标题，只返回 JSON。"
        )

        try:
            response = self.capabilities.call_llm(prompt, system_prompt, response_format="json_object")
            data = json.loads(response)
            if isinstance(data, dict):
                title = self._normalize_title_text(data.get("title") or data.get("selected_title") or "")
                if title and title in candidates:
                    return title
        except Exception as exc:
            logger.warning("Title picking failed: %s", exc)

        scored = sorted(candidates, key=lambda item: self._score_title_candidate(item, topic), reverse=True)
        if scored:
            return scored[0]
        return f"主流AI编程工具中的{topic[:10]}实践"

    def _score_title_candidate(self, title: str, topic: str) -> tuple[int, int, int, int]:
        normalized = self._normalize_title_text(title)
        topic_text = self._normalize_title_text(topic)
        score = 0
        if any(keyword in normalized for keyword in ("AI", "ai", "智能体", "编程", "开发", "流程", "工具")):
            score += 20
        if "多智能体" in normalized:
            score += 18
        if "工作流" in normalized:
            score += 14
        if "重塑" in normalized or "改变" in normalized or "重构" in normalized:
            score += 12
        if "开发者" in normalized:
            score += 6
        if "为什么" in normalized or "怎么" in normalized or "如何" in normalized:
            score += 6
        if "正在" in normalized:
            score += 4
        if len(normalized) <= 24:
            score += 8
        elif len(normalized) <= 28:
            score += 4
        if len(normalized.encode("utf-8")) <= int(os.environ.get("WECHAT_TITLE_MAX_BYTES", "65")):
            score += 4
        if topic_text and all(word in normalized for word in ("AI", "多智能体") if word):
            score += 4
        if normalized == topic_text:
            score -= 20
        return (score, -len(normalized), -len(normalized.encode("utf-8")), -normalized.count("的"))

    def _fit_title_for_publish(self, title: str, candidates: List[str]) -> str:
        current = self._normalize_title_text(title)
        if not current:
            current = candidates[0] if candidates else "未命名文章"

        max_bytes = int(os.environ.get("WECHAT_TITLE_MAX_BYTES", "65"))
        if len(current.encode("utf-8")) <= max_bytes:
            return current

        for candidate in candidates:
            if len(candidate.encode("utf-8")) <= max_bytes:
                return candidate

        while len(current.encode("utf-8")) > max_bytes and current:
            current = current[:-1]
        return current.strip("：:，。,.!！?？")

    def process(self, requirements: Dict[str, Any], research_context: str) -> Dict[str, Any]:
        topic = requirements.get("topic", "未命名主题")
        tone = requirements.get("tone", "专业且易懂")
        audience = requirements.get("audience", "通用读者")

        # ── Writer ──────────────────────────────────────────────────────
        writer_system = self._build_writer_system_prompt(topic, tone, audience)

        writer_prompt = (
            f"主题: {topic}\n\n"
            f"用户的具体要求：\n{topic}\n\n"
            f"研究资料（供参考，不要直接复制）：\n{research_context}"
        )

        logger.info("Writer is generating content...")
        draft_body = self.capabilities.call_llm(writer_prompt, writer_system, model="gpt-4.1-mini")

        # ── Editor ──────────────────────────────────────────────────────
        editor_system = self._build_editor_system_prompt(topic)

        editor_prompt = f"请优化以下草稿:\n\n{draft_body}"

        logger.info("Editor is reviewing content...")
        final_body = self.capabilities.call_llm(editor_prompt, editor_system, model="gpt-4.1-mini")

        # ── Script ──────────────────────────────────────────────────────
        script_system = "你是一个播客/视频脚本编剧。请根据文章内容，提取核心观点，写一段适合口播的短脚本（约200字）。"
        script_prompt = f"文章内容:\n{final_body}"

        logger.info("Generating script...")
        script = self.capabilities.call_llm(script_prompt, script_system)

            # ── Metadata ────────────────────────────────────────────
        logger.info("Generating metadata...")
        title_candidates = self._generate_title_candidates(topic, tone, audience, final_body)
        title = self._pick_best_title(topic, tone, audience, final_body, title_candidates)
        title = self._fit_title_for_publish(title, title_candidates)

        # 提取所有占位符（[IMAGE: ...] 和 [TABLE_IMAGE: ...]）
        image_placeholders = re.findall(r'\[(?:TABLE_)?IMAGE:\s*(.*?)\]', final_body, re.DOTALL)
        image_prompts = [p.strip() for p in image_placeholders]
        logger.info(f"Found {len(image_prompts)} image placeholders (including table images) in article")

        return {
            "title": title,
            "topic": topic,
            "body": final_body,
            "script": script,
            "image_prompts": image_prompts,
            "title_candidates": title_candidates,
        }


# ----------------------------------------------------------------------
# Visualist Agent
# ----------------------------------------------------------------------
class VisualistAgent:
    """配图师：根据正文中的 [IMAGE: ...] 占位符，调用 Gemini Imagen API 生成配图，
    并将占位符替换为本地图片路径引用。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.capabilities = _get_router(config)

    def _generate_image(self, prompt: str, aspect_ratio: str = "1:1", model: Optional[str] = None) -> Optional[bytes]:
        """Generate an image through the capability router."""
        return self.capabilities.generate_image(prompt, aspect_ratio, model=model)

    def _image_model_priority(self) -> List[str]:
        if hasattr(self.capabilities, "image_model_priority"):
            models = list(self.capabilities.image_model_priority())
        else:
            models = [
                "imagen-4.0-fast-generate-001",
                "imagen-4.0-generate-001",
                "imagen-4.0-ultra-generate-001",
            ]

        models = [str(model).strip() for model in models if str(model).strip()]
        if not models:
            models = [
                "imagen-4.0-fast-generate-001",
                "imagen-4.0-generate-001",
                "imagen-4.0-ultra-generate-001",
            ]
        while len(models) < 3:
            models.append(models[-1])
        return models[:3]

    def _clean_visual_subject(self, prompt: str) -> str:
        subject = re.sub(r"\s+", " ", str(prompt or "").strip())
        subject = re.sub(
            r"(?i)\b(flowchart|workflow diagram|diagram|table|labels?|labelled?|arrows?|numbers?|text overlays?|text|watermark|logo|screenshot|ui mockup|table grid|cells?|rows?|columns?)\b",
            "",
            subject,
        )
        subject = re.sub(r"\s+", " ", subject).strip(" .,:;，。；：")
        return subject

    def _visual_style_guidance(self, image_role: str, title: str, topic: str, subject: str) -> str:
        topic_text = topic or title or subject or "the article topic"
        if image_role == "cover":
            return (
                f"Style: wide editorial illustration banner for a Chinese tech article about {topic_text}. "
                "Use an abstract multi-agent software collaboration metaphor with code windows, connected nodes, and polished geometric shapes. "
                "Make it look publication-ready and modern. "
                "No text, no labels, no numbers, no watermarks, no logos, no screenshots, no UI mockups, no arrows with words."
            )
        if image_role == "table":
            return (
                f"Style: clean comparison infographic for a Chinese tech article about {topic_text}. "
                "Use card-based or panel-based comparison blocks with icons and color accents rather than a literal table. "
                "Keep it editorial and readable. "
                "No text, no labels, no numbers, no watermarks, no logos, no screenshots, no table grid."
            )
        return (
            f"Style: conceptual illustration for a Chinese tech article about {topic_text}. "
            f"Visualize the idea suggested by: {subject or topic_text}. "
            "Use icons, shapes, nodes, and simplified connectors instead of a literal flowchart. "
            "No text, no labels, no numbers, no watermarks, no logos, no screenshots."
        )

    def _prepare_visual_prompt(self, prompt: str, image_role: str, title: str, topic: str) -> str:
        subject = self._clean_visual_subject(prompt)
        if image_role == "cover":
            base = (
                f"Wide editorial banner about {topic or title or 'the article topic'}. "
                "Multi-agent software team collaborating around planning, coding, review, and testing. "
                "Use abstract collaboration visuals, code windows, connected nodes, and polished geometric shapes."
            )
        elif image_role == "table":
            base = (
                f"Comparison infographic about {topic or title or 'the article topic'}. "
                f"Summarize this idea with icon-based panels or cards: {subject or prompt}."
            )
        else:
            base = (
                f"Conceptual illustration about {topic or title or 'the article topic'}. "
                f"Visualize this idea with icons and simplified connectors: {subject or prompt}."
            )

        return f"{base} {self._visual_style_guidance(image_role, title, topic, subject)}"

    def _review_image(
        self,
        prompt: str,
        image_bytes: bytes,
        aspect_ratio: str,
        image_role: str,
        title: str,
        topic: str,
    ) -> Dict[str, Any]:
        if hasattr(self.capabilities, "review_image"):
            result = self.capabilities.review_image(
                prompt=prompt,
                image_bytes=image_bytes,
                aspect_ratio=aspect_ratio,
                image_role=image_role,
                title=title,
                topic=topic,
            )
            if isinstance(result, dict):
                return result
            if isinstance(result, bool):
                return {"approved": result, "reason": "", "provider": "openclaw"}
            return {"approved": False, "reason": str(result), "provider": "openclaw"}
        logger.warning("Visual review capability unavailable; rejecting image by default")
        return {"approved": False, "reason": "visual review capability unavailable", "provider": "local"}

    def _review_approved(self, review_result: Dict[str, Any]) -> bool:
        value = review_result.get("approved")
        if isinstance(value, bool):
            if not value:
                return False
        if isinstance(value, str):
            if value.strip().lower() not in {"true", "yes", "approved", "pass"}:
                return False
        try:
            score = float(review_result.get("score")) if review_result.get("score") is not None else None
        except (TypeError, ValueError):
            score = None
        if score is not None and score < 0.85:
            return False
        return bool(value)

    def _review_reason(self, review_result: Dict[str, Any]) -> str:
        for key in ("reason", "message", "detail", "feedback"):
            value = review_result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        score = review_result.get("score")
        if score is not None:
            return f"visual review rejected the image (score={score})"
        return "visual review rejected the image"

    def _generate_verified_image(
        self,
        prompt: str,
        aspect_ratio: str,
        title: str,
        topic: str,
        image_role: str,
    ) -> Optional[bytes]:
        attempts = self._image_model_priority()
        last_reason = ""
        for index, model in enumerate(attempts, start=1):
            attempt_prompt = prompt
            if index > 1 and last_reason:
                attempt_prompt = (
                    f"{prompt}\n\n"
                    f"Previous attempt failed visual review because: {last_reason}. "
                    "Regenerate a cleaner, more relevant image that fixes the issues."
                )

            logger.info(
                "Generating %s image attempt %d with model %s",
                image_role,
                index,
                model,
            )
            img_bytes = self._generate_image(attempt_prompt, aspect_ratio=aspect_ratio, model=model)
            if not img_bytes:
                last_reason = "image generation returned no bytes"
                continue

            review = self._review_image(
                prompt=prompt,
                image_bytes=img_bytes,
                aspect_ratio=aspect_ratio,
                image_role=image_role,
                title=title,
                topic=topic,
            )
            if self._review_approved(review):
                return img_bytes

            last_reason = self._review_reason(review)
            logger.warning(
                "%s image attempt %d rejected: %s",
                image_role,
                index,
                last_reason,
            )

        logger.warning("%s image discarded after three failed attempts", image_role)
        return None

    def _fallback_image_bytes(self, width: int = 1200, height: int = 675) -> bytes:
        """Create a simple solid-color PNG without external dependencies."""

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + tag
                + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        r, g, b = 247, 250, 252
        scanline = b"\x00" + bytes([r, g, b, 255]) * width
        raw = scanline * height
        png = [b"\x89PNG\r\n\x1a\n"]
        png.append(
            chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0),
            )
        )
        png.append(chunk(b"IDAT", zlib.compress(raw, level=6)))
        png.append(chunk(b"IEND", b""))
        return b"".join(png)

    def _build_cover_prompt(self, title: str, topic: str) -> str:
        """为文章生成一个高质量封面图 prompt（小红书/公众号风格，900x383px）"""
        # 调用 LLM 生成专业封面 prompt
        try:
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
            return self.capabilities.call_llm(user_msg, system, model="gpt-4.1-mini").strip()
        except Exception as e:
            logger.warning(f"Failed to generate cover prompt via router: {e}, using fallback")
            return (
                f"A stunning wide-format banner image representing '{topic}'. "
                "Abstract multi-agent software collaboration visualization with vibrant colors, "
                "connected nodes, code windows, and polished geometric forms. "
                "Modern editorial tech aesthetic, deep blue and purple gradient background, "
                "professional, publication-ready, no text, no labels, no numbers, no watermarks."
            )

    def process(
        self,
        article_data: Dict[str, Any],
        visuals_dir: str,
        reuse_existing_visuals: bool = False,
    ) -> Dict[str, Any]:
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
        image_request_counts = {
            "cover": 1,
            "article": len(re.findall(r"\[IMAGE:\s*(.*?)\]", body, flags=re.DOTALL)),
            "table": len(re.findall(r"\[TABLE_IMAGE:\s*(.*?)\]", body, flags=re.DOTALL)),
        }

        os.makedirs(visuals_dir, exist_ok=True)

        def load_existing_or_generate(
            filename: str,
            generator,
            fallback_width: int,
            fallback_height: int,
            reuse: bool,
            logger_message: str,
            fallback_message: str,
            discard_on_failure: bool = False,
        ) -> bytes:
            filepath = os.path.join(visuals_dir, filename)
            if reuse and os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    data = f.read()
                visuals[filename] = data
                logger.info("Reused existing visual: %s", filename)
                return data

            img_bytes = generator()
            if img_bytes:
                with open(filepath, "wb") as f:
                    f.write(img_bytes)
                visuals[filename] = img_bytes
                logger.info(logger_message, filename, len(img_bytes))
                return img_bytes

            if discard_on_failure:
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                visuals.pop(filename, None)
                logger.warning(fallback_message)
                return None

            fallback_bytes = self._fallback_image_bytes(fallback_width, fallback_height)
            with open(filepath, "wb") as f:
                f.write(fallback_bytes)
            visuals[filename] = fallback_bytes
            logger.warning(fallback_message)
            return fallback_bytes

        # ── 专门生成封面图（visual_0.png）──────────────────────────────
        cover_filename = "visual_0.png"
        logger.info(f"Preparing dedicated cover image for: {title}")

        # 封面图使用 aspectRatio 16:9（宽屏横幅，最接近公众号封面 900x383）
        load_existing_or_generate(
            cover_filename,
            lambda: self._generate_verified_image(
                self._prepare_visual_prompt(self._build_cover_prompt(title, topic), "cover", title, topic),
                aspect_ratio="16:9",
                title=title,
                topic=topic,
                image_role="cover",
            ),
            1200,
            675,
            reuse_existing_visuals,
            "Cover image saved: %s (%d bytes)",
            "Cover image generation failed after three attempts; discarded cover image",
            discard_on_failure=True,
        )

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
            load_existing_or_generate(
                filename,
                lambda: self._generate_verified_image(
                    self._prepare_visual_prompt(prompt, "article", title, topic),
                    aspect_ratio="1:1",
                    title=title,
                    topic=topic,
                    image_role="article",
                ),
                960,
                540,
                reuse_existing_visuals,
                "Saved article image: %s (%d bytes)",
                f"Article image generation failed for placeholder {idx} after three attempts; discarded image.",
                discard_on_failure=True,
            )
            alt_text = prompt[:40] + "..." if len(prompt) > 40 else prompt
            if os.path.exists(filepath):
                return f"\n\n![{alt_text}]({rel_path})\n\n"
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
            enhanced_prompt = self._prepare_visual_prompt(clean_prompt, "table", title, topic)

            logger.info(f"Generating table illustration [{idx}]: {prompt[:60]}...")
            load_existing_or_generate(
                filename,
                lambda: self._generate_verified_image(
                    enhanced_prompt,
                    aspect_ratio="4:3",
                    title=title,
                    topic=topic,
                    image_role="table",
                ),
                960,
                720,
                reuse_existing_visuals,
                "Saved table illustration: %s (%d bytes)",
                f"Table image generation failed for placeholder {idx} after three attempts; discarded image.",
                discard_on_failure=True,
            )
            if not os.path.exists(filepath):
                return ""
            return (
                f"\n\n<p style=\"text-align:center;color:#888;font-size:12px;margin-top:4px;\">\u56fe：{prompt[:30]}...</p>"
                f"\n\n![表格示意图]({rel_path})\n\n"
            )

        updated_body = re.sub(r'\[TABLE_IMAGE:\s*(.*?)\]', replace_table_image, updated_body, flags=re.DOTALL)

        article_data["body"] = updated_body
        article_data["visuals"] = visuals
        article_data["visual_report"] = {
            "requested": image_request_counts,
            "kept": {
                "cover": 1 if os.path.exists(os.path.join(visuals_dir, "visual_0.png")) else 0,
                "article_or_table": max(len(visuals) - (1 if os.path.exists(os.path.join(visuals_dir, "visual_0.png")) else 0), 0),
                "total": len(visuals),
            },
            "discarded": {
                "total": max(sum(image_request_counts.values()) - len(visuals), 0),
            },
            "reuse_existing_visuals": reuse_existing_visuals,
            "files": sorted(visuals.keys()),
        }
        return article_data

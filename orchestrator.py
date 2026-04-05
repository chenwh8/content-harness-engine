import logging
import json
import os
import re
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional

from agents import ArchitectAgent, ResearcherAgent, WriterEditorAgent, VisualistAgent
from capabilities import CapabilityRouter
from obsidian_formatter import ObsidianFormatter
from bridge import distribute_content

try:
    import yaml
except ImportError:  # pragma: no cover - optional in minimal environments
    yaml = None

logger = logging.getLogger(__name__)

class State(Enum):
    IDLE = "IDLE"
    COLLECTING = "COLLECTING"
    AWAITING_REUSE_DECISION = "AWAITING_REUSE_DECISION"
    RESEARCHING = "RESEARCHING"
    WRITING = "WRITING"
    VISUALIZING = "VISUALIZING"
    FORMATTING = "FORMATTING"
    DISTRIBUTING = "DISTRIBUTING"
    DONE = "DONE"
    ERROR = "ERROR"

class Orchestrator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.capabilities = CapabilityRouter.from_config(self.config)
        self.config["CAPABILITY_ROUTER"] = self.capabilities
        self.state = State.IDLE
        self.context: Dict[str, Any] = {}

        # Initialize agents
        self.architect = ArchitectAgent(config)
        self.researcher = ResearcherAgent(config)
        self.writer_editor = WriterEditorAgent(config)
        self.visualist = VisualistAgent(config)

        self.output_dir = config.get("OUTPUT_DIR", "./output")
        self.formatter = ObsidianFormatter(self.output_dir)

    def _normalize_topic(self, text: str) -> str:
        topic = str(text or "").strip()
        if not topic:
            return ""
        for pattern in (r"“([^”]+)”", r'"([^"]+)"', r"『([^』]+)』", r"'([^']+)'"):
            match = re.search(pattern, topic)
            if match:
                topic = match.group(1).strip()
                break
        topic = re.sub(
            r"^(帮我写(?:一篇)?(?:关于)?|请写(?:一篇)?(?:关于)?|请围绕|围绕|关于|写一篇关于)",
            "",
            topic,
        ).strip()
        topic = re.sub(
            r"(的公众号文章|公众号文章|的公众号稿件|公众号稿件|的文章|文章|深度技术文章|技术文章)$",
            "",
            topic,
        ).strip()
        topic = topic.strip("：:，。,.!！?？")
        topic = re.sub(r"\s+", " ", topic)
        return topic.lower()

    def _parse_main_metadata(self, main_md_path: str) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        try:
            with open(main_md_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return metadata

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                if yaml is not None:
                    try:
                        data = yaml.safe_load(frontmatter) or {}
                        for key in ("title", "topic"):
                            value = data.get(key)
                            if value:
                                metadata[key] = str(value)
                        if metadata:
                            return metadata
                    except Exception:
                        pass
                for key in ("title", "topic"):
                    match = re.search(rf"^\s*{key}:\s*(.+)$", frontmatter, re.MULTILINE)
                    if match:
                        metadata[key] = match.group(1).strip().strip('"').strip("'")
                if metadata:
                    return metadata

        match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if match:
            metadata["title"] = match.group(1).strip()
        return metadata

    def _find_recent_project_for_topic(self, topic: str) -> Optional[Dict[str, Any]]:
        normalized_topic = self._normalize_topic(topic)
        if not normalized_topic or not os.path.isdir(self.output_dir):
            return None

        candidates = []
        for name in os.listdir(self.output_dir):
            project_dir = os.path.join(self.output_dir, name)
            main_md = os.path.join(project_dir, "main.md")
            if not os.path.isdir(project_dir) or not os.path.exists(main_md):
                continue
            try:
                mtime = os.path.getmtime(project_dir)
            except OSError:
                mtime = 0
            metadata = self._parse_main_metadata(main_md)
            candidate_topic = metadata.get("topic") or metadata.get("title") or name
            normalized_title = self._normalize_topic(candidate_topic)
            if not normalized_title:
                continue
            if normalized_topic in normalized_title or normalized_title in normalized_topic:
                candidates.append(
                    {
                        "project_dir": project_dir,
                        "main_md": main_md,
                        "title": metadata.get("title") or name,
                        "topic": metadata.get("topic") or candidate_topic,
                        "mtime": mtime,
                    }
                )

        if not candidates:
            return None

        candidates.sort(key=lambda item: item["mtime"], reverse=True)
        return candidates[0]

    def _build_project_dir(self, topic: str, title: Optional[str] = None) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        basis = topic or title or "untitled"
        safe_title = basis.replace("/", "-").replace("\\", "-")[:50]
        return os.path.join(self.output_dir, f"{timestamp}-{safe_title}")

    def _reuse_response(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "asking",
            "message": (
                f"发现最近的同主题草稿目录：{candidate['project_dir']}。\n"
                f"标题：{candidate.get('title', '未命名')}\n"
                f"主题：{candidate.get('topic', candidate.get('title', '未命名'))}\n"
                "回复“复用”继续编辑这份草稿，回复“新建”创建一个新的时间戳目录。"
            ),
            "choices": ["复用", "新建"],
        }

    def _apply_reuse_decision(self, user_input: Optional[str]) -> Dict[str, Any]:
        candidate = self.context.get("reuse_candidate")
        requirements = self.context.get("requirements")
        if not candidate or not requirements:
            self.state = State.COLLECTING
            return {"needs_more_info": True, "message": "请重新提交主题。"}

        text = (user_input or "").strip().lower()
        if not text:
            return self._reuse_response(candidate)

        if any(keyword in text for keyword in ("复用", "继续", "沿用", "reuse", "yes", "是", "好", "确认")):
            self.context["project_dir"] = candidate["project_dir"]
            self.context["visuals_dir"] = os.path.join(candidate["project_dir"], "_visuals")
            self.context["reuse_existing_project"] = True
            self.state = State.RESEARCHING
            return {"status": "confirmed"}

        if any(keyword in text for keyword in ("新建", "重新", "new", "no", "否")):
            self.context.pop("project_dir", None)
            self.context.pop("visuals_dir", None)
            self.context["reuse_existing_project"] = False
            self.state = State.RESEARCHING
            return {"status": "confirmed"}

        return self._reuse_response(candidate)

    def handle_input(self, user_input: str) -> Dict[str, Any]:
        """Entry point for incoming messages (e.g., from Feishu webhook)"""
        logger.info(f"Received input in state {self.state.value}: {user_input[:80]}...")

        if self.state == State.IDLE:
            self.state = State.COLLECTING
            self.context["raw_input"] = user_input

        return self._step(user_input)

    def _step(self, user_input: Optional[str] = None) -> Dict[str, Any]:
        """State machine runner"""
        try:
            while self.state not in [State.DONE, State.ERROR]:
                if self.state == State.AWAITING_REUSE_DECISION:
                    decision = self._apply_reuse_decision(user_input)
                    if decision.get("needs_more_info") or decision.get("status") == "asking":
                        return decision
                    user_input = None
                    continue

                if self.state == State.COLLECTING:
                    result = self.architect.process(user_input, self.context)
                    if result.get("needs_more_info"):
                        return {"status": "asking", "message": result["message"]}
                    else:
                        requirements = result["requirements"]
                        raw_topic = requirements.get("topic", "")
                        normalized_topic = self._normalize_topic(raw_topic)
                        if normalized_topic:
                            requirements["raw_topic"] = raw_topic
                            requirements["topic"] = normalized_topic
                        self.context["requirements"] = requirements
                        reuse_candidate = self._find_recent_project_for_topic(
                            self.context["requirements"].get("topic", "")
                        )
                        if reuse_candidate:
                            self.context["reuse_candidate"] = reuse_candidate
                            self.state = State.AWAITING_REUSE_DECISION
                            return self._reuse_response(reuse_candidate)
                        self.context["reuse_existing_project"] = False
                        self.state = State.RESEARCHING
                        user_input = None

                elif self.state == State.RESEARCHING:
                    research_data = self.researcher.process(self.context["requirements"])
                    self.context["research_context"] = research_data
                    self.state = State.WRITING

                elif self.state == State.WRITING:
                    article_data = self.writer_editor.process(
                        self.context["requirements"],
                        self.context["research_context"]
                    )
                    self.context["article"] = article_data
                    self.state = State.VISUALIZING

                elif self.state == State.VISUALIZING:
                    # Determine the output project directory ahead of time
                    # so Visualist can save images directly there
                    title = self.context["article"].get("title", "untitled")
                    topic = self.context.get("requirements", {}).get("topic", title)
                    project_dir = self.context.get("project_dir") or self._build_project_dir(topic, title)
                    visuals_dir = os.path.join(project_dir, "_visuals")
                    os.makedirs(visuals_dir, exist_ok=True)

                    self.context["project_dir"] = project_dir
                    self.context["visuals_dir"] = visuals_dir

                    # 1. Run Visualist: generate AI images for [IMAGE: ...] placeholders
                    article_data = self.visualist.process(
                        self.context["article"],
                        visuals_dir,
                        reuse_existing_visuals=bool(self.context.get("reuse_existing_project"))
                    )
                    self.context["article"] = article_data

                    # 2. Render LaTeX formulas to PNG images
                    try:
                        from latex_renderer import render_latex_in_markdown
                    except Exception as exc:
                        logger.warning("Skipping LaTeX rendering because renderer is unavailable: %s", exc)
                    else:
                        logger.info("Rendering LaTeX formulas to images...")
                        article_data["body"] = render_latex_in_markdown(
                            article_data["body"],
                            visuals_dir
                        )
                        self.context["article"] = article_data

                    self.state = State.FORMATTING

                elif self.state == State.FORMATTING:
                    file_paths = self.formatter.generate(
                        self.context["requirements"],
                        self.context["article"],
                        self.context.get("article", {}).get("visuals", {}),
                        project_dir=self.context.get("project_dir")
                    )
                    self.context["output_files"] = file_paths
                    self.state = State.DISTRIBUTING

                elif self.state == State.DISTRIBUTING:
                    dist_results = distribute_content(
                        self.context["requirements"],
                        self.context["output_files"]["main_md"],
                        capability_router=self.capabilities,
                    )
                    self.context["distribution"] = dist_results
                    self.state = State.DONE

            self.context["capability_trace"] = self.capabilities.snapshot()
            return {
                "status": "completed",
                "message": "Content generation and distribution finished.",
                "files": self.context.get("output_files", {}),
                "capability_trace": self.context.get("capability_trace", []),
            }

        except Exception as e:
            logger.error(f"Error in state {self.state.value}: {str(e)}", exc_info=True)
            self.state = State.ERROR
            return {"status": "error", "message": str(e)}

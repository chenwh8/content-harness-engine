import logging
import json
import os
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional

from agents import ArchitectAgent, ResearcherAgent, WriterEditorAgent, VisualistAgent
from obsidian_formatter import ObsidianFormatter
from bridge import distribute_content

logger = logging.getLogger(__name__)

class State(Enum):
    IDLE = "IDLE"
    COLLECTING = "COLLECTING"
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
        self.state = State.IDLE
        self.context: Dict[str, Any] = {}

        # Initialize agents
        self.architect = ArchitectAgent(config)
        self.researcher = ResearcherAgent(config)
        self.writer_editor = WriterEditorAgent(config)
        self.visualist = VisualistAgent(config)

        self.output_dir = config.get("OUTPUT_DIR", "./output")
        self.formatter = ObsidianFormatter(self.output_dir)

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
                if self.state == State.COLLECTING:
                    result = self.architect.process(user_input, self.context)
                    if result.get("needs_more_info"):
                        return {"status": "asking", "message": result["message"]}
                    else:
                        self.context["requirements"] = result["requirements"]
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
                    date_str = datetime.now().strftime("%Y-%m-%d")
                    safe_title = title.replace("/", "-").replace("\\", "-")[:50]
                    project_dir = os.path.join(self.output_dir, f"{date_str}-{safe_title}")
                    visuals_dir = os.path.join(project_dir, "_visuals")
                    os.makedirs(visuals_dir, exist_ok=True)

                    self.context["project_dir"] = project_dir
                    self.context["visuals_dir"] = visuals_dir

                    # 1. Run Visualist: generate AI images for [IMAGE: ...] placeholders
                    article_data = self.visualist.process(
                        self.context["article"],
                        visuals_dir
                    )
                    self.context["article"] = article_data

                    # 2. Render LaTeX formulas to PNG images
                    from latex_renderer import render_latex_in_markdown
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
                        self.context["output_files"]["main_md"]
                    )
                    self.context["distribution"] = dist_results
                    self.state = State.DONE

            return {
                "status": "completed",
                "message": "Content generation and distribution finished.",
                "files": self.context.get("output_files", {})
            }

        except Exception as e:
            logger.error(f"Error in state {self.state.value}: {str(e)}", exc_info=True)
            self.state = State.ERROR
            return {"status": "error", "message": str(e)}

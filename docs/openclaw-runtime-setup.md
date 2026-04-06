# OpenClaw Runtime Setup

This project prefers the host agent's native capabilities first. In most installs, `CapabilityRouter` will auto-detect the host runtime without any extra configuration. If that fails, it will fall back to Gemini, OpenAI, Tavily, or local templates.

## What the runtime must provide

You usually do not need to set `OPENCLAW_RUNTIME`. Template placeholder values such as `your_module:YourRuntime` are ignored automatically. If you want to override detection manually, configure it as a Python import path in the form:

```env
OPENCLAW_RUNTIME=your_module:YourRuntime
```

The imported object can be either:

- a zero-argument class, or
- a factory function that returns a runtime object

The runtime object should expose one or more of these methods:

- `call_llm(prompt, system_prompt="...", model="...", response_format="text")`
- `search(query, max_results=3)`
- `read_text(path)`
- `generate_image(prompt, aspect_ratio="1:1")`
- `review_image(prompt, image_bytes, aspect_ratio="1:1", image_role="cover", title="", topic="")`
- `publish_wechat_draft(title, html, thumb_media_id)`

For image QA, the runtime should return a structured result with:

- `approved`: boolean
- `reason`: short explanation for rejection or approval
- `score`: optional float from `0.0` to `1.0`

The pipeline treats low scores as rejection and will discard the image instead of silently publishing it. To match the current prompt strategy, reviewers should expect editorial, icon-based visuals with no text, no labels, and no numbers.

If a method is missing, `CapabilityRouter` will fall back to the next provider in the chain.

When embedding this skill in OpenClaw, you can pass a callable under `PROGRESS_CALLBACK` to receive stage-by-stage progress events. Each event is a dictionary with `stage`, `message`, `details`, `state`, and `timestamp`. The final `handle_input` result also includes a `summary` object with the title, topic, outline, visual report, distribution status, and generated file paths.

## One-line installation prompt

Use this exact sentence in OpenClaw to install the skill from GitHub:

```text
请在当前 OpenClaw agent 工作区目录下从 GitHub 克隆 `chenwh8/content-harness-engine` 到本地，安装并启用这个内容生产 skill；如果本地已经存在仓库，请先更新到最新版本，不要重复克隆。请把 Obsidian 草稿目录也放在这个 skill 安装目录的同级位置。安装后请读取仓库中的 README 和 OpenClaw 运行时说明，按文档配置必要环境变量并完成启用，优先使用宿主自身能力，必要时再回退到 API token。首次收到写作需求时，只能先确认主题和文章大纲，不能直接开始检索、写作、配图或发布；必须等我明确回复“确认”之后，才能进入自动执行。完成后告诉我如何触发这项能力。
```

If you just want to validate that the install worked, you can trigger it with:

```text
帮我写一篇关于主流ai编程工具中多智能体应用的公众号文章
```

If you are using `opencode`, keep the same install/update split:

- **Install** means cloning the repository into the current workspace and initializing the environment.
- **Update** means pulling the latest code only, without recreating the directory, overwriting `.env`, or changing公众号 configuration.

Copyable prompts:

```text
请在当前 opencode 工作区目录下从 GitHub 克隆 `chenwh8/content-harness-engine` 到本地，安装并启用这个内容生产 skill；如果本地已经存在仓库，请先更新到最新版本，不要重复克隆。请把 Obsidian 草稿目录也放在这个 skill 安装目录的同级位置。安装后请读取仓库中的 README 和运行时说明，按文档配置必要环境变量并完成启用。首次收到写作需求时，只能先确认主题和文章大纲，不能直接开始检索、写作、配图或发布；必须等我明确回复“确认”之后，才能进入自动执行。
```

```text
请在当前 opencode 工作区里的 `content-harness-engine` 仓库中执行更新，只拉取最新代码，不要重建目录，不要覆盖现有 `.env`，也不要改动我的公众号配置；更新完成后请告诉我当前版本和是否需要重启工作区。
```

For the first turn, the skill must stop after requirement confirmation and wait for an explicit `确认` before it starts any research, writing, image generation, or publishing steps. A good confirmation reply looks like:

```text
我先整理出这篇文章的大纲，请你确认后再开工。
主题：...
受众：...
调性：...
大纲：
- ...
- ...

回复“确认”开始自动写作；如果要改大纲，请直接说你的修改意见。
```

After the user confirms the outline, the skill must run one web search pass before writing and must report the research sources back to the user. The research step should include at least:

- the search query used
- a short research summary
- a source list with titles and URLs when available

To update an existing workspace safely without touching your local configuration, use:

```text
请在当前 OpenClaw agent 工作区里的 `content-harness-engine` 仓库中执行更新，只拉取最新代码，不要重建目录，不要覆盖现有 `.env`，也不要改动我的公众号配置；更新完成后请告诉我当前版本和是否需要重启工作区。
```

This update instruction is meant to preserve:

- the repo-local `.env`
- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`
- `OUTPUT_DIR`
- any other local OpenClaw overrides

If you trigger the skill from `opencode`, the first response should stay in confirmation mode until the user explicitly approves the topic and outline. A good first-turn response is:

```text
我先确认一下需求再开工。
主题：...
受众：...
角度：...
大纲：
- ...
- ...

你确认后，我会先做一次联网检索并回报来源，然后再自动写作、配图和推送草稿箱。
```

## Auto-detection order

Without any explicit `OPENCLAW_RUNTIME`, the router checks:

1. Config-injected runtime objects such as `CAPABILITY_RUNTIME`, `HOST_RUNTIME`, or `NATIVE_RUNTIME`
2. Objects exposed on `__main__`
3. A short list of candidate module names:
   - `openclaw_runtime`
   - `codex_runtime`
   - `host_runtime`
   - `agent_runtime`
   - `runtime`

For each candidate, the router accepts either a runtime object or a factory/class that can be instantiated.

## Recommended environment variables

Set these in `.env` or the OpenClaw environment only when you need to override auto-detection or enable specific fallback providers:

```env
OPENCLAW_RUNTIME=your_module:YourRuntime
OPENAI_API_KEY=optional_openai_fallback_key
GEMINI_API_KEY=optional_gemini_fallback_key
GEMINI_TEXT_MODEL=gemini-2.5-flash
TAVILY_API_KEY=optional_search_fallback_key
WECHAT_APP_ID=your_wechat_app_id
WECHAT_APP_SECRET=your_wechat_app_secret
OUTPUT_DIR=/path/to/your/output
```

Only `WECHAT_APP_ID` and `WECHAT_APP_SECRET` are required if you want the WeChat draft box step to run against the real platform.
That means if you want a full one-stop publish flow from article generation to公众号草稿箱, you should provide both values in the environment.

For a full publish flow, update these configuration locations:

- the repository root `.env`
- or the OpenClaw service environment if your deployment does not read the repo-local `.env`
- the Obsidian output directory should live alongside the skill install directory, for example:
  - `/path/to/agent-workspace/content-harness-engine`
  - `/path/to/agent-workspace/content-harness-output`

At minimum, the `.env` should include:

```env
WECHAT_APP_ID=your_wechat_app_id
WECHAT_APP_SECRET=your_wechat_app_secret
OUTPUT_DIR=/path/to/agent-workspace/content-harness-output
```

## Validation steps in Codex

Run these before testing in OpenClaw:

```bash
python3 test_capability_router.py
python3 test_architect_clarification.py
python3 test_research_sources.py
python3 test_writer_prompt.py
python3 test_obsidian_formatter.py
python3 -m py_compile agents.py bridge.py orchestrator.py capabilities.py obsidian_formatter.py
```

Then run a real end-to-end article pass:

```bash
python3 test_run.py
```

## Fallback order

- Text generation: native runtime -> Gemini -> OpenAI -> local template
- Search: native runtime -> Tavily -> local summary
- Images: native runtime -> Gemini Imagen / Gemini multimodal review -> discard if no reviewer or low score
- WeChat draft publishing: native runtime -> WeChat API

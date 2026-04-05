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

## Validation steps in Codex

Run these before testing in OpenClaw:

```bash
python3 test_capability_router.py
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

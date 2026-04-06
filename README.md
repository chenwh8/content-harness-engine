# Content Harness Engine

`content-harness-engine` 是一个可安装在 **Codex / OpenClaw / 其他宿主 agent** 上的内容生产能力。它通过多智能体协作（Architect, Researcher, Writer/Editor, Visualist）将输入转化为高质量的内容资产，并以符合 Obsidian 标准的 Markdown 格式输出，同时支持自动路由分发到微信等下游平台。

## 🌟 核心特性

- **多智能体协作调度**：基于状态机 (Orchestrator) 驱动的流水线作业。
- **Obsidian 资产化输出**：生成包含 YAML Frontmatter 的 Markdown 文档，自动下载并引用本地配图，预留播客/视频脚本模块。
- **主题级草稿工作台**：每次按主题创建带时间戳的独立 Obsidian 项目；如果发现最近的同主题草稿，会先提示用户决定是否复用。
- **确认-执行-总结工作流**：先确认核心主题和文章大纲，再自动执行全文、配图和发布；执行过程中可通过宿主回调汇报进度，结束后返回结构化总结。
- **可配置生图优先级**：默认按 `imagen-4.0-fast-generate-001`、`imagen-4.0-generate-001`、`imagen-4.0-ultra-generate-001` 的顺序尝试，也可通过环境变量自定义列表。
- **视觉质量门**：每张新图都会先通过多模态审核，未通过则自动切换到下一档模型重试；连续 3 次失败，或者根本没有审图能力时，直接舍弃该图。图像 prompt 默认偏向少文字、少标签、少数字的 editorial / icon-based 风格。
- **智能搜索集成**：内置 Tavily API 支持，提供高质量的背景资料检索。
- **宿主优先路由**：优先使用宿主 agent 自带的搜索、阅读和文字生成能力，缺失时才降级到 API token 方案。
- **自动下游分发**：(Bridge) 无缝对接 `wechat_poster` 等下游插件，实现内容一键分发。

## 🏗 架构设计

系统包含四个核心 Agent，由 Orchestrator 统一调度：

1. **Architect (需求架构师)**：监听飞书输入，通过多轮对话追问受众、调性等，确认后生成 JSON 格式的需求。
2. **Researcher (情报员)**：调用 Tavily 搜索工具获取相关素材。
3. **Writer & Editor (写手与审计)**：采用 Harness“模块化”理念生成正文，Editor 对逻辑进行交叉校验。
4. **Visualist (配图师)**：调用 Nano-Banana-Pro API 为文章生成配图，并将图片下载到本地。

## 📦 安装与配置

### 1. 安装依赖

在 OpenClaw 环境中，进入插件目录并安装依赖：

```bash
pip install -r requirements.txt
```

### 2. 环境变量配置

复制环境变量模板并填写你的 API Key：

```bash
cp .env.example .env
```

在 `.env` 文件中配置以下内容：

```env
NANO_BANANA_API_KEY=your_nano_banana_api_key_here
GEMINI_IMAGE_MODEL_PRIORITY=imagen-4.0-fast-generate-001,imagen-4.0-generate-001,imagen-4.0-ultra-generate-001
TAVILY_API_KEY=your_tavily_api_key_here
WECHAT_APP_ID=your_wechat_app_id_here
WECHAT_APP_SECRET=your_wechat_app_secret_here
OUTPUT_DIR=/path/to/your/obsidian/vault/content-harness-output
```

如果你希望把文章一条龙推送到公众号草稿箱，`WECHAT_APP_ID` 和 `WECHAT_APP_SECRET` 必填；如果只做本地生成和 Obsidian 输出，这两个可以先不配。

默认情况下，系统会自动探测宿主是否已经注入了可用能力。模板里的占位值会被忽略。只有在自动探测失败，或者你想强制指定一个运行时时，才需要手工设置 `OPENCLAW_RUNTIME`：

```env
OPENCLAW_RUNTIME=your_module:YourRuntime
```

自动探测会寻找已经暴露在宿主进程中的能力对象，以及少量约定模块名。手工指定的运行时适配器需要提供这些方法中的一部分或全部：

- `call_llm(prompt, system_prompt="...", model="...", response_format="text")`
- `search(query, max_results=3)`
- `read_text(path)`
- `generate_image(prompt, aspect_ratio="1:1")`
- `review_image(prompt, image_bytes, aspect_ratio="1:1", image_role="cover")`
- `publish_wechat_draft(title, html, thumb_media_id)`

其中 `review_image` 最好返回 `approved`、`reason` 和可选的 `score`，并按当前门禁逻辑把低分内容判为不通过。

如果宿主能力不可用，系统会自动回退到 `GEMINI_API_KEY`、`OPENAI_API_KEY` 和本地模板兜底，不会直接中断整条流程。
图像链路会优先使用宿主的多模态审图能力；若宿主未提供，则回退到 Gemini 视觉模型。若两者都不可用，图片会被直接丢弃，不会写入占位图。

### 公众号草稿一条龙发布

当 `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET` 已配置且公众号接口白名单可用时，系统会在生成 `main.md` 和本地配图后，自动把文章推送到公众号草稿箱。封面图优先使用 `_visuals/visual_0.png`，没有合格封面时会直接跳过该图，而不是上传占位图。

### 3. 注册到 OpenClaw (龙虾)

把下面这句直接发给 OpenClaw 即可完成安装。它会把 skill 安装到当前 agent 工作区目录里，并默认把 Obsidian 草稿放在同级目录下：

```text
请在当前 OpenClaw agent 工作区目录下从 GitHub 克隆 `chenwh8/content-harness-engine` 到本地，安装并启用这个内容生产 skill；如果本地已经存在仓库，请先更新到最新版本，不要重复克隆。请把 Obsidian 草稿目录也放在这个 skill 安装目录的同级位置。安装后请读取仓库中的 README 和 OpenClaw 运行时说明，按文档配置必要环境变量并完成启用，优先使用宿主自身能力，必要时再回退到 API token。首次收到写作需求时，只能先确认主题和文章大纲，不能直接开始检索、写作、配图或发布；必须等我明确回复“确认”之后，才能进入自动执行。完成后告诉我如何触发这项能力。
```

安装完成后，你需要自行检查并修改这些配置：

- 仓库根目录的 `.env`
- 如果你的 OpenClaw 运行环境不读取仓库 `.env`，就改 OpenClaw 服务本身的环境变量配置
- 如果你希望 Obsidian 草稿和 skill 目录保持同级，建议把 `OUTPUT_DIR` 指向同级目录，例如 `../content-harness-output` 或绝对路径 `/path/to/agent-workspace/content-harness-output`

其中公众号一条龙发文至少需要：

```env
WECHAT_APP_ID=your_wechat_app_id_here
WECHAT_APP_SECRET=your_wechat_app_secret_here
OUTPUT_DIR=/path/to/agent-workspace/content-harness-output
```

如果你还想启用外部 fallback，再补这些：

```env
GEMINI_API_KEY=your_gemini_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
GEMINI_IMAGE_MODEL_PRIORITY=imagen-4.0-fast-generate-001,imagen-4.0-generate-001,imagen-4.0-ultra-generate-001
GEMINI_VISION_MODEL=gemini-2.5-flash
GEMINI_TEXT_MODEL=gemini-2.5-flash
```

安装成功后，最直接的触发方式就是在 OpenClaw 里直接说：

```text
帮我写一篇关于主流ai编程工具中多智能体应用的公众号文章，并推送到公众号草稿箱
```

如果你只想先验证安装是否成功，也可以先说：

```text
帮我写一篇关于主流ai编程工具中多智能体应用的公众号文章
```

OpenClaw 会先生成内容，再按配置决定是否继续推送草稿箱。

首次触发时，建议 OpenClaw 先返回下面这种确认消息，然后等待用户回复“确认”：

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

如果你要在 OpenClaw 里更新这个 skill 包，可以直接说：

```text
请在当前 OpenClaw agent 工作区里的 `content-harness-engine` 仓库中执行更新，只拉取最新代码，不要重建目录，不要覆盖现有 `.env`，也不要改动我的公众号配置；更新完成后请告诉我当前版本和是否需要重启工作区。
```

这条更新指令的含义是：

- 只更新仓库代码
- 保留你当前的 `.env`
- 保留公众号 `WECHAT_APP_ID` / `WECHAT_APP_SECRET`
- 保留 `OUTPUT_DIR` 和其它本地配置

如果你需要在 OpenClaw 里展示阶段性进度，建议把宿主的消息回调绑定到 `PROGRESS_CALLBACK`，这样可以收到像下面这样的阶段事件：

- 主题与大纲已确认
- 资料检索完成
- 正文初稿完成
- 配图与质量检测完成
- Obsidian 草稿整理完成
- 公众号草稿箱推送完成

最终返回结果会包含一份结构化总结，里面有标题、主题、大纲、配图报告、分发状态和生成文件路径。

## 🔗 飞书回调配置

1. 在飞书开放平台创建一个企业自建应用，并启用“机器人”能力。
2. 配置**事件订阅**或**接收消息的 Webhook**，将其指向 OpenClaw 实例的对应 API 路由。
3. OpenClaw 接收到飞书消息后，提取文本内容并传递给 `Orchestrator.handle_input(user_input)`。
4. Orchestrator 会返回状态和回复内容，OpenClaw 将回复内容通过飞书 API 发送回给用户。

### 4. 本地验证

在 Codex 环境里，你可以先跑这些检查：

```bash
python3 test_capability_router.py
python3 test_writer_prompt.py
python3 test_obsidian_formatter.py
python3 -m py_compile agents.py bridge.py orchestrator.py capabilities.py obsidian_formatter.py
```

如果你已经把 `OPENCLAW_RUNTIME` 接好了，再执行一轮真实生成：

```bash
python3 test_run.py
```

## 📂 输出目录结构

生成的 Obsidian 资产结构如下：

```text
OUTPUT_DIR/
└── 2026-04-04-153012-文章主题/
    ├── main.md          # 包含 YAML Frontmatter 和正文
    └── _visuals/
        ├── cover_0.png  # 本地下载的配图
        └── ...
```

如果同一主题再次写作，系统会优先查找最近一次同主题项目目录，并把“复用 / 新建”的决定权交给用户。复用时会尽量保留已有图片，只补缺的章节图和新增图。

`main.md` 示例：

```markdown
---
title: "深度解析：OpenClaw 框架"
date: "2026-04-04"
tags: ["AI", "Content"]
platforms: ["wechat"]
status: draft
---

# 深度解析：OpenClaw 框架

![cover_0.png](./_visuals/cover_0.png)

正文内容...

## 播客/视频脚本
大家好，今天我们来聊聊...
```

## 🚀 下游分发 (Bridge)

当文档生成完毕后，Bridge 模块会读取 `main.md` 的 YAML Frontmatter。
如果 `platforms` 包含 `wechat`，系统将自动组装标准入参，调用 ClawHub 上已有的 `wechat_poster` 插件进行发布。无需额外编写微信接口代码。

## 📝 License

MIT License

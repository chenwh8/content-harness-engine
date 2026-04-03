# Content Harness Engine

`content-harness-engine` 是一个专为 **OpenClaw** 框架设计的本地 Skill 插件。它通过多智能体协作（Architect, Researcher, Writer/Editor, Visualist）将用户的飞书输入转化为高质量的内容资产，并以符合 Obsidian 标准的 Markdown 格式输出，同时支持自动路由分发到微信等下游平台。

## 🌟 核心特性

- **多智能体协作调度**：基于状态机 (Orchestrator) 驱动的流水线作业。
- **Obsidian 资产化输出**：生成包含 YAML Frontmatter 的 Markdown 文档，自动下载并引用本地配图，预留播客/视频脚本模块。
- **智能搜索集成**：内置 Tavily API 支持，提供高质量的背景资料检索。
- **自动下游分发**：(Bridge) 无缝对接 ClawHub/SkillHub 的 `wechat_poster` 等现有插件，实现内容一键分发。

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
TAVILY_API_KEY=your_tavily_api_key_here
OUTPUT_DIR=/path/to/your/obsidian/vault/content-harness-output
```

### 3. 注册到 OpenClaw (龙虾)

在你的 OpenClaw 实例配置文件或注册表中，添加此 Skill：

```python
from content_harness_engine.orchestrator import Orchestrator

# 初始化调度器
config = {
    "NANO_BANANA_API_KEY": "...",
    "OUTPUT_DIR": "/path/to/obsidian"
}
harness_engine = Orchestrator(config)

# 将 harness_engine.handle_input 绑定到 OpenClaw 的消息路由
```

## 🔗 飞书回调配置

1. 在飞书开放平台创建一个企业自建应用，并启用“机器人”能力。
2. 配置**事件订阅**或**接收消息的 Webhook**，将其指向 OpenClaw 实例的对应 API 路由。
3. OpenClaw 接收到飞书消息后，提取文本内容并传递给 `Orchestrator.handle_input(user_input)`。
4. Orchestrator 会返回状态和回复内容，OpenClaw 将回复内容通过飞书 API 发送回给用户。

## 📂 输出目录结构

生成的 Obsidian 资产结构如下：

```text
OUTPUT_DIR/
└── 2026-04-04-文章标题/
    ├── main.md          # 包含 YAML Frontmatter 和正文
    └── _visuals/
        ├── cover_0.png  # 本地下载的配图
        └── ...
```

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

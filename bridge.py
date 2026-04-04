"""
bridge.py
下游分发路由：读取 YAML platforms 字段，将 Obsidian 文件分发到对应平台。
目前支持：wechat（调用 wechat_poster 模块）
预留：xiaohongshu, weibo 等
"""
import os
import re
import yaml
import logging
from typing import Dict, Any, List

from wechat_poster import WeChatPoster

logger = logging.getLogger(__name__)


def _md_to_wechat_html(body: str, project_dir: str, poster: WeChatPoster) -> str:
    """
    将 Markdown 正文转换为微信公众号兼容的 HTML。
    
    处理流程：
    1. 将本地图片（_visuals/ 相对路径）上传到微信素材库，替换为微信 CDN URL
    2. 将 Markdown 语法转换为带内联样式的 HTML（微信不支持外部 CSS）
    """

    # ── Step 1: 上传本地图片并替换路径（带去重缓存）─────────────────────
    _upload_cache: Dict[str, str] = {}  # abs_path → wechat_url

    def upload_and_replace(match: re.Match) -> str:
        alt = match.group(1)
        rel_path = match.group(2)

        # 已是微信 URL，直接保留
        if rel_path.startswith('http'):
            return match.group(0)

        # 解析本地绝对路径
        clean_path = rel_path.lstrip("./")
        abs_path = os.path.join(project_dir, clean_path)

        if not os.path.exists(abs_path):
            logger.warning(f"Image not found: {abs_path}, removing reference.")
            return ""

        # 去重：同一文件只上传一次
        if abs_path in _upload_cache:
            wechat_url = _upload_cache[abs_path]
            logger.debug(f"Reusing cached URL for: {os.path.basename(abs_path)}")
            return f"![{alt}]({wechat_url})"

        try:
            logger.info(f"Uploading image to WeChat: {os.path.basename(abs_path)}")
            wechat_url = poster._upload_image_for_content(abs_path)
            _upload_cache[abs_path] = wechat_url
            return f"![{alt}]({wechat_url})"
        except Exception as e:
            logger.error(f"Failed to upload image {abs_path}: {e}")
            return ""

    # 替换所有本地图片引用
    body = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', upload_and_replace, body)

    # ── Step 2: Markdown → 微信兼容 HTML ────────────────────────────────
    # ── Step 2a: 预处理 Markdown 表格 → HTML table（在逐行处理前整体替换）──
    body = _convert_md_tables(body)

    lines = body.split('\n')
    html_parts = []
    in_code_block = False
    code_buffer = []
    code_lang = ""
    in_raw_html = False  # 用于跳过已转换的 HTML 块

    for line in lines:
        # 已转换的 HTML 表格直接透传
        if line.startswith('<table') or in_raw_html:
            in_raw_html = True
            html_parts.append(line)
            if '</table>' in line:
                in_raw_html = False
            continue

        # 代码块
        if line.startswith('```'):
            if not in_code_block:
                in_code_block = True
                code_lang = line[3:].strip()
                code_buffer = []
            else:
                in_code_block = False
                code_content = '\n'.join(code_buffer)
                html_parts.append(
                    f'<pre style="background:#f6f8fa;padding:16px;border-radius:6px;'
                    f'overflow-x:auto;font-size:13px;line-height:1.6;margin:16px 0;">'
                    f'<code>{_escape_html(code_content)}</code></pre>'
                )
                code_buffer = []
            continue

        if in_code_block:
            code_buffer.append(line)
            continue

        # 分隔线
        if re.match(r'^---+$', line.strip()):
            html_parts.append('<hr style="border:none;border-top:1px solid #e0e0e0;margin:24px 0;"/>')
            continue

        # 标题
        h_match = re.match(r'^(#{1,4})\s+(.+)$', line)
        if h_match:
            level = len(h_match.group(1))
            text = _inline_md(h_match.group(2))
            sizes = {1: '22px', 2: '20px', 3: '18px', 4: '16px'}
            weights = {1: '700', 2: '700', 3: '600', 4: '600'}
            margins = {1: '28px 0 12px', 2: '24px 0 10px', 3: '20px 0 8px', 4: '16px 0 6px'}
            html_parts.append(
                f'<h{level} style="font-size:{sizes[level]};font-weight:{weights[level]};'
                f'color:#1a1a1a;margin:{margins[level]};line-height:1.4;">{text}</h{level}>'
            )
            continue

        # 图片（已替换为微信 URL）
        img_match = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)$', line.strip())
        if img_match:
            alt = img_match.group(1)
            src = img_match.group(2)
            if src.startswith('http'):
                html_parts.append(
                    f'<figure style="margin:16px 0;text-align:center;">'
                    f'<img src="{src}" alt="{_escape_html(alt)}" '
                    f'style="max-width:100%;height:auto;border-radius:4px;"/>'
                    f'</figure>'
                )
            continue

        # 无序列表
        if re.match(r'^[-*]\s+', line):
            text = _inline_md(re.sub(r'^[-*]\s+', '', line))
            html_parts.append(
                f'<li style="margin:4px 0;line-height:1.8;color:#333;font-size:15px;">{text}</li>'
            )
            continue

        # 有序列表
        if re.match(r'^\d+\.\s+', line):
            text = _inline_md(re.sub(r'^\d+\.\s+', '', line))
            html_parts.append(
                f'<li style="margin:4px 0;line-height:1.8;color:#333;font-size:15px;">{text}</li>'
            )
            continue

        # 引用块
        if line.startswith('>'):
            text = _inline_md(line[1:].strip())
            html_parts.append(
                f'<blockquote style="border-left:4px solid #4a90e2;padding:8px 16px;'
                f'margin:12px 0;background:#f0f6ff;color:#555;font-size:14px;">{text}</blockquote>'
            )
            continue

        # 空行
        if not line.strip():
            html_parts.append('<p style="margin:0;"></p>')
            continue

        # 普通段落
        text = _inline_md(line)
        html_parts.append(
            f'<p style="font-size:15px;line-height:1.9;color:#333;margin:8px 0;'
            f'text-indent:0;">{text}</p>'
        )

    html = '\n'.join(html_parts)

    # 用 <ul>/<ol> 包裹连续的 <li>
    html = re.sub(r'(<li[^>]*>.*?</li>\n?)+', lambda m: f'<ul style="padding-left:20px;margin:8px 0;">{m.group(0)}</ul>', html, flags=re.DOTALL)

    # 外层容器
    html = (
        f'<section style="font-family:-apple-system,BlinkMacSystemFont,\'Helvetica Neue\','
        f'Arial,sans-serif;max-width:680px;margin:0 auto;padding:0 16px;">'
        f'{html}'
        f'</section>'
    )
    return html


def _convert_md_tables(body: str) -> str:
    """
    将 Markdown 管道表格转换为微信兼容的内联样式 HTML table。
    支持标准的 | col1 | col2 | 格式，包含分隔行。
    """
    # 表格样式定义（微信只支持内联 style）
    # 配色方案：深青灰表头 + 温暖白/淡灰斑马纹，亮色/深色背景均适合
    TABLE_STYLE = (
        'border-collapse:collapse;width:100%;margin:20px 0;'
        'font-size:14px;line-height:1.7;border-radius:8px;'
        'overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);'
    )
    TH_STYLE = (
        'background:#2d3748;color:#e2e8f0;font-weight:600;'
        'padding:12px 16px;border:none;'
        'text-align:left;letter-spacing:0.03em;font-size:13px;'
    )
    TD_STYLE_ODD = (
        'padding:10px 16px;border:none;border-bottom:1px solid #edf2f7;'
        'color:#2d3748;background:#ffffff;vertical-align:top;'
    )
    TD_STYLE_EVEN = (
        'padding:10px 16px;border:none;border-bottom:1px solid #edf2f7;'
        'color:#2d3748;background:#f7fafc;vertical-align:top;'
    )

    def replace_table(m: re.Match) -> str:
        raw = m.group(0)
        rows = [r.strip() for r in raw.strip().split('\n') if r.strip()]
        if len(rows) < 2:
            return raw

        # 解析单元格（去掉首尾的 | ）
        def parse_cells(row: str):
            row = row.strip().strip('|')
            return [c.strip() for c in row.split('|')]

        header_cells = parse_cells(rows[0])
        # rows[1] 是分隔行（--- 行），跳过
        data_rows = rows[2:]

        # 构建表头
        th_html = ''.join(
            f'<th style="{TH_STYLE}">{_inline_md(c)}</th>'
            for c in header_cells
        )
        thead = f'<thead><tr>{th_html}</tr></thead>'

        # 构建表体（斑马纹）
        tbody_rows = []
        for i, row in enumerate(data_rows):
            cells = parse_cells(row)
            td_style = TD_STYLE_ODD if i % 2 == 0 else TD_STYLE_EVEN
            td_html = ''.join(
                f'<td style="{td_style}">{_inline_md(c)}</td>'
                for c in cells
            )
            tbody_rows.append(f'<tr>{td_html}</tr>')
        tbody = f'<tbody>{chr(10).join(tbody_rows)}</tbody>'

        return f'<table style="{TABLE_STYLE}">{thead}{tbody}</table>'

    # 匹配连续的 Markdown 表格行（包含表头、分隔行、数据行）
    table_pattern = re.compile(
        r'(?:^[ \t]*\|.+\|[ \t]*\n){2,}',
        re.MULTILINE
    )
    return table_pattern.sub(replace_table, body)


def _escape_html(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _inline_md(text: str) -> str:
    """处理行内 Markdown：加粗、斜体、行内代码、行内图片。"""
    # 行内图片（已是微信 URL）
    text = re.sub(
        r'!\[([^\]]*)\]\((https?://[^)]+)\)',
        r'<img src="\2" alt="\1" style="max-width:100%;height:auto;vertical-align:middle;"/>',
        text
    )
    # 加粗
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong style="font-weight:600;color:#1a1a1a;">\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong style="font-weight:600;color:#1a1a1a;">\1</strong>', text)
    # 斜体
    text = re.sub(r'\*(.+?)\*', r'<em style="font-style:italic;color:#555;">\1</em>', text)
    # 行内代码
    text = re.sub(
        r'`([^`]+)`',
        r'<code style="background:#f0f0f0;padding:2px 5px;border-radius:3px;'
        r'font-size:13px;color:#c7254e;font-family:monospace;">\1</code>',
        text
    )
    return text


def distribute_content(requirements: Dict[str, Any], main_md_path: str) -> Dict[str, Any]:
    """下游分发路由：读取 YAML platforms 字段，如果是 wechat 则调用 wechat_poster 插件。"""

    # ── 解析 main.md 中的 YAML Frontmatter ──────────────────────────────
    with open(main_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    frontmatter: Dict[str, Any] = {}
    body_content = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
                body_content = parts[2]
            except yaml.YAMLError as e:
                logger.error(f"YAML parse error: {e}")

    platforms: List[str] = frontmatter.get("platforms", [])
    results = {}

    # ── 微信分发 ─────────────────────────────────────────────────────────
    if "wechat" in platforms:
        logger.info("Distributing to WeChat...")

        project_dir = os.path.dirname(main_md_path)
        visuals_dir = os.path.join(project_dir, "_visuals")

        # 找封面图（优先使用 visual_0.png，即第一张 AI 配图）
        cover_image_path = None
        if os.path.exists(visuals_dir):
            for preferred in ["visual_0.png", "visual_1.png"]:
                candidate = os.path.join(visuals_dir, preferred)
                if os.path.exists(candidate):
                    cover_image_path = candidate
                    break
            if not cover_image_path:
                for fname in os.listdir(visuals_dir):
                    if fname.endswith(".png") and not fname.startswith("formula"):
                        cover_image_path = os.path.join(visuals_dir, fname)
                        break

        poster = WeChatPoster()

        # 去掉播客脚本模块（微信正文不需要）
        wechat_body = re.split(r'\n##\s*播客/视频脚本', body_content)[0].strip()

        # 去掉文章大标题（第一行的 # 标题）
        wechat_body = re.sub(r'^#\s+.+\n', '', wechat_body, count=1).strip()

        # 转换为微信兼容 HTML（含图片上传）
        logger.info("Converting Markdown to WeChat HTML and uploading images...")
        html_content = _md_to_wechat_html(wechat_body, project_dir, poster)

        title = frontmatter.get("title", "未命名")
        result = poster.post_to_draft(
            poster._truncate_title(title),
            html_content,
            cover_image_path
        )
        results["wechat"] = result
        logger.info(f"WeChat draft result: {result}")

    # ── 预留扩展 ─────────────────────────────────────────────────────────
    if "xiaohongshu" in platforms:
        logger.info("Xiaohongshu distribution not yet implemented.")
        results["xiaohongshu"] = {"status": "skipped", "platform": "xiaohongshu"}

    return results

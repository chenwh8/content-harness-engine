"""
latex_renderer.py
将 Markdown 正文中的 LaTeX 公式（行内 $...$ 和块级 $$...$$）渲染为 PNG 图片，
并将 Markdown 中的公式替换为图片引用。
"""
import os
import re
import hashlib
import logging
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

logger = logging.getLogger(__name__)


def _render_formula_to_png(latex: str, output_path: str, is_block: bool = False) -> bool:
    """将单个 LaTeX 公式渲染为 PNG 图片。"""
    try:
        fontsize = 18 if is_block else 14
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.patch.set_alpha(0)

        # 使用 matplotlib 的 mathtext 渲染（不需要系统 LaTeX）
        # 将公式包裹在 $ $ 中（matplotlib mathtext 格式）
        formula = latex.strip()
        # 清理常见的 LaTeX 命令，转换为 matplotlib mathtext 兼容格式
        formula = _clean_latex_for_mathtext(formula)
        display_formula = f"${formula}$"

        text = fig.text(
            0.5, 0.5, display_formula,
            fontsize=fontsize,
            ha='center', va='center',
            color='#1a1a1a'
        )

        # 先渲染一次获取实际尺寸
        fig.canvas.draw()
        bbox = text.get_window_extent(renderer=fig.canvas.get_renderer())
        dpi = 150
        width = max(bbox.width / dpi + 0.4, 1.0)
        height = max(bbox.height / dpi + 0.2, 0.4)

        plt.close(fig)

        # 用正确尺寸重新渲染
        fig = plt.figure(figsize=(width, height), dpi=dpi)
        fig.patch.set_facecolor('white')
        fig.patch.set_alpha(1.0)
        fig.text(
            0.5, 0.5, display_formula,
            fontsize=fontsize,
            ha='center', va='center',
            color='#1a1a1a'
        )
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight',
                    facecolor='white', edgecolor='none',
                    pad_inches=0.08)
        plt.close(fig)
        return True
    except Exception as e:
        logger.error(f"Failed to render LaTeX formula: {latex[:60]}... Error: {e}")
        return False


def _clean_latex_for_mathtext(formula: str) -> str:
    """将标准 LaTeX 转换为 matplotlib mathtext 兼容格式。"""
    # 处理多行 aligned/align 环境：将多行合并为单行，用 \\; 分隔
    # 先提取 aligned 内容
    def flatten_aligned(m):
        inner = m.group(1)
        # 移除 \\ 换行，替换为空格
        inner = re.sub(r'\\\\', '  ', inner)
        # 移除 &
        inner = inner.replace('&', '')
        return inner
    formula = re.sub(r'\\begin\{aligned\}([\s\S]*?)\\end\{aligned\}', flatten_aligned, formula)
    formula = re.sub(r'\\begin\{align\*?\}([\s\S]*?)\\end\{align\*?\}', flatten_aligned, formula)
    # 移除其他不支持的环境标记
    formula = re.sub(r'\\begin\{[^}]+\}', '', formula)
    formula = re.sub(r'\\end\{[^}]+\}', '', formula)
    # 预处理：必须在其他替换之前处理，避免被拆散
    # \xrightarrow[下标]{上标} 或 \xrightarrow{上标} 或 \xrightarrow → \rightarrow
    # 两步法：先用 str.replace 替换命令名，再用 re.escape 构建正确模式清除可选参数
    formula = formula.replace(r'\xrightarrow', r'\rightarrow_XREPLACE')
    _xr_pattern = re.escape(r'\rightarrow_XREPLACE') + r'\s*(?:\[[^\]]*\])?\s*(?:\{[^}]*\})?'
    formula = re.sub(_xr_pattern, r'\\rightarrow', formula)
    # 替换常见命令
    replacements = [
        # \bmod → \mathrm{mod}
        (r'\\bmod', r'\\,\\mathrm{mod}\\,'),
        (r'\\pmod\{([^}]+)\}', r'\\,(\\mathrm{mod}\\,\1)'),
        # \mathbf, \text, \operatorname
        (r'\\text\{([^}]+)\}', r'\\mathrm{\1}'),
        (r'\\operatorname\{([^}]+)\}', r'\\mathrm{\1}'),
        # spacing
        (r'\\quad', r'\ '),
        (r'\\qquad', r'\ \ '),
        (r'\\,', ' '),
        (r'\\;', ' '),
        (r'\\!', ''),
        # delimiters - 注意：\\right 必须加边界，避免匹配 \\rightarrow
        (r'\\left\s*[\\|({\\ []', ''),
        (r'\\right\s*[\\|)}\\]]', ''),
        (r'\\left(?!arrow)', ''),
        (r'\\right(?!arrow)', ''),
        (r'\\bigg[lrLR]?', ''),
        (r'\\big[lrLR]?', ''),
        # misc
        (r'\\ldots', r'\\cdots'),
        (r'\\nonumber', ''),
        (r'\\label\{[^}]+\}', ''),
        (r'\\tag\{[^}]+\}', ''),
        (r'\[6pt\]', ''),
        # alignment markers
        (r'&=', '='),
        (r'&\\approx', r'\\approx'),
        (r'&', ' '),
    ]
    for pattern, repl in replacements:
        formula = re.sub(pattern, repl, formula)
    # 清理多余空白
    formula = re.sub(r'\s+', ' ', formula).strip()
    return formula


def render_latex_in_markdown(body: str, visuals_dir: str) -> str:
    """
    扫描 Markdown 正文中的 LaTeX 公式，渲染为 PNG 图片，
    并将公式替换为 Markdown 图片引用。
    
    Args:
        body: Markdown 正文字符串
        visuals_dir: 图片输出目录（_visuals/）
    
    Returns:
        替换后的 Markdown 字符串
    """
    os.makedirs(visuals_dir, exist_ok=True)
    formula_dir = os.path.join(visuals_dir, 'formulas')
    os.makedirs(formula_dir, exist_ok=True)

    rendered_count = 0
    failed_count = 0

    def replace_block_formula(match):
        nonlocal rendered_count, failed_count
        latex = match.group(1).strip()
        # 生成唯一文件名
        h = hashlib.md5(latex.encode()).hexdigest()[:8]
        filename = f"formula_block_{h}.png"
        filepath = os.path.join(formula_dir, filename)
        rel_path = f"./_visuals/formulas/{filename}"

        if not os.path.exists(filepath):
            ok = _render_formula_to_png(latex, filepath, is_block=True)
            if ok:
                rendered_count += 1
                logger.info(f"Rendered block formula: {latex[:40]}...")
            else:
                failed_count += 1
                # 降级：保留原始 LaTeX 文本
                return f"\n\n`{latex}`\n\n"
        else:
            rendered_count += 1

        return f"\n\n![公式]({rel_path})\n\n"

    def replace_inline_formula(match):
        nonlocal rendered_count, failed_count
        latex = match.group(1).strip()
        # 非常短的公式（单个字母/数字）不渲染，保留为代码格式
        if len(latex) <= 2:
            return f"`{latex}`"
        
        h = hashlib.md5(latex.encode()).hexdigest()[:8]
        filename = f"formula_inline_{h}.png"
        filepath = os.path.join(formula_dir, filename)
        rel_path = f"./_visuals/formulas/{filename}"

        if not os.path.exists(filepath):
            ok = _render_formula_to_png(latex, filepath, is_block=False)
            if ok:
                rendered_count += 1
            else:
                failed_count += 1
                return f"`{latex}`"
        else:
            rendered_count += 1

        return f"![公式]({rel_path})"

    # 先处理块级公式 $$...$$（多行）
    body = re.sub(r'\$\$\s*([\s\S]+?)\s*\$\$', replace_block_formula, body)
    # 再处理行内公式 $...$（单行）
    body = re.sub(r'\$([^$\n]+?)\$', replace_inline_formula, body)

    logger.info(f"LaTeX rendering complete: {rendered_count} rendered, {failed_count} failed/skipped")
    return body

"""
latex_renderer.py
处理 Markdown 正文中的 LaTeX 公式：
- 块级公式 $$...$$ → 渲染为 PNG 图片（微信不支持块级公式展示）
- 行内公式 $...$ → 转换为 Unicode 数学符号（保持行文流畅，无需图片）
"""
import os
import re
import hashlib
import logging
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 行内公式：LaTeX → Unicode 符号映射
# ──────────────────────────────────────────────────────────────────────────────

# 希腊字母
_GREEK = {
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ',
    r'\epsilon': 'ε', r'\varepsilon': 'ε', r'\zeta': 'ζ', r'\eta': 'η',
    r'\theta': 'θ', r'\vartheta': 'ϑ', r'\iota': 'ι', r'\kappa': 'κ',
    r'\lambda': 'λ', r'\mu': 'μ', r'\nu': 'ν', r'\xi': 'ξ',
    r'\pi': 'π', r'\varpi': 'ϖ', r'\rho': 'ρ', r'\varrho': 'ϱ',
    r'\sigma': 'σ', r'\varsigma': 'ς', r'\tau': 'τ', r'\upsilon': 'υ',
    r'\phi': 'φ', r'\varphi': 'φ', r'\chi': 'χ', r'\psi': 'ψ', r'\omega': 'ω',
    r'\Gamma': 'Γ', r'\Delta': 'Δ', r'\Theta': 'Θ', r'\Lambda': 'Λ',
    r'\Xi': 'Ξ', r'\Pi': 'Π', r'\Sigma': 'Σ', r'\Upsilon': 'Υ',
    r'\Phi': 'Φ', r'\Psi': 'Ψ', r'\Omega': 'Ω',
}

# 数学运算符与符号
_OPERATORS = {
    r'\infty': '∞', r'\partial': '∂', r'\nabla': '∇',
    r'\pm': '±', r'\mp': '∓', r'\times': '×', r'\div': '÷',
    r'\cdot': '·', r'\circ': '∘', r'\bullet': '•',
    r'\leq': '≤', r'\geq': '≥', r'\neq': '≠', r'\approx': '≈',
    r'\equiv': '≡', r'\sim': '∼', r'\simeq': '≃', r'\cong': '≅',
    r'\propto': '∝', r'\ll': '≪', r'\gg': '≫',
    r'\in': '∈', r'\notin': '∉', r'\subset': '⊂', r'\supset': '⊃',
    r'\subseteq': '⊆', r'\supseteq': '⊇', r'\cup': '∪', r'\cap': '∩',
    r'\emptyset': '∅', r'\varnothing': '∅',
    r'\forall': '∀', r'\exists': '∃',
    r'\rightarrow': '→', r'\leftarrow': '←', r'\leftrightarrow': '↔',
    r'\Rightarrow': '⇒', r'\Leftarrow': '⇐', r'\Leftrightarrow': '⇔',
    r'\to': '→', r'\gets': '←',
    r'\uparrow': '↑', r'\downarrow': '↓',
    r'\xrightarrow': '→',
    r'\cdots': '⋯', r'\ldots': '…', r'\vdots': '⋮', r'\ddots': '⋱',
    r'\sum': '∑', r'\prod': '∏', r'\int': '∫', r'\oint': '∮',
    r'\sqrt': '√',
    r'\langle': '⟨', r'\rangle': '⟩',
    r'\lfloor': '⌊', r'\rfloor': '⌋', r'\lceil': '⌈', r'\rceil': '⌉',
    r'\|': '‖', r'\perp': '⊥', r'\parallel': '∥',
    r'\oplus': '⊕', r'\otimes': '⊗',
    r'\dagger': '†', r'\ddagger': '‡',
    r'\hbar': 'ℏ', r'\ell': 'ℓ', r'\Re': 'ℜ', r'\Im': 'ℑ',
    # 数学函数名（保留为普通文本）
    r'\log': 'log', r'\ln': 'ln', r'\exp': 'exp', r'\sin': 'sin',
    r'\cos': 'cos', r'\tan': 'tan', r'\lim': 'lim', r'\max': 'max',
    r'\min': 'min', r'\det': 'det', r'\dim': 'dim', r'\ker': 'ker',
    r'\arg': 'arg', r'\sup': 'sup', r'\inf': 'inf', r'\mod': 'mod',
    r'\mathbb{R}': 'ℝ', r'\mathbb{C}': 'ℂ', r'\mathbb{Z}': 'ℤ',
    r'\mathbb{N}': 'ℕ', r'\mathbb{Q}': 'ℚ',
}

# 上标/下标数字映射
_SUPERSCRIPT = str.maketrans('0123456789+-=()nijk', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱʲᵏ')
_SUBSCRIPT   = str.maketrans('0123456789+-=()nijk', '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₙᵢⱼₖ')


def _latex_inline_to_unicode(latex: str) -> str:
    """
    将行内 LaTeX 公式转换为 Unicode 文本。
    策略：尽力转换常见符号，复杂结构（分数、矩阵等）保留为简化文本形式。
    """
    s = latex.strip()

    # 1. 处理 \xrightarrow[下标]{上标} → →
    s = re.sub(r'\\xrightarrow\s*(?:\[[^\]]*\])?\s*(?:\{[^}]*\})?', '→', s)

    # 2. 处理 \frac{a}{b} → a/b
    def replace_frac(m):
        num = m.group(1).strip()
        den = m.group(2).strip()
        num = _latex_inline_to_unicode(num)
        den = _latex_inline_to_unicode(den)
        return f"({num}/{den})"
    s = re.sub(r'\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}',
               replace_frac, s)

    # 3. 处理 \sqrt{x} → √x
    s = re.sub(r'\\sqrt\{([^}]+)\}', lambda m: f"√({_latex_inline_to_unicode(m.group(1))})", s)
    s = re.sub(r'\\sqrt\[([^\]]+)\]\{([^}]+)\}',
               lambda m: f"ⁿ√({_latex_inline_to_unicode(m.group(2))})", s)

    # 4. 处理 \mathbf{X} → X（粗体用普通字母代替）
    s = re.sub(r'\\math(?:bf|rm|it|cal|bb|sf|tt)\{([^}]+)\}',
               lambda m: _latex_inline_to_unicode(m.group(1)), s)

    # 5. 处理 \text{...} → 直接文字
    s = re.sub(r'\\text\{([^}]+)\}', r'\1', s)
    s = re.sub(r'\\operatorname\{([^}]+)\}', r'\1', s)
    s = re.sub(r'\\mathrm\{([^}]+)\}', r'\1', s)

    # 6. 处理上标 ^{...} 和 ^x
    def replace_superscript(m):
        content = m.group(1) if m.group(1) else m.group(2)
        content = _latex_inline_to_unicode(content)
        # 尝试用 Unicode 上标字符
        try:
            return content.translate(_SUPERSCRIPT)
        except Exception:
            return f"^{content}"
    s = re.sub(r'\^\{([^}]+)\}|\^([A-Za-z0-9])', replace_superscript, s)

    # 7. 处理下标 _{...} 和 _x（注意：\log_2 中的 _2 是下标，但 \log 本身不是下标）
    def replace_subscript(m):
        content = m.group(1) if m.group(1) else m.group(2)
        content = _latex_inline_to_unicode(content)
        try:
            result = content.translate(_SUBSCRIPT)
            # 如果翻译后和原文相同（无法翻译），加 _ 前缀
            if result == content and not content.isdigit():
                return f"_{content}"
            return result
        except Exception:
            return f"_{content}"
    s = re.sub(r'_\{([^}]+)\}|_([A-Za-z0-9])', replace_subscript, s)

    # 8. 替换希腊字母和运算符（按长度降序，避免短前缀先匹配）
    all_symbols = {**_GREEK, **_OPERATORS}
    for latex_cmd, unicode_char in sorted(all_symbols.items(), key=lambda x: -len(x[0])):
        s = s.replace(latex_cmd, unicode_char)

    # 9. 清理剩余 LaTeX 命令（\cmd → 空）和括号
    s = re.sub(r'\\[a-zA-Z]+\*?', '', s)
    # 清理多余的 { } 括号
    s = s.replace('{', '').replace('}', '')
    # 清理多余空白
    s = re.sub(r'\s+', ' ', s).strip()

    return s


# ──────────────────────────────────────────────────────────────────────────────
# 块级公式：LaTeX → PNG 图片（matplotlib mathtext）
# ──────────────────────────────────────────────────────────────────────────────

def _clean_latex_for_mathtext(formula: str) -> str:
    """将标准 LaTeX 转换为 matplotlib mathtext 兼容格式。"""
    # 处理多行 aligned/align 环境：将多行合并为单行
    def flatten_aligned(m):
        inner = m.group(1)
        inner = re.sub(r'\\\\', '  ', inner)
        inner = inner.replace('&', '')
        return inner
    formula = re.sub(r'\\begin\{aligned\}([\s\S]*?)\\end\{aligned\}', flatten_aligned, formula)
    formula = re.sub(r'\\begin\{align\*?\}([\s\S]*?)\\end\{align\*?\}', flatten_aligned, formula)
    # 移除其他不支持的环境标记
    formula = re.sub(r'\\begin\{[^}]+\}', '', formula)
    formula = re.sub(r'\\end\{[^}]+\}', '', formula)

    # 预处理 \xrightarrow → \rightarrow（必须在其他替换之前）
    formula = formula.replace(r'\xrightarrow', r'\rightarrow_XREPLACE')
    _xr_pattern = re.escape(r'\rightarrow_XREPLACE') + r'\s*(?:\[[^\]]*\])?\s*(?:\{[^}]*\})?'
    formula = re.sub(_xr_pattern, r'\\rightarrow', formula)

    replacements = [
        (r'\\bmod', r'\\,\\mathrm{mod}\\,'),
        (r'\\pmod\{([^}]+)\}', r'\\,(\\mathrm{mod}\\,\1)'),
        (r'\\text\{([^}]+)\}', r'\\mathrm{\1}'),
        (r'\\operatorname\{([^}]+)\}', r'\\mathrm{\1}'),
        (r'\\quad', r'\ '),
        (r'\\qquad', r'\ \ '),
        (r'\\,', ' '),
        (r'\\;', ' '),
        (r'\\!', ''),
        # delimiters — 注意：\\right(?!arrow) 避免匹配 \\rightarrow
        (r'\\left\s*[\\|({\[ ]', ''),
        (r'\\right\s*[\\|)}\]]', ''),
        (r'\\left(?!arrow)', ''),
        (r'\\right(?!arrow)', ''),
        (r'\\bigg[lrLR]?', ''),
        (r'\\big[lrLR]?', ''),
        (r'\\ldots', r'\\cdots'),
        (r'\\nonumber', ''),
        (r'\\label\{[^}]+\}', ''),
        (r'\\tag\{[^}]+\}', ''),
        (r'\[6pt\]', ''),
        (r'&=', '='),
        (r'&\\approx', r'\\approx'),
        (r'&', ' '),
    ]
    for pattern, repl in replacements:
        formula = re.sub(pattern, repl, formula)
    formula = re.sub(r'\s+', ' ', formula).strip()
    return formula


def _render_block_formula_to_png(latex: str, output_path: str) -> bool:
    """将块级 LaTeX 公式渲染为 PNG 图片。"""
    try:
        formula = _clean_latex_for_mathtext(latex.strip())
        display_formula = f"${formula}$"
        fontsize = 18

        fig = plt.figure(figsize=(0.01, 0.01))
        fig.patch.set_alpha(0)
        text = fig.text(0.5, 0.5, display_formula, fontsize=fontsize,
                        ha='center', va='center', color='#1a1a1a')
        fig.canvas.draw()
        bbox = text.get_window_extent(renderer=fig.canvas.get_renderer())
        dpi = 150
        width = max(bbox.width / dpi + 0.6, 1.5)
        height = max(bbox.height / dpi + 0.3, 0.5)
        plt.close(fig)

        fig = plt.figure(figsize=(width, height), dpi=dpi)
        fig.patch.set_facecolor('white')
        fig.text(0.5, 0.5, display_formula, fontsize=fontsize,
                 ha='center', va='center', color='#1a1a1a')
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight',
                    facecolor='white', edgecolor='none', pad_inches=0.1)
        plt.close(fig)
        return True
    except Exception as e:
        logger.error(f"Block formula render failed: {latex[:60]}... Error: {e}")
        return False


def render_latex_in_markdown(body: str, visuals_dir: str) -> str:
    """
    处理 Markdown 正文中的 LaTeX 公式：
    - 块级公式 $$...$$ → 渲染为 PNG 图片（居中展示）
    - 行内公式 $...$ → 转换为 Unicode 数学符号（保持行文流畅）

    Args:
        body: Markdown 正文字符串
        visuals_dir: 图片输出目录（_visuals/）

    Returns:
        处理后的 Markdown 字符串
    """
    os.makedirs(visuals_dir, exist_ok=True)
    formula_dir = os.path.join(visuals_dir, 'formulas')
    os.makedirs(formula_dir, exist_ok=True)

    block_rendered = 0
    block_failed = 0
    inline_converted = 0

    # ── 1. 块级公式 → PNG 图片 ──────────────────────────────────────────
    # 支持两种块级公式格式：$$...$$ 和 \[...\]
    # 注意：必须先处理块级公式，再处理行内公式，避免 $$ 被行内正则误匹配
    def replace_block_formula(match):
        nonlocal block_rendered, block_failed
        latex = match.group(1).strip()
        h = hashlib.md5(latex.encode()).hexdigest()[:8]
        filename = f"formula_block_{h}.png"
        filepath = os.path.join(formula_dir, filename)
        rel_path = f"./_visuals/formulas/{filename}"

        if not os.path.exists(filepath):
            ok = _render_block_formula_to_png(latex, filepath)
            if ok:
                block_rendered += 1
                logger.debug(f"Rendered block formula: {latex[:50]}...")
            else:
                block_failed += 1
                # 降级：用代码块保留原始 LaTeX
                return f"\n\n```\n{latex}\n```\n\n"
        else:
            block_rendered += 1

        return f"\n\n![公式]({rel_path})\n\n"

    # 处理 $$...$$ 格式
    body = re.sub(r'(?<![\$])\$\$([^$][\s\S]*?[^$])\$\$(?![\$])', replace_block_formula, body)
    body = re.sub(r'(?<![\$])\$\$([^$\n]+?)\$\$(?![\$])', replace_block_formula, body)
    # 处理 \[...\] 格式（标准 LaTeX 块级公式）
    body = re.sub(r'\\\[([\s\S]+?)\\\]', replace_block_formula, body)

    # ── 2. 行内公式 → Unicode 符号 ──────────────────────────────────────────
    # 支持两种行内公式格式：$...$ 和 \(...\)
    def replace_inline_formula(match):
        nonlocal inline_converted
        latex = match.group(1).strip()
        # 极短的公式（单字母/数字）直接保留，不做转换
        if len(latex) <= 1:
            return latex
        unicode_text = _latex_inline_to_unicode(latex)
        inline_converted += 1
        return unicode_text

    # 处理 $...$ 格式
    body = re.sub(r'\$([^$\n]+?)\$', replace_inline_formula, body)
    # 处理 \(...\) 格式（标准 LaTeX 行内公式）
    body = re.sub(r'\\\(([^\\]+?)\\\)', replace_inline_formula, body)

    logger.info(
        f"LaTeX processing: {block_rendered} block formulas → PNG, "
        f"{block_failed} failed, {inline_converted} inline formulas → Unicode"
    )
    return body

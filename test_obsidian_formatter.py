import os
from pathlib import Path

from obsidian_formatter import ObsidianFormatter


def test_generate_strips_duplicate_title_and_derives_tags(tmp_path):
    formatter = ObsidianFormatter(str(tmp_path))
    result = formatter.generate(
        {
            'topic': '主流ai编程工具中多智能体的应用',
            'platforms': ['wechat'],
            'audience': '一线开发者',
            'tone': '实践导向',
        },
        {
            'title': '主流AI编程工具中的多智能体实践',
            'body': '# 主流AI编程工具中的多智能体实践\n\n## 背景介绍\n\n正文内容',
            'script': '脚本内容',
        },
        {},
    )

    content = Path(result['main_md']).read_text(encoding='utf-8')
    assert content.count('# 主流AI编程工具中的多智能体实践') == 1
    assert 'topic: 主流ai编程工具中多智能体的应用' in content
    assert 'tags:' in content
    assert '- AI编程' in content
    assert '- 多智能体' in content
    assert '- 软件工程' in content
    assert 'platforms:\n  - wechat' in content
    assert content.split('---', 2)[2].lstrip().startswith('# 主流AI编程工具中的多智能体实践\n\n## 背景介绍')

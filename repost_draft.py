"""
repost_draft.py
直接使用已生成的 Obsidian 输出文件重新发布到微信草稿箱（跳过内容生成阶段）。
用于快速验证 bridge.py 的修复效果。
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from bridge import distribute_content

# 找到最新的输出目录
output_base = os.path.join(os.path.dirname(__file__), 'output')
dirs = sorted([
    d for d in os.listdir(output_base)
    if os.path.isdir(os.path.join(output_base, d))
], reverse=True)

if not dirs:
    print("No output directories found!")
    sys.exit(1)

latest_dir = os.path.join(output_base, dirs[0])
main_md = os.path.join(latest_dir, 'main.md')
print(f"Re-posting from: {main_md}")

requirements = {"platforms": ["wechat"]}
result = distribute_content(requirements, main_md)
print(f"\nResult: {result}")

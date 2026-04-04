import sys, os, re, glob, yaml
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
import markdown
from wechat_poster import WeChatPoster

main_md = glob.glob('output/*/main.md')[0]
print(f"Using: {main_md}")

with open(main_md, 'r') as f:
    content = f.read()

parts = content.split('---', 2)
frontmatter = yaml.safe_load(parts[1])
body = parts[2]
project_dir = os.path.dirname(main_md)

def replacer(match):
    rel = match.group(1)
    clean = rel.lstrip('./').lstrip('../')
    return match.group(0).replace(rel, os.path.abspath(os.path.join(project_dir, clean)))

body = re.sub(r'!\[.*?\]\((.*?)\)', replacer, body)
html = markdown.markdown(body)

poster = WeChatPoster()

# Upload inline images
img_pattern = re.compile(r'<img[^>]+src="([^">]+)"')
for m in img_pattern.finditer(html):
    src = m.group(1)
    if os.path.exists(src):
        url = poster._upload_image_for_content(src)
        html = html.replace(src, url)
        print(f"Uploaded inline img -> {url[:50]}...")

# Cover image
visuals_dir = os.path.join(project_dir, '_visuals')
cover = next((os.path.join(visuals_dir, f) for f in sorted(os.listdir(visuals_dir)) if f.endswith('.png')), None)
print(f"Cover: {cover}")

title = poster._truncate_title(frontmatter.get('title', ''))
print(f"Title: {title!r} | {len(title.encode())} bytes")

result = poster.post_to_draft(title, html, cover)
print(f"Result: {result}")

import sys, glob
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from wechat_poster import WeChatPoster
import requests

poster = WeChatPoster()
token = poster._get_access_token()
cover = glob.glob('output/*/_visuals/cover_0.png')[0]
media_id = poster._upload_image(cover)

titles = [
    'AI Agent框架全景',
    'AI Agent框架全景解析',
    'AI Agent框架全景解析：',
    'AI Agent框架全景解析：核',
    'AI Agent框架全景解析：核心',
    'AI Agent框架全景解析：核心架',
]

for title in titles:
    url = f'https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}'
    payload = {'articles': [{'title': title, 'content': '<p>test</p>', 'thumb_media_id': media_id, 'show_cover_pic': 1}]}
    r = requests.post(url, json=payload)
    data = r.json()
    ok = 'media_id' in data
    b = len(title.encode('utf-8'))
    c = len(title)
    status = "OK  " if ok else "FAIL"
    print(f"[{b:>2}b/{c:>2}c] {status}: {title}")

import os
import logging
import requests
import json
import re
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

class WeChatPoster:
    def __init__(self):
        self.app_id = os.environ.get("WECHAT_APP_ID")
        self.app_secret = os.environ.get("WECHAT_APP_SECRET")
        self.access_token = None

    def _get_access_token(self) -> str:
        if self.access_token:
            return self.access_token
            
        if not self.app_id or not self.app_secret:
            raise ValueError("WECHAT_APP_ID or WECHAT_APP_SECRET is not set")
            
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={self.app_id}&secret={self.app_secret}"
        response = requests.get(url)
        data = response.json()
        
        if "access_token" in data:
            self.access_token = data["access_token"]
            return self.access_token
        else:
            raise Exception(f"Failed to get WeChat access token: {data}")

    def _upload_image(self, file_path: str) -> str:
        """Upload image to WeChat and get media_id"""
        token = self._get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=image"
        
        with open(file_path, "rb") as f:
            files = {"media": f}
            response = requests.post(url, files=files)
            
        data = response.json()
        if "media_id" in data:
            return data["media_id"]
        else:
            raise Exception(f"Failed to upload image {file_path}: {data}")

    def _upload_image_for_content(self, file_path: str) -> str:
        """Upload image to get URL for embedding in article content"""
        token = self._get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={token}"
        
        with open(file_path, "rb") as f:
            files = {"media": f}
            response = requests.post(url, files=files)
            
        data = response.json()
        if "url" in data:
            return data["url"]
        else:
            raise Exception(f"Failed to upload content image {file_path}: {data}")

    def _display_width(self, s: str) -> int:
        """Calculate display width: CJK/fullwidth chars = 2, others = 1."""
        import unicodedata
        w = 0
        for c in s:
            if unicodedata.east_asian_width(c) in ('W', 'F'):
                w += 2
            else:
                w += 1
        return w

    def _truncate_title(self, title: str, max_bytes: int = 30) -> str:
        """Truncate title to fit within WeChat's byte limit.
        Empirically tested: WeChat enforces a strict 30-byte (UTF-8) limit
        on draft article titles. CJK chars = 3 bytes each, ASCII = 1 byte.
        The ellipsis character … (U+2026) is also 3 bytes in UTF-8.
        So the safe strategy: truncate until body <= 27 bytes, then append ….
        """
        encoded = title.encode('utf-8')
        if len(encoded) <= max_bytes:
            return title
        # Shrink char by char, reserve 3 bytes for the … ellipsis
        t = title
        while len(t.encode('utf-8')) > max_bytes - 3:
            t = t[:-1]
        return t + '…'

    def post_to_draft(self, title: str, content: str, cover_image_path: str = None) -> Dict[str, Any]:
        """Post an article to WeChat Draft Box"""
        try:
            token = self._get_access_token()
            
            # 1. Upload cover image
            thumb_media_id = None
            if cover_image_path and os.path.exists(cover_image_path):
                logger.info(f"Uploading cover image: {cover_image_path}")
                thumb_media_id = self._upload_image(cover_image_path)
            else:
                logger.warning("No cover image provided or found. WeChat requires a cover image.")
                return {"status": "error", "message": "Cover image is required for WeChat drafts."}
                
            # 2. Process content: replace local images with WeChat URLs
            # Note: A simple implementation for markdown-like or HTML content
            # In a real scenario, we'd convert markdown to HTML first.
            import markdown
            html_content = markdown.markdown(content)
            
            # Find local image references in HTML and upload them
            # This is a simplified regex, might need refinement
            img_pattern = re.compile(r'<img[^>]+src="([^">]+)"')
            
            def replace_img(match):
                local_src = match.group(1)
                # Assuming local_src is a relative path from the output dir
                # We need to resolve it. This is a bit tricky without context.
                # For now, we'll try to find the file if it's an absolute path, 
                # or we skip it if we can't find it.
                if os.path.exists(local_src):
                    try:
                        wechat_url = self._upload_image_for_content(local_src)
                        return match.group(0).replace(local_src, wechat_url)
                    except Exception as e:
                        logger.error(f"Failed to upload embedded image: {e}")
                        return match.group(0)
                return match.group(0)
                
            # Note: The actual path resolution logic needs to be handled carefully.
            # We'll rely on bridge.py to pass fully resolved paths or pre-process HTML.
            
            # 3. Create draft
            url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}"
            
            article = {
                "title": title,
                "content": html_content,
                "thumb_media_id": thumb_media_id,
                "show_cover_pic": 1,
                "need_open_comment": 0,
                "only_fans_can_comment": 0
            }
            
            payload = {
                "articles": [article]
            }
            
            # IMPORTANT: Use data= with ensure_ascii=False to prevent Unicode escape sequences
            # (e.g., \u6df1 instead of 深) in the title and content sent to WeChat API.
            # requests' json= parameter uses json.dumps with ensure_ascii=True by default.
            response = requests.post(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type': 'application/json; charset=utf-8'}
            )
            response.encoding = 'utf-8'
            data = response.json()
            
            if "media_id" in data:
                logger.info(f"Successfully created WeChat draft: {data['media_id']}")
                return {"status": "success", "platform": "wechat", "draft_id": data["media_id"]}
            else:
                logger.error(f"Failed to create draft: {data}")
                return {"status": "error", "platform": "wechat", "message": str(data)}
                
        except Exception as e:
            logger.error(f"WeChat poster error: {e}")
            return {"status": "error", "platform": "wechat", "message": str(e)}

import os
import logging
import json
import re
import mimetypes
import uuid
from typing import Dict, Any, List, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency in minimal envs
    requests = None

from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

class WeChatPoster:
    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        max_title_bytes: int | None = None,
    ):
        self.app_id = app_id or os.environ.get("WECHAT_APP_ID")
        self.app_secret = app_secret or os.environ.get("WECHAT_APP_SECRET")
        self.max_title_bytes = max_title_bytes or int(os.environ.get("WECHAT_TITLE_MAX_BYTES", "65"))
        self.access_token = None

    def _http_get_json(self, url: str) -> Dict[str, Any]:
        if requests is not None:
            response = requests.get(url, timeout=30)
            return response.json()

        req = urllib_request.Request(url, method="GET")
        try:
            with urllib_request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except urllib_error.HTTPError as exc:
            return json.loads(exc.read().decode("utf-8", errors="ignore"))

    def _http_post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if requests is not None:
            response = requests.post(url, data=body, headers=headers, timeout=30)
            return response.json()

        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib_request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except urllib_error.HTTPError as exc:
            return json.loads(exc.read().decode("utf-8", errors="ignore"))

    def _http_post_file(self, url: str, file_path: str, field_name: str = "media") -> Dict[str, Any]:
        if requests is not None:
            with open(file_path, "rb") as f:
                files = {field_name: f}
                response = requests.post(url, files=files, timeout=30)
            return response.json()

        boundary = uuid.uuid4().hex
        filename = os.path.basename(file_path)
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        body = b"".join(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                file_bytes,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
        )
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib_request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except urllib_error.HTTPError as exc:
            return json.loads(exc.read().decode("utf-8", errors="ignore"))

    def _get_access_token(self) -> str:
        if self.access_token:
            return self.access_token
            
        if not self.app_id or not self.app_secret:
            raise ValueError("WECHAT_APP_ID or WECHAT_APP_SECRET is not set")
            
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={self.app_id}&secret={self.app_secret}"
        data = self._http_get_json(url)
        
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
            data = self._http_post_file(url, file_path)
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
            data = self._http_post_file(url, file_path)
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

    def _truncate_title(self, title: str, max_bytes: int | None = None) -> str:
        """Truncate title to fit within WeChat's byte limit.
        The default keeps more context for draft previews while still allowing
        a configurable escape hatch via WECHAT_TITLE_MAX_BYTES.
        """
        if max_bytes is None:
            max_bytes = self.max_title_bytes
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
                
            # 2. Process content: accept HTML directly when bridge has already converted it.
            # Fallback to Markdown conversion only if the input still looks like Markdown.
            if content.lstrip().startswith("<"):
                html_content = content
            else:
                try:
                    import markdown
                except ImportError:
                    html_content = content
                else:
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
            data = self._http_post_json(url, payload)
            
            if "media_id" in data:
                logger.info(f"Successfully created WeChat draft: {data['media_id']}")
                return {"status": "success", "platform": "wechat", "draft_id": data["media_id"]}
            else:
                logger.error(f"Failed to create draft: {data}")
                return {"status": "error", "platform": "wechat", "message": str(data)}
                
        except Exception as e:
            logger.error(f"WeChat poster error: {e}")
            return {"status": "error", "platform": "wechat", "message": str(e)}

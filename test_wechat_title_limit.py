import sys
import types
import unittest

sys.modules.setdefault("requests", types.ModuleType("requests"))

from wechat_poster import WeChatPoster


class WeChatTitleLimitTest(unittest.TestCase):
    def test_current_title_is_not_truncated_by_default(self):
        poster = WeChatPoster(max_title_bytes=65)
        title = "AI编程新范式：多智能体如何颠覆你的开发流程？"
        self.assertEqual(poster._truncate_title(title), title)


if __name__ == "__main__":
    unittest.main()

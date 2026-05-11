from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_maimai_updater.message_recaller import MessageRecaller


class FakeMessage:
    def __init__(self, group: bool = True):
        self.message_id = "123"
        self.group_id = "456" if group else ""


class FakeEvent:
    message_obj = FakeMessage()

    def __init__(self, platform_name: str = "unknown", group: bool = True):
        self.platform_name = platform_name
        self.group = group
        self.message_obj = FakeMessage(group)

    def get_platform_name(self):
        return self.platform_name

    def get_group_id(self):
        return "456" if self.group else ""


class FakeOneBotClient:
    def __init__(self):
        self.calls = []

    async def call_action(self, action: str, **kwargs):
        self.calls.append((action, kwargs))
        return {"status": "ok"}


class FakePlatform:
    def __init__(self, client):
        self._client = client

    def get_client(self):
        return self._client


class FakeContext:
    def __init__(self, platform=None):
        self.platform = platform

    def get_platform_inst(self, _platform_name: str):
        return self.platform


class RecallerTest(unittest.IsolatedAsyncioTestCase):
    async def test_private_message_is_not_recalled(self):
        result = await MessageRecaller(FakeContext()).recall_sensitive(
            FakeEvent("unknown", group=False)
        )
        self.assertFalse(result.attempted)
        self.assertFalse(result.success)

    async def test_onebot_delete_msg(self):
        client = FakeOneBotClient()
        result = await MessageRecaller(FakeContext(FakePlatform(client))).recall_sensitive(
            FakeEvent("aiocqhttp")
        )
        self.assertTrue(result.success)
        self.assertEqual(client.calls, [("delete_msg", {"message_id": 123})])

    async def test_unsupported_platform_warns(self):
        result = await MessageRecaller(FakeContext()).recall_sensitive(FakeEvent("telegram"))
        self.assertTrue(result.attempted)
        self.assertFalse(result.success)
        self.assertIn("不支持", result.message)


if __name__ == "__main__":
    unittest.main()

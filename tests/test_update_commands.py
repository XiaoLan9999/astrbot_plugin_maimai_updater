from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from astrbot_plugin_maimai_updater.maimai_service import SyncResult


SGID = "SGWCMAID261016120000" + "A" * 64


class Result:
    def message(self, text):
        self.text = text
        return self


class Image:
    pass


def load_plugin():
    def decorator(*args, **kwargs):
        return lambda function: function

    modules = {name: types.ModuleType(name) for name in (
        "astrbot", "astrbot.api", "astrbot.api.all", "astrbot.api.event",
        "astrbot.api.event.filter", "astrbot.api.star", "astrbot.api.message_components",
    )}
    modules["astrbot.api"].AstrBotConfig = dict
    modules["astrbot.api"].logger = logging.getLogger("maimai-test")
    modules["astrbot.api.all"].register = decorator
    modules["astrbot.api.event"].AstrMessageEvent = object
    modules["astrbot.api.event"].MessageEventResult = Result
    modules["astrbot.api.event.filter"].EventMessageType = types.SimpleNamespace(ALL=1)
    modules["astrbot.api.event.filter"].command = decorator
    modules["astrbot.api.event.filter"].event_message_type = decorator
    modules["astrbot.api.star"].Context = object
    modules["astrbot.api.star"].Star = type("Star", (), {"__init__": lambda self, *args: None})
    modules["astrbot.api.star"].StarTools = types.SimpleNamespace(get_data_dir=lambda **kwargs: ".")
    modules["astrbot.api.message_components"].Image = Image
    name = "astrbot_plugin_maimai_updater._command_test_main"
    path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


plugin_module = load_plugin()


class Event:
    def __init__(self, text="", sender="user", group="group", bot="bot", images=None):
        self.message_str = text
        self.sender = sender
        self.unified_msg_origin = group
        self.bot = bot
        self.images = images or []
        self.extra = {}
        self.messages = []
        self.stopped = False
        self.admin = False

    def get_platform_name(self): return "test"
    def get_platform_id(self): return self.bot
    def get_sender_id(self): return self.sender
    def get_messages(self): return self.images
    def is_admin(self): return self.admin
    def get_extra(self, key, default=None): return self.extra.get(key, default)
    def set_extra(self, key, value): self.extra[key] = value
    def stop_event(self): self.stopped = True
    def plain_result(self, text): return text

    async def send(self, result):
        self.messages.append(result.text if isinstance(result, Result) else result)


class UpdateCommandTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        with patch.object(plugin_module.StarTools, "get_data_dir", return_value=self.folder.name):
            self.plugin = plugin_module.MaimaiUpdaterPlugin(object(), {"require_command_prefix": False})
        await self.plugin.store.set_import_token("test:user", "import-token")
        self.plugin.service = types.SimpleNamespace(
            ensure_backend_available=Mock(),
            sync_from_sgid_to_divingfish=AsyncMock(return_value=SyncResult("", 14205, 446, marked_score_count=380, source="official")),
            close=AsyncMock(), describe_error=lambda exc: str(exc),
        )
        self.plugin._recall_current_message = AsyncMock()
        self.plugin._validate_sgid_for_one_time_use = lambda value: ""

    async def asyncTearDown(self):
        await self.plugin.terminate()
        self.folder.cleanup()

    async def start(self):
        event = Event("更新水鱼")
        await self.plugin.handle_plain_command(event)
        self.assertTrue(event.stopped)
        self.assertIn("180 秒", event.messages[0])
        self.plugin.service.sync_from_sgid_to_divingfish.assert_not_awaited()

    async def test_two_step_text_and_session_isolation(self):
        await self.start()
        for event in (Event(SGID, sender="other"), Event(SGID, group="other"), Event(SGID, bot="other")):
            await self.plugin.handle_plain_command(event)
            self.assertFalse(event.stopped)
        event = Event(SGID)
        await self.plugin.handle_plain_command(event)
        self.plugin.service.sync_from_sgid_to_divingfish.assert_awaited_once_with(sgid=SGID, import_token="import-token")
        self.assertIn("水鱼更新完成", event.messages[-1])
        await self.plugin.handle_plain_command(Event(SGID))
        self.assertEqual(self.plugin.service.sync_from_sgid_to_divingfish.await_count, 1)

    async def test_invalid_image_keeps_waiting_for_retry(self):
        await self.start()
        self.plugin.qr_reader.read = AsyncMock(return_value=["unrelated-qr"])
        bad = Event(images=[Image()])
        await self.plugin.handle_plain_command(bad)
        self.assertIn("未找到", bad.messages[-1])
        self.assertEqual(self.plugin.pending_updates.state(self.plugin._input_key(bad)), "waiting")
        self.plugin.qr_reader.read.return_value = ["unrelated-qr", SGID]
        good = Event(images=[Image(), Image()])
        await self.plugin.handle_plain_command(good)
        self.assertEqual(len(self.plugin.qr_reader.read.call_args.args[0]), 2)
        self.plugin.service.sync_from_sgid_to_divingfish.assert_awaited_once()

    async def test_timeout_and_cancellation_do_not_consume_sgid(self):
        await self.start()
        self.plugin.pending_updates.clock = lambda: float("inf")
        event = Event(SGID)
        await self.plugin.handle_plain_command(event)
        self.assertIn("超时", event.messages[-1])
        self.plugin.service.sync_from_sgid_to_divingfish.assert_not_awaited()
        self.plugin.pending_updates.clock = lambda: 0.0
        await self.start()
        cancel = Event("取消更新")
        await self.plugin.handle_plain_command(cancel)
        await self.plugin.handle_plain_command(Event(SGID))
        self.plugin.service.sync_from_sgid_to_divingfish.assert_not_awaited()

    async def test_prefix_setting_only_applies_to_initial_command(self):
        self.plugin.require_command_prefix = True
        initial = Event("更新水鱼")
        await self.plugin.handle_plain_command(initial)
        self.assertFalse(initial.stopped)
        await self.plugin.update_scores(Event("/更新水鱼"))
        followup = Event(SGID)
        await self.plugin.handle_plain_command(followup)
        self.plugin.service.sync_from_sgid_to_divingfish.assert_awaited_once()

    async def test_legacy_inline_and_duplicate_handler_only_run_once(self):
        event = Event(f"水鱼更新 {SGID}")
        await self.plugin.handle_plain_command(event)
        await self.plugin.update_scores(event, SGID)
        self.plugin.service.sync_from_sgid_to_divingfish.assert_awaited_once()

    async def test_missing_token_or_backend_does_not_start_waiting(self):
        await self.plugin.store.remove("test:user")
        event = Event("更新水鱼")
        await self.plugin.handle_plain_command(event)
        self.assertIn("尚未绑定", event.messages[-1])
        self.assertEqual(self.plugin.pending_updates.state(self.plugin._input_key(event)), "absent")
        await self.plugin.store.set_import_token("test:user", "token")
        self.plugin.service.ensure_backend_available.side_effect = RuntimeError("请配置远程成绩服务")
        event = Event("更新水鱼")
        await self.plugin.handle_plain_command(event)
        self.assertIn("远程成绩服务", event.messages[-1])
        self.assertEqual(self.plugin.pending_updates.state(self.plugin._input_key(event)), "absent")

    async def test_concurrent_followups_do_not_duplicate_update(self):
        await self.start()
        started, finish = asyncio.Event(), asyncio.Event()

        async def read(images):
            started.set()
            await finish.wait()
            return [SGID]

        self.plugin.qr_reader.read = read
        task = asyncio.create_task(self.plugin.handle_plain_command(Event(images=[Image()])))
        await started.wait()
        await self.plugin.handle_plain_command(Event(SGID))
        finish.set()
        await task
        self.plugin.service.sync_from_sgid_to_divingfish.assert_awaited_once()

    async def test_cancel_while_image_is_downloading_does_not_update(self):
        await self.start()
        started, finish = asyncio.Event(), asyncio.Event()

        async def read(images):
            started.set()
            await finish.wait()
            return [SGID]

        self.plugin.qr_reader.read = read
        task = asyncio.create_task(self.plugin.handle_plain_command(Event(images=[Image()])))
        await started.wait()
        await self.plugin.handle_plain_command(Event("取消更新"))
        finish.set()
        await task
        self.plugin.service.sync_from_sgid_to_divingfish.assert_not_awaited()

    async def test_runtime_commands_cannot_be_started_by_group_members(self):
        event = Event("舞萌环境准备")
        with patch.object(plugin_module.asyncio, "create_subprocess_exec") as start:
            await self.plugin.handle_plain_command(event)
        start.assert_not_called()
        self.assertIn("仅 Bot 管理员", event.messages[-1])

    async def test_admin_can_probe_without_providing_sgid(self):
        event = Event("舞萌环境检测")
        event.admin = True
        process = types.SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b'{"ready":true,"code":"ready"}', None)))
        with patch.object(plugin_module.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)) as start:
            await self.plugin.handle_plain_command(event)
        self.assertIn("检测通过", event.messages[-1])
        self.assertNotIn("--install", start.call_args.args)
        self.plugin.service.sync_from_sgid_to_divingfish.assert_not_awaited()

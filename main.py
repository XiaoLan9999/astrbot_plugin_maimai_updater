from __future__ import annotations

import hashlib
import time

from astrbot.api import AstrBotConfig, logger
from astrbot.api.all import register
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import EventMessageType, command, event_message_type
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.message_components import Image

from .maimai_service import MaimaiService
from .message_recaller import RecallResult, MessageRecaller
from .storage import UserStore
from .update_input import PendingUpdates, QrImageReader, UpdateInputError, select_sgid
from .utils import (
    extract_sgid,
    format_ts,
    is_probable_import_token,
    is_probable_sgid,
    mask_secret,
    parse_bool,
    require_command_prefix_from_config,
    validate_sgid_freshness,
)


PLAIN_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("token", ("maimaitoken", "水鱼绑定", "绑定水鱼")),
    ("update", ("maimaiupdate", "更新水鱼", "水鱼更新", "更新B50", "更新b50")),
    ("clear", ("maimaiclear", "清空水鱼", "清空B50", "清空b50")),
    ("status", ("maimaistatus", "水鱼状态")),
    ("unbind", ("maimaiunbind", "水鱼解绑")),
)


@register(
    "astrbot_plugin_maimai_updater",
    "User",
    "使用一次性舞萌官方二维码凭据，把官方成绩同步到水鱼。",
    "0.7.0",
    "",
)
class MaimaiUpdaterPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict):
        super().__init__(context)
        self.context = context
        self.config = config or {}

        data_dir = StarTools.get_data_dir(plugin_name="astrbot_plugin_maimai_updater")
        self.store = UserStore(data_dir)

        self.require_command_prefix = self._require_command_prefix_config()
        self.enable_clear_command = self._bool_config("enable_clear_command", True)
        self.warn_unsupported_recall = self._bool_config("warn_unsupported_recall", True)
        self.service = MaimaiService(
            timeout=self._int_config("request_timeout_seconds", 30),
            http_proxy=str(self.config.get("maimai_http_proxy", "") or ""),
            remote_score_url=str(self.config.get("remote_score_url", "") or ""),
            remote_score_token=str(self.config.get("remote_score_token", "") or ""),
        )
        self.recaller = MessageRecaller(
            context,
            kook_token=str(self.config.get("kook_token", "") or ""),
        )
        self.sgid_max_age_seconds = self._int_config("sgid_max_age_seconds", 180)
        self._used_sgid_hashes: dict[str, float] = {}
        self.pending_updates = PendingUpdates(self._int_config("update_input_timeout_seconds", 180))
        self.qr_reader = QrImageReader()
        self._active_updates: set[str] = set()
        self._reading_inputs: set[str] = set()

    def _int_config(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _bool_config(self, key: str, default: bool) -> bool:
        return parse_bool(self.config.get(key, default), default)

    def _require_command_prefix_config(self) -> bool:
        return require_command_prefix_from_config(self.config)

    @staticmethod
    def _message(text: str) -> MessageEventResult:
        return MessageEventResult().message(text)

    @staticmethod
    def _user_key(event: AstrMessageEvent) -> str:
        return f"{event.get_platform_name()}:{event.get_sender_id()}"

    @staticmethod
    def _input_key(event: AstrMessageEvent) -> tuple[str, str, str]:
        return (str(event.get_platform_id()), event.unified_msg_origin, str(event.get_sender_id()))

    @staticmethod
    def _images(event: AstrMessageEvent) -> list[Image]:
        return [part for part in event.get_messages() if isinstance(part, Image)]

    async def _send_text(self, event: AstrMessageEvent, text: str) -> None:
        await event.send(event.plain_result(text))

    async def _send_recall_notice(
        self,
        event: AstrMessageEvent,
        recall: RecallResult,
    ) -> None:
        if not self.warn_unsupported_recall or not recall.attempted:
            return
        await self._send_text(event, "🔒 已尝试撤回消息，如果没撤回请手动撤回。")

    @staticmethod
    def _prefixless_update_example() -> str:
        return "更新水鱼"

    @staticmethod
    def _split_plain_command(content: str, command_text: str) -> str | None:
        if content == command_text:
            return ""
        if not content.startswith(command_text):
            return None
        suffix = content[len(command_text):]
        if suffix and suffix[0] not in " \t\r\n:：　":
            return None
        return suffix.strip().lstrip(":：").strip()

    def _parse_plain_command(self, text: str) -> tuple[str, str] | None:
        if self.require_command_prefix:
            return None
        content = (text or "").strip()
        if not content:
            return None
        for command_key, command_names in PLAIN_COMMANDS:
            for command_text in command_names:
                argument = self._split_plain_command(content, command_text)
                if argument is not None:
                    return command_key, argument
        return None

    def _validate_sgid_for_one_time_use(self, sgid: str) -> str:
        freshness = validate_sgid_freshness(
            sgid,
            max_age_seconds=self.sgid_max_age_seconds,
        )
        if not freshness.ok:
            current = int(time.time())
            logger.warning(
                "[MaimaiUpdater] SGID freshness validation rejected: "
                "issued_at_cst=%s current_cst=%s age_seconds=%s max_age_seconds=%s reason=%s",
                format_ts(freshness.issued_at),
                format_ts(current),
                current - freshness.issued_at if freshness.issued_at else "unknown",
                self.sgid_max_age_seconds,
                freshness.message,
            )
            return freshness.message

        now = time.time()
        for digest, expires_at in list(self._used_sgid_hashes.items()):
            if expires_at <= now:
                self._used_sgid_hashes.pop(digest, None)

        digest = hashlib.sha256(sgid.encode("utf-8")).hexdigest()
        if digest in self._used_sgid_hashes:
            return "这条 SGID 已经被使用过，请重新从官方公众号获取二维码后再试。"

        self._used_sgid_hashes[digest] = now + max(self.sgid_max_age_seconds + 60, 300)
        return ""

    async def _recall_current_message(self, event: AstrMessageEvent) -> None:
        recall = await self.recaller.recall_sensitive(event)
        await self._send_recall_notice(event, recall)

    async def _send_command_result(
        self,
        event: AstrMessageEvent,
        result: MessageEventResult | None,
    ) -> None:
        if result is not None:
            await event.send(result)

    async def _update_from_credential(self, event: AstrMessageEvent, credential_text: str) -> None:
        user_key = self._user_key(event)
        if user_key in self._active_updates:
            await self._send_text(event, "你的成绩正在更新，请等待本次更新完成。")
            return
        self._active_updates.add(user_key)
        try:
            await self._sync_credential(event, credential_text)
        finally:
            self._active_updates.discard(user_key)

    async def _sync_credential(self, event: AstrMessageEvent, credential_text: str) -> None:
        event.stop_event()
        user_key = self._user_key(event)
        record = self.store.get(user_key)
        if not record.divingfish_import_token:
            await self._send_text(
                event,
                "❌ 尚未绑定水鱼 Import-Token。\n"
                "请先执行 maimaitoken <水鱼 Import-Token>、水鱼绑定 <水鱼 Import-Token> 或 绑定水鱼 <水鱼 Import-Token>。",
            )
            return

        sgid = extract_sgid(credential_text or "")
        if not sgid:
            await self._send_text(
                event,
                "❌ 凭据格式不正确。\n"
                "请发送以 SGWCMAID 开头的官方二维码识别文本。",
            )
            return

        if not is_probable_sgid(sgid):
            await self._send_text(event, "❌ SGID 格式不正确，请发送以 SGWCMAID 开头的完整文本。")
            return

        if not await self._check_backend(event):
            return

        if validation_error := self._validate_sgid_for_one_time_use(sgid):
            await self._send_text(event, f"❌ {validation_error}")
            return

        await self._send_text(event, "⏳ 正在用本次 SGID 拉取成绩并同步到水鱼，请稍候...")
        try:
            result = await self.service.sync_from_sgid_to_divingfish(
                sgid=sgid,
                import_token=record.divingfish_import_token,
            )
        except Exception as exc:
            logger.exception("[MaimaiUpdater] update failed")
            msg = self.service.describe_error(exc)
            await self.store.set_sync_result(
                user_key,
                rating=record.rating,
                result=f"失败：{msg}",
            )
            await self._send_text(event, f"❌ 更新失败：{msg}")
            return

        summary = f"成功，同步 {result.score_count} 条成绩"
        if result.marked_score_count:
            summary += f"，含 {result.marked_score_count} 条特殊标识"
        await self.store.set_sync_result(
            user_key,
            rating=result.rating,
            result=summary,
        )
        lines = [
            "✅ 水鱼更新完成！",
            f"Rating：{result.rating or record.rating}",
            f"成绩数：{result.score_count}",
            "现在可以用你现有的 B50 插件查询最新数据。",
        ]
        if result.marked_score_count:
            lines.insert(3, f"特殊标识：{result.marked_score_count} 条含 FC/FS/AP")
        if result.player_warning:
            lines.append(f"⚠️ {result.player_warning}")
        await self._send_text(event, "\n".join(lines))

    @command("maimaitoken", alias={"水鱼绑定", "绑定水鱼"})
    async def bind_token(self, event: AstrMessageEvent, token: str = ""):
        token = (token or "").strip()
        if not token:
            return self._message(
                "用法：maimaitoken <水鱼 Import-Token>\n"
                "也可以使用：水鱼绑定 <水鱼 Import-Token> / 绑定水鱼 <水鱼 Import-Token>\n"
                "群聊中我会尝试撤回包含 Token 的消息。"
            )

        event.stop_event()
        await self._recall_current_message(event)

        if not is_probable_import_token(token):
            await self._send_text(
                event,
                "❌ 水鱼 Import-Token 格式看起来不正确，请确认长度约 100-180 字符且只包含字母、数字、_、-。",
            )
            return

        await self.store.set_import_token(self._user_key(event), token)
        if self.require_command_prefix:
            update_hint = (
                "之后带 Bot 唤醒前缀执行 "
                "更新水鱼，再按提示发送官方二维码图片或 SGID 即可更新 B50。"
            )
        else:
            update_hint = "之后发送 更新水鱼，再按提示发送官方二维码图片或 SGID 即可更新 B50。"
        await self._send_text(
            event,
            f"✅ 水鱼绑定成功：{mask_secret(token)}\n"
            f"{update_hint}",
        )

    @command("maimaiupdate", alias={"更新水鱼", "水鱼更新", "更新b50", "更新B50"})
    async def update_scores(self, event: AstrMessageEvent, credential_text: str = ""):
        if event.get_extra("maimai_updater_update_handled", False):
            return
        event.set_extra("maimai_updater_update_handled", True)
        event.stop_event()
        if self._user_key(event) in self._active_updates or self._user_key(event) in self._reading_inputs:
            await self._send_text(event, "你的成绩正在更新，请等待本次更新完成。")
            return
        if not self.store.get(self._user_key(event)).divingfish_import_token:
            await self._send_text(event, "尚未绑定水鱼，请先发送 水鱼绑定 <Import-Token>（按面板配置添加唤醒前缀）。")
            return
        if not await self._check_backend(event):
            return
        credential_text = (credential_text or "").strip()
        if not credential_text and not self._images(event):
            self.pending_updates.begin(self._input_key(event))
            await self._send_text(
                event, f"请在 {self.pending_updates.timeout} 秒内发送官方玩家二维码图片或完整 SGID 文本。\n"
                "发送 取消更新 可结束本次等待。",
            )
            return
        await self._receive_update_input(event, credential_text)

    async def _check_backend(self, event: AstrMessageEvent) -> bool:
        try:
            self.service.ensure_backend_available()
        except Exception as exc:
            await self._send_text(event, self.service.describe_error(exc))
            return False
        return True

    async def _receive_update_input(self, event: AstrMessageEvent, text: str) -> None:
        user_key = self._user_key(event)
        if user_key in self._reading_inputs or user_key in self._active_updates:
            await self._recall_current_message(event)
            await self._send_text(event, "正在处理你的更新，请稍候。")
            return
        self._reading_inputs.add(user_key)
        try:
            await self._decode_update_input(event, text)
        finally:
            self._reading_inputs.discard(user_key)

    async def _decode_update_input(self, event: AstrMessageEvent, text: str) -> None:
        key = self._input_key(event)
        was_waiting = self.pending_updates.state(key) == "waiting"
        await self._recall_current_message(event)
        try:
            values = [text]
            if images := self._images(event):
                values.extend(await self.qr_reader.read(images))
            sgid = select_sgid(values)
        except UpdateInputError as exc:
            await self._send_text(event, f"❌ {exc}")
            return
        if was_waiting and self.pending_updates.state(key) != "waiting":
            if self.pending_updates.state(key) == "expired":
                self.pending_updates.remove(key)
                await self._send_text(event, "本次等待已超时，请重新发送 更新水鱼。")
            return
        self.pending_updates.remove(key)
        await self._update_from_credential(event, sgid)

    @command("maimaiclear", alias={"清空水鱼", "清空b50", "清空B50"})
    async def clear_scores(self, event: AstrMessageEvent, confirm: str = ""):
        if not self.enable_clear_command:
            return self._message("当前配置已关闭清空水鱼命令。")

        if confirm not in {"confirm", "确认", "确认清空"}:
            return self._message(
                "此操作会向水鱼发送清空成绩请求。\n"
                "确认要清空时请执行：maimaiclear 确认清空 / 清空水鱼 确认清空 / 清空b50 确认清空"
            )

        user_key = self._user_key(event)
        record = self.store.get(user_key)
        if not record.divingfish_import_token:
            return self._message(
                "❌ 尚未绑定水鱼 Import-Token。\n"
                "请先执行 maimaitoken <水鱼 Import-Token>。"
            )

        await self._send_text(event, "⏳ 正在向水鱼发送清空成绩请求，请稍候...")
        try:
            await self.service.clear_divingfish_scores(
                import_token=record.divingfish_import_token,
            )
        except Exception as exc:
            logger.exception("[MaimaiUpdater] clear failed")
            msg = self.service.describe_error(exc)
            await self.store.set_sync_result(
                user_key,
                rating=record.rating,
                result=f"清空失败：{msg}",
            )
            return self._message(f"❌ 清空失败：{msg}")

        await self.store.clear_local_profile(
            user_key,
            result="已向水鱼发送清空成绩请求",
        )
        return self._message("✅ 已向水鱼发送清空成绩请求。发送 更新水鱼，再按提示提供二维码图片或 SGID 即可再次更新 B50。")

    @command("maimaistatus", alias={"水鱼状态"})
    async def status(self, event: AstrMessageEvent):
        record = self.store.get(self._user_key(event))
        lines = ["📋 maimai 水鱼更新状态"]
        prefix_required = "需要" if self.require_command_prefix else "不需要"
        lines.append(f"唤醒前缀：{prefix_required}")
        if not self.require_command_prefix:
            lines.append(
                "免前缀用法：水鱼状态 / 水鱼绑定 <Token> / "
                f"{self._prefixless_update_example()}"
            )
        lines.append("更新方式：发送 更新水鱼，再发送二维码图片或 SGID")
        lines.append(f"水鱼 Token：{mask_secret(record.divingfish_import_token)}")
        if record.rating:
            lines.append(f"Rating：{record.rating}")
        lines.append(f"上次更新：{format_ts(record.last_sync_at)}")
        if record.last_sync_result:
            lines.append(f"上次结果：{record.last_sync_result}")
        return self._message("\n".join(lines))

    @command("maimaiunbind", alias={"水鱼解绑"})
    async def unbind(self, event: AstrMessageEvent):
        self.pending_updates.remove(self._input_key(event))
        removed = await self.store.remove(self._user_key(event))
        if removed:
            return self._message("✅ 已删除你的水鱼 Token 和本地展示状态。")
        return self._message("当前没有保存的绑定信息。")

    @event_message_type(EventMessageType.ALL, priority=100)
    async def handle_plain_command(self, event: AstrMessageEvent):
        parsed = self._parse_plain_command(event.message_str or "")
        if not parsed:
            key = self._input_key(event)
            state = self.pending_updates.state(key)
            if state == "absent":
                return
            content = (event.message_str or "").strip()
            if content in {"取消", "取消更新"}:
                event.stop_event()
                self.pending_updates.remove(key)
                await self._send_text(event, "已取消本次更新。")
                return
            if not extract_sgid(content) and not self._images(event):
                return
            event.stop_event()
            event.set_extra("maimai_updater_update_handled", True)
            if state == "expired":
                self.pending_updates.remove(key)
                await self._recall_current_message(event)
                await self._send_text(event, "本次等待已超时，请重新发送 更新水鱼。")
                return
            await self._receive_update_input(event, content)
            return

        event.stop_event()
        command_key, argument = parsed
        if command_key == "token":
            result = await self.bind_token(event, argument)
        elif command_key == "update":
            result = await self.update_scores(event, argument)
        elif command_key == "clear":
            result = await self.clear_scores(event, argument)
        elif command_key == "status":
            result = await self.status(event)
        elif command_key == "unbind":
            result = await self.unbind(event)
        else:
            return
        await self._send_command_result(event, result)

    async def terminate(self):
        self.pending_updates.clear()
        await self.service.close()

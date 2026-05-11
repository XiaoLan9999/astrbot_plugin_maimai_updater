from __future__ import annotations

import asyncio
from dataclasses import dataclass

from astrbot.api import AstrBotConfig, logger
from astrbot.api.all import register
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import EventMessageType, command, event_message_type
from astrbot.api.star import Context, Star, StarTools

from .maimai_service import MaimaiService
from .message_recaller import RecallResult, MessageRecaller
from .storage import UserStore
from .utils import (
    extract_sgid,
    format_ts,
    is_probable_import_token,
    is_probable_sgid,
    mask_secret,
)


class PendingBindReplaced(RuntimeError):
    pass


@dataclass(slots=True)
class PendingBind:
    future: asyncio.Future


@dataclass(slots=True)
class SensitiveInput:
    value: str
    recall: RecallResult


@register(
    "astrbot_plugin_maimai_updater",
    "User",
    "使用一次性舞萌官方二维码凭据，把机台成绩同步到水鱼。",
    "0.2.0",
    "",
)
class MaimaiUpdaterPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict):
        super().__init__(context)
        self.context = context
        self.config = config or {}

        data_dir = StarTools.get_data_dir(plugin_name="astrbot_plugin_maimai_updater")
        self.store = UserStore(data_dir)

        self.bind_timeout = self._int_config("bind_timeout_seconds", 180)
        self.warn_unsupported_recall = bool(self.config.get("warn_unsupported_recall", True))
        self.service = MaimaiService(
            timeout=self._int_config("request_timeout_seconds", 30),
            http_proxy=str(self.config.get("maimai_http_proxy", "") or ""),
        )
        self.recaller = MessageRecaller(
            context,
            kook_token=str(self.config.get("kook_token", "") or ""),
        )
        self._pending_binds: dict[str, PendingBind] = {}

    def _int_config(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _message(text: str) -> MessageEventResult:
        return MessageEventResult().message(text)

    @staticmethod
    def _user_key(event: AstrMessageEvent) -> str:
        return f"{event.get_platform_name()}:{event.get_sender_id()}"

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

    def _cancel_old_pending(self, user_key: str) -> None:
        old = self._pending_binds.pop(user_key, None)
        if old and not old.future.done():
            old.future.set_exception(PendingBindReplaced())

    async def _request_sgid(
        self,
        event: AstrMessageEvent,
        user_key: str,
        *,
        prompt: str,
        timeout_message: str,
    ) -> SensitiveInput | MessageEventResult:
        self._cancel_old_pending(user_key)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_binds[user_key] = PendingBind(future=future)
        await self._send_text(event, prompt)

        try:
            sensitive: SensitiveInput = await asyncio.wait_for(
                future,
                timeout=max(self.bind_timeout, 1),
            )
            return sensitive
        except asyncio.TimeoutError:
            self._pending_binds.pop(user_key, None)
            return self._message(timeout_message)
        except PendingBindReplaced:
            return self._message("已开始新的 SGID 流程，旧流程已取消。")
        finally:
            current = self._pending_binds.get(user_key)
            if current and current.future is future and future.done():
                self._pending_binds.pop(user_key, None)

    @command("maimai_bind", alias={"舞萌绑定", "水鱼绑定"})
    async def bind_arcade(self, event: AstrMessageEvent):
        user_key = self._user_key(event)
        sensitive = await self._request_sgid(
            event,
            user_key,
            prompt=(
                f"请在 {self.bind_timeout} 秒内发送官方二维码识别出的 SGWCMAID/SGID 文本。\n"
                "这条 SGID 只用于本次账号验证，不会保存；群聊中我会尝试自动撤回。"
            ),
            timeout_message="⏰ 绑定超时，请重新执行 /maimai_bind。",
        )
        if not isinstance(sensitive, SensitiveInput):
            return sensitive

        if not is_probable_sgid(sensitive.value):
            return self._message(
                "❌ SGID 格式不正确，请重新执行 /maimai_bind 后发送以 SGWCMAID 开头的文本。"
            )

        await self._send_text(event, "⏳ 正在解析本次二维码，请稍候...")
        try:
            result = await self.service.bind_from_sgid(sensitive.value)
        except Exception as exc:
            logger.exception("[MaimaiUpdater] bind failed")
            return self._message(
                f"❌ 绑定失败：{self.service.describe_error(exc)}"
            )

        await self.store.set_player_profile(
            user_key,
            player_name="",
            rating=0,
        )
        lines = [
            "✅ 官方二维码验证成功！\n"
            "我不会保存本次 SGID 或官方临时凭据。之后更新水鱼仍需重新提供一次 SGID。\n"
            "接下来可发送 /maimai_token <水鱼 Import-Token>，再用 /maimai_update 更新水鱼。\n"
            "玩家名/Rating 会在更新时尽量从官方成绩链路获取。"
        ]
        if result.player_warning:
            lines.append(f"⚠️ {result.player_warning}")
        return self._message("\n".join(lines))

    @command("maimai_token", alias={"水鱼token"})
    async def bind_token(self, event: AstrMessageEvent, token: str = ""):
        token = (token or "").strip()
        if not token:
            return self._message(
                "用法：/maimai_token <水鱼 Import-Token>\n"
                "群聊中我会尝试撤回包含 Token 的消息。"
            )

        recall = await self.recaller.recall_sensitive(event)
        if recall.attempted:
            event.stop_event()
            await self._send_recall_notice(event, recall)

        if not is_probable_import_token(token):
            await self._send_text(
                event,
                "❌ 水鱼 Import-Token 格式看起来不正确，请确认长度约 127-132 字符且只包含字母、数字、_、-。",
            )
            return

        await self.store.set_import_token(self._user_key(event), token)
        await self._send_text(
            event,
            f"✅ 水鱼 Token 绑定成功：{mask_secret(token)}"
        )

    @command("maimai_update", alias={"更新水鱼", "更新b50"})
    async def update_scores(self, event: AstrMessageEvent):
        user_key = self._user_key(event)
        record = self.store.get(user_key)
        if not record.divingfish_import_token:
            return self._message(
                "❌ 尚未绑定水鱼 Import-Token。\n"
                "请先执行 /maimai_token <水鱼 Import-Token>。"
            )

        sensitive = await self._request_sgid(
            event,
            user_key,
            prompt=(
                f"请在 {self.bind_timeout} 秒内发送本次更新用的 SGWCMAID/SGID 文本。\n"
                "这条 SGID 只用于本次更新，使用后不会保存；群聊中我会尝试自动撤回。"
            ),
            timeout_message="⏰ 更新超时，请重新执行 /maimai_update。",
        )
        if not isinstance(sensitive, SensitiveInput):
            return sensitive

        if not is_probable_sgid(sensitive.value):
            return self._message(
                "❌ SGID 格式不正确，请重新执行 /maimai_update 后发送以 SGWCMAID 开头的文本。"
            )

        await self._send_text(event, "⏳ 正在用本次 SGID 拉取机台成绩并同步到水鱼，请稍候...")
        try:
            result = await self.service.sync_from_sgid_to_divingfish(
                sgid=sensitive.value,
                import_token=record.divingfish_import_token,
            )
        except Exception as exc:
            logger.exception("[MaimaiUpdater] update failed")
            msg = self.service.describe_error(exc)
            await self.store.set_sync_result(
                user_key,
                player_name=record.player_name,
                rating=record.rating,
                result=f"失败：{msg}",
            )
            return self._message(f"❌ 更新失败：{msg}")

        summary = f"成功，同步 {result.score_count} 条成绩"
        await self.store.set_sync_result(
            user_key,
            player_name=result.player_name,
            rating=result.rating,
            result=summary,
        )
        lines = [
            "✅ 水鱼更新完成！",
            f"玩家名：{result.player_name or record.player_name or '未知'}",
            f"Rating：{result.rating or record.rating}",
            f"成绩数：{result.score_count}",
            "现在可以用你现有的 B50 插件查询最新数据。",
        ]
        if result.player_warning:
            lines.append(f"⚠️ {result.player_warning}")
        return self._message("\n".join(lines))

    @command("maimai_status", alias={"水鱼状态"})
    async def status(self, event: AstrMessageEvent):
        record = self.store.get(self._user_key(event))
        lines = ["📋 maimai 水鱼更新状态"]
        lines.append("官方 SGID：不保存，每次绑定/更新都需要临时提供")
        lines.append(f"水鱼 Token：{mask_secret(record.divingfish_import_token)}")
        if record.player_name or record.rating:
            lines.append(f"玩家名：{record.player_name or '未知'}")
            lines.append(f"Rating：{record.rating}")
        lines.append(f"最近验证：{format_ts(record.bound_at)}")
        lines.append(f"上次更新：{format_ts(record.last_sync_at)}")
        if record.last_sync_result:
            lines.append(f"上次结果：{record.last_sync_result}")
        return self._message("\n".join(lines))

    @command("maimai_unbind", alias={"水鱼解绑"})
    async def unbind(self, event: AstrMessageEvent):
        removed = await self.store.remove(self._user_key(event))
        if removed:
            return self._message("✅ 已删除你的水鱼 Token 和本地展示状态。")
        return self._message("当前没有保存的绑定信息。")

    @event_message_type(EventMessageType.ALL)
    async def handle_pending_bind_message(self, event: AstrMessageEvent):
        user_key = self._user_key(event)
        pending = self._pending_binds.get(user_key)
        if not pending:
            return

        sgid = extract_sgid(event.message_str or "")
        if not sgid:
            return

        recall = await self.recaller.recall_sensitive(event)
        await self._send_recall_notice(event, recall)
        if not pending.future.done():
            pending.future.set_result(SensitiveInput(value=sgid, recall=recall))
        event.stop_event()

    async def terminate(self):
        for pending in list(self._pending_binds.values()):
            if not pending.future.done():
                pending.future.cancel()
        self._pending_binds.clear()
        await self.service.close()

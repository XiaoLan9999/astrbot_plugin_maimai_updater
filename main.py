from __future__ import annotations

import asyncio
from dataclasses import dataclass

from astrbot.api import AstrBotConfig, logger
from astrbot.api.all import register
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult
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
    prompt_event: AstrMessageEvent


@dataclass(slots=True)
class SensitiveInput:
    value: str
    recall: RecallResult


@register(
    "astrbot_plugin_maimai_updater",
    "User",
    "绑定舞萌官方二维码凭据和水鱼 Import-Token，并把机台成绩同步到水鱼。",
    "0.1.3",
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
        await event.send(MessageChain().message(text))

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

    @command("maimai_bind", alias={"舞萌绑定", "水鱼绑定"})
    async def bind_arcade(self, event: AstrMessageEvent):
        user_key = self._user_key(event)
        self._cancel_old_pending(user_key)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_binds[user_key] = PendingBind(future=future, prompt_event=event)

        await self._send_text(
            event,
            f"请在 {self.bind_timeout} 秒内发送官方二维码识别出的 SGWCMAID/SGID 文本。\n"
            "群聊中我会尝试自动撤回包含 SGID 的消息；私聊不会撤回。",
        )

        try:
            sensitive: SensitiveInput = await asyncio.wait_for(
                future,
                timeout=max(self.bind_timeout, 1),
            )
        except asyncio.TimeoutError:
            self._pending_binds.pop(user_key, None)
            return self._message("⏰ 绑定超时，请重新执行 /maimai_bind。")
        except PendingBindReplaced:
            return self._message("已开始新的绑定流程，旧流程已取消。")
        finally:
            current = self._pending_binds.get(user_key)
            if current and current.future is future and future.done():
                self._pending_binds.pop(user_key, None)

        if not is_probable_sgid(sensitive.value):
            return self._message(
                "❌ SGID 格式不正确，请重新执行 /maimai_bind 后发送以 SGWCMAID 开头的文本。"
            )

        await self._send_text(event, "⏳ 正在解析二维码并获取玩家信息，请稍候...")
        try:
            result = await self.service.bind_from_sgid(sensitive.value)
        except Exception as exc:
            logger.exception("[MaimaiUpdater] bind failed")
            return self._message(
                f"❌ 绑定失败：{self.service.describe_error(exc)}"
            )

        await self.store.set_arcade_credentials(
            user_key,
            arcade_credentials=result.arcade_credentials,
            player_name=result.player_name,
            rating=result.rating,
        )
        return self._message(
            "✅ 官方账号绑定成功！\n"
            f"玩家名：{result.player_name or '未知'}\n"
            f"Rating：{result.rating}\n"
            "接下来可发送 /maimai_token <水鱼 Import-Token>，再用 /maimai_update 更新水鱼。"
        )

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
        missing = []
        if not record.arcade_credentials:
            missing.append("官方账号")
        if not record.divingfish_import_token:
            missing.append("水鱼 Import-Token")
        if missing:
            return self._message(
                "❌ 尚未完成绑定："
                + "、".join(missing)
                + "。\n请先执行 /maimai_bind 和 /maimai_token。"
            )

        await self._send_text(event, "⏳ 正在从机台数据源拉取成绩并同步到水鱼，请稍候...")
        try:
            result = await self.service.sync_to_divingfish(
                arcade_credentials=record.arcade_credentials,
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
        return self._message(
            "✅ 水鱼更新完成！\n"
            f"玩家名：{result.player_name or record.player_name or '未知'}\n"
            f"Rating：{result.rating}\n"
            f"成绩数：{result.score_count}\n"
            "现在可以用你现有的 B50 插件查询最新数据。"
        )

    @command("maimai_status", alias={"水鱼状态"})
    async def status(self, event: AstrMessageEvent):
        record = self.store.get(self._user_key(event))
        lines = ["📋 maimai 水鱼更新状态"]
        lines.append(f"官方账号：{'已绑定' if record.arcade_credentials else '未绑定'}")
        lines.append(f"水鱼 Token：{mask_secret(record.divingfish_import_token)}")
        if record.player_name or record.rating:
            lines.append(f"玩家名：{record.player_name or '未知'}")
            lines.append(f"Rating：{record.rating}")
        lines.append(f"绑定时间：{format_ts(record.bound_at)}")
        lines.append(f"上次更新：{format_ts(record.last_sync_at)}")
        if record.last_sync_result:
            lines.append(f"上次结果：{record.last_sync_result}")
        return self._message("\n".join(lines))

    @command("maimai_unbind", alias={"水鱼解绑"})
    async def unbind(self, event: AstrMessageEvent):
        removed = await self.store.remove(self._user_key(event))
        if removed:
            return self._message("✅ 已删除你的官方账号凭据和水鱼 Token。")
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

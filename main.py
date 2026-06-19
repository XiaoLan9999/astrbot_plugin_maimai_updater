from __future__ import annotations

import hashlib
import time

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
    "0.5.2",
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
        )
        self.recaller = MessageRecaller(
            context,
            kook_token=str(self.config.get("kook_token", "") or ""),
        )
        self.sgid_max_age_seconds = self._int_config("sgid_max_age_seconds", 180)
        self._used_sgid_hashes: dict[str, float] = {}

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
        return "更新水鱼 SGWCMAID..."

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

        await self._recall_current_message(event)
        event.stop_event()

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
                f"maimaiupdate <SGID> / {self._prefixless_update_example()} 即可更新 B50。"
            )
        else:
            update_hint = f"之后直接发送 {self._prefixless_update_example()} 即可更新 B50。"
        await self._send_text(
            event,
            f"✅ 水鱼绑定成功：{mask_secret(token)}\n"
            f"{update_hint}",
        )

    @command("maimaiupdate", alias={"更新水鱼", "水鱼更新", "更新b50", "更新B50"})
    async def update_scores(self, event: AstrMessageEvent, credential_text: str = ""):
        credential_text = (credential_text or "").strip()
        if not extract_sgid(credential_text):
            update_usage = self._prefixless_update_example()
            if self.require_command_prefix:
                update_usage = f"maimaiupdate <SGID> / {self._prefixless_update_example()}"
            return self._message(
                f"用法：{update_usage}\n"
                "注意：当前 SGID 机台源暂时无法提供 FULL COMBO/FULL SYNC/AP 标识。"
            )

        await self._recall_current_message(event)
        event.stop_event()
        await self._update_from_credential(event, credential_text)

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
        return self._message("✅ 已向水鱼发送清空成绩请求。重新发送新的 SGID 即可再次更新 B50。")

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
        lines.append("官方 SGID：不保存，每次更新都需要临时提供")
        lines.append(f"水鱼 Token：{mask_secret(record.divingfish_import_token)}")
        if record.rating:
            lines.append(f"Rating：{record.rating}")
        lines.append(f"上次更新：{format_ts(record.last_sync_at)}")
        if record.last_sync_result:
            lines.append(f"上次结果：{record.last_sync_result}")
        return self._message("\n".join(lines))

    @command("maimaiunbind", alias={"水鱼解绑"})
    async def unbind(self, event: AstrMessageEvent):
        removed = await self.store.remove(self._user_key(event))
        if removed:
            return self._message("✅ 已删除你的水鱼 Token 和本地展示状态。")
        return self._message("当前没有保存的绑定信息。")

    @event_message_type(EventMessageType.ALL)
    async def handle_plain_command(self, event: AstrMessageEvent):
        parsed = self._parse_plain_command(event.message_str or "")
        if not parsed:
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
        await self.service.close()

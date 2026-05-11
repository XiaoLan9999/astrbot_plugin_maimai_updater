from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from astrbot.api import logger
except ImportError:  # pragma: no cover - used by local unit tests outside AstrBot
    import logging

    logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecallResult:
    attempted: bool
    success: bool
    message: str = ""

    @property
    def warning(self) -> str:
        if not self.attempted or self.success:
            return ""
        return self.message


class MessageRecaller:
    KOOK_API_BASE = "https://www.kookapp.cn/api/v3"

    def __init__(self, context: Any, *, kook_token: str = ""):
        self.context = context
        self.kook_token = (kook_token or "").strip()

    async def recall_sensitive(self, event: Any) -> RecallResult:
        if not self._is_group_message(event):
            return RecallResult(False, False, "私聊消息不会自动撤回。")

        msg_id = self._message_id(event)
        if not msg_id:
            return RecallResult(True, False, "未能获取消息 ID，请手动撤回刚才发送的敏感消息。")

        platform_name = self._platform_name(event)
        if platform_name == "kook":
            return await self._recall_kook(msg_id)

        if self._looks_like_onebot(platform_name):
            return await self._recall_onebot(platform_name, msg_id)

        onebot_result = await self._recall_onebot(platform_name, msg_id)
        if onebot_result.success:
            return onebot_result

        return RecallResult(
            True,
            False,
            "当前平台不支持自动撤回，请手动撤回刚才发送的敏感消息。",
        )

    @staticmethod
    def _platform_name(event: Any) -> str:
        getter = getattr(event, "get_platform_name", None)
        if callable(getter):
            try:
                return str(getter() or "").lower()
            except Exception:
                return ""
        return ""

    @staticmethod
    def _message_id(event: Any) -> str:
        msg_obj = getattr(event, "message_obj", None)
        value = getattr(msg_obj, "message_id", "") if msg_obj is not None else ""
        if value:
            return str(value)
        raw = getattr(msg_obj, "raw_message", None) if msg_obj is not None else None
        if isinstance(raw, dict):
            for key in ("message_id", "msg_id", "id"):
                if raw.get(key):
                    return str(raw[key])
            data = raw.get("data")
            if isinstance(data, dict):
                for key in ("message_id", "msg_id", "id"):
                    if data.get(key):
                        return str(data[key])
        return str(value or "")

    @staticmethod
    def _is_group_message(event: Any) -> bool:
        getter = getattr(event, "get_group_id", None)
        if callable(getter):
            try:
                if getter():
                    return True
            except Exception:
                pass
        msg_obj = getattr(event, "message_obj", None)
        return bool(getattr(msg_obj, "group_id", "") if msg_obj is not None else "")

    @staticmethod
    def _looks_like_onebot(platform_name: str) -> bool:
        return any(mark in platform_name for mark in ("aiocqhttp", "onebot", "napcat"))

    def _find_platform_inst(self, platform_name: str) -> Any | None:
        getter = getattr(self.context, "get_platform_inst", None)
        if callable(getter) and platform_name:
            try:
                inst = getter(platform_name)
                if inst:
                    return inst
            except Exception:
                pass
        manager = getattr(self.context, "platform_manager", None)
        for inst in getattr(manager, "platform_insts", []) or []:
            try:
                meta = inst.meta()
                if str(meta.name).lower() == platform_name:
                    return inst
            except Exception:
                continue
        return None

    def _find_kook_token(self) -> str:
        if self.kook_token:
            return self.kook_token
        inst = self._find_platform_inst("kook")
        config = getattr(inst, "config", {}) if inst is not None else {}
        if isinstance(config, dict):
            return str(config.get("kook_bot_token") or "").strip()
        return ""

    async def _recall_kook(self, msg_id: str) -> RecallResult:
        token = self._find_kook_token()
        if not token:
            return RecallResult(True, False, "未配置 KOOK Bot Token，无法自动撤回，请手动撤回敏感消息。")
        try:
            import httpx
        except ImportError:
            return RecallResult(True, False, "缺少 httpx 依赖，无法自动撤回 KOOK 消息，请手动撤回敏感消息。")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.KOOK_API_BASE}/message/delete",
                    headers={"Authorization": f"Bot {token}"},
                    json={"msg_id": msg_id},
                )
            if resp.status_code == 200 and resp.json().get("code") == 0:
                return RecallResult(True, True)
        except Exception:
            logger.exception("[MaimaiUpdater] KOOK recall failed")
            return RecallResult(True, False, "KOOK 撤回失败，请手动撤回敏感消息。")
        return RecallResult(True, False, "KOOK 撤回失败，请确认 Bot 拥有管理消息权限。")

    async def _recall_onebot(self, platform_name: str, msg_id: str) -> RecallResult:
        inst = self._find_platform_inst(platform_name)
        client = inst.get_client() if inst is not None and hasattr(inst, "get_client") else None
        if not client or not hasattr(client, "call_action"):
            return RecallResult(True, False, "当前平台不支持自动撤回，请手动撤回刚才发送的敏感消息。")
        try:
            message_id: int | str = int(msg_id) if str(msg_id).isdigit() else msg_id
            await client.call_action("delete_msg", message_id=message_id)
            return RecallResult(True, True)
        except Exception:
            logger.exception("[MaimaiUpdater] OneBot recall failed")
            return RecallResult(True, False, "消息撤回失败，请确认 Bot 拥有撤回权限并手动撤回敏感消息。")

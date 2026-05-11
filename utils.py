from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

SGID_PATTERN = re.compile(r"(SGWCMAID[^\s<>\]\[\"']+)", re.IGNORECASE)
SGID_TIMESTAMP_PATTERN = re.compile(r"^SGWCMAID(\d{12})", re.IGNORECASE)
IMPORT_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{100,180}$")


@dataclass(frozen=True, slots=True)
class SgidFreshness:
    ok: bool
    message: str = ""
    issued_at: int = 0


def now_ts() -> int:
    return int(datetime.now().timestamp())


def format_ts(value: int | None) -> str:
    if not value:
        return "未记录"
    return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")


def extract_sgid(text: str) -> str | None:
    match = SGID_PATTERN.search((text or "").strip())
    if not match:
        return None
    return match.group(1).strip()


def is_probable_sgid(value: str) -> bool:
    value = (value or "").strip()
    return value.upper().startswith("SGWCMAID") and 12 <= len(value) <= 1024


def sgid_issued_at(value: str) -> int | None:
    match = SGID_TIMESTAMP_PATTERN.match((value or "").strip())
    if not match:
        return None
    try:
        dt = datetime.strptime(f"20{match.group(1)}", "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return int(dt.timestamp())


def validate_sgid_freshness(
    value: str,
    *,
    max_age_seconds: int = 180,
    future_tolerance_seconds: int = 60,
    now: int | None = None,
) -> SgidFreshness:
    issued_at = sgid_issued_at(value)
    if issued_at is None:
        return SgidFreshness(False, "SGID 时间戳无法解析，请重新从官方公众号获取二维码后再试。")
    current = int(now_ts() if now is None else now)
    age = current - issued_at
    if age < -abs(int(future_tolerance_seconds)):
        return SgidFreshness(False, "SGID 时间晚于当前系统时间，请检查服务器时间或重新获取二维码。", issued_at)
    if age > max(1, int(max_age_seconds)):
        return SgidFreshness(
            False,
            f"SGID 已超过 {max_age_seconds} 秒有效窗口，请重新从官方公众号获取二维码后再试。",
            issued_at,
        )
    return SgidFreshness(True, issued_at=issued_at)


def is_probable_import_token(value: str) -> bool:
    return bool(IMPORT_TOKEN_PATTERN.fullmatch((value or "").strip()))


def mask_secret(value: Any, visible_prefix: int = 6, visible_suffix: int = 4) -> str:
    if value is None:
        return "未绑定"
    text = str(value)
    if not text:
        return "未绑定"
    if len(text) <= visible_prefix + visible_suffix:
        return "*" * len(text)
    return f"{text[:visible_prefix]}***{text[-visible_suffix:]}"


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

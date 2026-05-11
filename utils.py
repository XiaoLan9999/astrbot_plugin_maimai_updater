from __future__ import annotations

import re
from datetime import datetime
from typing import Any

SGID_PATTERN = re.compile(r"(SGWCMAID[^\s<>\]\[\"']+)", re.IGNORECASE)
IMPORT_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{100,180}$")


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


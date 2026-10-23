from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalRuntime:
    wine_binary: Path
    prefix: Path


def is_arm64_linux() -> bool:
    return sys.platform == "linux" and platform.machine().lower() in {"aarch64", "arm64"}


def runtime_home() -> Path:
    configured = os.environ.get("MAIMAI_CHIME_RUNTIME_DIR", "")
    return Path(configured).expanduser() if configured else Path.home() / ".local/share/astrbot-maimai/native"


def prepared_runtime() -> LocalRuntime | None:
    try:
        data = json.loads((runtime_home() / "runtime.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != 1 or data.get("probe") != "dll_exports":
            return None
        wine = Path(data["wine_binary"])
        prefix = Path(data["prefix"])
        if not wine.is_absolute() or not wine.is_file() or not prefix.is_absolute() or not prefix.is_dir():
            return None
        return LocalRuntime(wine, prefix)
    except (OSError, ValueError, TypeError, KeyError):
        return None

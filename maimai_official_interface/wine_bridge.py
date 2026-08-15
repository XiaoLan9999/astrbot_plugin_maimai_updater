from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BRIDGE_PATH_ENV = "MAIMAI_CHIME_BRIDGE_PATH"
WINE_BINARY_ENV = "MAIMAI_CHIME_WINE_BINARY"
WINE_PREFIX_ENV = "MAIMAI_CHIME_WINEPREFIX"
DEFAULT_BRIDGE_PATH = Path("/opt/maimai-chime/chime_bridge.exe")
BRIDGE_PROTOCOL_VERSION = 1
_PROCESS_LOCK = threading.Lock()


class WineBridgeError(RuntimeError):
    pass


class WineBridgeUnavailableError(WineBridgeError):
    pass


class WineBridgeSessionError(WineBridgeError):
    pass


@dataclass(frozen=True, slots=True)
class WineBridgeSession:
    user_id: int
    token: str


def _safe_stage(value: Any) -> str:
    text = str(value or "unknown")[:64]
    cleaned = "".join(char for char in text if char.isalnum() or char in "_-.")
    return cleaned or "unknown"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class WineChimeBridge:
    def __init__(
        self,
        *,
        dll_path: str | Path,
        bridge_path: str | Path | None = None,
        wine_binary: str | Path | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.dll_path = Path(dll_path).expanduser()
        self.bridge_path = self._resolve_bridge_path(bridge_path)
        self.wine_binary = self._resolve_wine_binary(wine_binary)
        self.timeout = max(float(timeout or 20.0), 1.0)

    def _resolve_bridge_path(self, configured: str | Path | None) -> Path:
        if configured:
            candidate = Path(configured).expanduser()
            if candidate.is_file():
                return candidate
            raise WineBridgeUnavailableError("configured official Wine bridge is unavailable")
        if env_path := os.environ.get(BRIDGE_PATH_ENV):
            candidate = Path(env_path).expanduser()
            if candidate.is_file():
                return candidate
            raise WineBridgeUnavailableError("configured official Wine bridge is unavailable")
        for candidate in (self.dll_path.parent / "chime_bridge.exe", DEFAULT_BRIDGE_PATH):
            if candidate.is_file():
                return candidate
        raise WineBridgeUnavailableError("official Wine bridge executable is unavailable")

    @staticmethod
    def _resolve_wine_binary(configured: str | Path | None) -> str:
        if configured:
            candidate = str(configured)
            path = Path(candidate).expanduser()
            if path.is_absolute() and path.is_file():
                return str(path)
            if resolved := shutil.which(candidate):
                return resolved
            raise WineBridgeUnavailableError("configured Wine x64 runtime is unavailable")
        if env_binary := os.environ.get(WINE_BINARY_ENV):
            path = Path(env_binary).expanduser()
            if path.is_absolute() and path.is_file():
                return str(path)
            if resolved := shutil.which(env_binary):
                return resolved
            raise WineBridgeUnavailableError("configured Wine x64 runtime is unavailable")

        for candidate in ("wine", "wine64", "/usr/lib/wine/wine64"):
            path = Path(candidate).expanduser()
            if path.is_absolute() and path.is_file():
                return str(path)
            if resolved := shutil.which(candidate):
                return resolved
        raise WineBridgeUnavailableError("Wine x64 runtime is unavailable")

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment.setdefault("WINEARCH", "win64")
        environment.setdefault("WINEDEBUG", "-all")
        if prefix := environment.get(WINE_PREFIX_ENV):
            environment["WINEPREFIX"] = prefix
        return environment

    @staticmethod
    def _parse_payload(stdout: str) -> dict[str, Any]:
        for line in reversed((stdout or "").splitlines()):
            candidate = line.strip()
            if not candidate.startswith("{"):
                continue
            try:
                payload = json.loads(candidate)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return payload
        raise WineBridgeSessionError("official Wine bridge returned an invalid response")

    def _invoke(self, *, input_text: str = "", probe: bool = False) -> dict[str, Any]:
        if not self.dll_path.is_file():
            raise WineBridgeUnavailableError("official runtime asset is unavailable")

        command = [self.wine_binary, str(self.bridge_path)]
        if probe:
            command.append("--probe")

        try:
            with _PROCESS_LOCK:
                completed = subprocess.run(
                    command,
                    input=input_text,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(self.dll_path.parent),
                    env=self._environment(),
                    timeout=self.timeout + 5.0,
                    check=False,
                    start_new_session=True,
                )
        except subprocess.TimeoutExpired as exc:
            raise WineBridgeSessionError("official Wine bridge process timed out") from exc
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise WineBridgeUnavailableError("official Wine bridge process could not start") from exc

        payload = self._parse_payload(completed.stdout)
        if _safe_int(payload.get("protocol")) != BRIDGE_PROTOCOL_VERSION:
            raise WineBridgeUnavailableError(
                "official Wine bridge protocol version is incompatible"
            )
        if completed.returncode != 0 or payload.get("ok") is not True:
            stage = _safe_stage(payload.get("stage"))
            error_id = _safe_int(payload.get("error_id"))
            message = f"official Wine bridge failed at stage={stage}"
            if error_id:
                message += f" error_id={error_id}"
            error_type = (
                WineBridgeUnavailableError
                if completed.returncode in {10, 11}
                else WineBridgeSessionError
            )
            raise error_type(message)
        return payload

    def probe(self) -> str:
        payload = self._invoke(probe=True)
        stage = _safe_stage(payload.get("stage"))
        if stage != "dll_exports":
            raise WineBridgeUnavailableError("official Wine bridge probe returned an unexpected stage")
        return stage

    def resolve(
        self,
        sgid: str,
        *,
        game_id: str,
        qr_game_id: str,
        chip_id: str,
        common_key: str,
        title_key: str,
        server_url_index: int,
    ) -> WineBridgeSession:
        timeout_ms = max(1000, min(int(self.timeout * 1000), 120000))
        input_text = "\n".join(
            (
                str(sgid or "").strip(),
                str(game_id or "MAID"),
                str(qr_game_id or "MAID"),
                str(chip_id or ""),
                str(common_key or ""),
                str(title_key or "SDGB"),
                str(int(server_url_index or 0)),
                str(timeout_ms),
            )
        ) + "\n"
        payload = self._invoke(input_text=input_text)
        user_id = _safe_int(payload.get("user_id"))
        token = str(payload.get("token") or "")
        if not user_id or not token:
            raise WineBridgeSessionError(
                "official Wine bridge returned an empty user_id or token"
            )
        return WineBridgeSession(user_id=user_id, token=token)

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from importlib import metadata
import sys
from typing import Any

from .official_protocol import (
    DEFAULT_OFFICIAL_TITLE_ENDPOINTS,
    ChimeSession,
    ChimeSessionError,
    ChimeSessionResolver,
    OfficialProtocolError,
    OfficialProtocolUnavailableError,
    OfficialTitleClient,
    OfficialTitleServerError,
    combo_status_to_fc_name,
    sync_status_to_fs_name,
)

try:
    from astrbot.api import logger
except ModuleNotFoundError:  # pragma: no cover - local tests without AstrBot installed.
    import logging

    logger = logging.getLogger(__name__)


class MaimaiDependencyError(RuntimeError):
    pass


MIN_MAIMAI_PY = (1, 5, 1)
MIN_MAIMAI_FFI = (0, 7, 0)
MIN_CN_CURRENT_VERSION_NAME = "MAIMAI_DX_CIRCLE"
SCORE_SOURCE_ARCADE = "arcade"
SCORE_SOURCE_OFFICIAL_ONLY = "official_only"
SCORE_SOURCE_OFFICIAL_THEN_ARCADE = "official_then_arcade"
SCORE_SOURCE_MODES = {
    SCORE_SOURCE_ARCADE,
    SCORE_SOURCE_OFFICIAL_ONLY,
    SCORE_SOURCE_OFFICIAL_THEN_ARCADE,
}
DEFAULT_OFFICIAL_KEYCHIP_ID = "A63E-01E11890000"
DEFAULT_OFFICIAL_PLACE_ID = 3496
ACCEPTED_OFFICIAL_LOGIN_RETURN_CODES = {1, 100}


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in version.replace("-", ".").split("."):
        digits = ""
        for char in part:
            if not char.isdigit():
                break
            digits += char
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def _is_version_at_least(version: str, minimum: tuple[int, ...]) -> bool:
    parsed = _parse_version(version)
    width = max(len(parsed), len(minimum))
    return parsed + (0,) * (width - len(parsed)) >= minimum + (0,) * (width - len(minimum))


def _version_value(version: Any) -> int:
    try:
        return int(getattr(version, "value", version) or 0)
    except (TypeError, ValueError):
        return 0


def _patch_maimai_current_version(enums_module: Any, maimai_module: Any) -> bool:
    version_cls = getattr(enums_module, "Version", None)
    minimum_current = getattr(version_cls, MIN_CN_CURRENT_VERSION_NAME, None)
    if minimum_current is None:
        return False

    patched = False
    for module in (enums_module, maimai_module):
        current = getattr(module, "current_version", None)
        if _version_value(current) < _version_value(minimum_current):
            setattr(module, "current_version", minimum_current)
            patched = True
    return patched


def _short_keychip_id(keychip_id: str) -> str:
    value = (keychip_id or "").strip()
    if "-" in value:
        return "".join(ch for ch in value.rsplit("-", 1)[-1] if ch.isalnum())
    return "".join(ch for ch in value if ch.isalnum())


def _chime_keychip_id(keychip_id: str) -> str:
    value = (keychip_id or "").strip()
    if "-" in value:
        return "".join(ch for ch in value.rsplit("-", 1)[-1] if ch.isalnum())
    return "".join(ch for ch in value if ch.isalnum())


@dataclass(slots=True)
class BindResult:
    player_warning: str = ""


@dataclass(slots=True)
class SyncResult:
    player_name: str
    rating: int
    score_count: int
    player_warning: str = ""
    marked_score_count: int = 0
    source: str = "arcade"


class MaimaiService:
    def __init__(
        self,
        *,
        timeout: float = 30.0,
        http_proxy: str = "",
        score_source_mode: str = "",
        official_protocol_enabled: bool = False,
        official_chimelib_dll_path: str = "",
        official_title_base_url: str = "",
        official_client_id: str = "",
        official_region_id: int = 8,
        official_place_id: int = DEFAULT_OFFICIAL_PLACE_ID,
        official_server_url_index: int = 0,
        official_keychip_id: str = "",
        official_game_id: str = "MAID",
        official_title_key: str = "SDGB",
        official_interface_enabled: bool = True,
    ):
        self.timeout = float(timeout or 30.0)
        self.http_proxy = (http_proxy or "").strip() or None
        self._client: Any | None = None
        self._imports: dict[str, Any] | None = None
        self.score_source_mode = (score_source_mode or "").strip().lower()
        self.official_protocol_enabled = bool(official_protocol_enabled)
        self.official_chimelib_dll_path = (official_chimelib_dll_path or "").strip()
        self.official_title_base_url = (official_title_base_url or "").strip()
        self.official_client_id = (official_client_id or "").strip()
        self.official_region_id = int(official_region_id or 8)
        self.official_place_id = int(official_place_id or DEFAULT_OFFICIAL_PLACE_ID)
        self.official_server_url_index = int(official_server_url_index or 0)
        self.official_keychip_id = (official_keychip_id or "").strip()
        self.official_game_id = (official_game_id or "MAID").strip() or "MAID"
        self.official_title_key = (official_title_key or "SDGB").strip() or "SDGB"
        self.official_interface_enabled = bool(official_interface_enabled)
        self._ffi_request_lock = asyncio.Lock()

    def _ensure_dependency_versions(self) -> None:
        requirements = (
            ("maimai-py", MIN_MAIMAI_PY),
            ("maimai-ffi", MIN_MAIMAI_FFI),
        )
        installed: list[str] = []
        too_old: list[str] = []
        missing: list[str] = []
        for package_name, minimum in requirements:
            minimum_text = ".".join(str(part) for part in minimum)
            try:
                version = metadata.version(package_name)
            except metadata.PackageNotFoundError:
                missing.append(f"{package_name}>={minimum_text}")
                continue
            installed.append(f"{package_name}=={version}")
            if not _is_version_at_least(version, minimum):
                too_old.append(f"{package_name}=={version}，需要 >= {minimum_text}")

        if missing or too_old:
            detail = "；".join(missing + too_old)
            installed_text = "，当前已安装：" + "、".join(installed) if installed else ""
            raise MaimaiDependencyError(
                "maimai-py/maimai-ffi 版本不满足当前插件要求。"
                f"{detail}{installed_text}。"
                "请完全关闭 AstrBot 后重新安装 requirements.txt，再启动 AstrBot。"
            )

    def _load_imports(self) -> dict[str, Any]:
        if self._imports is not None:
            return self._imports
        self._ensure_dependency_versions()
        try:
            from maimai_py import (  # type: ignore
                ArcadeProvider,
                DivingFishProvider,
                MaimaiClient,
                PlayerIdentifier,
            )
            from maimai_py import exceptions as maimai_exceptions  # type: ignore
            from maimai_py import enums as maimai_enums  # type: ignore
            from maimai_py import maimai as maimai_core  # type: ignore
            from maimai_py.maimai import MaimaiScores  # type: ignore
            from maimai_py.enums import FCType, FSType, LevelIndex, RateType, SongType  # type: ignore
            from maimai_py.models import Score  # type: ignore
            import httpx
        except SyntaxError as exc:
            raise MaimaiDependencyError(
                "maimai-py/maimai-ffi 依赖导入失败，当前安装可能版本冲突或文件损坏。"
                "请在 AstrBot 的 Python 环境中重新安装 requirements.txt。"
            ) from exc
        except ImportError as exc:
            raise MaimaiDependencyError(
                "缺少 maimai-py 依赖，请先安装插件 requirements.txt。"
            ) from exc

        if _patch_maimai_current_version(maimai_enums, maimai_core):
            logger.info(
                "[MaimaiUpdater] patched maimai.py current_version to %s for MAIMAI2026 rating",
                MIN_CN_CURRENT_VERSION_NAME,
            )

        self._imports = {
            "ArcadeProvider": ArcadeProvider,
            "DivingFishProvider": DivingFishProvider,
            "MaimaiClient": MaimaiClient,
            "MaimaiScores": MaimaiScores,
            "PlayerIdentifier": PlayerIdentifier,
            "Score": Score,
            "FCType": FCType,
            "FSType": FSType,
            "LevelIndex": LevelIndex,
            "RateType": RateType,
            "SongType": SongType,
            "AimeServerError": getattr(maimai_exceptions, "AimeServerError", None),
            "ArcadeError": getattr(maimai_exceptions, "ArcadeError", None),
            "ArcadeIdentifierError": getattr(maimai_exceptions, "ArcadeIdentifierError", None),
            "InvalidDeveloperTokenError": getattr(maimai_exceptions, "InvalidDeveloperTokenError", None),
            "InvalidPlayerIdentifierError": getattr(maimai_exceptions, "InvalidPlayerIdentifierError", None),
            "MaimaiPyError": getattr(maimai_exceptions, "MaimaiPyError", None),
            "PrivacyLimitationError": getattr(maimai_exceptions, "PrivacyLimitationError", None),
            "TitleServerBlockedError": getattr(maimai_exceptions, "TitleServerBlockedError", None),
            "TitleServerError": getattr(maimai_exceptions, "TitleServerError", None),
            "TitleServerNetworkError": getattr(maimai_exceptions, "TitleServerNetworkError", None),
            "HTTPError": httpx.HTTPError,
        }
        return self._imports

    @property
    def client(self) -> Any:
        imports = self._load_imports()
        if self._client is None:
            self._client = imports["MaimaiClient"](timeout=self.timeout)
        return self._client

    def _arcade_provider(self) -> Any:
        return self._load_imports()["ArcadeProvider"](http_proxy=self.http_proxy)

    def _divingfish_provider(self) -> Any:
        return self._load_imports()["DivingFishProvider"]()

    def _identifier(self, *, credentials: str) -> Any:
        return self._load_imports()["PlayerIdentifier"](credentials=credentials)

    def _configured_chimelib_path(self) -> Path | None:
        if not self.official_chimelib_dll_path:
            return None
        return Path(self.official_chimelib_dll_path).expanduser()

    def _chimelib_candidates(self) -> list[Path]:
        plugin_dir = Path(__file__).resolve().parent
        candidates = [
            plugin_dir / "_resources" / "core.dat",
            plugin_dir / "chimelib_dll.dll",
            plugin_dir / "bin" / "chimelib_dll.dll",
        ]
        for parent in plugin_dir.parents:
            candidates.append(
                parent
                / "sdgb_analysis"
                / "extracted"
                / "Package"
                / "Sinmai_Data"
                / "Plugins"
                / "chimelib_dll.dll"
            )
        seen: set[str] = set()
        unique: list[Path] = []
        for candidate in candidates:
            key = str(candidate).lower()
            if key not in seen:
                unique.append(candidate)
                seen.add(key)
        return unique

    def _find_chimelib_dll_path(self) -> Path | None:
        configured = self._configured_chimelib_path()
        if configured is not None:
            if configured.is_file():
                return configured
            raise OfficialProtocolUnavailableError(
                "official runtime asset is unavailable"
            )

        for candidate in self._chimelib_candidates():
            if candidate.is_file():
                return candidate
        return None

    def _official_interface_chimelib_path(self) -> Path | None:
        configured = self._configured_chimelib_path()
        if configured is not None:
            if configured.is_file():
                return configured
            raise OfficialProtocolUnavailableError(
                "official runtime asset is unavailable"
            )

        bundled = Path(__file__).resolve().parent / "_resources" / "core.dat"
        if bundled.is_file():
            return bundled
        return None

    def _load_official_interface_client_cls(self) -> Any | None:
        if not self.official_interface_enabled:
            return None
        try:
            from maimai_official_interface import MaimaiOfficialClient  # type: ignore
            return MaimaiOfficialClient
        except (ImportError, AttributeError):
            pass

        plugin_dir = Path(__file__).resolve().parent
        vendored_init = plugin_dir / "maimai_official_interface" / "__init__.py"
        if vendored_init.is_file():
            plugin_dir_text = str(plugin_dir)
            if plugin_dir_text not in sys.path:
                sys.path.insert(0, plugin_dir_text)
            sys.modules.pop("maimai_official_interface", None)
            try:
                from maimai_official_interface import MaimaiOfficialClient  # type: ignore
                return MaimaiOfficialClient
            except (ImportError, AttributeError):
                pass

        for parent in (plugin_dir.parent, *plugin_dir.parents):
            repo_root = parent / "maimai_official_interface"
            package_init = repo_root / "maimai_official_interface" / "__init__.py"
            if not package_init.is_file():
                continue
            repo_root_text = str(repo_root)
            if repo_root_text not in sys.path:
                sys.path.insert(0, repo_root_text)
            sys.modules.pop("maimai_official_interface", None)
            try:
                from maimai_official_interface import MaimaiOfficialClient  # type: ignore
                return MaimaiOfficialClient
            except (ImportError, AttributeError):
                continue
        return None

    def _official_interface_client(self) -> Any | None:
        client_cls = self._load_official_interface_client_cls()
        if client_cls is None:
            return None

        chimelib_path = self._official_interface_chimelib_path()
        kwargs: dict[str, Any] = {
            "keychip_id": self.official_keychip_id or DEFAULT_OFFICIAL_KEYCHIP_ID,
            "region_id": self.official_region_id,
            "place_id": self.official_place_id,
            "game_id": self.official_game_id or "MAID",
            "qr_game_id": "MAID",
            "title_key": self.official_title_key or "SDGB",
            "server_url_index": self.official_server_url_index,
            "timeout": self.timeout,
            "http_proxy": self.http_proxy,
        }
        if chimelib_path is not None:
            kwargs["chimelib_path"] = chimelib_path
        return client_cls(**kwargs)

    async def _official_session_from_sgid(self, sgid: str) -> ChimeSession:
        dll_path = self._find_chimelib_dll_path()
        if dll_path is None:
            raise OfficialProtocolUnavailableError(
                "official runtime asset is unavailable"
            )

        resolver = ChimeSessionResolver(
            dll_path=str(dll_path),
            game_id=self.official_game_id or "MAID",
            qr_game_id="MAID",
            chip_id=_chime_keychip_id(self.official_keychip_id or DEFAULT_OFFICIAL_KEYCHIP_ID),
            title_key=self.official_title_key or "SDGB",
            server_url_index=self.official_server_url_index,
            timeout=self.timeout,
        )
        try:
            session = await resolver.resolve_async(sgid)
        except ChimeSessionError:
            raise
        logger.info(
            "[MaimaiUpdater] resolved official one-time session user_id=%s",
            session.user_id,
        )
        return session

    def _log_nonfatal_player_error(self, exc: BaseException, *, stage: str) -> None:
        logger.warning(
            "[MaimaiUpdater] player metadata fetch failed during %s: %s: %s",
            stage,
            exc.__class__.__name__,
            self.describe_error(exc),
            exc_info=True,
        )

    async def _prepare_song_cache_without_aliases(self) -> None:
        songs = getattr(self.client, "songs", None)
        if not songs:
            return
        try:
            await songs(alias_provider=None)
        except TypeError:
            # Older maimai.py versions may not expose alias_provider. Let the
            # later score fetch use the library's default path in that case.
            return

    async def _arcade_identifier_from_sgid(self, sgid: str) -> tuple[Any, str]:
        identifier = await self.client.qrcode(sgid, http_proxy=self.http_proxy)
        arcade_credentials = getattr(identifier, "credentials", None)
        if not isinstance(arcade_credentials, str) or not arcade_credentials:
            raise RuntimeError("二维码返回的凭据格式异常。")
        return self._identifier(credentials=arcade_credentials), arcade_credentials

    @staticmethod
    def _count_score_marks(scores: list[Any]) -> int:
        return sum(
            1
            for score in scores
            if getattr(score, "fc", None) is not None or getattr(score, "fs", None) is not None
        )

    async def bind_from_sgid(self, sgid: str) -> BindResult:
        await self._arcade_identifier_from_sgid(sgid)
        return BindResult()

    def _official_configured(self) -> bool:
        return self._score_source_wants_official()

    def _score_source_mode(self) -> str:
        if self.score_source_mode in SCORE_SOURCE_MODES:
            return self.score_source_mode
        if self.official_protocol_enabled:
            return SCORE_SOURCE_OFFICIAL_ONLY
        return SCORE_SOURCE_OFFICIAL_ONLY

    def _score_source_wants_official(self) -> bool:
        return self._score_source_mode() in {
            SCORE_SOURCE_OFFICIAL_ONLY,
            SCORE_SOURCE_OFFICIAL_THEN_ARCADE,
        }

    @staticmethod
    def _enum_by_name(enum_cls: Any, name: str | None) -> Any:
        if not name:
            return None
        members = getattr(enum_cls, "__members__", {})
        return members.get(name)

    def _official_fc_type(self, combo_status: int) -> Any:
        return self._enum_by_name(self._load_imports()["FCType"], combo_status_to_fc_name(combo_status))

    def _official_fs_type(self, sync_status: int) -> Any:
        return self._enum_by_name(self._load_imports()["FSType"], sync_status_to_fs_name(sync_status))

    @staticmethod
    def _detail_first_value(detail: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in detail:
                return detail.get(key)
        return None

    @staticmethod
    def _status_value(value: Any, names: dict[str, int]) -> int:
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            pass

        normalized = str(value).strip().lower()
        return names.get(normalized, 0)

    def _official_combo_status_from_detail(self, detail: dict[str, Any]) -> int:
        value = self._detail_first_value(
            detail,
            "comboStatus",
            "combo_status",
            "combo",
            "fullCombo",
            "full_combo",
            "fc",
        )
        return self._status_value(
            value,
            {
                "silver": 1,
                "fc": 1,
                "fullcombo": 1,
                "full_combo": 1,
                "gold": 2,
                "fcp": 2,
                "fc+": 2,
                "fullcomboplus": 2,
                "allperfect": 3,
                "ap": 3,
                "allperfectplus": 4,
                "app": 4,
                "ap+": 4,
                "none": 0,
                "": 0,
            },
        )

    def _official_sync_status_from_detail(self, detail: dict[str, Any]) -> int:
        value = self._detail_first_value(
            detail,
            "syncStatus",
            "sync_status",
            "sync",
            "fullSync",
            "full_sync",
            "fs",
        )
        return self._status_value(
            value,
            {
                "chainlow": 1,
                "fs": 1,
                "fullsync": 1,
                "chainhi": 2,
                "fsp": 2,
                "fs+": 2,
                "fullsyncplus": 2,
                "synclow": 3,
                "fsd": 3,
                "syncdx": 3,
                "synchi": 4,
                "fsdp": 4,
                "fsd+": 4,
                "syncdxplus": 4,
                "syncplay": 5,
                "sync": 5,
                "none": 0,
                "": 0,
            },
        )

    @staticmethod
    def _details_have_mark_fields(details: list[dict[str, Any]]) -> bool:
        mark_keys = {
            "comboStatus",
            "combo_status",
            "combo",
            "fullCombo",
            "full_combo",
            "fc",
            "syncStatus",
            "sync_status",
            "sync",
            "fullSync",
            "full_sync",
            "fs",
        }
        return any(any(key in detail for key in mark_keys) for detail in details)

    def _official_level_index(self, music_id: int, level: int) -> Any:
        imports = self._load_imports()
        LevelIndex = imports["LevelIndex"]
        try:
            return LevelIndex(int(level or 0))
        except (TypeError, ValueError):
            return getattr(LevelIndex, "BASIC", LevelIndex(0))

    async def _song_level_text(self, songs: Any, music_id: int, song_type: Any, level_index: Any) -> str:
        try:
            song = await songs.by_id(music_id % 10000)
            if not song:
                return ""
            difficulty = song.get_difficulty(song_type, level_index)
            return str(getattr(difficulty, "level", "") or "")
        except Exception:
            return ""

    async def _official_details_to_scores(self, details: list[dict[str, Any]]) -> list[Any]:
        imports = self._load_imports()
        Score = imports["Score"]
        RateType = imports["RateType"]
        SongType = imports["SongType"]
        try:
            songs = await self.client.songs(alias_provider=None)
        except TypeError:
            songs = await self.client.songs()

        scores: list[Any] = []
        for detail in details:
            music_id = int(detail.get("musicId") or 0)
            if music_id <= 0:
                continue
            song_type = SongType._from_id(music_id)
            level_index = self._official_level_index(music_id, int(detail.get("level") or 0))
            achievement = float(detail.get("achievement") or 0) / 10000
            score_id = music_id if song_type == SongType.UTAGE else music_id % 10000
            scores.append(
                Score(
                    id=score_id,
                    level=await self._song_level_text(songs, music_id, song_type, level_index),
                    level_index=level_index,
                    achievements=achievement,
                    fc=self._official_fc_type(self._official_combo_status_from_detail(detail)),
                    fs=self._official_fs_type(self._official_sync_status_from_detail(detail)),
                    dx_score=int(
                        detail.get("deluxscoreMax")
                        or detail.get("deluxeScoreMax")
                        or detail.get("deluxScoreMax")
                        or detail.get("dxScore")
                        or detail.get("dx_score")
                        or 0
                    ),
                    dx_rating=None,
                    play_count=int(detail.get("playCount") or 0),
                    play_time=None,
                    rate=RateType._from_achievement(achievement),
                    type=song_type,
                )
            )
        return scores

    @staticmethod
    def _decode_user_id(value: Any) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, bytes):
            value = value.decode("ascii", errors="ignore")
        text = str(value or "").strip()
        if text.isdigit():
            return int(text)
        return 0

    @staticmethod
    def _extract_official_rating(value: Any) -> int:
        if not isinstance(value, dict):
            return 0
        for key in ("rating", "playerRating", "musicRating", "totalRating"):
            try:
                rating = int(value.get(key) or 0)
            except (TypeError, ValueError):
                rating = 0
            if rating > 0:
                return rating
        for nested_key in ("userData", "userRating"):
            nested = value.get(nested_key)
            if isinstance(nested, dict):
                rating = MaimaiService._extract_official_rating(nested)
                if rating > 0:
                    return rating
        return 0

    async def _official_user_id_from_sgid(self, sgid: str) -> int:
        try:
            from maimai_ffi import arcade as ffi_arcade  # type: ignore
        except ImportError as exc:
            raise MaimaiDependencyError("missing maimai-ffi arcade module") from exc

        request_module = getattr(ffi_arcade, "request", None)
        original_paginated = getattr(request_module, "request_paginated", None)
        if request_module is None or original_paginated is None:
            raise OfficialProtocolUnavailableError("maimai-ffi arcade request hook is unavailable")

        captured_user_ids: list[int] = []

        async def capture_request_paginated(path: str, data: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            for candidate in (data.get("userId"), data.get("rivalId"), args[1] if len(args) > 1 else None):
                user_id = self._decode_user_id(candidate)
                if user_id > 0:
                    captured_user_ids.append(user_id)
                    break
            return {"userRivalMusicList": []}

        encrypted = await ffi_arcade.get_uid_encrypted(str(sgid), http_proxy=self.http_proxy)
        async with self._ffi_request_lock:
            setattr(request_module, "request_paginated", capture_request_paginated)
            try:
                await ffi_arcade.get_user_scores(encrypted, http_proxy=self.http_proxy)
            finally:
                setattr(request_module, "request_paginated", original_paginated)

        if captured_user_ids:
            return captured_user_ids[0]
        raise OfficialProtocolUnavailableError("official SGID resolver did not expose user_id")

    async def _official_arcade_details_from_sgid(self, sgid: str) -> list[dict[str, Any]]:
        try:
            from maimai_ffi import arcade as ffi_arcade  # type: ignore
        except ImportError as exc:
            raise MaimaiDependencyError("missing maimai-ffi arcade module") from exc

        encrypted = await ffi_arcade.get_uid_encrypted(str(sgid), http_proxy=self.http_proxy)
        raw_scores = await ffi_arcade.get_user_scores(encrypted, http_proxy=self.http_proxy)
        details = [dict(score) for score in raw_scores if isinstance(score, dict)]
        if not details:
            raise OfficialTitleServerError("official score source returned no scores")
        if not self._details_have_mark_fields(details):
            raise OfficialTitleServerError("official score source did not include full mark fields")
        return details

    async def _rating_from_score_list(self, scores: list[Any]) -> int:
        try:
            maimai_scores = self._load_imports()["MaimaiScores"](self.client)
            configured = await maimai_scores.configure(scores)
            return int(getattr(configured, "rating", 0) or 0)
        except Exception as exc:
            logger.warning(
                "[MaimaiUpdater] local rating calculation failed: %s: %s",
                exc.__class__.__name__,
                exc,
                exc_info=True,
            )
            return 0

    async def _fetch_official_details_and_rating(self, session: ChimeSession) -> tuple[list[dict[str, Any]], int, str]:
        if not DEFAULT_OFFICIAL_TITLE_ENDPOINTS:
            raise OfficialProtocolUnavailableError("official title endpoint has not been resolved")

        last_error: BaseException | None = None
        for endpoint_index, endpoint in enumerate(DEFAULT_OFFICIAL_TITLE_ENDPOINTS, start=1):
            settings_client = OfficialTitleClient(
                base_url=endpoint.base_url,
                client_id=self.official_client_id
                or _short_keychip_id(self.official_keychip_id or DEFAULT_OFFICIAL_KEYCHIP_ID),
                timeout=self.timeout,
                http_proxy=self.http_proxy,
                host_header=endpoint.host_header,
                verify_tls=endpoint.verify_tls,
            )
            client: OfficialTitleClient | None = None
            login_date_time = 0
            try:
                runtime_base_url = await settings_client.resolve_runtime_base_url(
                    place_id=self.official_place_id,
                )
                client = (
                    settings_client
                    if runtime_base_url == settings_client.base_url
                    else settings_client.with_base_url(runtime_base_url)
                )
                preview_data: dict[str, Any] = {}
                try:
                    preview_data = await client.get_user_preview(session)
                    preview_error_id = int(preview_data.get("errorId") or 0)
                    if preview_error_id != 0:
                        raise OfficialTitleServerError(
                            f"official one-time session preview rejected: error_id={preview_error_id}"
                        )
                except Exception as exc:
                    if isinstance(exc, OfficialTitleServerError):
                        raise
                    logger.warning(
                        "[MaimaiUpdater] official preview fetch failed via endpoint #%s: %s: %s",
                        endpoint_index,
                        exc.__class__.__name__,
                        exc,
                        exc_info=True,
                    )

                try:
                    login_data = await client.user_login(
                        session,
                        region_id=self.official_region_id,
                        place_id=self.official_place_id,
                    )
                    login_return_code = int(login_data.get("returnCode") or 0)
                    if login_return_code not in ACCEPTED_OFFICIAL_LOGIN_RETURN_CODES:
                        raise OfficialTitleServerError(
                            f"official one-time session login rejected: return_code={login_return_code}"
                        )
                    login_date_time = int(login_data.get("_loginDateTime") or login_data.get("loginDateTime") or 0)
                except Exception as exc:
                    if isinstance(exc, OfficialTitleServerError):
                        raise
                    logger.warning(
                        "[MaimaiUpdater] official login request failed via endpoint #%s: %s: %s",
                        endpoint_index,
                        exc.__class__.__name__,
                        exc,
                        exc_info=True,
                    )

                try:
                    user_data = await client.get_user_data(session.user_id, token=session.token)
                except Exception as exc:
                    logger.warning(
                        "[MaimaiUpdater] official user data fetch failed via endpoint #%s: %s: %s",
                        endpoint_index,
                        exc.__class__.__name__,
                        exc,
                        exc_info=True,
                    )
                    user_data = {}
                details = await client.get_user_music(session.user_id, token=session.token)
                try:
                    rating_data = await client.get_user_rating(session.user_id, token=session.token)
                except Exception as exc:
                    logger.warning(
                        "[MaimaiUpdater] official rating fetch failed via endpoint #%s: %s: %s",
                        endpoint_index,
                        exc.__class__.__name__,
                        exc,
                        exc_info=True,
                    )
                    rating_data = {}
                logger.info(
                    "[MaimaiUpdater] official title fetch succeeded via endpoint #%s",
                    endpoint_index,
                )
                rating = (
                    self._extract_official_rating(user_data)
                    or self._extract_official_rating(rating_data)
                    or self._extract_official_rating(preview_data)
                )
                return details, rating, runtime_base_url
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "[MaimaiUpdater] official title fetch failed via endpoint #%s: %s: %s",
                    endpoint_index,
                    exc.__class__.__name__,
                    exc,
                    exc_info=True,
                )
            finally:
                if client is not None and login_date_time:
                    try:
                        await client.user_logout(
                            session.user_id,
                            login_date_time=login_date_time,
                            logout_type=5,
                            region_id=self.official_region_id,
                            place_id=self.official_place_id,
                        )
                    except Exception:
                        pass
                if client is not None and client is not settings_client:
                    await client.close()
                await settings_client.close()
        raise OfficialTitleServerError("all built-in official title server endpoints failed") from last_error

    async def _fetch_official_interface_details_and_rating(self, sgid: str) -> tuple[list[dict[str, Any]], int, str]:
        client = self._official_interface_client()
        if client is None:
            raise OfficialProtocolUnavailableError("official interface package is unavailable")

        result = await client.fetch_from_sgid(sgid)
        details = [
            dict(detail)
            for detail in getattr(result, "music_details", []) or []
            if isinstance(detail, dict)
        ]
        if not details:
            raise OfficialTitleServerError("official score source returned no scores")
        if not self._details_have_mark_fields(details):
            raise OfficialTitleServerError("official score source did not include full mark fields")

        rating = int(getattr(result, "rating", 0) or 0)
        endpoint = str(getattr(result, "endpoint", "") or "")
        logger.info(
            "[MaimaiUpdater] official interface fetch succeeded: scores=%s marked=%s",
            len(details),
            sum(1 for detail in details if self._official_combo_status_from_detail(detail) or self._official_sync_status_from_detail(detail)),
        )
        return details, rating, endpoint

    async def _sync_official_sgid_to_divingfish(self, sgid: str, import_token: str) -> SyncResult:
        if self._load_official_interface_client_cls() is not None:
            details, rating, _endpoint = await self._fetch_official_interface_details_and_rating(sgid)
        else:
            if not DEFAULT_OFFICIAL_TITLE_ENDPOINTS:
                raise OfficialProtocolUnavailableError("official title endpoint has not been resolved")

            session = await self._official_session_from_sgid(sgid)
            details, rating, _endpoint = await self._fetch_official_details_and_rating(session)
        if not self._details_have_mark_fields(details):
            raise OfficialTitleServerError("official title score response did not include full mark fields")
        scores = await self._official_details_to_scores(details)
        if not rating:
            rating = await self._rating_from_score_list(scores)
        await self.client.updates(
            self._identifier(credentials=import_token),
            scores,
            provider=self._divingfish_provider(),
        )
        return SyncResult(
            player_name="",
            rating=rating,
            score_count=len(scores),
            player_warning="",
            marked_score_count=self._count_score_marks(scores),
            source="official",
        )

    async def _sync_arcade_identifier_to_divingfish(
        self,
        arcade_identifier: Any,
        import_token: str,
    ) -> SyncResult:
        arcade_provider = self._arcade_provider()
        await self._prepare_song_cache_without_aliases()
        scores = await self.client.scores(arcade_identifier, provider=arcade_provider)
        score_list = list(getattr(scores, "scores", []) or [])
        score_rating = int(getattr(scores, "rating", 0) or 0)
        await self.client.updates(
            self._identifier(credentials=import_token),
            score_list,
            provider=self._divingfish_provider(),
        )

        return SyncResult(
            player_name="",
            rating=score_rating,
            score_count=len(score_list),
            player_warning="当前 SGID 机台源只能提供基础成绩，暂时无法提供 FULL COMBO/FULL SYNC/AP 标识。",
            marked_score_count=self._count_score_marks(score_list),
            source="arcade",
        )

    async def sync_from_sgid_to_divingfish(
        self,
        *,
        sgid: str,
        import_token: str,
    ) -> SyncResult:
        source_mode = self._score_source_mode()
        if source_mode == SCORE_SOURCE_OFFICIAL_ONLY:
            return await self._sync_official_sgid_to_divingfish(sgid, import_token)

        if source_mode == SCORE_SOURCE_OFFICIAL_THEN_ARCADE and self._official_configured():
            return await self._sync_official_sgid_to_divingfish(sgid, import_token)

        arcade_identifier, _ = await self._arcade_identifier_from_sgid(sgid)
        return await self._sync_arcade_identifier_to_divingfish(
            arcade_identifier,
            import_token,
        )

    async def clear_divingfish_scores(self, *, import_token: str) -> None:
        await self.client.updates(
            self._identifier(credentials=import_token),
            [],
            provider=self._divingfish_provider(),
        )

    async def close(self) -> None:
        if self._client is None:
            return
        http_client = getattr(self._client, "_client", None)
        close = getattr(http_client, "aclose", None)
        if close:
            await close()
        self._client = None

    def describe_error(self, exc: BaseException) -> str:
        if isinstance(exc, MaimaiDependencyError):
            root = exc.__cause__
            if isinstance(root, SyntaxError):
                file_name = root.filename or "未知文件"
                return f"{exc} 原始错误：SyntaxError: {root.msg} ({file_name}, line {root.lineno})"
            return str(exc)

        class_name = exc.__class__.__name__
        if class_name in {"OfficialProtocolUnavailableError", "OfficialTitleServerError"}:
            return "官方完整成绩链路暂不可用，请稍后再试；若持续失败请联系插件维护者更新运行环境。"
        if class_name == "ChimeSessionError":
            return "官方完整成绩链路暂不可用，请重新获取二维码后再试；若持续失败请联系插件维护者。"
        if class_name == "OfficialProtocolError":
            return "官方完整成绩链路失败，请稍后再试；若持续失败请联系插件维护者。"

        if isinstance(exc, OfficialProtocolUnavailableError):
            return "官方完整成绩链路暂不可用，请稍后再试；若持续失败请联系插件维护者更新运行环境。"

        if isinstance(exc, OfficialTitleServerError):
            return "官方完整成绩链路暂不可用，请稍后再试；若持续失败请联系插件维护者更新运行环境。"

        if isinstance(exc, ChimeSessionError):
            return "官方完整成绩链路暂不可用，请重新获取二维码后再试；若持续失败请联系插件维护者。"

        if isinstance(exc, OfficialProtocolError):
            return "官方完整成绩链路失败，请稍后再试；若持续失败请联系插件维护者。"

        ffi_messages = {
            "TitleServerBlockedError": "舞萌标题服务器拒绝了当前请求，可能是当前网络环境暂时受限，请稍后再试或更换网络。",
            "TitleServerNetworkError": "舞萌标题服务器网络请求失败，请稍后再试。",
            "TitleServerError": "舞萌标题服务器请求失败，可能是网络波动或当前网络环境暂时受限，请稍后再试。",
            "AimeServerError": "二维码无效或已过期，请重新从官方公众号获取二维码后再试。",
            "ArcadeIdentifierError": "官方二维码凭据无效或已过期，请重新从官方公众号获取二维码后再试。",
        }
        if class_name in ffi_messages:
            return ffi_messages[class_name]

        imports = self._imports or {}
        checks = (
            ("AimeServerError", "二维码无效或已过期，请重新从官方公众号获取二维码后再试。"),
            ("TitleServerBlockedError", "舞萌标题服务器拒绝了当前请求，可能是当前网络环境暂时受限，请稍后再试或更换网络。"),
            ("TitleServerNetworkError", "舞萌标题服务器网络请求失败，请稍后再试。"),
            ("TitleServerError", "舞萌标题服务器请求失败，可能是网络波动或当前网络环境暂时受限，请稍后再试。"),
            ("ArcadeIdentifierError", "官方二维码凭据无效或已过期，请重新从官方公众号获取二维码后再试。"),
            ("ArcadeError", "机台数据源返回异常，可能是二维码过期、官方服务波动或账号状态异常。"),
            ("InvalidPlayerIdentifierError", "水鱼 Import-Token 无效，或水鱼账号不允许导入，请重新绑定 Token。"),
            ("InvalidDeveloperTokenError", "水鱼接口拒绝了请求，请检查 Token 或稍后再试。"),
            ("PrivacyLimitationError", "水鱼账号未允许第三方访问，请先在水鱼查分器中开启相关权限。"),
            ("HTTPError", "网络请求失败，请检查 AstrBot 所在机器的网络或代理设置。"),
        )
        for class_name, message in checks:
            cls = imports.get(class_name)
            if cls and isinstance(exc, cls):
                return message
        return f"操作失败：{exc.__class__.__name__}: {exc}"

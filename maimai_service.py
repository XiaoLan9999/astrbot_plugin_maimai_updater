from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Any

from .official_protocol import (
    ChimeSessionResolver,
    OfficialProtocolError,
    OfficialProtocolUnavailableError,
    OfficialTitleClient,
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
        official_protocol_enabled: bool = False,
        official_chimelib_dll_path: str = "",
        official_title_base_url: str = "",
        official_client_id: str = "",
        official_region_id: int = 8,
        official_place_id: int = 0,
        official_server_url_index: int = 0,
        official_keychip_id: str = "",
        official_game_id: str = "MAID",
    ):
        self.timeout = float(timeout or 30.0)
        self.http_proxy = (http_proxy or "").strip() or None
        self._client: Any | None = None
        self._imports: dict[str, Any] | None = None
        self.official_protocol_enabled = bool(official_protocol_enabled)
        self.official_chimelib_dll_path = (official_chimelib_dll_path or "").strip()
        self.official_title_base_url = (official_title_base_url or "").strip()
        self.official_client_id = (official_client_id or "").strip()
        self.official_region_id = int(official_region_id or 8)
        self.official_place_id = int(official_place_id or 0)
        self.official_server_url_index = int(official_server_url_index or 0)
        self.official_keychip_id = (official_keychip_id or "").strip()
        self.official_game_id = (official_game_id or "MAID").strip() or "MAID"

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
        return (
            self.official_protocol_enabled
            and bool(self.official_chimelib_dll_path)
            and bool(self.official_title_base_url)
        )

    def _official_resolver(self) -> ChimeSessionResolver:
        if not self._official_configured():
            raise OfficialProtocolUnavailableError("official protocol is not configured")
        return ChimeSessionResolver(
            dll_path=self.official_chimelib_dll_path,
            game_id=self.official_game_id,
            chip_id=self.official_keychip_id,
            server_url_index=self.official_server_url_index,
            timeout=self.timeout,
        )

    def _official_title_client(self) -> OfficialTitleClient:
        if not self._official_configured():
            raise OfficialProtocolUnavailableError("official protocol is not configured")
        return OfficialTitleClient(
            base_url=self.official_title_base_url,
            client_id=self.official_client_id or self.official_keychip_id,
            timeout=self.timeout,
            http_proxy=self.http_proxy,
        )

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

    def _official_level_index(self, music_id: int, level: int) -> Any:
        imports = self._load_imports()
        song_type = imports["SongType"]._from_id(music_id)
        if song_type == imports["SongType"].UTAGE:
            return music_id
        return imports["LevelIndex"](int(level or 0))

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
                    fc=self._official_fc_type(int(detail.get("comboStatus") or 0)),
                    fs=self._official_fs_type(int(detail.get("syncStatus") or 0)),
                    dx_score=int(detail.get("deluxscoreMax") or 0),
                    dx_rating=None,
                    play_count=int(detail.get("playCount") or 0),
                    play_time=None,
                    rate=RateType._from_achievement(achievement),
                    type=song_type,
                )
            )
        return scores

    async def _sync_official_sgid_to_divingfish(self, sgid: str, import_token: str) -> SyncResult:
        resolver = self._official_resolver()
        session = await resolver.resolve_async(sgid)
        title_client = self._official_title_client()
        try:
            preview: dict[str, Any] = {}
            try:
                preview = await title_client.get_user_preview(session)
            except Exception as exc:
                logger.warning(
                    "[MaimaiUpdater] official preview fetch failed: %s: %s",
                    exc.__class__.__name__,
                    exc,
                    exc_info=True,
                )

            try:
                await title_client.user_login(
                    session,
                    region_id=self.official_region_id,
                    place_id=self.official_place_id,
                )
            except Exception as exc:
                logger.warning(
                    "[MaimaiUpdater] official login failed, continuing score fetch: %s: %s",
                    exc.__class__.__name__,
                    exc,
                    exc_info=True,
                )

            details = await title_client.get_user_music(session.user_id)
            try:
                rating_data = await title_client.get_user_rating(session.user_id)
            except Exception as exc:
                logger.warning(
                    "[MaimaiUpdater] official rating fetch failed: %s: %s",
                    exc.__class__.__name__,
                    exc,
                    exc_info=True,
                )
                rating_data = {}
            scores = await self._official_details_to_scores(details)
            rating = int(rating_data.get("rating") or preview.get("playerRating") or 0)
            await self.client.updates(
                self._identifier(credentials=import_token),
                scores,
                provider=self._divingfish_provider(),
            )
            return SyncResult(
                player_name=str(preview.get("userName") or ""),
                rating=rating,
                score_count=len(scores),
                player_warning="",
                marked_score_count=self._count_score_marks(scores),
                source="official",
            )
        finally:
            await title_client.close()

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
        if self._official_configured():
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

        if isinstance(exc, OfficialProtocolUnavailableError):
            return "官方完整成绩链路未配置完整：请在插件配置里填写 chimelib_dll.dll 路径和标题服务器 base URL，或关闭官方链路。"

        if isinstance(exc, OfficialProtocolError):
            return f"官方完整成绩链路失败：{exc}"

        imports = self._imports or {}
        checks = (
            ("AimeServerError", "二维码无效或已过期，请重新从官方公众号获取二维码后再试。"),
            ("TitleServerBlockedError", "舞萌标题服务器拒绝了当前请求，可能是当前 IP 暂时被限制，请稍后再试或更换网络。"),
            ("TitleServerNetworkError", "舞萌标题服务器网络请求失败，请稍后再试。"),
            ("TitleServerError", "舞萌标题服务器请求失败，可能是网络波动或当前 IP 暂时被限制，请稍后再试。"),
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

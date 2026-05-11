from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Any

try:
    from astrbot.api import logger
except ModuleNotFoundError:  # pragma: no cover - local tests without AstrBot installed.
    import logging

    logger = logging.getLogger(__name__)


class MaimaiDependencyError(RuntimeError):
    pass


MIN_MAIMAI_PY = (1, 4, 2)
MIN_MAIMAI_FFI = (0, 7, 0)


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


@dataclass(slots=True)
class BindResult:
    player_warning: str = ""


@dataclass(slots=True)
class SyncResult:
    player_name: str
    rating: int
    score_count: int
    player_warning: str = ""


class MaimaiService:
    def __init__(self, *, timeout: float = 30.0, http_proxy: str = ""):
        self.timeout = float(timeout or 30.0)
        self.http_proxy = (http_proxy or "").strip() or None
        self._client: Any | None = None
        self._imports: dict[str, Any] | None = None

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

        try:
            arcade_provider_probe = ArcadeProvider(http_proxy=self.http_proxy)
        except TypeError:
            arcade_provider_probe = ArcadeProvider()
        if hasattr(arcade_provider_probe, "get_player"):
            raise MaimaiDependencyError(
                "当前 AstrBot 进程仍在使用旧版 maimai-py ArcadeProvider。"
                "请完全关闭 AstrBot 后重新安装 requirements.txt，并重启 AstrBot。"
            )

        self._imports = {
            "ArcadeProvider": ArcadeProvider,
            "DivingFishProvider": DivingFishProvider,
            "MaimaiClient": MaimaiClient,
            "PlayerIdentifier": PlayerIdentifier,
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

    def _log_nonfatal_arcade_player_error(self, exc: BaseException, *, stage: str) -> None:
        logger.warning(
            "[MaimaiUpdater] arcade player metadata fetch failed during %s: %s: %s",
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

    async def bind_from_sgid(self, sgid: str) -> BindResult:
        await self._arcade_identifier_from_sgid(sgid)
        return BindResult()

    async def _sync_arcade_identifier_to_divingfish(
        self,
        arcade_identifier: Any,
        import_token: str,
    ) -> SyncResult:
        arcade_provider = self._arcade_provider()
        player_name = ""
        player_rating = 0
        player_warning = ""
        if hasattr(arcade_provider, "get_player"):
            try:
                player = await self.client.players(arcade_identifier, provider=arcade_provider)
                player_name = str(getattr(player, "name", "") or "")
                player_rating = int(getattr(player, "rating", 0) or 0)
            except Exception as exc:
                self._log_nonfatal_arcade_player_error(exc, stage="update")
                player_warning = "当前数据源不提供官方玩家名预览。"
        else:
            player_warning = "当前数据源不提供官方玩家名预览。"

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
            player_name=player_name,
            rating=player_rating or score_rating,
            score_count=len(score_list),
            player_warning=player_warning,
        )

    async def sync_from_sgid_to_divingfish(
        self,
        *,
        sgid: str,
        import_token: str,
    ) -> SyncResult:
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

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class MaimaiDependencyError(RuntimeError):
    pass


@dataclass(slots=True)
class BindResult:
    arcade_credentials: str
    player_name: str
    rating: int
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

    def _load_imports(self) -> dict[str, Any]:
        if self._imports is not None:
            return self._imports
        try:
            from maimai_py import (  # type: ignore
                ArcadeProvider,
                DivingFishProvider,
                MaimaiClient,
                PlayerIdentifier,
            )
            from maimai_py.exceptions import (  # type: ignore
                AimeServerError,
                ArcadeError,
                InvalidDeveloperTokenError,
                InvalidPlayerIdentifierError,
                MaimaiPyError,
                PrivacyLimitationError,
                TitleServerError,
            )
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

        self._imports = {
            "ArcadeProvider": ArcadeProvider,
            "DivingFishProvider": DivingFishProvider,
            "MaimaiClient": MaimaiClient,
            "PlayerIdentifier": PlayerIdentifier,
            "AimeServerError": AimeServerError,
            "ArcadeError": ArcadeError,
            "InvalidDeveloperTokenError": InvalidDeveloperTokenError,
            "InvalidPlayerIdentifierError": InvalidPlayerIdentifierError,
            "MaimaiPyError": MaimaiPyError,
            "PrivacyLimitationError": PrivacyLimitationError,
            "TitleServerError": TitleServerError,
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

    async def bind_from_sgid(self, sgid: str) -> BindResult:
        identifier = await self.client.qrcode(sgid, http_proxy=self.http_proxy)
        arcade_credentials = getattr(identifier, "credentials", None)
        if not isinstance(arcade_credentials, str) or not arcade_credentials:
            raise RuntimeError("二维码返回的凭据格式异常。")

        player_name = ""
        rating = 0
        player_warning = ""
        try:
            player = await self.client.players(
                self._identifier(credentials=arcade_credentials),
                provider=self._arcade_provider(),
            )
            player_name = str(getattr(player, "name", "") or "")
            rating = int(getattr(player, "rating", 0) or 0)
        except Exception as exc:
            player_warning = f"二维码已解析，但玩家名/Rating 暂时获取失败：{self.describe_error(exc)}"

        return BindResult(
            arcade_credentials=arcade_credentials,
            player_name=player_name,
            rating=rating,
            player_warning=player_warning,
        )

    async def sync_to_divingfish(
        self,
        *,
        arcade_credentials: str,
        import_token: str,
    ) -> SyncResult:
        arcade_identifier = self._identifier(credentials=arcade_credentials)
        arcade_provider = self._arcade_provider()
        scores = await self.client.scores(arcade_identifier, provider=arcade_provider)
        score_list = list(getattr(scores, "scores", []) or [])
        await self.client.updates(
            self._identifier(credentials=import_token),
            score_list,
            provider=self._divingfish_provider(),
        )

        player_name = ""
        rating = 0
        player_warning = ""
        try:
            player = await self.client.players(arcade_identifier, provider=arcade_provider)
            player_name = str(getattr(player, "name", "") or "")
            rating = int(getattr(player, "rating", 0) or 0)
        except Exception as exc:
            player_warning = f"成绩已同步，但玩家名/Rating 暂时获取失败：{self.describe_error(exc)}"

        return SyncResult(
            player_name=player_name,
            rating=rating,
            score_count=len(score_list),
            player_warning=player_warning,
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
            ("TitleServerError", "舞萌标题服务器请求失败，可能是网络波动或当前 IP 暂时被限制，请稍后再试。"),
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

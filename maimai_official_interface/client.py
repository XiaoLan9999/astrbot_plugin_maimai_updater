from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .protocol import (
    ChimeSession,
    ChimeSessionResolver,
    DEFAULT_OFFICIAL_TITLE_ENDPOINTS,
    OfficialProtocolUnavailableError,
    OfficialTitleClient,
    OfficialTitleServerError,
)


DEFAULT_KEYCHIP_ID = "A63E-01E11890000"
DEFAULT_REGION_ID = 8
DEFAULT_PLACE_ID = 3496
DEFAULT_GAME_ID = "MAID"
DEFAULT_TITLE_KEY = "SDGB"
ACCEPTED_LOGIN_RETURN_CODES = {1, 100}


@dataclass(slots=True)
class OfficialFetchResult:
    session: ChimeSession
    endpoint: str
    preview: dict[str, Any]
    user_data: dict[str, Any]
    rating_data: dict[str, Any]
    music_details: list[dict[str, Any]]

    @property
    def rating(self) -> int:
        for source in (self.user_data, self.rating_data, self.preview):
            rating = _extract_rating(source)
            if rating:
                return rating
        return 0


class OfficialSessionHandle:
    def __init__(
        self,
        *,
        session: ChimeSession,
        client: OfficialTitleClient,
        endpoint: str,
        preview: dict[str, Any],
        login: dict[str, Any],
        region_id: int = DEFAULT_REGION_ID,
        place_id: int = DEFAULT_PLACE_ID,
    ) -> None:
        self.session = session
        self.client = client
        self.endpoint = endpoint
        self.preview = preview
        self.login = login
        self.region_id = int(region_id or DEFAULT_REGION_ID)
        self.place_id = int(place_id or DEFAULT_PLACE_ID)
        self._closed = False
        self._logged_out = False

    async def __aenter__(self) -> "OfficialSessionHandle":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.logout_best_effort()
        finally:
            await self.client.close()

    async def get_user_data(self) -> dict[str, Any]:
        return await self.client.get_user_data(self.session.user_id, token=self.session.token)

    async def get_music_details(self) -> list[dict[str, Any]]:
        return await self.client.get_user_music(self.session.user_id, token=self.session.token)

    async def get_rating(self) -> dict[str, Any]:
        return await self.client.get_user_rating(self.session.user_id, token=self.session.token)

    async def user_logout(self, *, login_date_time: int = 0, logout_type: int = 5) -> dict[str, Any]:
        return await self.client.post(
            "UserLogoutApi",
            self.session.user_id,
            {
                "userId": self.session.user_id,
                "accessCode": "",
                "regionId": self.region_id,
                "placeId": self.place_id,
                "clientId": self.client.client_id,
                "loginDateTime": int(login_date_time or 0),
                "type": int(logout_type or 5),
            },
        )

    async def logout_best_effort(self, *, logout_type: int = 5) -> None:
        if self._logged_out:
            return
        self._logged_out = True
        try:
            login_date_time = int(
                self.login.get("_loginDateTime")
                or self.login.get("loginDateTime")
                or 0
            )
        except (TypeError, ValueError):
            login_date_time = 0
        try:
            await self.user_logout(
                login_date_time=login_date_time,
                logout_type=logout_type,
            )
        except Exception:
            return


def _compact_keychip_id(keychip_id: str) -> str:
    return "".join(ch for ch in (keychip_id or "").strip() if ch.isalnum())


def _keychip_tail(keychip_id: str) -> str:
    value = (keychip_id or "").strip()
    if "-" in value:
        return _compact_keychip_id(value.rsplit("-", 1)[-1])
    return _compact_keychip_id(value)


def _extract_rating(value: Any) -> int:
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
        rating = _extract_rating(value.get(nested_key))
        if rating:
            return rating
    return 0


class MaimaiOfficialClient:
    def __init__(
        self,
        *,
        keychip_id: str = DEFAULT_KEYCHIP_ID,
        region_id: int = DEFAULT_REGION_ID,
        place_id: int = DEFAULT_PLACE_ID,
        game_id: str = DEFAULT_GAME_ID,
        qr_game_id: str = DEFAULT_GAME_ID,
        title_key: str = DEFAULT_TITLE_KEY,
        server_url_index: int = 0,
        chimelib_path: str | Path | None = None,
        timeout: float = 30.0,
        http_proxy: str | None = None,
    ) -> None:
        self.keychip_id = keychip_id or DEFAULT_KEYCHIP_ID
        self.region_id = int(region_id or DEFAULT_REGION_ID)
        self.place_id = int(place_id or DEFAULT_PLACE_ID)
        self.game_id = game_id or DEFAULT_GAME_ID
        self.qr_game_id = qr_game_id or DEFAULT_GAME_ID
        self.title_key = title_key or DEFAULT_TITLE_KEY
        self.server_url_index = int(server_url_index or 0)
        self.chimelib_path = Path(chimelib_path).expanduser() if chimelib_path else self._default_chimelib_path()
        self.timeout = float(timeout or 30.0)
        self.http_proxy = (http_proxy or "").strip() or None

    @staticmethod
    def _default_chimelib_path() -> Path:
        return Path(__file__).resolve().parent / "resources" / "core.dat"

    @property
    def client_id(self) -> str:
        return _keychip_tail(self.keychip_id)

    async def resolve_session_async(self, sgid: str) -> ChimeSession:
        if not self.chimelib_path.is_file():
            raise OfficialProtocolUnavailableError("official runtime asset is unavailable")
        resolver = ChimeSessionResolver(
            dll_path=str(self.chimelib_path),
            game_id=self.game_id,
            qr_game_id=self.qr_game_id,
            chip_id=_keychip_tail(self.keychip_id),
            title_key=self.title_key,
            server_url_index=self.server_url_index,
            timeout=self.timeout,
        )
        return await resolver.resolve_async(sgid)

    async def fetch_from_sgid(self, sgid: str) -> OfficialFetchResult:
        session = await self.resolve_session_async(sgid)
        return await self.fetch(session)

    async def fetch(self, session: ChimeSession) -> OfficialFetchResult:
        handle = await self.open(session)
        try:
            try:
                user_data = await handle.get_user_data()
            except Exception:
                user_data = {}

            music_details = await handle.get_music_details()

            try:
                rating_data = await handle.get_rating()
            except Exception:
                rating_data = {}

            return OfficialFetchResult(
                session=session,
                endpoint=handle.endpoint,
                preview=handle.preview,
                user_data=user_data,
                rating_data=rating_data,
                music_details=music_details,
            )
        finally:
            await handle.close()

    async def open(self, session: ChimeSession) -> OfficialSessionHandle:
        last_error: BaseException | None = None
        for endpoint in DEFAULT_OFFICIAL_TITLE_ENDPOINTS:
            settings_client = OfficialTitleClient(
                base_url=endpoint.base_url,
                client_id=self.client_id,
                timeout=self.timeout,
                http_proxy=self.http_proxy,
                host_header=endpoint.host_header,
                verify_tls=endpoint.verify_tls,
            )
            client: OfficialTitleClient | None = None
            returning_handle = False
            try:
                runtime_base_url = await settings_client.resolve_runtime_base_url(place_id=self.place_id)
                client = (
                    settings_client
                    if runtime_base_url == settings_client.base_url
                    else settings_client.with_base_url(runtime_base_url)
                )
                preview = await client.get_user_preview(session)
                preview_error_id = int(preview.get("errorId") or 0)
                if preview_error_id != 0:
                    raise OfficialTitleServerError(f"preview rejected: error_id={preview_error_id}")

                login = await client.user_login(session, region_id=self.region_id, place_id=self.place_id)
                login_return_code = int(login.get("returnCode") or 0)
                if login_return_code not in ACCEPTED_LOGIN_RETURN_CODES:
                    raise OfficialTitleServerError(f"login rejected: return_code={login_return_code}")

                handle = OfficialSessionHandle(
                    session=session,
                    client=client,
                    endpoint=runtime_base_url,
                    preview=preview,
                    login=login,
                    region_id=self.region_id,
                    place_id=self.place_id,
                )
                if client is not settings_client:
                    await settings_client.close()
                returning_handle = True
                return handle
            except Exception as exc:
                last_error = exc
                if client is not None and client is not settings_client:
                    await client.close()
            finally:
                if not returning_handle:
                    await settings_client.close()
        raise OfficialTitleServerError("all official endpoints failed") from last_error

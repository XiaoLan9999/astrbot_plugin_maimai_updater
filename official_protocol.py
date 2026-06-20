from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import os
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAI_ENCODING = "1.55"
API_PREFIX = "MaimaiChn"
OBFUSCATE_PARAM = "8bF76dE9"
AES_KEY = b"FKM2JX:VjZNK6hc:A0<JU:i5oR7LA]9W"
AES_IV = b"F>;24DjU9W6ZsRH["


class OfficialProtocolError(RuntimeError):
    pass


class OfficialProtocolUnavailableError(OfficialProtocolError):
    pass


class ChimeSessionError(OfficialProtocolError):
    pass


class OfficialTitleServerError(OfficialProtocolError):
    pass


@dataclass(slots=True)
class ChimeSession:
    user_id: int
    token: str


@dataclass(frozen=True, slots=True)
class OfficialTitleEndpoint:
    base_url: str
    host_header: str = ""
    verify_tls: bool = True


OFFICIAL_TITLE_HOSTS = (
    "wq.sys-all.cn",
    "ai.sys-all.cn",
    "wi.sys-all.cn",
    "at.sys-all.cn",
)
OFFICIAL_TITLE_IP = "43.137.89.146"
OFFICIAL_TITLE_PATH = "Maimai2Servlet/"
DEFAULT_OFFICIAL_TITLE_ENDPOINTS = (
    *(OfficialTitleEndpoint(f"https://{host}/{OFFICIAL_TITLE_PATH}") for host in OFFICIAL_TITLE_HOSTS),
    *(
        OfficialTitleEndpoint(
            f"https://{OFFICIAL_TITLE_IP}/{OFFICIAL_TITLE_PATH}",
            host_header=host,
            verify_tls=False,
        )
        for host in OFFICIAL_TITLE_HOSTS
    ),
    *(
        OfficialTitleEndpoint(
            f"http://{OFFICIAL_TITLE_IP}/{OFFICIAL_TITLE_PATH}",
            host_header=host,
            verify_tls=True,
        )
        for host in OFFICIAL_TITLE_HOSTS
    ),
)


@dataclass(slots=True)
class OfficialSyncPayload:
    user_id: int
    token: str
    player_name: str = ""
    rating: int = 0
    music_details: list[dict[str, Any]] | None = None
    charges: list[dict[str, Any]] | None = None


def is_official_sgid(sgid: str, game_id: str = "MAID") -> bool:
    value = (sgid or "").strip()
    return value.startswith("SGWC") and value[4:8] == game_id and len(value) > 20


def erase_sgid_hash_identifier(sgid: str, game_id: str = "MAID") -> str:
    value = (sgid or "").strip()
    if not is_official_sgid(value, game_id=game_id):
        raise ChimeSessionError("invalid SGID format for official chime API")
    return value[20:]


def official_api_name(api: str) -> str:
    return api if api.startswith(API_PREFIX) else f"{API_PREFIX}{api}"


def obfuscate_api(api: str) -> str:
    source = f"{official_api_name(api)}{OBFUSCATE_PARAM}".encode("utf-8")
    return hashlib.md5(source).hexdigest()


def _aes_cipher():
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:  # pragma: no cover - depends on deployed deps.
        raise OfficialProtocolUnavailableError(
            "cryptography is required for the official title protocol"
        ) from exc
    return Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV))


def _pkcs7_pad(data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives import padding
    except ImportError as exc:  # pragma: no cover - depends on deployed deps.
        raise OfficialProtocolUnavailableError(
            "cryptography is required for the official title protocol"
        ) from exc
    padder = padding.PKCS7(128).padder()
    return padder.update(data) + padder.finalize()


def _pkcs7_unpad(data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives import padding
    except ImportError as exc:  # pragma: no cover - depends on deployed deps.
        raise OfficialProtocolUnavailableError(
            "cryptography is required for the official title protocol"
        ) from exc
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(data) + unpadder.finalize()


def aes_encrypt(data: bytes) -> bytes:
    encryptor = _aes_cipher().encryptor()
    return encryptor.update(_pkcs7_pad(data)) + encryptor.finalize()


def aes_decrypt(data: bytes) -> bytes:
    decryptor = _aes_cipher().decryptor()
    return _pkcs7_unpad(decryptor.update(data) + decryptor.finalize())


def zlib_wrap_raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(level=zlib.Z_DEFAULT_COMPRESSION, wbits=-15)
    compressed = compressor.compress(data) + compressor.flush()
    checksum = zlib.adler32(data) & 0xFFFFFFFF
    return b"\x78\x9c" + compressed + checksum.to_bytes(4, "big")


def zlib_unwrap_raw_deflate(data: bytes) -> bytes:
    if len(data) < 6:
        return b""
    return zlib.decompress(data[2:-4], wbits=-15)


def encode_request_payload(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return aes_encrypt(zlib_wrap_raw_deflate(body))


def decode_response_payload(payload: bytes) -> dict[str, Any]:
    body = zlib_unwrap_raw_deflate(aes_decrypt(payload))
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def combo_status_to_fc_name(combo_status: int) -> str | None:
    return {
        1: "FC",
        2: "FCP",
        3: "AP",
        4: "APP",
    }.get(int(combo_status or 0))


def sync_status_to_fs_name(sync_status: int) -> str | None:
    # Official enum names:
    # SyncPlay -> normal SYNC, ChainLow/Hi -> FS/FSP, SyncLow/Hi -> FSD/FSDP.
    return {
        5: "SYNC",
        1: "FS",
        2: "FSP",
        3: "FSD",
        4: "FSDP",
    }.get(int(sync_status or 0))


class ChimeSessionResolver:
    def __init__(
        self,
        *,
        dll_path: str,
        game_id: str = "MAID",
        chip_id: str = "",
        common_key: str = "",
        title_key: str = "",
        server_url_index: int = 0,
        timeout: float = 20.0,
        poll_interval: float = 0.05,
    ) -> None:
        self.dll_path = Path(dll_path).expanduser()
        self.game_id = game_id or "MAID"
        self.chip_id = chip_id or ""
        self.common_key = common_key or ""
        self.title_key = title_key or ""
        self.server_url_index = int(server_url_index or 0)
        self.timeout = float(timeout or 20.0)
        self.poll_interval = float(poll_interval or 0.05)
        self._dll: Any | None = None
        self._dll_dir_handle: Any | None = None

    def _load(self) -> Any:
        if self._dll is not None:
            return self._dll
        if os.name != "nt":
            raise OfficialProtocolUnavailableError("chimelib_dll is only supported on Windows")
        if not self.dll_path.is_file():
            raise OfficialProtocolUnavailableError("chimelib_dll path does not exist")

        if hasattr(os, "add_dll_directory"):
            self._dll_dir_handle = os.add_dll_directory(str(self.dll_path.parent))

        dll = ctypes.CDLL(str(self.dll_path))
        dll.CCommGetUserData_Create.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint64,
        ]
        dll.CCommGetUserData_Create.restype = ctypes.c_void_p
        dll.CCommGetUserData_Destroy.argtypes = [ctypes.c_void_p]
        dll.CCommGetUserData_Destroy.restype = ctypes.c_bool
        dll.CCommGetUserData_execute.argtypes = [ctypes.c_void_p]
        dll.CCommGetUserData_execute.restype = None
        dll.CCommGetUserData_getErrorID.argtypes = [ctypes.c_void_p]
        dll.CCommGetUserData_getErrorID.restype = ctypes.c_int
        dll.CCommGetUserData_isEnd.argtypes = [ctypes.c_void_p]
        dll.CCommGetUserData_isEnd.restype = ctypes.c_bool
        dll.CCommGetUserData_getUserID.argtypes = [ctypes.c_void_p]
        dll.CCommGetUserData_getUserID.restype = ctypes.c_uint32
        dll.CCommGetUserData_getToken.argtypes = [ctypes.c_void_p]
        dll.CCommGetUserData_getToken.restype = ctypes.c_char_p
        self._dll = dll
        return dll

    def resolve(self, sgid: str) -> ChimeSession:
        dll = self._load()
        qr_data = erase_sgid_hash_identifier(sgid, game_id=self.game_id)
        handle = dll.CCommGetUserData_Create(
            self.game_id,
            self.chip_id,
            self.common_key,
            qr_data,
            self.title_key,
            self.server_url_index,
        )
        if not handle:
            raise ChimeSessionError("failed to create official chime session")

        try:
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                dll.CCommGetUserData_execute(handle)
                if dll.CCommGetUserData_isEnd(handle):
                    break
                time.sleep(self.poll_interval)
            else:
                raise ChimeSessionError("official chime session timed out")

            error_id = int(dll.CCommGetUserData_getErrorID(handle))
            if error_id != 0:
                raise ChimeSessionError(f"official chime session failed: error_id={error_id}")

            user_id = int(dll.CCommGetUserData_getUserID(handle))
            token_bytes = dll.CCommGetUserData_getToken(handle) or b""
            token = token_bytes.decode("ascii", errors="ignore")
            if not user_id or not token:
                raise ChimeSessionError("official chime session returned empty user_id or token")
            return ChimeSession(user_id=user_id, token=token)
        finally:
            dll.CCommGetUserData_Destroy(handle)

    async def resolve_async(self, sgid: str) -> ChimeSession:
        return await asyncio.to_thread(self.resolve, sgid)


class OfficialTitleClient:
    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        timeout: float = 30.0,
        http_proxy: str | None = None,
        host_header: str = "",
        verify_tls: bool = True,
    ) -> None:
        if not base_url:
            raise OfficialProtocolUnavailableError("official title base URL is not configured")
        self.base_url = base_url.rstrip("/") + "/"
        self.client_id = client_id or ""
        self.timeout = float(timeout or 30.0)
        self.http_proxy = (http_proxy or "").strip() or None
        self.host_header = (host_header or "").strip()
        self.verify_tls = bool(verify_tls)
        self._client: Any | None = None

    def _http_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - depends on deployed deps.
            raise OfficialProtocolUnavailableError("httpx is required for official title protocol") from exc

        kwargs: dict[str, Any] = {"timeout": self.timeout, "verify": self.verify_tls}
        if self.http_proxy:
            kwargs["proxy"] = self.http_proxy
        self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def post(self, api: str, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        api_name = official_api_name(api)
        url = self.base_url + obfuscate_api(api_name)
        headers = {
            "Content-Type": "application/json",
            "charset": "UTF-8",
            "Mai-Encoding": MAI_ENCODING,
            "Content-Encoding": "deflate",
            "User-Agent": f"{obfuscate_api(api_name)}#{user_id or self.client_id}",
        }
        if self.host_header:
            headers["Host"] = self.host_header
        response = await self._http_client().post(
            url,
            content=encode_request_payload(payload),
            headers=headers,
        )
        if response.status_code != 200:
            raise OfficialTitleServerError(
                f"official title API {api} failed: HTTP {response.status_code}"
            )
        try:
            return decode_response_payload(response.content)
        except Exception as exc:
            raise OfficialTitleServerError(f"official title API {api} returned invalid payload") from exc

    async def get_user_preview(self, session: ChimeSession) -> dict[str, Any]:
        return await self.post(
            "GetUserPreviewApi",
            session.user_id,
            {
                "userId": session.user_id,
                "segaIdAuthKey": "",
                "token": session.token,
                "clientId": self.client_id,
            },
        )

    async def user_login(
        self,
        session: ChimeSession,
        *,
        access_code: str = "",
        region_id: int = 8,
        place_id: int = 0,
        generic_flag: int = 0,
    ) -> dict[str, Any]:
        now = int(time.time())
        return await self.post(
            "UserLoginApi",
            session.user_id,
            {
                "userId": session.user_id,
                "accessCode": access_code or "",
                "regionId": int(region_id or 0),
                "placeId": int(place_id or 0),
                "clientId": self.client_id,
                "dateTime": now,
                "loginDateTime": now,
                "isContinue": False,
                "genericFlag": int(generic_flag or 0),
                "token": session.token,
            },
        )

    async def get_user_music(self, user_id: int, *, max_count: int = 50) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        next_index = 0
        while True:
            response = await self.post(
                "GetUserMusicApi",
                user_id,
                {
                    "userId": user_id,
                    "nextIndex": next_index,
                    "maxCount": int(max_count or 50),
                },
            )
            for music in response.get("userMusicList") or []:
                details.extend(music.get("userMusicDetailList") or [])
            next_index = int(response.get("nextIndex") or 0)
            if next_index == 0:
                return details

    async def get_user_rating(self, user_id: int) -> dict[str, Any]:
        response = await self.post("GetUserRatingApi", user_id, {"userId": user_id})
        return response.get("userRating") or {}

    async def get_user_charge(self, user_id: int) -> list[dict[str, Any]]:
        response = await self.post("GetUserChargeApi", user_id, {"userId": user_id})
        return list(response.get("userChargeList") or [])

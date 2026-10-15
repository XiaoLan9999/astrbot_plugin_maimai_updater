from __future__ import annotations

import math
import platform
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


DIVINGFISH_BASE = "https://www.diving-fish.com/api/maimaidxprober/"
FC_NAMES = {0: "", 1: "fc", 2: "fcp", 3: "ap", 4: "app"}
FS_NAMES = {0: "", 1: "fs", 2: "fsp", 3: "fsd", 4: "fsdp", 5: "sync"}
DX_SCORE_KEYS = ("deluxscoreMax", "deluxeScoreMax", "deluxScoreMax", "dxScore", "dx_score")


class PortableBackendError(RuntimeError):
    pass


def supports_local_runtime() -> bool:
    return sys.platform in {"win32", "linux"} and platform.machine().lower() in {"amd64", "x86_64"}


def validate_service_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise PortableBackendError("远程成绩服务地址格式不正确，请在插件面板中检查配置。")
    if parsed.query or parsed.fragment:
        raise PortableBackendError("远程成绩服务地址不能包含查询参数或片段。")
    return url.rstrip("/")


def validate_details(details: Any) -> list[dict[str, Any]]:
    if not isinstance(details, list) or not details or len(details) > 100_000:
        raise PortableBackendError("成绩服务未返回有效成绩，请稍后重试。")
    try:
        for item in details:
            if not isinstance(item, dict) or "comboStatus" not in item or "syncStatus" not in item:
                raise ValueError
            if int(item["musicId"]) <= 0 or not 0 <= int(item["level"]) <= 4:
                raise ValueError
            achievement = float(item["achievement"])
            if not math.isfinite(achievement) or not 0 <= achievement <= 1_010_000:
                raise ValueError
            if int(item["comboStatus"]) not in FC_NAMES or int(item["syncStatus"]) not in FS_NAMES:
                raise ValueError
            dx_score = next(item[k] for k in DX_SCORE_KEYS if item.get(k) is not None)
            if int(dx_score) < 0:
                raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError, StopIteration) as exc:
        raise PortableBackendError("成绩服务返回的数据不完整或缺少 FC/FS 字段，本次未写入水鱼。") from exc
    return details


@dataclass(slots=True)
class PortableImportResult:
    count: int
    marked: int
    skipped: int


class PortableScoreClient:
    def __init__(self, timeout: float = 30):
        self.timeout = timeout

    def _http_client(self):
        import httpx

        return httpx.AsyncClient(timeout=self.timeout, follow_redirects=False)

    async def fetch(self, base_url: str, access_token: str, sgid: str) -> tuple[list[dict[str, Any]], int]:
        import httpx

        url = validate_service_url(base_url)
        if not access_token:
            raise PortableBackendError("请在插件面板填写远程成绩服务访问密钥。")
        async with self._http_client() as client:
            response = await client.post(
                url + "/v1/scores", json={"sgid": sgid},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=httpx.Timeout(self.timeout, read=max(120, self.timeout)),
            )
        if response.status_code in {401, 403}:
            raise PortableBackendError("远程成绩服务鉴权失败，请检查插件面板中的访问密钥。")
        if response.status_code == 409:
            raise PortableBackendError("二维码无效、过期或账号暂不可用，请重新获取二维码后再试。")
        if response.status_code == 503:
            raise PortableBackendError("远程成绩服务繁忙或尚未就绪，请稍后重试。")
        if not response.is_success:
            raise PortableBackendError("远程成绩服务请求失败，请稍后重试。")
        try:
            data = response.json()
            if not isinstance(data, dict) or data.get("protocol") != 1:
                raise ValueError
            details = validate_details(data.get("music_details"))
            rating = int(data.get("rating") or 0)
            if rating < 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise PortableBackendError("远程成绩服务返回格式不正确，请联系管理员更新服务。") from exc
        return details, rating

    @staticmethod
    def serialize(details: list[dict[str, Any]], songs: list[dict[str, Any]]) -> tuple[list[dict], int]:
        validate_details(details)
        try:
            catalog = {int(song["id"]): song for song in songs}
        except (KeyError, TypeError, ValueError) as exc:
            raise PortableBackendError("水鱼曲库返回格式异常，请稍后重试。") from exc
        records = []
        skipped = 0
        for detail in details:
            song = catalog.get(int(detail["musicId"]))
            if not song:
                skipped += 1
                continue
            if "cids" in song and int(detail["level"]) >= len(song["cids"]):
                skipped += 1
                continue
            records.append({
                "title": song["title"],
                "type": song["type"],
                "level_index": int(detail["level"]),
                "achievements": float(detail["achievement"]) / 10000,
                "fc": FC_NAMES[int(detail["comboStatus"])],
                "fs": FS_NAMES[int(detail["syncStatus"])],
                "dxScore": int(next(detail[k] for k in DX_SCORE_KEYS if detail.get(k) is not None)),
            })
        if not records:
            raise PortableBackendError("水鱼曲库未匹配到可导入的成绩，本次未写入。")
        return records, skipped

    @staticmethod
    def _check_divingfish_response(response) -> None:
        if response.status_code in {400, 401}:
            raise PortableBackendError("水鱼 Import-Token 无效或导入数据被拒绝，请检查后重试。")
        if response.status_code == 403:
            raise PortableBackendError("水鱼拒绝了导入请求，请检查账号权限。")
        if not response.is_success:
            raise PortableBackendError("水鱼请求失败，请稍后重试。")
        try:
            body = response.json()
        except ValueError as exc:
            raise PortableBackendError("水鱼返回格式异常，无法确认操作结果。") from exc
        if isinstance(body, dict) and body.get("status") == "error":
            raise PortableBackendError("水鱼未接受本次操作，请检查 Import-Token 后重试。")

    async def update(self, details: list[dict[str, Any]], import_token: str) -> PortableImportResult:
        async with self._http_client() as client:
            catalog_response = await client.get(DIVINGFISH_BASE + "music_data")
            catalog_response.raise_for_status()
            records, skipped = self.serialize(details, catalog_response.json())
            response = await client.post(
                DIVINGFISH_BASE + "player/update_records", json=records,
                headers={"Import-Token": import_token},
            )
        self._check_divingfish_response(response)
        return PortableImportResult(len(records), sum(bool(r["fc"] or r["fs"]) for r in records), skipped)

    async def clear(self, import_token: str) -> None:
        async with self._http_client() as client:
            response = await client.delete(
                DIVINGFISH_BASE + "player/delete_records", headers={"Import-Token": import_token},
            )
        self._check_divingfish_response(response)

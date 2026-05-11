from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .utils import now_ts, safe_int


@dataclass(slots=True)
class UserRecord:
    player_name: str = ""
    rating: int = 0
    divingfish_import_token: str = ""
    bound_at: int = 0
    last_sync_at: int = 0
    last_sync_result: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "UserRecord":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            player_name=str(raw.get("player_name") or ""),
            rating=safe_int(raw.get("rating"), 0),
            divingfish_import_token=str(raw.get("divingfish_import_token") or ""),
            bound_at=safe_int(raw.get("bound_at"), 0),
            last_sync_at=safe_int(raw.get("last_sync_at"), 0),
            last_sync_result=str(raw.get("last_sync_result") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UserStore:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "users.json"
        self._lock = asyncio.Lock()
        self._users: dict[str, UserRecord] = {}
        self._load()

    def _load(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._users = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            self._users = {}
            return
        if not isinstance(raw, dict):
            self._users = {}
            return
        self._users = {
            str(user_key): UserRecord.from_dict(record)
            for user_key, record in raw.items()
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    async def save(self) -> None:
        payload = {
            user_key: record.to_dict()
            for user_key, record in sorted(self._users.items())
        }
        await asyncio.to_thread(self._write_json, self.path, payload)

    def get(self, user_key: str) -> UserRecord:
        return self._users.get(user_key, UserRecord())

    async def set_player_profile(
        self,
        user_key: str,
        *,
        player_name: str,
        rating: int,
    ) -> UserRecord:
        async with self._lock:
            record = self.get(user_key)
            record.player_name = player_name
            record.rating = int(rating or 0)
            record.bound_at = now_ts()
            self._users[user_key] = record
            await self.save()
            return record

    async def set_import_token(self, user_key: str, token: str) -> UserRecord:
        async with self._lock:
            record = self.get(user_key)
            record.divingfish_import_token = token
            self._users[user_key] = record
            await self.save()
            return record

    async def set_sync_result(
        self,
        user_key: str,
        *,
        player_name: str,
        rating: int,
        result: str,
    ) -> UserRecord:
        async with self._lock:
            record = self.get(user_key)
            if player_name:
                record.player_name = player_name
            record.rating = int(rating or record.rating or 0)
            record.last_sync_at = now_ts()
            record.last_sync_result = result
            self._users[user_key] = record
            await self.save()
            return record

    async def clear_local_profile(self, user_key: str, *, result: str) -> UserRecord:
        async with self._lock:
            record = self.get(user_key)
            record.player_name = ""
            record.rating = 0
            record.last_sync_at = now_ts()
            record.last_sync_result = result
            self._users[user_key] = record
            await self.save()
            return record

    async def remove(self, user_key: str) -> bool:
        async with self._lock:
            existed = user_key in self._users
            self._users.pop(user_key, None)
            await self.save()
            return existed

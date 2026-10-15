from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable, Iterable

from .utils import extract_sgid, is_probable_sgid


class UpdateInputError(ValueError):
    pass


class PendingUpdates:
    def __init__(self, timeout: int = 180, clock: Callable[[], float] = time.monotonic):
        self.timeout = max(10, int(timeout))
        self.clock = clock
        self._deadlines: dict[tuple[str, str, str], float] = {}

    def begin(self, key: tuple[str, str, str]) -> None:
        now = self.clock()
        self._deadlines = {k: v for k, v in self._deadlines.items() if v > now}
        self._deadlines[key] = now + self.timeout

    def state(self, key: tuple[str, str, str]) -> str:
        deadline = self._deadlines.get(key)
        if deadline is None:
            return "absent"
        return "waiting" if deadline > self.clock() else "expired"

    def remove(self, key: tuple[str, str, str]) -> None:
        self._deadlines.pop(key, None)

    def clear(self) -> None:
        self._deadlines.clear()


def select_sgid(values: Iterable[str]) -> str:
    candidates = {
        sgid
        for value in values
        if (sgid := extract_sgid(value)) and is_probable_sgid(sgid)
    }
    if not candidates:
        raise UpdateInputError("未找到舞萌 SGID，请发送官方玩家二维码图片或完整 SGID 文本。")
    if len(candidates) > 1:
        raise UpdateInputError("发现多个不同的 SGID，请单独发送本次要更新的一个玩家二维码。")
    return candidates.pop()


class QrImageReader:
    max_file_bytes = 20 * 1024 * 1024
    max_pixels = 24_000_000

    def decode_file(self, path: str) -> list[str]:
        try:
            import zxingcpp
            from PIL import Image, ImageOps, UnidentifiedImageError
        except ImportError as exc:
            raise UpdateInputError("二维码识别依赖未安装，请让 Bot 管理员更新插件依赖，或直接发送 SGID 文本。") from exc

        source = Path(path)
        try:
            if source.stat().st_size > self.max_file_bytes:
                raise UpdateInputError("图片过大，请发送小于 20 MB 的二维码图片。")
            with Image.open(source) as image:
                if image.width * image.height > self.max_pixels:
                    raise UpdateInputError("图片分辨率过高，请裁剪后重新发送。")
                image = ImageOps.exif_transpose(image).convert("RGB")
                results = zxingcpp.read_barcodes(
                    image, formats=zxingcpp.BarcodeFormat.QRCode,
                    try_rotate=True, try_downscale=True, try_invert=True,
                )
                return [result.text for result in results if result.valid]
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise UpdateInputError("图片无法读取，请重新发送二维码原图。") from exc

    async def read(self, images: Iterable[object]) -> list[str]:
        values: list[str] = []
        failure: UpdateInputError | None = None
        for component in images:
            try:
                path = await component.convert_to_file_path()
            except Exception:
                failure = UpdateInputError("二维码图片获取失败，请重新发送原图或 SGID 文本。")
                continue
            try:
                values.extend(await asyncio.to_thread(self.decode_file, path))
            except UpdateInputError as exc:
                failure = exc
        if not values and failure:
            raise failure
        return values

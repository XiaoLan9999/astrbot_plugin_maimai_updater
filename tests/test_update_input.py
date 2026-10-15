from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import qrcode
from PIL import Image

from astrbot_plugin_maimai_updater.update_input import (
    PendingUpdates, QrImageReader, UpdateInputError, select_sgid,
)


SGID = "SGWCMAID261016120000" + "A" * 64
OTHER_SGID = "SGWCMAID261016120000" + "B" * 64


def qr_sheet(path: Path, texts: list[str]) -> None:
    codes = [qrcode.make(text).convert("RGB") for text in texts]
    sheet = Image.new("RGB", (sum(code.width for code in codes) + 40, max(code.height for code in codes) + 40), "white")
    x = 20
    for code in codes:
        sheet.paste(code, (x, 20))
        x += code.width
    sheet.save(path)


class InputTest(unittest.IsolatedAsyncioTestCase):
    def test_pending_scope_expiry_and_restart(self):
        now = [0.0]
        pending = PendingUpdates(clock=lambda: now[0])
        key = ("bot", "group:1", "user:1")
        pending.begin(key)
        self.assertEqual(pending.state(("bot", "group:2", "user:1")), "absent")
        self.assertEqual(pending.state(("bot", "group:1", "user:2")), "absent")
        self.assertEqual(pending.state(("bot2", "group:1", "user:1")), "absent")
        now[0] = 170
        pending.begin(key)
        now[0] = 181
        self.assertEqual(pending.state(key), "waiting")
        now[0] = 350
        self.assertEqual(pending.state(key), "expired")
        pending.remove(key)
        self.assertEqual(pending.state(key), "absent")

    async def test_scan_all_qrs_before_selecting_sgid(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "qrs.png"
            qr_sheet(path, ["https://example.org/unrelated", SGID])
            values = QrImageReader().decode_file(str(path))
            self.assertIn("https://example.org/unrelated", values)
            self.assertIn(SGID, values)
            self.assertEqual(select_sgid(values), SGID)

    async def test_read_multiple_images_even_when_first_has_no_sgid(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f"qr{i}.png" for i in range(2)]
            qr_sheet(paths[0], ["unrelated"])
            qr_sheet(paths[1], [SGID])
            images = [type("Image", (), {"convert_to_file_path": AsyncMock(return_value=str(path))})() for path in paths]
            self.assertEqual(select_sgid(await QrImageReader().read(images)), SGID)

    def test_duplicates_accepted_and_multiple_accounts_rejected(self):
        self.assertEqual(select_sgid([SGID, SGID]), SGID)
        with self.assertRaisesRegex(UpdateInputError, "多个不同"):
            select_sgid([SGID, OTHER_SGID])
        with self.assertRaisesRegex(UpdateInputError, "未找到"):
            select_sgid(["other QR", "https://example.org"])

    def test_actual_multi_account_qr_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "qrs.png"
            qr_sheet(path, [SGID, OTHER_SGID])
            with self.assertRaisesRegex(UpdateInputError, "多个不同"):
                select_sgid(QrImageReader().decode_file(str(path)))

    def test_corrupt_and_oversized_images(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.png"
            path.write_bytes(b"invalid image")
            with self.assertRaisesRegex(UpdateInputError, "无法读取"):
                QrImageReader().decode_file(str(path))
            reader = QrImageReader()
            reader.max_file_bytes = 2
            with self.assertRaisesRegex(UpdateInputError, "过大"):
                reader.decode_file(str(path))

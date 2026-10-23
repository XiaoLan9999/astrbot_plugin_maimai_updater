from __future__ import annotations

import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from astrbot_plugin_maimai_updater.maimai_official_interface import local_runtime as runtime
from astrbot_plugin_maimai_updater.maimai_official_interface.wine_bridge import WineChimeBridge
from astrbot_plugin_maimai_updater import remote_scores
from astrbot_plugin_maimai_updater.maimai_service import MaimaiService
from astrbot_plugin_maimai_updater.remote_scores import PortableImportResult


path = Path(__file__).resolve().parents[1] / "tools/setup_local_runtime.py"
spec = importlib.util.spec_from_file_location("setup_local_runtime", path)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class LocalRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def test_arm64_only_becomes_available_after_successful_probe_marker(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"MAIMAI_CHIME_RUNTIME_DIR": folder}):
            wine = Path(folder) / "wine"
            wine.write_bytes(b"runtime")
            prefix = Path(folder) / "prefix"
            prefix.mkdir()
            manifest = {"schema": 1, "wine_binary": str(wine), "prefix": str(prefix), "probe": "failed"}
            marker = Path(folder) / "runtime.json"
            marker.write_text(json.dumps(manifest))
            self.assertIsNone(runtime.prepared_runtime())
            manifest["probe"] = "dll_exports"
            marker.write_text(json.dumps(manifest))
            self.assertEqual(runtime.prepared_runtime().prefix, prefix)
            with patch.object(remote_scores, "is_arm64_linux", return_value=True):
                self.assertTrue(remote_scores.supports_local_runtime())
            marker.write_text("[]")
            self.assertIsNone(runtime.prepared_runtime())

    def test_bridge_uses_prepared_runtime_and_separate_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wine, dll, bridge = (root / name for name in ("wine", "core.dat", "chime_bridge.exe"))
            for p in (wine, dll, bridge): p.write_bytes(b"test")
            prefix = root / "prefix"
            prefix.mkdir()
            configured = runtime.LocalRuntime(wine, prefix)
            module = "astrbot_plugin_maimai_updater.maimai_official_interface.wine_bridge"
            with patch(module + ".prepared_runtime", return_value=configured), patch.dict(os.environ, {}, clear=True):
                runner = WineChimeBridge(dll_path=dll, bridge_path=bridge)
                self.assertEqual(runner.wine_binary, str(wine))
                self.assertEqual(runner._environment()["WINEPREFIX"], str(prefix))
                self.assertEqual(runner._environment()["HODLL64"], "libarm64ecfex.dll")

    async def test_arm64_local_flow_does_not_import_x64_python_dependencies(self):
        service = MaimaiService()
        details = [{"musicId": 11026, "comboStatus": 3, "syncStatus": 4}]
        service._fetch_official_interface_details_and_rating = AsyncMock(return_value=(details, 14205, ""))
        portable = Mock()
        portable.update = AsyncMock(return_value=PortableImportResult(1, 1, 0))
        with (
            patch("astrbot_plugin_maimai_updater.maimai_service.is_arm64_linux", return_value=True),
            patch("astrbot_plugin_maimai_updater.maimai_service.supports_local_runtime", return_value=True),
            patch("astrbot_plugin_maimai_updater.maimai_service.PortableScoreClient", return_value=portable),
            patch.object(service, "_load_imports", side_effect=AssertionError("native dependency import")),
        ):
            result = await service.sync_from_sgid_to_divingfish(sgid="sample", import_token="user-token")
        service._fetch_official_interface_details_and_rating.assert_awaited_once_with("sample")
        portable.update.assert_awaited_once_with(details, "user-token")
        self.assertEqual((result.score_count, result.marked_score_count, result.rating), (1, 1, 14205))

    def test_archive_checksum_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "fake.tar"
            archive.write_bytes(b"bad archive")
            with self.assertRaisesRegex(setup.SetupError, "checksum"):
                setup.extract_packages(archive, Path(folder))

    def test_unsupported_memory_pages_do_not_start_download_or_install(self):
        with (
            patch.object(setup, "is_arm64_linux", return_value=True),
            patch.object(setup.os, "sysconf", return_value=16384, create=True),
            patch.object(setup, "download") as download,
            patch.object(setup, "run") as install,
        ):
            with self.assertRaisesRegex(setup.SetupError, "requires_4k_pages"):
                setup.install()
        download.assert_not_called()
        install.assert_not_called()

    def test_installer_extracts_only_expected_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            archive = directory / "test.tar"
            with tarfile.open(archive, "w") as data:
                for name in (*setup.PACKAGES, "../escape.deb", "dxvk.tar.gz"):
                    entry = tarfile.TarInfo(name)
                    entry.size = 3
                    data.addfile(entry, io.BytesIO(b"deb"))
            with patch.object(setup, "RUNTIME_SHA256", setup.digest(archive)):
                files = setup.extract_packages(archive, directory)
            self.assertEqual({f.name for f in files}, set(setup.PACKAGES))
            self.assertFalse((directory.parent / "escape.deb").exists())

    def test_native_provider_has_no_embedded_developer_token(self):
        service = MaimaiService()
        constructor = Mock()
        service._imports = {"DivingFishProvider": constructor}
        service._divingfish_provider()
        constructor.assert_called_once_with()

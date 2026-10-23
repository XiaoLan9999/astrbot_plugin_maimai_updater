from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from packaging.requirements import Requirement

from astrbot_plugin_maimai_updater.maimai_service import MaimaiService
from astrbot_plugin_maimai_updater.remote_scores import (
    PortableBackendError, PortableScoreClient, validate_details,
)


DETAILS = [{"musicId": 11026, "level": 3, "achievement": 1001481,
            "comboStatus": 3, "syncStatus": 4, "deluxeScoreMax": 2914}]
SONGS = [{"id": "11026", "title": "Test song", "type": "DX"}]


class PortableScoresTest(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        client = PortableScoreClient()
        client._http_client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return client

    async def test_portable_import_preserves_marks_without_native_dependencies(self):
        requests = []

        def respond(request):
            requests.append(request)
            if request.url.path.endswith("music_data"):
                return httpx.Response(200, json=SONGS)
            self.assertEqual(request.headers["Import-Token"], "user-import-token")
            self.assertNotIn("Authorization", request.headers)
            self.assertIn(b'"fc":"ap"', request.content)
            self.assertIn(b'"fs":"fsdp"', request.content)
            self.assertIn(b'"title":"Test song"', request.content)
            return httpx.Response(200, json={"message": "success"})

        client = self.client(respond)
        result = await client.update(DETAILS, "user-import-token")
        self.assertEqual((result.count, result.marked, result.skipped), (1, 1, 0))
        self.assertEqual(len(requests), 2)

    async def test_legacy_remote_settings_cannot_override_local_backend(self):
        service = MaimaiService(remote_score_url="not-a-valid-url", remote_score_token="old-service-key")
        service._sync_official_sgid_to_divingfish = AsyncMock(return_value="local-result")
        with (
            patch("astrbot_plugin_maimai_updater.maimai_service.supports_local_runtime", return_value=True),
            patch("astrbot_plugin_maimai_updater.maimai_service.is_arm64_linux", return_value=False),
            patch.object(PortableScoreClient, "fetch", new_callable=AsyncMock) as remote_fetch,
        ):
            result = await service.sync_from_sgid_to_divingfish(sgid="sample-sgid", import_token="user-token")
        remote_fetch.assert_not_awaited()
        service._sync_official_sgid_to_divingfish.assert_awaited_once_with("sample-sgid", "user-token")
        self.assertEqual(result, "local-result")
        self.assertEqual(service.remote_score_url, "")
        self.assertEqual(service.remote_score_token, "")

    async def test_rejected_auth_and_incomplete_marks_never_write(self):
        for status, body in [(401, {}), (200, {"protocol": 1, "music_details": [{"musicId": 1}]})]:
            calls = []
            client = self.client(lambda request: (calls.append(request), httpx.Response(status, json=body))[1])
            with self.assertRaises(PortableBackendError):
                await client.fetch("https://scores.example.test", "service-key", "sample-sgid")
            self.assertEqual(len(calls), 1)

    def test_arm64_preflight_and_requirements_markers(self):
        with patch("astrbot_plugin_maimai_updater.maimai_service.supports_local_runtime", return_value=False):
            with self.assertRaisesRegex(PortableBackendError, "本地运行环境"):
                MaimaiService(remote_score_url="https://old.example.test", remote_score_token="old-key").ensure_backend_available()
        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        for line in requirements.read_text().splitlines():
            req = Requirement(line)
            if req.name in {"maimai-py", "maimai-ffi"}:
                self.assertFalse(req.marker.evaluate({"sys_platform": "linux", "platform_machine": "aarch64"}))
                self.assertTrue(req.marker.evaluate({"sys_platform": "win32", "platform_machine": "AMD64"}))
                self.assertTrue(req.marker.evaluate({"sys_platform": "linux", "platform_machine": "x86_64"}))

    def test_mark_mappings_and_link_title_from_catalog(self):
        for combo in range(5):
            for sync in range(6):
                detail = {**DETAILS[0], "musicId": 383, "comboStatus": combo, "syncStatus": sync}
                records, _ = PortableScoreClient.serialize([detail], [{"id": 383, "title": "Link(CoF)", "type": "SD"}])
                self.assertEqual(records[0]["title"], "Link(CoF)")
                self.assertEqual(records[0]["achievements"], 100.1481)
                if sync == 5:
                    self.assertEqual(records[0]["fs"], "sync")
        with self.assertRaises(PortableBackendError):
            validate_details([{**DETAILS[0], "achievement": float("nan")}])

    async def test_clear_uses_documented_delete_endpoint(self):
        calls = []
        client = self.client(lambda request: (calls.append(request), httpx.Response(200, json={"message": 1}))[1])
        await client.clear("user-token")
        self.assertEqual(calls[0].method, "DELETE")
        self.assertTrue(calls[0].url.path.endswith("player/delete_records"))

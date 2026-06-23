from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_maimai_updater.official_protocol import (
    DEFAULT_OFFICIAL_TITLE_ENDPOINTS,
    MAI_ENCODING,
    OfficialTitleServerError,
    combo_status_to_fc_name,
    decode_response_payload,
    encode_request_payload,
    erase_sgid_hash_identifier,
    obfuscate_api,
    official_api_name,
    OfficialTitleClient,
    sync_status_to_fs_name,
    ChimeSessionResolver,
)


class OfficialProtocolTest(unittest.TestCase):
    def test_chime_session_default_game_ids(self):
        resolver = ChimeSessionResolver(dll_path=__file__)

        self.assertEqual(resolver.game_id, "MAID")
        self.assertEqual(resolver.qr_game_id, "MAID")
        self.assertEqual(resolver.title_key, "SDGB")

    def test_official_api_name_and_obfuscation(self):
        self.assertEqual(official_api_name("GetUserMusicApi"), "GetUserMusicApiMaimaiChn")
        self.assertEqual(
            obfuscate_api("GetUserMusicApi"),
            obfuscate_api("MaimaiChnGetUserMusicApi"),
        )
        self.assertEqual(
            obfuscate_api("GetUserMusicApi"),
            obfuscate_api("GetUserMusicApiMaimaiChn"),
        )
        self.assertEqual(len(obfuscate_api("GetUserMusicApi")), 32)

    def test_sgid_hash_identifier_is_erased(self):
        sgid = "SGWCMAID260511123456ABCDEF"
        self.assertEqual(erase_sgid_hash_identifier(sgid), "ABCDEF")

    def test_combo_status_mapping(self):
        self.assertIsNone(combo_status_to_fc_name(0))
        self.assertEqual(combo_status_to_fc_name(1), "FC")
        self.assertEqual(combo_status_to_fc_name(2), "FCP")
        self.assertEqual(combo_status_to_fc_name(3), "AP")
        self.assertEqual(combo_status_to_fc_name(4), "APP")

    def test_sync_status_mapping(self):
        self.assertIsNone(sync_status_to_fs_name(0))
        self.assertEqual(sync_status_to_fs_name(5), "SYNC")
        self.assertEqual(sync_status_to_fs_name(1), "FS")
        self.assertEqual(sync_status_to_fs_name(2), "FSP")
        self.assertEqual(sync_status_to_fs_name(3), "FSD")
        self.assertEqual(sync_status_to_fs_name(4), "FSDP")

    @unittest.skipIf(importlib.util.find_spec("cryptography") is None, "cryptography not installed")
    def test_payload_round_trip(self):
        payload = {
            "userId": 12345,
            "nextIndex": 0,
            "maxCount": 50,
        }
        self.assertEqual(decode_response_payload(encode_request_payload(payload)), payload)

    def test_default_title_endpoint_points_to_game_setting_entry(self):
        self.assertTrue(DEFAULT_OFFICIAL_TITLE_ENDPOINTS)
        self.assertTrue(
            DEFAULT_OFFICIAL_TITLE_ENDPOINTS[0].base_url.endswith("/Maimai2Servlet/")
        )


class OfficialTitleClientTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipIf(importlib.util.find_spec("cryptography") is None, "cryptography not installed")
    async def test_post_uses_official_http_endpoint(self):
        calls = []

        class FakeResponse:
            content = encode_request_payload({"ok": True})

            def raise_for_status(self):
                calls.append(("raise_for_status",))

        class FakeHttpClient:
            async def post(self, url, *, content, headers):
                calls.append(("post", url, content, headers))
                return FakeResponse()

        client = OfficialTitleClient(
            base_url="https://example.test/Maimai2Servlet/SDGB/",
            client_id="",
            host_header="title.example.test",
        )
        client._client = FakeHttpClient()

        self.assertEqual(
            await client.post("GetUserRatingApi", 123, {"userId": 123}),
            {"ok": True},
        )

        api_hash = obfuscate_api("GetUserRatingApi")
        self.assertEqual(calls[0][0], "post")
        self.assertEqual(calls[0][1], f"https://example.test/Maimai2Servlet/SDGB/{api_hash}")
        self.assertEqual(decode_response_payload(calls[0][2]), {"userId": 123})
        self.assertEqual(calls[0][3]["Host"], "title.example.test")
        self.assertEqual(calls[0][3]["Mai-Encoding"], MAI_ENCODING)
        self.assertEqual(calls[0][3]["Content-Encoding"], "deflate")
        self.assertEqual(calls[0][3]["User-Agent"], f"{api_hash}#123")
        self.assertEqual(calls[1], ("raise_for_status",))

    @unittest.skipIf(importlib.util.find_spec("cryptography") is None, "cryptography not installed")
    async def test_post_uses_client_id_for_zero_user_agent(self):
        calls = []

        class FakeResponse:
            content = encode_request_payload({"ok": True})

            def raise_for_status(self):
                return None

        class FakeHttpClient:
            async def post(self, url, *, content, headers):
                calls.append(headers)
                return FakeResponse()

        client = OfficialTitleClient(
            base_url="https://example.test/Maimai2Servlet/",
            client_id="client-id",
        )
        client._client = FakeHttpClient()

        await client.post("GetGameSettingApi", 0, {"placeId": 0, "clientId": "client-id"})

        api_hash = obfuscate_api("GetGameSettingApi")
        self.assertEqual(calls[0]["User-Agent"], f"{api_hash}#client-id")

    @unittest.skipIf(importlib.util.find_spec("cryptography") is None, "cryptography not installed")
    async def test_post_rejects_empty_official_response(self):
        class FakeResponse:
            content = b""

            def raise_for_status(self):
                return None

        class FakeHttpClient:
            async def post(self, url, *, content, headers):
                return FakeResponse()

        client = OfficialTitleClient(
            base_url="https://example.test/Maimai2Servlet/SDGB/",
            client_id="",
        )
        client._client = FakeHttpClient()

        with self.assertRaises(OfficialTitleServerError):
            await client.post("GetUserRatingApi", 123, {"userId": 123})

    @unittest.skipIf(importlib.util.find_spec("cryptography") is None, "cryptography not installed")
    async def test_post_replays_official_session_cookie(self):
        calls = []

        class FakeHeaders:
            def __init__(self, values=None):
                self.values = list(values or [])

            def get_list(self, name):
                return self.values if name.lower() == "set-cookie" else []

        class FakeResponse:
            def __init__(self, headers):
                self.headers = headers
                self.content = encode_request_payload({"ok": True})

            def raise_for_status(self):
                return None

        class FakeHttpClient:
            def __init__(self):
                self.count = 0

            async def post(self, url, *, content, headers):
                calls.append(headers)
                self.count += 1
                if self.count == 1:
                    return FakeResponse(FakeHeaders(["sid=abc123; Path=/; HttpOnly"]))
                return FakeResponse(FakeHeaders())

        client = OfficialTitleClient(
            base_url="https://example.test/Maimai2Servlet/SDGB/",
            client_id="",
        )
        client._client = FakeHttpClient()

        await client.post("UserLoginApi", 123, {"userId": 123})
        await client.post("GetUserMusicApi", 123, {"userId": 123})

        self.assertNotIn("Cookie", calls[0])
        self.assertEqual(calls[1]["Cookie"], "sid=abc123")

    async def test_only_preview_and_login_send_session_token(self):
        calls = []
        client = OfficialTitleClient(
            base_url="https://ignored.example/Maimai2Servlet/",
            client_id="client-id",
        )

        async def fake_post(api, user_id, payload):
            calls.append((api, user_id, payload))
            if api == "GetUserMusicApi":
                return {"userMusicList": [], "nextIndex": 0}
            return {"userRating": {"rating": 14370}}

        client.post = fake_post
        await client.get_user_preview(type("Session", (), {"user_id": 123, "token": "session-token"})())
        await client.user_login(type("Session", (), {"user_id": 123, "token": "session-token"})())
        self.assertEqual(await client.get_user_music(123, token="session-token"), [])
        self.assertEqual(await client.get_user_rating(123, token="session-token"), {"rating": 14370})
        await client.user_logout(123, login_date_time=1782183759, region_id=8, place_id=3496)

        self.assertEqual(calls[0][0], "GetUserPreviewApi")
        self.assertEqual(calls[0][2]["token"], "session-token")
        self.assertEqual(calls[0][2]["clientId"], "client-id")
        self.assertEqual(calls[1][0], "UserLoginApi")
        self.assertEqual(calls[1][2]["token"], "session-token")
        self.assertEqual(calls[2][0], "GetUserMusicApi")
        self.assertEqual(calls[2][2], {"userId": 123, "nextIndex": 0, "maxCount": 50})
        self.assertNotIn("token", calls[2][2])
        self.assertEqual(calls[3][0], "GetUserRatingApi")
        self.assertNotIn("token", calls[3][2])
        self.assertEqual(calls[4][0], "UserLogoutApi")
        self.assertEqual(calls[4][2]["loginDateTime"], 1782183759)
        self.assertEqual(calls[4][2]["type"], 5)

    async def test_resolve_runtime_base_url_uses_movie_server_uri(self):
        client = OfficialTitleClient(
            base_url="https://example.test/Maimai2Servlet/",
            client_id="client-id",
        )

        async def fake_post(api, user_id, payload):
            self.assertEqual(api, "GetGameSettingApi")
            self.assertEqual(user_id, 0)
            self.assertEqual(payload, {"placeId": 3496, "clientId": "client-id"})
            return {"gameSetting": {"movieServerUri": "runtime/"}}

        client.post = fake_post

        self.assertEqual(
            await client.resolve_runtime_base_url(place_id=3496),
            "https://example.test/Maimai2Servlet/runtime/",
        )

    async def test_resolve_runtime_base_url_uses_builtin_runtime_when_setting_is_blank(self):
        client = OfficialTitleClient(
            base_url="https://example.test/Maimai2Servlet/",
            client_id="client-id",
        )

        async def fake_post(api, user_id, payload):
            self.assertEqual(api, "GetGameSettingApi")
            return {"gameSetting": {"movieServerUri": ""}}

        client.post = fake_post

        self.assertNotEqual(
            await client.resolve_runtime_base_url(place_id=3496),
            "https://example.test/Maimai2Servlet/",
        )


if __name__ == "__main__":
    unittest.main()

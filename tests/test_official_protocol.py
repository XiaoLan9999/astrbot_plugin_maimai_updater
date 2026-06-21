from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_maimai_updater.official_protocol import (
    combo_status_to_fc_name,
    decode_response_payload,
    encode_request_payload,
    erase_sgid_hash_identifier,
    obfuscate_api,
    official_api_name,
    OfficialTitleClient,
    sync_status_to_fs_name,
)


class OfficialProtocolTest(unittest.TestCase):
    def test_official_api_name_and_obfuscation(self):
        self.assertEqual(official_api_name("GetUserMusicApi"), "MaimaiChnGetUserMusicApi")
        self.assertEqual(
            obfuscate_api("GetUserMusicApi"),
            obfuscate_api("MaimaiChnGetUserMusicApi"),
        )
        self.assertEqual(len(obfuscate_api("GetUserMusicApi")), 32)

    def test_sgid_hash_identifier_is_erased_like_chimelib(self):
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


class OfficialTitleClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_post_uses_maimai_ffi_request_layer(self):
        calls = []

        class FakeClientGenerator:
            def __init__(self, http_proxy=None):
                calls.append(("generator", http_proxy))

            async def __aenter__(self):
                calls.append(("enter",))
                return "fake-client"

            async def __aexit__(self, exc_type, exc, tb):
                calls.append(("exit", exc_type))

        async def fake_request(api, payload, client, user_id):
            calls.append(("request", api, payload, client, user_id))
            return {"ok": True}

        fake_request_module = types.SimpleNamespace(
            AsyncClientGenerator=FakeClientGenerator,
            request=fake_request,
        )
        fake_pkg = types.ModuleType("maimai_ffi")
        fake_pkg.request = fake_request_module
        old_pkg = sys.modules.get("maimai_ffi")
        old_request = sys.modules.get("maimai_ffi.request")
        sys.modules["maimai_ffi"] = fake_pkg
        sys.modules["maimai_ffi.request"] = fake_request_module
        try:
            client = OfficialTitleClient(
                base_url="https://ignored.example/Maimai2Servlet/",
                client_id="",
                http_proxy="http://127.0.0.1:7890",
            )
            self.assertEqual(
                await client.post("GetUserRatingApi", 123, {"userId": 123}),
                {"ok": True},
            )
        finally:
            if old_pkg is None:
                sys.modules.pop("maimai_ffi", None)
            else:
                sys.modules["maimai_ffi"] = old_pkg
            if old_request is None:
                sys.modules.pop("maimai_ffi.request", None)
            else:
                sys.modules["maimai_ffi.request"] = old_request

        self.assertEqual(calls[0], ("generator", "http://127.0.0.1:7890"))
        self.assertEqual(calls[1], ("enter",))
        self.assertEqual(calls[2], ("request", "GetUserRatingApi", {"userId": 123}, "fake-client", 123))
        self.assertEqual(calls[3], ("exit", None))

    async def test_get_user_music_and_rating_send_session_token(self):
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
        self.assertEqual(await client.get_user_music(123, token="session-token"), [])
        self.assertEqual(await client.get_user_rating(123, token="session-token"), {"rating": 14370})

        self.assertEqual(calls[0][0], "GetUserMusicApi")
        self.assertEqual(calls[0][2]["token"], "session-token")
        self.assertEqual(calls[1][0], "GetUserRatingApi")
        self.assertEqual(calls[1][2]["token"], "session-token")


if __name__ == "__main__":
    unittest.main()

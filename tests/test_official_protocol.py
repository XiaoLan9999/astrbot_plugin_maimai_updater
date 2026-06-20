from __future__ import annotations

import importlib.util
import sys
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


if __name__ == "__main__":
    unittest.main()

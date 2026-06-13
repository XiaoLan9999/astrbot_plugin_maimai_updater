from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_maimai_updater.storage import UserRecord, UserStore
from astrbot_plugin_maimai_updater.utils import (
    extract_sgid,
    is_probable_import_token,
    is_probable_sgid,
    mask_secret,
    parse_bool,
    require_command_prefix_from_config,
    sgid_issued_at,
    validate_sgid_freshness,
)


class UtilsTest(unittest.TestCase):
    def test_extract_and_validate_sgid(self):
        sgid = "SGWCMAID260511231203abcdef"
        self.assertEqual(extract_sgid(f"请绑定 {sgid}"), sgid)
        self.assertTrue(is_probable_sgid(sgid))
        self.assertFalse(is_probable_sgid("not-a-sgid"))
        issued_at = sgid_issued_at(sgid)
        self.assertIsNotNone(issued_at)
        self.assertTrue(validate_sgid_freshness(sgid, now=issued_at + 120).ok)
        self.assertFalse(validate_sgid_freshness(sgid, now=issued_at + 301).ok)
        self.assertFalse(validate_sgid_freshness("SGWCMAIDbad", now=issued_at).ok)

    def test_token_validation_and_masking(self):
        token = "a" * 127
        self.assertTrue(is_probable_import_token(token))
        self.assertFalse(is_probable_import_token("short-token"))
        self.assertEqual(mask_secret("abcdef123456", 3, 3), "abc***456")
        self.assertEqual(mask_secret(""), "未绑定")

    def test_parse_bool_accepts_panel_strings(self):
        self.assertTrue(parse_bool("true", False))
        self.assertTrue(parse_bool("开启", False))
        self.assertFalse(parse_bool("false", True))
        self.assertFalse(parse_bool("关闭", True))
        self.assertTrue(parse_bool("unknown", True))
        self.assertFalse(parse_bool("unknown", False))

    def test_require_command_prefix_config_handles_panel_and_legacy_values(self):
        self.assertTrue(require_command_prefix_from_config({}))
        self.assertFalse(require_command_prefix_from_config({"require_command_prefix": "false"}))
        self.assertFalse(require_command_prefix_from_config({"require_command_prefix": False}))
        self.assertTrue(require_command_prefix_from_config({"require_command_prefix": "true"}))
        self.assertFalse(
            require_command_prefix_from_config({"enable_prefixless_update_command": "true"})
        )
        self.assertTrue(
            require_command_prefix_from_config({"enable_prefixless_update_command": "false"})
        )

class StorageTest(unittest.IsolatedAsyncioTestCase):
    async def test_user_store_roundtrip_and_unbind(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = UserStore(tmp)
            await store.set_import_token("kook:user1", "b" * 127)
            await store.set_sync_result(
                "kook:user1",
                rating=13000,
                result="成功，同步 100 条成绩",
            )

            reloaded = UserStore(tmp)
            record = reloaded.get("kook:user1")
            self.assertEqual(record.rating, 13000)
            self.assertEqual(record.divingfish_import_token, "b" * 127)
            self.assertIn("同步", record.last_sync_result)

            await reloaded.clear_local_profile("kook:user1", result="已清空")
            cleared = UserStore(tmp).get("kook:user1")
            self.assertEqual(cleared.rating, 0)
            self.assertEqual(cleared.divingfish_import_token, "b" * 127)
            self.assertEqual(cleared.last_sync_result, "已清空")

            self.assertTrue(await reloaded.remove("kook:user1"))
            self.assertEqual(reloaded.get("kook:user1"), UserRecord())

    async def test_legacy_arcade_credentials_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.json"
            path.write_text(
                '{"onebot:user1":{"player_name":"P","rating":1,"arcade_credentials":"secret"}}',
                encoding="utf-8",
            )

            store = UserStore(tmp)
            self.assertEqual(store.get("onebot:user1").rating, 1)

            await store.set_import_token("onebot:user1", "c" * 127)
            self.assertNotIn("arcade_credentials", path.read_text(encoding="utf-8"))
            self.assertNotIn("player_name", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

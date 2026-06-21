from __future__ import annotations

import sys
from pathlib import Path
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_maimai_updater.official_protocol import ChimeSession
from astrbot_plugin_maimai_updater.maimai_service import (
    MaimaiDependencyError,
    OfficialProtocolUnavailableError,
    MaimaiService,
    _is_version_at_least,
    _patch_maimai_current_version,
)


class FakeIdentifier:
    def __init__(self, credentials: str):
        self.credentials = credentials


class FakeArcadeProvider:
    def __init__(self, http_proxy=None):
        self.http_proxy = http_proxy


class FakeDivingFishProvider:
    pass


class FakeUnmarkedScore:
    fc = None
    fs = None


class FakeArcadeScores:
    scores = [FakeUnmarkedScore(), FakeUnmarkedScore()]
    rating = 14370


class FakeScore:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeFCType:
    __members__ = {"FC": "FC", "FCP": "FCP", "AP": "AP", "APP": "APP"}


class FakeFSType:
    __members__ = {"SYNC": "SYNC", "FS": "FS", "FSP": "FSP", "FSD": "FSD", "FSDP": "FSDP"}


class FakeLevelIndex(int):
    pass


class FakeRateType:
    @staticmethod
    def _from_achievement(achievement):
        return f"rate:{achievement:.4f}"


class FakeSongType:
    STANDARD = "standard"
    UTAGE = "utage"

    @staticmethod
    def _from_id(music_id):
        return FakeSongType.UTAGE if int(music_id) >= 100000 else FakeSongType.STANDARD


class FakeDifficulty:
    level = "14+"


class FakeSong:
    def get_difficulty(self, song_type, level_index):
        self.last_difficulty = (song_type, level_index)
        return FakeDifficulty()


class FakeSongs:
    def __init__(self):
        self.ids = []

    async def by_id(self, music_id):
        self.ids.append(music_id)
        return FakeSong()


class FakeClient:
    def __init__(self, fail_players: bool = False):
        self.updated = None
        self.fail_players = fail_players
        self.songs_object = FakeSongs()

    async def qrcode(self, qrcode: str, http_proxy=None):
        self.qrcode_input = (qrcode, http_proxy)
        return FakeIdentifier("arcade-credentials")

    async def scores(self, identifier, provider):
        self.scores_input = (identifier, provider)
        return FakeArcadeScores()

    async def songs(self, **kwargs):
        self.songs_input = kwargs
        return self.songs_object

    async def updates(self, identifier, scores, provider):
        self.updated = (identifier, scores, provider)


class MaimaiServiceTest(unittest.IsolatedAsyncioTestCase):
    def make_service(self, *, fail_players: bool = False, score_source_mode: str = ""):
        service = MaimaiService(
            timeout=1,
            http_proxy="http://127.0.0.1:7890",
            score_source_mode=score_source_mode,
        )
        service._imports = {
            "ArcadeProvider": FakeArcadeProvider,
            "DivingFishProvider": FakeDivingFishProvider,
            "PlayerIdentifier": FakeIdentifier,
            "Score": FakeScore,
            "FCType": FakeFCType,
            "FSType": FakeFSType,
            "LevelIndex": FakeLevelIndex,
            "RateType": FakeRateType,
            "SongType": FakeSongType,
        }
        service._client = FakeClient(fail_players=fail_players)
        return service

    async def test_bind_from_sgid_only_validates_qrcode(self):
        service = self.make_service()
        result = await service.bind_from_sgid("SGWCMAID-test")

        self.assertEqual(result.player_warning, "")
        self.assertEqual(service.client.qrcode_input, ("SGWCMAID-test", "http://127.0.0.1:7890"))
        self.assertFalse(hasattr(service.client, "scores_input"))

    async def test_sync_from_sgid_defaults_to_official_full_score_path(self):
        service = self.make_service()

        async def fake_session_from_sgid(sgid: str) -> ChimeSession:
            service.seen_sgid = sgid
            return ChimeSession(user_id=24681357, token="session-token")

        async def fake_fetch(session: ChimeSession):
            service.seen_session = session
            return (
                [
                    {
                        "musicId": 11026,
                        "level": 4,
                        "achievement": 1001481,
                        "comboStatus": 3,
                        "syncStatus": 4,
                        "deluxeScoreMax": 2914,
                        "playCount": 7,
                    }
                ],
                14370,
                "https://wq.sys-all.cn/Maimai2Servlet/",
            )

        service._official_session_from_sgid = fake_session_from_sgid
        service._fetch_official_details_and_rating = fake_fetch

        result = await service.sync_from_sgid_to_divingfish(
            sgid="SGWCMAID-test",
            import_token="import-token",
        )

        self.assertEqual(service.seen_sgid, "SGWCMAID-test")
        self.assertEqual(service.seen_session.user_id, 24681357)
        self.assertEqual(service.seen_session.token, "session-token")
        self.assertFalse(hasattr(service.client, "qrcode_input"))
        self.assertEqual(result.source, "official")
        self.assertEqual(result.score_count, 1)
        self.assertEqual(result.rating, 14370)
        self.assertEqual(result.marked_score_count, 1)
        self.assertEqual(result.player_warning, "")
        identifier, scores, provider = service.client.updated
        self.assertEqual(identifier.credentials, "import-token")
        self.assertIsInstance(provider, FakeDivingFishProvider)
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0].id, 1026)
        self.assertEqual(scores[0].fc, "AP")
        self.assertEqual(scores[0].fs, "FSDP")
        self.assertEqual(scores[0].dx_score, 2914)
        self.assertEqual(scores[0].level, "14+")

    async def test_sync_from_sgid_to_divingfish_uses_arcade_scores_when_explicit(self):
        service = self.make_service(score_source_mode="arcade")
        result = await service.sync_from_sgid_to_divingfish(
            sgid="SGWCMAID-test",
            import_token="import-token",
        )

        self.assertEqual(result.score_count, 2)
        self.assertEqual(result.rating, 14370)
        self.assertEqual(result.marked_score_count, 0)
        self.assertEqual(result.source, "arcade")
        self.assertIn("FULL COMBO", result.player_warning)
        self.assertEqual(service.client.qrcode_input, ("SGWCMAID-test", "http://127.0.0.1:7890"))
        self.assertEqual(service.client.songs_input, {"alias_provider": None})
        score_identifier, score_provider = service.client.scores_input
        self.assertEqual(score_identifier.credentials, "arcade-credentials")
        self.assertIsInstance(score_provider, FakeArcadeProvider)
        identifier, scores, provider = service.client.updated
        self.assertEqual(identifier.credentials, "import-token")
        self.assertEqual(scores, FakeArcadeScores.scores)
        self.assertIsInstance(provider, FakeDivingFishProvider)

    async def test_clear_divingfish_scores_sends_empty_score_list(self):
        service = self.make_service()
        await service.clear_divingfish_scores(import_token="import-token")

        identifier, scores, provider = service.client.updated
        self.assertEqual(identifier.credentials, "import-token")
        self.assertEqual(scores, [])
        self.assertIsInstance(provider, FakeDivingFishProvider)

    async def test_official_sgid_resolver_captures_user_id_without_saving_sgid(self):
        service = self.make_service()
        fake_request = types.SimpleNamespace()
        original_paginated = object()
        fake_request.request_paginated = original_paginated
        fake_arcade = types.SimpleNamespace(request=fake_request)

        async def fake_get_uid_encrypted(code: str, http_proxy=None):
            fake_arcade.qr_call = (code, http_proxy)
            return b"encrypted-credentials"

        async def fake_get_user_scores(credentials: bytes, http_proxy=None):
            fake_arcade.score_call = (credentials, http_proxy)
            return await fake_arcade.request.request_paginated(
                "GetUserRivalMusicApi",
                {"userId": 12345678, "rivalId": 12345678},
                object(),
                12345678,
            )

        fake_arcade.get_uid_encrypted = fake_get_uid_encrypted
        fake_arcade.get_user_scores = fake_get_user_scores
        fake_pkg = types.ModuleType("maimai_ffi")
        fake_pkg.arcade = fake_arcade
        old_pkg = sys.modules.get("maimai_ffi")
        old_arcade = sys.modules.get("maimai_ffi.arcade")
        sys.modules["maimai_ffi"] = fake_pkg
        sys.modules["maimai_ffi.arcade"] = fake_arcade
        try:
            user_id = await service._official_user_id_from_sgid("SGWCMAID-test")
        finally:
            if old_pkg is None:
                sys.modules.pop("maimai_ffi", None)
            else:
                sys.modules["maimai_ffi"] = old_pkg
            if old_arcade is None:
                sys.modules.pop("maimai_ffi.arcade", None)
            else:
                sys.modules["maimai_ffi.arcade"] = old_arcade

        self.assertEqual(user_id, 12345678)
        self.assertEqual(fake_arcade.qr_call, ("SGWCMAID-test", "http://127.0.0.1:7890"))
        self.assertEqual(fake_arcade.score_call, (b"encrypted-credentials", "http://127.0.0.1:7890"))
        self.assertIs(fake_arcade.request.request_paginated, original_paginated)

    def test_legacy_official_flag_maps_to_official_only(self):
        service = MaimaiService(official_protocol_enabled=True)

        self.assertEqual(service._score_source_mode(), "official_only")

    def test_describe_dependency_syntax_error(self):
        service = self.make_service()
        syntax_error = SyntaxError("bad syntax")
        syntax_error.filename = "__init__.py"
        syntax_error.lineno = 94
        exc = MaimaiDependencyError("dependency import failed")
        exc.__cause__ = syntax_error

        message = service.describe_error(exc)
        self.assertIn("dependency import failed", message)
        self.assertIn("__init__.py", message)
        self.assertIn("line 94", message)

    def test_describe_official_unavailable_mentions_builtin_sgid_path(self):
        service = self.make_service()
        message = service.describe_error(OfficialProtocolUnavailableError("no user id"))
        self.assertIn("SGID", message)
        self.assertIn("token/session", message)
        self.assertIn("chimelib_dll.dll", message)


class VersionTest(unittest.TestCase):
    def test_version_compare(self):
        self.assertTrue(_is_version_at_least("1.5.1", (1, 5, 1)))
        self.assertTrue(_is_version_at_least("1.6.0", (1, 5, 1)))
        self.assertFalse(_is_version_at_least("1.5.0", (1, 5, 1)))
        self.assertTrue(_is_version_at_least("0.7.0.post1", (0, 7, 0)))
        self.assertFalse(_is_version_at_least("0.9.5", (1, 4, 2)))
        self.assertFalse(_is_version_at_least("0.6.9", (0, 7, 0)))

    def test_patch_current_version_promotes_maimai2026(self):
        class FakeVersion:
            MAIMAI_DX_PRISM_PLUS = 25500
            MAIMAI_DX_CIRCLE = 26000

        class FakeEnums:
            Version = FakeVersion
            current_version = FakeVersion.MAIMAI_DX_PRISM_PLUS

        class FakeMaimaiModule:
            current_version = FakeVersion.MAIMAI_DX_PRISM_PLUS

        self.assertTrue(_patch_maimai_current_version(FakeEnums, FakeMaimaiModule))
        self.assertEqual(FakeEnums.current_version, FakeVersion.MAIMAI_DX_CIRCLE)
        self.assertEqual(FakeMaimaiModule.current_version, FakeVersion.MAIMAI_DX_CIRCLE)

    def test_patch_current_version_keeps_newer_version(self):
        class FakeVersion:
            MAIMAI_DX_CIRCLE = 26000
            MAIMAI_DX_CIRCLE_PLUS = 26500

        class FakeEnums:
            Version = FakeVersion
            current_version = FakeVersion.MAIMAI_DX_CIRCLE_PLUS

        class FakeMaimaiModule:
            current_version = FakeVersion.MAIMAI_DX_CIRCLE_PLUS

        self.assertFalse(_patch_maimai_current_version(FakeEnums, FakeMaimaiModule))
        self.assertEqual(FakeEnums.current_version, FakeVersion.MAIMAI_DX_CIRCLE_PLUS)
        self.assertEqual(FakeMaimaiModule.current_version, FakeVersion.MAIMAI_DX_CIRCLE_PLUS)


if __name__ == "__main__":
    unittest.main()

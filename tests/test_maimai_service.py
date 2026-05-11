from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_maimai_updater.maimai_service import (
    MaimaiDependencyError,
    MaimaiService,
    _is_version_at_least,
)


class FakeIdentifier:
    def __init__(self, credentials: str):
        self.credentials = credentials


class FakeArcadeProvider:
    def __init__(self, http_proxy=None):
        self.http_proxy = http_proxy

    async def get_player(self, identifier, client):
        return FakePlayer()


class FakeArcadeProviderWithoutPlayer:
    def __init__(self, http_proxy=None):
        self.http_proxy = http_proxy


class FakeDivingFishProvider:
    pass


class FakePlayer:
    name = "XiAoLan"
    rating = 14370


class FakeScores:
    scores = ["score1", "score2"]
    rating = 14370


class FakeClient:
    def __init__(self, fail_players: bool = False):
        self.updated = None
        self.fail_players = fail_players

    async def qrcode(self, qrcode: str, http_proxy=None):
        self.qrcode_input = (qrcode, http_proxy)
        return FakeIdentifier("arcade-credentials")

    async def players(self, identifier, provider):
        self.player_input = (identifier, provider)
        if self.fail_players:
            raise RuntimeError("preview failed")
        return FakePlayer()

    async def scores(self, identifier, provider):
        self.scores_input = (identifier, provider)
        return FakeScores()

    async def songs(self, **kwargs):
        self.songs_input = kwargs

    async def updates(self, identifier, scores, provider):
        self.updated = (identifier, scores, provider)


class MaimaiServiceTest(unittest.IsolatedAsyncioTestCase):
    def make_service(self, *, fail_players: bool = False, arcade_provider=FakeArcadeProvider):
        service = MaimaiService(timeout=1, http_proxy="http://127.0.0.1:7890")
        service._imports = {
            "ArcadeProvider": arcade_provider,
            "DivingFishProvider": FakeDivingFishProvider,
            "PlayerIdentifier": FakeIdentifier,
        }
        service._client = FakeClient(fail_players=fail_players)
        return service

    async def test_bind_from_sgid_only_validates_qrcode(self):
        service = self.make_service()
        result = await service.bind_from_sgid("SGWCMAID-test")

        self.assertEqual(result.player_warning, "")
        self.assertEqual(service.client.qrcode_input, ("SGWCMAID-test", "http://127.0.0.1:7890"))
        self.assertFalse(hasattr(service.client, "player_input"))

    async def test_sync_from_sgid_to_divingfish_uses_fresh_qrcode(self):
        service = self.make_service()
        result = await service.sync_from_sgid_to_divingfish(
            sgid="SGWCMAID-test",
            import_token="import-token",
        )

        self.assertEqual(result.score_count, 2)
        self.assertEqual(result.player_name, "XiAoLan")
        self.assertEqual(result.rating, 14370)
        self.assertEqual(service.client.qrcode_input, ("SGWCMAID-test", "http://127.0.0.1:7890"))
        self.assertEqual(service.client.songs_input, {"alias_provider": None})
        identifier, scores, provider = service.client.updated
        self.assertEqual(identifier.credentials, "import-token")
        self.assertEqual(scores, ["score1", "score2"])
        self.assertIsInstance(provider, FakeDivingFishProvider)
        player_identifier, player_provider = service.client.player_input
        self.assertEqual(player_identifier.credentials, "arcade-credentials")
        self.assertIsInstance(player_provider, FakeArcadeProvider)

    async def test_sync_from_sgid_to_divingfish_uses_score_rating_when_preview_fails(self):
        service = self.make_service(fail_players=True)
        with patch("astrbot_plugin_maimai_updater.maimai_service.logger.warning") as warning:
            result = await service.sync_from_sgid_to_divingfish(
                sgid="SGWCMAID-test",
                import_token="import-token",
            )

        self.assertEqual(result.score_count, 2)
        self.assertEqual(result.rating, 14370)
        self.assertIn("官方玩家名/Rating", result.player_warning)
        self.assertIsNotNone(service.client.updated)
        warning.assert_called_once()
        self.assertIn("update", warning.call_args.args[1:])

    async def test_sync_from_sgid_to_divingfish_skips_player_for_provider_without_preview(self):
        service = self.make_service(arcade_provider=FakeArcadeProviderWithoutPlayer)
        result = await service.sync_from_sgid_to_divingfish(
            sgid="SGWCMAID-test",
            import_token="import-token",
        )

        self.assertEqual(result.score_count, 2)
        self.assertEqual(result.player_name, "")
        self.assertEqual(result.rating, 14370)
        self.assertIn("不提供官方玩家名", result.player_warning)

    async def test_describe_dependency_syntax_error(self):
        service = self.make_service()
        syntax_error = SyntaxError("bad syntax")
        syntax_error.filename = "__init__.py"
        syntax_error.lineno = 94
        exc = MaimaiDependencyError("依赖导入失败")
        exc.__cause__ = syntax_error

        message = service.describe_error(exc)
        self.assertIn("依赖导入失败", message)
        self.assertIn("__init__.py", message)
        self.assertIn("line 94", message)


class VersionTest(unittest.TestCase):
    def test_version_compare(self):
        self.assertTrue(_is_version_at_least("1.4.2", (1, 4, 2)))
        self.assertTrue(_is_version_at_least("1.5.0", (1, 4, 2)))
        self.assertTrue(_is_version_at_least("0.7.0.post1", (0, 7, 0)))
        self.assertFalse(_is_version_at_least("0.9.5", (1, 4, 2)))
        self.assertFalse(_is_version_at_least("0.6.9", (0, 7, 0)))


if __name__ == "__main__":
    unittest.main()

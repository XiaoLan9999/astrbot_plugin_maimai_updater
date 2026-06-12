from __future__ import annotations

import sys
from pathlib import Path
import unittest

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


class FakeDivingFishProvider:
    pass


class FakeUnmarkedScore:
    fc = None
    fs = None


class FakeArcadeScores:
    scores = [FakeUnmarkedScore(), FakeUnmarkedScore()]
    rating = 14370


class FakeClient:
    def __init__(self, fail_players: bool = False):
        self.updated = None
        self.fail_players = fail_players

    async def qrcode(self, qrcode: str, http_proxy=None):
        self.qrcode_input = (qrcode, http_proxy)
        return FakeIdentifier("arcade-credentials")

    async def scores(self, identifier, provider):
        self.scores_input = (identifier, provider)
        return FakeArcadeScores()

    async def songs(self, **kwargs):
        self.songs_input = kwargs

    async def updates(self, identifier, scores, provider):
        self.updated = (identifier, scores, provider)


class MaimaiServiceTest(unittest.IsolatedAsyncioTestCase):
    def make_service(self, *, fail_players: bool = False):
        service = MaimaiService(timeout=1, http_proxy="http://127.0.0.1:7890")
        service._imports = {
            "ArcadeProvider": FakeArcadeProvider,
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
        self.assertFalse(hasattr(service.client, "scores_input"))

    async def test_sync_from_sgid_to_divingfish_uses_arcade_scores(self):
        service = self.make_service()
        result = await service.sync_from_sgid_to_divingfish(
            sgid="SGWCMAID-test",
            import_token="import-token",
        )

        self.assertEqual(result.score_count, 2)
        self.assertEqual(result.rating, 14370)
        self.assertEqual(result.marked_score_count, 0)
        self.assertEqual(result.source, "arcade")
        self.assertIn("基础成绩", result.player_warning)
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
        self.assertTrue(_is_version_at_least("1.5.1", (1, 5, 1)))
        self.assertTrue(_is_version_at_least("1.6.0", (1, 5, 1)))
        self.assertFalse(_is_version_at_least("1.5.0", (1, 5, 1)))
        self.assertTrue(_is_version_at_least("0.7.0.post1", (0, 7, 0)))
        self.assertFalse(_is_version_at_least("0.9.5", (1, 4, 2)))
        self.assertFalse(_is_version_at_least("0.6.9", (0, 7, 0)))


if __name__ == "__main__":
    unittest.main()

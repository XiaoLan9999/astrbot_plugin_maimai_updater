from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_maimai_updater.maimai_service import MaimaiService


class FakeIdentifier:
    def __init__(self, credentials: str):
        self.credentials = credentials


class FakeArcadeProvider:
    def __init__(self, http_proxy=None):
        self.http_proxy = http_proxy


class FakeDivingFishProvider:
    pass


class FakePlayer:
    name = "XiAoLan"
    rating = 14370


class FakeScores:
    scores = ["score1", "score2"]


class FakeClient:
    def __init__(self):
        self.updated = None

    async def qrcode(self, qrcode: str, http_proxy=None):
        self.qrcode_input = (qrcode, http_proxy)
        return FakeIdentifier("arcade-credentials")

    async def players(self, identifier, provider):
        self.player_input = (identifier, provider)
        return FakePlayer()

    async def scores(self, identifier, provider):
        self.scores_input = (identifier, provider)
        return FakeScores()

    async def updates(self, identifier, scores, provider):
        self.updated = (identifier, scores, provider)


class MaimaiServiceTest(unittest.IsolatedAsyncioTestCase):
    def make_service(self):
        service = MaimaiService(timeout=1, http_proxy="http://127.0.0.1:7890")
        service._imports = {
            "ArcadeProvider": FakeArcadeProvider,
            "DivingFishProvider": FakeDivingFishProvider,
            "PlayerIdentifier": FakeIdentifier,
        }
        service._client = FakeClient()
        return service

    async def test_bind_from_sgid_uses_qrcode_credentials(self):
        service = self.make_service()
        result = await service.bind_from_sgid("SGWCMAID-test")

        self.assertEqual(result.arcade_credentials, "arcade-credentials")
        self.assertEqual(result.player_name, "XiAoLan")
        self.assertEqual(result.rating, 14370)
        self.assertEqual(service.client.qrcode_input, ("SGWCMAID-test", "http://127.0.0.1:7890"))
        identifier, provider = service.client.player_input
        self.assertEqual(identifier.credentials, "arcade-credentials")
        self.assertIsInstance(provider, FakeArcadeProvider)

    async def test_sync_to_divingfish_updates_scores_with_import_token(self):
        service = self.make_service()
        result = await service.sync_to_divingfish(
            arcade_credentials="arcade-credentials",
            import_token="import-token",
        )

        self.assertEqual(result.score_count, 2)
        identifier, scores, provider = service.client.updated
        self.assertEqual(identifier.credentials, "import-token")
        self.assertEqual(scores, ["score1", "score2"])
        self.assertIsInstance(provider, FakeDivingFishProvider)


if __name__ == "__main__":
    unittest.main()

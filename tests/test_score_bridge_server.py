from __future__ import annotations

import importlib.util
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from astrbot_plugin_maimai_updater.utils import SGID_TIMEZONE


path = Path(__file__).resolve().parents[1] / "tools" / "score_bridge_server.py"
spec = importlib.util.spec_from_file_location("score_bridge_server", path)
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class ScoreBridgeServerTest(unittest.TestCase):
    def test_http_contract_auth_and_invalid_credential(self):
        fetch = AsyncMock(return_value={"protocol": 1, "rating": 14205, "music_details": [{"test": "score"}]})
        server = server_module.make_server(("127.0.0.1", 0), "secret", fetch)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        sgid = "SGWCMAID" + datetime.now(SGID_TIMEZONE).strftime("%y%m%d%H%M%S") + "A" * 64
        try:
            with httpx.Client(base_url=base, trust_env=False) as client:
                self.assertEqual(client.get("/health").json()["protocol"], 1)
                self.assertEqual(client.post("/v1/scores", json={"sgid": sgid}).status_code, 401)
                auth = {"Authorization": "Bearer secret"}
                self.assertEqual(client.post("/v1/scores", headers=auth, json={"sgid": "invalid"}).status_code, 400)
                response = client.post("/v1/scores", headers=auth, json={"sgid": sgid})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["rating"], 14205)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                fetch.assert_awaited_once_with(sgid)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

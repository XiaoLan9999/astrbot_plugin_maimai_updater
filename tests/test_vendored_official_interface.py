from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import astrbot_plugin_maimai_updater.maimai_official_interface as official_interface
from astrbot_plugin_maimai_updater.maimai_service import MaimaiService


class VendoredOfficialInterfaceTest(unittest.TestCase):
    def test_score_only_interface_is_vendored(self):
        self.assertEqual(
            set(official_interface.__all__),
            {
                "ChimeSession",
                "ChimeSessionError",
                "MaimaiOfficialClient",
                "OfficialFetchResult",
                "OfficialProtocolError",
                "OfficialProtocolUnavailableError",
                "OfficialTitleServerError",
                "combo_status_to_fc_name",
                "sync_status_to_fs_name",
            },
        )

    def test_service_can_discover_vendored_interface(self):
        service = MaimaiService()
        client_cls = service._load_official_interface_client_cls()

        self.assertIsNotNone(client_cls)
        self.assertEqual(client_cls.__name__, "MaimaiOfficialClient")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import types
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

    def test_service_purges_stale_official_interface_submodules(self):
        stale_protocol = types.ModuleType("maimai_official_interface.protocol")
        stale_protocol.STALE = True
        sys.modules["maimai_official_interface.protocol"] = stale_protocol

        service = MaimaiService()
        client_cls = service._load_official_interface_client_cls()

        self.assertIsNotNone(client_cls)
        self.assertIsNot(sys.modules.get("maimai_official_interface.protocol"), stale_protocol)
        self.assertFalse(getattr(sys.modules["maimai_official_interface.protocol"], "STALE", False))


if __name__ == "__main__":
    unittest.main()

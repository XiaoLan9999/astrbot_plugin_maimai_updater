from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_maimai_updater import official_protocol as root_protocol
from astrbot_plugin_maimai_updater.maimai_official_interface import protocol as vendored_protocol
from astrbot_plugin_maimai_updater.maimai_official_interface import wine_bridge as bridge_module
from astrbot_plugin_maimai_updater.maimai_official_interface.wine_bridge import (
    WineBridgeSession,
    WineBridgeSessionError,
    WineBridgeUnavailableError,
    WineChimeBridge,
)


VALID_SGID = "SGWCMAID260714120000PAYLOAD"
SESSION_TOKEN = "session-secret-token"


class WineBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp_dir.name)
        self.dll_path = self.folder / "core.dat"
        self.bridge_path = self.folder / "chime_bridge.exe"
        self.wine_path = self.folder / "wine"
        self.dll_path.write_bytes(b"dll")
        self.bridge_path.write_bytes(b"bridge")
        self.wine_path.write_bytes(b"wine")

    def tearDown(self):
        self.temp_dir.cleanup()

    def runner(self, **kwargs):
        return WineChimeBridge(
            dll_path=self.dll_path,
            bridge_path=self.bridge_path,
            wine_binary=self.wine_path,
            timeout=1,
            **kwargs,
        )

    def test_resolve_passes_secrets_only_through_stdin(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                '{"protocol":1,"ok":true,"stage":"session","error_id":0,'
                f'"user_id":12345678,"token":"{SESSION_TOKEN}"}}\n'
            ),
            stderr="",
        )
        with patch.object(bridge_module.subprocess, "run", return_value=completed) as run:
            session = self.runner().resolve(
                VALID_SGID,
                game_id="MAID",
                qr_game_id="MAID",
                chip_id="01E11890000",
                common_key="common-secret",
                title_key="SDGB",
                server_url_index=0,
            )

        self.assertEqual(session, WineBridgeSession(12345678, SESSION_TOKEN))
        command = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        command_text = " ".join(command)
        self.assertNotIn(VALID_SGID, command_text)
        self.assertNotIn("common-secret", command_text)
        self.assertNotIn(SESSION_TOKEN, command_text)
        self.assertEqual(command, [str(self.wine_path), str(self.bridge_path)])
        self.assertEqual(kwargs["input"].splitlines()[0], VALID_SGID)
        self.assertEqual(kwargs["input"].splitlines()[4], "common-secret")
        self.assertEqual(kwargs["cwd"], str(self.folder))
        self.assertNotIn("shell", kwargs)
        self.assertTrue(kwargs["start_new_session"])

    def test_probe_checks_expected_stage(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"protocol":1,"ok":true,"stage":"dll_exports"}\n',
            stderr="",
        )
        with patch.object(bridge_module.subprocess, "run", return_value=completed) as run:
            self.assertEqual(self.runner().probe(), "dll_exports")

        self.assertEqual(
            run.call_args.args[0],
            [str(self.wine_path), str(self.bridge_path), "--probe"],
        )

    def test_runtime_failure_does_not_expose_bridge_output(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=32,
            stdout=(
                '{"protocol":1,"ok":false,"stage":"session","error_id":7,'
                f'"token":"{SESSION_TOKEN}","sgid":"{VALID_SGID}"}}\n'
            ),
            stderr=f"diagnostic {SESSION_TOKEN} {VALID_SGID}",
        )
        with patch.object(bridge_module.subprocess, "run", return_value=completed):
            with self.assertRaises(WineBridgeSessionError) as raised:
                self.runner().resolve(
                    VALID_SGID,
                    game_id="MAID",
                    qr_game_id="MAID",
                    chip_id="01E11890000",
                    common_key="",
                    title_key="SDGB",
                    server_url_index=0,
                )

        message = str(raised.exception)
        self.assertIn("stage=session", message)
        self.assertIn("error_id=7", message)
        self.assertNotIn(VALID_SGID, message)
        self.assertNotIn(SESSION_TOKEN, message)

    def test_dll_load_failure_is_reported_as_unavailable(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=10,
            stdout='{"protocol":1,"ok":false,"stage":"dll_load","error_id":126}\n',
            stderr="",
        )
        with patch.object(bridge_module.subprocess, "run", return_value=completed):
            with self.assertRaises(WineBridgeUnavailableError) as raised:
                self.runner().probe()

        self.assertIn("stage=dll_load", str(raised.exception))
        self.assertIn("error_id=126", str(raised.exception))

    def test_invalid_output_and_timeout_are_sanitized(self):
        invalid = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=f"not-json {VALID_SGID} {SESSION_TOKEN}",
            stderr="",
        )
        with patch.object(bridge_module.subprocess, "run", return_value=invalid):
            with self.assertRaises(WineBridgeSessionError) as invalid_error:
                self.runner().probe()
        self.assertNotIn(VALID_SGID, str(invalid_error.exception))
        self.assertNotIn(SESSION_TOKEN, str(invalid_error.exception))

        with patch.object(
            bridge_module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="wine", timeout=1),
        ):
            with self.assertRaises(WineBridgeSessionError) as timeout_error:
                self.runner().probe()
        self.assertEqual(
            str(timeout_error.exception),
            "official Wine bridge process timed out",
        )

    def test_old_bridge_protocol_is_rejected(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"ok":true,"stage":"dll_exports"}\n',
            stderr="",
        )
        with patch.object(bridge_module.subprocess, "run", return_value=completed):
            with self.assertRaises(WineBridgeUnavailableError) as raised:
                self.runner().probe()

        self.assertIn("protocol version is incompatible", str(raised.exception))

    def test_missing_runtime_assets_are_reported_without_starting_process(self):
        missing_dll = self.folder / "missing-core.dat"
        runner = WineChimeBridge(
            dll_path=missing_dll,
            bridge_path=self.bridge_path,
            wine_binary=self.wine_path,
        )
        with patch.object(bridge_module.subprocess, "run") as run:
            with self.assertRaises(WineBridgeUnavailableError):
                runner.probe()
        run.assert_not_called()

        with self.assertRaises(WineBridgeUnavailableError):
            WineChimeBridge(
                dll_path=self.dll_path,
                bridge_path=self.folder / "missing-bridge.exe",
                wine_binary=self.wine_path,
            )

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(bridge_module.shutil, "which", return_value=None):
                with self.assertRaises(WineBridgeUnavailableError):
                    WineChimeBridge(
                        dll_path=self.dll_path,
                        bridge_path=self.bridge_path,
                        wine_binary=self.folder / "missing-wine",
                    )

    def test_process_start_failure_is_sanitized(self):
        with patch.object(
            bridge_module.subprocess,
            "run",
            side_effect=PermissionError(f"denied {VALID_SGID} {SESSION_TOKEN}"),
        ):
            with self.assertRaises(WineBridgeUnavailableError) as raised:
                self.runner().probe()

        self.assertEqual(
            str(raised.exception),
            "official Wine bridge process could not start",
        )


class ResolverWineDispatchTest(unittest.TestCase):
    def test_both_protocol_resolvers_dispatch_to_shared_wine_backend(self):
        for protocol_module in (root_protocol, vendored_protocol):
            captured = {}

            class FakeBridge:
                def __init__(self, **kwargs):
                    captured["init"] = kwargs

                def resolve(self, sgid, **kwargs):
                    captured["sgid"] = sgid
                    captured["resolve"] = kwargs
                    return WineBridgeSession(12345678, SESSION_TOKEN)

            with self.subTest(module=protocol_module.__name__):
                with (
                    patch.object(protocol_module.os, "name", "posix"),
                    patch.object(protocol_module, "WineChimeBridge", FakeBridge),
                ):
                    resolver = protocol_module.ChimeSessionResolver(
                        dll_path=__file__,
                        chip_id="01E11890000",
                        timeout=3,
                    )
                    session = resolver.resolve(VALID_SGID)

                self.assertEqual(session.user_id, 12345678)
                self.assertEqual(session.token, SESSION_TOKEN)
                self.assertEqual(captured["sgid"], VALID_SGID)
                self.assertEqual(captured["resolve"]["chip_id"], "01E11890000")

    def test_invalid_sgid_is_rejected_before_wine_starts(self):
        with (
            patch.object(root_protocol.os, "name", "posix"),
            patch.object(root_protocol, "WineChimeBridge") as bridge,
        ):
            resolver = root_protocol.ChimeSessionResolver(dll_path=__file__)
            with self.assertRaises(root_protocol.ChimeSessionError):
                resolver.resolve("invalid-sgid")
        bridge.assert_not_called()

    def test_wine_errors_map_to_existing_protocol_errors(self):
        class UnavailableBridge:
            def __init__(self, **kwargs):
                raise WineBridgeUnavailableError("Wine x64 runtime is unavailable")

        with (
            patch.object(root_protocol.os, "name", "posix"),
            patch.object(root_protocol, "WineChimeBridge", UnavailableBridge),
        ):
            resolver = root_protocol.ChimeSessionResolver(dll_path=__file__)
            with self.assertRaises(root_protocol.OfficialProtocolUnavailableError):
                resolver.resolve(VALID_SGID)

        class FailedBridge:
            def __init__(self, **kwargs):
                pass

            def resolve(self, sgid, **kwargs):
                raise WineBridgeSessionError("official Wine bridge failed at stage=session")

        with (
            patch.object(root_protocol.os, "name", "posix"),
            patch.object(root_protocol, "WineChimeBridge", FailedBridge),
        ):
            resolver = root_protocol.ChimeSessionResolver(dll_path=__file__)
            with self.assertRaises(root_protocol.ChimeSessionError):
                resolver.resolve(VALID_SGID)


if __name__ == "__main__":
    unittest.main()

"""Platform branch contracts; these tests do not claim macOS runtime acceptance."""
import json
from pathlib import Path
import shlex
import signal
import tempfile
import unittest
from unittest.mock import patch, Mock

from keydous_bridge.config import data_directory
from keydous_bridge.codex_rpc import find_codex
from keydous_bridge.integration import Integration, _source_command
from keydous_bridge.pets import _find_codex_asar


class PlatformTests(unittest.TestCase):
    def test_desktop_profile_failure_is_reported_and_releases_owner(self):
        from keydous_bridge.__main__ import main
        app, server, owner = Mock(), Mock(), Mock()
        with patch("sys.platform","win32"), patch("keydous_bridge.app.BridgeApp",return_value=app), patch("keydous_bridge.server.BridgeServer",return_value=server), patch("keydous_bridge.instance.HardwareOwner",return_value=owner), patch("keydous_bridge.desktop.run_desktop",side_effect=FileExistsError("profile path is a file")), patch("keydous_bridge.__main__.report_error") as report:
            self.assertEqual(main([]),1)
        report.assert_called_once()
        app.close.assert_called_once()
        server.server_close.assert_called_once()
        owner.close.assert_called_once()

    def test_failed_start_and_failed_app_close_still_release_owner_and_signal(self):
        from keydous_bridge.__main__ import main
        app, server, owner = Mock(), Mock(), Mock()
        app.start.side_effect = RuntimeError("start failed")
        app.close.side_effect = RuntimeError("cleanup failed")
        old = signal.getsignal(signal.SIGTERM)
        with patch("keydous_bridge.app.BridgeApp",return_value=app), patch("keydous_bridge.server.BridgeServer",return_value=server), patch("keydous_bridge.instance.HardwareOwner",return_value=owner):
            with self.assertRaises(RuntimeError):
                main(["--no-browser"])
        server.server_close.assert_called_once()
        owner.close.assert_called_once()
        self.assertEqual(signal.getsignal(signal.SIGTERM),old)

    def test_mac_data_and_app_bundle_paths(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            with patch("sys.platform", "darwin"), patch("pathlib.Path.home", return_value=home):
                self.assertEqual(data_directory(),home / "Library/Application Support/KeydousCodex")
                resource = home / "Applications/Codex.app/Contents/Resources"
                resource.mkdir(parents=True)
                (resource / "app.asar").write_bytes(b"fixture")
                (resource / "codex").write_bytes(b"fixture")
                with patch.object(Path,"is_file",lambda candidate: candidate in (resource / "app.asar", resource / "codex")):
                    self.assertEqual(_find_codex_asar(),resource / "app.asar")
                    with patch("keydous_bridge.codex_rpc.os.access",return_value=True):
                        self.assertEqual(find_codex(),resource / "codex")
                with patch.object(Path,"is_file",return_value=True), self.assertRaises(ValueError):
                    _find_codex_asar()

    def test_posix_hook_quotes_argument_boundaries_and_definitions(self):
        with tempfile.TemporaryDirectory() as root, patch("sys.platform", "darwin"):
            directory = Path(root) / "pet's folder $(touch ignored)"
            exe,args,readable,command,integrity = _source_command(directory)
            self.assertEqual(shlex.split(command),[exe,*args])
            self.assertEqual(command,readable)
            self.assertTrue(integrity)
            integration = Integration(directory)
            review = integration.review()
            self.assertEqual(review["platform"],"darwin")
            self.assertTrue(all("command_windows" not in d and "command" in d for d in review["definitions"]))
            hooks = json.loads(integration._files[2].read_text())
            self.assertEqual(len(hooks["hooks"]),8)
            self.assertTrue(all("commandWindows" not in handlers[0]["hooks"][0] for handlers in hooks["hooks"].values()))

    def test_hook_review_digest_changes_across_platforms(self):
        with tempfile.TemporaryDirectory() as root:
            integration = Integration(Path(root))
            with patch("sys.platform", "win32"):
                windows = integration._objects()[3]
            with patch("sys.platform","darwin"):
                mac = integration._objects()[3]
            self.assertNotEqual(windows["digest"],mac["digest"])

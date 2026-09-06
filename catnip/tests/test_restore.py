"""
test_restore.py
================
Unit tests for modules/firmware/restore.py — CC1352 JTAG restore procedure.

This module had 0% test coverage before this file (Análisis Comparativo
Bombercat vs Catnip, sección 5). All hardware interactions (OpenOCD,
lsusb, RP2040 mass-storage mount, serial flashing) are mocked; no
hardware or external network access is required.
"""

import os
import subprocess
from unittest.mock import MagicMock, patch, mock_open

import pytest

from modules.firmware import restore


# ─────────────────────────────────────────────────────────────────────────────
# check_openocd
# ─────────────────────────────────────────────────────────────────────────────
class TestCheckOpenocd:
    def test_not_found_returns_none(self):
        with patch.object(restore, "_bundled_openocd", return_value=None), patch(
            "shutil.which", return_value=None
        ):
            assert restore.check_openocd() is None

    def test_found_returns_path_and_prints_version(self):
        proc = MagicMock(stderr="Open On-Chip Debugger 0.12.0\nLicensed...\n")
        with patch.object(restore, "_bundled_openocd", return_value=None), patch(
            "shutil.which", return_value="/usr/bin/openocd"
        ), patch("subprocess.run", return_value=proc) as run:
            path = restore.check_openocd()
        assert path == "/usr/bin/openocd"
        run.assert_called_once()

    def test_version_probe_exception_still_returns_path(self):
        with patch.object(restore, "_bundled_openocd", return_value=None), patch(
            "shutil.which", return_value="/usr/bin/openocd"
        ), patch("subprocess.run", side_effect=OSError("boom")):
            assert restore.check_openocd() == "/usr/bin/openocd"

    def test_bundled_takes_priority_over_which(self):
        with patch.object(
            restore, "_bundled_openocd", return_value="/bundle/openocd.exe"
        ), patch("shutil.which") as which, patch(
            "subprocess.run", return_value=MagicMock(stderr="")
        ):
            path = restore.check_openocd()
        assert path == "/bundle/openocd.exe"
        which.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# _bundled_openocd / _bundled_scripts_dir
# ─────────────────────────────────────────────────────────────────────────────
class TestBundledPaths:
    def test_no_meipass_returns_none(self):
        with patch.object(restore.sys, "_MEIPASS", "/tmp/x", create=True), patch(
            "os.path.exists", return_value=False
        ):
            assert restore._bundled_openocd() is None
            assert restore._bundled_scripts_dir() is None

    def test_meipass_missing_attr_returns_none(self):
        # sys has no _MEIPASS outside a PyInstaller bundle.
        if hasattr(restore.sys, "_MEIPASS"):
            delattr(restore.sys, "_MEIPASS")
        assert restore._bundled_openocd() is None
        assert restore._bundled_scripts_dir() is None

    def test_meipass_present_and_file_exists(self):
        with patch.object(restore.sys, "_MEIPASS", "/bundle", create=True), patch(
            "os.path.exists", return_value=True
        ):
            assert restore._bundled_openocd() == os.path.join("/bundle", "openocd.exe")
            assert restore._bundled_scripts_dir() == os.path.join(
                "/bundle", "openocd_scripts"
            )


# ─────────────────────────────────────────────────────────────────────────────
# _download_asset
# ─────────────────────────────────────────────────────────────────────────────
class TestDownloadAsset:
    def test_success_writes_file(self, tmp_path):
        dest = tmp_path / "file.uf2"
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.iter_content.return_value = [b"abc", b"def"]
        with patch("requests.get", return_value=resp):
            assert restore._download_asset("http://x/file.uf2", str(dest)) is True
        assert dest.read_bytes() == b"abcdef"

    def test_http_error_returns_false(self, tmp_path):
        dest = tmp_path / "file.uf2"
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("404")
        with patch("requests.get", return_value=resp):
            assert restore._download_asset("http://x/file.uf2", str(dest)) is False
        assert not dest.exists()

    def test_network_error_returns_false(self, tmp_path):
        dest = tmp_path / "file.uf2"
        with patch("requests.get", side_effect=ConnectionError("no network")):
            assert restore._download_asset("http://x/file.uf2", str(dest)) is False


# ─────────────────────────────────────────────────────────────────────────────
# get_free_dap_path
# ─────────────────────────────────────────────────────────────────────────────
class TestGetFreeDapPath:
    def test_uses_cache_when_present(self, tmp_path):
        cached = tmp_path / restore.FREE_DAP_FILENAME
        cached.write_bytes(b"x" * 2000)
        with patch.object(restore, "CACHE_DIR", str(tmp_path)):
            assert restore.get_free_dap_path() == str(cached)

    def test_ignores_tiny_cached_file_and_downloads(self, tmp_path):
        cached = tmp_path / restore.FREE_DAP_FILENAME
        cached.write_bytes(b"x" * 10)  # below the 1000-byte sanity threshold
        release_json = {
            "assets": [
                {
                    "name": restore.FREE_DAP_FILENAME,
                    "browser_download_url": "http://x/f",
                }
            ]
        }
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = release_json
        with patch.object(restore, "CACHE_DIR", str(tmp_path)), patch(
            "requests.get", return_value=resp
        ), patch.object(restore, "_download_asset", return_value=True) as dl:
            result = restore.get_free_dap_path()
        dl.assert_called_once_with("http://x/f", str(cached))
        assert result == str(cached)

    def test_asset_not_in_release_returns_none(self, tmp_path):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "assets": [{"name": "other.uf2", "browser_download_url": "u"}]
        }
        with patch.object(restore, "CACHE_DIR", str(tmp_path)), patch(
            "requests.get", return_value=resp
        ):
            assert restore.get_free_dap_path() is None

    def test_api_error_returns_none(self, tmp_path):
        with patch.object(restore, "CACHE_DIR", str(tmp_path)), patch(
            "requests.get", side_effect=ConnectionError("down")
        ):
            assert restore.get_free_dap_path() is None


# ─────────────────────────────────────────────────────────────────────────────
# get_bridge_uf2_path
# ─────────────────────────────────────────────────────────────────────────────
class TestGetBridgeUf2Path:
    def test_finds_uf2_via_flasher_release_path(self, tmp_path):
        release_dir = tmp_path / "releases"
        release_dir.mkdir()
        (release_dir / "catsniffer_bridge_v3.uf2").write_bytes(b"x")
        flasher = MagicMock()
        flasher.get_releases_path.return_value = str(release_dir)
        assert restore.get_bridge_uf2_path(flasher) == str(
            release_dir / "catsniffer_bridge_v3.uf2"
        )

    def test_flasher_error_falls_back_to_cache(self, tmp_path):
        flasher = MagicMock()
        flasher.get_releases_path.side_effect = RuntimeError("no releases")
        (tmp_path / "catsniffer_bridge.uf2").write_bytes(b"x")
        with patch.object(restore, "CACHE_DIR", str(tmp_path)):
            assert restore.get_bridge_uf2_path(flasher) == str(
                tmp_path / "catsniffer_bridge.uf2"
            )

    def test_cache_skips_free_dap_file(self, tmp_path):
        (tmp_path / "free_dap_catsniffer.uf2").write_bytes(b"x")
        with patch.object(restore, "CACHE_DIR", str(tmp_path)):
            assert restore.get_bridge_uf2_path(None) is None

    def test_nothing_found_returns_none(self, tmp_path):
        with patch.object(restore, "CACHE_DIR", str(tmp_path)):
            assert restore.get_bridge_uf2_path(None) is None


# ─────────────────────────────────────────────────────────────────────────────
# get_default_cc1352_firmware
# ─────────────────────────────────────────────────────────────────────────────
class TestGetDefaultCc1352Firmware:
    def test_found_via_flasher_release_path(self, tmp_path):
        release_dir = tmp_path / "releases"
        release_dir.mkdir()
        target = release_dir / restore.DEFAULT_CC1352_FW
        target.write_bytes(b"x")
        flasher = MagicMock()
        flasher.get_releases_path.return_value = str(release_dir)
        assert restore.get_default_cc1352_firmware(flasher) == str(target)

    def test_falls_back_to_catnip_dir_scan(self, tmp_path, monkeypatch):
        catnip_dir = tmp_path / ".catnip"
        release_sub = catnip_dir / "v3.1.0.0"
        release_sub.mkdir(parents=True)
        target = release_sub / restore.DEFAULT_CC1352_FW
        target.write_bytes(b"x")
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        assert restore.get_default_cc1352_firmware(None) == str(target)

    def test_nothing_found_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            os.path, "expanduser", lambda p: str(tmp_path / "nonexistent")
        )
        assert restore.get_default_cc1352_firmware(None) is None


# ─────────────────────────────────────────────────────────────────────────────
# create_openocd_config
# ─────────────────────────────────────────────────────────────────────────────
class TestCreateOpenocdConfig:
    def test_no_stock_cfg_found_returns_none(self):
        with patch.object(restore, "_bundled_scripts_dir", return_value=None), patch(
            "os.path.exists", return_value=False
        ):
            assert restore.create_openocd_config() is None

    def test_uses_bundled_scripts_dir_when_present(self, tmp_path):
        bundled = tmp_path / "scripts"
        target_cfg = bundled / "target"
        target_cfg.mkdir(parents=True)
        cfg_file = target_cfg / "ti_cc13x2.cfg"
        cfg_file.write_text("tapid 0x0BB4102F end\ntapid 0x0bb4102f end\n")

        fake_tmp = MagicMock()
        fake_tmp.name = str(tmp_path / "generated.cfg")
        fake_tmp.write = MagicMock()
        fake_tmp.close = MagicMock()

        with patch.object(
            restore, "_bundled_scripts_dir", return_value=str(bundled)
        ), patch("tempfile.NamedTemporaryFile", return_value=fake_tmp):
            result = restore.create_openocd_config(tapid="0xDEADBEEF")

        assert result == fake_tmp.name
        written = fake_tmp.write.call_args[0][0]
        assert "0xDEADBEEF" in written
        assert "0xdeadbeef" in written

    def test_falls_back_to_stock_system_path(self):
        stock_path = "/usr/share/openocd/scripts/target/ti_cc13x2.cfg"
        fake_tmp = MagicMock()
        fake_tmp.name = "/tmp/generated.cfg"

        def exists_side_effect(path):
            return path == stock_path

        with patch.object(restore, "_bundled_scripts_dir", return_value=None), patch(
            "os.path.exists", side_effect=exists_side_effect
        ), patch("builtins.open", mock_open(read_data="tapid 0x0BB4102F\n")), patch(
            "tempfile.NamedTemporaryFile", return_value=fake_tmp
        ):
            result = restore.create_openocd_config(tapid="0xCAFEBABE")

        assert result == fake_tmp.name


# ─────────────────────────────────────────────────────────────────────────────
# erase_cc1352_jtag
# ─────────────────────────────────────────────────────────────────────────────
class TestEraseCc1352Jtag:
    def test_success(self):
        proc = MagicMock(stderr="init\nhalt\nshutdown\n")
        with patch.object(restore, "_bundled_scripts_dir", return_value=None), patch(
            "subprocess.run", return_value=proc
        ):
            assert restore.erase_cc1352_jtag("/usr/bin/openocd", "/tmp/cfg.cfg") is True

    def test_error_in_output_returns_false(self):
        proc = MagicMock(stderr="Error: erase failed on sector 3\n")
        with patch.object(restore, "_bundled_scripts_dir", return_value=None), patch(
            "subprocess.run", return_value=proc
        ):
            assert (
                restore.erase_cc1352_jtag("/usr/bin/openocd", "/tmp/cfg.cfg") is False
            )

    def test_timeout_returns_false(self):
        with patch.object(restore, "_bundled_scripts_dir", return_value=None), patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="openocd", timeout=60),
        ):
            assert (
                restore.erase_cc1352_jtag("/usr/bin/openocd", "/tmp/cfg.cfg") is False
            )

    def test_generic_exception_returns_false(self):
        with patch.object(restore, "_bundled_scripts_dir", return_value=None), patch(
            "subprocess.run", side_effect=OSError("no such file")
        ):
            assert (
                restore.erase_cc1352_jtag("/usr/bin/openocd", "/tmp/cfg.cfg") is False
            )

    def test_includes_bundled_scripts_dir_in_command(self):
        proc = MagicMock(stderr="")
        with patch.object(
            restore, "_bundled_scripts_dir", return_value="/bundle/scripts"
        ), patch("subprocess.run", return_value=proc) as run:
            restore.erase_cc1352_jtag("/bundle/openocd.exe", "/tmp/cfg.cfg")
        cmd = run.call_args[0][0]
        assert "-s" in cmd and "/bundle/scripts" in cmd


# ─────────────────────────────────────────────────────────────────────────────
# wait_for_bootsel / wait_for_cmsis_dap
# ─────────────────────────────────────────────────────────────────────────────
class TestWaitForBootsel:
    def test_found_immediately(self):
        with patch.object(
            restore, "find_rp2040_mount_point", return_value="/media/RPI-RP2"
        ), patch("time.sleep"):
            assert restore.wait_for_bootsel(timeout=5) == "/media/RPI-RP2"

    def test_timeout_returns_none(self):
        with patch.object(restore, "find_rp2040_mount_point", return_value=None), patch(
            "time.sleep"
        ):
            assert restore.wait_for_bootsel(timeout=3) is None


class TestWaitForCmsisDap:
    def test_detected_via_lsusb(self):
        proc = MagicMock(
            stdout=f"Bus 001 Device 005: ID {restore.CMSIS_DAP_VID_PID} ARM\n"
        )
        with patch("subprocess.run", return_value=proc), patch("time.sleep"):
            assert restore.wait_for_cmsis_dap(timeout=3) is True

    def test_lsusb_missing_assumes_available(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            assert restore.wait_for_cmsis_dap(timeout=3) is True

    def test_not_detected_times_out(self):
        proc = MagicMock(stdout="Bus 001 Device 001: ID 1d6b:0002 Linux Foundation\n")
        with patch("subprocess.run", return_value=proc), patch("time.sleep"):
            assert restore.wait_for_cmsis_dap(timeout=2) is False


# ─────────────────────────────────────────────────────────────────────────────
# _cleanup
# ─────────────────────────────────────────────────────────────────────────────
class TestCleanup:
    def test_removes_file(self):
        with patch("os.unlink") as unlink:
            restore._cleanup("/tmp/x.cfg")
        unlink.assert_called_once_with("/tmp/x.cfg")

    def test_none_path_is_noop(self):
        with patch("os.unlink") as unlink:
            restore._cleanup(None)
        unlink.assert_not_called()

    def test_swallows_unlink_errors(self):
        with patch("os.unlink", side_effect=OSError("gone")):
            restore._cleanup("/tmp/x.cfg")  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# restore_cc1352 — top-level orchestration branches
# ─────────────────────────────────────────────────────────────────────────────
class TestRestoreCc1352:
    def test_no_openocd_fails_fast(self):
        with patch.object(restore, "check_openocd", return_value=None):
            assert restore.restore_cc1352() is False

    def test_no_hex_path_and_no_default_fails(self, tmp_path):
        with patch.object(
            restore, "check_openocd", return_value="/usr/bin/openocd"
        ), patch.object(restore, "get_default_cc1352_firmware", return_value=None):
            assert restore.restore_cc1352() is False

    def test_hex_path_does_not_exist_fails(self):
        with patch.object(restore, "check_openocd", return_value="/usr/bin/openocd"):
            assert restore.restore_cc1352(hex_path="/no/such/file.hex") is False

    def test_no_free_dap_fails(self, tmp_path):
        hex_file = tmp_path / "fw.hex"
        hex_file.write_bytes(b"x")
        with patch.object(
            restore, "check_openocd", return_value="/usr/bin/openocd"
        ), patch.object(restore, "get_free_dap_path", return_value=None):
            assert restore.restore_cc1352(hex_path=str(hex_file)) is False

    def test_no_openocd_config_fails(self, tmp_path):
        hex_file = tmp_path / "fw.hex"
        hex_file.write_bytes(b"x")
        with patch.object(
            restore, "check_openocd", return_value="/usr/bin/openocd"
        ), patch.object(
            restore, "get_free_dap_path", return_value="/cache/free_dap.uf2"
        ), patch.object(
            restore, "get_bridge_uf2_path", return_value=None
        ), patch.object(
            restore, "create_openocd_config", return_value=None
        ):
            assert restore.restore_cc1352(hex_path=str(hex_file)) is False

    def test_bootsel_never_appears_fails(self, tmp_path):
        hex_file = tmp_path / "fw.hex"
        hex_file.write_bytes(b"x")
        with patch.object(
            restore, "check_openocd", return_value="/usr/bin/openocd"
        ), patch.object(
            restore, "get_free_dap_path", return_value="/cache/free_dap.uf2"
        ), patch.object(
            restore, "get_bridge_uf2_path", return_value=None
        ), patch.object(
            restore, "create_openocd_config", return_value="/tmp/cfg.cfg"
        ), patch.object(
            restore, "wait_for_bootsel", return_value=None
        ), patch.object(
            restore, "_cleanup"
        ) as cleanup:
            assert (
                restore.restore_cc1352(
                    hex_path=str(hex_file), device=MagicMock(shell_port=None)
                )
                is False
            )
        cleanup.assert_called_once_with("/tmp/cfg.cfg")

    def test_erase_failure_reports_and_returns_false(self, tmp_path):
        hex_file = tmp_path / "fw.hex"
        hex_file.write_bytes(b"x")
        device = MagicMock(shell_port="/dev/ttyACM0")
        with patch.object(
            restore, "check_openocd", return_value="/usr/bin/openocd"
        ), patch.object(
            restore, "get_free_dap_path", return_value="/cache/free_dap.uf2"
        ), patch.object(
            restore, "get_bridge_uf2_path", return_value=None
        ), patch.object(
            restore, "create_openocd_config", return_value="/tmp/cfg.cfg"
        ), patch.object(
            restore, "enter_boot_mode", return_value=True
        ), patch.object(
            restore, "wait_for_bootsel", return_value="/media/RPI-RP2"
        ), patch.object(
            restore, "wait_for_cmsis_dap", return_value=True
        ), patch.object(
            restore, "erase_cc1352_jtag", return_value=False
        ), patch(
            "shutil.copy2"
        ), patch(
            "time.sleep"
        ):
            assert (
                restore.restore_cc1352(hex_path=str(hex_file), device=device) is False
            )

    def test_full_happy_path_returns_true(self, tmp_path):
        hex_file = tmp_path / "fw.hex"
        hex_file.write_bytes(b"x")
        device = MagicMock(shell_port="/dev/ttyACM0")
        flasher = MagicMock()
        flasher.find_flash_firmware.return_value = True

        with patch.object(
            restore, "check_openocd", return_value="/usr/bin/openocd"
        ), patch.object(
            restore, "get_free_dap_path", return_value="/cache/free_dap.uf2"
        ), patch.object(
            restore, "get_bridge_uf2_path", return_value="/cache/bridge.uf2"
        ), patch.object(
            restore, "create_openocd_config", return_value="/tmp/cfg.cfg"
        ), patch.object(
            restore, "enter_boot_mode", return_value=True
        ), patch.object(
            restore, "wait_for_bootsel", return_value="/media/RPI-RP2"
        ), patch.object(
            restore, "wait_for_cmsis_dap", return_value=True
        ), patch.object(
            restore, "erase_cc1352_jtag", return_value=True
        ), patch(
            "modules.core.catnip.catnip_get_device", return_value=device
        ), patch(
            "shutil.copy2"
        ), patch(
            "time.sleep"
        ):
            result = restore.restore_cc1352(
                hex_path=str(hex_file), device=device, flasher=flasher
            )

        assert result is True
        flasher.find_flash_firmware.assert_called_once_with(str(hex_file), device)

    def test_missing_bridge_uf2_after_bootsel_fails(self, tmp_path):
        hex_file = tmp_path / "fw.hex"
        hex_file.write_bytes(b"x")
        device = MagicMock(shell_port="/dev/ttyACM0")

        with patch.object(
            restore, "check_openocd", return_value="/usr/bin/openocd"
        ), patch.object(
            restore, "get_free_dap_path", return_value="/cache/free_dap.uf2"
        ), patch.object(
            restore, "get_bridge_uf2_path", return_value=None
        ), patch.object(
            restore, "create_openocd_config", return_value="/tmp/cfg.cfg"
        ), patch.object(
            restore, "enter_boot_mode", return_value=True
        ), patch.object(
            restore, "wait_for_bootsel", return_value="/media/RPI-RP2"
        ), patch.object(
            restore, "wait_for_cmsis_dap", return_value=True
        ), patch.object(
            restore, "erase_cc1352_jtag", return_value=True
        ), patch(
            "shutil.copy2"
        ), patch(
            "time.sleep"
        ):
            assert (
                restore.restore_cc1352(hex_path=str(hex_file), device=device) is False
            )

    def test_copy_free_dap_failure_fails(self, tmp_path):
        hex_file = tmp_path / "fw.hex"
        hex_file.write_bytes(b"x")
        device = MagicMock(shell_port=None)

        with patch.object(
            restore, "check_openocd", return_value="/usr/bin/openocd"
        ), patch.object(
            restore, "get_free_dap_path", return_value="/cache/free_dap.uf2"
        ), patch.object(
            restore, "get_bridge_uf2_path", return_value=None
        ), patch.object(
            restore, "create_openocd_config", return_value="/tmp/cfg.cfg"
        ), patch.object(
            restore, "wait_for_bootsel", return_value="/media/RPI-RP2"
        ), patch(
            "shutil.copy2", side_effect=OSError("disk full")
        ), patch.object(
            restore, "_cleanup"
        ) as cleanup:
            assert (
                restore.restore_cc1352(hex_path=str(hex_file), device=device) is False
            )
        cleanup.assert_called_once_with("/tmp/cfg.cfg")

    def test_no_device_detected_after_bridge_restore_returns_true(self, tmp_path):
        """Erase + bridge restore succeeded; only the final serial flash step is skipped."""
        hex_file = tmp_path / "fw.hex"
        hex_file.write_bytes(b"x")
        device = MagicMock(shell_port="/dev/ttyACM0")

        with patch.object(
            restore, "check_openocd", return_value="/usr/bin/openocd"
        ), patch.object(
            restore, "get_free_dap_path", return_value="/cache/free_dap.uf2"
        ), patch.object(
            restore, "get_bridge_uf2_path", return_value="/cache/bridge.uf2"
        ), patch.object(
            restore, "create_openocd_config", return_value="/tmp/cfg.cfg"
        ), patch.object(
            restore, "enter_boot_mode", return_value=True
        ), patch.object(
            restore, "wait_for_bootsel", return_value="/media/RPI-RP2"
        ), patch.object(
            restore, "wait_for_cmsis_dap", return_value=True
        ), patch.object(
            restore, "erase_cc1352_jtag", return_value=True
        ), patch(
            "modules.core.catnip.catnip_get_device", return_value=None
        ), patch(
            "shutil.copy2"
        ), patch(
            "time.sleep"
        ):
            result = restore.restore_cc1352(hex_path=str(hex_file), device=device)

        assert result is True

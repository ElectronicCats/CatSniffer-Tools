"""Wireshark extcap plumbing for the Sniffle BLE capture path.

Kept free of Click so that any ``modules/<feature>/cli.py`` can import it
without creating a cycle back to ``modules.core.cli``.
"""

import os
import sys
import shutil
import subprocess
import platform
import tempfile
import threading
import time
from pathlib import Path

# Internal
from .pipes import Wireshark, UnixPipe, WindowsPipe

# External
from ..utils.output import (
    print_success,
    print_warning,
    print_error,
    print_info,
    print_dim,
)


def find_putty_path():
    """Find PuTTY executable path."""
    system = platform.system()

    if system == "Windows":
        paths = [
            Path("C:\\Program Files\\PuTTY\\putty.exe"),
            Path("C:\\Program Files (x86)\\PuTTY\\putty.exe"),
        ]
    elif system in ["Linux", "Darwin"]:
        paths = [
            Path("/usr/bin/putty"),
            Path("/usr/local/bin/putty"),
            Path("/opt/homebrew/bin/putty"),  # macOS Homebrew
        ]
    else:
        return None

    for path in paths:
        if path.exists():
            return str(path)

    # Also search in PATH
    which_cmd = "where" if system == "Windows" else "which"
    try:
        result = subprocess.run([which_cmd, "putty"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass

    return None


def run_extcap_directly(port, channel=37, mode="conn_follow", **kwargs):
    """Run Sniffle extcap directly and bridge it to Wireshark."""
    try:
        system = platform.system()

        # 1. Set up PCAP pipes
        # pipe_ws: The pipe Wireshark will read from
        # pipe_plugin: The pipe the plugin will write to
        pipe_ws = WindowsPipe() if system == "Windows" else UnixPipe()

        # Use a unique name for the internal plugin pipe to avoid conflicts
        plugin_pipe_name = f"sniffle_plugin_{os.getpid()}"
        if system == "Windows":
            pipe_plugin = WindowsPipe(path=f"\\\\.\\pipe\\{plugin_pipe_name}")
        else:
            temp_dir = tempfile.gettempdir()
            pipe_plugin = UnixPipe(path=os.path.join(temp_dir, plugin_pipe_name))

        # 2. Open pipes in background threads
        threading.Thread(target=pipe_ws.open, daemon=True).start()
        # Plugin pipe needs to be opened for READING by catnip
        if system == "Windows":
            threading.Thread(target=pipe_plugin.open, daemon=True).start()
        else:
            # On Linux, open() blocks, so we do it in a thread
            threading.Thread(target=pipe_plugin.open, args=("rb",), daemon=True).start()

        # 3. Command to run the plugin
        extcap_path = find_extcap_plugin("sniffle_extcap")
        if not extcap_path:
            print_error("Sniffle extcap plugin not found!")
            print_dim("Install it from: https://github.com/nccgroup/Sniffle")
            print_dim(
                "Place sniffle_extcap.py (or .exe) in your Wireshark extcap directory."
            )
            pipe_ws.remove()
            pipe_plugin.remove()
            return False

        # Use a real Python interpreter for .py files, or call .exe directly.
        # sys.executable may be the frozen catnip.exe when built with PyInstaller,
        # so we resolve the actual Python interpreter via _find_python_executable().
        if extcap_path.endswith(".py"):
            python_exe = _find_python_executable()
            if not python_exe:
                print_error(
                    "Could not find a Python interpreter to run the extcap plugin."
                )
                print_dim("Make sure Python is installed and available in your PATH.")
                pipe_ws.remove()
                pipe_plugin.remove()
                return False
            # Resolve the symlink so Python sets sys.path[0] to the real
            # directory (where the sniffle/ package lives), not the extcap
            # directory where the symlink sits. Without this, Windows Python
            # cannot find `from sniffle.constant import BLE_ADV_AA`.
            real_extcap_path = str(Path(extcap_path).resolve())
            cmd = [python_exe, real_extcap_path]
        else:
            cmd = [extcap_path]

        cmd.extend(
            [
                "--capture",
                "--extcap-interface",
                "sniffle",
                "--fifo",
                pipe_plugin.pipe_path,
                "--serport",
                port,
                "--mode",
                mode,
                "--advchan",
                str(channel),
            ]
        )

        # Build subprocess environment: add the real extcap script directory
        # to PYTHONPATH so relative package imports inside sniffle_extcap.py
        # work even if Python's automatic sys.path resolution falls short.
        extcap_env = os.environ.copy()
        if extcap_path.endswith(".py"):
            real_extcap_dir = str(Path(extcap_path).resolve().parent)
            existing_pp = extcap_env.get("PYTHONPATH", "")
            extcap_env["PYTHONPATH"] = (
                real_extcap_dir + os.pathsep + existing_pp
                if existing_pp
                else real_extcap_dir
            )

        # 4. Start the plugin FIRST
        print_info(f"Starting Sniffle extcap...")
        extcap_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            env=extcap_env,
        )

        # 5. Bridge worker: Cache the header and then relay
        stop_event = threading.Event()
        header_captured = threading.Event()
        cached_data = []

        # Thread to relay stderr to console for debugging
        def stderr_worker():
            try:
                for line in extcap_proc.stderr:
                    if line:
                        print_dim(f"[extcap] {line.decode().strip()}")
            except Exception:
                pass

        threading.Thread(target=stderr_worker, daemon=True).start()

        def bridge_worker():
            try:
                # Wait for plugin to connect and send the initial header
                if not pipe_plugin.ready_event.wait(timeout=30):
                    return

                # Read initial PCAP header; on Windows read() is non-blocking so loop
                while not stop_event.is_set():
                    first_chunk = pipe_plugin.read(4096)
                    if first_chunk:
                        cached_data.append(first_chunk)
                        header_captured.set()
                        break
                    if extcap_proc.poll() is not None:
                        return
                    time.sleep(0.01)

                # Now wait for Wireshark to be ready (this is set after launching Wireshark)
                pipe_ws.ready_event.wait(timeout=35)

                # Send cached header
                for chunk in cached_data:
                    pipe_ws.write_packet(chunk)
                cached_data.clear()

                while not stop_event.is_set():
                    data = pipe_plugin.read(4096)
                    if not data:
                        # If no data, check if plugin is still alive
                        if extcap_proc.poll() is not None:
                            print_warning("Plugin process terminated")
                            break
                        # Short sleep to avoid CPU spinning
                        time.sleep(0.01)
                        continue

                    # If Wireshark is gone, stop bridging
                    if ws.wireshark_process and ws.wireshark_process.poll() is not None:
                        break

                    pipe_ws.write_packet(data)
            except Exception as e:
                print_error(f"Bridge error: {str(e)}")
                pass

        threading.Thread(target=bridge_worker, daemon=True).start()

        # 6. Wait for the plugin to emit the header before launching Wireshark
        print_info("Waiting for sniffer data...")
        if not header_captured.wait(timeout=15):
            print_error("Timed out waiting for sniffer header")
            stop_event.set()
            extcap_proc.terminate()
            pipe_ws.remove()
            pipe_plugin.remove()
            return False

        # 7. NOW launch Wireshark
        ws = Wireshark()
        ws.start()

        # 8. Wait for Wireshark connection
        print_info("Connecting to Wireshark...")
        if not pipe_ws.ready_event.wait(timeout=30):
            print_error("Timed out waiting for Wireshark to connect")
            stop_event.set()
            extcap_proc.terminate()
            pipe_ws.remove()
            pipe_plugin.remove()
            return False

        print_success("Capture running automatically!")

        # 9. Wait for Wireshark to close
        ws.join()

        # Cleanup
        stop_event.set()
        extcap_proc.terminate()
        pipe_ws.remove()
        pipe_plugin.remove()

        return True

    except Exception as e:
        print_error(f"Automatic capture failed: {str(e)}")
        return False


def find_extcap_plugin(plugin_name):
    """Find extcap plugin in Wireshark directories."""
    system = platform.system()

    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        wireshark_dirs = [
            Path(appdata) / "Wireshark" / "extcap" if appdata else None,
            Path("C:\\Program Files\\Wireshark\\extcap"),
            Path("C:\\Program Files (x86)\\Wireshark\\extcap"),
        ]
        paths = []
        for d in wireshark_dirs:
            if d is None:
                continue
            paths.append(d / f"{plugin_name}.exe")
            paths.append(d / f"{plugin_name}.py")
    elif system == "Linux":
        paths = [
            Path.home() / ".local/lib/wireshark/extcap" / f"{plugin_name}.py",
            Path("/usr/lib/wireshark/extcap") / f"{plugin_name}.py",
            Path("/usr/local/lib/wireshark/extcap") / f"{plugin_name}.py",
        ]
    elif system == "Darwin":
        paths = [
            Path.home()
            / "Library/Application Support/Wireshark/extcap"
            / f"{plugin_name}.py",
            Path("/usr/local/lib/wireshark/extcap") / f"{plugin_name}.py",
        ]

    for path in paths:
        if path.is_file():
            return str(path)

    # Also search in PATH
    which_cmd = "where" if system == "Windows" else "which"
    try:
        search_name = plugin_name if system == "Windows" else f"{plugin_name}.py"
        result = subprocess.run(
            [which_cmd, search_name], capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except:
        pass

    return None


def _find_python_executable():
    """Return a Python interpreter path usable for running .py scripts.

    When catnip is built with PyInstaller, sys.executable points to the
    frozen catnip.exe, not to python.exe. Passing that path as the
    interpreter for a subprocess causes the catnip CLI to receive the
    extcap script path as an unknown sub-command. We detect the frozen
    state (sys.frozen) and any other case where sys.executable is not
    Python, then fall back to a PATH search.
    """
    # PyInstaller sets sys.frozen in bundled executables
    if not getattr(sys, "frozen", False):
        basename = os.path.basename(sys.executable).lower()
        if basename.startswith("python"):
            return sys.executable

    # sys.executable is not Python — search PATH
    candidates = ("python3", "python3.exe", "python", "python.exe")
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found

    return None

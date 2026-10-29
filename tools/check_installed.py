"""Verify that relaunching the installed exe restores a minimized window."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import time


def wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise AssertionError("Installed application did not reach the expected window state")


def main():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    hwnd = user32.FindWindowW(None, "Codex Usage")
    assert hwnd, "Installed application is not running"
    user32.PostMessageW(hwnd, 0x0112, 0xF020, 0)  # WM_SYSCOMMAND / SC_MINIMIZE
    wait_for(lambda: user32.IsIconic(hwnd))
    executable = Path(os.environ["LOCALAPPDATA"]) / "CodexUsage/bin/CodexUsage.exe"
    process = subprocess.run([str(executable)], timeout=25)
    assert process.returncode == 0
    wait_for(lambda: user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd))
    print("Installed exe: taskbar minimization and relaunch-to-restore verified")


if __name__ == "__main__":
    main()

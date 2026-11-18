"""Capture the widget in horizontal layout for visual verification."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import Application


def main():
    app = Application(smoke_test=True)
    app.root.after_cancel(app.smoke_after_id)
    app.config["layout"] = "horizontal"
    for widget in list(app._body.winfo_children()):
        widget.destroy()
    app.build_ui()
    app.root.update_idletasks()
    app.position()
    app.root.update()
    # Use Win32 to get exact window bounds including borders/shadow
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    rect = wintypes.RECT()
    user32.GetWindowRect(app.hwnd, ctypes.byref(rect))
    destination = ROOT / "test-artifacts"
    destination.mkdir(exist_ok=True)
    ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom),
                   all_screens=True).save(destination / "widget-horizontal.png")
    print(f"Horizontal layout captured: {rect.right - rect.left}x{rect.bottom - rect.top}")
    app.quit()


if __name__ == "__main__":
    main()

"""Exercise the real Tk/tray UI with sample data and capture the widget."""

from pathlib import Path
import sys

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import Application
from windows_integration import RestoreHotkey


def main():
    app = Application(smoke_test=True)
    app.start_tray()
    failures = []

    def callback_exception(exc_type, exc, traceback):
        failures.append(exc)
        app.quit()

    app.root.report_callback_exception = callback_exception

    def check():
        root = app.root
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        destination = ROOT / "test-artifacts"
        destination.mkdir(exist_ok=True)
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(destination / "widget.png")
        assert app.ticket_value.cget("text") == "3 枚"
        assert app.five.value.cget("text") == "72%"
        assert app.weekly.value.cget("text") == "47%"
        assert app.tray is not None and app.tray.visible
        app.minimize()
        root.update_idletasks()
        assert root.state() == "iconic", root.state()
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32")
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        style = user32.GetWindowLongW(app.hwnd, -20)
        assert style & 0x00040000, "Taskbar APPWINDOW flag missing"
        assert not style & 0x00000080, "Taskbar window incorrectly marked TOOLWINDOW"
        app.show()
        root.update_idletasks()
        assert root.state() == "normal"
        app.hide_to_tray()
        assert root.state() == "withdrawn"
        app.show()
        root.update_idletasks()
        assert root.state() == "normal"
        app.hotkey = RestoreHotkey(lambda: app.actions.put("show"))
        assert app.hotkey.registered, "Restore hotkey registration failed"
        app.hide_to_tray()
        app.hotkey.user32.PostThreadMessageW(app.hotkey.thread_id, 0x0312, 1, 0)
        root.after(650, check_hotkey)

    def check_hotkey():
        assert app.root.state() == "normal", "Hotkey did not restore the widget"
        print("Values, taskbar minimization, tray restoration, global hotkey: OK")

    app.root.after(1000, check)
    app.run()
    if failures:
        raise failures[0]


if __name__ == "__main__":
    main()

"""Taskbar visibility and a global restore hotkey for the Windows widget."""

import ctypes
from ctypes import wintypes
import threading


def taskbar_window(root):
    root.update_idletasks()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
    style = user32.GetWindowLongW(hwnd, -20)
    user32.SetWindowLongW(hwnd, -20, (style | 0x00040000) & ~0x00000080)
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
    return hwnd


class RestoreHotkey:
    def __init__(self, callback):
        self.callback = callback
        self.thread_id = None
        self.registered = False
        self.ready = threading.Event()
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                              wintypes.UINT, wintypes.UINT]
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                           wintypes.UINT, wintypes.UINT]
        self.user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                                 wintypes.WPARAM, wintypes.LPARAM]
        self.thread = threading.Thread(target=self._run, name="restore-hotkey", daemon=True)
        self.thread.start()
        self.ready.wait(2)

    def _run(self):
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self.thread_id = kernel32.GetCurrentThreadId()
        # MOD_CONTROL | MOD_ALT | MOD_NOREPEAT; Ctrl+Alt+U.
        self.registered = bool(self.user32.RegisterHotKey(None, 1, 0x4003, 0x55))
        self.ready.set()
        if not self.registered:
            return
        message = wintypes.MSG()
        try:
            while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == 0x0312 and message.wParam == 1:
                    self.callback()
        finally:
            self.user32.UnregisterHotKey(None, 1)

    def close(self):
        if self.thread_id and self.thread.is_alive():
            self.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(timeout=2)

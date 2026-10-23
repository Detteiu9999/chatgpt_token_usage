"""Codex Usage — Windows desktop widget and notification-area application."""

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
import webbrowser
import winreg

from PIL import Image, ImageDraw, ImageTk
import pystray

from browser import ConnectionProblem, EdgeConnection, USAGE_URL
from usage import Usage, parse_usage


APP_NAME = "Codex Usage"
DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "CodexUsage"
CONFIG_FILE = DATA_DIR / "settings.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CodexUsage"
BG = "#101723"
PANEL = "#192332"
TEXT = "#eef3fa"
MUTED = "#9eafc5"
GREEN = "#51dcba"
AMBER = "#ffc56d"
RED = "#ff858c"


def launch_command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pythonw if pythonw.exists() else Path(sys.executable)),
            str(Path(__file__).resolve())]


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
        return value == subprocess.list2cmdline(launch_command() + ["--startup"])
    except OSError:
        return False


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ,
                             subprocess.list2cmdline(launch_command() + ["--startup"]))
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def load_config():
    defaults = {"topmost": True, "interval": 60, "x": None, "y": None, "connected": False}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update({key: data[key] for key in defaults if key in data})
    except (OSError, ValueError):
        pass
    if defaults["interval"] not in (30, 60, 120, 300):
        defaults["interval"] = 60
    defaults["topmost"] = defaults["topmost"] is True
    defaults["connected"] = defaults["connected"] is True
    return defaults


def save_config(config):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(CONFIG_FILE)


class SingleInstance:
    """An existing instance receives a request to show its widget."""

    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                           wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.mutex = self.kernel.CreateMutexW(None, False, "Local\\CodexUsage.Widget.v1")
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.existing = ctypes.get_last_error() == 183
        self.event = self.kernel.CreateEventW(None, False, False, "Local\\CodexUsage.Show.v1")
        if not self.event:
            raise ctypes.WinError(ctypes.get_last_error())
        if self.existing:
            self.kernel.SetEvent(self.event)

    def requested(self):
        return self.kernel.WaitForSingleObject(self.event, 0) == 0

    def close(self):
        self.kernel.CloseHandle(self.event)
        self.kernel.CloseHandle(self.mutex)


def make_icon():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1, 1, 63, 63), radius=16, fill=BG)
    draw.arc((12, 12, 52, 52), 135, 405, fill=GREEN, width=7)
    draw.line((32, 33, 45, 23), fill=TEXT, width=5)
    draw.ellipse((28, 29, 36, 37), fill=TEXT)
    return image


def reset_label(timestamp):
    if timestamp is None:
        return "回復時刻：未取得"
    try:
        at = datetime.fromtimestamp(timestamp)
    except (ValueError, OSError, OverflowError):
        return "回復時刻：未取得"
    seconds = max(0, int(timestamp - time.time()))
    if seconds == 0:
        remaining = "再取得待ち"
    elif seconds >= 86400:
        remaining = f"あと{seconds // 86400}日{seconds % 86400 // 3600}時間"
    elif seconds >= 3600:
        remaining = f"あと{seconds // 3600}時間{seconds % 3600 // 60}分"
    else:
        remaining = f"あと{max(1, seconds // 60)}分"
    return f"回復 {at:%m/%d %H:%M}  ·  {remaining}"


class UsageCard:
    def __init__(self, app, parent, title):
        self.app = app
        self.window = None
        self.frame = tk.Frame(parent, bg=PANEL, padx=app.px(15), pady=app.px(12))
        self.frame.pack(fill="x", pady=(0, app.px(9)))
        row = tk.Frame(self.frame, bg=PANEL)
        row.pack(fill="x")
        app.label(row, title, fg=MUTED, bg=PANEL, size=10).pack(side="left")
        self.value = app.label(row, "—", bg=PANEL, size=21, bold=True)
        self.value.pack(side="right")
        self.bar = tk.Canvas(self.frame, height=app.px(6), bg=PANEL, highlightthickness=0)
        self.bar.pack(fill="x", pady=(app.px(8), app.px(9)))
        self.bar.bind("<Configure>", lambda _: self.draw())
        self.info = app.label(self.frame, "使用量：未取得", bg=PANEL, fg=MUTED, size=9)
        self.info.pack(anchor="w")
        self.reset = app.label(self.frame, "回復時刻：未取得", bg=PANEL, fg=MUTED, size=9)
        self.reset.pack(anchor="w", pady=(app.px(2), 0))

    def draw(self):
        width = self.bar.winfo_width()
        height = self.app.px(6)
        self.bar.delete("all")
        self.bar.create_rectangle(0, 0, width, height, fill="#2b394c", outline="")
        if self.window is not None:
            remaining = self.window.remaining
            color = RED if remaining <= 10 else AMBER if remaining <= 25 else GREEN
            self.bar.create_rectangle(0, 0, width * remaining / 100, height,
                                      fill=color, outline="")

    def update(self, window):
        self.window = window
        self.value.configure(text=f"{window.remaining:g}%" if window else "—")
        self.info.configure(text=f"使用済み {window.used:g}%  /  残り {window.remaining:g}%"
                            if window else "使用量：未取得")
        self.reset.configure(text=reset_label(window.resets_at) if window else "回復時刻：未取得")
        self.draw()


class Application:
    def __init__(self, instance=None, smoke_test=False, startup=False):
        self.instance = instance
        self.smoke_test = smoke_test
        self.config = load_config()
        self.snapshot: Usage | None = None
        self.error = ""
        self.tray = None
        self.actions = queue.Queue()
        self.messages = queue.Queue()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.connect_requested = threading.Event()
        self.edge = EdgeConnection(DATA_DIR / "EdgeProfile")
        self.worker_thread = None
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.config["topmost"])
        self.scale = max(1.0, float(self.root.tk.call("tk", "scaling")) / (96 / 72))
        self.icon_image = ImageTk.PhotoImage(make_icon())
        self.root.iconphoto(True, self.icon_image)
        self.build_ui()
        self.position()
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.bind("<Escape>", lambda _: self.hide())
        self.root.bind("<Button-3>", self.popup_menu)
        self.root.deiconify()
        self.root.after(100, self.tick)
        if smoke_test:
            now = time.time()
            self.snapshot = parse_usage({
                "plan_type": "plus",
                "rate_limit": {
                    "primary_window": {"used_percent": 28, "limit_window_seconds": 18000,
                                       "reset_at": now + 7200},
                    "secondary_window": {"used_percent": 53, "limit_window_seconds": 604800,
                                         "reset_at": now + 172800},
                }, "rate_limit_reset_credits": {"available_count": 3},
            })
            self.root.after(2500, self.quit)
        else:
            self.start_tray()
            if not self.config["connected"] and not startup:
                self.connect_requested.set()
            self.worker_thread = threading.Thread(target=self.worker, name="usage-reader", daemon=True)
            self.worker_thread.start()

    def px(self, n):
        return round(n * self.scale)

    def label(self, parent, text, *, size=10, fg=TEXT, bg=BG, bold=False, **kwargs):
        return tk.Label(parent, text=text, fg=fg, bg=bg,
                        font=("Yu Gothic UI", size, "bold" if bold else "normal"), **kwargs)

    def button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, bg="#243349", fg=TEXT,
                         activebackground="#31455f", activeforeground=TEXT,
                         relief="flat", borderwidth=0, cursor="hand2",
                         padx=self.px(10), pady=self.px(5), font=("Yu Gothic UI", 9))

    def build_ui(self):
        outer = tk.Frame(self.root, bg=BG, highlightbackground="#344055", highlightthickness=1)
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer, bg=BG, padx=self.px(16), pady=self.px(12))
        header.pack(fill="x")
        title = self.label(header, "◉  CODEX USAGE", size=11, bold=True)
        title.pack(side="left")
        for widget in (header, title):
            widget.bind("<ButtonPress-1>", self.drag_start)
            widget.bind("<B1-Motion>", self.drag_move)
            widget.bind("<ButtonRelease-1>", self.drag_end)
        self.button(header, "×", self.hide).pack(side="right")
        self.button(header, "⋯", self.popup_menu).pack(side="right", padx=(0, self.px(5)))
        body = tk.Frame(outer, bg=BG, padx=self.px(16))
        body.pack(fill="both", expand=True)
        self.label(body, "利用枠の残量", fg=MUTED, size=9).pack(anchor="w", pady=(0, self.px(8)))
        self.five = UsageCard(self, body, "5時間枠")
        self.weekly = UsageCard(self, body, "1週間枠")
        tickets = tk.Frame(body, bg=PANEL, padx=self.px(15), pady=self.px(10))
        tickets.pack(fill="x")
        ticket_row = tk.Frame(tickets, bg=PANEL)
        ticket_row.pack(fill="x")
        self.label(ticket_row, "利用上限のリセット", bg=PANEL, fg=MUTED).pack(side="left")
        self.ticket_value = self.label(ticket_row, "—", bg=PANEL, size=19, bold=True)
        self.ticket_value.pack(side="right")
        self.expiry = self.label(tickets, "残数：未取得", bg=PANEL, fg=MUTED, size=9)
        self.expiry.pack(anchor="w", pady=(self.px(3), 0))
        self.status = self.label(body, "接続を準備しています…", size=9, fg=MUTED,
                                 wraplength=self.px(300), justify="left", anchor="w", height=2)
        self.status.pack(fill="x", pady=(self.px(10), self.px(3)))
        self.updated = self.label(body, "最終取得：—", size=8, fg=MUTED)
        self.updated.pack(anchor="w", pady=(0, self.px(9)))
        controls = tk.Frame(body, bg=BG)
        controls.pack(fill="x", pady=(0, self.px(14)))
        self.button(controls, "接続 / ログイン", self.connect).pack(side="left")
        self.button(controls, "更新", self.refresh).pack(side="right")
        self.button(controls, "使用状況 ↗", lambda: webbrowser.open(USAGE_URL)).pack(
            side="right", padx=self.px(6))

    def position(self):
        self.root.update_idletasks()
        width = self.px(354)
        height = self.root.winfo_reqheight()
        user32 = ctypes.windll.user32
        left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        x, y = self.config["x"], self.config["y"]
        if not isinstance(x, int) or not isinstance(y, int):
            x, y = self.root.winfo_screenwidth() - width - self.px(24), self.px(40)
        x = max(left, min(x, left + vw - width))
        y = max(top, min(y, top + vh - height))
        self.root.geometry(f"{width}x{height}")
        self.move_window(x, y)

    def move_window(self, x, y):
        # Tk's negative geometry offsets mean distance from the right/bottom;
        # Win32 coordinates also support monitors left of the primary display.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.root.update_idletasks()
        hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)

    def drag_start(self, event):
        self.drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag_move(self, event):
        dx, dy = self.drag
        self.move_window(event.x_root - dx, event.y_root - dy)

    def drag_end(self, _):
        self.config.update(x=self.root.winfo_x(), y=self.root.winfo_y())
        self.persist()

    def persist(self):
        if not self.smoke_test:
            try:
                save_config(self.config)
            except OSError:
                self.error = "設定を保存できませんでした"

    def show(self):
        self.root.deiconify()
        self.root.overrideredirect(True)
        self.root.lift()
        self.root.attributes("-topmost", self.config["topmost"])

    def hide(self):
        if self.tray is None:
            if self.smoke_test:
                return
            self.root.overrideredirect(False)
            self.root.iconify()
        else:
            self.root.withdraw()

    def connect(self):
        self.status.configure(text="専用のEdge画面でログインしてください", fg=AMBER)
        self.connect_requested.set()
        self.wake.set()

    def refresh(self):
        self.wake.set()

    def popup_menu(self, event=None):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="今すぐ更新", command=self.refresh)
        menu.add_command(label="ChatGPTに接続 / 再ログイン", command=self.connect)
        menu.add_command(label="接続用ブラウザーを隠す", command=lambda: self.actions.put("hide_browser"))
        menu.add_separator()
        self.topmost_var = tk.BooleanVar(value=self.config["topmost"])
        menu.add_checkbutton(label="常に最前面", variable=self.topmost_var, command=self.toggle_topmost)
        self.startup_var = tk.BooleanVar(value=startup_enabled())
        menu.add_checkbutton(label="Windows起動時に常駐", variable=self.startup_var,
                             command=self.toggle_startup)
        interval = tk.Menu(menu, tearoff=False)
        self.interval_var = tk.IntVar(value=self.config["interval"])
        for seconds in (30, 60, 120, 300):
            interval.add_radiobutton(label=f"{seconds}秒", value=seconds,
                                     variable=self.interval_var, command=self.change_interval)
        menu.add_cascade(label="自動更新間隔", menu=interval)
        menu.add_separator()
        menu.add_command(label="ウィジェットを隠す", command=self.hide)
        menu.add_command(label="終了", command=self.quit)
        x = event.x_root if event else self.root.winfo_pointerx()
        y = event.y_root if event else self.root.winfo_pointery()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def toggle_topmost(self):
        self.config["topmost"] = self.topmost_var.get()
        self.root.attributes("-topmost", self.config["topmost"])
        self.persist()

    def toggle_startup(self):
        try:
            set_startup(self.startup_var.get())
        except OSError:
            messagebox.showerror(APP_NAME, "自動起動の設定に失敗しました", parent=self.root)

    def change_interval(self):
        self.config["interval"] = self.interval_var.get()
        self.persist()
        self.wake.set()

    def start_tray(self):
        def action(name):
            return lambda *_: self.actions.put(name)
        menu = pystray.Menu(
            pystray.MenuItem("ウィジェットを表示", action("show"), default=True),
            pystray.MenuItem("ウィジェットを隠す", action("hide")),
            pystray.MenuItem("今すぐ更新", action("refresh")),
            pystray.MenuItem("ChatGPTに接続", action("connect")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("終了", action("quit")),
        )
        try:
            self.tray = pystray.Icon("CodexUsage", make_icon(), APP_NAME, menu)
            self.tray.run_detached()
        except Exception:
            logging.exception("Notification-area icon failed")
            self.tray = None

    def worker(self):
        failures = 0
        try:
            while not self.stop.is_set():
                self.wake.clear()
                visible = self.connect_requested.is_set()
                self.connect_requested.clear()
                try:
                    self.edge.start(visible=visible)
                    payload, details = self.edge.fetch()
                    snapshot = parse_usage(payload, details)
                    self.edge.ready()
                    self.messages.put(("usage", snapshot))
                    failures = 0
                    delay = self.config["interval"]
                except ConnectionProblem as exc:
                    failures += 1
                    self.messages.put(("error", str(exc)))
                    delay = 15 if exc.needs_login else min(300, 30 * 2 ** min(failures - 1, 4))
                except Exception as exc:
                    failures += 1
                    # Do not log browser replies: they can contain account data.
                    logging.warning("Usage read failed: %s", type(exc).__name__)
                    self.messages.put(("error", "接続を再試行しています。「接続」からログインを確認できます"))
                    delay = min(300, 30 * 2 ** min(failures - 1, 4))
                if not self.stop.is_set():
                    self.wake.wait(delay)
        finally:
            self.edge.close()

    def tick(self):
        if self.stop.is_set():
            return
        if self.instance and self.instance.requested():
            self.show()
        while True:
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                break
            if action == "hide_browser":
                self.edge.hide()
            else:
                getattr(self, action)()
            if self.stop.is_set():
                return
        while True:
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "usage":
                self.snapshot = value
                self.error = ""
                if not self.config["connected"]:
                    self.config["connected"] = True
                    self.persist()
            else:
                self.error = value
        snapshot = self.snapshot
        if snapshot:
            self.five.update(snapshot.five_hour)
            self.weekly.update(snapshot.weekly)
            self.ticket_value.configure(text=f"{snapshot.reset_count} 枚"
                                        if snapshot.reset_count is not None else "—")
            if snapshot.next_expiry:
                expiry = datetime.fromtimestamp(snapshot.next_expiry).strftime("%Y/%m/%d %H:%M")
                self.expiry.configure(text=f"最も近い有効期限：{expiry}")
            else:
                self.expiry.configure(text="保有しているリセット権の残数"
                                      if snapshot.reset_count is not None else "残数を取得できませんでした")
            age = max(0, int(time.time() - snapshot.fetched_at))
            at = datetime.fromtimestamp(snapshot.fetched_at).strftime("%m/%d %H:%M:%S")
            self.updated.configure(text=f"最終取得 {at}  ·  {age}秒前")
            stale = age > max(180, self.config["interval"] * 2)
            warning = self.error or ("更新が遅れています。前回の取得値です" if stale else "")
            if warning:
                self.status.configure(text=f"{warning}（前回値）", fg=AMBER)
            else:
                plan = snapshot.plan.upper()
                self.status.configure(text=f"● 接続済み  {plan}  ·  {self.config['interval']}秒ごとに更新", fg=GREEN)
            if self.tray:
                short = lambda w: f"{w.remaining:g}%" if w else "未取得"
                tickets = snapshot.reset_count if snapshot.reset_count is not None else "未取得"
                title = f"Codex | 5時間 {short(snapshot.five_hour)} | 週間 {short(snapshot.weekly)} | リセット {tickets}"
                title = ("[前回値] " if warning else "") + title
                if self.tray.title != title:
                    self.tray.title = title
        elif self.error:
            self.status.configure(text=self.error, fg=AMBER)
        self.root.after(500, self.tick)

    def quit(self):
        if self.stop.is_set():
            return
        self.config.update(x=self.root.winfo_x(), y=self.root.winfo_y())
        self.persist()
        self.stop.set()
        self.wake.set()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.stop.set()
            self.wake.set()
            if self.worker_thread:
                self.worker_thread.join(timeout=40)


def install():
    if not getattr(sys, "frozen", False):
        raise RuntimeError("インストールにはビルド済みのexeを使用してください")
    destination = DATA_DIR / "bin" / "CodexUsage.exe"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if Path(sys.executable).resolve() != destination.resolve():
        shutil.copy2(sys.executable, destination)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        command = subprocess.list2cmdline([str(destination), "--startup"])
        winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
    print(f"Installed: {destination}")
    return destination


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--startup", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--disable-startup", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.disable_startup:
        set_startup(False)
        return
    if args.install:
        install()
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA_DIR / "app.log", maxBytes=250000, backupCount=2,
                                  encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    instance = None if args.smoke_test else SingleInstance()
    try:
        if instance and instance.existing:
            return
        Application(instance, args.smoke_test, args.startup).run()
    except Exception:
        logging.exception("Application failed")
        ctypes.windll.user32.MessageBoxW(None, f"起動できませんでした。\n{DATA_DIR / 'app.log'}", APP_NAME, 16)
        raise
    finally:
        if instance:
            instance.close()


if __name__ == "__main__":
    main()

"""Dedicated Edge profile; authenticated GETs run inside the ChatGPT origin.

Cookies and access tokens never leave the browser. Only usage responses cross CDP.
"""

import ctypes
from ctypes import wintypes
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from urllib.parse import urlsplit

import websocket


USAGE_URL = "https://chatgpt.com/settings/usage?tab=overview"

# Read-only endpoints confirmed in openai/codex backend-client/rate_limit_resets.rs.
FETCH_USAGE = r"""
(async () => {
  if (location.origin !== 'https://chatgpt.com') return {error: 'login'};
  const get = async (path, headers = {}) => {
    const response = await fetch(path, {
      credentials: 'include', cache: 'no-store', headers,
      signal: AbortSignal.timeout(12000)
    });
    let data = null;
    if ((response.headers.get('content-type') || '').includes('application/json')) {
      data = await response.json();
    }
    return {status: response.status, data};
  };
  try {
    const session = await get('/api/auth/session');
    if (!session.data?.accessToken) {
      return {error: session.status === 403 ? 'challenge' : 'login'};
    }
    const headers = {'Authorization': 'Bearer ' + session.data.accessToken};
    const [usage, resets] = await Promise.all([
      get('/backend-api/wham/usage', headers),
      get('/backend-api/wham/rate-limit-reset-credits', headers)
    ]);
    return {usage, resets};
  } catch (e) {
    return {error: e.name === 'TimeoutError' ? 'timeout' : 'network'};
  }
})()
"""


class ConnectionProblem(Exception):
    def __init__(self, message, needs_login=False):
        super().__init__(message)
        self.needs_login = needs_login


class EdgeConnection:
    def __init__(self, profile: Path):
        self.profile = profile
        self.process = None
        self.port = None
        self.browser_pid = None
        self.browser_socket = None
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.auto_hide = False

    def start(self, visible=False):
        if self.port:
            try:
                self._targets()
                if visible:
                    self.show()
                return
            except (OSError, ValueError):
                self.port = None
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
            / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        ]
        edge = next((p for p in candidates if p.is_file()), None)
        if edge is None:
            raise ConnectionProblem("Microsoft Edgeが見つかりません")
        self.profile.mkdir(parents=True, exist_ok=True)
        active_port = self.profile / "DevToolsActivePort"
        # Reattach to this dedicated profile after a widget crash; never attach
        # to the user's normal Edge profile or launch a second locked instance.
        try:
            lines = active_port.read_text(encoding="utf-8").splitlines()
            self.port = int(lines[0])
            version = self._version()
            if urlsplit(version["webSocketDebuggerUrl"]).path == lines[1]:
                self.browser_socket = version["webSocketDebuggerUrl"]
                self._identify_browser()
                self.auto_hide = True
                self.show() if visible else self.hide()
                return
        except (OSError, ValueError, IndexError, KeyError, websocket.WebSocketException):
            pass
        self.port = None
        active_port.unlink(missing_ok=True)
        args = [str(edge), f"--user-data-dir={self.profile}",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                "--no-first-run", "--no-default-browser-check", "--disable-background-mode",
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                "--disable-session-crashed-bubble", "--window-size=1050,800",
                f"--app={USAGE_URL}"]
        if not visible:
            args.append("--start-minimized")
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        self.port = None
        self.auto_hide = True
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                self.port = int(active_port.read_text(encoding="utf-8").splitlines()[0])
                self._targets()
                self.browser_socket = self._version()["webSocketDebuggerUrl"]
                self.browser_pid = self.process.pid
                if not visible:
                    self.hide()
                return
            except (OSError, ValueError, IndexError):
                time.sleep(0.25)
        raise ConnectionProblem("Edgeの起動待ちです。しばらくして再接続してください")

    def _targets(self):
        with self.http.open(f"http://127.0.0.1:{self.port}/json/list", timeout=4) as response:
            return json.load(response)

    def _version(self):
        with self.http.open(f"http://127.0.0.1:{self.port}/json/version", timeout=4) as response:
            return json.load(response)

    def _identify_browser(self):
        info = self._exchange(self.browser_socket, "SystemInfo.getProcessInfo", timeout=5)
        self.browser_pid = next((int(p["id"]) for p in info.get("processInfo", [])
                                 if p.get("type") == "browser"), None)

    def _target(self):
        targets = [t for t in self._targets() if t.get("type") == "page"]
        for target in targets:
            if target.get("url", "").startswith("https://chatgpt.com/"):
                return target
        raise ConnectionProblem("接続ボタンからChatGPTへのログインを完了してください", True)

    def _command(self, method, params=None):
        target = self._target()
        return self._exchange(target["webSocketDebuggerUrl"], method, params)

    def _exchange(self, socket_url, method, params=None, timeout=35):
        with closing(websocket.create_connection(socket_url, timeout=timeout,
                     suppress_origin=True, http_no_proxy=["127.0.0.1"])) as ws:
            ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                reply = json.loads(ws.recv())
                if reply.get("id") == 1:
                    if "error" in reply:
                        raise ConnectionProblem("ブラウザーとの通信を再試行しています")
                    return reply.get("result", {})
        raise ConnectionProblem("ブラウザーの応答がタイムアウトしました")

    def fetch(self):
        result = self._command("Runtime.evaluate", {
            "expression": FETCH_USAGE, "awaitPromise": True, "returnByValue": True,
            "timeout": 28000,
        })
        if "exceptionDetails" in result:
            raise ConnectionProblem("使用状況ページの準備中です")
        value = result.get("result", {}).get("value")
        if not isinstance(value, dict):
            raise ConnectionProblem("使用状況ページを読み込み中です")
        error = value.get("error")
        if error in ("login", "challenge"):
            raise ConnectionProblem("接続ボタンを押し、ChatGPTにログインしてください", True)
        if error:
            raise ConnectionProblem("通信できません。ネット接続を確認してください")
        usage = value.get("usage") or {}
        status = usage.get("status")
        if status in (401, 403):
            raise ConnectionProblem("接続画面でログイン・本人確認を完了してください", True)
        if status != 200 or not isinstance(usage.get("data"), dict):
            if status == 429:
                raise ConnectionProblem("取得回数の制限中です。自動で再試行します")
            raise ConnectionProblem(f"使用量を取得できませんでした（HTTP {status}）")
        resets = value.get("resets") or {}
        details = resets.get("data") if resets.get("status") == 200 else None
        return usage["data"], details

    def _windows(self, visible):
        if self.browser_pid is None:
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

        @callback_type
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.browser_pid:
                # Avoid revealing Edge's auxiliary tool/IPC windows.
                name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, name, len(name))
                if name.value == "Chrome_WidgetWin_1":
                    user32.ShowWindow(hwnd, 9 if visible else 0)
                    if visible:
                        user32.SetForegroundWindow(hwnd)
            return True

        user32.EnumWindows(visit, 0)

    def show(self):
        self._windows(True)
        self.auto_hide = True

    def hide(self):
        self._windows(False)

    def ready(self):
        if self.auto_hide:
            self.hide()
            self.auto_hide = False

    def close(self):
        try:
            if self.browser_socket:
                self._exchange(self.browser_socket, "Browser.close", timeout=5)
        except Exception:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        if self.process:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.port = None
        self.browser_pid = None
        self.browser_socket = None

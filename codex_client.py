"""Read-only usage client for the official Codex app-server protocol.

OAuth runs in the default, unmodified browser. The official binary owns token
refresh and stores credentials in Windows Credential Manager, scoped by CODEX_HOME.
No browser debugging, injected JavaScript, cookie copying, or model turns are used.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import webbrowser

from errors import ConnectionProblem


USAGE_URL = "https://chatgpt.com/settings/usage?tab=overview"


def runtime_path():
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    candidates = [root / "codex.exe", root / "dist/codex.exe",
                  root / "runtime/node_modules/@openai/codex-win32-x64/vendor"
                  / "x86_64-pc-windows-msvc/bin/codex.exe"]
    return next((path for path in candidates if path.is_file()), None)


def normalize_limits(response):
    buckets = response.get("rateLimitsByLimitId") or {}
    limits = buckets.get("codex") or response.get("rateLimits")
    if not isinstance(limits, dict):
        raise ConnectionProblem("Codexの使用量データを確認できませんでした")
    windows = {}
    for source, target, default in (("primary", "primary_window", 300),
                                    ("secondary", "secondary_window", 10080)):
        item = limits.get(source)
        if not isinstance(item, dict):
            continue
        minutes = item.get("windowDurationMins")
        windows[target] = {
            "used_percent": item.get("usedPercent"),
            "reset_at": item.get("resetsAt"),
            "limit_window_seconds": (default if minutes is None else minutes) * 60,
        }
    payload = {"plan_type": limits.get("planType"), "rate_limit": windows}
    summary = response.get("rateLimitResetCredits")
    details = None
    if isinstance(summary, dict):
        payload["rate_limit_reset_credits"] = {"available_count": summary.get("availableCount")}
        details = {"available_count": summary.get("availableCount"), "credits": []}
        for credit in summary.get("credits") or []:
            if not isinstance(credit, dict):
                continue
            expires = credit.get("expiresAt")
            try:
                expires = datetime.fromtimestamp(expires, timezone.utc).isoformat() if expires else None
            except (ValueError, TypeError, OverflowError, OSError):
                expires = None
            details["credits"].append({"status": credit.get("status"), "expires_at": expires})
    return payload, details


class CodexConnection:
    def __init__(self, home: Path, on_change=None, executable=None):
        self.home = home
        self.executable = executable
        self.on_change = on_change or (lambda: None)
        self.process = None
        self.login_in_progress = False
        self.login_id = None
        self.auth_url = None
        self.login_failed = False
        self._start_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._login_lock = threading.Lock()
        self._pending = {}
        self._sequence = 0

    def start(self):
        with self._start_lock:
            if self.process and self.process.poll() is None:
                return
            executable = self.executable or runtime_path()
            if executable is None:
                raise ConnectionProblem("Codex公式コンポーネントがありません。アプリを再インストールしてください")
            self.login_in_progress = False
            self.login_id = None
            self.auth_url = None
            self.home.mkdir(parents=True, exist_ok=True)
            environment = dict(os.environ, CODEX_HOME=str(self.home))
            process = subprocess.Popen([
                str(executable), "-c", 'cli_auth_credentials_store="keyring"',
                "app-server", "--stdio",
            ], cwd=self.home, env=environment, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
            self.process = process
            threading.Thread(target=self._read, args=(process,), name="codex-rpc", daemon=True).start()
            try:
                self.request("initialize", {
                    "clientInfo": {"name": "codex_usage_widget", "title": "Codex Usage", "version": "1.2.0"},
                    "capabilities": {"experimentalApi": False},
                }, timeout=25)
                self._send({"method": "initialized", "params": {}})
            except Exception:
                self.close()
                raise

    def _send(self, message):
        with self._write_lock:
            if not self.process or self.process.poll() is not None:
                raise ConnectionProblem("Codexへの接続を再試行しています")
            try:
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                raise ConnectionProblem("Codexへの接続が切れました。自動で再接続します") from None

    def request(self, method, params=None, timeout=35):
        result_queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._sequence += 1
            request_id = self._sequence
            self._pending[request_id] = result_queue
        try:
            self._send({"id": request_id, "method": method, "params": params or {}})
            try:
                response = result_queue.get(timeout=timeout)
            except queue.Empty:
                raise ConnectionProblem("Codexの応答を待っています。自動で再試行します") from None
            if "error" in response:
                # Never include raw RPC replies or authentication URLs in logs.
                raise ConnectionProblem("Codexから情報を取得できませんでした。「接続」から認証状態を確認してください")
            return response.get("result", {})
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _read(self, process):
        try:
            for line in process.stdout:
                if self.process is not process:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if "id" in message and ("result" in message or "error" in message):
                    with self._pending_lock:
                        destination = self._pending.get(message["id"])
                        if destination and destination.empty():
                            destination.put_nowait(message)
                elif message.get("method") == "account/login/completed":
                    self.login_in_progress = False
                    self.login_failed = not message.get("params", {}).get("success", False)
                    self.login_id = None
                    self.auth_url = None
                    self.on_change()
                elif message.get("method") == "account/updated":
                    self.on_change()
        except (OSError, ValueError):
            pass
        finally:
            if self.process is process:
                with self._pending_lock:
                    for destination in self._pending.values():
                        if destination.empty():
                            destination.put_nowait({"error": {"code": "disconnected"}})

    def open_login(self):
        self.start()
        with self._login_lock:
            if not self.login_in_progress or not self.auth_url:
                result = self.request("account/login/start", {"type": "chatgpt"})
                address = result.get("authUrl", "")
                parsed = urlsplit(address)
                if parsed.scheme != "https" or parsed.hostname not in (
                    "auth.openai.com", "auth0.openai.com", "chatgpt.com"
                ):
                    raise ConnectionProblem("公式ログインページのURLを確認できませんでした")
                self.login_id = result.get("loginId")
                self.auth_url = address
                self.login_failed = False
                self.login_in_progress = True
            if not webbrowser.open(self.auth_url, new=1):
                raise ConnectionProblem("既定のブラウザーを開けませんでした。Windowsの既定ブラウザー設定を確認してください")

    def fetch(self):
        # During authentication we do not inspect, refresh, or inject anything
        # into the browser, and do not make background usage requests.
        if self.login_in_progress:
            raise ConnectionProblem("通常のブラウザーでログインを完了してください", True)
        account = self.request("account/read", {"refreshToken": False})
        if not account.get("account"):
            message = "認証が完了しませんでした。もう一度「接続」を押してください" if self.login_failed else "「接続 / ログイン」からCodexにログインしてください"
            raise ConnectionProblem(message, True)
        if account["account"].get("type") != "chatgpt":
            raise ConnectionProblem("ChatGPTアカウントでCodexにログインしてください", True)
        response = self.request("account/rateLimits/read")
        return normalize_limits(response)

    def close(self):
        with self._start_lock:
            process = self.process
            if process:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                process.stdout.close()
            self.login_in_progress = False
            self.login_id = None
            self.auth_url = None

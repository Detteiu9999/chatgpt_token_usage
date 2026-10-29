"""Live official-runtime handshake with an isolated account; never print auth URLs."""

import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from codex_client import CodexConnection
from errors import ConnectionProblem


def main():
    temporary_root = Path(os.environ["LOCALAPPDATA"]) / "Temp/opencode"
    with tempfile.TemporaryDirectory(prefix="codex-rpc-", dir=temporary_root,
                                     ignore_cleanup_errors=True) as directory:
        client = CodexConnection(Path(directory))
        try:
            client.start()
            account = client.request("account/read", {"refreshToken": False})
            assert account.get("account") is None
            with patch("codex_client.webbrowser.open", return_value=True) as browser:
                client.open_login()
                assert browser.call_count == 1
                assert urlsplit(browser.call_args.args[0]).hostname == "auth.openai.com"
                assert client.login_in_progress
                try:
                    client.fetch()
                    raise AssertionError("Usage should pause during authentication")
                except ConnectionProblem as exc:
                    assert exc.needs_login
            client.request("account/login/cancel", {"loginId": client.login_id})
            print("Official Codex runtime: initialize, keyring configuration, account read, OAuth start/cancel verified")
            print("Normal default browser selected; browser automation and usage polling during login: disabled")
        finally:
            client.close()


if __name__ == "__main__":
    main()

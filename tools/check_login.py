"""Exercise the real Tk login button without automating a browser challenge."""

from pathlib import Path
import sys
import threading
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import Application


def main():
    app = Application(smoke_test=True)
    app.root.after_cancel(app.smoke_after_id)
    failures = []
    login_started = threading.Event()
    app.client = Mock(login_in_progress=True)
    app.client.open_login.side_effect = login_started.set

    def failed(exc_type, exc, traceback):
        failures.append(exc)
        app.quit()

    app.root.report_callback_exception = failed

    def click():
        app.login_button.invoke()
        app.root.after(650, check)

    def check():
        assert login_started.is_set(), "Login button did not start authentication"
        assert app.login_open, "Login state was not reflected in the UI"
        assert not app.login_pending
        print("Real Tk button: independent official login request and UI state verified")
        app.quit()

    app.root.after(150, click)
    app.run()
    if failures:
        raise failures[0]


if __name__ == "__main__":
    main()

import queue
import threading
import unittest
from unittest.mock import Mock

from app import Application


class LoginTests(unittest.TestCase):
    def test_login_button_is_not_blocked_by_a_pending_usage_request(self):
        app = Application.__new__(Application)
        app.stop = threading.Event()
        app.wake = threading.Event()
        app.messages = queue.Queue()
        app.config = {"interval": 60}
        app.client = Mock()
        app.client.login_in_progress = False
        app.status = Mock()
        app.login_thread = None
        app.error = ""
        fetch_busy = threading.Event()
        release_fetch = threading.Event()
        login_opened = threading.Event()

        def fetch():
            fetch_busy.set()
            release_fetch.wait(5)
            return {"plan_type": "plus"}, None

        app.client.fetch.side_effect = fetch
        app.client.open_login.side_effect = login_opened.set
        worker = threading.Thread(target=app.worker)
        worker.start()
        try:
            self.assertTrue(fetch_busy.wait(2))
            app.connect()
            self.assertTrue(login_opened.wait(1), "Login waited for the blocked usage request")
            self.assertFalse(release_fetch.is_set())
        finally:
            app.stop.set()
            app.wake.set()
            release_fetch.set()
            worker.join(5)
            if app.login_thread:
                app.login_thread.join(5)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from codex_client import CodexConnection, normalize_limits
from errors import ConnectionProblem
from usage import parse_usage


class CodexClientTests(unittest.TestCase):
    def setUp(self):
        self.client = CodexConnection(Path("unused-test-auth"))
        self.client.start = Mock()
        self.client.request = Mock()

    @patch("codex_client.webbrowser.open", return_value=True)
    def test_login_opens_official_oauth_in_normal_browser_and_reuses_pending_flow(self, browser):
        self.client.request.return_value = {"type": "chatgpt", "loginId": "test-login",
                                            "authUrl": "https://auth.openai.com/oauth/authorize?state=test"}
        self.client.open_login()
        self.client.open_login()
        self.assertEqual(self.client.request.call_count, 1)
        self.assertEqual(browser.call_count, 2)
        self.assertTrue(self.client.login_in_progress)

    def test_no_usage_or_session_requests_during_browser_authentication(self):
        self.client.login_in_progress = True
        with self.assertRaises(ConnectionProblem) as raised:
            self.client.fetch()
        self.assertTrue(raised.exception.needs_login)
        self.client.request.assert_not_called()

    @patch("codex_client.webbrowser.open")
    def test_unexpected_login_destination_is_not_opened(self, browser):
        self.client.request.return_value = {"authUrl": "https://example.com/login"}
        with self.assertRaises(ConnectionProblem):
            self.client.open_login()
        browser.assert_not_called()

    def test_signed_out_state_requests_manual_login_without_opening_any_browser(self):
        self.client.request.return_value = {"account": None}
        with self.assertRaises(ConnectionProblem) as raised:
            self.client.fetch()
        self.assertTrue(raised.exception.needs_login)
        self.client.request.assert_called_once_with("account/read", {"refreshToken": False})

    def test_official_rpc_limits_and_reset_tickets_preserve_widget_contract(self):
        payload, details = normalize_limits({
            "rateLimits": {"primary": {"usedPercent": 99, "windowDurationMins": 300}},
            "rateLimitsByLimitId": {"codex": {
                "planType": "plus",
                "primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": 2000000000},
                "secondary": {"usedPercent": 61, "windowDurationMins": 10080, "resetsAt": 2000600000},
            }},
            "rateLimitResetCredits": {"availableCount": 2, "credits": [
                {"status": "available", "expiresAt": 2000800000},
            ]},
        })
        result = parse_usage(payload, details, now=1900000000)
        self.assertEqual(result.five_hour.remaining, 75)
        self.assertEqual(result.weekly.remaining, 39)
        self.assertEqual(result.reset_count, 2)
        self.assertEqual(result.next_expiry, 2000800000)

    def test_missing_reset_information_remains_unknown(self):
        payload, details = normalize_limits({"rateLimits": {"planType": "plus"}})
        self.assertIsNone(parse_usage(payload, details).reset_count)


if __name__ == "__main__":
    unittest.main()

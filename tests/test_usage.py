import unittest

from usage import parse_usage


class UsageContractTests(unittest.TestCase):
    def test_backend_window_duration_takes_precedence_over_position(self):
        result = parse_usage({"plan_type": "plus", "rate_limit": {
            "primary_window": {"used_percent": 80, "limit_window_seconds": 604800,
                               "reset_at": 2000000000},
            "secondary_window": {"used_percent": 25, "limit_window_seconds": 18000,
                                 "reset_after_seconds": 60},
        }}, now=1000)
        self.assertEqual(result.weekly.remaining, 20)
        self.assertEqual(result.five_hour.remaining, 75)
        self.assertEqual(result.five_hour.resets_at, 1060)

    def test_unknown_does_not_look_like_zero_or_full_remaining(self):
        result = parse_usage({"plan_type": "plus", "rate_limit": None})
        self.assertIsNone(result.five_hour)
        self.assertIsNone(result.weekly)
        self.assertIsNone(result.reset_count)

    def test_reset_details_override_summary_and_only_available_future_expiry_counts(self):
        result = parse_usage({"rate_limit_reset_credits": {"available_count": 9}}, {
            "available_count": 0,
            "credits": [
                {"status": "redeemed", "expires_at": "2030-01-01T00:00:00Z"},
                {"status": "available", "expires_at": "2000-01-01T00:00:00Z"},
                {"status": "available", "expires_at": "2031-01-01T00:00:00Z"},
                {"status": "available", "expires_at": None},
            ],
        }, now=1800000000)
        self.assertEqual(result.reset_count, 0)
        self.assertEqual(result.next_expiry, 1924992000)

    def test_failed_detail_endpoint_keeps_summary(self):
        result = parse_usage({"rate_limit_reset_credits": {"available_count": 3}})
        self.assertEqual(result.reset_count, 3)

    def test_malformed_values_are_unknown(self):
        for used in (True, "30", float("nan"), -1):
            with self.subTest(used=used):
                result = parse_usage({"rate_limit": {"primary_window": {"used_percent": used}},
                                      "rate_limit_reset_credits": {"available_count": True}})
                self.assertIsNone(result.five_hour)
                self.assertIsNone(result.reset_count)

    def test_unrecognized_duration_is_not_mislabelled(self):
        result = parse_usage({"rate_limit": {"primary_window": {
            "used_percent": 30, "limit_window_seconds": 3600,
        }}})
        self.assertIsNone(result.five_hour)

    def test_non_usage_response_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_usage({"error": "unauthorized"})


if __name__ == "__main__":
    unittest.main()

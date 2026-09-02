import unittest

from visitor_counter import anonymous_visitor_id, normalize_visitor_id


class VisitorCounterTests(unittest.TestCase):
    def test_valid_uuid_is_normalized(self):
        value = "550E8400-E29B-41D4-A716-446655440000"
        self.assertEqual(
            normalize_visitor_id(value),
            "550e8400-e29b-41d4-a716-446655440000",
        )

    def test_invalid_identifier_is_rejected(self):
        for value in (None, "", "not-a-uuid", "<script>"):
            self.assertIsNone(normalize_visitor_id(value))

    def test_anonymous_identity_is_stable_across_header_casing(self):
        first = anonymous_visitor_id(
            {
                "X-Forwarded-For": "203.0.113.10, 10.0.0.1",
                "User-Agent": "Example Browser",
                "Accept-Language": "en-US",
            },
            secret="test-secret",
        )
        second = anonymous_visitor_id(
            {
                "x-forwarded-for": "203.0.113.10, 10.0.0.2",
                "user-agent": "Example Browser",
                "accept-language": "en-US",
            },
            secret="test-secret",
        )
        self.assertEqual(first, second)

    def test_anonymous_identity_changes_for_a_different_visitor(self):
        first = anonymous_visitor_id(
            {"x-forwarded-for": "203.0.113.10", "user-agent": "Browser"},
            secret="test-secret",
        )
        second = anonymous_visitor_id(
            {"x-forwarded-for": "203.0.113.11", "user-agent": "Browser"},
            secret="test-secret",
        )
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
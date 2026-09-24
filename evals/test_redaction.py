import unittest

from redaction import mask_sensitive


class RedactionTests(unittest.TestCase):
    def test_masks_email_and_bearer_token(self):
        value = "Contact Pavel@example.com with Bearer abc.def-123"
        masked = mask_sensitive(value)
        self.assertNotIn("Pavel@example.com", masked)
        self.assertNotIn("abc.def-123", masked)
        self.assertIn("[EMAIL_MASKED]", masked)
        self.assertIn("Bearer [MASKED]", masked)

    def test_masks_credentials_and_url_secrets(self):
        value = "password=NewPass123 token:secret-value https://example.test/reset?token=abc"
        masked = mask_sensitive(value)
        self.assertNotIn("NewPass123", masked)
        self.assertNotIn("secret-value", masked)
        self.assertNotIn("?token=abc", masked)
        self.assertEqual(masked.count("[MASKED]"), 3)

    def test_preserves_normal_qa_text(self):
        value = "Ссылка действует 30 минут и используется только один раз."
        self.assertEqual(mask_sensitive(value), value)


if __name__ == "__main__":
    unittest.main()

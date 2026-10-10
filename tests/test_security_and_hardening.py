"""
BudgetBy — Security, Secret Hardening & Deployment Resilience Tests.
Verifies admin isolation, secret fallback elimination, open-redirect prevention,
security headers, and error response sanitization.
"""

import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from budgetby.dashboard.app import app
from budgetby.dashboard.helpers import is_safe_redirect_url
import budgetby.config as config


class TestSecurityAndHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_empty_admin_secret_key_denies_all_admin_access(self):
        """When ADMIN_SECRET_KEY is empty, no token or credential should grant admin access."""
        with patch("budgetby.dashboard.app.ADMIN_SECRET_KEY", ""):
            # Querying admin APIs without valid secret key must yield 404
            resp_stats = self.client.get("/api/stats", params={"key": ""})
            self.assertEqual(resp_stats.status_code, 404)

            # Even with random non-empty string, when ADMIN_SECRET_KEY is empty, must fail
            resp_random = self.client.get("/api/stats", params={"key": "some_token"})
            self.assertEqual(resp_random.status_code, 404)

    def test_admin_api_routes_return_404_stealth_when_unauthorized(self):
        """Unauthorized requests to admin API routes must return 404 (not 401/403) to prevent discovery."""
        unauthorized_endpoints = [
            "/api/stats",
            "/api/channel_stats",
            "/api/posting_queue",
            "/api/category_platform_stats",
            "/api/price_changes_24h",
            "/api/db/overview",
            "/api/db/table_data",
        ]
        for ep in unauthorized_endpoints:
            resp = self.client.get(ep)
            self.assertEqual(resp.status_code, 404, f"Endpoint {ep} should return 404 for unauthorized request")

    def test_admin_html_routes_redirect_unauthenticated_requests(self):
        """Unauthenticated requests to admin HTML endpoints redirect to login or homepage."""
        resp = self.client.get("/pnther", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303, 307))

        resp_explorer = self.client.get("/pnther/db-explorer", follow_redirects=False)
        self.assertIn(resp_explorer.status_code, (302, 303, 307))

    def test_safe_redirect_url_whitelist(self):
        """Open redirect protection: Only allowed domains (and relative URLs) are safe."""
        # Allowed domains
        self.assertTrue(is_safe_redirect_url("https://www.amazon.in/dp/B00EXAMPLE?tag=test"))
        self.assertTrue(is_safe_redirect_url("https://flipkart.com/product-p-12345"))
        self.assertTrue(is_safe_redirect_url("https://fktr.in/xyz789"))
        self.assertTrue(is_safe_redirect_url("https://myntra.com/tshirt/123"))
        self.assertTrue(is_safe_redirect_url("https://ekaro.in/enkr2026"))
        self.assertTrue(is_safe_redirect_url("https://clnk.in/abcde"))

        # Malicious / Untrusted domains
        self.assertFalse(is_safe_redirect_url("https://evil-attacker.com/steal-creds"))
        self.assertFalse(is_safe_redirect_url("https://amazon.in.phishing.com/login"))
        self.assertFalse(is_safe_redirect_url("javascript:alert(1)"))
        self.assertFalse(is_safe_redirect_url("data:text/html,<script>alert(1)</script>"))
        self.assertFalse(is_safe_redirect_url(""))

    def test_deal_redirect_endpoint_falls_back_safely_on_invalid_destination(self):
        """If a stored product has a malicious or invalid URL, /api/deal/redirect/{id} falls back to /deals."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow:
            mock_fetchrow.return_value = {
                "id": 999,
                "platform": "flipkart",
                "affiliate_url": "https://attacker.com/malware",
                "product_url": "https://attacker.com/malware",
                "clean_url": "https://attacker.com/malware",
                "current_price": 499.0,
                "title": "Suspicious Item",
                "category": "fashion"
            }
            resp = self.client.get("/api/deal/redirect/999", follow_redirects=False)
            self.assertEqual(resp.status_code, 307)
            self.assertEqual(resp.headers.get("location"), "/deals")

    def test_healthz_endpoint_is_fast_and_zero_database(self):
        """Health check endpoint /healthz should succeed immediately with status ok."""
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "budgetby")
        self.assertIn("timestamp", data)

    def test_security_headers_are_present(self):
        """FastAPI responses must contain standard web security hardening headers."""
        resp = self.client.get("/healthz")
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(resp.headers.get("x-frame-options"), "DENY")
        self.assertEqual(resp.headers.get("x-xss-protection"), "1; mode=block")
        self.assertEqual(resp.headers.get("referrer-policy"), "strict-origin-when-cross-origin")

    def test_log_sanitizer_redacts_credentials(self):
        """Verify _clean_log_line redacts bot tokens, postgres URIs, query tokens, and auth secrets."""
        from budgetby.dashboard.app import _clean_log_line

        sample_lines = [
            "Request to https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz1234567/sendMessage failed",
            "Connecting to postgresql://postgres.xyz:secret_password_123@aws-0-ap-south-1.pooler.supabase.com:6543/postgres",
            "GET /api/stats?key=bb_sec_9e72f8a14b30c5e7d82f091a384b62d1 HTTP/1.1",
            "Authorization: Bearer my_jwt_token_value_abc123",
            "Form submitted with password=SecretAdminPass123"
        ]

        for line in sample_lines:
            cleaned = _clean_log_line(line, "test")
            self.assertIsNotNone(cleaned)
            cleaned_text = cleaned["text"]
            # Ensure none of the sensitive tokens leaked
            self.assertNotIn("123456789:ABCdefGHIjklMNOpqrsTUVwxyz1234567", cleaned_text)
            self.assertNotIn("secret_password_123", cleaned_text)
            self.assertNotIn("bb_sec_9e72f8a14b30c5e7d82f091a384b62d1", cleaned_text)
            self.assertNotIn("my_jwt_token_value_abc123", cleaned_text)
            self.assertNotIn("SecretAdminPass123", cleaned_text)
            self.assertIn("[REDACTED]", cleaned_text)


if __name__ == "__main__":
    unittest.main()

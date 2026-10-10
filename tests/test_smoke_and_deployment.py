"""
Production Smoke Tests and Deployment Verification for BudgetBy.
Verifies all public routes, SSR pages, redirect endpoints, and deployment configurations.
"""

import unittest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from budgetby.dashboard.app import app, ram_cache

class TestSmokeAndDeployment(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.fake_db_deal = {
            "deal_id": 10, "product_id": 100, "title": "Test Wireless Headphones",
            "platform": "amazon", "category": "electronics", "product_url": "https://amazon.in/dp/B001",
            "affiliate_url": "https://amazon.in/dp/B001?tag=dealpulse", "image_url": "https://img.com/1.jpg",
            "rating": 4.5, "review_count": 500, "current_price": 799.0, "mrp": 1999.0,
            "previous_price": 1499.0, "min_30d": 799.0, "all_time_low": 799.0,
            "in_stock": True, "status": "ACTIVE", "last_checked": None,
            "is_verified": True, "badge": "LOOT", "deal_score": 92.0,
            "deal_time": None, "relevance_score": 0, "drop_pct": 46.7, "drop_amount": 700.0,
            "last_price_change": None, "is_verified_deal": True
        }
        ram_cache.clear()

    def test_public_pages_smoke(self):
        """Smoke test all primary public web pages for 200 OK and expected HTML content."""
        routes = [
            ("/", "Shop by Category"),
            ("/deals", "All Deals"),
            ("/drops", "Price Drops"),
            ("/price-drops", "Price Drops"),
            ("/atl", "All-Time Low"),
            ("/all-time-lows", "All-Time Low"),
            ("/stores", "Stores"),
            ("/stores/amazon", "Amazon"),
            ("/stores/flipkart", "Flipkart"),
            ("/about", "About"),
            ("/healthz", "ok"),
        ]

        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.fake_db_deal]
            mock_fetchrow.return_value = {
                "total_products": 100000, "total_deals": 14000, "deals_today": 1500,
                "drops_today": 30000, "latest_deal_time": None, "by_platform_json": {}
            }
            mock_fetchval.return_value = 100

            for path, expected_str in routes:
                ram_cache.clear()
                res = self.client.get(path)
                self.assertEqual(res.status_code, 200, f"Failed on {path}")
                self.assertIn(expected_str, res.text, f"Expected substring '{expected_str}' not in {path}")

    def test_ssr_hydration_json_payloads(self):
        """Verify embedded JSON scripts are present in HTML for zero-fetch JS hydration."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.fake_db_deal]
            mock_fetchrow.return_value = {
                "total_products": 100000, "total_deals": 14000, "deals_today": 1500,
                "drops_today": 30000, "latest_deal_time": None, "by_platform_json": {}
            }
            mock_fetchval.return_value = 100

            # Deals page should contain initial-deals-data script
            res_deals = self.client.get("/deals")
            self.assertEqual(res_deals.status_code, 200)
            self.assertIn('id="initial-deals-data"', res_deals.text)

            # Drops page should contain initial-drops-data script
            res_drops = self.client.get("/drops")
            self.assertEqual(res_drops.status_code, 200)
            self.assertIn('id="initial-drops-data"', res_drops.text)

            # ATL page should contain initial-atl-data script
            res_atl = self.client.get("/atl")
            self.assertEqual(res_atl.status_code, 200)
            self.assertIn('id="initial-atl-data"', res_atl.text)

    def test_deal_redirect_endpoint(self):
        """Verify deal redirect resolves safe retailer destination with affiliate tracking."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow:
            mock_fetchrow.return_value = {
                "id": 100,
                "platform": "amazon",
                "product_url": "https://www.amazon.in/dp/B08N5WRWNW",
                "affiliate_url": "https://www.amazon.in/dp/B08N5WRWNW?tag=dealpulse-21"
            }

            res = self.client.get("/api/deal/redirect/100", follow_redirects=False)
            self.assertIn(res.status_code, (302, 307))
            location = res.headers.get("location") or res.headers.get("Location")
            self.assertIsNotNone(location)
            self.assertIn("amazon.in", location)

    def test_deployment_configuration_separation(self):
        """Verify deployment configurations enforce separation of web vs local engine."""
        import pathlib
        import yaml

        # 1. Verify render.yaml
        render_file = pathlib.Path("render.yaml")
        self.assertTrue(render_file.exists())
        with open(render_file, "r", encoding="utf-8") as f:
            render_cfg = yaml.safe_load(f)
            services = render_cfg.get("services", [])
            self.assertEqual(len(services), 1)
            web_svc = services[0]
            self.assertEqual(web_svc.get("type"), "web")
            # Must run uvicorn dashboard directly, NOT python -m budgetby.main
            self.assertIn("uvicorn budgetby.dashboard.app:app", web_svc.get("startCommand"))
            self.assertEqual(web_svc.get("healthCheckPath"), "/healthz")

        # 2. Verify Procfile
        procfile = pathlib.Path("Procfile")
        self.assertTrue(procfile.exists())
        with open(procfile, "r", encoding="utf-8") as f:
            proc_content = f.read()
            self.assertIn("uvicorn budgetby.dashboard.app:app", proc_content)

if __name__ == "__main__":
    unittest.main()

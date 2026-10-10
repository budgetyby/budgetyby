"""
Tests for BudgetBy Website Speed, Frontend/API Performance, Caching, and Egress Optimization.
"""

import unittest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from budgetby.dashboard.app import app, ram_cache, coalescer

class TestWebsitePerformance(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        ram_cache.clear()

    def tearDown(self):
        self.loop.close()

    def test_pagination_bounded_limits(self):
        """Verify API enforces maximum limit cap on deals listing to prevent large DB payloads."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:
            mock_fetch.return_value = []
            mock_fetchval.return_value = 0

            # Request 45 items (within FastAPI schema <=50), should be clamped internally to 30
            response = self.client.get("/api/public/deals?limit=45")
            self.assertEqual(response.status_code, 200)

            # Check the SQL limit argument passed to database.fetch
            mock_fetch.assert_called_once()
            args, _ = mock_fetch.call_args
            self.assertIn(30, args)

    def test_cache_hit_prevents_db_query(self):
        """Verify that cache hit returns response immediately without hitting PostgreSQL."""
        fake_db_data = [{
            "deal_id": 10, "product_id": 100, "title": "Wireless Earbuds",
            "platform": "amazon", "category": "electronics", "product_url": "https://amazon.in/dp/B001",
            "affiliate_url": "https://amazon.in/dp/B001?tag=dealpulse", "image_url": "https://img.com/1.jpg",
            "rating": 4.5, "review_count": 500, "current_price": 799.0, "mrp": 1999.0,
            "previous_price": 1499.0, "min_30d": 799.0, "all_time_low": 799.0,
            "in_stock": True, "status": "ACTIVE", "last_checked": None,
            "is_verified": True, "badge": "LOOT", "deal_score": 92.0,
            "deal_time": None, "relevance_score": 0
        }]

        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:
            mock_fetch.return_value = fake_db_data
            mock_fetchval.return_value = 1

            # Request 1: Cache Miss -> 1 DB query
            res1 = self.client.get("/api/public/deals?category=electronics&limit=10")
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(mock_fetch.call_count, 1)

            # Request 2: Cache Hit -> 0 additional DB queries
            res2 = self.client.get("/api/public/deals?category=electronics&limit=10")
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(mock_fetch.call_count, 1) # Unchanged!
            self.assertEqual(res1.json()["deals"][0]["title"], res2.json()["deals"][0]["title"])

    def test_request_coalescing_concurrent_requests(self):
        """Verify concurrent requests for the same cache key are coalesced to a single DB query."""
        async def run_test():
            fake_db_data = [{
                "deal_id": 20, "product_id": 200, "title": "Smart Watch",
                "platform": "flipkart", "category": "watches", "product_url": "https://flipkart.com/p/1",
                "affiliate_url": "", "image_url": "", "rating": 4.2, "review_count": 300,
                "current_price": 999.0, "mrp": 2999.0, "previous_price": 1999.0, "min_30d": 999.0,
                "all_time_low": 999.0, "in_stock": True, "status": "ACTIVE", "last_checked": None,
                "is_verified": True, "badge": "ATL", "deal_score": 90.0,
                "deal_time": None, "relevance_score": 0
            }]

            with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
                 patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:
                
                async def slow_fetch(*args, **kwargs):
                    await asyncio.sleep(0.05)
                    return fake_db_data
                
                mock_fetch.side_effect = slow_fetch
                mock_fetchval.return_value = 1

                from budgetby.dashboard.app import get_public_deals
                from starlette.requests import Request
                
                mock_request = MagicMock(spec=Request)
                mock_request.url.path = "/api/public/deals"

                # Trigger 4 concurrent calls for identical parameters
                t1 = get_public_deals(request=mock_request, category="watches", limit=10)
                t2 = get_public_deals(request=mock_request, category="watches", limit=10)
                t3 = get_public_deals(request=mock_request, category="watches", limit=10)
                t4 = get_public_deals(request=mock_request, category="watches", limit=10)

                results = await asyncio.gather(t1, t2, t3, t4)
                
                # All 4 return identical data
                for r in results:
                    self.assertEqual(len(r["deals"]), 1)
                    self.assertEqual(r["deals"][0]["title"], "Smart Watch")

                # But database.fetch was called only ONCE due to single-flight coalescing
                self.assertEqual(mock_fetch.call_count, 1)

        self.loop.run_until_complete(run_test())

    def test_required_api_fields_preserved(self):
        """Verify all critical UI consumer fields exist in API responses."""
        fake_db_data = [{
            "deal_id": 30, "product_id": 300, "title": "Running Shoes",
            "platform": "myntra", "category": "footwear", "product_url": "https://myntra.com/1",
            "affiliate_url": "https://myntra.com/1?aff=test", "image_url": "https://img.com/shoe.jpg",
            "rating": 4.4, "review_count": 210, "current_price": 1299.0, "mrp": 2999.0,
            "previous_price": 1999.0, "min_30d": 1299.0, "all_time_low": 1299.0,
            "in_stock": True, "status": "ACTIVE", "last_checked": None,
            "is_verified": True, "badge": "HOT DEAL", "deal_score": 88.0,
            "deal_time": None, "relevance_score": 0
        }]

        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:
            mock_fetch.return_value = fake_db_data
            mock_fetchval.return_value = 1

            response = self.client.get("/api/public/deals?category=footwear&limit=5")
            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertIn("deals", data)
            self.assertIn("total_matches", data)
            self.assertIn("page", data)
            self.assertIn("total_pages", data)

            deal = data["deals"][0]
            required_keys = [
                "product_id", "title", "platform", "category", "current_price",
                "mrp", "image_url", "affiliate_url", "rating", "review_count",
                "badge", "is_verified_deal", "in_stock"
            ]
            for key in required_keys:
                self.assertIn(key, deal, f"Missing required field: {key}")

    def test_search_suggestions_lightweight_payload(self):
        """Verify search suggestions endpoint returns lightweight payload with 300s cache."""
        fake_deals = {
            "deals": [{
                "deal_id": 5, "product_id": 50, "title": "Nike Sneakers",
                "platform": "myntra", "current_price": 1999.0, "deal_price": 1999.0,
                "mrp": 3999.0, "image_url": "https://img.com/nike.jpg",
                "affiliate_url": "https://myntra.com/nike", "badge": "LOOT"
            }]
        }

        with patch("budgetby.dashboard.app.get_public_deals", new_callable=AsyncMock) as mock_get_deals:
            mock_get_deals.return_value = fake_deals

            # 1. First call -> calls get_public_deals
            res1 = self.client.get("/api/public/search-suggestions?q=nike")
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(mock_get_deals.call_count, 1)
            self.assertEqual(len(res1.json()["suggestions"]), 1)

            # 2. Second call -> served from RAM cache (0 calls)
            res2 = self.client.get("/api/public/search-suggestions?q=nike")
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(mock_get_deals.call_count, 1)

    def test_gzip_compression_and_cache_control_headers(self):
        """Verify GZip compression middleware and HTTP Cache-Control headers."""
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)

        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow:
            mock_fetchrow.return_value = {
                "total_products": 100000, "total_deals": 14000, "deals_today": 1500,
                "drops_today": 30000, "latest_deal_time": None, "by_platform_json": {}
            }
            res = self.client.get("/api/public/stats")
            self.assertEqual(res.status_code, 200)
            self.assertIn("Cache-Control", res.headers)
            self.assertIn("public", res.headers["Cache-Control"])

if __name__ == "__main__":
    unittest.main()

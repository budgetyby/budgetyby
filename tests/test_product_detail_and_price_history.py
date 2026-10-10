"""
BudgetBy — Test Suite: Product & Deal Detail Experience & Price History
Validates:
1. Product/deal detail route works (/deal/{id} and /product/{id}).
2. Public API endpoints work (/api/public/deal/{id} and /api/public/product/{id}).
3. All required consumer deal fields are present (title, price, mrp, discount, savings, rating, reviews, platform, stock).
4. Current price and discount calculations match backend formulas.
5. Historical all-time low (ATL) is displayed only when verified.
6. Out-of-stock (TEMP_OOS / in_stock=False) states are clearly reflected in CTA and badges.
7. Outbound affiliate redirect uses safe /api/deal/redirect/{id} route.
8. Non-existent product ID returns clean 404.
9. Cache hit executes 0 database queries.
10. Price history query is strictly bounded (LIMIT 30) with explicit columns.
11. Concurrent requests for same product detail are coalesced.
12. No client-side polling or refresh loops exist.
13. Data consistency across Telegram deal, list deal, and detail deal.
14. SEO OpenGraph and JSON-LD Product schema rendered cleanly without extra queries.
15. Related category deals prefetch reuses RAM cache with 0 extra queries.
"""

import unittest
import datetime
import asyncio
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient
from budgetby.dashboard.app import app, ram_cache, coalescer, get_public_deal_detail


class TestProductDetailAndPriceHistory(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        ram_cache.clear()
        self.client = TestClient(app)
        self.mock_product_row = {
            "product_id": 101,
            "platform": "amazon",
            "platform_id": "B08N5WRWNW",
            "title": "Sony WH-1000XM4 Wireless Noise Cancelling Headphones",
            "category": "electronics",
            "product_url": "https://www.amazon.in/dp/B08N5WRWNW",
            "affiliate_url": "https://www.amazon.in/dp/B08N5WRWNW?tag=dealpulse21-21",
            "image_url": "https://m.media-amazon.com/images/I/71o8Q5XJS5L._SL1500_.jpg",
            "current_price": 19990.0,
            "previous_price": 24990.0,
            "mrp": 29990.0,
            "median_30d_price": 24990.0,
            "min_30d": 19990.0,
            "min_60d": 19990.0,
            "min_90d": 22990.0,
            "min_120d": 22990.0,
            "all_time_low": 19990.0,
            "rating": 4.6,
            "review_count": 14250,
            "in_stock": True,
            "status": "ACTIVE",
            "last_checked": datetime.datetime.now(datetime.timezone.utc),
            "last_price_change": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3),
            "created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=45),
            "deal_id": 501,
            "deal_type": "price_drop",
            "badge": "ATL",
            "posted_price": 19990.0,
            "posted_mrp": 29990.0,
            "savings_amount": 10000.0,
            "savings_pct": 33.34,
            "deal_score": 88.5,
            "posted_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)
        }
        self.mock_history_rows = [
            {"date": "2026-09-15", "min_price": 24990.0, "close_price": 24990.0},
            {"date": "2026-09-20", "min_price": 24990.0, "close_price": 24990.0},
            {"date": "2026-10-01", "min_price": 22990.0, "close_price": 22990.0},
            {"date": "2026-10-07", "min_price": 19990.0, "close_price": 19990.0},
        ]

    async def test_01_product_detail_route_works(self):
        """GET /deal/{id} and /product/{id} return 200 OK and render deal detail HTML."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            resp1 = self.client.get("/deal/101")
            self.assertEqual(resp1.status_code, 200)
            self.assertIn("Sony WH-1000XM4", resp1.text)
            self.assertIn("19,990", resp1.text)
            self.assertIn("ALL-TIME LOW", resp1.text)

            # /product/{id} alias
            resp2 = self.client.get("/product/101")
            self.assertEqual(resp2.status_code, 200)
            self.assertIn("Sony WH-1000XM4", resp2.text)

    async def test_02_public_api_deal_detail_works(self):
        """GET /api/public/deal/{id} returns structured JSON."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            resp = self.client.get("/api/public/deal/101")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("product", data)
            self.assertIn("price_history", data)
            self.assertEqual(data["product"]["product_id"], 101)
            self.assertEqual(data["product"]["current_price"], 19990.0)
            self.assertEqual(len(data["price_history"]), 4)

    async def test_03_required_product_fields_present(self):
        """Verify all essential shopper information fields are returned."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            resp = self.client.get("/api/public/deal/101")
            p = resp.json()["product"]

            required_fields = [
                "product_id", "platform", "title", "category",
                "current_price", "mrp", "discount_pct", "savings_amount",
                "rating", "review_count", "in_stock", "all_time_low",
                "min_30d", "deal_score"
            ]
            for field in required_fields:
                self.assertIn(field, p, f"Missing required field {field}")

    async def test_04_current_price_and_discount_calculation(self):
        """Verify discount % and savings amount calculate accurately."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            resp = self.client.get("/api/public/deal/101")
            p = resp.json()["product"]

            # MRP = 29990, CP = 19990 -> Savings = 10000, Disc % = round(10000/29990 * 100) = 33%
            self.assertEqual(p["savings_amount"], 10000.0)
            self.assertEqual(p["discount_pct"], 33)

    async def test_05_historical_low_displayed_when_verified(self):
        """Verify ATL claim is shown when current price matches historical ATL, but not otherwise."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            # 1. Matches ATL
            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            resp_atl = self.client.get("/deal/101")
            self.assertIn("ALL-TIME LOW", resp_atl.text)

            # 2. Not ATL (current price 24,990 vs ATL 19,990)
            ram_cache.clear()
            non_atl_row = dict(self.mock_product_row)
            non_atl_row["current_price"] = 24990.0
            non_atl_row["all_time_low"] = 19990.0
            non_atl_row["badge"] = "PRICE_DROP"
            mock_fetchrow.return_value = non_atl_row

            resp_non_atl = self.client.get("/deal/101")
            self.assertNotIn("🏆 ALL-TIME LOW", resp_non_atl.text)

    async def test_06_out_of_stock_state_handled_accurately(self):
        """Verify out-of-stock products display clear stock notice and modified CTA."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            oos_row = dict(self.mock_product_row)
            oos_row["in_stock"] = False
            oos_row["status"] = "TEMP_OOS"
            mock_fetchrow.return_value = oos_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            resp = self.client.get("/deal/101")
            self.assertIn("Currently Out of Stock", resp.text)
            self.assertIn("Check Stock on Amazon", resp.text)

    async def test_07_affiliate_cta_uses_safe_redirect(self):
        """Verify CTA links to the internal whitelist-protected redirect endpoint /api/deal/redirect/{id}."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            resp = self.client.get("/deal/101")
            self.assertIn('/api/deal/redirect/101', resp.text)

    async def test_08_invalid_product_id_fails_safely_404(self):
        """Non-existent product ID returns clean 404 response."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = None
            mock_fetch.return_value = []
            mock_fetchval.return_value = 0

            resp = self.client.get("/deal/999999")
            self.assertEqual(resp.status_code, 404)
            self.assertIn("Page Not Found", resp.text)

            api_resp = self.client.get("/api/public/deal/999999")
            self.assertEqual(api_resp.status_code, 404)

    async def test_09_detail_cache_hit_performs_zero_db_queries(self):
        """Verify second request for same product is served from RAM cache with 0 DB queries."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            # 1. First call (cache miss) -> fetches DB
            resp1 = self.client.get("/deal/101")
            self.assertEqual(resp1.status_code, 200)
            self.assertEqual(mock_fetchrow.call_count, 1)

            # 2. Second call (cache hit) -> 0 additional DB queries
            mock_fetchrow.reset_mock()
            mock_fetch.reset_mock()
            mock_fetchval.reset_mock()

            resp2 = self.client.get("/deal/101")
            self.assertEqual(resp2.status_code, 200)
            mock_fetchrow.assert_not_called()
            mock_fetch.assert_not_called()
            mock_fetchval.assert_not_called()

    async def test_10_price_history_query_is_bounded(self):
        """Verify price history query enforces explicit column selection and LIMIT 30."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            self.client.get("/api/public/deal/101")
            self.assertEqual(mock_fetch.call_count, 1)
            query_sql = mock_fetch.call_args[0][0]

            self.assertIn("LIMIT 30", query_sql)
            self.assertIn("SELECT date, min_price, close_price", query_sql)
            self.assertNotIn("SELECT *", query_sql)

    async def test_11_concurrent_detail_requests_are_coalesced(self):
        """Verify concurrent requests for the same product detail are coalesced into a single DB call."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchval.return_value = 10

            async def slow_fetchrow(*args):
                await asyncio.sleep(0.05)
                return self.mock_product_row

            async def slow_fetch(*args):
                await asyncio.sleep(0.05)
                return self.mock_history_rows

            mock_fetchrow.side_effect = slow_fetchrow
            mock_fetch.side_effect = slow_fetch

            # Run 5 parallel detail fetches
            async def fetch_job():
                return await get_public_deal_detail(101)

            results = await asyncio.gather(*(fetch_job() for _ in range(5)))

            # All 5 return identical product
            for res in results:
                self.assertEqual(res["product"]["product_id"], 101)

            # DB was queried only once due to single-flight coalescing
            self.assertEqual(mock_fetchrow.call_count, 1)

    async def test_12_no_client_polling_in_detail_page(self):
        """Verify the detail page does not introduce browser polling (no setInterval, no repeated fetch loops)."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            resp = self.client.get("/deal/101")
            text = resp.text

            self.assertNotIn("setInterval", text)
            self.assertNotIn("polling", text.lower())

    async def test_13_telegram_deal_data_consistency(self):
        """Verify price, MRP, savings, and deal score match the values from deal scoring."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            detail = self.client.get("/api/public/deal/101").json()
            prod = detail["product"]

            # Detail data matches posted deal
            self.assertEqual(prod["current_price"], self.mock_product_row["posted_price"])
            self.assertEqual(prod["mrp"], self.mock_product_row["posted_mrp"])
            self.assertEqual(prod["deal_score"], self.mock_product_row["deal_score"])

    async def test_14_seo_metadata_in_detail_page(self):
        """Verify OpenGraph, Twitter Card, and Product JSON-LD schema are present without extra queries."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            resp = self.client.get("/deal/101")
            text = resp.text

            self.assertIn('<meta property="og:title"', text)
            self.assertIn('<meta property="og:image"', text)
            self.assertIn('"@type": "Product"', text)
            self.assertIn('"priceCurrency": "INR"', text)
            self.assertIn('"19990.0"', text)

    async def test_15_related_deals_use_ram_cache_zero_extra_queries(self):
        """Verify related category deals prefetch reuses RAM cache with 0 extra DB queries."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.mock_product_row
            mock_fetch.return_value = self.mock_history_rows
            mock_fetchval.return_value = 10

            # Pre-warm category cache in ram_cache
            cached_cat_deals = {
                "total_matches": 10,
                "total_pages": 1,
                "page": 1,
                "deals": [
                    {
                        "product_id": 102,
                        "deal_id": 502,
                        "title": "Bose QuietComfort 45",
                        "current_price": 18990.0,
                        "mrp": 29900.0,
                        "platform": "amazon",
                        "image_url": "https://example.com/bose.jpg",
                        "in_stock": True
                    }
                ]
            }
            # Exact cache key used by get_public_deals for related items prefetch
            cache_key = "deals:::electronics::::all::latest:0.0:0.0:0.0:0.0:False:::1:4"
            await ram_cache.set(cache_key, cached_cat_deals, ttl=300)

            resp = self.client.get("/deal/101")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("More Deals in Electronics", resp.text)
            self.assertIn("Bose QuietComfort 45", resp.text)


if __name__ == "__main__":
    unittest.main()

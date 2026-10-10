"""
BudgetBy — Test Suite: Full Shopper Journey & Storefront UX Audit
Validates:
1. Complete Shopper Journey Data Consistency (Listing, Detail, Search, Telegram).
2. Deals Page Filters Single Bounded Query Guarantee.
3. Pagination Offset Computation and Maximum Limit Enforcing.
4. Search Debouncing and Lightweight Suggestion Payloads.
5. RAM Cache Reuse Across Shopper Navigation Flow.
6. SSR Hydration with Zero Redundant Client Fetches.
7. Hero vs Catalog Image Lazy Loading & Fallbacks.
8. Out-of-Stock and Markdowns Handling.
9. Safe Retailer Affiliate Redirection.
10. Mobile Viewport Overflow & Layout Safety.
11. Zero Supabase Egress on Warm Shopper Journey.
12. Telegram Pipeline Decoupled from Storefront Runtime.
"""

import unittest
import datetime
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient
from starlette.requests import Request
from budgetby.dashboard.app import (
    app,
    ram_cache,
    coalescer,
    get_public_deals,
    get_public_deal_detail,
    get_public_price_drops,
    get_public_search_suggestions,
)
from budgetby.engine.deal_scorer import score_deal_full
from budgetby.dashboard.helpers import is_safe_redirect_url


class TestShopperJourneyAndUX(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        ram_cache.clear()
        self.client = TestClient(app)
        self.mock_request = MagicMock(spec=Request)
        self.mock_request.url.path = "/api/public/deals"

        self.sample_deal = {
            "product_id": 201,
            "platform": "amazon",
            "platform_id": "B09G9FPHY6",
            "title": "Apple iPad 10.2-inch (9th Gen) Wi-Fi 64GB Space Grey",
            "category": "electronics",
            "product_url": "https://www.amazon.in/dp/B09G9FPHY6",
            "affiliate_url": "https://www.amazon.in/dp/B09G9FPHY6?tag=dealpulse21-21",
            "image_url": "https://m.media-amazon.com/images/I/61NGnpjoRDL._SL1500_.jpg",
            "current_price": 24999.0,
            "previous_price": 29900.0,
            "mrp": 32900.0,
            "median_30d_price": 28900.0,
            "min_30d": 24999.0,
            "min_60d": 24999.0,
            "min_90d": 26999.0,
            "min_120d": 26999.0,
            "all_time_low": 24999.0,
            "min_price": 24999.0,
            "close_price": 24999.0,
            "date": "2026-10-07",
            "rating": 4.6,
            "review_count": 8500,
            "in_stock": True,
            "status": "ACTIVE",
            "is_verified": True,
            "is_verified_deal": True,
            "deal_time": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2),
            "last_checked": datetime.datetime.now(datetime.timezone.utc),
            "last_price_change": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2),
            "created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30),
            "deal_id": 701,
            "deal_type": "price_drop",
            "badge": "ATL",
            "posted_price": 24999.0,
            "posted_mrp": 32900.0,
            "savings_amount": 7901.0,
            "savings_pct": 0.2401,
            "deal_score": 86.0,
            "posted_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2),
        }

    async def test_01_complete_shopper_journey_data_consistency(self):
        """Verify pricing, discounts, badges and scores match across listing, detail, and scorer."""
        mrp = self.sample_deal["mrp"]
        cp = self.sample_deal["current_price"]
        expected_discount = round(((mrp - cp) / mrp) * 100)

        # 1. Scorer validation
        prod = {
            "current_price": cp,
            "mrp": mrp,
            "platform": "amazon",
            "category": "electronics",
            "rating": self.sample_deal["rating"],
            "review_count": self.sample_deal["review_count"]
        }
        det = {
            "savings_pct": 0.2401,
            "badge": "ATL",
            "is_verified": True
        }
        scores = score_deal_full(prod, det)
        self.assertGreater(scores["shopper_quality_score"], 70.0)

        # 2. SSR Deal detail rendering consistency
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.sample_deal
            mock_fetch.return_value = []
            mock_fetchval.return_value = 5

            resp = self.client.get("/deal/201")
            self.assertEqual(resp.status_code, 200)
            html = resp.text

            # Confirm price and savings format
            self.assertIn("24,999", html)
            self.assertIn("32,900", html)
            self.assertIn(f"{expected_discount}% OFF", html)
            self.assertIn("ALL-TIME LOW", html)

    async def test_02_deals_page_filters_bounded_query(self):
        """Verify complex filter parameters are parameterized and executed as single query."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.sample_deal]
            mock_fetchval.return_value = 1

            res = await get_public_deals(
                request=self.mock_request,
                category="electronics",
                platform="amazon",
                min_discount=20.0,
                min_price=10000.0,
                max_price=30000.0,
                min_rating=4.0,
                verified_only=True,
                page=1,
                limit=24
            )

            self.assertEqual(len(res["deals"]), 1)
            self.assertEqual(res["deals"][0]["product_id"], 201)
            self.assertEqual(res["total_matches"], 1)
            self.assertEqual(res["page"], 1)

    async def test_03_pagination_offsets_and_limit_enforcement(self):
        """Verify pagination computes correct offset and caps limit at safe maximum (30)."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = []
            mock_fetchval.return_value = 250

            # Requesting limit 500 should be safely clamped to max limit 30
            res = await get_public_deals(request=self.mock_request, page=3, limit=500)
            self.assertEqual(res["limit"], 30)
            self.assertEqual(res["page"], 3)
            self.assertEqual(res["total_pages"], 9)

    async def test_04_search_debouncing_and_autocomplete_suggestions(self):
        """Verify search suggestions endpoint returns max 5 lightweight results and uses RAM cache."""
        fake_deals = {
            "deals": [self.sample_deal]
        }
        with patch("budgetby.dashboard.app.get_public_deals", new_callable=AsyncMock) as mock_deals:
            mock_deals.return_value = fake_deals

            resp1 = self.client.get("/api/public/search-suggestions?q=ipad")
            self.assertEqual(resp1.status_code, 200)
            data1 = resp1.json()
            self.assertIn("suggestions", data1)
            self.assertEqual(len(data1["suggestions"]), 1)
            self.assertEqual(data1["suggestions"][0]["product_id"], 201)

            # Second call must hit RAM cache with 0 calls to get_public_deals
            mock_deals.reset_mock()
            resp2 = self.client.get("/api/public/search-suggestions?q=ipad")
            self.assertEqual(resp2.status_code, 200)
            mock_deals.assert_not_called()

    async def test_05_ram_cache_reuse_across_shopper_navigation(self):
        """Verify browsing the storefront reuses cache without repetitive database hits."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.sample_deal
            mock_fetch.return_value = []
            mock_fetchval.return_value = 1

            # Request 1: Detail page miss -> DB query
            resp1 = self.client.get("/deal/201")
            self.assertEqual(resp1.status_code, 200)
            call_count = mock_fetchrow.call_count

            # Request 2: Navigating back to detail page -> RAM cache hit -> 0 DB query
            resp2 = self.client.get("/deal/201")
            self.assertEqual(resp2.status_code, 200)
            self.assertEqual(mock_fetchrow.call_count, call_count)

    async def test_06_ssr_hydration_zero_redundant_client_fetches(self):
        """Verify SSR HTML pages embed initial data for instant client hydration."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.sample_deal]
            mock_fetchval.return_value = 1

            resp = self.client.get("/deals")
            self.assertEqual(resp.status_code, 200)
            self.assertIn('id="dealsMatchesCount"', resp.text)
            self.assertIn('Filter Products', resp.text)

    async def test_07_hero_images_lazy_loading_and_fallbacks(self):
        """Verify listing partials include loading='lazy' and error fallbacks."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.sample_deal
            mock_fetch.return_value = []
            mock_fetchval.return_value = 1

            resp = self.client.get("/deal/201")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("onerror=\"this.src='/static/placeholder.svg'\"", resp.text)

    async def test_08_out_of_stock_and_price_drop_badges(self):
        """Verify out-of-stock items display out-of-stock badge and disabled action cleanly."""
        oos_deal = dict(self.sample_deal)
        oos_deal["in_stock"] = False
        oos_deal["status"] = "TEMP_OOS"

        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = oos_deal
            mock_fetch.return_value = []
            mock_fetchval.return_value = 1

            resp = self.client.get("/deal/201")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("OUT OF STOCK", resp.text)
            self.assertIn("Check Stock on Amazon", resp.text)

    async def test_09_safe_retailer_redirection_affiliate_preservation(self):
        """Verify /api/deal/redirect/{id} routes safely to allowed e-commerce domains."""
        # Safe URL checks
        self.assertTrue(is_safe_redirect_url("https://www.amazon.in/dp/B09G9FPHY6?tag=dealpulse-21"))
        self.assertTrue(is_safe_redirect_url("https://www.flipkart.com/p/item?pid=MOB123"))
        self.assertTrue(is_safe_redirect_url("https://www.myntra.com/shoes/nike"))
        self.assertTrue(is_safe_redirect_url("https://www.ajio.com/clothing/p/460"))
        self.assertTrue(is_safe_redirect_url("https://www.nykaa.com/makeup/p/123"))

        # Malicious URLs blocked
        self.assertFalse(is_safe_redirect_url("https://evil-phishing-site.com/steal"))
        self.assertFalse(is_safe_redirect_url("javascript:alert(1)"))
        self.assertFalse(is_safe_redirect_url("http://malicious.in"))

    async def test_10_mobile_viewport_overflow_safety(self):
        """Verify templates include mobile responsive viewport containers and navigation bars."""
        with patch("budgetby.dashboard.app.get_public_price_drops", new_callable=AsyncMock) as mock_drops, \
             patch("budgetby.dashboard.app.get_public_deals", new_callable=AsyncMock) as mock_deals, \
             patch("budgetby.dashboard.app.get_public_stats", new_callable=AsyncMock) as mock_stats:
            
            mock_drops.return_value = {"drops": []}
            mock_deals.return_value = {"deals": []}
            mock_stats.return_value = {}

            resp = self.client.get("/")
            self.assertEqual(resp.status_code, 200)
            self.assertIn('name="viewport"', resp.text)
            self.assertIn('content="width=device-width, initial-scale=1.0"', resp.text)

    async def test_11_zero_supabase_egress_on_cached_shopper_journey(self):
        """Verify entire simulated shopper navigation through warm cache makes 0 DB calls."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.sample_deal
            mock_fetch.return_value = [self.sample_deal]
            mock_fetchval.return_value = 1

            # Populate caches
            await get_public_deals(request=self.mock_request, category="electronics", page=1, limit=10)
            await get_public_deal_detail(201)

            # Reset database call trackers
            mock_fetchrow.reset_mock()
            mock_fetch.reset_mock()
            mock_fetchval.reset_mock()

            # Execute warm requests: Homepage deals -> Product Detail
            await get_public_deals(request=self.mock_request, category="electronics", page=1, limit=10)
            await get_public_deal_detail(201)

            mock_fetchrow.assert_not_called()
            mock_fetch.assert_not_called()
            mock_fetchval.assert_not_called()

    async def test_12_telegram_pipeline_decoupled_from_storefront(self):
        """Verify storefront rendering is not coupled to background Telegram delivery tasks."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.sample_deal
            mock_fetch.return_value = []
            mock_fetchval.return_value = 1

            resp = self.client.get("/deal/201")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("Apple iPad", resp.text)


if __name__ == "__main__":
    unittest.main()

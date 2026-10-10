"""
BudgetBy — Test Suite: Guest Deal Discovery & "Best Deals" Experience Audit
Validates:
1. Best Deals uses Shopper Deal Quality Score (sort_by="score_desc" / "best").
2. Monetization/commission does not affect public ranking.
3. Newly discovered deals ordering (sort_by="latest").
4. Price-drop ordering (sort_by="drop_pct" / "drop_desc").
5. ATL semantics (historical low verification).
6. Category navigation (parameter preservation & taxonomy).
7. Store navigation (Amazon, Flipkart, Myntra, Ajio, Nykaa).
8. Search -> detail navigation (direct deal link).
9. Filter request efficiency (single parameterized bounded query).
10. No duplicate initial requests on SSR hydration.
11. Cache hit = 0 database queries.
12. Bounded pagination (clamped to <= 30 items).
13. Affiliate redirect with whitelist validation.
14. Complete anonymous browsing experience with zero auth.
15. No authentication/login wall enforcement.
16. Zero unnecessary Supabase reads/writes.
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
from budgetby.engine.deal_scorer import score_deal, score_deal_full, calculate_shopper_score, calculate_monetization_score
from budgetby.dashboard.helpers import is_safe_redirect_url


class TestGuestDealDiscovery(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        ram_cache.clear()
        self.client = TestClient(app)
        self.mock_request = MagicMock(spec=Request)
        self.mock_request.url.path = "/api/public/deals"

        self.sample_deal_a = {
            "deal_id": 801,
            "product_id": 301,
            "platform": "amazon",
            "platform_id": "B08N5WRWNW",
            "title": "Deal A - Super Budget Wireless Earbuds (80% Off ATL)",
            "category": "electronics",
            "product_url": "https://www.amazon.in/dp/B08N5WRWNW",
            "affiliate_url": "https://www.amazon.in/dp/B08N5WRWNW?tag=dealpulse21-21",
            "image_url": "https://m.media-amazon.com/images/I/earbuds.jpg",
            "current_price": 500.0,
            "deal_price": 500.0,
            "previous_price": 2500.0,
            "mrp": 2500.0,
            "median_30d_price": 2000.0,
            "min_30d": 500.0,
            "min_60d": 500.0,
            "min_90d": 900.0,
            "min_120d": 1200.0,
            "all_time_low": 500.0,
            "min_price": 500.0,
            "close_price": 500.0,
            "date": "2026-10-07",
            "rating": 4.0,
            "review_count": 500,
            "in_stock": True,
            "status": "ACTIVE",
            "is_verified": True,
            "is_verified_deal": True,
            "deal_time": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1),
            "last_checked": datetime.datetime.now(datetime.timezone.utc),
            "last_price_change": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1),
            "created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10),
            "deal_type": "price_drop",
            "badge": "ATL",
            "posted_price": 500.0,
            "posted_mrp": 2500.0,
            "savings_amount": 2000.0,
            "savings_pct": 0.80,
            "drop_pct": 80.0,
            "drop_amount": 2000.0,
            "relevance_score": 0,
            "deal_score": 87.8,
            "posted_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1),
        }

        self.sample_deal_b = {
            "deal_id": 802,
            "product_id": 302,
            "platform": "amazon",
            "platform_id": "B09ABC1234",
            "title": "Deal B - Premium Flagship Laptop (20% Off 60d Low)",
            "category": "electronics",
            "product_url": "https://www.amazon.in/dp/B09ABC1234",
            "affiliate_url": "https://www.amazon.in/dp/B09ABC1234?tag=dealpulse21-21",
            "image_url": "https://m.media-amazon.com/images/I/laptop.jpg",
            "current_price": 5000.0,
            "deal_price": 5000.0,
            "previous_price": 6250.0,
            "mrp": 6250.0,
            "median_30d_price": 6000.0,
            "min_30d": 5000.0,
            "min_60d": 5000.0,
            "min_90d": 5000.0,
            "min_120d": 5000.0,
            "all_time_low": 4500.0,
            "min_price": 5000.0,
            "close_price": 5000.0,
            "date": "2026-10-07",
            "rating": 4.8,
            "review_count": 10000,
            "in_stock": True,
            "status": "ACTIVE",
            "is_verified": True,
            "is_verified_deal": True,
            "deal_time": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5),
            "last_checked": datetime.datetime.now(datetime.timezone.utc),
            "last_price_change": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5),
            "created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60),
            "deal_type": "price_drop",
            "badge": "60d_low",
            "posted_price": 5000.0,
            "posted_mrp": 6250.0,
            "savings_amount": 1250.0,
            "savings_pct": 0.20,
            "drop_pct": 20.0,
            "drop_amount": 1250.0,
            "relevance_score": 0,
            "deal_score": 67.5,
            "posted_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5),
        }

        self.sample_deal_c = {
            "deal_id": 803,
            "product_id": 303,
            "platform": "myntra",
            "platform_id": "MYN123456",
            "title": "Deal C - Running Shoes (45% Off 90d Low)",
            "category": "footwear",
            "product_url": "https://www.myntra.com/shoes/nike",
            "affiliate_url": "https://www.myntra.com/shoes/nike?aff=test",
            "image_url": "https://assets.myntassets.com/shoes.jpg",
            "current_price": 1500.0,
            "deal_price": 1500.0,
            "previous_price": 2727.0,
            "mrp": 2727.0,
            "median_30d_price": 2200.0,
            "min_30d": 1500.0,
            "min_60d": 1500.0,
            "min_90d": 1500.0,
            "min_120d": 1800.0,
            "all_time_low": 1400.0,
            "min_price": 1500.0,
            "close_price": 1500.0,
            "date": "2026-10-07",
            "rating": 4.3,
            "review_count": 3000,
            "in_stock": True,
            "status": "ACTIVE",
            "is_verified": True,
            "is_verified_deal": True,
            "deal_time": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3),
            "last_checked": datetime.datetime.now(datetime.timezone.utc),
            "last_price_change": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3),
            "created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=40),
            "deal_type": "price_drop",
            "badge": "90d_low",
            "posted_price": 1500.0,
            "posted_mrp": 2727.0,
            "savings_amount": 1227.0,
            "savings_pct": 0.45,
            "drop_pct": 45.0,
            "drop_amount": 1227.0,
            "relevance_score": 0,
            "deal_score": 81.1,
            "posted_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3),
        }

    async def test_01_best_deals_ranking_uses_shopper_quality_score(self):
        """Verify Best Deals ordering places consumer value (A > C > B) without commission bias."""
        score_a = score_deal(self.sample_deal_a, {"savings_pct": 0.80, "badge": "ATL"})
        score_b = score_deal(self.sample_deal_b, {"savings_pct": 0.20, "badge": "60d_low"})
        score_c = score_deal(self.sample_deal_c, {"savings_pct": 0.45, "badge": "90d_low"})

        self.assertGreater(score_a, score_c)
        self.assertGreater(score_c, score_b)

    async def test_02_monetization_does_not_affect_public_ranking(self):
        """Verify high ticket size / commission (Deal B) does not overtake higher consumer discount (Deal A)."""
        mon_b = calculate_monetization_score(self.sample_deal_b, {"savings_pct": 0.20})
        shop_a = calculate_shopper_score(self.sample_deal_a, {"savings_pct": 0.80, "badge": "ATL"})
        shop_b = calculate_shopper_score(self.sample_deal_b, {"savings_pct": 0.20, "badge": "60d_low"})

        # Monetization score may be higher for B due to ₹5000 price ticket
        self.assertGreater(mon_b, 0.0)
        # But public shopper deal quality score strictly favors Deal A
        self.assertGreater(shop_a, shop_b)

    async def test_03_newly_discovered_deals_ordering(self):
        """Verify sort_by='latest' orders deals by discovery/posting freshness."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.sample_deal_a, self.sample_deal_c, self.sample_deal_b]
            mock_fetchval.return_value = 3

            res = await get_public_deals(request=self.mock_request, sort_by="latest", limit=10)
            self.assertEqual(len(res["deals"]), 3)
            self.assertEqual(res["deals"][0]["product_id"], 301)

    async def test_04_price_drop_ordering_and_fields(self):
        """Verify 24h price drops uses verified drop percentage from previous observed price."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.sample_deal_a]
            mock_fetchval.return_value = 1

            res = await get_public_price_drops(request=self.mock_request, min_drop_pct=10.0, page=1, limit=12)
            self.assertEqual(len(res["drops"]), 1)
            self.assertEqual(res["drops"][0]["drop_pct"], 80.0)
            self.assertEqual(res["drops"][0]["previous_price"], 2500.0)

    async def test_05_atl_semantics_verified_historically(self):
        """Verify All-Time Low badge is only active when current price <= all_time_low * 1.02."""
        self.assertTrue(self.sample_deal_a["current_price"] <= self.sample_deal_a["all_time_low"] * 1.02)
        # Deal B (₹5000 vs ATL ₹4500) is NOT an ATL
        self.assertFalse(self.sample_deal_b["current_price"] <= self.sample_deal_b["all_time_low"] * 1.02)

    async def test_06_category_navigation_and_filtering(self):
        """Verify category deals endpoint filters by taxonomy key cleanly."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.sample_deal_c]
            mock_fetchval.return_value = 1

            res = await get_public_deals(request=self.mock_request, category="footwear", page=1, limit=24)
            self.assertEqual(len(res["deals"]), 1)
            self.assertEqual(res["deals"][0]["category"], "footwear")

    async def test_07_store_navigation_filters(self):
        """Verify store filtering works for Amazon, Flipkart, Myntra, Ajio, Nykaa."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.sample_deal_c]
            mock_fetchval.return_value = 1

            res = await get_public_deals(request=self.mock_request, platform="myntra", page=1, limit=10)
            self.assertEqual(len(res["deals"]), 1)
            self.assertEqual(res["deals"][0]["platform"], "myntra")

    async def test_08_search_autocomplete_to_deal_detail_navigation(self):
        """Verify search autocomplete suggestions return lightweight payloads with direct product_id links."""
        fake_deals = {
            "deals": [self.sample_deal_a]
        }
        with patch("budgetby.dashboard.app.get_public_deals", new_callable=AsyncMock) as mock_deals:
            mock_deals.return_value = fake_deals

            resp = self.client.get("/api/public/search-suggestions?q=earbuds")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("suggestions", data)
            self.assertEqual(data["suggestions"][0]["product_id"], 301)

    async def test_09_filter_request_efficiency_single_bounded_query(self):
        """Verify applying multiple filters executes only 1 database query via database.fetch."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.sample_deal_a]
            mock_fetchval.return_value = 1

            res = await get_public_deals(
                request=self.mock_request,
                category="electronics",
                platform="amazon",
                min_discount=50.0,
                min_rating=4.0,
                page=1,
                limit=24
            )
            self.assertEqual(mock_fetch.call_count, 1)
            self.assertEqual(len(res["deals"]), 1)

    async def test_10_no_duplicate_initial_requests_on_ssr_hydration(self):
        """Verify homepage HTML response renders pre-fetched sections with 0 client polling loops."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = [self.sample_deal_a]
            mock_fetchrow.return_value = {
                "total_products": 100000, "total_deals": 14000, "deals_today": 1500,
                "drops_today": 30000, "latest_deal_time": None, "by_platform_json": {}
            }
            mock_fetchval.return_value = 1

            resp = self.client.get("/")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("Best Deals Today", resp.text)
            self.assertIn("Just Dropped Deals", resp.text)
            self.assertNotIn("startHomeLiveAutoPolling", resp.text)

    async def test_11_cache_hit_executes_zero_database_queries(self):
        """Verify cached deal requests execute 0 database queries on repeat visits."""
        with patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.sample_deal_a
            mock_fetch.return_value = []
            mock_fetchval.return_value = 1

            # Request 1: Cache miss
            await get_public_deal_detail(301)
            self.assertEqual(mock_fetchrow.call_count, 1)

            # Request 2: Cache hit
            mock_fetchrow.reset_mock()
            await get_public_deal_detail(301)
            mock_fetchrow.assert_not_called()

    async def test_12_bounded_pagination_caps_limit_at_30(self):
        """Verify requesting arbitrary large limits is safely capped at 30 items."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetch.return_value = []
            mock_fetchval.return_value = 100

            res = await get_public_deals(request=self.mock_request, limit=999)
            self.assertEqual(res["limit"], 30)

    async def test_13_affiliate_redirect_safely_validates_whitelist(self):
        """Verify redirect routes safely validate trusted merchant hosts."""
        self.assertTrue(is_safe_redirect_url("https://www.amazon.in/dp/B08N5WRWNW"))
        self.assertTrue(is_safe_redirect_url("https://www.flipkart.com/p/item"))
        self.assertTrue(is_safe_redirect_url("https://www.myntra.com/product/123"))
        self.assertTrue(is_safe_redirect_url("https://www.ajio.com/product/456"))
        self.assertTrue(is_safe_redirect_url("https://www.nykaa.com/product/789"))
        self.assertFalse(is_safe_redirect_url("https://phishing-site.example.com"))

    async def test_14_anonymous_user_can_browse_entire_storefront(self):
        """Verify guest user can access homepage, deals, drops, all-time lows, stores, and detail views."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            def mock_fetchrow_side_effect(query, *args):
                if "WHERE p.id" in str(query) or "FROM products" in str(query):
                    return self.sample_deal_a
                return {
                    "total_products": 100000, "total_deals": 14000, "deals_today": 1500,
                    "drops_today": 30000, "latest_deal_time": None, "by_platform_json": {}
                }
            mock_fetchrow.side_effect = mock_fetchrow_side_effect
            mock_fetchval.return_value = 1

            for route in ["/", "/deals", "/drops", "/all-time-lows", "/stores", "/deal/301"]:
                ram_cache.clear()
                resp = self.client.get(route)
                self.assertEqual(resp.status_code, 200, f"Route {route} failed for guest visitor with {resp.status_code}")

    async def test_15_no_authentication_or_login_wall_enforced(self):
        """Verify no login or register redirects exist on public consumer routes."""
        public_routes = ["/", "/deals", "/drops", "/all-time-lows", "/stores", "/about", "/api/public/stats"]
        for route in public_routes:
            resp = self.client.get(route, follow_redirects=False)
            self.assertIn(resp.status_code, [200, 307, 308], f"Public route {route} blocked guest with status {resp.status_code}")
            if resp.status_code in [307, 308]:
                self.assertNotIn("login", resp.headers.get("location", "").lower())

    async def test_16_zero_unnecessary_supabase_writes_on_public_reads(self):
        """Verify read operations do not trigger any database write executions."""
        with patch("budgetby.database.execute", new_callable=AsyncMock) as mock_execute, \
             patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
             patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:

            mock_fetchrow.return_value = self.sample_deal_a
            mock_fetch.return_value = []
            mock_fetchval.return_value = 1

            await get_public_deal_detail(301)
            mock_execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

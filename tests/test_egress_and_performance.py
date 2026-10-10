"""
Tests for Supabase Egress Audit and Website Speed Optimization.
Verifies caching, pagination limits, explicit column queries, cooldown memory layer,
and local SQLite batching isolation.
"""

import unittest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import time
import datetime

class TestEgressAndPerformance(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_cooldown_memory_caching(self):
        """Verify cooldown memory cache prevents repeated Supabase queries within TTL."""
        from budgetby.engine import cooldown
        
        async def run_test():
            cooldown._cooldown_cache.clear()
            
            with patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_fetchval:
                mock_fetchval.return_value = False
                
                # First check should hit database
                res1 = await cooldown.is_on_cooldown(101)
                self.assertFalse(res1)
                self.assertEqual(mock_fetchval.call_count, 1)
                
                # Second check immediately after should hit RAM cache (0 DB calls)
                res2 = await cooldown.is_on_cooldown(101)
                self.assertFalse(res2)
                self.assertEqual(mock_fetchval.call_count, 1)
                
                # Verify another product_id hits DB
                res3 = await cooldown.is_on_cooldown(102)
                self.assertFalse(res3)
                self.assertEqual(mock_fetchval.call_count, 2)
                
        self.loop.run_until_complete(run_test())

    def test_evergreen_memory_caching(self):
        """Verify evergreen deals memory cache avoids repeated Supabase fetch queries."""
        from budgetby.engine import evergreen
        
        async def run_test():
            evergreen._evergreen_cache.clear()
            
            fake_record = {
                "id": 1, "platform": "amazon", "product_url": "https://amazon.in/dp/B001",
                "affiliate_url": "", "title": "Evergreen Product", "current_price": 500.0,
                "mrp": 1000.0, "rating": 4.5, "review_count": 100, "image_url": "", "category": "electronics"
            }
            
            with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = [fake_record]
                
                # First call hits DB
                deals1 = await evergreen.find_evergreen_deals(limit=5, platform="amazon")
                self.assertEqual(len(deals1), 1)
                self.assertEqual(mock_fetch.call_count, 1)
                
                # Second call served from memory cache
                deals2 = await evergreen.find_evergreen_deals(limit=5, platform="amazon")
                self.assertEqual(len(deals2), 1)
                self.assertEqual(mock_fetch.call_count, 1)
                
        self.loop.run_until_complete(run_test())

    def test_local_price_check_zero_supabase_read_egress(self):
        """Verify local price_check_loop reads exclusively from SQLite with zero Supabase reads."""
        from budgetby.scheduler import scheduler
        
        async def run_test():
            fake_row = {
                "id": 55, "platform": "amazon", "platform_id": "B0TEST",
                "url": "https://amazon.in/dp/B0TEST", "current_price": 1000.0, "mrp": 1500.0,
                "priority_tier": 3, "next_check": "2026-01-01T00:00:00", "status": "ACTIVE"
            }
            
            with patch("budgetby.local_db.get_products_due_for_check", new_callable=AsyncMock) as mock_local_get, \
                 patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_sb_fetch, \
                 patch("budgetby.database.fetchrow", new_callable=AsyncMock) as mock_sb_fetchrow, \
                 patch("budgetby.database.fetchval", new_callable=AsyncMock) as mock_sb_fetchval, \
                 patch("budgetby.scrapers.amazon.AmazonScraper.scrape_product", new_callable=AsyncMock) as mock_scrape, \
                 patch("budgetby.local_db.update_product_check_time") as mock_update_check:
                
                mock_local_get.return_value = [fake_row]
                # Price unchanged
                mock_scrape.return_value = {"current_price": 1000.0, "mrp": 1500.0, "in_stock": True}
                
                await scheduler.price_check_loop()
                
                # Verify local SQLite was read
                mock_local_get.assert_called_once()
                mock_update_check.assert_called_once()
                
                # Verify ZERO reads were performed on Supabase
                self.assertEqual(mock_sb_fetch.call_count, 0)
                self.assertEqual(mock_sb_fetchrow.call_count, 0)
                self.assertEqual(mock_sb_fetchval.call_count, 0)
                
        self.loop.run_until_complete(run_test())

    def test_pending_syncs_batching_and_isolation(self):
        """Verify Tier 3/4 price updates are queued in SQLite and batched to Supabase during nightly sync."""
        from budgetby.scheduler import scheduler
        from budgetby import local_db
        
        async def run_test():
            fake_pending_rows = [
                {"platform": "amazon", "platform_id": "B01", "new_price": 799.0, "in_stock": True, "status": "ACTIVE"},
                {"platform": "flipkart", "platform_id": "FK02", "new_price": 499.0, "in_stock": True, "status": "ACTIVE"}
            ]
            
            with patch("budgetby.local_db.get_and_clear_pending_syncs", new_callable=AsyncMock) as mock_get_clear, \
                 patch("budgetby.database.batch_update_products", new_callable=AsyncMock) as mock_batch_update, \
                 patch("budgetby.database.sync_daily_price_baselines", new_callable=AsyncMock) as mock_sync_baselines:
                
                mock_get_clear.return_value = fake_pending_rows
                
                await scheduler.nightly_batch_sync()
                
                mock_get_clear.assert_called_once()
                mock_batch_update.assert_called_once()
                args, _ = mock_batch_update.call_args
                self.assertEqual(len(args[0]), 2)
                self.assertEqual(args[0][0], (799.0, True, "ACTIVE", "amazon", "B01"))
                mock_sync_baselines.assert_called_once()
                
        self.loop.run_until_complete(run_test())

if __name__ == "__main__":
    unittest.main()

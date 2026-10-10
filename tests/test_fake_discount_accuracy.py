"""
BudgetBy — Test Suite for Multi-Day MRP History & Fake-Discount Accuracy
Comprehensive edge-case and write-efficiency verification:
1. Stable MRP + genuine selling-price drop -> PASS
2. Sudden MRP spike + unchanged selling price -> REJECT (Fake Discount)
3. Gradual suspicious MRP creep -> REJECT (Fake Discount)
4. MRP spike followed by return to normal -> PASS
5. Insufficient history (<3 days) -> Fallback heuristic (genuine new product PASS)
6. Missing/zero MRP handling -> Safe without crash or history corruption
7. Price drop with unchanged MRP -> PASS
8. Local DB 14-day retention cleanup -> Prunes old observations correctly
9. Zero Supabase egress -> All MRP operations remain 100% in local SQLite
10. Same-day observation deduplication -> Eliminates write amplification (1 write only)
11. Same-day MRP update -> Changed MRP updates the daily record
12. Gradual legitimate MRP change -> PASS
13. Legitimate promotion where selling price & MRP both change -> PASS
"""

import unittest
import asyncio
import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from budgetby import local_db
from budgetby.engine.fake_discount import is_fake_discount
from budgetby.engine.deal_detector import detect_deal


class TestFakeDiscountAccuracy(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Initialize local database connection in memory or local test db
        await local_db.init_db()

    async def asyncTearDown(self):
        await local_db.close_db()

    async def test_01_stable_mrp_genuine_discount_passes(self):
        """Test that a product with stable historical MRP passes fake discount check."""
        platform = "amazon"
        platform_id = "B0STABLE01"
        today = datetime.datetime.now(datetime.timezone.utc)

        # Seed 7 days of stable MRP (₹1,000 every day)
        for i in range(7, 0, -1):
            date_str = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            local_db.record_mrp_observation(platform, platform_id, 1000.0, date_str=date_str)

        # Allow writer queue to drain
        await asyncio.sleep(0.05)

        product = {
            "platform": platform,
            "platform_id": platform_id,
            "mrp": 1000.0,
            "current_price": 600.0,
            "previous_price": 900.0,
            "median_30d_price": 850.0,
        }
        is_fake = await is_fake_discount(product, new_price=600.0)
        self.assertFalse(is_fake, "Stable MRP with genuine price drop should NOT be flagged as fake discount.")

    async def test_02_sudden_mrp_spike_flagged_as_fake(self):
        """Test that a sudden MRP spike (>20% above median) is flagged as fake discount."""
        platform = "flipkart"
        platform_id = "FLIP_SPIKE01"
        today = datetime.datetime.now(datetime.timezone.utc)

        # Seed 5 days of baseline MRP = ₹1,000
        for i in range(5, 0, -1):
            date_str = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            local_db.record_mrp_observation(platform, platform_id, 1000.0, date_str=date_str)

        await asyncio.sleep(0.05)

        # Merchant suddenly raises MRP to ₹1,500 (+50% spike) and sets price to ₹950 (regular price)
        product = {
            "platform": platform,
            "platform_id": platform_id,
            "mrp": 1500.0,
            "current_price": 950.0,
            "previous_price": 950.0,
            "median_30d_price": 950.0,
        }
        is_fake = await is_fake_discount(product, new_price=950.0)
        self.assertTrue(is_fake, "Sudden MRP spike with no real price drop MUST be flagged as fake discount.")

    async def test_03_gradual_mrp_creeping_flagged_as_fake(self):
        """Test that gradual MRP creeping (>25% above 14d minimum) is flagged as fake discount."""
        platform = "myntra"
        platform_id = "MYN_CREEP01"
        today = datetime.datetime.now(datetime.timezone.utc)

        # MRP gradually climbed: 1000 -> 1100 -> 1200 -> 1300
        days_mrps = [(10, 1000.0), (7, 1100.0), (4, 1200.0), (1, 1300.0)]
        for days_ago, mrp_val in days_mrps:
            date_str = (today - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d")
            local_db.record_mrp_observation(platform, platform_id, mrp_val, date_str=date_str)

        await asyncio.sleep(0.05)

        # Current MRP is 1350 (+35% from min of 1000), offering at 950 (which is near the old regular price)
        product = {
            "platform": platform,
            "platform_id": platform_id,
            "mrp": 1350.0,
            "current_price": 950.0,
            "previous_price": 980.0,
            "median_30d_price": 950.0,
        }
        is_fake = await is_fake_discount(product, new_price=950.0)
        self.assertTrue(is_fake, "Gradual MRP creeping without true discount MUST be flagged as fake discount.")

    async def test_04_mrp_returning_to_normal_passes(self):
        """Test that when MRP returns to its historical normal, genuine discounts pass."""
        platform = "ajio"
        platform_id = "AJIO_NORMAL01"
        today = datetime.datetime.now(datetime.timezone.utc)

        # Baseline MRP was 2000, briefly spiked to 2600, now back to 2000
        days_mrps = [(6, 2000.0), (5, 2000.0), (4, 2600.0), (2, 2000.0), (1, 2000.0)]
        for days_ago, mrp_val in days_mrps:
            date_str = (today - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d")
            local_db.record_mrp_observation(platform, platform_id, mrp_val, date_str=date_str)

        await asyncio.sleep(0.05)

        product = {
            "platform": platform,
            "platform_id": platform_id,
            "mrp": 2000.0,
            "current_price": 1100.0,
            "previous_price": 1800.0,
            "median_30d_price": 1700.0,
        }
        is_fake = await is_fake_discount(product, new_price=1100.0)
        self.assertFalse(is_fake, "MRP returned to normal with a genuine price drop should pass.")

    async def test_05_insufficient_history_fallback_does_not_reject_new_deals(self):
        """Test that new products with < 3 days of history are not falsely rejected."""
        platform = "nykaa"
        platform_id = "NYK_NEW01"

        # Brand new product (0 days of history in local SQLite)
        product = {
            "platform": platform,
            "platform_id": platform_id,
            "mrp": 1200.0,
            "current_price": 600.0,
            "previous_price": 1200.0,
            "median_30d_price": 1000.0,
        }
        is_fake = await is_fake_discount(product, new_price=600.0)
        self.assertFalse(is_fake, "New product with genuine 50% discount should NOT be falsely rejected.")

    async def test_06_missing_mrp_safe_handling(self):
        """Test that products with None, 0, or invalid MRP fail gracefully without exceptions."""
        product_no_mrp = {"platform": "amazon", "platform_id": "NO_MRP", "mrp": None}
        is_fake1 = await is_fake_discount(product_no_mrp, new_price=500.0)
        self.assertFalse(is_fake1)

        product_zero_mrp = {"platform": "amazon", "platform_id": "ZERO_MRP", "mrp": 0}
        is_fake2 = await is_fake_discount(product_zero_mrp, new_price=500.0)
        self.assertFalse(is_fake2)

        is_fake3 = await is_fake_discount(None, new_price=500.0)
        self.assertFalse(is_fake3)

    async def test_07_price_drop_with_unchanged_mrp_passes(self):
        """Test that when MRP remains exactly unchanged and price drops, it passes deal detection."""
        platform = "amazon"
        platform_id = "AMZ_GENUINE_DROP"
        today = datetime.datetime.now(datetime.timezone.utc)

        for i in range(5, 0, -1):
            date_str = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            local_db.record_mrp_observation(platform, platform_id, 3000.0, date_str=date_str)

        await asyncio.sleep(0.05)

        product = {
            "platform": platform,
            "platform_id": platform_id,
            "mrp": 3000.0,
            "current_price": 2500.0,
            "previous_price": 2500.0,
            "min_30d": 2400.0,
            "all_time_low": 2000.0,
            "median_30d_price": 2450.0,
        }
        is_fake = await is_fake_discount(product, new_price=1800.0)
        self.assertFalse(is_fake, "Legitimate price drop with steady MRP must pass fake discount check.")

        # Also verify through deal detector
        deal = await detect_deal(product, new_price=1800.0)
        self.assertIsNotNone(deal, "Deal detector should qualify genuine price drop.")
        self.assertFalse(deal["is_fake_discount"])

    async def test_08_retention_cleanup_prunes_old_records(self):
        """Test that cleanup_old_mrp_history prunes records older than 14 days and keeps fresh ones."""
        platform = "amazon"
        platform_id = "PRUNE_TEST"
        today = datetime.datetime.now(datetime.timezone.utc)

        # Seed an old record (20 days ago) and a fresh record (5 days ago)
        old_date = (today - datetime.timedelta(days=20)).strftime("%Y-%m-%d")
        fresh_date = (today - datetime.timedelta(days=5)).strftime("%Y-%m-%d")

        local_db.record_mrp_observation(platform, platform_id, 1000.0, date_str=old_date)
        local_db.record_mrp_observation(platform, platform_id, 1200.0, date_str=fresh_date)

        await asyncio.sleep(0.05)

        # Run cleanup with 14-day retention
        deleted = await local_db.cleanup_old_mrp_history(retention_days=14)
        self.assertGreaterEqual(deleted, 1, "Should have pruned at least 1 record older than 14 days.")

        # Check history
        history = await local_db.get_mrp_history(platform, platform_id, days=30)
        dates = [h["date"] for h in history]
        self.assertNotIn(old_date, dates, "Old date (>14d) should be deleted.")
        self.assertIn(fresh_date, dates, "Fresh date (<=14d) should be preserved.")

    async def test_09_zero_supabase_egress_for_mrp_history(self):
        """Verify that recording and querying MRP history makes ZERO calls to Supabase database."""
        with patch("budgetby.database.execute") as mock_db_exec, \
             patch("budgetby.database.fetch") as mock_db_fetch, \
             patch("budgetby.database.fetchrow") as mock_db_fetchrow:

            platform = "amazon"
            platform_id = "ZERO_EGRESS_TEST"

            # 1. Record MRP observation
            local_db.record_mrp_observation(platform, platform_id, 1500.0)
            await asyncio.sleep(0.05)

            # 2. Query MRP history
            history = await local_db.get_mrp_history(platform, platform_id, days=14)

            # 3. Fake discount evaluation
            product = {
                "platform": platform,
                "platform_id": platform_id,
                "mrp": 1500.0,
                "current_price": 1000.0,
                "previous_price": 1400.0,
                "median_30d_price": 1350.0,
            }
            await is_fake_discount(product, new_price=1000.0)

            # 4. Retention prune
            await local_db.cleanup_old_mrp_history(retention_days=14)

            # Assert ZERO calls to Supabase cloud database
            mock_db_exec.assert_not_called()
            mock_db_fetch.assert_not_called()
            mock_db_fetchrow.assert_not_called()

    async def test_10_same_day_observation_deduplication_eliminates_write_amplification(self):
        """Verify that multiple scraper checks on the same day with identical MRP do not trigger repeated SQLite writes."""
        platform = "amazon"
        platform_id = "DEDUP_TEST_01"
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

        # 1st observation: should enqueue an SQLite write (returns True)
        wrote_first = local_db.record_mrp_observation(platform, platform_id, 1999.0, date_str=today_str)
        self.assertTrue(wrote_first, "First daily observation must enqueue a write.")

        # 2nd observation (30 seconds later, same MRP): should be deduplicated (returns False)
        wrote_second = local_db.record_mrp_observation(platform, platform_id, 1999.0, date_str=today_str)
        self.assertFalse(wrote_second, "Duplicate same-day observation with identical MRP must be skipped.")

        # 3rd observation (5 minutes later, same MRP): should also be deduplicated
        wrote_third = local_db.record_mrp_observation(platform, platform_id, 1999.0, date_str=today_str)
        self.assertFalse(wrote_third, "Subsequent duplicate same-day observations must be skipped.")

        await asyncio.sleep(0.05)

        # Check that exactly 1 row exists in SQLite
        history = await local_db.get_mrp_history(platform, platform_id, days=1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["mrp"], 1999.0)

    async def test_11_same_day_changed_mrp_updates_daily_row(self):
        """Verify that if MRP changes during the day, the daily row is updated to the new MRP."""
        platform = "flipkart"
        platform_id = "SAME_DAY_CHANGE"
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

        # Morning observation: MRP = 2000.0
        wrote_morning = local_db.record_mrp_observation(platform, platform_id, 2000.0, date_str=today_str)
        self.assertTrue(wrote_morning)

        # Evening observation: MRP changed to 2200.0
        wrote_evening = local_db.record_mrp_observation(platform, platform_id, 2200.0, date_str=today_str)
        self.assertTrue(wrote_evening, "Changed MRP on the same day must trigger an update write.")

        await asyncio.sleep(0.05)

        # Check that the daily observation has the updated MRP
        history = await local_db.get_mrp_history(platform, platform_id, days=1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["mrp"], 2200.0)

    async def test_12_gradual_legitimate_mrp_change_passes(self):
        """Verify that a legitimate moderate MRP increase (e.g. +10% inflation) with a genuine discount passes."""
        platform = "myntra"
        platform_id = "LEGIT_MRP_INFLATION"
        today = datetime.datetime.now(datetime.timezone.utc)

        # Baseline MRP: 1000 -> 1020 -> 1050 -> 1080 -> 1100 (+10% over 2 weeks)
        mrps = [(12, 1000.0), (9, 1020.0), (6, 1050.0), (3, 1080.0), (1, 1100.0)]
        for days_ago, m_val in mrps:
            date_str = (today - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d")
            local_db.record_mrp_observation(platform, platform_id, m_val, date_str=date_str)

        await asyncio.sleep(0.05)

        # Current MRP is 1100, genuine clearance price is 500 (deep 55% discount)
        product = {
            "platform": platform,
            "platform_id": platform_id,
            "mrp": 1100.0,
            "current_price": 500.0,
            "previous_price": 900.0,
            "median_30d_price": 850.0,
        }
        is_fake = await is_fake_discount(product, new_price=500.0)
        self.assertFalse(is_fake, "Legitimate moderate MRP increase with deep discount should NOT be flagged.")

    async def test_13_legitimate_promotion_with_mrp_reduction_passes(self):
        """Verify that when brand reduces official MRP and offers promo price, it passes."""
        platform = "ajio"
        platform_id = "PROMO_MRP_DROP"
        today = datetime.datetime.now(datetime.timezone.utc)

        # Baseline MRP was 2500 for 5 days
        for i in range(5, 0, -1):
            date_str = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            local_db.record_mrp_observation(platform, platform_id, 2500.0, date_str=date_str)

        await asyncio.sleep(0.05)

        # Brand official MRP drops from 2500 -> 2000 and retailer sells for 1200
        product = {
            "platform": platform,
            "platform_id": platform_id,
            "mrp": 2000.0,
            "current_price": 1200.0,
            "previous_price": 1800.0,
            "median_30d_price": 1800.0,
        }
        is_fake = await is_fake_discount(product, new_price=1200.0)
        self.assertFalse(is_fake, "Promotion with lower MRP and genuine price drop must pass.")


if __name__ == "__main__":
    unittest.main()

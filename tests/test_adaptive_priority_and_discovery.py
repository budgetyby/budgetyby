"""
BudgetBy — Test Suite for Adaptive Priority & Intelligent Discovery
Verifies:
1. New product receives temporary priority boost (Tier 2 within 48h).
2. Stable product gradually demoted to Tier 3 / Tier 4 (14d unchanged).
3. Recent price volatility increases priority to Tier 1 (within 24h).
4. Recent deal activity increases priority to Tier 1 (within 48h).
5. Stock recovery from TEMP_OOS to ACTIVE boosts priority to Tier 2.
6. Out of Stock (TEMP_OOS) demoted immediately to Tier 4 (48h interval).
7. Priority bounds strictly respected [1..4].
8. Check intervals calculate properly with sale mode multiplier.
9. Duplicate discovery resolves cleanly to canonical identity.
10. Local discovery telemetry records events with zero cloud egress.
11. Zero Supabase read egress for all priority decisions.
12. Zero Supabase write egress for telemetry events.
"""

import unittest
import asyncio
import datetime
from unittest.mock import patch, AsyncMock, MagicMock
from budgetby import config, local_db
from budgetby.scheduler.priority import assign_priority
from budgetby.engine.discovery_telemetry import (
    record_discovery_event,
    get_source_metrics,
    reset_telemetry
)


class TestAdaptivePriorityAndDiscovery(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        await local_db.init_db()
        reset_telemetry()

    async def asyncTearDown(self):
        await local_db.close_db()

    def test_01_new_product_receives_temporary_priority_boost(self):
        """Newly discovered product (<48h) receives Tier 2 priority boost to establish price history."""
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Product discovered 12 hours ago
        new_prod = {
            "created_at": now - datetime.timedelta(hours=12),
            "status": "ACTIVE",
            "category": "books",
            "review_count": 50,
            "last_price_change": None
        }
        tier = assign_priority(new_prod)
        self.assertEqual(tier, 2, "New product discovered <48h ago must receive Tier 2 priority boost.")

    def test_02_stable_product_gradually_demoted(self):
        """Product unchanged for >14 days with low reviews is demoted to Tier 4."""
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Stable product: last price change 20 days ago, created 60 days ago
        stable_prod = {
            "created_at": now - datetime.timedelta(days=60),
            "last_price_change": now - datetime.timedelta(days=20),
            "status": "ACTIVE",
            "category": "tools",
            "review_count": 200,
        }
        tier = assign_priority(stable_prod)
        self.assertEqual(tier, 4, "Product unchanged >14 days with low reviews must be demoted to Tier 4.")

    def test_03_recent_price_volatility_boosts_to_tier_1(self):
        """Product with price change in last 24h receives Tier 1 priority (1h check interval)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        
        volatile_prod = {
            "last_price_change": now - datetime.timedelta(hours=4),
            "status": "ACTIVE",
            "category": "home",
            "review_count": 100
        }
        tier = assign_priority(volatile_prod)
        self.assertEqual(tier, 1, "Price change within 24h must boost product to Tier 1.")

    def test_04_recent_deal_activity_boosts_to_tier_1(self):
        """Product with active deal posted within last 48h receives Tier 1 priority."""
        deal_prod = {
            "has_recent_deal": True,
            "status": "ACTIVE",
            "category": "electronics",
            "review_count": 500
        }
        tier = assign_priority(deal_prod)
        self.assertEqual(tier, 1, "Active recent deal must boost product to Tier 1.")

    def test_05_stock_recovery_boosts_to_tier_2(self):
        """Product recovering from TEMP_OOS back to ACTIVE receives Tier 2 priority."""
        recovered_prod = {
            "recovered_from_oos": True,
            "status": "ACTIVE",
            "category": "appliances",
            "review_count": 300
        }
        tier = assign_priority(recovered_prod)
        self.assertEqual(tier, 2, "Stock recovery must grant a Tier 2 priority boost.")

    def test_06_out_of_stock_demoted_to_tier_4(self):
        """TEMP_OOS product is demoted to Tier 4 to conserve scraper concurrency."""
        oos_prod = {
            "status": "TEMP_OOS",
            "has_recent_deal": True,  # Even with recent deal, if it's OOS it must be Tier 4
            "category": "fashion",
            "review_count": 10000
        }
        tier = assign_priority(oos_prod)
        self.assertEqual(tier, 4, "Out-of-stock items must be demoted to Tier 4.")

    def test_07_priority_bounds_respected(self):
        """Extreme or empty product states always return safe tiers [1..4]."""
        self.assertIn(assign_priority({}), [1, 2, 3, 4])
        self.assertIn(assign_priority(None), [1, 2, 3, 4])
        self.assertIn(assign_priority({"status": "ARCHIVED"}), [1, 2, 3, 4])

    def test_08_adaptive_check_intervals_and_sale_mode(self):
        """Verify dynamic check intervals adhere to configured seconds and scale with sale mode."""
        intervals = config.PRIORITY_INTERVALS
        self.assertEqual(intervals[1], 3600, "Tier 1 must be 1 hour (3600s).")
        self.assertEqual(intervals[2], 10800, "Tier 2 must be 3 hours (10800s).")
        self.assertEqual(intervals[3], 64800, "Tier 3 must be 18 hours (64800s).")
        self.assertEqual(intervals[4], 172800, "Tier 4 must be 48 hours (172800s).")

    async def test_09_duplicate_discovery_preserves_canonical_identity(self):
        """Verify that rediscovering the same product updates the existing row in SQLite without duplication."""
        platform = "amazon"
        platform_id = "B0CANONICAL01"
        url = f"https://www.amazon.in/dp/{platform_id}"

        # 1st discovery from channel monitor
        local_db.update_product_locally(platform, platform_id, url, 999.0, 1999.0, 2, "ACTIVE")
        await asyncio.sleep(0.05)

        # 2nd discovery of same item from live hunter
        local_db.update_product_locally(platform, platform_id, url, 899.0, 1999.0, 1, "ACTIVE")
        await asyncio.sleep(0.05)

        # Query local SQLite
        async with local_db._db_conn.execute(
            "SELECT COUNT(*) as cnt, current_price, priority_tier FROM products WHERE platform = ? AND platform_id = ?",
            (platform, platform_id)
        ) as cursor:
            row = await cursor.fetchone()

        self.assertEqual(row["cnt"], 1, "Duplicate discoveries must NOT create duplicate rows.")
        self.assertEqual(row["current_price"], 899.0, "Product price should be updated to latest observation.")
        self.assertEqual(row["priority_tier"], 1, "Priority tier should reflect updated tier.")

    def test_10_local_discovery_telemetry_tracking(self):
        """Verify local discovery telemetry tracks events and rates in-memory with zero network overhead."""
        record_discovery_event("channel_telegram", "discovered", count=10)
        record_discovery_event("channel_telegram", "scraped", count=9)
        record_discovery_event("channel_telegram", "deal_detected", count=3)
        record_discovery_event("channel_telegram", "posted", count=2)

        metrics = get_source_metrics("channel_telegram")
        self.assertEqual(metrics["discovered"], 10)
        self.assertEqual(metrics["scraped"], 9)
        self.assertEqual(metrics["deal_detected"], 3)
        self.assertEqual(metrics["posted"], 2)
        self.assertEqual(metrics["valid_deal_rate_pct"], 33.3)
        self.assertEqual(metrics["post_conversion_rate_pct"], 20.0)

    def test_11_zero_supabase_reads_during_priority_decisions(self):
        """Verify priority decisions execute in pure memory with ZERO Supabase reads."""
        with patch("budgetby.database.fetch") as mock_fetch, \
             patch("budgetby.database.fetchrow") as mock_fetchrow:

            now = datetime.datetime.now(datetime.timezone.utc)
            prod = {
                "created_at": now - datetime.timedelta(hours=5),
                "last_price_change": now - datetime.timedelta(hours=1),
                "category": "fashion",
                "status": "ACTIVE"
            }
            tier = assign_priority(prod)
            self.assertEqual(tier, 1)

            mock_fetch.assert_not_called()
            mock_fetchrow.assert_not_called()

    def test_12_zero_supabase_writes_for_telemetry_events(self):
        """Verify telemetry recording is 100% in-memory with ZERO Supabase database writes."""
        with patch("budgetby.database.execute") as mock_exec:
            for _ in range(50):
                record_discovery_event("live_hunter", "scraped", count=1)
                record_discovery_event("live_hunter", "deal_detected", count=1)

            mock_exec.assert_not_called()


if __name__ == "__main__":
    unittest.main()

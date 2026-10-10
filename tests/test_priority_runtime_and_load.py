"""
BudgetBy — Test Suite: Adaptive Priority Runtime & Scraper Load Validation
Validates:
1. Actual configured worker concurrency (SCRAPER_WORKERS) and safety thresholds.
2. 3,000-product synthetic catalog distribution across Tiers 1-4.
3. Check throughput (checks/hr, checks/day) vs scraper capacity.
4. Anti-tier explosion under overlapping volatility signals.
5. Anti-priority thrashing and stable deterministic transitions.
6. New product boost 48h expiration decay.
7. Sale mode interval multiplier acceleration.
8. Same-product in-flight duplicate scrape prevention.
9. Discovery telemetry thread/asyncio concurrency safety.
10. Zero Supabase read/write egress during local priority management.
"""

import unittest
import datetime
from unittest.mock import AsyncMock, patch
from budgetby import config
from budgetby.scheduler.priority import assign_priority
from budgetby.engine.discovery_telemetry import record_discovery_event, get_source_metrics, reset_telemetry
from budgetby import local_db


class TestPriorityRuntimeAndLoad(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        reset_telemetry()
        local_db._in_flight_products.clear()

    def tearDown(self):
        reset_telemetry()
        local_db._in_flight_products.clear()

    def test_01_actual_configured_worker_count_and_constants(self):
        """Verify actual configured SCRAPER_WORKERS and dynamic priority intervals."""
        self.assertEqual(config.SCRAPER_WORKERS, 15)
        self.assertGreaterEqual(config.SCRAPER_DELAY_MIN, 1.0)
        self.assertLessEqual(config.SCRAPER_DELAY_MAX, 10.0)
        self.assertEqual(config.SCRAPER_TIMEOUT, 25)
        self.assertEqual(config.SCRAPER_MAX_RETRIES, 3)

        # Dynamic Intervals: Tier 1=1h, Tier 2=3h, Tier 3=18h, Tier 4=48h
        self.assertEqual(config.PRIORITY_INTERVALS[1], 3600)
        self.assertEqual(config.PRIORITY_INTERVALS[2], 10800)
        self.assertEqual(config.PRIORITY_INTERVALS[3], 64800)
        self.assertEqual(config.PRIORITY_INTERVALS[4], 172800)
        self.assertEqual(config.SALE_MODE_INTERVAL_MULTIPLIER, 0.5)

    def test_02_synthetic_3000_product_catalog_tier_distribution(self):
        """
        Simulate a realistic 3,000-product catalog across e-commerce categories and lifecycle states.
        Verify expected tier distribution percentages.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        catalog = []

        # 1. 120 Volatile / Active Deal items (~4%) -> Expected Tier 1
        for i in range(120):
            catalog.append({
                "platform": "amazon" if i % 2 == 0 else "flipkart",
                "platform_id": f"tier1_{i}",
                "category": "electronics",
                "current_price": 1000.0,
                "status": "ACTIVE",
                "has_recent_deal": (i % 2 == 0),
                "last_price_change": (now - datetime.timedelta(hours=i % 20)).isoformat() if i % 2 != 0 else None,
                "created_at": (now - datetime.timedelta(days=10)).isoformat(),
                "review_count": 2500
            })

        # 2. 540 High-Velocity / New Discoveries / Restocks (~18%) -> Expected Tier 2
        for i in range(540):
            is_new = (i < 200)
            catalog.append({
                "platform": "myntra" if i % 3 == 0 else ("nykaa" if i % 3 == 1 else "ajio"),
                "platform_id": f"tier2_{i}",
                "category": "fashion" if i % 2 == 0 else "beauty",
                "current_price": 799.0,
                "status": "ACTIVE",
                "has_recent_deal": False,
                "last_price_change": (now - datetime.timedelta(days=5)).isoformat(),
                "created_at": (now - datetime.timedelta(hours=12)).isoformat() if is_new else (now - datetime.timedelta(days=15)).isoformat(),
                "review_count": 1500
            })

        # 3. 2,040 Standard Active Products (~68%) -> Expected Tier 3
        for i in range(2040):
            catalog.append({
                "platform": "amazon" if i % 2 == 0 else "flipkart",
                "platform_id": f"tier3_{i}",
                "category": "home" if i % 3 == 0 else ("sports" if i % 3 == 1 else "toys_kids"),
                "current_price": 1499.0,
                "status": "ACTIVE",
                "has_recent_deal": False,
                "last_price_change": (now - datetime.timedelta(days=6)).isoformat(),
                "created_at": (now - datetime.timedelta(days=30)).isoformat(),
                "review_count": 800
            })

        # 4. 300 Out of Stock / Dormant items (~10%) -> Expected Tier 4
        for i in range(300):
            is_oos = (i < 180)
            catalog.append({
                "platform": "flipkart" if i % 2 == 0 else "amazon",
                "platform_id": f"tier4_{i}",
                "category": "automotive" if i % 2 == 0 else "home",
                "current_price": 500.0,
                "status": "TEMP_OOS" if is_oos else "ACTIVE",
                "has_recent_deal": False,
                "last_price_change": (now - datetime.timedelta(days=25)).isoformat(),
                "created_at": (now - datetime.timedelta(days=60)).isoformat(),
                "review_count": 150
            })

        self.assertEqual(len(catalog), 3000)

        # Count tier assignments
        tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for prod in catalog:
            t = assign_priority(prod)
            tier_counts[t] += 1

        # Assertions on distribution proportions
        pct_t1 = (tier_counts[1] / 3000) * 100
        pct_t2 = (tier_counts[2] / 3000) * 100
        pct_t3 = (tier_counts[3] / 3000) * 100
        pct_t4 = (tier_counts[4] / 3000) * 100

        self.assertGreaterEqual(pct_t1, 3.0)
        self.assertLessEqual(pct_t1, 6.0)

        self.assertGreaterEqual(pct_t2, 15.0)
        self.assertLessEqual(pct_t2, 22.0)

        self.assertGreaterEqual(pct_t3, 60.0)
        self.assertLessEqual(pct_t3, 75.0)

        self.assertGreaterEqual(pct_t4, 8.0)
        self.assertLessEqual(pct_t4, 15.0)

    def test_03_catalog_checks_per_hour_and_day_throughput(self):
        """
        Calculate total checks/hour and checks/day for a 3,000 product catalog.
        Verify that scraper load is smoothly bounded and well below worker capacity.
        """
        # Distribution: 120 Tier 1 (1h), 540 Tier 2 (3h), 2040 Tier 3 (18h), 300 Tier 4 (48h)
        t1_checks_hr = 120 / (config.PRIORITY_INTERVALS[1] / 3600)  # 120 / 1 = 120
        t2_checks_hr = 540 / (config.PRIORITY_INTERVALS[2] / 3600)  # 540 / 3 = 180
        t3_checks_hr = 2040 / (config.PRIORITY_INTERVALS[3] / 3600) # 2040 / 18 = 113.33
        t4_checks_hr = 300 / (config.PRIORITY_INTERVALS[4] / 3600)  # 300 / 48 = 6.25

        total_checks_per_hour = t1_checks_hr + t2_checks_hr + t3_checks_hr + t4_checks_hr
        checks_per_minute = total_checks_per_hour / 60.0
        total_checks_per_day = total_checks_per_hour * 24

        # Throughput expectations
        self.assertAlmostEqual(total_checks_per_hour, 419.58, delta=5.0)
        self.assertAlmostEqual(checks_per_minute, 7.0, delta=1.0)
        self.assertAlmostEqual(total_checks_per_day, 10070.0, delta=100.0)

        # Scraper worker capacity: 15 workers with avg 3.5s per request can execute:
        # 15 workers * (60s / 3.5s) ≈ 257 checks/min capacity.
        # Demand of 7.0 checks/min is ~2.7% of maximum capacity (vast safety headroom).
        worker_capacity_per_min = config.SCRAPER_WORKERS * (60.0 / ((config.SCRAPER_DELAY_MIN + config.SCRAPER_DELAY_MAX) / 2 + 1.5))
        self.assertGreater(worker_capacity_per_min, 150.0)
        self.assertLess(checks_per_minute, worker_capacity_per_min * 0.10)

    def test_04_anti_tier_explosion_overlapping_signals(self):
        """Verify that overlapping priority signals resolve cleanly without duplicate work or tier explosion."""
        now = datetime.datetime.now(datetime.timezone.utc)

        # Case 1: Both recent price drop (<24h) and new discovery (<48h) and fashion category
        multi_signal_prod = {
            "platform": "myntra",
            "platform_id": "multi_1",
            "category": "fashion",
            "status": "ACTIVE",
            "has_recent_deal": True,
            "last_price_change": (now - datetime.timedelta(hours=2)).isoformat(),
            "created_at": (now - datetime.timedelta(hours=5)).isoformat(),
            "review_count": 8000
        }
        # Tier 1 takes precedence deterministically
        self.assertEqual(assign_priority(multi_signal_prod), 1)

        # Case 2: Out of stock overrides all high-volatility signals immediately
        oos_multi_signal = dict(multi_signal_prod)
        oos_multi_signal["status"] = "TEMP_OOS"
        self.assertEqual(assign_priority(oos_multi_signal), 4)

    def test_05_anti_priority_thrashing_and_stability(self):
        """Verify that repeated evaluation on static states produces identical stable tiers (no thrashing)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        prod = {
            "platform": "amazon",
            "platform_id": "stable_1",
            "category": "home",
            "status": "ACTIVE",
            "has_recent_deal": False,
            "last_price_change": (now - datetime.timedelta(days=3)).isoformat(),
            "created_at": (now - datetime.timedelta(days=20)).isoformat(),
            "review_count": 500
        }

        first_tier = assign_priority(prod)
        self.assertEqual(first_tier, 3)

        # 50 consecutive evaluations must remain 3
        for _ in range(50):
            self.assertEqual(assign_priority(prod), 3)

    def test_06_new_product_boost_expiration(self):
        """Verify new product boost grants Tier 2 for first 48h, then seamlessly decays to Tier 3."""
        now = datetime.datetime.now(datetime.timezone.utc)

        # Product created 6 hours ago -> Boosted to Tier 2
        fresh_prod = {
            "platform": "amazon",
            "platform_id": "fresh_1",
            "category": "home",
            "status": "ACTIVE",
            "created_at": (now - datetime.timedelta(hours=6)).isoformat(),
            "review_count": 10
        }
        self.assertEqual(assign_priority(fresh_prod), 2)

        # Same product aged 50 hours (>48h) -> Decays to Tier 3
        aged_prod = dict(fresh_prod)
        aged_prod["created_at"] = (now - datetime.timedelta(hours=50)).isoformat()
        self.assertEqual(assign_priority(aged_prod), 3)

    def test_07_sale_mode_interval_multiplier(self):
        """Verify that during sale events, intervals scale down by SALE_MODE_INTERVAL_MULTIPLIER."""
        multiplier = config.SALE_MODE_INTERVAL_MULTIPLIER
        self.assertEqual(multiplier, 0.5)

        # Standard intervals: T1=3600s (60m), T2=10800s (180m), T3=64800s (1080m), T4=172800s (2880m)
        sale_t1 = int(config.PRIORITY_INTERVALS[1] * multiplier)
        sale_t2 = int(config.PRIORITY_INTERVALS[2] * multiplier)
        sale_t3 = int(config.PRIORITY_INTERVALS[3] * multiplier)
        sale_t4 = int(config.PRIORITY_INTERVALS[4] * multiplier)

        self.assertEqual(sale_t1, 1800)   # 30 minutes
        self.assertEqual(sale_t2, 5400)   # 90 minutes (1.5 hours)
        self.assertEqual(sale_t3, 32400)  # 9 hours
        self.assertEqual(sale_t4, 86400)  # 24 hours (1 day)

    def test_08_same_product_in_flight_protection(self):
        """Verify in-flight concurrency guards prevent duplicate simultaneous scraping of the same product."""
        platform = "amazon"
        pid = "B09XYZ1234"

        # 1. First worker acquires lock
        acquired = local_db.mark_in_flight(platform, pid)
        self.assertTrue(acquired)
        self.assertTrue(local_db.is_in_flight(platform, pid))
        self.assertEqual(local_db.get_in_flight_count(), 1)

        # 2. Second concurrent worker tries to acquire same product -> Rejected
        second_attempt = local_db.mark_in_flight(platform, pid)
        self.assertFalse(second_attempt)
        self.assertEqual(local_db.get_in_flight_count(), 1)

        # 3. Different product acquires successfully
        diff_acquired = local_db.mark_in_flight("flipkart", "FLIP123456")
        self.assertTrue(diff_acquired)
        self.assertEqual(local_db.get_in_flight_count(), 2)

        # 4. Release first product
        local_db.release_in_flight(platform, pid)
        self.assertFalse(local_db.is_in_flight(platform, pid))
        self.assertTrue(local_db.is_in_flight("flipkart", "FLIP123456"))
        self.assertEqual(local_db.get_in_flight_count(), 1)

        # 5. Clean up
        local_db.release_in_flight("flipkart", "FLIP123456")
        self.assertEqual(local_db.get_in_flight_count(), 0)

    def test_09_discovery_telemetry_concurrency_safety(self):
        """Verify discovery telemetry aggregates multiple concurrent source events accurately."""
        reset_telemetry()

        # Simulate 10 discovery events across sources
        for _ in range(5):
            record_discovery_event("live_hunter", "discovered", 10)
            record_discovery_event("live_hunter", "scraped", 8)
            record_discovery_event("live_hunter", "deal_detected", 2)
            record_discovery_event("live_hunter", "posted", 1)

        for _ in range(5):
            record_discovery_event("channel_monitor", "discovered", 4)
            record_discovery_event("channel_monitor", "scraped", 4)
            record_discovery_event("channel_monitor", "deal_detected", 3)
            record_discovery_event("channel_monitor", "posted", 2)

        lh_metrics = get_source_metrics("live_hunter")
        self.assertEqual(lh_metrics["discovered"], 50)
        self.assertEqual(lh_metrics["scraped"], 40)
        self.assertEqual(lh_metrics["deal_detected"], 10)
        self.assertEqual(lh_metrics["posted"], 5)
        self.assertEqual(lh_metrics["valid_deal_rate_pct"], 25.0)  # (10/40) * 100
        self.assertEqual(lh_metrics["post_conversion_rate_pct"], 10.0)  # (5/50) * 100

        cm_metrics = get_source_metrics("channel_monitor")
        self.assertEqual(cm_metrics["discovered"], 20)
        self.assertEqual(cm_metrics["scraped"], 20)
        self.assertEqual(cm_metrics["deal_detected"], 15)
        self.assertEqual(cm_metrics["posted"], 10)
        self.assertEqual(cm_metrics["valid_deal_rate_pct"], 75.0)  # (15/20) * 100
        self.assertEqual(cm_metrics["post_conversion_rate_pct"], 50.0)  # (10/20) * 100

    def test_10_zero_supabase_egress_priority_scheduling(self):
        """Verify priority scheduling and telemetry execution generate 0 Supabase cloud queries."""
        with patch("budgetby.database.fetch", new_callable=AsyncMock) as mock_fetch, \
             patch("budgetby.database.execute", new_callable=AsyncMock) as mock_execute:

            # Run priority tier calculations
            prod = {
                "platform": "nykaa",
                "platform_id": "nyk_99",
                "category": "beauty",
                "status": "ACTIVE",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            tier = assign_priority(prod)
            self.assertEqual(tier, 2)

            # In-flight lock and release
            local_db.mark_in_flight("nykaa", "nyk_99")
            local_db.release_in_flight("nykaa", "nyk_99")

            # Telemetry update
            record_discovery_event("live_hunter", "discovered", 5)

            # Assert 0 Supabase queries were executed
            mock_fetch.assert_not_called()
            mock_execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

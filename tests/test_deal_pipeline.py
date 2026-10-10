"""
Unit Tests for BudgetBy Deal Pipeline Interfaces
Tests:
1. Deal detector -> fake discount
2. Fake discount async behavior
3. Deal detector -> scorer
4. Scorer -> posting queue
5. Duplicate / cooldown behavior
6. Telegram path does not depend on Supabase sync
"""

import sys
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from budgetby.engine.deal_detector import detect_deal
from budgetby.engine.fake_discount import is_fake_discount
from budgetby.engine.deal_scorer import score_deal
from budgetby.engine.posting_queue import PostingQueue, get_posting_queue
from budgetby.engine.cooldown import is_on_cooldown, _cooldown_cache


class TestDealPipeline(unittest.IsolatedAsyncioTestCase):

    async def test_fake_discount_async_behavior(self):
        """Test 2: Verify fake discount is async and correctly evaluates."""
        legit_product = {
            "mrp": 1500.0,
            "current_price": 800.0,
            "previous_price": 1000.0,
            "median_30d_price": 1000.0
        }
        # A normal price drop from 1000 to 500
        self.assertFalse(await is_fake_discount(legit_product, 500.0))

        # A fake discount where MRP was inflated by >20% and price is within 10% of median
        fake_product = {
            "mrp": 2000.0,
            "previous_price": 1000.0,  # MRP (2000) is >20% above previous (1000)
            "current_price": 980.0,
            "median_30d_price": 1000.0 # 980 is within 10% of median (1000)
        }
        self.assertTrue(await is_fake_discount(fake_product, 980.0))

    async def test_deal_detector_and_fake_discount_integration(self):
        """Test 1: Verify deal_detector integrates with fake_discount."""
        # Valid drop with All-Time Low
        valid_prod = {
            "id": 101,
            "platform": "amazon",
            "title": "Sony Wireless Headphones",
            "mrp": 5000.0,
            "previous_price": 4000.0,
            "current_price": 4000.0,
            "all_time_low": 3000.0,
            "min_30d": 3500.0,
            "median_30d_price": 3800.0,
            "category": "electronics"
        }
        deal = await detect_deal(valid_prod, 2800.0)
        self.assertIsNotNone(deal)
        self.assertTrue(deal["should_post"])
        self.assertEqual(deal["badge"], "ATL")
        self.assertFalse(deal["is_fake_discount"])
        self.assertGreater(deal["savings_pct"], 0.4)

        # Product with fake discount -> should be rejected by detect_deal
        fake_prod = {
            "id": 102,
            "platform": "amazon",
            "title": "Inflated Brand T-Shirt",
            "mrp": 2000.0,
            "previous_price": 1000.0,
            "current_price": 1000.0,
            "median_30d_price": 1000.0,
            "category": "fashion"
        }
        fake_deal = await detect_deal(fake_prod, 980.0)
        self.assertIsNone(fake_deal)

    async def test_deal_detector_to_scorer(self):
        """Test 3: Verify scorer receives (product, deal_result) and produces 0-100 float score."""
        prod = {
            "id": 201,
            "platform": "myntra",
            "category": "fashion",
            "current_price": 1200.0,
            "previous_price": 2500.0,
            "mrp": 3000.0,
            "rating": 4.5,
            "review_count": 1200,
            "all_time_low": 1500.0
        }
        deal = await detect_deal(prod, 1200.0)
        self.assertIsNotNone(deal)

        score = score_deal(prod, deal)
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
        # Because it's an ATL with >50% discount and 4.5 rating, score should be high (>= 60)
        self.assertGreater(score, 60.0)

    async def test_scorer_to_posting_queue(self):
        """Test 4: Scorer output formatted into deal_data and queued properly."""
        pq = PostingQueue()
        # Reset queue state for clean test
        while not pq._queue.empty():
            try:
                pq._queue.get_nowait()
            except Exception:
                break
        pq._queued_pids.clear()

        deal_data = {
            "product": {
                "id": 301,
                "platform": "flipkart",
                "platform_id": "FK12345",
                "title": "Puma Running Shoes",
                "current_price": 1499.0,
                "mrp": 4999.0,
                "rating": 4.3,
                "review_count": 500,
                "category": "footwear",
                "product_url": "https://www.flipkart.com/puma-shoes/p/itm123",
                "affiliate_url": "https://www.flipkart.com/puma-shoes/p/itm123"
            },
            "type": "price_drop",
            "badge": "LOOT",
            "score": 85.0,
            "source_channel": "scheduler"
        }

        # Test async queue_deal
        await pq.queue_deal(deal_data)
        self.assertEqual(pq._queue.qsize(), 1)
        self.assertIn(301, pq._queued_pids)

        # Test sync add_deal method alias
        deal_data_2 = {
            "product": {
                "id": 302,
                "platform": "amazon",
                "platform_id": "B08TESTASIN",
                "title": "Echo Dot Smart Speaker",
                "current_price": 2499.0,
                "mrp": 4499.0,
                "product_url": "https://www.amazon.in/dp/B08TESTASIN"
            },
            "type": "price_drop",
            "badge": "HOT_DEAL",
            "score": 75.0,
            "source_channel": "scheduler"
        }
        pq.add_deal(deal_data_2)
        # Allow event loop to process scheduled task
        await asyncio.sleep(0.01)
        self.assertIn(302, pq._queued_pids)

    async def test_duplicate_and_cooldown_behavior(self):
        """Test 5: Verify duplicate deals and cooldown checks."""
        pq = PostingQueue()
        pq._queued_pids.clear()
        while not pq._queue.empty():
            try:
                pq._queue.get_nowait()
            except Exception:
                break

        deal_data = {
            "product": {
                "id": 401,
                "platform": "ajio",
                "platform_id": "AJ123456",
                "title": "Levis Denim Jacket",
                "current_price": 1999.0,
                "mrp": 4999.0
            },
            "type": "price_drop",
            "badge": "DEAL",
            "score": 70.0
        }

        # First enqueue succeeds
        await pq.queue_deal(deal_data)
        self.assertEqual(pq._queue.qsize(), 1)

        # Duplicate enqueue with same pid is blocked
        await pq.queue_deal(deal_data)
        self.assertEqual(pq._queue.qsize(), 1)

        # Test cooldown memory cache
        _cooldown_cache[401] = (True, 9999999999.0)
        deal_data_cooldown = {
            "product": {
                "id": 401,
                "platform": "ajio",
                "title": "Levis Denim Jacket"
            }
        }
        pq._queued_pids.discard(401)
        # Even though removed from queued_pids, cooldown blocks it
        await pq.queue_deal(deal_data_cooldown)
        self.assertEqual(pq._queue.qsize(), 1) # Size remains 1

    async def test_telegram_path_does_not_depend_on_supabase_sync(self):
        """Test 6: Verify Telegram message is dispatched immediately before database write."""
        pq = PostingQueue()
        mock_bot = MagicMock()
        mock_sent_msg = MagicMock()
        mock_sent_msg.message_id = 98765
        mock_bot.send_photo = AsyncMock(return_value=mock_sent_msg)
        mock_bot.send_message = AsyncMock(return_value=mock_sent_msg)

        deal_data = {
            "product": {
                "id": 501,
                "platform": "amazon",
                "platform_id": "B0TEST501",
                "title": "Logitech Wireless Mouse",
                "current_price": 599.0,
                "mrp": 1299.0,
                "image_url": "https://example.com/mouse.jpg",
                "product_url": "https://www.amazon.in/dp/B0TEST501"
            },
            "type": "price_drop",
            "badge": "PRICE_DROP",
            "score": 70.0,
            "source_channel": "scheduler"
        }

        call_order = []

        async def fake_send_to_telegram(*args, **kwargs):
            call_order.append("TELEGRAM_SEND")
            return mock_sent_msg

        async def fake_insert_deal(*args, **kwargs):
            call_order.append("DATABASE_INSERT")
            return 501

        async def fake_set_cooldown(*args, **kwargs):
            call_order.append("SET_COOLDOWN")

        with patch.object(pq, "_send_to_telegram", side_effect=fake_send_to_telegram), \
             patch("budgetby.database.insert_deal", side_effect=fake_insert_deal), \
             patch("budgetby.engine.cooldown.set_cooldown", side_effect=fake_set_cooldown), \
             patch("budgetby.engine.cooldown.is_on_cooldown", new_callable=AsyncMock, return_value=False):

            success = await pq._post_queued_deal(deal_data, mock_bot)

            self.assertTrue(success)
            self.assertEqual(call_order[0], "TELEGRAM_SEND")
            self.assertEqual(call_order[1], "DATABASE_INSERT")
            self.assertEqual(call_order[2], "SET_COOLDOWN")

    async def test_variant_mismatch_anomaly_guard(self):
        """Verify extreme drops (>75% on >2000 INR items) are rejected as SKU variant mismatch anomalies."""
        anomaly_prod = {
            "id": 601,
            "platform": "amazon",
            "title": "Luxury Face Serum 50ml",
            "mrp": 3500.0,
            "current_price": 3000.0,
            "previous_price": 3000.0,
            "category": "beauty"
        }
        # Dropping from 3000 to 499 (>75% drop on >2000 item -> SKU variant switch)
        deal = await detect_deal(anomaly_prod, 499.0)
        self.assertIsNone(deal)

    def test_score_deal_clamping_and_penalties(self):
        """Verify score_deal clamps between 0.0 and 100.0 and handles empty or extreme inputs."""
        empty_score = score_deal({}, {})
        self.assertEqual(empty_score, 0.0)

        fake_detection = {
            "savings_pct": 0.02,
            "badge": "none",
            "is_fake_discount": True
        }
        low_prod = {
            "current_price": 50.0,
            "review_count": 0,
            "category": "default",
            "platform": "amazon"
        }
        penalty_score = score_deal(low_prod, fake_detection)
        self.assertGreaterEqual(penalty_score, 0.0)
        self.assertLessEqual(penalty_score, 100.0)


if __name__ == "__main__":
    unittest.main()

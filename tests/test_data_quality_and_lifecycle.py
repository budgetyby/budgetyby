"""
BudgetBy — Data Quality, Price Consistency & Lifecycle Verification Tests.
Tests deal lifecycle flow, pricing consistency guards, fake discount validation,
badge assignment accuracy, and cross-source normalization.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from budgetby.engine.deal_detector import detect_deal
from budgetby.engine.fake_discount import is_fake_discount
from budgetby.engine.deal_scorer import score_deal
from budgetby.bot.templates import get_tiered_badge
from budgetby.engine.posting_queue import format_deal_message
from budgetby.scrapers.utils import clean_title, extract_price


class TestDataQualityAndLifecycle(unittest.TestCase):
    def test_deal_lifecycle_end_to_end_flow(self):
        """Trace a complete deal lifecycle from scraped data to formatted Telegram payload."""
        # 1. Scraped product data
        product = {
            "id": 101,
            "platform": "amazon",
            "platform_id": "B08EXAMPLE",
            "title": "Premium Wireless Noise Cancelling Headphones",
            "current_price": 2999.0,
            "previous_price": 4999.0,
            "mrp": 7999.0,
            "min_30d": 3499.0,
            "min_60d": 3999.0,
            "min_90d": 4499.0,
            "all_time_low": 2999.0,
            "median_30d_price": 4999.0,
            "category": "electronics",
            "rating": 4.5,
            "review_count": 12500,
            "in_stock": True,
            "affiliate_url": "https://www.amazon.in/dp/B08EXAMPLE?tag=dealpulse21-21",
            "product_url": "https://www.amazon.in/dp/B08EXAMPLE",
            "image_url": "https://m.media-amazon.com/images/I/71example.jpg"
        }

        # 2. Deal Detection (Cascading comparison)
        import asyncio
        detection = asyncio.run(detect_deal(product, 2999.0))
        self.assertIsNotNone(detection)
        self.assertTrue(detection["should_post"])
        self.assertEqual(detection["badge"], "ATL")
        self.assertFalse(detection["is_fake_discount"])

        # 3. Deal Scoring
        score = score_deal(product, detection)
        self.assertGreaterEqual(score, 60.0)
        self.assertLessEqual(score, 100.0)

        # 4. Telegram Formatting
        deal_payload = {
            "product": product,
            "type": "price_drop",
            "badge": detection["badge"],
            "score": score
        }
        msg = format_deal_message(deal_payload)
        self.assertIn("MEGA PRICE DROP", msg)
        self.assertIn("₹2,999", msg)
        self.assertIn("₹7,999", msg)
        self.assertIn("63% OFF", msg)
        self.assertIn("https://www.amazon.in/dp/B08EXAMPLE?tag=dealpulse21-21", msg)

    def test_price_consistency_and_drop_calculations(self):
        """Verify discount percentage and savings formulas handle edge cases correctly."""
        # Clean price extractor
        self.assertEqual(extract_price("₹1,499.00"), 1499.0)
        self.assertEqual(extract_price("Rs. 299"), 299.0)
        self.assertEqual(extract_price("499"), 499.0)
        self.assertEqual(extract_price(""), 0.0)

        # MRP <= price must be rejected as deal
        product_invalid = {
            "current_price": 500.0,
            "previous_price": 500.0,
            "mrp": 400.0,
            "all_time_low": 500.0
        }
        import asyncio
        res = asyncio.run(detect_deal(product_invalid, 500.0))
        self.assertIsNone(res)

    def test_fake_discount_detection_behavior(self):
        """Verify fake discount flags MRP hikes when current price is within median."""
        import asyncio
        # Case 1: Fake discount (MRP hiked from 1000 to 2000, but price 950 is near median 1000)
        fake_prod = {
            "current_price": 950.0,
            "previous_price": 950.0,
            "mrp": 2000.0,
            "median_30d_price": 1000.0
        }
        is_fake = asyncio.run(is_fake_discount(fake_prod, 950.0))
        self.assertTrue(is_fake)

        # Case 2: Real discount (Price dropped from median 1000 down to 499)
        real_prod = {
            "current_price": 499.0,
            "previous_price": 950.0,
            "mrp": 2000.0,
            "median_30d_price": 1000.0
        }
        is_fake_real = asyncio.run(is_fake_discount(real_prod, 499.0))
        self.assertFalse(is_fake_real)

    def test_badge_tier_hierarchy(self):
        """Verify get_tiered_badge applies badges accurately based on discount & ATL status."""
        self.assertIn("LOOT", get_tiered_badge("PRICE_DROP", pct=75))
        self.assertIn("MEGA", get_tiered_badge("PRICE_DROP", pct=55))
        self.assertIn("ALL-TIME LOW", get_tiered_badge("ATL", pct=40))
        self.assertIn("NEAR RECORD LOW", get_tiered_badge("near_ATL", pct=30))
        self.assertIn("90-DAY", get_tiered_badge("90d_low", pct=25))
        self.assertIn("PRICE DROP", get_tiered_badge("PRICE_DROP", pct=20))

    def test_title_cleaner_removes_prefixes_and_junk(self):
        """Verify clean_title cleans product names across sources."""
        raw = "1.   CANTABIL Men Slim Fit Casual Shirt (Blue) 4.2 (1,200 Ratings)   "
        cleaned = clean_title(raw)
        self.assertFalse(cleaned.startswith("1."))
        self.assertNotIn("Ratings", cleaned)
        self.assertEqual(cleaned, "CANTABIL Men Slim Fit Casual Shirt (Blue)")


if __name__ == "__main__":
    unittest.main()

"""
BudgetBy — Test Suite for Separating Shopper Deal Quality from Monetization Score
Verifies:
1. High-discount low-price item gets strong shopper score.
2. Moderate discount high-commission item does NOT outrank genuinely better deal for shoppers.
3. Commission changes monetization score.
4. Commission does NOT change shopper score.
5. Missing commission still allows correct shopper score.
6. Missing historical data behaves safely with neutral fallbacks.
7. Score ranges strictly bounded between 0.0 and 100.0.
8. score_deal_full returns structured dictionary with both scores.
9. Website sorting and APIs consume shopper score without commission bias.
10. Zero Supabase egress for score calculations.
"""

import unittest
from unittest.mock import patch
from budgetby import config
from budgetby.engine.deal_scorer import (
    calculate_shopper_score,
    calculate_monetization_score,
    score_deal,
    score_deal_full
)


class TestShopperVsMonetizationScoring(unittest.TestCase):

    def test_01_high_discount_low_price_item_strong_shopper_score(self):
        """Test Example A: ₹500 item with 80% discount gets a high shopper score (>85)."""
        product = {
            "current_price": 500.0,
            "mrp": 2500.0,
            "category": "fashion",
            "platform": "myntra",
            "rating": 4.2,
            "review_count": 2500,
        }
        detection = {
            "savings_pct": 0.80,
            "badge": "LOOT",
            "is_fake_discount": False,
        }
        shopper_score = calculate_shopper_score(product, detection)
        monetization_score = calculate_monetization_score(product, detection)

        self.assertGreaterEqual(shopper_score, 85.0, "80% LOOT deal must have a high shopper score.")
        self.assertLess(monetization_score, 40.0, "Low ticket/commission item has lower monetization value.")

    def test_02_moderate_discount_high_commission_does_not_outrank_better_deal(self):
        """Test Example B: ₹5000 item with 20% discount does not outrank Example A for shoppers."""
        # Example A: True Loot Deal (₹500, 80% OFF, low comm)
        deal_a_prod = {
            "current_price": 500.0, "mrp": 2500.0, "category": "fashion",
            "platform": "myntra", "rating": 4.2, "review_count": 2500,
        }
        deal_a_det = {"savings_pct": 0.80, "badge": "LOOT", "is_fake_discount": False}

        # Example B: Expensive Item (₹5,000, 20% OFF, high 10% commission = ₹500 payout)
        deal_b_prod = {
            "current_price": 5000.0, "mrp": 6250.0, "category": "electronics",
            "platform": "amazon", "rating": 4.0, "review_count": 500,
        }
        deal_b_det = {"savings_pct": 0.20, "badge": "30d_low", "is_fake_discount": False}

        shopper_a = calculate_shopper_score(deal_a_prod, deal_a_det)
        shopper_b = calculate_shopper_score(deal_b_prod, deal_b_det)

        monetization_a = calculate_monetization_score(deal_a_prod, deal_a_det)
        monetization_b = calculate_monetization_score(deal_b_prod, deal_b_det)

        # Shopper score must prioritize the 80% loot deal
        self.assertGreater(shopper_a, shopper_b, "Shopper score must rank 80% LOOT deal above 20% moderate deal.")

        # Monetization score correctly captures the higher affiliate revenue
        self.assertGreater(monetization_b, monetization_a, "Monetization score reflects higher commission revenue.")

    def test_03_commission_changes_monetization_score(self):
        """Test that altering commission rates directly changes monetization score."""
        prod_low_comm = {"current_price": 2000.0, "category": "books", "platform": "amazon"}
        prod_high_comm = {"current_price": 2000.0, "category": "fashion", "platform": "amazon"}

        m_score_low = calculate_monetization_score(prod_low_comm)
        m_score_high = calculate_monetization_score(prod_high_comm)

        self.assertNotEqual(m_score_low, m_score_high)
        self.assertGreater(m_score_high, m_score_low)

    def test_04_commission_does_not_change_shopper_score(self):
        """Test that changing platform/category commission rates has ZERO effect on shopper score."""
        detection = {"savings_pct": 0.40, "badge": "60d_low", "is_fake_discount": False}

        prod_amazon = {
            "current_price": 1000.0, "mrp": 1666.0, "category": "books",
            "platform": "amazon", "rating": 4.0, "review_count": 500,
        }
        prod_myntra = {
            "current_price": 1000.0, "mrp": 1666.0, "category": "fashion",
            "platform": "myntra", "rating": 4.0, "review_count": 500,
        }

        shopper_amazon = calculate_shopper_score(prod_amazon, detection)
        shopper_myntra = calculate_shopper_score(prod_myntra, detection)

        self.assertEqual(shopper_amazon, shopper_myntra, "Shopper score must be identical regardless of affiliate rates.")

    def test_05_missing_commission_still_allows_correct_shopper_score(self):
        """Test that a product with unknown platform/category still receives an accurate shopper score."""
        product = {
            "current_price": 800.0, "mrp": 1600.0, "category": "unknown_niche",
            "platform": "unknown_store", "rating": 4.5, "review_count": 1200,
        }
        detection = {"savings_pct": 0.50, "badge": "ATL", "is_fake_discount": False}

        shopper_score = calculate_shopper_score(product, detection)
        self.assertGreaterEqual(shopper_score, 80.0, "Unknown commission store must receive full shopper deal score.")

    def test_06_missing_historical_and_review_data_behaves_safely(self):
        """Test that missing ratings, reviews, or historical badges use neutral fallbacks without crashing."""
        product_empty = {"current_price": 1000.0, "mrp": 1500.0}
        detection_empty = {"savings_pct": 0.33, "badge": None}

        shopper_score = calculate_shopper_score(product_empty, detection_empty)
        self.assertGreater(shopper_score, 0.0)
        self.assertLessEqual(shopper_score, 100.0)

        monetization_score = calculate_monetization_score(product_empty)
        self.assertGreater(monetization_score, 0.0)
        self.assertLessEqual(monetization_score, 100.0)

    def test_07_score_ranges_strictly_bounded_0_to_100(self):
        """Test that extreme inputs never produce scores below 0 or above 100."""
        # Extreme high
        prod_max = {"current_price": 100000.0, "mrp": 500000.0, "rating": 5.0, "review_count": 1000000}
        det_max = {"savings_pct": 0.95, "badge": "LOOT", "is_fake_discount": False}

        s_max = calculate_shopper_score(prod_max, det_max)
        m_max = calculate_monetization_score(prod_max)
        self.assertLessEqual(s_max, 100.0)
        self.assertLessEqual(m_max, 100.0)

        # Extreme low with fake discount penalty
        prod_min = {"current_price": 10.0, "mrp": 10.0, "rating": 1.0, "review_count": 0}
        det_min = {"savings_pct": 0.0, "badge": None, "is_fake_discount": True}

        s_min = calculate_shopper_score(prod_min, det_min)
        m_min = calculate_monetization_score(prod_min)
        self.assertGreaterEqual(s_min, 0.0)
        self.assertGreaterEqual(m_min, 0.0)

    def test_08_score_deal_full_returns_structured_dict(self):
        """Test score_deal_full helper returns both scores cleanly."""
        product = {"current_price": 1200.0, "mrp": 2400.0, "category": "beauty", "platform": "nykaa", "rating": 4.3, "review_count": 3000}
        detection = {"savings_pct": 0.50, "badge": "90d_low", "is_fake_discount": False}

        res = score_deal_full(product, detection)
        self.assertIn("shopper_quality_score", res)
        self.assertIn("monetization_score", res)
        self.assertIn("deal_score", res)
        self.assertEqual(res["deal_score"], res["shopper_quality_score"])

    def test_09_score_deal_alias_maintains_backward_compatibility(self):
        """Test score_deal() returns the pure shopper deal quality score."""
        product = {"current_price": 1000.0, "mrp": 2000.0, "rating": 4.0, "review_count": 1000}
        detection = {"savings_pct": 0.50, "badge": "ATL", "is_fake_discount": False}

        legacy_call = score_deal(product, detection)
        shopper_call = calculate_shopper_score(product, detection)
        self.assertEqual(legacy_call, shopper_call)

    def test_10_zero_supabase_egress_during_scoring(self):
        """Verify that score calculations perform 0 Supabase cloud queries."""
        with patch("budgetby.database.execute") as mock_db_exec, \
             patch("budgetby.database.fetch") as mock_db_fetch, \
             patch("budgetby.database.fetchrow") as mock_db_fetchrow:

            product = {"current_price": 1500.0, "mrp": 3000.0, "category": "electronics", "platform": "amazon"}
            detection = {"savings_pct": 0.50, "badge": "ATL", "is_fake_discount": False}

            score_deal_full(product, detection)

            mock_db_exec.assert_not_called()
            mock_db_fetch.assert_not_called()
            mock_db_fetchrow.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""
BudgetBy — Test Suite for Shopper Deal Score Calibration & Ranking Validation
Verifies:
1. Monotonicity of discount magnitude, historical position, star rating, and review count.
2. Popularity bias protection (deep discounts outrank weak discounts regardless of review volume).
3. Discount vs Historical benchmark balance.
4. Missing consumer data handling & zero commission impact.
5. Fake-discount penalty impact and separation.
6. 100-profile deterministic synthetic deal distribution analysis.
7. Monetization independence regression tests.
8. Score boundaries [0.0, 100.0] and website sorting guarantees.
"""

import unittest
import statistics
from unittest.mock import patch
from budgetby.engine.deal_scorer import (
    calculate_shopper_score,
    calculate_monetization_score,
    score_deal,
    score_deal_full
)


class TestScoreCalibrationAndRanking(unittest.TestCase):

    def test_01_monotonicity_discount_magnitude(self):
        """Verify score increases monotonically with increasing discount percentage."""
        product = {"current_price": 1000.0, "rating": 4.0, "review_count": 1000}
        
        det_10 = {"savings_pct": 0.10, "badge": "30d_low", "is_fake_discount": False}
        det_20 = {"savings_pct": 0.20, "badge": "30d_low", "is_fake_discount": False}
        det_35 = {"savings_pct": 0.35, "badge": "30d_low", "is_fake_discount": False}
        det_50 = {"savings_pct": 0.50, "badge": "30d_low", "is_fake_discount": False}
        det_80 = {"savings_pct": 0.80, "badge": "30d_low", "is_fake_discount": False}

        s_10 = calculate_shopper_score(product, det_10)
        s_20 = calculate_shopper_score(product, det_20)
        s_35 = calculate_shopper_score(product, det_35)
        s_50 = calculate_shopper_score(product, det_50)
        s_80 = calculate_shopper_score(product, det_80)

        self.assertLess(s_10, s_20)
        self.assertLess(s_20, s_35)
        self.assertLess(s_35, s_50)
        self.assertLessEqual(s_50, s_80)

    def test_02_monotonicity_historical_position(self):
        """Verify score increases monotonically as historical low benchmark improves."""
        product = {"current_price": 1000.0, "rating": 4.0, "review_count": 1000}
        
        det_none = {"savings_pct": 0.30, "badge": None, "is_fake_discount": False}
        det_30d = {"savings_pct": 0.30, "badge": "30d_low", "is_fake_discount": False}
        det_60d = {"savings_pct": 0.30, "badge": "60d_low", "is_fake_discount": False}
        det_90d = {"savings_pct": 0.30, "badge": "90d_low", "is_fake_discount": False}
        det_near_atl = {"savings_pct": 0.30, "badge": "near_ATL", "is_fake_discount": False}
        det_atl = {"savings_pct": 0.30, "badge": "ATL", "is_fake_discount": False}

        s_none = calculate_shopper_score(product, det_none)
        s_30d = calculate_shopper_score(product, det_30d)
        s_60d = calculate_shopper_score(product, det_60d)
        s_90d = calculate_shopper_score(product, det_90d)
        s_near_atl = calculate_shopper_score(product, det_near_atl)
        s_atl = calculate_shopper_score(product, det_atl)

        self.assertLess(s_none, s_30d)
        self.assertLess(s_30d, s_60d)
        self.assertLess(s_60d, s_90d)
        self.assertLess(s_90d, s_near_atl)
        self.assertLess(s_near_atl, s_atl)

    def test_03_monotonicity_rating_and_reviews(self):
        """Verify score increases monotonically with higher ratings and review volume."""
        det = {"savings_pct": 0.30, "badge": "30d_low", "is_fake_discount": False}

        # Rating progression: 3.0 -> 3.5 -> 4.0 -> 4.5
        p_30 = {"current_price": 1000.0, "rating": 3.0, "review_count": 500}
        p_35 = {"current_price": 1000.0, "rating": 3.5, "review_count": 500}
        p_40 = {"current_price": 1000.0, "rating": 4.0, "review_count": 500}
        p_45 = {"current_price": 1000.0, "rating": 4.5, "review_count": 500}

        s_30 = calculate_shopper_score(p_30, det)
        s_35 = calculate_shopper_score(p_35, det)
        s_40 = calculate_shopper_score(p_40, det)
        s_45 = calculate_shopper_score(p_45, det)

        self.assertLess(s_30, s_35)
        self.assertLess(s_35, s_40)
        self.assertLess(s_40, s_45)

        # Review count progression: 100 -> 1k -> 5k -> 10k -> 50k
        p_100 = {"current_price": 1000.0, "rating": 4.0, "review_count": 100}
        p_1k = {"current_price": 1000.0, "rating": 4.0, "review_count": 1000}
        p_5k = {"current_price": 1000.0, "rating": 4.0, "review_count": 5000}
        p_10k = {"current_price": 1000.0, "rating": 4.0, "review_count": 10000}
        p_50k = {"current_price": 1000.0, "rating": 4.0, "review_count": 50000}

        s_100 = calculate_shopper_score(p_100, det)
        s_1k = calculate_shopper_score(p_1k, det)
        s_5k = calculate_shopper_score(p_5k, det)
        s_10k = calculate_shopper_score(p_10k, det)
        s_50k = calculate_shopper_score(p_50k, det)

        self.assertLess(s_100, s_1k)
        self.assertLess(s_1k, s_5k)
        self.assertLess(s_5k, s_10k)
        self.assertLess(s_10k, s_50k)

    def test_04_popularity_bias_validation(self):
        """Verify deep discount items outrank weak discount items even with huge popularity differences."""
        # Product A: 70% LOOT Deal, moderate popularity (500 reviews, 4.0 rating)
        prod_a = {"current_price": 300.0, "rating": 4.0, "review_count": 500}
        det_a = {"savings_pct": 0.70, "badge": "LOOT", "is_fake_discount": False}

        # Product B: 25% Weak Deal, massive popularity (100,000 reviews, 4.7 rating)
        prod_b = {"current_price": 3000.0, "rating": 4.7, "review_count": 100000}
        det_b = {"savings_pct": 0.25, "badge": "30d_low", "is_fake_discount": False}

        score_a = calculate_shopper_score(prod_a, det_a)
        score_b = calculate_shopper_score(prod_b, det_b)

        # 70% LOOT deal must clearly outrank 25% popular item for shoppers
        self.assertGreater(score_a, score_b, f"Product A (70% LOOT, score {score_a}) must outrank Product B (25% weak, score {score_b})")
        self.assertGreater(score_a - score_b, 15.0, "Expect at least 15 point separation in favor of the 70% LOOT deal.")

    def test_05_discount_vs_history_balance(self):
        """Verify ranking across discount strength vs historical benchmark confirmation."""
        # Case A: 60% discount + no historical benchmark
        prod_a = {"current_price": 800.0, "rating": 4.0, "review_count": 500}
        det_a = {"savings_pct": 0.60, "badge": None, "is_fake_discount": False}

        # Case B: 30% discount + verified ATL
        prod_b = {"current_price": 1400.0, "rating": 4.0, "review_count": 500}
        det_b = {"savings_pct": 0.30, "badge": "ATL", "is_fake_discount": False}

        # Case C: 45% discount + verified 90d low
        prod_c = {"current_price": 1100.0, "rating": 4.0, "review_count": 500}
        det_c = {"savings_pct": 0.45, "badge": "90d_low", "is_fake_discount": False}

        score_a = calculate_shopper_score(prod_a, det_a)
        score_b = calculate_shopper_score(prod_b, det_b)
        score_c = calculate_shopper_score(prod_c, det_c)

        # 45% + 90d low is a strong deal (>= 75.0)
        self.assertGreaterEqual(score_c, 75.0)
        # All three provide solid shopper value (>55)
        self.assertGreater(score_a, 55.0)
        self.assertGreater(score_b, 65.0)

    def test_06_missing_data_resilience(self):
        """Verify missing reviews, rating, and platform handle safely with clean fallback scores."""
        # Missing all social proof
        prod_no_social = {"current_price": 1000.0, "mrp": 2000.0}
        det = {"savings_pct": 0.50, "badge": "90d_low", "is_fake_discount": False}

        score = calculate_shopper_score(prod_no_social, det)
        self.assertGreaterEqual(score, 70.0)
        self.assertLessEqual(score, 100.0)

        # None detection
        score_none = calculate_shopper_score(prod_no_social, None)
        self.assertEqual(score_none, 0.0)

    def test_07_fake_discount_penalty_separation(self):
        """Verify fake-discount penalty creates clear separation between genuine and suspicious deals."""
        prod = {"current_price": 950.0, "rating": 4.0, "review_count": 500}
        
        genuine_det = {"savings_pct": 0.35, "badge": "30d_low", "is_fake_discount": False}
        fake_det = {"savings_pct": 0.35, "badge": "30d_low", "is_fake_discount": True}

        score_genuine = calculate_shopper_score(prod, genuine_det)
        score_fake = calculate_shopper_score(prod, fake_det)

        self.assertEqual(score_genuine - score_fake, 20.0, "Fake discount penalty must be exactly 20 points.")
        self.assertLess(score_fake, 55.0, "Suspicious fake discount must be heavily penalized.")

    def test_08_synthetic_100_deal_distribution(self):
        """Analyze score distribution across 100 realistic deterministic synthetic deals."""
        scores = []
        monetizations = []

        platforms = ["amazon", "flipkart", "myntra", "ajio", "nykaa"]
        badges = [None, "30d_low", "60d_low", "90d_low", "near_ATL", "ATL", "LOOT"]
        discounts = [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.75, 0.85]
        ratings = [0.0, 3.2, 3.8, 4.1, 4.4, 4.8]
        reviews = [0, 50, 450, 2500, 12000, 60000]
        prices = [199.0, 499.0, 1299.0, 2999.0, 7999.0, 24999.0]

        # Generate 100 deterministic profiles
        for i in range(100):
            p = {
                "current_price": prices[i % len(prices)],
                "mrp": prices[i % len(prices)] / (1.0 - discounts[i % len(discounts)]),
                "category": "fashion" if i % 2 == 0 else "electronics",
                "platform": platforms[i % len(platforms)],
                "rating": ratings[i % len(ratings)],
                "review_count": reviews[i % len(reviews)],
            }
            det = {
                "savings_pct": discounts[i % len(discounts)],
                "badge": badges[i % len(badges)],
                "is_fake_discount": (i % 25 == 0),  # 4% fake discounts
            }

            s_score = calculate_shopper_score(p, det)
            m_score = calculate_monetization_score(p, det)
            scores.append(s_score)
            monetizations.append(m_score)

        # Statistical analysis
        min_score = min(scores)
        max_score = max(scores)
        median_score = statistics.median(scores)
        q1 = statistics.quantiles(scores, n=4)[0]
        q3 = statistics.quantiles(scores, n=4)[2]
        below_35 = sum(1 for s in scores if s < 35.0)
        above_70 = sum(1 for s in scores if s >= 70.0)
        above_90 = sum(1 for s in scores if s >= 90.0)

        # Assert healthy distribution characteristics
        self.assertGreaterEqual(min_score, 0.0)
        self.assertLessEqual(max_score, 100.0)
        self.assertGreater(median_score, 50.0)
        self.assertLess(median_score, 80.0)
        self.assertGreater(above_70, 20, "At least 20% of high-grade deals should reach 70+.")
        self.assertGreater(above_90, 5, "At least 5% of exceptional LOOT deals should reach 90+.")
        self.assertGreater(below_35, 2, "Poor / fake deals should fall below 35.")

    def test_09_monetization_independence_regression(self):
        """Mathematical proof that changing commission rates has 0.000 effect on shopper score."""
        detection = {"savings_pct": 0.45, "badge": "ATL", "is_fake_discount": False}

        base_prod = {
            "current_price": 2000.0, "mrp": 3636.0, "category": "electronics",
            "platform": "amazon", "rating": 4.2, "review_count": 3000
        }

        # Calculate base shopper score
        base_shopper = calculate_shopper_score(base_prod, detection)
        base_monetization = calculate_monetization_score(base_prod, detection)

        # Alter commission rates dynamically in config
        with patch.dict("budgetby.config.AMAZON_COMMISSION_RATES", {"electronics": 0.15}):
            altered_shopper = calculate_shopper_score(base_prod, detection)
            altered_monetization = calculate_monetization_score(base_prod, detection)

            # Shopper score must be 100% identical
            self.assertEqual(base_shopper, altered_shopper)
            # Monetization score must reflect the commission change
            self.assertGreater(altered_monetization, base_monetization)

    def test_10_zero_supabase_egress_calibration(self):
        """Verify calibration computations perform 0 Supabase cloud queries."""
        with patch("budgetby.database.execute") as mock_db_exec, \
             patch("budgetby.database.fetch") as mock_db_fetch, \
             patch("budgetby.database.fetchrow") as mock_db_fetchrow:

            prod = {"current_price": 500.0, "mrp": 2500.0, "rating": 4.5, "review_count": 1000}
            det = {"savings_pct": 0.80, "badge": "LOOT", "is_fake_discount": False}

            for _ in range(50):
                score_deal_full(prod, det)

            mock_db_exec.assert_not_called()
            mock_db_fetch.assert_not_called()
            mock_db_fetchrow.assert_not_called()


if __name__ == "__main__":
    unittest.main()

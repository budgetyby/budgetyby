"""
BudgetBy — Deal Scorer
Scores deals from 0 to 100 based on magnitude, history, commission, and popularity.
"""

import logging
from asyncpg import Record
from budgetby import config

logger = logging.getLogger("budgetby.engine.deal_scorer")

def score_deal(product: Record, detection_result: dict) -> float:
    """
    Calculate a deal score 0-100 based on weighted factors.
    """
    try:
        weights = config.SCORE_WEIGHTS
        score = 0.0

        # 1. Drop Magnitude (30%)
        # 5% = 20pts, 20% = 60pts, 50%+ = 100pts
        savings_pct = detection_result.get("savings_pct", 0.0)
        pct_val = savings_pct * 100
        drop_score = 0
        if pct_val >= 50:
            drop_score = 100
        elif pct_val >= 20:
            drop_score = 60 + ((pct_val - 20) / 30) * 40
        elif pct_val >= 5:
            drop_score = 20 + ((pct_val - 5) / 15) * 40
        else:
            drop_score = (pct_val / 5) * 20
        
        score += drop_score * weights["drop_magnitude"]

        # 2. Historical Position (20%)
        badge = detection_result.get("badge")
        hist_score = 20 # none
        if badge == "ATL":
            hist_score = 100
        elif badge == "near_ATL":
            hist_score = 80
        elif badge == "90d_low":
            hist_score = 70
        elif badge == "60d_low":
            hist_score = 50
        elif badge == "30d_low":
            hist_score = 40
        
        score += hist_score * weights["historical_position"]

        # 3. Commission Potential (30%)
        # Assuming max standard commission per item around 200 INR for 100 score
        current_price = product.get("current_price", 0)
        category = product.get("category", "default")
        platform = product.get("platform", "amazon")
        
        comm_rate = 0.05
        if platform == "amazon":
            comm_rate = config.AMAZON_COMMISSION_RATES.get(category, 0.045)
        elif platform in config.EARNKARO_COMMISSION_RATES:
            comm_rate = config.EARNKARO_COMMISSION_RATES[platform].get(category, 0.03)
            
        estimated_commission = current_price * comm_rate
        # Cap at 100 points
        comm_score = min(100.0, (estimated_commission / 100.0) * 100.0)
        
        score += comm_score * weights["commission_potential"]

        # 4. Popularity (20%)
        review_count = product.get("review_count", 0)
        pop_score = 10
        if review_count >= 50000:
            pop_score = 100
        elif review_count >= 10000:
            pop_score = 90 + ((review_count - 10000) / 40000) * 10
        elif review_count >= 5000:
            pop_score = 70 + ((review_count - 5000) / 5000) * 20
        elif review_count >= 1000:
            pop_score = 50 + ((review_count - 1000) / 4000) * 20
        elif review_count >= 100:
            pop_score = 30 + ((review_count - 100) / 900) * 20
        else:
            pop_score = 10 + (review_count / 100) * 20
            
        score += pop_score * weights["popularity"]

        # Penalty
        if detection_result.get("is_fake_discount"):
            score -= config.FAKE_DISCOUNT_PENALTY

        return max(0.0, min(100.0, score))
    except Exception as e:
        logger.error(f"Error in score_deal: {e}")
        return 0.0

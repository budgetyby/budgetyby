"""
BudgetBy — Deal Detector
Implements the cascading comparison logic for detecting deals.
"""

import logging
from asyncpg import Record
from budgetby import config

logger = logging.getLogger("budgetby.engine.deal_detector")

async def detect_deal(product: Record, new_price: float) -> dict | None:
    """
    Detects if a new_price constitutes a deal based on a 5-level cascading comparison.
    Returns a dict with deal details or None if it's not a deal.
    """
    try:
        if new_price <= 0:
            return None

        current_price = product.get("current_price")
        previous_price = product.get("previous_price")
        
        if not ((current_price and new_price < current_price) or (previous_price and new_price < previous_price)):
            return None

        margins = config.BENCHMARK_MARGINS
        
        min_30d = product.get("min_30d")
        min_60d = product.get("min_60d")
        min_90d = product.get("min_90d")
        all_time_low = product.get("all_time_low")
        median_30d = product.get("median_30d_price")
        mrp = product.get("mrp") or new_price
        
        category = product.get("category", "default")
        cat_min_drop_pct, cat_min_savings = config.CATEGORY_MIN_DROPS.get(
            category, config.DEFAULT_MIN_DROP
        )

        best_badge = None
        all_badges = []
        should_post = False
        deal_type = "price_drop"

        # Level 4: All Time Low
        if all_time_low and all_time_low > 0:
            if new_price <= all_time_low:
                all_badges.append("ATL")
                best_badge = "ATL"
                should_post = True
            elif new_price <= all_time_low * (1 + margins["all_time_low"]):
                all_badges.append("near_ATL")
                if not best_badge:
                    best_badge = "near_ATL"
                should_post = True

        # Level 3: 90-day Low
        if min_90d and min_90d > 0 and new_price <= min_90d * (1 + margins["min_90d"]):
            all_badges.append("90d_low")
            if not best_badge:
                best_badge = "90d_low"
            should_post = True

        # Level 2: 60-day Low
        if min_60d and min_60d > 0 and new_price <= min_60d * (1 + margins["min_60d"]):
            all_badges.append("60d_low")
            if not best_badge:
                best_badge = "60d_low"
            should_post = True

        # Level 1: 30-day Low
        if min_30d and min_30d > 0 and new_price <= min_30d * (1 + margins["min_30d"]):
            all_badges.append("30d_low")
            if not best_badge:
                best_badge = "30d_low"
            should_post = True

        # Level 5: Median Drop
        if median_30d and median_30d > 0:
            drop_amount = median_30d - new_price
            drop_pct = drop_amount / median_30d
            if drop_pct >= cat_min_drop_pct and drop_amount >= cat_min_savings:
                all_badges.append("median_drop")
                if not best_badge:
                    best_badge = "median_drop"
                should_post = True

        if not should_post:
            return None

        # Calculate savings against MRP or baseline
        savings_amount = mrp - new_price
        savings_pct = savings_amount / mrp if mrp > 0 else 0.0

        if savings_amount < 0:
            savings_amount = 0
            savings_pct = 0.0

        from budgetby.engine import fake_discount
        is_fake = await fake_discount.is_fake_discount(product, new_price)

        return {
            "should_post": True,
            "badge": best_badge,
            "all_badges": all_badges,
            "savings_amount": savings_amount,
            "savings_pct": savings_pct,
            "deal_type": deal_type,
            "is_fake_discount": is_fake
        }
    except Exception as e:
        logger.error(f"Error in detect_deal for product {product.get('id')}: {e}")
        return None

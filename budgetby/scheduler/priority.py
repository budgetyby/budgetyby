"""
Priority assignment logic.
"""
import datetime
from budgetby import config
import asyncpg

def assign_priority(product: asyncpg.Record) -> int:
    """
    Assign priority tier 1-4 based on product state.
    Returns integer 1-4.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # 1. Tier 1 (Critical): Active deal posted in last 48h, price change in last 24h, lightning deal
    if product.get('has_recent_deal'):
        return 1

    last_change = product.get('last_price_change')
    if last_change:
        if last_change.tzinfo is None:
            last_change = last_change.replace(tzinfo=datetime.timezone.utc)
        if (now - last_change).total_seconds() < 86400:
            return 1
            
    if product.get('is_lightning_deal') or product.get('is_movers_shakers'):
        return 1

    # 2. Tier 2 (High): Bestseller, high commission category, high reviews
    category = product.get('category') or ""
    review_count = int(product.get('review_count') or 0)
    
    if category in ('fashion', 'beauty') or review_count > 5000 or product.get('is_bestseller'):
        return 2

    # 3. Tier 4 (Low/Dormant): TEMP_OOS or unchanged for 7+ days with low reviews
    if product.get('status') == config.STATUS_TEMP_OOS:
        return 4
        
    if last_change:
        if (now - last_change).total_seconds() > 7 * 86400 and review_count < 500:
            return 4

    # 4. Tier 3 (Medium): Standard
    return 3

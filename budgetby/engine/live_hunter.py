"""
BudgetBy — Live Smart Deal Hunter
Fetches live high-discount deals directly from store APIs on each rotation tick,
upserts them into PostgreSQL (adding if new or updating if existing),
and returns the deal for immediate Telegram broadcasting.
"""

import random
import logging
from typing import Dict, Any, Optional

from budgetby import config, database
from budgetby.engine.cooldown import is_on_cooldown

logger = logging.getLogger("budgetby.engine.live_hunter")

HUNT_CATEGORIES = {
    "myntra": [
        "men-tshirts", "women-kurtas-sets", "casual-shoes", "women-dresses",
        "men-jeans", "handbags", "perfumes", "sports-shoes", "trousers", "watches"
    ],
    "nykaa": [
        "sunscreen", "face-serum", "lipstick", "perfumes-women",
        "perfumes-men", "shampoo", "mens-grooming", "body-lotion"
    ],
    "flipkart": [
        ("t-shirts", "2oq,s1a,w04,smo"),
        ("shoes", "osp,cil"),
        ("casual-shirts", "2oq,s1a,w04,e83"),
        ("jeans", "2oq,s1a,w04,qda"),
        ("watches", "r18,f1m")
    ],
    "ajio": [
        "men-tshirts", "women-kurtas", "men-casual-shoes", "women-westernwear", "men-jeans"
    ]
}

async def hunt_live_store_deal(platform: str) -> Optional[Dict[str, Any]]:
    """
    Hunts for a single fresh, high-discount deal live from the store API.
    Upserts it into the DB (expanding product count organically) and returns it.
    """
    platform = platform.lower()
    min_disc = 0.40  # 40% minimum discount for live hunted flash deals

    try:
        products = []
        if platform == "myntra":
            from budgetby.discovery import myntra_discover
            cat = random.choice(HUNT_CATEGORIES["myntra"])
            products = await myntra_discover.discover_category(cat, pages=1, sort="discount")
            for p in products:
                p["platform"] = "myntra"
                p["category"] = "fashion"
            
        elif platform == "nykaa":
            from budgetby.discovery import nykaa_discover
            cat = random.choice(HUNT_CATEGORIES["nykaa"])
            products = await nykaa_discover.discover_category(cat, pages=1, sort="discount")
            for p in products:
                p["platform"] = "nykaa"
                p["category"] = "beauty"

        elif platform == "flipkart":
            from budgetby.discovery import flipkart_discover
            cat, sid = random.choice(HUNT_CATEGORIES["flipkart"])
            products = await flipkart_discover.discover_category(cat, sid, pages=1, sort="popularity")
            for p in products:
                p["platform"] = "flipkart"
                p["category"] = "fashion"

        elif platform == "ajio":
            from budgetby.discovery import ajio_discover
            cat = random.choice(HUNT_CATEGORIES["ajio"])
            products = await ajio_discover.discover_category(cat, pages=1)
            for p in products:
                p["platform"] = "ajio"
                p["category"] = "fashion"

        else:
            return None

        if not products:
            return None

        # Filter and pick the best non-cooldown candidate
        random.shuffle(products)
        for p in products:
            price = float(p.get("current_price") or 0)
            mrp = float(p.get("mrp") or price)
            title = p.get("title") or ""

            if price <= 0 or mrp <= price or len(title) < 8:
                continue

            disc = (mrp - price) / mrp
            if disc < min_disc or (mrp - price) < 150:
                continue

            # Upsert into PostgreSQL (adds if new or updates existing)
            try:
                pid = await database.upsert_product(p)
                p["id"] = pid
                
                # Check cooldown
                if await is_on_cooldown(pid):
                    continue

                logger.info(f"🎯 [LIVE HUNT SUCCESS] [{platform.upper()}] Found fresh deal #{pid}: {title[:40]} | ₹{price} ({round(disc*100)}% OFF)")

                badge = "LOOT" if disc >= 0.70 else "HOT_DEAL"
                return {
                    "product": p,
                    "type": "flash_hunt",
                    "badge": badge,
                    "score": 85.0
                }
            except Exception as ue:
                logger.debug(f"Live hunt upsert note: {ue}")

    except Exception as e:
        logger.debug(f"Live hunt exception for {platform}: {e}")

    return None

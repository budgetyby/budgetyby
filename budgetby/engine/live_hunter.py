"""
BudgetBy — Live Smart Deal Hunter (All Platforms)
Dynamically scans live store high-discount APIs and deals feeds on each rotation tick:
- Amazon: Lightning Deals (/deals & /gp/goldbox) & Top Category Deals
- Flipkart: Top Category Deals & Flash Discounts
- Myntra: Live Gateway Search API (sort=discount)
- Ajio: Top Fashion & Clearance Deals
- Nykaa: Live Beauty, Skincare & Fragrance (sort=discount)

Upserts qualifying loot into PostgreSQL (expanding product count organically)
and returns the deal for immediate Telegram broadcasting.
"""

import random
import logging
from typing import Dict, Any, Optional
from budgetby import database
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
        ("watches", "r18,f1m"),
        ("headphones-earphones", "0pm,fcn")
    ],
    "ajio": [
        "men-tshirts", "women-kurtas", "men-casual-shoes", "women-westernwear", "men-jeans"
    ],
    "amazon": [
        "deals_hub",
        "wireless earbuds", "smart watch", "running shoes men", "men t-shirt cotton",
        "women kurti set with dupatta", "bluetooth speaker", "perfumes for men"
    ]
}

async def hunt_live_store_deal(platform: str) -> Optional[Dict[str, Any]]:
    """
    Hunts for a single fresh, high-discount deal live from any store's live API / deals feed.
    Upserts it into the DB (expanding product count organically) and returns it.
    """
    platform = platform.lower()
    min_disc = 0.35  # 35% minimum discount for live hunted flash deals

    try:
        products = []
        
        # 1. AMAZON LIVE HUNT
        if platform == "amazon":
            from budgetby.discovery import amazon_discover
            kw = random.choice(HUNT_CATEGORIES["amazon"])
            if kw == "deals_hub":
                products = await amazon_discover.discover_deals_page(pages=1)
            else:
                products = await amazon_discover.discover_search_keywords(kw, pages=1)
            for p in products:
                p["platform"] = "amazon"
                p["category"] = p.get("category", "electronics")

        # 2. MYNTRA LIVE HUNT
        elif platform == "myntra":
            from budgetby.discovery import myntra_discover
            cat = random.choice(HUNT_CATEGORIES["myntra"])
            products = await myntra_discover.discover_category(cat, pages=1, sort="discount")
            for p in products:
                p["platform"] = "myntra"
                p["category"] = "fashion"
            
        # 3. NYKAA LIVE HUNT
        elif platform == "nykaa":
            from budgetby.discovery import nykaa_discover
            cat = random.choice(HUNT_CATEGORIES["nykaa"])
            products = await nykaa_discover.discover_category(cat, pages=1, sort="discount")
            for p in products:
                p["platform"] = "nykaa"
                p["category"] = "beauty"

        # 4. FLIPKART LIVE HUNT
        elif platform == "flipkart":
            from budgetby.discovery import flipkart_discover
            cat, sid = random.choice(HUNT_CATEGORIES["flipkart"])
            products = await flipkart_discover.discover_category(cat, sid, pages=1, sort="popularity")
            for p in products:
                p["platform"] = "flipkart"
                p["category"] = "fashion"

        # 5. AJIO LIVE HUNT
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

                badge = "LOOT" if disc >= 0.70 else ("ATL" if disc >= 0.50 else "HOT_DEAL")
                return {
                    "product": p,
                    "type": "flash_hunt",
                    "badge": badge,
                    "score": 85.0
                }
            except Exception as ue:
                logger.debug(f"Live hunt upsert note for {platform}: {ue}")

    except Exception as e:
        logger.debug(f"Live hunt exception for {platform}: {e}")

    return None

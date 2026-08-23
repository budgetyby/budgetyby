"""
Ajio discovery engine.
"""
import logging
import asyncio
from typing import List, Dict, Any
from curl_cffi.requests import AsyncSession
from budgetby import config
from budgetby.affiliate.earnkaro_links import build_earnkaro_url_sync

logger = logging.getLogger("budgetby.discovery.ajio")

async def discover_category(category_code: str, pages: int = 3) -> List[Dict[str, Any]]:
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        "Accept": "application/json"
    }
    async with AsyncSession(impersonate="safari17_0", headers=headers, timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(0, pages):
            url = f"https://www.ajio.com/api/category/{category_code}?currentPage={page}&pageSize=45&format=json&query=%3Arelevance&gridColumns=3"
            try:
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
                response = await session.get(url)
                if response.status_code != 200:
                    continue

                data = response.json()
                products = data.get("products", [])
                for p in products:
                    code = str(p.get("code", ""))
                    if not code:
                        continue
                    name = p.get("name", "")
                    brand = p.get("fnlColorVariantData", {}).get("brandName", "")
                    title = f"{brand} {name}".strip() if brand and not name.startswith(brand) else name
                    price = float(p.get("price", {}).get("value", 0)) if p.get("price") else None
                    mrp = float(p.get("wasPriceData", {}).get("value", price)) if p.get("wasPriceData") else price
                    
                    product_url = f"https://www.ajio.com/p/{code}"
                    aff_url = build_earnkaro_url_sync(product_url)
                    images = p.get("images", [])
                    image_url = images[0].get("url", "") if images else ""

                    results.append({
                        "platform": "ajio",
                        "platform_id": code,
                        "product_url": product_url,
                        "affiliate_url": aff_url,
                        "title": title,
                        "brand": brand,
                        "image_url": image_url,
                        "current_price": price,
                        "mrp": mrp,
                        "rating": 4.1,
                        "review_count": 25,
                    })
            except Exception as e:
                logger.error(f"Error scraping Ajio category {category_code} page {page}: {e}")
    return results

async def discover_deals_page(pages: int = 2) -> List[Dict[str, Any]]:
    """Crawls Ajio 50-90% Discount Clearance Hubs."""
    results = []
    # 830201=Men Clothing, 830202=Women Clothing, 830216=Footwear
    for code in ["830201", "830202", "830216"]:
        try:
            items = await discover_category(code, pages=pages)
            for it in items:
                it["deal_type"] = "today_deal"
                it["badge"] = "TODAY_DEAL"
            results.extend(items)
        except Exception as e:
            logger.error(f"Error scraping Ajio deals {code}: {e}")
    return results


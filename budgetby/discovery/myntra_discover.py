"""
Myntra discovery engine.
"""
import logging
import json
import asyncio
from typing import List, Dict, Any
from curl_cffi.requests import AsyncSession
from budgetby import config
from budgetby.affiliate.earnkaro_links import build_earnkaro_url

logger = logging.getLogger("budgetby.discovery.myntra")

async def discover_category(slug: str, pages: int = 5) -> List[Dict[str, Any]]:
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.myntra.com/"
    }
    async with AsyncSession(impersonate="chrome", headers=headers, timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.myntra.com/{slug}?p={page}&sort=popularity"
            try:
                await asyncio.sleep(0.05)
                response = await session.get(url)
                if response.status_code != 200:
                    continue

                text = response.text
                idx = text.find("window.__myx =")
                if idx == -1:
                    idx = text.find("window.__myx=")
                if idx == -1:
                    idx = text.find("window.__myx_data__ =")

                if idx != -1:
                    json_start = text.find("{", idx)
                    decoder = json.JSONDecoder()
                    data, _ = decoder.raw_decode(text[json_start:])
                    products = data.get("searchData", {}).get("results", {}).get("products", [])
                    
                    for p in products:
                        style_id = str(p.get("productId", p.get("styleId", "")))
                        if not style_id:
                            continue
                        title = p.get("productName", "") or p.get("brand", "")
                        p_url = f"https://www.myntra.com/{p.get('landingPageUrl', style_id)}"
                        img_url = p.get("searchImage", "")
                        price = float(p.get("price", 0)) if p.get("price") else None
                        mrp = float(p.get("mrp", 0)) if p.get("mrp") else price
                        brand = p.get("brand", "")
                        rating = float(p.get("rating", 0)) if p.get("rating") else None
                        rc = int(p.get("ratingCount", 0)) if p.get("ratingCount") else 0

                        aff_url = await build_earnkaro_url(p_url)

                        results.append({
                            "platform": "myntra",
                            "platform_id": style_id,
                            "product_url": p_url,
                            "affiliate_url": aff_url,
                            "title": title,
                            "brand": brand,
                            "image_url": img_url,
                            "current_price": price,
                            "mrp": mrp,
                            "rating": rating,
                            "review_count": rc,
                        })
            except Exception as e:
                logger.error(f"Error scraping Myntra category {slug} page {page}: {e}")
    return results

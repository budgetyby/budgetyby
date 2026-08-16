"""
Myntra discovery engine.
"""
import logging
import json
import asyncio
from typing import List, Dict, Any
from curl_cffi.requests import AsyncSession
from budgetby import config

logger = logging.getLogger("budgetby.discovery.myntra")

async def discover_category(slug: str, pages: int = 5) -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.myntra.com/{slug}?p={page}&sort=popularity"
            try:
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
                response = await session.get(url)
                response.raise_for_status()
                
                # Extract embedded JSON data from window.__myx_data__
                start_str = "window.__myx_data__ = "
                end_str = "};"
                text = response.text
                start_idx = text.find(start_str)
                if start_idx != -1:
                    start_idx += len(start_str)
                    end_idx = text.find(end_str, start_idx)
                    if end_idx != -1:
                        json_str = text[start_idx:end_idx+1]
                        data = json.loads(json_str)
                        products = data.get("searchData", {}).get("results", {}).get("products", [])
                        for p in products:
                            style_id = str(p.get("productId", p.get("styleId", "")))
                            title = p.get("productName", "")
                            p_url = f"https://www.myntra.com/{style_id}"
                            img_url = p.get("searchImage", "")
                            
                            results.append({
                                "platform": "myntra",
                                "platform_id": style_id,
                                "product_url": p_url,
                                "title": title,
                                "image_url": img_url
                            })
            except Exception as e:
                logger.error(f"Error scraping Myntra category {slug} page {page}: {e}")
    return results

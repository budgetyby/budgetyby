"""
BudgetBy — Ajio Scraper
"""
import re
import logging
from curl_cffi.requests import AsyncSession
from budgetby.scrapers.base import BaseScraper
from budgetby.scrapers.utils import extract_price, clean_title
from budgetby.affiliate.earnkaro_links import build_earnkaro_url_sync
from budgetby import config

logger = logging.getLogger("budgetby.scrapers.ajio")

class AjioScraper(BaseScraper):
    async def _do_scrape_product(self, url: str) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
            "Accept": "application/json"
        }
        
        # Extract product code from URL (e.g. /p/441234567_black or 441234567)
        code_match = re.search(r'/p/([A-Za-z0-9_]+)', url)
        code = code_match.group(1) if code_match else ""

        title = ""
        brand = ""
        price = 0.0
        mrp = 0.0
        image_url = ""
        in_stock = True

        async with AsyncSession(impersonate="safari17_0", headers=headers) as s:
            if code:
                api_url = f"https://www.ajio.com/api/p/{code}"
                try:
                    r = await s.get(api_url, timeout=config.SCRAPER_TIMEOUT)
                    if r.status_code == 200:
                        data = r.json()
                        title = clean_title(data.get("name", "") or data.get("baseOptions", [{}])[0].get("title", ""))
                        brand = data.get("brandName", "") or data.get("brickSubject", "")
                        
                        price_val = data.get("price", {}).get("value") or data.get("offerPrice", {}).get("value")
                        if price_val:
                            price = float(price_val)
                            
                        mrp_val = data.get("wasPriceData", {}).get("value") or data.get("mrp", {}).get("value")
                        if mrp_val:
                            mrp = float(mrp_val)
                            
                        in_stock = data.get("stock", {}).get("stockLevelStatus", "inStock") == "inStock"
                        images = data.get("images", [])
                        if images:
                            image_url = images[0].get("url", "")
                except Exception as e:
                    logger.debug(f"Ajio API failed for {code}: {e}")

        if not mrp or mrp < price:
            mrp = price

        affiliate_url = build_earnkaro_url_sync(url)

        return {
            "platform": "ajio",
            "platform_id": code or url,
            "title": f"{brand} {title}".strip() if brand and not title.startswith(brand) else title,
            "brand": brand,
            "current_price": price,
            "mrp": mrp,
            "product_url": url,
            "affiliate_url": affiliate_url,
            "image_url": image_url,
            "in_stock": in_stock,
            "rating": 4.2,
            "review_count": 50,
        }

    async def _do_scrape_listing(self, url: str) -> list[dict]:
        from budgetby.discovery.ajio_discover import discover_category
        code_match = re.search(r'/c/(\d+)', url)
        code = code_match.group(1) if code_match else "830216014"
        return await discover_category(code, pages=1)

"""
BudgetBy — Myntra Scraper
"""
import re
import json
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
from budgetby.scrapers.base import BaseScraper
from budgetby.scrapers.utils import get_random_ua, extract_price, clean_title
from budgetby import config

class MyntraScraper(BaseScraper):
    async def _do_scrape_product(self, url: str) -> dict:
        async with AsyncSession(impersonate="chrome", headers={"User-Agent": get_random_ua()}) as s:
            r = await s.get(url, timeout=config.SCRAPER_TIMEOUT)
            
        tree = HTMLParser(r.text)
        script_node = None
        for script in tree.css("script"):
            if script.text() and "window.__myx_data__" in script.text():
                script_node = script
                break
                
        title = ""
        price = 0.0
        mrp = 0.0
        rating = 0.0
        review_count = 0
        image_url = ""
        in_stock = True
        
        if script_node:
            try:
                json_str = re.search(r'window\.__myx_data__\s*=\s*({.*?});', script_node.text(), re.DOTALL)
                if json_str:
                    data = json.loads(json_str.group(1))
                    pdp_data = data.get("pdpData", {})
                    title = pdp_data.get("name", "")
                    price = float(pdp_data.get("price", {}).get("discounted", 0))
                    mrp = float(pdp_data.get("price", {}).get("mrp", 0))
                    
                    media = pdp_data.get("media", {}).get("albums", [])
                    if media and media[0].get("images"):
                        image_url = media[0]["images"][0].get("src", "")
                        
                    rating = float(pdp_data.get("ratings", {}).get("averageRating", 0))
                    review_count = int(pdp_data.get("ratings", {}).get("totalReviewsCount", 0))
                    in_stock = not pdp_data.get("flags", {}).get("outOfStock", False)
            except Exception:
                pass
                
        return {
            "title": title,
            "current_price": price,
            "mrp": mrp,
            "rating": rating,
            "review_count": review_count,
            "in_stock": in_stock,
            "image_url": image_url,
            "brand": "",
            "category": "",
            "has_coupon": False,
            "coupon_value": 0,
            "has_bank_offer": False,
            "bank_offer_text": "",
            "is_renewed": False
        }

    async def _do_scrape_listing(self, url: str) -> list[dict]:
        async with AsyncSession(impersonate="chrome", headers={"User-Agent": get_random_ua()}) as s:
            r = await s.get(url, timeout=config.SCRAPER_TIMEOUT)
            
        tree = HTMLParser(r.text)
        products = []
        
        for script in tree.css("script"):
            if script.text() and "window.__myx_data__" in script.text():
                try:
                    json_str = re.search(r'window\.__myx_data__\s*=\s*({.*?});', script.text(), re.DOTALL)
                    if json_str:
                        data = json.loads(json_str.group(1))
                        items = data.get("searchData", {}).get("results", {}).get("products", [])
                        for item in items:
                            pid = str(item.get("productId", ""))
                            p_url = f"https://www.myntra.com/{item.get('landingPageUrl', '')}"
                            title = clean_title(item.get("productName", ""))
                            if pid:
                                products.append({
                                    "platform_id": pid,
                                    "product_url": p_url,
                                    "title": title
                                })
                except Exception:
                    pass
                break
        return products

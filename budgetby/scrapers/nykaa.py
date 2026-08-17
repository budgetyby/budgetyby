"""
BudgetBy — Nykaa Scraper
"""
import re
import logging
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
from budgetby.scrapers.base import BaseScraper
from budgetby.scrapers.utils import extract_price, clean_title
from budgetby.affiliate.earnkaro_links import build_earnkaro_url_sync
from budgetby import config

logger = logging.getLogger("budgetby.scrapers.nykaa")

class NykaaScraper(BaseScraper):
    async def _do_scrape_product(self, url: str) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        
        pid_match = re.search(r'/p/(\d+)', url)
        pid = pid_match.group(1) if pid_match else re.sub(r'https?://[^/]+/', '', url).split('?')[0]

        async with AsyncSession(impersonate="chrome", headers=headers) as s:
            r = await s.get(url, timeout=config.SCRAPER_TIMEOUT)
            
        tree = HTMLParser(r.text)
        
        # Title
        t_node = tree.css_first("h1.css-1gc4x7i, h1.title, h1")
        raw_title = t_node.text() if t_node else ""
        raw_title = re.sub(r'\.css-[^{]+\{[^}]+\}', '', raw_title)
        raw_title = re.sub(r'@media[^{]+\{[^}]+\}', '', raw_title)
        title = clean_title(raw_title)

        # Price
        price = 0.0
        p_node = tree.css_first(".css-1jczs19, .post-discount-price, .css-1d0jf8e, .css-111z9ua")
        if p_node:
            price = extract_price(p_node.text())

        # MRP
        mrp = price
        m_node = tree.css_first(".css-u05rr, .css-17x46n5, .css-t37sfa")
        if m_node:
            mrp = extract_price(m_node.text())

        if not mrp or mrp < price:
            mrp = price

        # Rating
        rating = 4.3
        r_node = tree.css_first(".css-15vd5n, .css-1369vsm")
        if r_node:
            try:
                rating = float(extract_price(r_node.text()))
            except Exception:
                pass

        # Image
        img_node = tree.css_first("img.css-11q6006, img[alt]")
        image_url = img_node.attributes.get("src", "") if img_node else ""

        affiliate_url = build_earnkaro_url_sync(url)

        return {
            "platform": "nykaa",
            "platform_id": pid,
            "title": title,
            "current_price": price,
            "mrp": mrp,
            "product_url": url,
            "affiliate_url": affiliate_url,
            "image_url": image_url,
            "in_stock": True,
            "rating": rating,
            "review_count": 100,
        }

    async def _do_scrape_listing(self, url: str) -> list[dict]:
        from budgetby.discovery.nykaa_discover import discover_category
        path = re.sub(r'https?://[^/]+/', '', url).split('?')[0]
        return await discover_category(path, pages=1)

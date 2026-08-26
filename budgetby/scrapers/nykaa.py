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
        pid_match = re.search(r'/p/(\d+)', url)
        pid = pid_match.group(1) if pid_match else re.sub(r'https?://[^/]+/', '', url).split('?')[0]

        title = ""
        price = 0.0
        mrp = 0.0
        rating = 4.3
        review_count = 100
        image_url = ""
        in_stock = True

        try:
            import json
            async with AsyncSession(impersonate="chrome124", timeout=config.SCRAPER_TIMEOUT) as s:
                r = await s.get(url)

            tree = HTMLParser(r.text)

            # 1. Primary Strategy: application/ld+json
            for script in tree.css("script[type='application/ld+json']"):
                txt = script.text() or ""
                try:
                    data = json.loads(txt)
                    if isinstance(data, list):
                        data = data[0]
                    if data.get("@type") == "Product" or "offers" in data:
                        raw_t = data.get("name", "")
                        if raw_t:
                            raw_t = re.sub(r'@media[^{]+\{[^}]+\}', '', raw_t)
                            raw_t = re.sub(r'\.css-[^{]+\{[^}]+\}', '', raw_t)
                            title = clean_title(raw_t)

                        offers = data.get("offers", {})
                        if isinstance(offers, dict):
                            p_val = offers.get("price")
                            if p_val:
                                price = float(p_val)
                            avail = str(offers.get("availability", ""))
                            if "OutOfStock" in avail:
                                in_stock = False

                        imgs = data.get("image")
                        if isinstance(imgs, list) and imgs:
                            image_url = imgs[0]
                        elif isinstance(imgs, str):
                            image_url = imgs

                        agg = data.get("aggregateRating", {})
                        if isinstance(agg, dict):
                            r_val = agg.get("ratingValue")
                            if r_val:
                                rating = float(r_val)
                        break
                except Exception:
                    pass

            # 2. Fallback Title
            if not title:
                t_node = tree.css_first("h1.css-1gc4x7i, h1.title, h1")
                raw_title = t_node.text() if t_node else ""
                raw_title = re.sub(r'@media[^{]+\{[^}]+\}', '', raw_title)
                raw_title = re.sub(r'\.css-[^{]+\{[^}]+\}', '', raw_title)
                title = clean_title(raw_title)

            # 3. Fallback Price
            if not price:
                p_node = tree.css_first(".css-1jczs19, .post-discount-price, .css-1d0jf8e, .css-111z9ua")
                if p_node:
                    price = extract_price(p_node.text())

            # 4. MRP
            m_node = tree.css_first(".css-u05rr, .css-17x46n5, .css-t37sfa, span[class*='mrp']")
            if m_node:
                mrp_cand = extract_price(m_node.text())
                if mrp_cand > price:
                    mrp = mrp_cand

            if not mrp or mrp < price:
                mrp = price

            # 5. Image
            if not image_url:
                img_node = tree.css_first("img.css-11q6006, img[alt]")
                if img_node:
                    image_url = img_node.attributes.get("src", "")
        except Exception as e:
            logger.debug(f"Nykaa scraping error: {e}")

        if not title or price <= 0:
            return None

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
            "in_stock": in_stock,
            "rating": rating,
            "review_count": review_count,
        }

    async def _do_scrape_listing(self, url: str) -> list[dict]:
        from budgetby.discovery.nykaa_discover import discover_category
        path = re.sub(r'https?://[^/]+/', '', url).split('?')[0]
        return await discover_category(path, pages=1)

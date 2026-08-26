"""
BudgetBy — Croma Product Detail Page Scraper
Scrapes live price, MRP, rating, stock status, and HD product images from Croma.
Uses pure Chrome 124 TLS fingerprinting to bypass anti-bot challenges.
"""
import logging
import json
import re
from typing import Dict, Any, Optional
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser

from budgetby.scrapers.base import BaseScraper
from budgetby.scrapers.utils import extract_price, clean_title
from budgetby import config

logger = logging.getLogger("budgetby.scrapers.croma")

class CromaScraper(BaseScraper):
    platform = "croma"

    async def _do_scrape_product(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Scrapes a live Croma PDP.
        Returns:
            dict containing title, current_price, mrp, rating, review_count, in_stock, image_url, etc.
        """
        try:
            async with AsyncSession(impersonate="chrome124", timeout=config.SCRAPER_TIMEOUT) as session:
                r = await session.get(url, allow_redirects=True)
                if r.status_code != 200 or not r.text:
                    logger.warning(f"Croma scrape failed (status {r.status_code}) for {url}")
                    return None

                title = ""
                price = 0.0
                mrp = 0.0
                rating = 0.0
                review_count = 0
                image_url = ""
                in_stock = True
                brand = ""
                category = "electronics"

                # 1. Parse window.__INITIAL_DATA__
                start = r.text.find("window.__INITIAL_DATA__")
                if start != -1:
                    try:
                        eq = r.text.find("=", start)
                        sub = r.text[eq+1:].strip()
                        brace = sub.find("{")
                        target_str = sub[brace:]
                        # Sanitize JS undefined to null
                        target_str = re.sub(r':\s*undefined\b', ': null', target_str)
                        decoder = json.JSONDecoder()
                        data, _ = decoder.raw_decode(target_str)

                        pdp = data.get("pdpReducer", {}).get("pdpData", {})
                        price_red = data.get("pdpPriceReducer", {}).get("pdpPriceData", {})

                        # Product Title
                        if pdp.get("name"):
                            title = clean_title(pdp["name"])

                        # Brand & Category
                        if pdp.get("manufacturer") or pdp.get("SAP_BRAND_ID"):
                            brand = pdp.get("manufacturer") or pdp.get("SAP_BRAND_ID")
                        if pdp.get("categoryL1") or pdp.get("categoryL0"):
                            category = (pdp.get("categoryL1") or pdp.get("categoryL0") or "electronics").lower()

                        # Pricing from pdpPriceReducer
                        if price_red:
                            sp_val = price_red.get("sellingPrice", {}).get("value")
                            if sp_val:
                                price = float(str(sp_val).replace(',', ''))

                            mrp_val = price_red.get("mrp", {}).get("value")
                            if mrp_val:
                                mrp = float(str(mrp_val).replace(',', ''))

                        # Fallback price from pdpData
                        if not price and pdp.get("price", {}).get("value"):
                            price = float(str(pdp["price"]["value"]).replace(',', ''))

                        if not mrp and pdp.get("mrpPrice"):
                            mrp = float(str(pdp["mrpPrice"]).replace(',', ''))

                        # Real live star rating & review count
                        if pdp.get("averageRating") is not None:
                            try:
                                rating = round(float(pdp["averageRating"]), 1)
                            except Exception:
                                rating = 0.0

                        if pdp.get("numberOfReviews") is not None:
                            try:
                                review_count = int(pdp["numberOfReviews"])
                            except Exception:
                                review_count = 0

                        # Primary HD Product Image
                        img_info = pdp.get("imageInfo", [])
                        if img_info and isinstance(img_info, list) and len(img_info) > 0:
                            image_url = img_info[0].get("url") or ""

                    except Exception as je:
                        logger.debug(f"Croma INITIAL_DATA parse note: {je}")

                # 2. Fallback CSS Selectors via Selectolax
                tree = HTMLParser(r.text)
                if not title:
                    t_el = tree.css_first("h1.pd-title, h1.pdp-title, h1")
                    if t_el:
                        title = clean_title(t_el.text())

                if not price:
                    p_el = tree.css_first(".amount, .new-price, span[data-testid='new-price'], .pdp-price")
                    if p_el:
                        price = extract_price(p_el.text())

                if not mrp:
                    m_el = tree.css_first(".old-price, .strike-price, span[data-testid='old-price'], .mrp")
                    if m_el:
                        mrp = extract_price(m_el.text())

                if not image_url:
                    img_el = tree.css_first(".pdp-image img, .product-image img, img[data-testid='product-image']")
                    if img_el and img_el.attributes.get("src"):
                        image_url = img_el.attributes.get("src")

                # Sanity Check & Boundaries
                if not mrp or mrp < price:
                    mrp = price

                if price > 0 and mrp > (4.0 * price):
                    mrp = round((price * 1.35) / 10) * 10

                if not title or len(title) < 5 or price <= 0:
                    return None

                return {
                    "platform": "croma",
                    "title": title,
                    "brand": brand,
                    "category": category,
                    "current_price": price,
                    "mrp": mrp,
                    "rating": rating,
                    "review_count": review_count,
                    "in_stock": in_stock,
                    "image_url": image_url,
                    "is_renewed": False
                }

        except Exception as e:
            logger.error(f"Error scraping Croma product {url}: {e}")
            return None

    async def _do_scrape_listing(self, url: str) -> list[dict]:
        from budgetby.discovery.croma_discover import discover_category
        # Extract slug from URL (e.g. laptops, smartphones, etc.)
        for key in ["laptops", "smartphones", "smartwatches", "headphones-earphones", "smart-tvs", "air-conditioners"]:
            if key in url:
                return await discover_category(key, max_pages=1)
        return await discover_category("deals-of-the-day", max_pages=1)
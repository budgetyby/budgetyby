"""
BudgetBy — Flipkart Scraper
"""
import re
import json
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
from budgetby.scrapers.base import BaseScraper
from budgetby.scrapers.utils import get_random_ua, extract_price, clean_title
from budgetby import config

class FlipkartScraper(BaseScraper):
    async def _do_scrape_product(self, url: str) -> dict:
        async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as client:
            r = await client.get(url, allow_redirects=True)
            
        tree = HTMLParser(r.text)
        title = ""
        price = 0.0
        mrp = 0.0
        rating = 0.0
        review_count = 0
        image_url = ""
        in_stock = True
        
        # 1. Primary Strategy: application/ld+json (Flipkart official structured schema)
        for script in tree.css("script[type='application/ld+json']"):
            txt = script.text() or ""
            try:
                data = json.loads(txt)
                if isinstance(data, list):
                    data = data[0]
                if data.get("@type") == "Product" or "offers" in data:
                    t_val = data.get("name")
                    if t_val:
                        title = clean_title(t_val)
                    
                    # Extract Offers Price
                    offers = data.get("offers")
                    if isinstance(offers, dict):
                        price = float(offers.get("price") or 0)
                    elif isinstance(offers, list) and offers:
                        price = float(offers[0].get("price") or 0)

                    # Extract Ratings & Reviews
                    agg = data.get("aggregateRating", {})
                    if isinstance(agg, dict):
                        rating = float(agg.get("ratingValue") or 0)
                        review_count = int(agg.get("ratingCount") or agg.get("reviewCount") or 0)

                    # Extract Image
                    imgs = data.get("image")
                    if isinstance(imgs, list) and imgs:
                        image_url = imgs[0]
                    elif isinstance(imgs, str):
                        image_url = imgs
                    break
            except Exception:
                pass
                
        # 2. Fallback Title
        if not title:
            brand_node = tree.css_first("div._2WkVRV, span.mEh187")
            brand = brand_node.text(strip=True) if brand_node else ""
            t_node = tree.css_first("h1.VU-Tz5, span.VU-Tz5, .VU-Tz5, .B_NuCI, h1._6EBuvT, h1")
            desc = t_node.text(strip=True) if t_node else ""
            if brand and desc and not desc.lower().startswith(brand.lower()):
                title = f"{brand} {desc}"
            elif desc:
                title = desc
            elif brand:
                title = brand
            title = clean_title(title)
                
        # 3. Fallback Price via modern CSS selectors
        if not price:
            for p_sel in [".Nx9bqj.CxhGGd", "._30jeq3._16Jk6d", ".css-g5y9jx", "div.v1zwn20", ".v1zwn21m.v1zwn20"]:
                p_node = tree.css_first(p_sel)
                if p_node and extract_price(p_node.text()) > 0:
                    price = extract_price(p_node.text())
                    break

        # 4. Accurate Hero Strike-Through MRP Extraction (Strictly for this SKU, ignoring other storage variant pills)
        if price > 0:
            price_int = int(price)
            price_str = f"{price_int:,}"
            price_digits = str(price_int)

            # Search in DOM text blocks where HTML tags are stripped
            for el in tree.css("div.OmE16y, div.asbjxx, div[class*='_1psv1ze'], div[class*='price'], div, span"):
                txt = el.text(strip=True)
                if price_str in txt or price_digits in txt:
                    m = re.search(rf'(\d+%)?\s*([0-9,]{{2,8}})\s*₹?\s*(?:{re.escape(price_str)}|{price_digits})', txt)
                    if m:
                        cand = float(m.group(2).replace(',', ''))
                        if cand > price:
                            mrp = cand
                            break

        if not mrp or mrp < price:
            for m_sel in ["div.v1zwn21n.v1zwn21", ".yRaY8j.A6rEoz", "._3I9_wc._2p6lqe", "div.Nx9bqj ~ div.yRaY8j"]:
                m_node = tree.css_first(m_sel)
                if m_node and extract_price(m_node.text()) > 0:
                    extracted_mrp = extract_price(m_node.text())
                    if extracted_mrp > price:
                        mrp = extracted_mrp
                        break

        if not mrp or mrp < price:
            mrp = price
            
        # 4. Fallback Rating & Review count
        if not rating:
            for r_sel in [".XQDdHH", "div._3LWZlK"]:
                r_node = tree.css_first(r_sel)
                if r_node and extract_price(r_node.text()) > 0:
                    rating = extract_price(r_node.text())
                    break
            
        if not review_count:
            rc_node = tree.css_first(".Wphh3N")
            if rc_node:
                rc_match = re.search(r'([\d,]+)\s*Reviews', rc_node.text())
                if rc_match:
                    review_count = int(extract_price(rc_match.group(1)))
                
        # 5. Fallback Image
        if not image_url:
            img_node = tree.css_first(".v2VVsD .jBwCF_, ._396cs4._2amPTt, img.DByuf4")
            if img_node:
                image_url = img_node.attributes.get("src", "")
            
        out_node = tree.css_first(".Z8NC81, div._16FRp0, ._16FRp0")
        if out_node and any(s in out_node.text().lower() for s in ["sold out", "currently unavailable", "item is out of stock"]):
            in_stock = False
        elif price <= 0:
            in_stock = False
            
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
            "is_renewed": False
        }

    async def _do_scrape_listing(self, url: str) -> list[dict]:
        async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as client:
            r = await client.get(url, follow_redirects=True)
            
        tree = HTMLParser(r.text)
        products = []
        seen = set()
        
        for a in tree.css("a.VJA3rP, a.CGtC98, a._1fQZEK, a._2rpwqI"):
            href = a.attributes.get("href", "")
            match = re.search(r'pid=([A-Z0-9]+)', href)
            if match:
                pid = match.group(1)
                if pid not in seen:
                    seen.add(pid)
                    p_url = f"https://www.flipkart.com{href}"
                    title_node = a.css_first(".wjcEIp, .s1Q9rs, ._4rR01T")
                    title = clean_title(title_node.text()) if title_node else ""
                    products.append({
                        "platform_id": pid,
                        "product_url": p_url,
                        "title": title
                    })
        return products

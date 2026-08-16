"""
BudgetBy — Flipkart Scraper
"""
import re
import json
import httpx
from selectolax.parser import HTMLParser
from budgetby.scrapers.base import BaseScraper
from budgetby.scrapers.utils import get_random_ua, extract_price, clean_title
from budgetby import config

class FlipkartScraper(BaseScraper):
    async def _do_scrape_product(self, url: str) -> dict:
        headers = {"User-Agent": get_random_ua()}
        async with httpx.AsyncClient(headers=headers, timeout=config.SCRAPER_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url)
            
        tree = HTMLParser(r.text)
        title = ""
        price = 0.0
        mrp = 0.0
        rating = 0.0
        review_count = 0
        image_url = ""
        in_stock = True
        
        # Try JSON first
        script_node = None
        for script in tree.css("script"):
            if script.text() and "window.__INITIAL_STATE__" in script.text():
                script_node = script
                break
                
        if script_node:
            try:
                json_str = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', script_node.text(), re.DOTALL)
                if json_str:
                    data = json.loads(json_str.group(1))
                    # Basic fallback JSON extraction could go here if needed.
            except Exception:
                pass
                
        # Fallback to HTML
        if not title:
            t_node = tree.css_first(".VU-Tz5")
            if not t_node:
                t_node = tree.css_first(".B_NuCI")
            if t_node:
                title = clean_title(t_node.text())
                
        if not price:
            p_node = tree.css_first(".Nx9bqj.CxhGGd")
            if not p_node:
                p_node = tree.css_first("._30jeq3._16Jk6d")
            if p_node:
                price = extract_price(p_node.text())
                
        if not mrp:
            m_node = tree.css_first(".yRaY8j.A6rEoz")
            if not m_node:
                m_node = tree.css_first("._3I9_wc._2p6lqe")
            if m_node:
                mrp = extract_price(m_node.text())
        if not mrp or mrp < price:
            mrp = price
            
        # Rating
        r_node = tree.css_first(".XQDdHH")
        if r_node:
            rating = extract_price(r_node.text())
            
        # Review count
        rc_node = tree.css_first(".Wphh3N")
        if rc_node:
            rc_match = re.search(r'([\d,]+)\s*Reviews', rc_node.text())
            if rc_match:
                review_count = int(extract_price(rc_match.group(1)))
                
        # Image
        img_node = tree.css_first(".v2VVsD .jBwCF_")
        if not img_node:
            img_node = tree.css_first("._396cs4._2amPTt")
        if img_node:
            image_url = img_node.attributes.get("src", "")
            
        out_node = tree.css_first(".Z8NC81")
        if out_node and "Sold Out" in out_node.text():
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
            "has_coupon": False,
            "coupon_value": 0,
            "has_bank_offer": False,
            "bank_offer_text": "",
            "is_renewed": False
        }

    async def _do_scrape_listing(self, url: str) -> list[dict]:
        headers = {"User-Agent": get_random_ua()}
        async with httpx.AsyncClient(headers=headers, timeout=config.SCRAPER_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url)
            
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

"""
Flipkart discovery engine.
"""
import logging
import re
import asyncio
from typing import List, Dict, Any
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
from budgetby import config
from budgetby.affiliate.earnkaro_links import build_earnkaro_url
from budgetby.scrapers.utils import extract_price

logger = logging.getLogger("budgetby.discovery.flipkart")

PID_REGEX = re.compile(r'pid=([A-Z0-9]+)')

async def discover_category(name: str, sid: str, pages: int = 5) -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.flipkart.com/{name}/pr?sid={sid}&sort=popularity&page={page}"
            try:
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
                response = await session.get(url)
                if response.status_code != 200:
                    continue

                tree = HTMLParser(response.text)
                for item in tree.css("div[data-id], a[href*='pid=']"):
                    pid = item.attributes.get("data-id")
                    href = item.attributes.get("href", "")
                    
                    if not pid and href:
                        match = PID_REGEX.search(href)
                        if match:
                            pid = match.group(1)
                    
                    if not pid:
                        continue

                    if href and not href.startswith("http"):
                        product_url = "https://www.flipkart.com" + href
                    elif not href:
                        product_url = f"https://www.flipkart.com/product/p/itme?pid={pid}"
                    else:
                        product_url = href

                    # Extract title
                    title = ""
                    for t_sel in ["div.KzDlHZ", "a.wByIpH", "div._4rR01T", "a.s1Q9rs", "div._2WkVRV", "img[alt]"]:
                        t_node = item.css_first(t_sel)
                        if t_node:
                            title = t_node.attributes.get("alt") if t_node.tag == "img" else t_node.text(strip=True)
                            if title:
                                break

                    # Image
                    img_node = item.css_first("img")
                    image_url = img_node.attributes.get("src", "") if img_node else ""

                    # Price
                    price = None
                    price_node = item.css_first("div.Nx9bqj, div._30jeq3")
                    if price_node:
                        price = extract_price(price_node.text())

                    # MRP
                    mrp = price
                    mrp_node = item.css_first("div.yRaY8j, div._3I9_wc")
                    if mrp_node:
                        mrp = extract_price(mrp_node.text())

                    aff_url = await build_earnkaro_url(product_url)

                    results.append({
                        "platform": "flipkart",
                        "platform_id": pid,
                        "product_url": product_url,
                        "affiliate_url": aff_url,
                        "title": title,
                        "image_url": image_url,
                        "current_price": price,
                        "mrp": mrp,
                    })
            except Exception as e:
                logger.error(f"Error scraping Flipkart category {name} page {page}: {e}")
    return results

async def discover_offers_store() -> List[Dict[str, Any]]:
    return await discover_category("offers-store", "all", pages=2)

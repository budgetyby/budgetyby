"""
Nykaa discovery engine.
"""
import logging
import asyncio
import re
from typing import List, Dict, Any
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
from budgetby import config
from budgetby.affiliate.earnkaro_links import build_earnkaro_url_sync
from budgetby.scrapers.utils import extract_price, clean_title

logger = logging.getLogger("budgetby.discovery.nykaa")

async def discover_category(category_path: str, pages: int = 3) -> List[Dict[str, Any]]:
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    async with AsyncSession(impersonate="chrome", headers=headers, timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.nykaa.com/{category_path}?page_no={page}&sort=popularity"
            try:
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
                response = await session.get(url)
                if response.status_code != 200:
                    continue

                tree = HTMLParser(response.text)
                for item in tree.css("div.productWrapper, div.product-listing"):
                    link_node = item.css_first("a[href*='/p/']")
                    if not link_node:
                        continue
                    href = link_node.attributes.get("href", "")
                    if not href.startswith("http"):
                        product_url = "https://www.nykaa.com" + href
                    else:
                        product_url = href

                    pid_match = re.search(r'/p/(\d+)', product_url)
                    pid = pid_match.group(1) if pid_match else re.sub(r'https?://[^/]+/', '', product_url).split('?')[0]

                    t_node = item.css_first(".title, .css-11gn9r6, h3, img")
                    title = t_node.attributes.get("alt") if (t_node and t_node.tag == "img") else (clean_title(t_node.text()) if t_node else "")

                    img_node = item.css_first("img")
                    image_url = img_node.attributes.get("src", "") if img_node else ""

                    price = None
                    p_node = item.css_first(".css-111z9ua, .post-discount-price, .css-1d0jf8e, .css-17x46n5")
                    if p_node:
                        price = extract_price(p_node.text())

                    mrp = price
                    m_node = item.css_first(".css-u05rr, .css-t37sfa")
                    if m_node:
                        mrp = extract_price(m_node.text())

                    aff_url = build_earnkaro_url_sync(product_url)

                    results.append({
                        "platform": "nykaa",
                        "platform_id": pid,
                        "product_url": product_url,
                        "affiliate_url": aff_url,
                        "title": title,
                        "image_url": image_url,
                        "current_price": price,
                        "mrp": mrp,
                    })
            except Exception as e:
                logger.error(f"Error scraping Nykaa category {category_path} page {page}: {e}")
    return results

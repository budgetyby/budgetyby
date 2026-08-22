"""
Nykaa discovery engine with high-accuracy title extraction.
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

async def discover_category(category_path: str, pages: int = 3, sort: str = "popularity") -> List[Dict[str, Any]]:
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    async with AsyncSession(impersonate="chrome", headers=headers, timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.nykaa.com/{category_path}?page_no={page}&sort={sort}"
            try:
                await asyncio.sleep(0.5)  # Fast discovery: 0.5s per page (was 2.0s - too slow)
                response = await session.get(url)
                if response.status_code != 200:
                    continue

                tree = HTMLParser(response.text)
                items = tree.css("div.productWrapper, div.product-listing")
                if not items:
                    # No more products in this category, stop paging early
                    break

                for item in items:
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

                    # 1. Extract title from img alt (ignoring generic icons)
                    title = ""
                    for img in item.css("img[alt]"):
                        alt = img.attributes.get("alt", "").strip()
                        if alt and not any(x in alt.lower() for x in ["editor", "pick", "featured", "nykaa", "star", "badge", "offer"]):
                            title = alt
                            break
                        elif alt and not title:
                            title = alt

                    # 2. Text node fallback
                    if not title or len(title) < 5:
                        for sel in ["div.css-xrzmfa", "div.css-11gn9r6", "div.css-154w49h", ".title", "h3", "h2"]:
                            node = item.css_first(sel)
                            if node and node.text(strip=True):
                                title = node.text(strip=True)
                                break

                    # 3. URL slug fallback (100% reliable)
                    if not title or len(title) < 4 or title.lower() in ["nykaa", "editor_pickv2", "featured"]:
                        slug = re.sub(r'https?://[^/]+/', '', product_url).split('/p/')[0].lstrip('/').replace('-', ' ').title()
                        title = slug if slug else f"Nykaa Product {pid}"

                    title = clean_title(title)

                    img_node = item.css_first("img[src*='media'], img[src*='assets'], img")
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

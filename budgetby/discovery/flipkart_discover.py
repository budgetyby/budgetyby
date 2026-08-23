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
from budgetby.affiliate.earnkaro_links import build_earnkaro_url, build_earnkaro_url_sync
from budgetby.scrapers.utils import extract_price

logger = logging.getLogger("budgetby.discovery.flipkart")

PID_REGEX = re.compile(r'pid=([A-Z0-9]+)')

async def discover_category(name: str, sid: str, pages: int = 5, sort: str = "popularity") -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.flipkart.com/{name}/pr?sid={sid}&sort={sort}&page={page}"
            try:
                await asyncio.sleep(0.3)  # Fast discovery: 0.3s per page (was 2.0s - too slow, caused restarts)
                response = await session.get(url)
                if response.status_code != 200:
                    continue

                tree = HTMLParser(response.text)
                items = tree.css("div[data-id], a[href*='pid=']")

                # If primary URL returns 0 items on page 1, fallback to search URL
                if not items and page == 1:
                    query = name.replace('-', '+')
                    search_url = f"https://www.flipkart.com/search?q={query}&sort={sort}&page={page}"
                    s_resp = await session.get(search_url)
                    if s_resp.status_code == 200:
                        tree = HTMLParser(s_resp.text)
                        items = tree.css("div[data-id], a[href*='pid=']")

                if not items:
                    # No more products in this category, stop paging early
                    break

                for item in items:
                    try:
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
                        for t_sel in ["div.KzDlHZ", "a.wByIpH", "div._4rR01T", "a.s1Q9rs", "div._2WkVRV", "div.WKTcLC", "a.IRpwTa", "img[alt]"]:
                            t_node = item.css_first(t_sel)
                            if t_node:
                                title = t_node.attributes.get("alt") if t_node.tag == "img" else t_node.text(strip=True)
                                if title:
                                    break

                        if not title:
                            title = item.text(strip=True) if hasattr(item, 'text') else ""
                        if not title:
                            # Derive from URL slug
                            slug = re.sub(r'https?://[^/]+/', '', product_url).split('/p/')[0].replace('-', ' ').title()
                            title = slug if slug else f"Flipkart Product {pid}"

                        # Image
                        img_node = item.css_first("img")
                        image_url = img_node.attributes.get("src", "") if img_node else ""

                        # Price extraction (multi-selector + regex fallback)
                        price = None
                        price_node = item.css_first("div.Nx9bqj, div._30jeq3, div[class*='Nx9bqj'], div[class*='_30jeq3'], div.hl05eU")
                        if price_node:
                            price = extract_price(price_node.text())
                        
                        if not price:
                            raw_text = item.text()
                            price_matches = re.findall(r'[\u20b9₹]\s*([\d]{1,3}(?:,\d{2,3})*|\d+)', raw_text)
                            if price_matches:
                                try:
                                    price = float(price_matches[0].replace(',', ''))
                                except Exception:
                                    pass

                        # MRP extraction
                        mrp = price
                        mrp_node = item.css_first("div.yRaY8j, div._3I9_wc, div[class*='yRaY8j'], div[class*='_3I9_wc']")
                        if mrp_node:
                            mrp = extract_price(mrp_node.text())
                        elif price and price_matches and len(price_matches) > 1:
                            try:
                                mrp_cand = float(price_matches[1].replace(',', ''))
                                if mrp_cand >= price:
                                    mrp = mrp_cand
                            except Exception:
                                pass

                        if not mrp or mrp <= (price or 0):
                            mrp = round(((price or 500) * 1.5) / 10) * 10 if price else None

                        # Rating extraction (e.g. 4.2 in div.XQDdHH or div._3LWZlK)
                        rating = None
                        rating_node = item.css_first("div.XQDdHH, div._3LWZlK, span._1lRcqv, div.hGSR34")
                        if rating_node:
                            r_match = re.search(r'([\d.]+)', rating_node.text())
                            if r_match:
                                try:
                                    rating = float(r_match.group(1))
                                except Exception:
                                    pass

                        # Review count extraction (e.g. (1,234) in span.WJhFly or span._2_R_DZ)
                        review_count = None
                        rc_node = item.css_first("span.WJhFly, span._2_R_DZ, span[class*='WJhFly']")
                        if rc_node:
                            rc_match = re.search(r'([\d,]+)', rc_node.text())
                            if rc_match:
                                try:
                                    review_count = int(rc_match.group(1).replace(',', ''))
                                except Exception:
                                    pass

                        if not title or len(title) < 5 or title.lower() in ('product', 'flipkart product'):
                            continue

                        aff_url = build_earnkaro_url_sync(product_url)

                        results.append({
                            "platform": "flipkart",
                            "platform_id": pid,
                            "product_url": product_url,
                            "affiliate_url": aff_url,
                            "title": title,
                            "image_url": image_url,
                            "current_price": price,
                            "mrp": mrp or price,
                            "rating": rating,
                            "review_count": review_count,
                        })
                    except Exception as e:
                        logger.error(f"Error parsing Flipkart product item: {e}")
            except Exception as e:
                logger.error(f"Error scraping Flipkart category {name} page {page}: {e}")
    return results

async def discover_offers_store() -> List[Dict[str, Any]]:
    return await discover_category("offers-store", "all", pages=2)

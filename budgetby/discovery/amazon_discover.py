"""
Amazon discovery engine.
"""
import logging
import re
import asyncio
from typing import List, Dict, Any
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
from budgetby import config
from budgetby.affiliate.amazon_links import build_affiliate_url

logger = logging.getLogger("budgetby.discovery.amazon")

ASIN_REGEX = re.compile(r'/dp/([A-Z0-9]{10})')

async def discover_bestsellers(category_slug: str, pages: int = 2) -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.amazon.in/gp/bestsellers/{category_slug}/ref=zg_bs_pg_{page}?ie=UTF8&pg={page}"
            try:
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
                response = await session.get(url)
                response.raise_for_status()
                
                tree = HTMLParser(response.text)
                for item in tree.css(".zg-grid-general-faceout"):
                    link_tag = item.css_first("a.a-link-normal")
                    if link_tag:
                        href = link_tag.attributes.get("href", "")
                        match = ASIN_REGEX.search(href)
                        if match:
                            asin = match.group(1)
                            title_tag = link_tag.css_first("div")
                            title = title_tag.text(strip=True) if title_tag else ""
                            results.append({
                                "platform": "amazon",
                                "platform_id": asin,
                                "product_url": f"https://www.amazon.in/dp/{asin}",
                                "affiliate_url": build_affiliate_url(asin),
                                "title": title
                            })
            except Exception as e:
                logger.error(f"Error scraping Amazon bestsellers {category_slug} page {page}: {e}")
    return results

async def discover_movers_and_shakers(category_slug: str) -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        url = f"https://www.amazon.in/gp/movers-and-shakers/{category_slug}"
        try:
            await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            response = await session.get(url)
            response.raise_for_status()
            
            tree = HTMLParser(response.text)
            for item in tree.css(".zg-grid-general-faceout"):
                link_tag = item.css_first("a.a-link-normal")
                if link_tag:
                    href = link_tag.attributes.get("href", "")
                    match = ASIN_REGEX.search(href)
                    if match:
                        asin = match.group(1)
                        title_tag = link_tag.css_first("div")
                        title = title_tag.text(strip=True) if title_tag else ""
                        results.append({
                            "platform": "amazon",
                            "platform_id": asin,
                            "product_url": f"https://www.amazon.in/dp/{asin}",
                            "affiliate_url": build_affiliate_url(asin),
                            "title": title
                        })
        except Exception as e:
            logger.error(f"Error scraping Amazon movers {category_slug}: {e}")
    return results

async def discover_deals_page() -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        url = "https://www.amazon.in/deals"
        try:
            await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            response = await session.get(url)
            response.raise_for_status()
            
            # This is a very simplified fallback. In reality Amazon deals page is heavily JS driven.
            tree = HTMLParser(response.text)
            for link_tag in tree.css("a"):
                href = link_tag.attributes.get("href", "")
                match = ASIN_REGEX.search(href)
                if match:
                    asin = match.group(1)
                    title = link_tag.text(strip=True) or ""
                    results.append({
                        "platform": "amazon",
                        "platform_id": asin,
                        "product_url": f"https://www.amazon.in/dp/{asin}",
                        "affiliate_url": build_affiliate_url(asin),
                        "title": title
                    })
        except Exception as e:
            logger.error(f"Error scraping Amazon deals page: {e}")
    return results

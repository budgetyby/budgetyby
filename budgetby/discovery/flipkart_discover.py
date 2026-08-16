"""
Flipkart discovery engine.
"""
import logging
import re
import asyncio
import httpx
from typing import List, Dict, Any
from selectolax.parser import HTMLParser
from budgetby import config

logger = logging.getLogger("budgetby.discovery.flipkart")

PID_REGEX = re.compile(r'pid=([A-Z0-9]+)')

async def discover_category(name: str, sid: str, pages: int = 5) -> List[Dict[str, Any]]:
    results = []
    headers = {
        "User-Agent": config.USER_AGENTS[0]
    }
    async with httpx.AsyncClient(timeout=config.SCRAPER_TIMEOUT, headers=headers) as client:
        for page in range(1, pages + 1):
            url = f"https://www.flipkart.com/{name}/pr?sid={sid}&sort=popularity&page={page}"
            try:
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
                response = await client.get(url)
                response.raise_for_status()
                
                tree = HTMLParser(response.text)
                for link_tag in tree.css("a"):
                    href = link_tag.attributes.get("href", "")
                    if href.startswith("/"):
                        href = "https://www.flipkart.com" + href
                    match = PID_REGEX.search(href)
                    if match:
                        pid = match.group(1)
                        # Extract basic title (often in image alt or inner text)
                        img_tag = link_tag.css_first("img")
                        title = img_tag.attributes.get("alt", "") if img_tag else link_tag.text(strip=True)
                        results.append({
                            "platform": "flipkart",
                            "platform_id": pid,
                            "product_url": href,
                            "title": title
                        })
            except Exception as e:
                logger.error(f"Error scraping Flipkart category {name} page {page}: {e}")
    return results

async def discover_offers_store() -> List[Dict[str, Any]]:
    results = []
    headers = {
        "User-Agent": config.USER_AGENTS[0]
    }
    async with httpx.AsyncClient(timeout=config.SCRAPER_TIMEOUT, headers=headers) as client:
        url = "https://www.flipkart.com/offers-store"
        try:
            await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            response = await client.get(url)
            response.raise_for_status()
            
            tree = HTMLParser(response.text)
            for link_tag in tree.css("a"):
                href = link_tag.attributes.get("href", "")
                if href.startswith("/"):
                    href = "https://www.flipkart.com" + href
                match = PID_REGEX.search(href)
                if match:
                    pid = match.group(1)
                    title = link_tag.text(strip=True) or ""
                    results.append({
                        "platform": "flipkart",
                        "platform_id": pid,
                        "product_url": href,
                        "title": title
                    })
        except Exception as e:
            logger.error(f"Error scraping Flipkart offers store: {e}")
    return results

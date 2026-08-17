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
from budgetby.scrapers.utils import extract_price

logger = logging.getLogger("budgetby.discovery.amazon")

ASIN_REGEX = re.compile(r'/dp/([A-Z0-9]{10})')

AMAZON_CATEGORY_KEYWORDS = {
    "electronics": ["wireless earbuds", "bluetooth speaker", "smart watch", "headphones", "power bank", "soundbar", "fast charger"],
    "computers": ["gaming laptop", "ssd 1tb", "wireless mouse", "mechanical keyboard", "computer monitor", "laptop stand"],
    "smartphones": ["5g mobile phone", "iphone 15", "oneplus 12", "samsung galaxy phone", "redmi mobile"],
    "appliances": ["air fryer", "mixer grinder", "water purifier", "microwave oven", "vacuum cleaner", "refrigerator"],
    "home": ["cookware set", "bedsheets king size", "water bottle steel", "office chair", "curtains for door", "wall clock"],
    "apparel": ["men t-shirt", "women kurti", "jeans men", "dresses for women", "track pants", "formal shirts"],
    "shoes": ["running shoes men", "sneakers women", "formal shoes men", "sandals for men", "walking shoes"],
    "watches": ["casio watch", "titan watch", "fastrack watch", "smart watch men", "fossil watch", "timex watch"],
    "beauty": ["face wash", "sunscreen spf 50", "body lotion", "perfume men", "shampoo for hair fall", "serum for face"],
    "sports": ["badminton racket", "dumbbells set", "yoga mat", "cricket kit", "resistance bands", "treadmill"],
    "toys": ["lego sets", "rc car", "board games", "action figures", "educational toys for kids"],
    "automotive": ["car dash camera", "tyre inflator", "car vacuum cleaner", "bike helmet", "car pressure washer"],
}

async def _parse_amazon_listing(tree: HTMLParser) -> List[Dict[str, Any]]:
    results = []
    for item in tree.css(".zg-grid-general-faceout, .zg-item-immersion, .a-carousel-card, div[data-component-type='s-search-result']"):
        link_tag = item.css_first("a.a-link-normal")
        if not link_tag:
            continue
        href = link_tag.attributes.get("href", "")
        match = ASIN_REGEX.search(href)
        if not match:
            # Also check data-asin
            data_asin = item.attributes.get("data-asin")
            if data_asin and len(data_asin) == 10:
                asin = data_asin
            else:
                continue
        else:
            asin = match.group(1)

        title = ""
        for t_sel in [
            "[class*='p13n-sc-css-line-clamp']",
            "div._cDEzb_p13n-sc-css-line-clamp-2_EWgCb",
            "div._cDEzb_p13n-sc-css-line-clamp-1_1Fn1y",
            ".p13n-sc-truncate-desktop-type2",
            "h2 a span",
            "a.a-link-normal span",
            "img[alt]"
        ]:
            t_node = item.css_first(t_sel)
            if t_node:
                title = t_node.attributes.get("alt") if t_node.tag == "img" else t_node.text(strip=True)
                if title:
                    break

        img_node = item.css_first("img")
        image_url = img_node.attributes.get("src", "") if img_node else ""

        price = None
        price_node = item.css_first(".p13n-sc-price, ._cDEzb_p13n-sc-price_3mJ9Z, span.a-price-whole")
        if price_node:
            price = extract_price(price_node.text())

        results.append({
            "platform": "amazon",
            "platform_id": asin,
            "product_url": f"https://www.amazon.in/dp/{asin}",
            "affiliate_url": build_affiliate_url(asin),
            "title": title,
            "image_url": image_url,
            "current_price": price,
            "mrp": price,
        })
    return results

async def discover_bestsellers(category_slug: str, pages: int = 2) -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.amazon.in/gp/bestsellers/{category_slug}/ref=zg_bs_pg_{page}?ie=UTF8&pg={page}"
            try:
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
                response = await session.get(url)
                if response.status_code == 200:
                    tree = HTMLParser(response.text)
                    items = await _parse_amazon_listing(tree)
                    results.extend(items)
            except Exception as e:
                logger.error(f"Error scraping Amazon bestsellers {category_slug} page {page}: {e}")
    return results

async def discover_new_releases(category_slug: str, pages: int = 2) -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.amazon.in/gp/new-releases/{category_slug}/ref=zg_bs_pg_{page}?ie=UTF8&pg={page}"
            try:
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
                response = await session.get(url)
                if response.status_code == 200:
                    tree = HTMLParser(response.text)
                    items = await _parse_amazon_listing(tree)
                    results.extend(items)
            except Exception as e:
                logger.error(f"Error scraping Amazon new releases {category_slug}: {e}")
    return results

async def discover_most_wished_for(category_slug: str) -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        url = f"https://www.amazon.in/gp/most-wished-for/{category_slug}"
        try:
            await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            response = await session.get(url)
            if response.status_code == 200:
                tree = HTMLParser(response.text)
                items = await _parse_amazon_listing(tree)
                results.extend(items)
        except Exception as e:
            logger.error(f"Error scraping Amazon most wished {category_slug}: {e}")
    return results

async def discover_movers_and_shakers(category_slug: str) -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        url = f"https://www.amazon.in/gp/movers-and-shakers/{category_slug}"
        try:
            await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            response = await session.get(url)
            if response.status_code == 200:
                tree = HTMLParser(response.text)
                items = await _parse_amazon_listing(tree)
                results.extend(items)
        except Exception as e:
            logger.error(f"Error scraping Amazon movers {category_slug}: {e}")
    return results

async def discover_search_keywords(keyword: str, pages: int = 2) -> List[Dict[str, Any]]:
    results = []
    async with AsyncSession(impersonate="chrome", timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(1, pages + 1):
            url = f"https://www.amazon.in/s?k={keyword.replace(' ', '+')}&page={page}"
            try:
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
                response = await session.get(url)
                if response.status_code == 200:
                    tree = HTMLParser(response.text)
                    items = await _parse_amazon_listing(tree)
                    results.extend(items)
            except Exception as e:
                logger.error(f"Error searching Amazon keyword {keyword} page {page}: {e}")
    return results

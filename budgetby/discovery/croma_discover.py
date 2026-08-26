"""
BudgetBy — Croma Category & Deals Discovery Engine
Discovers high-converting electronics deals across Croma categories:
Laptops, Smartphones, Smartwatches, Audio, 4K TVs, Appliances, and Deals of the Day Hub.
"""
import logging
import asyncio
import json
import re
from typing import List, Dict, Any
from curl_cffi.requests import AsyncSession

from budgetby.scrapers.utils import clean_title
from budgetby import config

logger = logging.getLogger("budgetby.discovery.croma")

CROMA_CATEGORIES = {
    # 💻 Laptops & Computers
    "macbooks":                {"url": "https://www.croma.com/computers-tablets/laptops/macbooks/c/906", "category": "laptops", "pages": 6},
    "gaming-laptops":          {"url": "https://www.croma.com/computers-tablets/laptops/gaming-laptops/c/806", "category": "laptops", "pages": 8},
    "windows-laptops":         {"url": "https://www.croma.com/computers-tablets/laptops/windows-laptops/c/855", "category": "laptops", "pages": 12},
    "tablets-ipads":           {"url": "https://www.croma.com/computers-tablets/tablets-e-readers/c/22", "category": "electronics", "pages": 8},
    "monitors":                {"url": "https://www.croma.com/computers-tablets/desktops-all-in-ones/monitors/c/32", "category": "electronics", "pages": 8},
    "external-ssds":           {"url": "https://www.croma.com/computers-tablets/storage-devices/external-solid-state-drive-ssd-/c/103", "category": "electronics", "pages": 6},
    "external-hdds":           {"url": "https://www.croma.com/computers-tablets/storage-devices/external-hard-disk-drive-hdd-/c/229", "category": "electronics", "pages": 6},
    "keyboards-mice":          {"url": "https://www.croma.com/computers-tablets/computer-laptop-accessories/keyboards/c/579", "category": "electronics", "pages": 6},
    "printers":                {"url": "https://www.croma.com/computers-tablets/printers/all-in-one-printers/c/240", "category": "electronics", "pages": 6},
    
    # 📱 Smartphones & Smartwatches
    "iphones":                 {"url": "https://www.croma.com/phones-wearables/mobile-phones/iphones/c/97", "category": "smartphones", "pages": 8},
    "android-phones":          {"url": "https://www.croma.com/phones-wearables/mobile-phones/android-phones/c/95", "category": "smartphones", "pages": 12},
    "smartwatches":            {"url": "https://www.croma.com/phones-wearables/wearables/smartwatches/c/931", "category": "electronics", "pages": 10},
    
    # 🎧 Audio & Home Theatre
    "truly-wireless-earbuds":  {"url": "https://www.croma.com/audio-video/headphones-earphones/truly-wireless-earbuds/c/611", "category": "electronics", "pages": 10},
    "bluetooth-headphones":    {"url": "https://www.croma.com/audio-video/headphones-earphones/bluetooth-headphones/c/1014", "category": "electronics", "pages": 10},
    "anc-headphones":          {"url": "https://www.croma.com/audio-video/headphones-earphones/noise-cancellation-earphones-headphones-earbuds/c/80", "category": "electronics", "pages": 6},
    "portable-speakers":       {"url": "https://www.croma.com/audio-video/speakers-media-players/portable-bluetooth-speakers/c/279", "category": "electronics", "pages": 8},
    "soundbars-home-theatre":  {"url": "https://www.croma.com/audio-video/home-theatres-sound-bars/c/44", "category": "electronics", "pages": 8},
    "smart-speakers":          {"url": "https://www.croma.com/audio-video/speakers-media-players/smart-speakers/c/1008", "category": "electronics", "pages": 4},
    
    # 📺 Televisions & Displays
    "oled-tvs":                {"url": "https://www.croma.com/televisions-accessories/led-tvs/oled-tvs/c/1000", "category": "electronics", "pages": 6},
    "4k-smart-tvs":            {"url": "https://www.croma.com/televisions-accessories/led-tvs/4k-ultra-hd-tvs/c/999", "category": "electronics", "pages": 12},
    "qled-tvs":                {"url": "https://www.croma.com/televisions-accessories/led-tvs/qled-tvs/c/897", "category": "electronics", "pages": 6},
    
    # ❄️ Home & Large Appliances
    "air-conditioners":        {"url": "https://www.croma.com/home-appliances/air-conditioners/c/46", "category": "appliances", "pages": 12},
    "double-door-fridges":     {"url": "https://www.croma.com/home-appliances/refrigerators-freezers/double-door-refrigerators/c/397", "category": "appliances", "pages": 8},
    "single-door-fridges":     {"url": "https://www.croma.com/home-appliances/refrigerators-freezers/single-door-refrigerators/c/741", "category": "appliances", "pages": 8},
    "front-load-washing":      {"url": "https://www.croma.com/home-appliances/washing-machines-dryers/front-load-washing-machines/c/404", "category": "appliances", "pages": 8},
    "top-load-washing":        {"url": "https://www.croma.com/home-appliances/washing-machines-dryers/top-load-washing-machines/c/405", "category": "appliances", "pages": 8},
    "storage-geysers":         {"url": "https://www.croma.com/home-appliances/geysers/storage-water-heaters/c/746", "category": "appliances", "pages": 8},
    "instant-geysers":         {"url": "https://www.croma.com/home-appliances/geysers/instant-water-heaters/c/745", "category": "appliances", "pages": 6},
    
    # 🍳 Kitchen, Grooming & Cameras
    "convection-microwaves":   {"url": "https://www.croma.com/kitchen-appliances/microwave-ovens/convection-microwave-ovens/c/487", "category": "home", "pages": 8},
    "solo-microwaves":         {"url": "https://www.croma.com/kitchen-appliances/microwave-ovens/solo-microwave-ovens/c/489", "category": "home", "pages": 6},
    "otg-ovens":               {"url": "https://www.croma.com/kitchen-appliances/microwave-ovens/oven-toaster-grills/c/468", "category": "home", "pages": 6},
    "trimmers-grooming":       {"url": "https://www.croma.com/grooming-personal-care/personal-grooming/trimmers/c/444", "category": "beauty", "pages": 8},
    "hair-dryers":             {"url": "https://www.croma.com/grooming-personal-care/hair-care-products/hair-dryers/c/442", "category": "beauty", "pages": 6},
    "cctv-security-cameras":   {"url": "https://www.croma.com/home-appliances/home-safety-security/cctv-video-security/c/379", "category": "appliances", "pages": 6},
    "professional-cameras":    {"url": "https://www.croma.com/cameras/professional-cameras/c/548", "category": "electronics", "pages": 6},
    
    # ⚡ Flash Deals & Clearance Campaigns
    "campaign-deals":          {"url": "https://www.croma.com/campaign/top-deals/c/1000", "category": "electronics", "pages": 5}
}

async def discover_category(cat_key: str, max_pages: int = 5, sort_mode: str = "popularity") -> List[Dict[str, Any]]:
    """
    Discovers deals for a specific Croma category across pages.
    Supports sort_mode='discount' (highest discounts first) and 'popularity'.
    """
    cat_info = CROMA_CATEGORIES.get(cat_key, {})
    base_url = cat_info.get("url", f"https://www.croma.com/{cat_key}")
    category = cat_info.get("category", "electronics")
    
    results = []
    seen_ids = set()

    async with AsyncSession(impersonate="chrome124", timeout=config.SCRAPER_TIMEOUT) as session:
        for page in range(max_pages):
            if sort_mode == "discount":
                page_url = f"{base_url}?q=%3Adiscount-desc&page={page}"
            else:
                page_url = f"{base_url}?page={page}"
            try:
                r = await session.get(page_url, timeout=12)
                if r.status_code != 200 or not r.text:
                    break

                start = r.text.find("window.__INITIAL_DATA__")
                if start == -1:
                    break

                eq = r.text.find("=", start)
                sub = r.text[eq+1:].strip()
                brace = sub.find("{")
                target_str = sub[brace:]
                target_str = re.sub(r':\s*undefined\b', ': null', target_str)
                
                decoder = json.JSONDecoder()
                data, _ = decoder.raw_decode(target_str)
                
                plp = data.get("plpReducer", {}).get("plpData", {})
                products = plp.get("products", [])
                if not products:
                    break

                for p in products:
                    try:
                        code = str(p.get("code") or "")
                        if not code or code in seen_ids:
                            continue
                        seen_ids.add(code)

                        name = clean_title(p.get("name") or "")
                        if not name or len(name) < 5:
                            continue

                        # Selling Price
                        price_obj = p.get("price") or {}
                        price = float(str(price_obj.get("value") or 0).replace(',', ''))
                        
                        # MRP Price
                        mrp_obj = p.get("mrp") or p.get("mrpPrice") or {}
                        if isinstance(mrp_obj, dict):
                            mrp = float(str(mrp_obj.get("value") or price).replace(',', ''))
                        else:
                            mrp = float(str(mrp_obj or price).replace(',', ''))

                        if price <= 0:
                            continue

                        if not mrp or mrp < price:
                            mrp = price

                        if mrp > (4.0 * price):
                            mrp = round((price * 1.35) / 10) * 10

                        # Rating & Review Count
                        rating = 0.0
                        if p.get("rating") is not None or p.get("averageRating") is not None:
                            try:
                                rating = round(float(p.get("rating") or p.get("averageRating")), 1)
                            except Exception:
                                rating = 0.0

                        review_count = 0
                        if p.get("reviewCount") is not None or p.get("numberOfReviews") is not None:
                            try:
                                review_count = int(p.get("reviewCount") or p.get("numberOfReviews"))
                            except Exception:
                                review_count = 0

                        # URL & Image
                        url_path = p.get("url") or ""
                        product_url = f"https://www.croma.com{url_path}" if url_path and not url_path.startswith("http") else url_path
                        
                        img_url = p.get("plpImage") or ""
                        if not img_url and p.get("images"):
                            img_url = p["images"][0].get("url") or ""

                        # Brand
                        brand = p.get("manufacturer") or ""

                        results.append({
                            "platform": "croma",
                            "platform_id": code,
                            "title": name,
                            "brand": brand,
                            "category": category,
                            "current_price": price,
                            "mrp": mrp,
                            "rating": rating,
                            "review_count": review_count,
                            "product_url": product_url,
                            "affiliate_url": product_url,
                            "image_url": img_url,
                            "in_stock": True,
                            "is_renewed": False
                        })
                    except Exception as pe:
                        logger.debug(f"Error parsing Croma product: {pe}")

                await asyncio.sleep(1.0)

            except Exception as e:
                logger.warning(f"Error discovering Croma {cat_key} page {page}: {e}")
                break

    return results

async def discover_deals_page() -> List[Dict[str, Any]]:
    """
    Crawls Croma Flash Deals & High-Discount Deals across top categories.
    Sorts by :discount-desc to pull live 40% to 80% OFF clearance items.
    """
    all_deals = []
    top_deal_cats = ["laptops", "4k-smart-tvs", "mobile-phones", "bluetooth-headphones", "air-conditioners"]
    
    # 1. Crawl campaign deals hub
    try:
        camp_deals = await discover_category("campaign-deals", max_pages=3)
        all_deals.extend(camp_deals)
    except Exception as e:
        logger.debug(f"Error crawling Croma campaign deals: {e}")

    # 2. Crawl top categories sorted by highest discount
    for cat in top_deal_cats:
        try:
            cat_deals = await discover_category(cat, max_pages=2, sort_mode="discount")
            all_deals.extend(cat_deals)
        except Exception as e:
            logger.debug(f"Error crawling Croma flash deals for {cat}: {e}")

    return all_deals
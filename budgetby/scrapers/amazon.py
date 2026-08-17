"""
BudgetBy — Amazon Scraper
"""
import re
from selectolax.parser import HTMLParser
from curl_cffi.requests import AsyncSession
from budgetby.scrapers.base import BaseScraper
from budgetby.scrapers.utils import get_random_ua, extract_price, clean_title
from budgetby import config

class AmazonScraper(BaseScraper):
    async def _do_scrape_product(self, url: str) -> dict:
        asin_match = re.search(r'/dp/([A-Z0-9]{10})', url)
        if not asin_match:
            asin_match = re.search(r'/product/([A-Z0-9]{10})', url)
            
        affiliate_url = f"{url}?tag={config.AMAZON_ASSOCIATE_TAG}"
        
        async with AsyncSession(impersonate="chrome", headers={"User-Agent": get_random_ua()}) as s:
            r = await s.get(url, timeout=config.SCRAPER_TIMEOUT)
            
        tree = HTMLParser(r.text)
        
        title_node = tree.css_first("#productTitle")
        title = clean_title(title_node.text()) if title_node else ""
        
        # Price
        price = 0.0
        for sel in ["#priceblock_dealprice", "#priceblock_ourprice", ".a-price .a-offscreen", "span.a-price-whole"]:
            node = tree.css_first(sel)
            if node:
                price = extract_price(node.text())
                if price > 0:
                    break
                    
        # MRP (Strike-through list price)
        mrp = 0.0
        for sel in [
            "span.basisPrice span.a-offscreen",
            "div#corePriceDisplay_desktop_feature_div span.a-text-price span.a-offscreen",
            "span.a-price.a-text-price span.a-offscreen",
            "span[data-a-strike='true']",
            "span.a-text-strike",
            "td.a-span12.a-color-secondary.a-size-base span.a-price.a-text-price span.a-offscreen",
            ".priceBlockStrikePriceString",
            "#priceblock_saleprice_lbl + span"
        ]:
            node = tree.css_first(sel)
            if node:
                mrp_cand = extract_price(node.text())
                if mrp_cand > (price or 0):
                    mrp = mrp_cand
                    break

        if not mrp or mrp < (price or 0):
            mrp = price
            
        # Rating
        rating_node = tree.css_first(".a-icon-alt")
        rating = 0.0
        if rating_node:
            rating_match = re.search(r'([\d.]+)\s*out of', rating_node.text())
            if rating_match:
                rating = float(rating_match.group(1))
                
        # Review count
        rc_node = tree.css_first("#acrCustomerReviewText")
        review_count = 0
        if rc_node:
            review_count = int(extract_price(rc_node.text()))
            
        # Image
        img_node = tree.css_first("#landingImage") or tree.css_first("#imgBlkFront")
        image_url = img_node.attributes.get("src") if img_node else ""
        
        # In stock
        out_of_stock_node = tree.css_first("#outOfStock")
        in_stock = not bool(out_of_stock_node)
        
        # Coupons
        has_coupon = False
        coupon_value = 0.0
        for sel in ["#couponBadgeRegularVpc", "#couponText", ".couponBadge", "[id*='coupon']"]:
            node = tree.css_first(sel)
            if node:
                has_coupon = True
                coupon_text = node.text()
                if "%" in coupon_text:
                    match = re.search(r'(\d+)%', coupon_text)
                    if match:
                        coupon_value = price * (float(match.group(1)) / 100)
                else:
                    coupon_value = extract_price(coupon_text)
                break
                
        # Bank offers
        has_bank_offer = False
        bank_offer_text = ""
        for sel in ["#itemBuyBoxBankOfferText", ".bankOfferText", "[data-feature-name='bankOffers'] li"]:
            node = tree.css_first(sel)
            if node:
                has_bank_offer = True
                bank_offer_text = clean_title(node.text())
                break
                
        # Renewed
        is_renewed = "Renewed" in title or "Refurbished" in title or "renewed" in r.text.lower()
        
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
            "has_coupon": has_coupon,
            "coupon_value": coupon_value,
            "has_bank_offer": has_bank_offer,
            "bank_offer_text": bank_offer_text,
            "is_renewed": is_renewed,
            "affiliate_url": affiliate_url
        }

    async def _do_scrape_listing(self, url: str) -> list[dict]:
        async with AsyncSession(impersonate="chrome", headers={"User-Agent": get_random_ua()}) as s:
            r = await s.get(url, timeout=config.SCRAPER_TIMEOUT)
            
        tree = HTMLParser(r.text)
        products = []
        seen = set()
        
        for a in tree.css("a"):
            href = a.attributes.get("href", "")
            if not href: continue
            match = re.search(r'/dp/([A-Z0-9]{10})', href)
            if match:
                asin = match.group(1)
                if asin not in seen:
                    seen.add(asin)
                    p_url = f"https://www.amazon.in/dp/{asin}"
                    title = clean_title(a.text())
                    products.append({
                        "platform_id": asin,
                        "product_url": p_url,
                        "title": title
                    })
        return products

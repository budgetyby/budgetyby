import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from budgetby.scrapers.utils import clean_title

def format_price(amount: float | int | None) -> str:
    """Format amount as ₹1,23,456"""
    if amount is None:
        return "N/A"
    try:
        amount = int(amount)
    except ValueError:
        return f"₹{amount}"
        
    s = str(amount)
    if len(s) <= 3:
        return f"₹{s}"
    last3 = s[-3:]
    other = s[:-3]
    other_parts = []
    while other:
        other_parts.append(other[-2:])
        other = other[:-2]
    other_parts.reverse()
    return f"₹{','.join(other_parts)},{last3}"

def build_buy_button(url: str, text: str = "🛒 Buy Now") -> InlineKeyboardMarkup:
    """Create an InlineKeyboardMarkup with a single URL button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, url=url)]])

def format_mega_deal(product: dict, deal_result: dict = None) -> str:
    """Format a 80+ score MEGA DEAL."""
    title = html.escape(clean_title(product.get("title", "")))
    current_price = product.get("current_price", 0)
    mrp = product.get("mrp", 0)
    platform = (product.get("platform") or "Store").capitalize()
    savings = mrp - current_price if mrp and mrp > current_price else 0
    pct = round((savings / mrp) * 100) if mrp and mrp > 0 else 0
    rating = product.get("rating", "")
    rc = product.get("review_count", 0)
    url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
    
    text = f"🚨 <b>MEGA PRICE DROP ALERT! ({platform})</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🛍️ <b>{title}</b>\n\n"
    if savings > 0:
        text += f"💸 <b>Steal Price:</b> <b>{format_price(current_price)}</b> (<s>{format_price(mrp)}</s>)\n"
        text += f"🏷️ <b>Massive Savings:</b> <b>{pct}% OFF</b> (Save {format_price(savings)})\n"
    else:
        text += f"💸 <b>Deal Price:</b> <b>{format_price(current_price)}</b>\n"
        
    if rating:
        rc_str = f" ({rc:,}+ reviews)" if rc and rc > 10 else ""
        text += f"⭐ <b>Rating:</b> {rating} ★{rc_str}\n"
        
    if url:
        text += f"\n🛒 <b>Buy Directly on {platform}:</b>\n👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += "🔥 <i>Lowest price recorded — grab it now!</i>"
        
    return text

def format_today_deal(product: dict, deal_result: dict = None) -> str:
    """Format a Today's Deal / Flash Sale alert."""
    title = html.escape(clean_title(product.get("title", "")))
    current_price = product.get("current_price", 0)
    mrp = product.get("mrp", 0)
    platform = (product.get("platform") or "Store").capitalize()
    savings = mrp - current_price if mrp and mrp > current_price else 0
    pct = round((savings / mrp) * 100) if mrp and mrp > 0 else 0
    rating = product.get("rating", "")
    rc = product.get("review_count", 0)
    url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")

    text = f"⚡ <b>TODAY'S FLASH DEAL! ({platform})</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🛍️ <b>{title}</b>\n\n"
    if savings > 0:
        text += f"💸 <b>Deal Price:</b> <b>{format_price(current_price)}</b> (<s>{format_price(mrp)}</s>)\n"
        text += f"🏷️ <b>Discount:</b> <b>{pct}% OFF</b> (Save {format_price(savings)})\n"
    else:
        text += f"💸 <b>Deal Price:</b> <b>{format_price(current_price)}</b>\n"

    if rating:
        rc_str = f" ({rc:,}+ reviews)" if rc and rc > 10 else ""
        text += f"⭐ <b>Rating:</b> {rating} ★{rc_str}\n"

    if url:
        text += f"\n🛒 <b>Buy Directly on {platform}:</b>\n👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += "⚡ <i>Limited time offer — grab it before it sells out!</i>"

    return text


def format_hot_deal(product: dict, deal_result: dict = None) -> str:
    """Format a 60-79 score HOT DEAL."""
    title = html.escape(clean_title(product.get("title", "")))
    current_price = product.get("current_price", 0)
    mrp = product.get("mrp", 0)
    platform = (product.get("platform") or "Store").capitalize()
    savings = mrp - current_price if mrp and mrp > current_price else 0
    pct = round((savings / mrp) * 100) if mrp and mrp > 0 else 0
    rating = product.get("rating", "")
    rc = product.get("review_count", 0)
    url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
    
    text = f"🔥 <b>HOT PRICE DROP! ({platform})</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🛍️ <b>{title}</b>\n\n"
    if savings > 0:
        text += f"💸 <b>Offer Price:</b> <b>{format_price(current_price)}</b> (<s>{format_price(mrp)}</s>)\n"
        text += f"🏷️ <b>Discount:</b> <b>{pct}% OFF</b> (Save {format_price(savings)})\n"
    else:
        text += f"💸 <b>Offer Price:</b> <b>{format_price(current_price)}</b>\n"
        
    if rating:
        rc_str = f" ({rc:,}+ reviews)" if rc and rc > 10 else ""
        text += f"⭐ <b>Rating:</b> {rating} ★{rc_str}\n"
        
    if url:
        text += f"\n🛒 <b>Buy Directly on {platform}:</b>\n👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += "🔥 <i>Great deal with high savings — check it out!</i>"
        
    return text

def format_good_deal(product: dict, deal_result: dict = None) -> str:
    """Format a 35-59 score Good Deal."""
    title = html.escape(clean_title(product.get("title", "")))
    current_price = product.get("current_price", 0)
    mrp = product.get("mrp", 0)
    platform = (product.get("platform") or "Store").capitalize()
    savings = mrp - current_price if mrp and mrp > current_price else 0
    pct = round((savings / mrp) * 100) if mrp and mrp > 0 else 0
    url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
    
    text = f"✅ <b>PRICE DROP ALERT ({platform})</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🛍️ <b>{title}</b>\n\n"
    if savings > 0:
        text += f"💸 <b>Deal Price:</b> <b>{format_price(current_price)}</b> (<s>{format_price(mrp)}</s>)\n"
        text += f"🏷️ <b>Discount:</b> <b>{pct}% OFF</b>\n"
    else:
        text += f"💸 <b>Deal Price:</b> <b>{format_price(current_price)}</b>\n"
        
    if url:
        text += f"\n🛒 <b>Buy Directly on {platform}:</b>\n👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━"
    return text

def format_evergreen_deal(product: dict, post_count: int = 1) -> str:
    """Format an evergreen deal repost."""
    title = html.escape(clean_title(product.get("title", "")))
    current_price = product.get("current_price", 0)
    mrp = product.get("mrp", 0)
    platform = (product.get("platform") or "Store").capitalize()
    savings = mrp - current_price if mrp and mrp > current_price else 0
    pct = round((savings / mrp) * 100) if mrp and mrp > 0 else 0
    rating = product.get("rating", "")
    rc = product.get("review_count", 0)
    url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
    
    header = "🌟 <b>HANDPICKED BESTSELLER DEAL!</b>" if post_count == 1 else "🔔 <b>DEAL REMINDER — DON'T MISS OUT!</b>"
    text = f"{header} ({platform})\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🛍️ <b>{title}</b>\n\n"
    if savings > 0:
        text += f"💸 <b>Offer Price:</b> <b>{format_price(current_price)}</b> (<s>{format_price(mrp)}</s>)\n"
        text += f"🏷️ <b>Discount:</b> <b>{pct}% OFF</b> (Save {format_price(savings)})\n"
    else:
        text += f"💸 <b>Offer Price:</b> <b>{format_price(current_price)}</b>\n"
        
    if rating:
        rc_str = f" ({rc:,}+ reviews)" if rc and rc > 10 else ""
        text += f"⭐ <b>Rating:</b> {rating} ★{rc_str}\n"
        
    if url:
        text += f"\n🛒 <b>Buy Directly on {platform}:</b>\n👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += "✨ <i>Top rated product with verified discount!</i>"
    return text

def format_refurbished_deal(product: dict, new_product: dict = None) -> str:
    """Format a refurbished deal with optional new product comparison."""
    title = html.escape(clean_title(product.get("title", "")))
    current_price = product.get("current_price", 0)
    platform = (product.get("platform") or "Store").capitalize()
    url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
    text = f"♻️ <b>VERIFIED REFURBISHED DEAL! ({platform})</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🛍️ <b>{title}</b>\n\n"
    text += f"💸 <b>Refurbished Price:</b> <b>{format_price(current_price)}</b>\n"
    if new_product:
        new_price = new_product.get("current_price", 0)
        text += f"🏷️ <b>Brand New Price:</b> <s>{format_price(new_price)}</s>\n"
    if url:
        text += f"\n🛒 <b>Buy Directly on {platform}:</b>\n👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += "✨ <i>Certified refurbished with warranty!</i>"
    return text

def format_bundle_deal(bundle_data: dict) -> str:
    """Format a bundle deal containing multiple items."""
    text = "📦 <b>COMBO BUNDLE DEAL!</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    items = bundle_data.get("items", [])
    total_separate = sum(i.get("price", 0) for i in items)
    bundle_price = bundle_data.get("bundle_price", 0)
    savings = total_separate - bundle_price
    
    for item in items:
        text += f"• <b>{item.get('name')}</b>: {format_price(item.get('price', 0))}\n"
        
    text += f"\n💸 <b>Bundle Price:</b> <b>{format_price(bundle_price)}</b> (<s>{format_price(total_separate)}</s>)\n"
    if savings > 0:
        pct = round((savings / total_separate) * 100) if total_separate > 0 else 0
        text += f"🏷️ <b>Combo Savings:</b> <b>{pct}% OFF</b> (Save {format_price(savings)})\n"
    text += "━━━━━━━━━━━━━━━━━━━━━"
    return text

def format_back_in_stock(product: dict, days_oos: int = 0) -> str:
    """Format a back in stock notification."""
    title = html.escape(clean_title(product.get("title", "")))
    current_price = product.get("current_price", 0)
    mrp = product.get("mrp", 0)
    platform = (product.get("platform") or "Store").capitalize()
    savings = mrp - current_price if mrp and mrp > current_price else 0
    pct = round((savings / mrp) * 100) if mrp and mrp > 0 else 0
    rating = product.get("rating")
    rc = product.get("review_count", 0)
    url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
    
    text = f"🔔 <b>BACK IN STOCK ALERT! ({platform})</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🛍️ <b>{title}</b>\n\n"
    if savings > 0:
        text += f"💸 <b>Current Price:</b> <b>{format_price(current_price)}</b> (<s>{format_price(mrp)}</s>)\n"
        text += f"🏷️ <b>Discount:</b> <b>{pct}% OFF</b>\n"
    else:
        text += f"💸 <b>Current Price:</b> <b>{format_price(current_price)}</b>\n"
    if rating:
        rc_str = f" ({rc:,}+ reviews)" if rc and rc > 10 else ""
        text += f"⭐ <b>Rating:</b> {rating} ★{rc_str}\n"
    if url:
        text += f"\n🛒 <b>Buy Directly on {platform}:</b>\n👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += "⚡ <i>Limited inventory restocked — grab before it sells out!</i>"
    return text

def format_variant_deal(product: dict, variants: list) -> str:
    """Format a deal with multiple variants."""
    title = html.escape(clean_title(product.get("title", "")))
    platform = (product.get("platform") or "Store").capitalize()
    url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
    text = f"🎨 <b>MULTIPLE VARIANTS ON SALE! ({platform})</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🛍️ <b>{title}</b>\n\n"
    variants_sorted = sorted(variants, key=lambda x: x.get("price", 0))
    for v in variants_sorted:
        text += f"• {v.get('name')}: <b>{format_price(v.get('price', 0))}</b>\n"
    if url:
        text += f"\n🛒 <b>Buy Directly on {platform}:</b>\n👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━"
    return text

def format_budget_segment(segment_name: str, deals: list) -> str:
    """Format a roundup of best deals in a budget segment."""
    text = f"📋 <b>Top {segment_name} Deals Right Now!</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    for d in deals:
        url = d.get('affiliate_url') or d.get('product_url') or d.get('url', '')
        text += f"• <b>{d.get('title')}</b> — <b>{format_price(d.get('current_price'))}</b>\n  👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━"
    return text

def format_trending_roundup(category: str, deals: list) -> str:
    """Format a trending roundup for a category."""
    text = f"🔥 <b>Trending Deals in {category.title()}</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    for d in deals:
        url = d.get('affiliate_url') or d.get('product_url') or d.get('url', '')
        text += f"• <b>{d.get('title')}</b> — <b>{format_price(d.get('current_price'))}</b>\n  👉 {url}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━"
    return text

def format_deal_expiry_edit(original_caption: str, new_price: float = None, is_oos: bool = False, dropped_more: bool = False) -> str:
    """Append expiry or update notice to an existing caption."""
    if is_oos:
        return original_caption + "\n\n❌ <i>UPDATE: Out of stock!</i>"
    if new_price is not None:
        if dropped_more:
            return original_caption + f"\n\n📉 <i>UPDATE: Price dropped further to {format_price(new_price)}!</i>"
        else:
            return original_caption + f"\n\n⚠️ <i>UPDATE: Price changed to {format_price(new_price)}. Deal may be over.</i>"
    return original_caption + "\n\n⚠️ <i>UPDATE: Deal has expired.</i>"

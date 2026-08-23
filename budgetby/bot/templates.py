"""
Message formatting templates for Telegram.
All templates use HTML mode.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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
    title = product.get("title", "")
    current_price = product.get("current_price", 0)
    mrp = product.get("mrp", 0)
    savings = mrp - current_price if mrp and mrp > current_price else 0
    rating = product.get("rating", "")
    
    text = "🚨 <b>MEGA DEAL ALERT!</b>\n\n"
    text += f"<b>{title}</b>\n\n"
    if savings > 0:
        text += f"📉 Price: {format_price(current_price)} (<s>{format_price(mrp)}</s>)\n"
        text += f"💰 You Save: {format_price(savings)}\n"
    else:
        text += f"📉 Price: {format_price(current_price)}\n"
        
    if product.get("has_coupon"):
        coupon_val = product.get("coupon_value")
        if coupon_val:
            text += f"🎫 Coupon: Save {format_price(coupon_val)} more!\n"
        else:
            text += f"🎫 Coupon: Extra savings available!\n"
            
    if product.get("has_bank_offer"):
        text += f"💳 Bank Offer: {product.get('bank_offer_text', 'Available')}\n"
        
    if rating:
        text += f"⭐ Rating: {rating}\n"
        
    return text

def format_today_deal(product: dict, deal_result: dict = None) -> str:
    """Format a Today's Deal / Flash Sale alert."""
    title = product.get("title", "")
    current_price = product.get("current_price", 0)
    mrp = product.get("mrp", 0)
    platform = (product.get("platform") or "store").capitalize()
    savings = mrp - current_price if mrp and mrp > current_price else 0
    pct = round((savings / mrp) * 100) if mrp and mrp > 0 else 0
    rating = product.get("rating", "")

    text = f"⚡ <b>TODAY'S DEAL ALERT! ({platform})</b>\n\n"
    text += f"<b>{title}</b>\n\n"
    if savings > 0:
        text += f"💥 Deal Price: <b>{format_price(current_price)}</b> (<s>{format_price(mrp)}</s>)\n"
        text += f"🏷️ Discount: <b>{pct}% OFF</b> (Save {format_price(savings)})\n"
    else:
        text += f"💥 Deal Price: <b>{format_price(current_price)}</b>\n"

    if rating:
        text += f"⭐ Rating: {rating} ★\n"

    return text


def format_hot_deal(product: dict, deal_result: dict = None) -> str:
    """Format a 60-79 score HOT DEAL."""
    title = product.get("title", "")
    current_price = product.get("current_price", 0)
    mrp = product.get("mrp", 0)
    
    text = "🔥 <b>HOT DEAL!</b>\n\n"
    text += f"<b>{title}</b>\n\n"
    if mrp and mrp > current_price:
        text += f"Price: {format_price(current_price)} (<s>{format_price(mrp)}</s>)\n"
    else:
        text += f"Price: {format_price(current_price)}\n"
        
    return text

def format_good_deal(product: dict, deal_result: dict = None) -> str:
    """Format a 35-59 score Good Deal."""
    title = product.get("title", "")
    current_price = product.get("current_price", 0)
    text = "✅ <b>Good Price Drop</b>\n\n"
    text += f"<b>{title}</b>\n"
    text += f"Price: {format_price(current_price)}\n"
    return text

def format_evergreen_deal(product: dict, post_count: int) -> str:
    """Format an evergreen deal repost."""
    title = product.get("title", "")
    current_price = product.get("current_price", 0)
    header = "⏰ <b>STILL AVAILABLE</b>" if post_count == 1 else "🔔 <b>REMINDER</b>"
    text = f"{header}\n\n<b>{title}</b>\nPrice: {format_price(current_price)}\n"
    return text

def format_refurbished_deal(product: dict, new_product: dict = None) -> str:
    """Format a refurbished deal with optional new product comparison."""
    title = product.get("title", "")
    current_price = product.get("current_price", 0)
    text = "♻️ <b>REFURBISHED DEAL</b>\n\n"
    text += f"<b>{title}</b>\n\n"
    text += f"Refurbished Price: {format_price(current_price)}\n"
    if new_product:
        new_price = new_product.get("current_price", 0)
        text += f"Brand New Product Price: {format_price(new_price)}\n"
    text += "\n<i>Note: This is a refurbished product.</i>\n"
    return text

def format_bundle_deal(bundle_data: dict) -> str:
    """Format a bundle deal containing multiple items."""
    text = "📦 <b>BUNDLE DEAL</b>\n\n"
    items = bundle_data.get("items", [])
    total_separate = sum(i.get("price", 0) for i in items)
    bundle_price = bundle_data.get("bundle_price", 0)
    savings = total_separate - bundle_price
    
    for item in items:
        text += f"• {item.get('name')}: {format_price(item.get('price', 0))}\n"
        
    text += f"\nTotal separate cost: {format_price(total_separate)}\n"
    text += f"Bundle price: <b>{format_price(bundle_price)}</b>\n"
    if savings > 0:
        text += f"💰 You Save: {format_price(savings)}\n"
        
    return text

def format_back_in_stock(product: dict, days_oos: int) -> str:
    """Format a back in stock notification."""
    title = product.get("title", "")
    current_price = product.get("current_price", 0)
    text = "🔔 <b>BACK IN STOCK!</b>\n\n"
    text += f"<b>{title}</b>\n"
    text += f"Price: {format_price(current_price)}\n"
    if days_oos > 0:
        text += f"<i>(Was out of stock for {days_oos} days)</i>\n"
    return text

def format_variant_deal(product: dict, variants: list) -> str:
    """Format a deal with multiple variants."""
    title = product.get("title", "")
    text = f"🎨 <b>MULTIPLE VARIANTS ON SALE</b>\n\n<b>{title}</b>\n\n"
    variants_sorted = sorted(variants, key=lambda x: x.get("price", 0))
    for v in variants_sorted:
        text += f"• {v.get('name')}: {format_price(v.get('price', 0))}\n"
    return text

def format_budget_segment(segment_name: str, deals: list) -> str:
    """Format a roundup of best deals in a budget segment."""
    text = f"📋 <b>Best Deals {segment_name} Today!</b>\n\n"
    for d in deals:
        text += f"• <a href='{d.get('url')}'>{d.get('title')}</a> - {format_price(d.get('current_price'))}\n"
    return text

def format_trending_roundup(category: str, deals: list) -> str:
    """Format a trending roundup for a category."""
    text = f"🔥 <b>Trending Now: {category}</b>\n\n"
    for d in deals:
        text += f"• <a href='{d.get('url')}'>{d.get('title')}</a> - {format_price(d.get('current_price'))}\n"
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

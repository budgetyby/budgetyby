"""
BudgetBy — Master Configuration
All constants, thresholds, category lists, and tuning parameters.
Edit this file to customize bot behavior without touching any logic code.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ════════════════════════════════════════════════════════════════════════
# 1. CREDENTIALS & SECRETS
# ════════════════════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")

DB_HOST = os.getenv("DB_HOST", "localhost")
_default_port = "6543" if "pooler.supabase.com" in DB_HOST else "5432"
DB_PORT = int(os.getenv("DB_PORT", _default_port))
DB_NAME = os.getenv("DB_NAME", "budgetby")
DB_USER = os.getenv("DB_USER", "budgetby")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_SSL = os.getenv("DB_SSL", "require" if os.getenv("DB_HOST", "localhost") != "localhost" else None)

AMAZON_ASSOCIATE_TAG = os.getenv("AMAZON_ASSOCIATE_TAG", "dealpulse21-21")
EARNKARO_API_KEY = os.getenv("EARNKARO_API_KEY", "5549565")

# ════════════════════════════════════════════════════════════════════════
# 2. SCRAPER SETTINGS
# ════════════════════════════════════════════════════════════════════════

# Number of concurrent async scraper workers
SCRAPER_WORKERS = 5

# Delay between requests (seconds) — per worker
SCRAPER_DELAY_MIN = 2.0
SCRAPER_DELAY_MAX = 5.0

# Request timeout (seconds)
SCRAPER_TIMEOUT = 15

# Max retry attempts for failed scrapes
SCRAPER_MAX_RETRIES = 3

# Retry backoff multiplier (seconds): delay = base * 2^attempt
SCRAPER_RETRY_BACKOFF_BASE = 5

# User-Agent strings for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

# ════════════════════════════════════════════════════════════════════════
# 3. DYNAMIC CHECK INTERVALS (seconds)
# ════════════════════════════════════════════════════════════════════════

PRIORITY_INTERVALS = {
    1: 20 * 60,      # Critical:   20 minutes
    2: 2 * 3600,     # High:       2 hours
    3: 6 * 3600,     # Medium:     6 hours
    4: 18 * 3600,    # Low:        18 hours
}

# Sale mode multiplier — check frequencies during detected sale events
SALE_MODE_INTERVAL_MULTIPLIER = 0.5  # 2x faster checks

# ════════════════════════════════════════════════════════════════════════
# 4. PRICE STORAGE
# ════════════════════════════════════════════════════════════════════════

DAILY_PRICE_RETENTION_DAYS = 30

# ════════════════════════════════════════════════════════════════════════
# 5. CASCADING COMPARISON BENCHMARKS
# ════════════════════════════════════════════════════════════════════════

# Margins for historical low badge qualification
BENCHMARK_MARGINS = {
    "min_30d":       0.00,   # 0% — must be AT or BELOW 30-day low
    "min_60d":       0.05,   # 5% — within 5% of 60-day low
    "min_90d":       0.08,   # 8% — within 8% of 90-day low
    "all_time_low":  0.10,   # 10% — within 10% of all-time low
}

# Category-specific minimum drop thresholds (vs 30-day median baseline)
# Format: { category: (min_drop_percentage, min_savings_inr) }
CATEGORY_MIN_DROPS = {
    "fashion":          (0.20, 200),
    "beauty":           (0.20, 150),
    "home":             (0.15, 250),
    "electronics":      (0.12, 300),
    "laptops":          (0.10, 2000),
    "smartphones":      (0.05, 1000),
    "books":            (0.15, 100),
    "sports":           (0.15, 200),
    "toys":             (0.15, 150),
    "grocery":          (0.15, 100),
    "baby":             (0.15, 200),
    "pet":              (0.15, 150),
    "automotive":       (0.12, 200),
    "appliances":       (0.12, 500),
}

# Default for categories not explicitly listed above
DEFAULT_MIN_DROP = (0.15, 200)

# ════════════════════════════════════════════════════════════════════════
# 6. DEAL SCORING WEIGHTS
# ════════════════════════════════════════════════════════════════════════

SCORE_WEIGHTS = {
    "drop_magnitude":      0.30,   # How big is the price drop?
    "historical_position": 0.20,   # Where vs historical lows?
    "commission_potential": 0.30,   # How much ₹ do we earn?
    "popularity":          0.20,   # Review count / rating
}

# Minimum score to post a deal (0-100)
MIN_DEAL_SCORE = 35

# Penalty for detected fake discount (subtracted from score)
FAKE_DISCOUNT_PENALTY = 12

# ════════════════════════════════════════════════════════════════════════
# 7. POSTING RULES
# ════════════════════════════════════════════════════════════════════════

# NO maximum limit — post every qualifying deal
MAX_POSTS_PER_DAY = None  # None = unlimited

# Hourly minimums (backfilled with evergreen deals)
MIN_POSTS_PER_HOUR_DAY = 5      # 7:00 AM - 11:00 PM IST
MIN_POSTS_PER_HOUR_NIGHT = 2    # 11:00 PM - 7:00 AM IST
DAYTIME_START_HOUR = 7          # IST
DAYTIME_END_HOUR = 23           # IST

# Delay between Telegram posts (seconds) — respects 20 msg/min limit
POST_DELAY_SECONDS = 3

# ════════════════════════════════════════════════════════════════════════
# 8. COOLDOWN SETTINGS
# ════════════════════════════════════════════════════════════════════════

# Anti-spam cooldown for price-drop & quick deals (minimum 24 hours)
PRICE_DROP_COOLDOWN_HOURS = 24

# Evergreen deal re-post cooldowns (days) by discount depth
EVERGREEN_COOLDOWNS = {
    0.60: 3,    # 60%+ OFF → re-post every 3 days
    0.40: 5,    # 40-59% OFF → every 5 days
    0.30: 7,    # 30-39% OFF → every 7 days
}

# Minimum MRP discount for evergreen deal qualification
EVERGREEN_MIN_MRP_DISCOUNT = 0.30   # 30% below MRP
EVERGREEN_MIN_SAVINGS_INR = 300     # ₹300 minimum savings
EVERGREEN_MIN_STABLE_HOURS = 24     # Price unchanged for 24+ hours

# ════════════════════════════════════════════════════════════════════════
# 9. DEAL TRACKING (Message Editing)
# ════════════════════════════════════════════════════════════════════════

# Track posted deals and edit messages if price changes
DEAL_TRACKING_HOURS = 60    # 2.5 days = 60 hours

# ════════════════════════════════════════════════════════════════════════
# 10. PRODUCT STATE MACHINE
# ════════════════════════════════════════════════════════════════════════

# Product statuses
STATUS_ACTIVE = "ACTIVE"
STATUS_TEMP_OOS = "TEMP_OOS"
STATUS_DORMANT = "DORMANT"
STATUS_ARCHIVED = "ARCHIVED"

# Transition thresholds (days of continuous OOS)
TEMP_OOS_THRESHOLD_DAYS = 0      # Immediately on first OOS
DORMANT_THRESHOLD_DAYS = 14      # 14 days OOS → dormant
ARCHIVE_THRESHOLD_DAYS = 60      # 60 days OOS → archived (stop checking)
DELETE_THRESHOLD_DAYS = 90       # 90 days OOS → delete from DB

# ════════════════════════════════════════════════════════════════════════
# 11. COMMISSION RATES (Verified August 2026)
# ════════════════════════════════════════════════════════════════════════

AMAZON_COMMISSION_RATES = {
    "fashion":       0.09,
    "beauty":        0.09,
    "shoes":         0.09,
    "watches":       0.09,
    "jewelry":       0.09,
    "luggage":       0.09,
    "home":          0.07,
    "baby":          0.06,
    "books":         0.055,
    "office":        0.05,
    "grocery":       0.048,
    "health":        0.048,
    "electronics":   0.045,
    "sports":        0.045,
    "toys":          0.045,
    "pet":           0.045,
    "garden":        0.045,
    "automotive":    0.045,
    "music":         0.045,
    "computers":     0.038,
    "appliances":    0.04,
    "videogames":    0.03,
    "smartphones":   0.015,
}

EARNKARO_COMMISSION_RATES = {
    "flipkart": {
        "fashion":       0.065,
        "electronics":   0.025,
        "smartphones":   0.0075,
        "home":          0.04,
        "beauty":        0.05,
        "default":       0.03,
    },
    "myntra": {
        "fashion_new":      0.0875,
        "fashion_existing": 0.0375,
        "default":          0.05,
    },
    "ajio": {
        "fashion":          0.085,
        "default":          0.07,
    },
    "nykaa": {
        "beauty":           0.06,
        "fashion":          0.05,
        "default":          0.05,
    },
}

# ════════════════════════════════════════════════════════════════════════
# 12. AMAZON DISCOVERY TARGETS (27 Categories)
# ════════════════════════════════════════════════════════════════════════

AMAZON_DISCOVERY_TARGETS = {
    # HIGH COMMISSION (8-10%)
    "apparel":              {"node": "1571271031", "commission": 0.09, "slug": "apparel",              "category": "fashion"},
    "beauty":               {"node": "1355016031", "commission": 0.09, "slug": "beauty",               "category": "beauty"},
    "shoes":                {"node": "1983396031", "commission": 0.09, "slug": "shoes",                "category": "fashion"},
    "watches":              {"node": "1350387031", "commission": 0.09, "slug": "watches",              "category": "fashion"},
    "jewelry":              {"node": "1953168031", "commission": 0.09, "slug": "jewelry",              "category": "fashion"},
    "luggage":              {"node": "2917436031", "commission": 0.09, "slug": "luggage",              "category": "fashion"},

    # MEDIUM COMMISSION (5-9%)
    "kitchen":              {"node": "976442031",  "commission": 0.07, "slug": "kitchen",              "category": "home"},
    "baby":                 {"node": "1571274031", "commission": 0.06, "slug": "baby",                 "category": "baby"},
    "books":                {"node": "976389031",  "commission": 0.055,"slug": "books",                "category": "books"},
    "office-products":      {"node": "3591425031", "commission": 0.05, "slug": "office-products",      "category": "books"},

    # STANDARD COMMISSION (4-5%)
    "grocery":              {"node": "2454178031", "commission": 0.048,"slug": "grocery",              "category": "grocery"},
    "hpc":                  {"node": "1350384031", "commission": 0.048,"slug": "hpc",                  "category": "health"},
    "electronics":          {"node": "976419031",  "commission": 0.045,"slug": "electronics",          "category": "electronics"},
    "sports":               {"node": "1984443031", "commission": 0.045,"slug": "sports",               "category": "sports"},
    "toys":                 {"node": "1350380031", "commission": 0.045,"slug": "toys",                 "category": "toys"},
    "pet-supplies":         {"node": "4771434031", "commission": 0.045,"slug": "pet-supplies",         "category": "pet"},
    "garden":               {"node": "3638258031", "commission": 0.045,"slug": "garden",               "category": "home"},
    "automotive":           {"node": "4252434031", "commission": 0.045,"slug": "automotive",           "category": "automotive"},
    "musical-instruments":  {"node": "4286643031", "commission": 0.045,"slug": "musical-instruments",  "category": "electronics"},

    # LOWER COMMISSION (3-4%)
    "computers":            {"node": "976392031",  "commission": 0.038,"slug": "computers",            "category": "laptops"},
    "home-improvement":     {"node": "4286640031", "commission": 0.04, "slug": "home-improvement",     "category": "home"},
    "appliances":           {"node": "1380370031", "commission": 0.04, "slug": "appliances",           "category": "appliances"},
    "videogames":           {"node": "976460031",  "commission": 0.03, "slug": "videogames",           "category": "electronics"},
    "amazon-devices":       {"node": "4156694031", "commission": 0.025,"slug": "amazon-devices",       "category": "electronics"},
    "industrial":           {"node": "4286644031", "commission": 0.03, "slug": "industrial",           "category": "home"},

    # ENGAGEMENT ONLY (0.5-2.5%)
    "smartphones":          {"node": "1389401031", "commission": 0.015,"slug": "electronics/smartphones", "category": "smartphones"},
}

# ════════════════════════════════════════════════════════════════════════
# 13. FLIPKART DISCOVERY TARGETS (80+ Categories)
# ════════════════════════════════════════════════════════════════════════

FLIPKART_DISCOVERY_TARGETS = {
    # MEN'S CLOTHING
    "mens-tshirts":              {"sid": "clo,ash,ank",    "pages": 5, "category": "fashion"},
    "mens-casual-shirts":        {"sid": "clo,ash",        "pages": 5, "category": "fashion"},
    "mens-formal-shirts":        {"sid": "clo,ash,kut",    "pages": 5, "category": "fashion"},
    "mens-jeans":                {"sid": "clo,vfi,36y",    "pages": 5, "category": "fashion"},
    "mens-trousers":             {"sid": "clo,vfi",        "pages": 5, "category": "fashion"},
    "mens-shorts":               {"sid": "clo,vfi,9xe",    "pages": 3, "category": "fashion"},
    "mens-trackpants-joggers":   {"sid": "clo,vfi,kop",    "pages": 3, "category": "fashion"},
    "mens-ethnic-kurtas":        {"sid": "clo,pbe",        "pages": 5, "category": "fashion"},
    "mens-jackets-coats":        {"sid": "clo,ash,prs",    "pages": 3, "category": "fashion"},
    "mens-innerwear-loungewear": {"sid": "clo,vfi,bvy",    "pages": 3, "category": "fashion"},

    # MEN'S FOOTWEAR
    "mens-casual-shoes":         {"sid": "clo,ajm",        "pages": 5, "category": "fashion"},
    "mens-sports-shoes":         {"sid": "clo,ajm,nvl",    "pages": 5, "category": "fashion"},
    "mens-formal-shoes":         {"sid": "clo,ajm,kut",    "pages": 3, "category": "fashion"},
    "mens-sandals-floaters":     {"sid": "clo,ajm,vhz",    "pages": 3, "category": "fashion"},

    # WOMEN'S CLOTHING
    "womens-sarees":             {"sid": "clo,8on,3eb,oot","pages": 5, "category": "fashion"},
    "womens-kurtas-suits":       {"sid": "clo,8on,3eb",    "pages": 5, "category": "fashion"},
    "womens-lehengas-gowns":     {"sid": "clo,8on,3eb,lg", "pages": 3, "category": "fashion"},
    "womens-western-tops":       {"sid": "clo,8on,vhz",    "pages": 5, "category": "fashion"},
    "womens-dresses":            {"sid": "clo,8on,vhz,drs","pages": 5, "category": "fashion"},
    "womens-jeans":              {"sid": "clo,8on,vhz,jns","pages": 5, "category": "fashion"},
    "womens-jackets-shrugs":     {"sid": "clo,8on,prs",    "pages": 3, "category": "fashion"},
    "womens-lingerie-nightwear": {"sid": "def,lingerie",    "pages": 5, "category": "fashion"},
    "womens-activewear":         {"sid": "clo,8on,ank",    "pages": 3, "category": "fashion"},
    "womens-maternity":          {"sid": "clo,8on,mat",    "pages": 2, "category": "fashion"},

    # WOMEN'S FOOTWEAR
    "womens-heels-wedges":       {"sid": "clo,8on,ajm,hel","pages": 5, "category": "fashion"},
    "womens-flats-sandals":      {"sid": "clo,8on,ajm,flt","pages": 5, "category": "fashion"},
    "womens-casual-shoes":       {"sid": "clo,8on,ajm",    "pages": 5, "category": "fashion"},
    "womens-sports-shoes":       {"sid": "clo,8on,ajm,nvl","pages": 3, "category": "fashion"},

    # KIDS' FASHION
    "boys-clothing":             {"sid": "clo,kid,boy",    "pages": 5, "category": "fashion"},
    "girls-clothing":            {"sid": "clo,kid,grl",    "pages": 5, "category": "fashion"},
    "kids-footwear":             {"sid": "clo,kid,ajm",    "pages": 3, "category": "fashion"},
    "infants-clothing":          {"sid": "clo,kid,inf",    "pages": 3, "category": "fashion"},
    "kids-ethnic-wear":          {"sid": "clo,kid,eth",    "pages": 2, "category": "fashion"},

    # ACCESSORIES
    "mens-watches":              {"sid": "clo,ash,nsc",    "pages": 5, "category": "fashion"},
    "womens-watches":            {"sid": "clo,8on,nsc",    "pages": 5, "category": "fashion"},
    "mens-sunglasses":           {"sid": "clo,ash,sun",    "pages": 3, "category": "fashion"},
    "womens-sunglasses":         {"sid": "clo,8on,sun",    "pages": 3, "category": "fashion"},
    "handbags-clutches":         {"sid": "clo,8on,bag",    "pages": 5, "category": "fashion"},
    "wallets-belts":             {"sid": "clo,ash,wlt",    "pages": 3, "category": "fashion"},
    "jewellery":                 {"sid": "clo,jew",        "pages": 5, "category": "fashion"},
    "luggage-travel-bags":       {"sid": "lugg",           "pages": 5, "category": "fashion"},

    # BEAUTY & PERSONAL CARE
    "makeup":                    {"sid": "vkn,7in,mup",    "pages": 5, "category": "beauty"},
    "skincare":                  {"sid": "vkn,7in,skn",    "pages": 5, "category": "beauty"},
    "haircare":                  {"sid": "vkn,7in,har",    "pages": 5, "category": "beauty"},
    "fragrances-deos":           {"sid": "vkn,7in,fra",    "pages": 3, "category": "beauty"},
    "personal-care-grooming":    {"sid": "vkn,7in,prc",    "pages": 3, "category": "beauty"},
    "bath-body":                 {"sid": "vkn,7in,bat",    "pages": 3, "category": "beauty"},

    # BABY PRODUCTS
    "baby-diapers":              {"sid": "kyh,2nq,dia",    "pages": 3, "category": "baby"},
    "baby-feeding":              {"sid": "kyh,2nq,fed",    "pages": 3, "category": "baby"},
    "baby-gear-strollers":       {"sid": "kyh,2nq,ger",    "pages": 3, "category": "baby"},
    "baby-skincare":             {"sid": "kyh,2nq,bat",    "pages": 2, "category": "baby"},
    "baby-clothing":             {"sid": "kyh,2nq,clo",    "pages": 3, "category": "baby"},

    # TOYS & GAMES
    "toys-educational":          {"sid": "tng,6bo,edu",    "pages": 3, "category": "toys"},
    "toys-action-figures":       {"sid": "tng,6bo,act",    "pages": 3, "category": "toys"},
    "board-games":               {"sid": "tng,6bo,brd",    "pages": 3, "category": "toys"},

    # HOME & FURNITURE
    "furniture":                 {"sid": "wge,57e",        "pages": 5, "category": "home"},
    "home-furnishing":           {"sid": "wge,12d",        "pages": 5, "category": "home"},
    "home-decor":                {"sid": "wge,t8r",        "pages": 5, "category": "home"},
    "kitchenware-dining":        {"sid": "wge,pbe",        "pages": 5, "category": "home"},
    "storage-organisers":        {"sid": "wge,sto",        "pages": 3, "category": "home"},
    "lighting":                  {"sid": "wge,lgt",        "pages": 3, "category": "home"},
    "cleaning-supplies":         {"sid": "wge,cln",        "pages": 3, "category": "home"},
    "garden-outdoors":           {"sid": "wge,grd",        "pages": 3, "category": "home"},

    # ELECTRONICS
    "mobiles":                   {"sid": "tyy,4io",        "pages": 5, "category": "smartphones"},
    "laptops":                   {"sid": "6bo,b5g",        "pages": 5, "category": "laptops"},
    "audio-headphones":          {"sid": "6bo,0pm",        "pages": 5, "category": "electronics"},
    "cameras-accessories":       {"sid": "6bo,all",        "pages": 3, "category": "electronics"},
    "computer-peripherals":      {"sid": "6bo,t2m",        "pages": 3, "category": "electronics"},
    "gaming-consoles":           {"sid": "6bo,p11",        "pages": 3, "category": "electronics"},

    # LARGE APPLIANCES
    "televisions":               {"sid": "ckf,czl",        "pages": 5, "category": "appliances"},
    "washing-machines":          {"sid": "ckf,vvg",        "pages": 3, "category": "appliances"},
    "refrigerators":             {"sid": "ckf,16t",        "pages": 3, "category": "appliances"},
    "air-conditioners":          {"sid": "ckf,273",        "pages": 3, "category": "appliances"},
    "dishwashers":               {"sid": "ckf,dsh",        "pages": 2, "category": "appliances"},

    # SMALL APPLIANCES
    "kitchen-appliances":        {"sid": "j9e,m8p",        "pages": 5, "category": "appliances"},
    "water-purifiers":           {"sid": "j9e,d30,wtr",    "pages": 3, "category": "appliances"},
    "vacuum-cleaners":           {"sid": "j9e,d30,vac",    "pages": 3, "category": "appliances"},
    "irons-steamers":            {"sid": "j9e,d30,irn",    "pages": 2, "category": "appliances"},
    "geysers-water-heaters":     {"sid": "j9e,d30,gys",    "pages": 2, "category": "appliances"},

    # HEALTH
    "health-monitors":           {"sid": "hlt,mon",        "pages": 3, "category": "health"},
    "nutrition-supplements":     {"sid": "hlt,nut",        "pages": 3, "category": "health"},
    "medical-supplies":          {"sid": "hlt,med",        "pages": 2, "category": "health"},

    # SPORTS & FITNESS
    "fitness-equipment":         {"sid": "qlo,fitness,ftn","pages": 5, "category": "sports"},
    "cricket-equipment":         {"sid": "qlo,fitness,crk","pages": 3, "category": "sports"},
    "cycling":                   {"sid": "qlo,fitness,cyc","pages": 3, "category": "sports"},
    "yoga-wellness":             {"sid": "qlo,fitness,yog","pages": 3, "category": "sports"},

    # GROCERY
    "grocery-staples":           {"sid": "7in,sta",        "pages": 5, "category": "grocery"},
    "snacks-beverages":          {"sid": "7in,snk",        "pages": 5, "category": "grocery"},
    "breakfast-dairy":           {"sid": "7in,bkf",        "pages": 3, "category": "grocery"},
    "cleaning-household":        {"sid": "7in,cln",        "pages": 3, "category": "grocery"},

    # BOOKS & STATIONERY
    "books-fiction":             {"sid": "bks,literature", "pages": 5, "category": "books"},
    "books-academic":            {"sid": "bks,academic",   "pages": 3, "category": "books"},
    "stationery-office":         {"sid": "bks,stt",        "pages": 3, "category": "books"},

    # AUTOMOTIVE & PET
    "car-accessories":           {"sid": "aut,car",        "pages": 3, "category": "automotive"},
    "bike-accessories":          {"sid": "aut,bike",       "pages": 3, "category": "automotive"},
    "pet-dog":                   {"sid": "pet,dog",        "pages": 3, "category": "pet"},
    "pet-cat":                   {"sid": "pet,cat",        "pages": 3, "category": "pet"},
}

# ════════════════════════════════════════════════════════════════════════
# 14. MYNTRA DISCOVERY TARGETS (115 Slugs)
# ════════════════════════════════════════════════════════════════════════

MYNTRA_DISCOVERY_TARGETS = {
    # MEN'S CLOTHING
    "men-tshirts":                  {"pages": 5, "category": "fashion"},
    "men-casual-shirts":            {"pages": 5, "category": "fashion"},
    "men-formal-shirts":            {"pages": 5, "category": "fashion"},
    "men-jeans":                    {"pages": 5, "category": "fashion"},
    "men-trousers":                 {"pages": 5, "category": "fashion"},
    "men-shorts":                   {"pages": 3, "category": "fashion"},
    "men-trackpants":               {"pages": 3, "category": "fashion"},
    "men-kurtas":                   {"pages": 5, "category": "fashion"},
    "men-ethnic-wear":              {"pages": 3, "category": "fashion"},
    "men-jackets":                  {"pages": 3, "category": "fashion"},
    "men-sweatshirts":              {"pages": 3, "category": "fashion"},
    "men-blazers":                  {"pages": 3, "category": "fashion"},
    "men-innerwear":                {"pages": 3, "category": "fashion"},

    # MEN'S FOOTWEAR
    "men-casual-shoes":             {"pages": 5, "category": "fashion"},
    "men-sports-shoes":             {"pages": 5, "category": "fashion"},
    "men-formal-shoes":             {"pages": 3, "category": "fashion"},
    "men-sandals":                  {"pages": 3, "category": "fashion"},
    "men-flip-flops":               {"pages": 3, "category": "fashion"},

    # MEN'S ACCESSORIES
    "men-watches":                  {"pages": 5, "category": "fashion"},
    "men-sunglasses":               {"pages": 3, "category": "fashion"},
    "men-wallets-and-belts":        {"pages": 3, "category": "fashion"},
    "men-bags":                     {"pages": 3, "category": "fashion"},
    "men-caps-and-hats":            {"pages": 2, "category": "fashion"},

    # MEN'S SPORTS
    "men-sports-wear":              {"pages": 3, "category": "sports"},
    "men-running-shoes":            {"pages": 3, "category": "sports"},
    "men-gym-and-training":         {"pages": 3, "category": "sports"},

    # WOMEN'S ETHNIC
    "women-kurtas-suits":           {"pages": 5, "category": "fashion"},
    "women-sarees":                 {"pages": 5, "category": "fashion"},
    "ethnic-tops-and-tunics":       {"pages": 5, "category": "fashion"},
    "women-lehenga-choli":          {"pages": 3, "category": "fashion"},
    "women-salwar-suits":           {"pages": 3, "category": "fashion"},
    "women-dupattas-and-shawls":    {"pages": 3, "category": "fashion"},

    # WOMEN'S WESTERN
    "women-tops":                   {"pages": 5, "category": "fashion"},
    "women-dresses":                {"pages": 5, "category": "fashion"},
    "women-jumpsuits":              {"pages": 3, "category": "fashion"},
    "women-jeans":                  {"pages": 5, "category": "fashion"},
    "women-trousers":               {"pages": 5, "category": "fashion"},
    "women-skirts":                 {"pages": 3, "category": "fashion"},
    "women-jackets":                {"pages": 3, "category": "fashion"},
    "women-sweatshirts":            {"pages": 3, "category": "fashion"},

    # WOMEN'S INNERWEAR
    "women-lingerie":               {"pages": 5, "category": "fashion"},
    "women-nightwear":              {"pages": 3, "category": "fashion"},
    "women-shapewear":              {"pages": 2, "category": "fashion"},

    # WOMEN'S FOOTWEAR
    "women-flats":                  {"pages": 5, "category": "fashion"},
    "women-heels":                  {"pages": 5, "category": "fashion"},
    "women-sports-shoes":           {"pages": 3, "category": "fashion"},
    "women-sandals":                {"pages": 3, "category": "fashion"},
    "women-boots":                  {"pages": 2, "category": "fashion"},

    # WOMEN'S BAGS & ACCESSORIES
    "women-handbags":               {"pages": 5, "category": "fashion"},
    "women-clutches":               {"pages": 3, "category": "fashion"},
    "women-backpacks":              {"pages": 3, "category": "fashion"},
    "women-jewellery":              {"pages": 5, "category": "fashion"},
    "women-watches":                {"pages": 5, "category": "fashion"},
    "women-sunglasses":             {"pages": 3, "category": "fashion"},

    # WOMEN'S SPORTS
    "women-sports-wear":            {"pages": 3, "category": "sports"},
    "women-yoga-wear":              {"pages": 2, "category": "sports"},

    # KIDS
    "boys-tshirts":                 {"pages": 5, "category": "fashion"},
    "boys-shirts":                  {"pages": 3, "category": "fashion"},
    "boys-trousers":                {"pages": 3, "category": "fashion"},
    "boys-ethnic-wear":             {"pages": 3, "category": "fashion"},
    "boys-shorts":                  {"pages": 3, "category": "fashion"},
    "girls-dresses":                {"pages": 5, "category": "fashion"},
    "girls-tops":                   {"pages": 3, "category": "fashion"},
    "girls-ethnic-wear":            {"pages": 3, "category": "fashion"},
    "girls-shorts":                 {"pages": 3, "category": "fashion"},
    "girls-skirts":                 {"pages": 3, "category": "fashion"},
    "kids-shoes":                   {"pages": 3, "category": "fashion"},
    "infants-clothing":             {"pages": 3, "category": "fashion"},
    "kids-accessories":             {"pages": 2, "category": "fashion"},
    "kids-activewear":              {"pages": 2, "category": "fashion"},

    # HOME & LIVING
    "bed-sheets":                   {"pages": 5, "category": "home"},
    "blankets-quilts-dohars":       {"pages": 3, "category": "home"},
    "cushion-covers":               {"pages": 3, "category": "home"},
    "curtains":                     {"pages": 3, "category": "home"},
    "bath-towels":                  {"pages": 3, "category": "home"},
    "carpets-rugs":                 {"pages": 3, "category": "home"},
    "wall-decor":                   {"pages": 3, "category": "home"},
    "lamps-lighting":               {"pages": 3, "category": "home"},
    "kitchen-storage":              {"pages": 3, "category": "home"},
    "cookware-kitchen-appliances":  {"pages": 3, "category": "home"},
    "dinnerware-tableware":         {"pages": 3, "category": "home"},
    "storage-organisers":           {"pages": 3, "category": "home"},

    # BEAUTY
    "makeup":                       {"pages": 5, "category": "beauty"},
    "skin-care":                    {"pages": 5, "category": "beauty"},
    "hair-care":                    {"pages": 5, "category": "beauty"},
    "perfumes-and-body-mists":      {"pages": 3, "category": "beauty"},
    "men-grooming":                 {"pages": 3, "category": "beauty"},
    "grooming-appliances":          {"pages": 3, "category": "beauty"},
    "bath-and-body":                {"pages": 3, "category": "beauty"},
    "nail-care":                    {"pages": 2, "category": "beauty"},
    "wellness-and-supplements":     {"pages": 2, "category": "beauty"},

    # GADGETS
    "headphones":                   {"pages": 3, "category": "electronics"},
    "smart-watches":                {"pages": 3, "category": "electronics"},
    "speakers":                     {"pages": 3, "category": "electronics"},
    "mobile-accessories":           {"pages": 3, "category": "electronics"},
    "power-banks":                  {"pages": 3, "category": "electronics"},
    "laptop-bags":                  {"pages": 3, "category": "fashion"},
    "backpacks":                    {"pages": 5, "category": "fashion"},
    "trolley-bags":                 {"pages": 3, "category": "fashion"},

    # SPORTS
    "sports-shoes":                 {"pages": 5, "category": "sports"},
    "sports-wear":                  {"pages": 3, "category": "sports"},
    "fitness-equipment":            {"pages": 3, "category": "sports"},
    "outdoor-sports":               {"pages": 3, "category": "sports"},

    # STATIONERY
    "stationery":                   {"pages": 2, "category": "books"},
    "notebooks-journals":           {"pages": 2, "category": "books"},
}

# ════════════════════════════════════════════════════════════════════════
# 14b. AJIO DISCOVERY TARGETS (Category Codes)
# ════════════════════════════════════════════════════════════════════════
AJIO_DISCOVERY_TARGETS = {
    "men-tshirts":       {"code": "830216014", "category": "fashion"},
    "men-shirts":        {"code": "830216013", "category": "fashion"},
    "men-jeans":         {"code": "830216001", "category": "fashion"},
    "men-trousers":      {"code": "830216002", "category": "fashion"},
    "men-footwear":      {"code": "830207",    "category": "fashion"},
    "men-jackets":       {"code": "830216010", "category": "fashion"},
    "women-kurtas":      {"code": "830303011", "category": "fashion"},
    "women-dresses":     {"code": "830316007", "category": "fashion"},
    "women-tops":        {"code": "830316018", "category": "fashion"},
    "women-jeans":       {"code": "830316009", "category": "fashion"},
    "women-footwear":    {"code": "830307",    "category": "fashion"},
    "women-handbags":    {"code": "830302001", "category": "fashion"},
    "kids-clothing":     {"code": "8304",      "category": "fashion"},
    "home-decor":        {"code": "8305",      "category": "home"},
}

# ════════════════════════════════════════════════════════════════════════
# 14c. NYKAA DISCOVERY TARGETS (Category Slugs)
# ════════════════════════════════════════════════════════════════════════
NYKAA_DISCOVERY_TARGETS = {
    # SKINCARE
    "skincare":               {"path": "skin/c/8377",                             "category": "beauty"},
    "face-wash":              {"path": "skin/cleansers/face-wash/c/8390",         "category": "beauty"},
    "sunscreen":              {"path": "skin/sun-care/face-sunscreen/c/8404",     "category": "beauty"},
    "serums":                 {"path": "skin/serums-face-oils/serums-essences/c/8401", "category": "beauty"},
    "moisturizers":           {"path": "skin/moisturizers/face-moisturizer-day-cream/c/8394", "category": "beauty"},
    "night-creams":           {"path": "skin/moisturizers/night-cream/c/8395",     "category": "beauty"},
    "toners":                 {"path": "skin/toners-mists/c/8392",                 "category": "beauty"},
    "eye-creams":             {"path": "skin/eye-care/under-eye-creams-serums/c/8408", "category": "beauty"},
    "lip-balms":              {"path": "skin/lip-care/lip-balms/c/8410",          "category": "beauty"},
    "face-masks":             {"path": "skin/masks-peels/sheet-masks/c/8407",      "category": "beauty"},
    "face-scrubs":            {"path": "skin/cleansers/face-scrubs-exfoliators/c/8389", "category": "beauty"},
    
    # MAKEUP
    "makeup-lips":            {"path": "makeup/lips/c/8327",                       "category": "beauty"},
    "lipsticks":              {"path": "makeup/lips/liquid-lipstick/c/8329",      "category": "beauty"},
    "matte-lipsticks":        {"path": "makeup/lips/matte-lipstick/c/8330",       "category": "beauty"},
    "makeup-eyes":            {"path": "makeup/eyes/c/8340",                       "category": "beauty"},
    "eyeliner":               {"path": "makeup/eyes/eyeliner/c/8342",             "category": "beauty"},
    "kajal":                  {"path": "makeup/eyes/kajal-kohl/c/8341",           "category": "beauty"},
    "mascara":                {"path": "makeup/eyes/mascara/c/8343",              "category": "beauty"},
    "eyeshadow":              {"path": "makeup/eyes/eyeshadow-palette/c/8344",     "category": "beauty"},
    "makeup-face":            {"path": "makeup/face/c/8354",                       "category": "beauty"},
    "foundation":             {"path": "makeup/face/foundation/c/8356",           "category": "beauty"},
    "compact-powder":         {"path": "makeup/face/compact/c/8357",              "category": "beauty"},
    "concealer":              {"path": "makeup/face/concealer/c/8358",            "category": "beauty"},
    "blush":                  {"path": "makeup/face/blush/c/8360",                "category": "beauty"},
    "highlighter":            {"path": "makeup/face/highlighter/c/8361",          "category": "beauty"},
    "makeup-remover":         {"path": "makeup/makeup-remover/c/8372",            "category": "beauty"},
    "makeup-brushes":         {"path": "makeup/tools-brushes/makeup-brushes/c/8366", "category": "beauty"},
    "nail-polish":            {"path": "makeup/nails/nail-polish/c/8336",         "category": "beauty"},

    # HAIRCARE
    "haircare":               {"path": "hair-care/c/9525",                         "category": "beauty"},
    "shampoo":                {"path": "hair-care/shampoo-conditioner/shampoo/c/9531", "category": "beauty"},
    "conditioner":            {"path": "hair-care/shampoo-conditioner/conditioner/c/9532", "category": "beauty"},
    "hair-oil":               {"path": "hair-care/hair-oil/c/9528",               "category": "beauty"},
    "hair-serum":             {"path": "hair-care/hair-serum-mask/c/9530",        "category": "beauty"},
    "hair-masks":             {"path": "hair-care/hair-masks/c/9537",             "category": "beauty"},
    "hair-color":             {"path": "hair-care/hair-color/c/9534",             "category": "beauty"},
    "hair-styling":           {"path": "hair-care/hair-styling/c/9535",           "category": "beauty"},

    # FRAGRANCES
    "fragrances":             {"path": "fragrance/c/8446",                         "category": "beauty"},
    "perfumes-men":           {"path": "fragrance/perfumes-edp-edt/eau-de-parfum-edp/c/8451", "category": "beauty"},
    "perfumes-women":         {"path": "fragrance/perfumes-women/c/8447",         "category": "beauty"},
    "body-mists":             {"path": "fragrance/body-mists-sprays/c/8450",      "category": "beauty"},
    "deodorants":             {"path": "fragrance/deodorants-roll-ons/c/8449",    "category": "beauty"},

    # BATH & BODY
    "bath-and-body":          {"path": "bath-body/c/8412",                         "category": "beauty"},
    "body-wash":              {"path": "bath-body/shower-gels-body-wash/c/8415",   "category": "beauty"},
    "body-lotion":            {"path": "bath-body/body-lotions-moisturizers/c/8416", "category": "beauty"},
    "hand-cream":             {"path": "bath-body/hand-care/hand-creams/c/8419",   "category": "beauty"},
    "body-scrub":             {"path": "bath-body/body-scrubs-exfoliators/c/8422", "category": "beauty"},

    # MEN'S GROOMING
    "mens-grooming":          {"path": "men/c/9564",                              "category": "beauty"},
    "mens-shaving":           {"path": "men/shaving-hair-removal/c/9571",         "category": "beauty"},
    "mens-beard-care":        {"path": "men/beard-care/c/9570",                   "category": "beauty"},
    "mens-face-care":         {"path": "men/face-care/c/9567",                    "category": "beauty"},

    # APPLIANCES & WELLNESS
    "hair-dryers":            {"path": "appliances/hair-styling-tools/hair-dryers/c/8459", "category": "appliances"},
    "straighteners":          {"path": "appliances/hair-styling-tools/hair-straighteners/c/8460", "category": "appliances"},
    "face-epilators":         {"path": "appliances/hair-removal-tools/epilators/c/8464", "category": "appliances"},
    "health-wellness":        {"path": "wellness/c/9580",                         "category": "health"},
}

# ════════════════════════════════════════════════════════════════════════
# 15. SALE EVENT CALENDAR (Hardcoded, Approximate Dates)
# ════════════════════════════════════════════════════════════════════════

SALE_CALENDAR = [
    {"name": "Republic Day Sale",      "platform": "amazon",   "month": 1,  "start_day": 14, "end_day": 20},
    {"name": "Republic Day Sale",      "platform": "flipkart", "month": 1,  "start_day": 14, "end_day": 20},
    {"name": "Summer Sale",            "platform": "amazon",   "month": 5,  "start_day": 4,  "end_day": 8},
    {"name": "Big Saving Days",        "platform": "flipkart", "month": 5,  "start_day": 1,  "end_day": 7},
    {"name": "Myntra EORS Summer",     "platform": "myntra",   "month": 6,  "start_day": 9,  "end_day": 15},
    {"name": "Prime Day",              "platform": "amazon",   "month": 7,  "start_day": 20, "end_day": 21},
    {"name": "Freedom Sale",           "platform": "amazon",   "month": 8,  "start_day": 6,  "end_day": 10},
    {"name": "Great Indian Festival",  "platform": "amazon",   "month": 10, "start_day": 8,  "end_day": 16},
    {"name": "Big Billion Days",       "platform": "flipkart", "month": 10, "start_day": 8,  "end_day": 15},
    {"name": "Myntra Big Fashion Fest","platform": "myntra",   "month": 10, "start_day": 7,  "end_day": 14},
    {"name": "Diwali Sale",            "platform": "amazon",   "month": 11, "start_day": 2,  "end_day": 5},
    {"name": "Flipkart Diwali Sale",   "platform": "flipkart", "month": 11, "start_day": 1,  "end_day": 5},
    {"name": "Myntra EORS Winter",     "platform": "myntra",   "month": 12, "start_day": 7,  "end_day": 17},
]

# Sale mode configuration
SALE_RAMP_UP_DAYS = 5             # Start ramping up discovery this many days before sale
SALE_PAGES_PER_CATEGORY = 50      # Normal = 2 pages, Sale = 50 pages
SALE_DEAL_CRAWL_INTERVAL = 900    # Flash deal crawl every 15 min during sales

# ════════════════════════════════════════════════════════════════════════
# 16. DISCOVERY SETTINGS
# ════════════════════════════════════════════════════════════════════════

# Normal mode
DISCOVERY_INTERVAL_HOURS = 6          # Run auto-discovery every 6 hours
DEALS_PAGE_CRAWL_INTERVAL_HOURS = 1   # Deals page crawl every hour
MOVERS_AND_SHAKERS_INTERVAL_HOURS = 3 # Amazon Movers & Shakers every 3 hours
NORMAL_PAGES_PER_CATEGORY = 2         # Pages to scrape per category (normal mode)

# ════════════════════════════════════════════════════════════════════════
# 17. TIMEZONE
# ════════════════════════════════════════════════════════════════════════

TIMEZONE = "Asia/Kolkata"

# ════════════════════════════════════════════════════════════════════════
# 18. DATABASE BACKUP
# ════════════════════════════════════════════════════════════════════════

BACKUP_ENABLED = True
BACKUP_HOUR = 3       # 3:00 AM IST daily backup
BACKUP_RETAIN_DAYS = 7 # Keep last 7 backup files

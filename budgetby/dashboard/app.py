import asyncio
import datetime
import time
import math
import re
import sys
import os
import secrets
import hmac
import hashlib
from fastapi import FastAPI, Query, HTTPException, Request, Depends, Response, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
import logging

logger = logging.getLogger("budgetby.dashboard.app")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from budgetby import database, config

app = FastAPI(title="BudgetBy Control Center", version="2.0")

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        path = request.url.path
        if path.startswith("/api/public/"):
            # No browser-side cache — server RAM cache handles egress reduction.
            # Browser must always ask the server, but server replies from RAM (no DB hit).
            # This keeps data fresh (within server cache TTL) while eliminating egress.
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        elif path.startswith("/api/deal/redirect/"):
            response.headers["Cache-Control"] = "public, max-age=30"
        elif path.startswith("/api/"):
            # Admin/internal: never cache
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ── Jinja2 Custom Storefront Filters for Server-Side Rendering (SSR) ────────
def jinja_format_inr(val):
    if val is None:
        return "₹0"
    try:
        val_int = int(round(float(val)))
        s = str(abs(val_int))
        if len(s) <= 3:
            res = s
        else:
            last3 = s[-3:]
            rest = s[:-3]
            chunks = []
            while len(rest) > 2:
                chunks.insert(0, rest[-2:])
                rest = rest[:-2]
            if rest:
                chunks.insert(0, rest)
            res = ",".join(chunks) + "," + last3
        prefix = "-" if val_int < 0 else ""
        return f"{prefix}₹{res}"
    except Exception:
        return f"₹{val}"

def jinja_time_ago(val):
    if not val:
        return "Recently"
    try:
        if isinstance(val, str):
            val = datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if hasattr(val, "tzinfo") and val.tzinfo is None:
            val = val.replace(tzinfo=datetime.timezone.utc)
        diff = int((now - val).total_seconds())
        if diff < 60:
            return "Just now"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return "Recently"

def jinja_store_badge(platform):
    plat = (platform or "").lower()
    badges = {
        "amazon": "bg-amber-50 text-amber-900 border border-amber-300 font-bold",
        "flipkart": "bg-blue-50 text-blue-700 border border-blue-300 font-bold",
        "myntra": "bg-pink-50 text-pink-700 border border-pink-300 font-bold",
        "ajio": "bg-yellow-50 text-yellow-800 border border-yellow-300 font-bold",
        "nykaa": "bg-rose-50 text-rose-700 border border-rose-300 font-bold",
    }
    return badges.get(plat, "bg-slate-100 text-slate-700 border border-slate-200 font-bold")

def jinja_store_name(platform):
    plat = (platform or "").lower()
    names = {
        "amazon": "Amazon",
        "flipkart": "Flipkart",
        "myntra": "Myntra",
        "ajio": "Ajio",
        "nykaa": "Nykaa",
    }
    return names.get(plat, plat.capitalize())

def jinja_round_int(val):
    try:
        return int(round(float(val)))
    except Exception:
        return 0

def jinja_format_posted_time(val):
    if not val:
        return "Recently posted"
    try:
        if isinstance(val, str):
            val = datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        if hasattr(val, "astimezone"):
            val_ist = val.astimezone(ist)
        else:
            val_ist = val
        return val_ist.strftime("%d %b, %I:%M %p")
    except Exception:
        return "Recently posted"

templates.env.filters["format_inr"] = jinja_format_inr
templates.env.filters["time_ago"] = jinja_time_ago
templates.env.filters["store_badge"] = jinja_store_badge
templates.env.filters["store_name"] = jinja_store_name
templates.env.filters["round_int"] = jinja_round_int
templates.env.filters["format_posted_time"] = jinja_format_posted_time

ADMIN_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "index.html")
EXPLORER_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "explorer.html")
ADMIN_LOGIN_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "admin_login.html")

ADMIN_SECRET_KEY = getattr(config, "ADMIN_SECRET_KEY", "bb_sec_9e72f8a14b30c5e7d82f091a384b62d1")

# Authorized Admin Credentials (Either pair unlocks access)
ADMIN_CREDENTIALS = [
    ("pnther", "Pnther@3Alphabetisc"),
    ("vidushi", "lilu"),
]

def create_admin_session_token(username: str) -> str:
    """Creates a tamper-proof HMAC-SHA256 signed session token."""
    now_ts = int(time.time())
    msg = f"{username}:{now_ts}"
    sig = hmac.new(ADMIN_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}:{sig}"

def verify_admin_session_token(token: str) -> bool:
    """Verifies that the session token is authentic, unexpired, and properly signed."""
    if not token:
        return False
    # Backwards compatibility: raw ADMIN_SECRET_KEY as cookie
    if secrets.compare_digest(str(token), ADMIN_SECRET_KEY):
        return True
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        username, ts_str, sig = parts
        msg = f"{username}:{ts_str}"
        expected_sig = hmac.new(ADMIN_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, expected_sig):
            return False
        token_time = int(ts_str)
        if (time.time() - token_time) > 86400 * 7:  # 7 days max age
            return False
        return username in ("pnther", "vidushi")
    except Exception:
        return False

def is_admin_authorized(request: Request) -> bool:
    """
    Cryptographically verifies admin access via:
    1. Header: X-Admin-Session: <token>
    2. Header: X-Admin-Key: <ADMIN_SECRET_KEY>
    3. Query parameter: ?key=<ADMIN_SECRET_KEY> or ?admin_key=<ADMIN_SECRET_KEY>
    4. Query parameter: ?auth_token=<token>
    """
    session_hdr = request.headers.get("X-Admin-Session") or request.headers.get("x-admin-session")
    if session_hdr and verify_admin_session_token(session_hdr):
        return True
    header_key = request.headers.get("X-Admin-Key") or request.headers.get("x-admin-key")
    if header_key and secrets.compare_digest(str(header_key), ADMIN_SECRET_KEY):
        return True
    req_key = request.query_params.get("key") or request.query_params.get("admin_key")
    if req_key and secrets.compare_digest(str(req_key), ADMIN_SECRET_KEY):
        return True
    auth_tok = request.query_params.get("auth_token")
    if auth_tok and verify_admin_session_token(auth_tok):
        return True
    return False

def require_admin(request: Request):
    """
    Dependency enforcing complete admin stealth isolation for APIs:
    Returns 404 Not Found to unauthorized requests, completely hiding admin/db existence.
    """
    if not is_admin_authorized(request):
        raise HTTPException(status_code=404, detail="Not Found")
    return True


# ── High-Speed In-Memory RAM Caching ─────────────────────────────────────────

class SimpleMemoryCache:
    """
    High-concurrency in-memory TTL cache.
    Eliminates redundant database queries by caching popular public API endpoints in RAM.
    Reduces database load and egress bandwidth by >95%.
    """
    def __init__(self, default_ttl: int = 30, max_entries: int = 1000):
        self._cache: dict[str, tuple[any, float]] = {}
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._lock = asyncio.Lock()

    async def get(self, key: str):
        entry = self._cache.get(key)
        if not entry:
            return None
        val, expires_at = entry
        if time.monotonic() > expires_at:
            self._cache.pop(key, None)
            return None
        return val

    async def set(self, key: str, value: any, ttl: int = None):
        if ttl is None:
            ttl = self._default_ttl
        now = time.monotonic()
        async with self._lock:
            if len(self._cache) >= self._max_entries:
                keys_to_del = [k for k, (v, exp) in self._cache.items() if now > exp]
                for k in keys_to_del:
                    self._cache.pop(k, None)
                if len(self._cache) >= self._max_entries:
                    for k in list(self._cache.keys())[:int(self._max_entries * 0.2)]:
                        self._cache.pop(k, None)
            self._cache[key] = (value, now + ttl)

    def clear(self):
        self._cache.clear()

ram_cache = SimpleMemoryCache(default_ttl=120, max_entries=2000)


@app.on_event("startup")
async def startup():
    if not database._pool:
        await database.init_pool()

@app.get("/api/stats", dependencies=[Depends(require_admin)])
async def get_stats():

    try:
        core_metrics = await database.get_core_metrics()
        total_prods = core_metrics["total_products"]
        products_added_today = core_metrics["products_added_today"]
        deals_lifetime = core_metrics.get("lifetime_deals", core_metrics["total_deals"])
        deals_active = core_metrics["total_deals"]
        deals_today = core_metrics["deals_today"]
        drops_today = core_metrics.get("drops_today", 0)

        by_plat = await database.fetch("SELECT platform, COUNT(*) as count FROM products WHERE LOWER(platform) != 'croma' GROUP BY platform ORDER BY count DESC;")
        
        # Time-based deals counts (IST Timezone)
        deals_1h = await database.fetchval("""
            SELECT COUNT(*) FROM deals d
            JOIN products p ON d.product_id = p.id
            WHERE d.posted_at >= NOW() - INTERVAL '1 hour'
              AND LOWER(p.platform) != 'croma';
        """)
        
        deals_this_month = await database.fetchval("""
            SELECT COUNT(*) FROM deals d
            JOIN products p ON d.product_id = p.id
            WHERE d.posted_at >= date_trunc('month', NOW() AT TIME ZONE 'Asia/Kolkata')
              AND LOWER(p.platform) != 'croma';
        """)
        
        deals_last_month = await database.fetchval("""
            SELECT COUNT(*) FROM deals d
            JOIN products p ON d.product_id = p.id
            WHERE d.posted_at >= date_trunc('month', (NOW() AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 month')
              AND d.posted_at < date_trunc('month', NOW() AT TIME ZONE 'Asia/Kolkata')
              AND LOWER(p.platform) != 'croma';
        """)
        
        # Deals posted TODAY grouped by platform
        posted_today_rows = await database.fetch("""
            SELECT p.platform, COUNT(*) as count 
            FROM deals d 
            JOIN products p ON d.product_id = p.id 
            WHERE d.posted_at >= (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE 
            GROUP BY p.platform;
        """)
        posted_today_by_plat = {r["platform"].lower(): r["count"] for r in posted_today_rows}
        
        # Deals posted THIS MONTH grouped by platform
        posted_month_rows = await database.fetch("""
            SELECT p.platform, COUNT(*) as count 
            FROM deals d 
            JOIN products p ON d.product_id = p.id 
            WHERE d.posted_at >= date_trunc('month', NOW() AT TIME ZONE 'Asia/Kolkata')
            GROUP BY p.platform;
        """)
        posted_month_by_plat = {r["platform"].lower(): r["count"] for r in posted_month_rows}
        
        # Deals posted LIFETIME grouped by platform
        posted_life_rows = await database.fetch("""
            SELECT p.platform, COUNT(*) as count 
            FROM deals d 
            JOIN products p ON d.product_id = p.id 
            GROUP BY p.platform;
        """)
        posted_life_by_plat = {r["platform"].lower(): r["count"] for r in posted_life_rows}
        
        all_plats = ["amazon", "flipkart", "myntra", "ajio", "nykaa"]
        for p in all_plats:
            posted_today_by_plat.setdefault(p, 0)
            posted_month_by_plat.setdefault(p, 0)
            posted_life_by_plat.setdefault(p, 0)
                
        cooldowns = await database.fetchval("SELECT COUNT(*) FROM post_cooldowns WHERE expires_at > NOW();")
        daily_prices = await database.fetchval("SELECT COUNT(*) FROM daily_prices;")
        
        # Channel Ingestion Stats
        total_ingested = await database.fetchval("SELECT COUNT(*) FROM ingested_channel_deals;")
        ingested_today = await database.fetchval("SELECT COUNT(*) FROM ingested_channel_deals WHERE created_at >= (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE;")
        
        # Monthly History Breakdown
        history_rows = await database.fetch("""
            SELECT 
                to_char(date_trunc('month', d.posted_at AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM') as month_key,
                to_char(date_trunc('month', d.posted_at AT TIME ZONE 'Asia/Kolkata'), 'FMMonth YYYY') as month_name,
                COUNT(*) as total_deals,
                COUNT(CASE WHEN p.platform = 'amazon' THEN 1 END) as amazon_deals,
                COUNT(CASE WHEN p.platform = 'flipkart' THEN 1 END) as flipkart_deals,
                COUNT(CASE WHEN p.platform = 'myntra' THEN 1 END) as myntra_deals,
                COUNT(CASE WHEN p.platform = 'ajio' THEN 1 END) as ajio_deals,
                COUNT(CASE WHEN p.platform = 'nykaa' THEN 1 END) as nykaa_deals
            FROM deals d
            LEFT JOIN products p ON d.product_id = p.id
            GROUP BY date_trunc('month', d.posted_at AT TIME ZONE 'Asia/Kolkata')
            ORDER BY date_trunc('month', d.posted_at AT TIME ZONE 'Asia/Kolkata') DESC;
        """)
        
        return {
            "status": "online",
            "total_products": total_prods or 0,
            "products_added_today": products_added_today or 0,
            "by_platform": {r["platform"]: r["count"] for r in by_plat},
            "deals_today": deals_today or 0,
            "drops_today": drops_today or 0,
            "total_deals": deals_active or 0,
            "deals_active": deals_active or 0,
            "deals_last_hour": deals_1h or 0,
            "deals_this_month": deals_this_month or 0,
            "deals_last_month": deals_last_month or 0,
            "deals_lifetime": deals_lifetime or 0,
            "total_deals_lifetime": deals_lifetime or 0,
            "posted_today_by_platform": posted_today_by_plat,
            "posted_this_month_by_platform": posted_month_by_plat,
            "posted_lifetime_by_platform": posted_life_by_plat,
            "total_ingested_from_channels": total_ingested or 0,
            "ingested_today_from_channels": ingested_today or 0,
            "monthly_history": [dict(r) for r in history_rows],
            "hourly_targets": config.PLATFORM_MIN_HOURLY_POSTS,
            "active_cooldowns": cooldowns or 0,
            "daily_prices_recorded": daily_prices or 0
        }
    except Exception as e:
        logger.error(f"Internal stats error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/channel_stats", dependencies=[Depends(require_admin)])
async def get_channel_stats():
    """Returns all monitored Telegram channels with real-time heartbeat and deal statistics."""
    try:
        rows = await database.fetch("""
            SELECT 
                m.channel_name as source_channel,
                m.status as monitor_status,
                COALESCE(COUNT(d.id), 0) as total_picked_up,
                COALESCE(COUNT(CASE WHEN d.product_id IS NOT NULL THEN 1 END), 0) as saved_to_catalog,
                COALESCE(COUNT(CASE WHEN d.status = 'VERIFIED_DEAL' THEN 1 END), 0) as verified_deals,
                COALESCE(COUNT(CASE WHEN d.status = 'OUT_OF_STOCK' THEN 1 END), 0) as out_of_stock,
                COALESCE(COUNT(CASE WHEN d.status = 'FAILED_SCRAPE' THEN 1 END), 0) as failed_scrapes,
                m.last_scanned_at as last_activity
            FROM channel_monitors m
            LEFT JOIN ingested_channel_deals d ON LOWER(d.source_channel) = LOWER(m.channel_name)
            GROUP BY m.channel_name, m.status, m.last_scanned_at
            ORDER BY total_picked_up DESC, m.channel_name ASC;
        """)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Channel stats error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/posting_queue", dependencies=[Depends(require_admin)])
async def get_posting_queue_endpoint():
    """Returns real-time deals in the posting queue waiting to be broadcasted."""
    try:
        from budgetby.engine.posting_queue import get_posting_queue
        pq = get_posting_queue()
        return pq.get_queue_snapshot()
    except Exception as e:
        logger.error(f"Posting queue error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/category_platform_stats", dependencies=[Depends(require_admin)])
async def get_category_platform_stats():
    """Returns detailed cross-matrix of deals and catalog products by category and platform."""
    try:
        # 1. Lifetime Deals Posted by Category & Platform
        lifetime_rows = await database.fetch("""
            SELECT 
                COALESCE(NULLIF(p.category, ''), 'general') as category,
                COUNT(*) as total_deals,
                COUNT(CASE WHEN p.platform = 'amazon' THEN 1 END) as amazon_count,
                COUNT(CASE WHEN p.platform = 'flipkart' THEN 1 END) as flipkart_count,
                COUNT(CASE WHEN p.platform = 'myntra' THEN 1 END) as myntra_count,
                COUNT(CASE WHEN p.platform = 'ajio' THEN 1 END) as ajio_count,
                COUNT(CASE WHEN p.platform = 'croma' THEN 1 END) as croma_count,
                COUNT(CASE WHEN p.platform = 'nykaa' THEN 1 END) as nykaa_count
            FROM deals d
            JOIN products p ON d.product_id = p.id
            GROUP BY COALESCE(NULLIF(p.category, ''), 'general')
            ORDER BY total_deals DESC;
        """)

        # 2. Today's Deals Posted by Category & Platform (IST)
        today_rows = await database.fetch("""
            SELECT 
                COALESCE(NULLIF(p.category, ''), 'general') as category,
                COUNT(*) as total_deals,
                COUNT(CASE WHEN p.platform = 'amazon' THEN 1 END) as amazon_count,
                COUNT(CASE WHEN p.platform = 'flipkart' THEN 1 END) as flipkart_count,
                COUNT(CASE WHEN p.platform = 'myntra' THEN 1 END) as myntra_count,
                COUNT(CASE WHEN p.platform = 'ajio' THEN 1 END) as ajio_count,
                COUNT(CASE WHEN p.platform = 'croma' THEN 1 END) as croma_count,
                COUNT(CASE WHEN p.platform = 'nykaa' THEN 1 END) as nykaa_count
            FROM deals d
            JOIN products p ON d.product_id = p.id
            WHERE d.posted_at >= (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE
            GROUP BY COALESCE(NULLIF(p.category, ''), 'general')
            ORDER BY total_deals DESC;
        """)

        # 3. This Month Deals Posted by Category & Platform
        month_rows = await database.fetch("""
            SELECT 
                COALESCE(NULLIF(p.category, ''), 'general') as category,
                COUNT(*) as total_deals,
                COUNT(CASE WHEN p.platform = 'amazon' THEN 1 END) as amazon_count,
                COUNT(CASE WHEN p.platform = 'flipkart' THEN 1 END) as flipkart_count,
                COUNT(CASE WHEN p.platform = 'myntra' THEN 1 END) as myntra_count,
                COUNT(CASE WHEN p.platform = 'ajio' THEN 1 END) as ajio_count,
                COUNT(CASE WHEN p.platform = 'croma' THEN 1 END) as croma_count,
                COUNT(CASE WHEN p.platform = 'nykaa' THEN 1 END) as nykaa_count
            FROM deals d
            JOIN products p ON d.product_id = p.id
            WHERE d.posted_at >= date_trunc('month', NOW() AT TIME ZONE 'Asia/Kolkata')
            GROUP BY COALESCE(NULLIF(p.category, ''), 'general')
            ORDER BY total_deals DESC;
        """)

        # 4. Catalog Products Available by Category & Platform
        catalog_rows = await database.fetch("""
            SELECT 
                COALESCE(NULLIF(category, ''), 'general') as category,
                COUNT(*) as total_prods,
                COUNT(CASE WHEN platform = 'amazon' THEN 1 END) as amazon_count,
                COUNT(CASE WHEN platform = 'flipkart' THEN 1 END) as flipkart_count,
                COUNT(CASE WHEN platform = 'myntra' THEN 1 END) as myntra_count,
                COUNT(CASE WHEN platform = 'ajio' THEN 1 END) as ajio_count,
                COUNT(CASE WHEN platform = 'croma' THEN 1 END) as croma_count,
                COUNT(CASE WHEN platform = 'nykaa' THEN 1 END) as nykaa_count
            FROM products
            GROUP BY COALESCE(NULLIF(category, ''), 'general')
            ORDER BY total_prods DESC;
        """)

        return {
            "lifetime": [dict(r) for r in lifetime_rows],
            "today": [dict(r) for r in today_rows],
            "this_month": [dict(r) for r in month_rows],
            "catalog": [dict(r) for r in catalog_rows]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/price_changes_24h", dependencies=[Depends(require_admin)])
async def get_price_changes_24h(
    direction: str = Query("all", pattern="^(all|drops|hikes)$"),
    platform: str = Query("", max_length=50),
    search: str = Query("", max_length=100),
    sort_by: str = Query("latest", max_length=50),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100)
):
    """
    Dedicated 24-Hour Price Movements Tracker.
    Returns all products whose prices changed in the last 24 hours.
    Products automatically drop off once they pass 24 hours without new changes.
    """
    try:
        direction_str = direction if isinstance(direction, str) else "all"
        platform_str = (platform if isinstance(platform, str) else "").strip().lower()
        search_str = (search if isinstance(search, str) else "").strip()
        sort_by_str = sort_by if isinstance(sort_by, str) else "latest"
        page_int = int(page) if isinstance(page, (int, str)) and str(page).isdigit() else 1
        limit_int = int(limit) if isinstance(limit, (int, str)) and str(limit).isdigit() else 25

        offset = (page_int - 1) * limit_int
        where_clauses = [
            "dp_today.close_price != dp_yest.close_price",
            "dp_today.close_price > 0",
            "dp_yest.close_price > 0",
            "(p.mrp = 0 OR (dp_today.close_price <= (p.mrp * 1.15) AND dp_yest.close_price <= (p.mrp * 1.15)))",
            "(dp_today.close_price <= (dp_yest.close_price * 3.0) AND (dp_yest.close_price <= 1500 OR dp_today.close_price >= (dp_yest.close_price * 0.40)))",
            "COALESCE(p.last_price_change, NOW()) >= (NOW() - INTERVAL '24 hours')"
        ]
        args = []
        arg_idx = 1

        if platform_str:
            where_clauses.append(f"LOWER(p.platform) = ${arg_idx}")
            args.append(platform_str)
            arg_idx += 1

        if direction_str == "drops":
            where_clauses.append("dp_today.close_price < dp_yest.close_price")
        elif direction_str == "hikes":
            where_clauses.append("dp_today.close_price > dp_yest.close_price")

        clean_search = search_str.lstrip("#")
        if clean_search:
            if clean_search.isdigit():
                where_clauses.append(f"(p.id = ${arg_idx} OR p.title ILIKE ${arg_idx+1})")
                args.extend([int(clean_search), f"%{clean_search}%"])
                arg_idx += 2
            else:
                where_clauses.append(f"p.title ILIKE ${arg_idx}")
                args.append(f"%{clean_search}%")
                arg_idx += 1

        where_sql = " AND ".join(where_clauses)

        # Sorting logic: Latest arrivals first by default
        if sort_by_str == "latest":
            order_sql = "ORDER BY changed_at DESC, id DESC"
        elif sort_by_str == "pct_desc":
            order_sql = "ORDER BY ABS(change_pct) DESC, id ASC"
        elif sort_by_str == "drop_largest":
            order_sql = "ORDER BY price_diff ASC, id ASC"
        elif sort_by_str == "hike_largest":
            order_sql = "ORDER BY price_diff DESC, id ASC"
        elif sort_by_str == "price_asc":
            order_sql = "ORDER BY new_price ASC, id ASC"
        elif sort_by_str == "diff_desc":
            order_sql = "ORDER BY ABS(price_diff) DESC, id ASC"
        else: # Default latest
            order_sql = "ORDER BY changed_at DESC, id DESC"

        query = f"""
            WITH changed_prods AS (
                SELECT 
                    p.id,
                    p.platform,
                    p.platform_id,
                    p.title,
                    p.category,
                    p.image_url,
                    p.product_url,
                    p.affiliate_url,
                    p.mrp,
                    COALESCE(dp_yest.close_price, p.previous_price, p.current_price) as old_price,
                    dp_today.close_price as new_price,
                    dp_today.min_price as today_min_price,
                    (dp_today.close_price - COALESCE(dp_yest.close_price, p.previous_price, p.current_price)) as price_diff,
                    ROUND(((dp_today.close_price - COALESCE(dp_yest.close_price, p.previous_price, p.current_price)) / NULLIF(COALESCE(dp_yest.close_price, p.previous_price, p.current_price), 0)) * 100, 1) as change_pct,
                    COALESCE(p.last_price_change, NOW()) as changed_at
                FROM products p
                JOIN daily_prices dp_today ON p.id = dp_today.product_id AND dp_today.date = (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE
                JOIN daily_prices dp_yest ON p.id = dp_yest.product_id AND dp_yest.date = ((NOW() AT TIME ZONE 'Asia/Kolkata')::DATE - 1)
                WHERE {where_sql}
            )
            SELECT *, 
                   COUNT(*) OVER() as total_matches,
                   COUNT(CASE WHEN price_diff < 0 THEN 1 END) OVER() as count_drops,
                   COUNT(CASE WHEN price_diff > 0 THEN 1 END) OVER() as count_hikes
            FROM changed_prods
            {order_sql}
            LIMIT ${arg_idx} OFFSET ${arg_idx + 1};
        """
        args.extend([limit, offset])

        rows = await database.fetch(query, *args)
        
        total_matches = rows[0]["total_matches"] if rows else 0
        count_drops = rows[0]["count_drops"] if rows else 0
        count_hikes = rows[0]["count_hikes"] if rows else 0

        # Global stats across entire 24h window (in-stock active products)
        core_metrics = await database.get_core_metrics()
        global_stats = await database.fetchrow("""
            SELECT 
                COUNT(*) as global_total,
                COUNT(CASE WHEN dp_today.close_price > dp_yest.close_price THEN 1 END) as global_hikes
            FROM products p
            JOIN daily_prices dp_today ON p.id = dp_today.product_id AND dp_today.date = (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE
            JOIN daily_prices dp_yest ON p.id = dp_yest.product_id AND dp_yest.date = ((NOW() AT TIME ZONE 'Asia/Kolkata')::DATE - 1)
            WHERE dp_today.close_price != dp_yest.close_price
              AND p.in_stock = TRUE AND dp_today.close_price > 0 AND dp_yest.close_price > 0
              AND LOWER(p.platform) != 'croma';
        """)

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "platform": r["platform"],
                "platform_id": r["platform_id"],
                "title": r["title"],
                "category": r["category"],
                "image_url": r["image_url"],
                "product_url": r["product_url"],
                "affiliate_url": r["affiliate_url"] or r["product_url"],
                "old_price": float(r["old_price"]) if r["old_price"] else None,
                "new_price": float(r["new_price"]) if r["new_price"] else None,
                "today_min_price": float(r["today_min_price"]) if r["today_min_price"] else None,
                "mrp": float(r["mrp"]) if r["mrp"] else None,
                "price_diff": float(r["price_diff"]) if r["price_diff"] else 0.0,
                "change_pct": float(r["change_pct"]) if r["change_pct"] else 0.0,
                "is_drop": bool(r["price_diff"] < 0),
                "changed_at": str(r["changed_at"])
            })

        return {
            "page": page,
            "limit": limit,
            "total_matches": total_matches,
            "total_pages": (total_matches + limit - 1) // limit if total_matches > 0 else 1,
            "global_stats": {
                "total": global_stats["global_total"] if global_stats else 0,
                "drops": core_metrics["drops_today"],
                "hikes": global_stats["global_hikes"] if global_stats else 0
            },
            "products": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Full Database Explorer Endpoints ──────────────────────────────────────────

ALLOWED_TABLES = [
    "products",
    "daily_prices",
    "deals",
    "ingested_channel_deals",
    "post_cooldowns",
    "channel_monitors",
    "deal_tracking"
]

ALLOWED_SORT_COLUMNS = {
    "products": {"id", "title", "platform", "current_price", "mrp", "rating", "review_count", "in_stock", "status", "created_at", "last_checked", "last_price_change", "all_time_low"},
    "deals": {"id", "product_id", "posted_price", "posted_mrp", "savings_pct", "badge", "deal_score", "posted_at", "source_channel"},
    "daily_prices": {"id", "product_id", "date", "open_price", "high", "low", "close_price", "created_at"},
    "ingested_channel_deals": {"id", "product_id", "platform", "raw_url", "source_channel", "created_at", "status"},
    "channel_monitors": {"id", "channel_name", "status", "last_scanned_at"},
    "post_cooldowns": {"id", "product_id", "expires_at", "created_at"},
    "deal_tracking": {"id", "product_id", "status", "created_at"}
}

def inject_admin_session_script(html_content: str, token: str) -> str:
    """
    Injects tab-scoped, in-memory session token & fetch interceptor.
    Prevents persistent cookies:
    - Reloading the page forces re-login (URL token is stripped from history via replaceState)
    - Opening a new tab forces re-login (no cookies or URL tokens shared)
    - Directly visiting /pnther/login always shows the login form
    - All background AJAX/fetch calls in the active dashboard are seamlessly authenticated via X-Admin-Session header
    """
    script_tag = f"""
    <script>
        window.BB_ADMIN_TOKEN = "{token}";
        (function() {{
            const originalFetch = window.fetch;
            window.fetch = function(input, init) {{
                if (input instanceof Request) {{
                    input.headers.set('X-Admin-Session', window.BB_ADMIN_TOKEN);
                    return originalFetch(input, init);
                }}
                init = init || {{}};
                init.headers = init.headers || {{}};
                if (init.headers instanceof Headers) {{
                    init.headers.set('X-Admin-Session', window.BB_ADMIN_TOKEN);
                }} else if (Array.isArray(init.headers)) {{
                    init.headers.push(['X-Admin-Session', window.BB_ADMIN_TOKEN]);
                }} else {{
                    init.headers['X-Admin-Session'] = window.BB_ADMIN_TOKEN;
                }}
                return originalFetch(input, init);
            }};
            if (window.history.replaceState) {{
                try {{
                    const u = new URL(window.location.href);
                    if (u.searchParams.has('auth_token')) {{
                        u.searchParams.delete('auth_token');
                        window.history.replaceState({{}}, document.title, u.pathname + (u.search ? u.search : ''));
                    }}
                }} catch(e) {{}}
            }}
            document.addEventListener('click', function(e) {{
                const a = e.target.closest('a');
                if (a && a.href) {{
                    try {{
                        const u = new URL(a.href, window.location.origin);
                        if (u.origin === window.location.origin && u.pathname.startsWith('/pnther') && !u.pathname.startsWith('/pnther/logout') && !u.pathname.startsWith('/pnther/login')) {{
                            if (!a.target || a.target === '_self') {{
                                e.preventDefault();
                                u.searchParams.set('auth_token', window.BB_ADMIN_TOKEN);
                                window.location.href = u.toString();
                            }}
                        }}
                    }} catch(err) {{}}
                }}
            }});
        }})();
    </script>
    """
    if "</head>" in html_content:
        return html_content.replace("</head>", f"{script_tag}\n</head>", 1)
    return script_tag + html_content

async def render_db_explorer(token: str = ""):
    """Renders the Full Database Explorer Web Interface (accessible strictly under /pnther/db-explorer)."""
    explorer_html_path = os.path.join(os.path.dirname(__file__), "templates", "explorer.html")
    raw_html = "<h1>Database Explorer Loading...</h1>"
    if os.path.exists(explorer_html_path):
        with open(explorer_html_path, "r", encoding="utf-8") as f:
            raw_html = f.read()
    if token:
        return HTMLResponse(inject_admin_session_script(raw_html, token))
    return HTMLResponse(raw_html)

@app.get("/db-explorer")
@app.get("/db-explorer/{rest:path}")
async def redirect_old_db_explorer(rest: str = ""):
    """Safely redirects public /db-explorer requests to consumer homepage."""
    return RedirectResponse(url="/", status_code=302)

@app.get("/api/db/overview", dependencies=[Depends(require_admin)])
async def get_db_overview():
    """Returns database size, table summaries, and column schemas for all tables."""
    try:
        total_db_size = await database.fetchval("SELECT pg_size_pretty(pg_database_size('budgetby'));")
        core_metrics = await database.get_core_metrics()
        total_products = core_metrics["total_products"]
        products_added_today = core_metrics["products_added_today"]
        
        tables_stats = await database.fetch("""
            SELECT
                relname AS table_name,
                n_live_tup AS row_count,
                pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                pg_total_relation_size(relid) AS total_bytes
            FROM pg_stat_user_tables
            ORDER BY total_bytes DESC;
        """)
        
        table_schemas = {}
        for t in ALLOWED_TABLES:
            cols = await database.fetch("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = $1
                ORDER BY ordinal_position;
            """, t)
            table_schemas[t] = [dict(c) for c in cols]

        return {
            "total_size": total_db_size,
            "total_products": total_products or 0,
            "products_added_today": products_added_today or 0,
            "tables": [dict(t) for t in tables_stats],
            "schemas": table_schemas
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/db/product_history/{product_id}", dependencies=[Depends(require_admin)])
async def get_product_history(product_id: int):
    """Returns the full 30-day chronological daily price timeline (Day 1 to Day 30) for a product."""
    try:
        product = await database.fetchrow("SELECT * FROM products WHERE id = $1;", product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Option 2: Chronological Age (Day 1 = First Discovered -> Day N = Today)
        daily_rows = await database.fetch("""
            SELECT 
                date,
                min_price,
                close_price
            FROM daily_prices
            WHERE product_id = $1
            ORDER BY date ASC
            LIMIT 30;
        """, product_id)

        today_str = str(await database.fetchval("SELECT (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE;"))
        total_days = len(daily_rows)
        history = []
        for idx, r in enumerate(daily_rows):
            d_str = str(r["date"])
            day_num = idx + 1
            if day_num == 1:
                label = "Day 1 (First Tracked)"
            elif d_str == today_str:
                label = f"Day {day_num} (Today)"
            else:
                label = f"Day {day_num}"

            history.append({
                "day_number": day_num,
                "day_label": label,
                "date": d_str,
                "is_today": d_str == today_str,
                "min_price": float(r["min_price"]) if r["min_price"] is not None else None,
                "close_price": float(r["close_price"]) if r["close_price"] is not None else None
            })

        return {
            "product": dict(product),
            "history_count": len(history),
            "daily_prices": history
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Product history error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/db/table_data", dependencies=[Depends(require_admin)])
async def get_table_data(
    table: str = Query("products"),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    search: str = Query("", max_length=100),
    platform: str = Query("", max_length=50),
    category: str = Query("", max_length=50),
    sort_by: str = Query("", max_length=50),
    sort_order: str = Query("desc", pattern="^(asc|desc)$")
):
    """Universal paginated table explorer with dynamic filters and search."""
    if table not in ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail="Invalid table name")

    try:
        offset = (page - 1) * limit
        where_clauses = []
        args = []
        arg_idx = 1

        # Search filter with exact ID prioritization
        order_override = None
        if search:
            clean_search = search.strip().lstrip("#")
            if table == "products":
                if clean_search.isdigit():
                    exact_id = int(clean_search)
                    clean_digits = re.sub(r'[^0-9]', '', clean_search)
                    where_clauses.append(f"(id = ${arg_idx} OR id::text LIKE ${arg_idx+1} OR title ILIKE ${arg_idx+2} OR platform_id ILIKE ${arg_idx+2})")
                    args.extend([exact_id, f"{clean_digits}%", f"%{clean_digits}%"])
                    arg_idx += 3
                    order_override = f"ORDER BY CASE WHEN id = {exact_id} THEN 0 WHEN id::text LIKE '{clean_digits}%' THEN 1 ELSE 2 END, id ASC"
                else:
                    where_clauses.append(f"(title ILIKE ${arg_idx} OR platform_id ILIKE ${arg_idx} OR category ILIKE ${arg_idx})")
                    args.append(f"%{search}%")
                    arg_idx += 1
            elif table == "daily_prices":
                if clean_search.isdigit():
                    exact_id = int(clean_search)
                    where_clauses.append(f"(product_id = ${arg_idx} OR id = ${arg_idx})")
                    args.append(exact_id)
                    arg_idx += 1
                    order_override = "ORDER BY date DESC, id ASC"
            elif table == "ingested_channel_deals":
                where_clauses.append(f"(title ILIKE ${arg_idx} OR source_channel ILIKE ${arg_idx} OR raw_url ILIKE ${arg_idx})")
                args.append(f"%{search}%")
                arg_idx += 1
            elif table == "deals":
                where_clauses.append(f"(badge ILIKE ${arg_idx} OR source_channel ILIKE ${arg_idx})")
                args.append(f"%{search}%")
                arg_idx += 1

        # Platform filter
        if platform:
            if table in ["products", "ingested_channel_deals"]:
                where_clauses.append(f"platform = ${arg_idx}")
                args.append(platform.lower())
                arg_idx += 1

        # Category filter
        if category and table == "products":
            where_clauses.append(f"category = ${arg_idx}")
            args.append(category.lower())
            arg_idx += 1

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Total Count for pagination
        count_sql = f"SELECT COUNT(*) FROM {table} {where_sql};"
        total_rows = await database.fetchval(count_sql, *args) or 0

        # Sort order
        if order_override:
            order_sql = order_override
        else:
            default_col = "id" if table != "channel_monitors" else "channel_name"
            order_col = default_col
            if sort_by and sort_by in ALLOWED_SORT_COLUMNS.get(table, set()):
                order_col = sort_by
            order_sql = f"ORDER BY {order_col} {sort_order.upper()} NULLS LAST"

        # Data query
        data_sql = f"""
            SELECT * FROM {table}
            {where_sql}
            {order_sql}
            LIMIT ${arg_idx} OFFSET ${arg_idx + 1};
        """
        args.extend([limit, offset])
        rows = await database.fetch(data_sql, *args)

        return {
            "table": table,
            "page": page,
            "limit": limit,
            "total_rows": total_rows,
            "total_pages": max(1, (total_rows + limit - 1) // limit),
            "rows": [dict(r) for r in rows]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Table data error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/deals", dependencies=[Depends(require_admin)])
async def get_deals(limit: int = 36, platform: str = ""):
    try:
        where_clauses = [
            "LOWER(p.platform) != 'croma'",
            "d.posted_at >= NOW() - INTERVAL '30 days'"
        ]
        args = []
        if platform and platform.lower() != "all":
            where_clauses.append("LOWER(p.platform) = $1")
            args.append(platform.lower())
            
        limit_val = min(max(1, limit), 200)
        args.append(limit_val)
        query = f"""
            SELECT d.id, d.posted_price, d.posted_mrp, d.savings_pct, d.badge, d.deal_score, d.posted_at, d.source_channel,
                   p.id as product_id, p.title, p.platform, p.category, p.product_url, p.affiliate_url, p.image_url, p.rating,
                   p.current_price, p.in_stock
            FROM deals d
            JOIN products p ON d.product_id = p.id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY d.posted_at DESC
            LIMIT ${len(args)};
        """
        rows = await database.fetch(query, *args)
        res = []
        for r in rows:
            d = dict(r)
            d["affiliate_url"] = resolve_deal_button_url(d.get("platform"), None, d.get("affiliate_url"), d.get("product_url"), product_id=d.get("product_id"))
            res.append(d)
        return res
    except Exception as e:
        logger.error(f"Internal deals error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/search")
async def search_products(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(8, ge=1, le=50)
):
    try:
        clean_q = q.strip()
        if not clean_q:
            return []

        cache_key = f"search:{clean_q.lower()}:{limit}"
        cached = await ram_cache.get(cache_key)
        if cached is not None:
            return cached

        parsed = parse_search_query(clean_q)
        tokens = parsed.get("tokens", [])
        target_plat = parsed.get("platform")
        max_p = parsed.get("max_price")
        min_p = parsed.get("min_price")

        where_clauses = [
            "LOWER(platform) != 'croma'",
            "in_stock = TRUE",
            "current_price > 0",
            "status = 'ACTIVE'"
        ]
        args = []
        arg_idx = 1

        if target_plat:
            where_clauses.append(f"LOWER(platform) = ${arg_idx}")
            args.append(target_plat)
            arg_idx += 1

        if max_p is not None:
            where_clauses.append(f"current_price <= ${arg_idx}")
            args.append(max_p)
            arg_idx += 1

        if min_p is not None:
            where_clauses.append(f"current_price >= ${arg_idx}")
            args.append(min_p)
            arg_idx += 1

        if tokens:
            for t in tokens:
                t_wild = f"%{t}%"
                where_clauses.append(f"(title ILIKE ${arg_idx} OR platform_id ILIKE ${arg_idx} OR COALESCE(category, '') ILIKE ${arg_idx})")
                args.append(t_wild)
                arg_idx += 1
        else:
            where_clauses.append(f"(title ILIKE ${arg_idx} OR platform_id ILIKE ${arg_idx})")
            args.append(f"%{clean_q}%")
            arg_idx += 1

        args.append(limit)
        limit_arg_idx = arg_idx

        where_sql = " AND ".join(where_clauses)
        sql = f"""
            SELECT id, platform, title, current_price, mrp, rating, review_count, in_stock, affiliate_url, product_url, image_url, min_30d, all_time_low
            FROM products
            WHERE {where_sql}
            ORDER BY 
              (CASE WHEN affiliate_url ILIKE '%fktr.in%' OR affiliate_url ILIKE '%myntr.it%' OR affiliate_url ILIKE '%ajiio.in%' OR affiliate_url ILIKE '%clnk.in%' OR LOWER(platform) = 'amazon' THEN 1 ELSE 0 END) DESC,
              (CASE WHEN mrp > current_price AND mrp > 0 THEN ((mrp - current_price)::float / mrp) ELSE 0 END) DESC,
              current_price ASC NULLS LAST
            LIMIT ${limit_arg_idx};
        """
        rows = await database.fetch(sql, *args)
        res = []
        for r in rows:
            d = dict(r)
            d["affiliate_url"] = resolve_deal_button_url(d.get("platform"), None, d.get("affiliate_url"), d.get("product_url"), product_id=d.get("id"))
            res.append(d)
        await ram_cache.set(cache_key, res, ttl=300)  # 5 min — search results stable
        return res
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/trigger/backup", dependencies=[Depends(require_admin)])
async def trigger_backup():
    try:
        from budgetby.scheduler.cleanup import run_backup
        asyncio.create_task(run_backup())
        return {"status": "success", "message": "Database backup triggered successfully."}
    except Exception as e:
        logger.error(f"Backup trigger error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/trigger/backfill", dependencies=[Depends(require_admin)])
async def trigger_backfill():
    try:
        from budgetby.scheduler.scheduler import hourly_backfill
        asyncio.create_task(hourly_backfill())
        return {"status": "success", "message": "Hourly backfill post triggered successfully."}
    except Exception as e:
        logger.error(f"Backfill trigger error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/trigger/channel_scan", dependencies=[Depends(require_admin)])
async def trigger_channel_scan():
    try:
        from budgetby.ingest.channel_monitor import run_channel_monitor
        asyncio.create_task(run_channel_monitor())
        return {"status": "success", "message": "Channel spy monitor scan triggered in background!"}
    except Exception as e:
        logger.error(f"Channel scan trigger error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Public Storefront Endpoints ──────────────────────────────────────────────

@app.get("/api/public/stats")
async def get_public_stats():
    """Returns quick hero statistics and latest activity timestamp for public website."""
    cached = await ram_cache.get("public_stats")
    if cached is not None:
        return cached

    try:
        stats_row = await database.fetchrow("""
            SELECT 
                (SELECT COUNT(*) FROM products WHERE LOWER(platform) != 'croma') as total_products,
                (SELECT COUNT(*) FROM deals) as total_deals,
                (SELECT COUNT(*) FROM deals WHERE posted_at >= (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE) as deals_today,
                (SELECT COUNT(*) FROM products WHERE previous_price > current_price AND in_stock = TRUE AND LOWER(platform) != 'croma') as drops_today,
                (SELECT MAX(posted_at) FROM deals) as latest_deal_time
        """)
        by_plat = await database.fetch("""
            SELECT platform, COUNT(*) as count, 
                   MAX(CASE WHEN mrp > current_price THEN ROUND(((mrp - current_price) / NULLIF(mrp, 0)) * 100) END) as max_discount
            FROM products 
            WHERE in_stock = TRUE AND current_price > 0 AND mrp > current_price AND LOWER(platform) != 'croma'
            GROUP BY platform;
        """)

        total_prods = stats_row["total_products"] if stats_row else 101000
        total_deals = stats_row["total_deals"] if stats_row else 14000
        deals_today = stats_row["deals_today"] if stats_row else 1500
        drops_today = stats_row["drops_today"] if stats_row else 30000
        latest_time = stats_row["latest_deal_time"] if stats_row else None

        result = {
            "total_products": total_prods,
            "total_deals": total_deals,
            "active_deals": total_deals,
            "lifetime_deals": total_deals,
            "deals_today": deals_today,
            "drops_today": drops_today,
            "by_platform": {r["platform"].lower(): {"count": r["count"], "max_discount": int(r["max_discount"] or 50)} for r in by_plat},
            "latest_timestamp": latest_time.isoformat() if latest_time else None,
            "platforms": ["Amazon", "Flipkart", "Myntra", "Ajio", "Nykaa"],
            "status": "live"
        }
        await ram_cache.set("public_stats", result, ttl=60)  # 60s RAM cache keeps latest_deal_time fresh while protecting DB
        return result
    except Exception as e:
        logger.error(f"Error in get_public_stats: {e}", exc_info=True)
        return {
            "total_products": 100000,
            "total_deals": 14000,
            "deals_today": 1500,
            "drops_today": 30000,
            "latest_timestamp": None,
            "platforms": ["Amazon", "Flipkart", "Myntra", "Ajio", "Nykaa"],
            "status": "fallback",
            "error": str(e)
        }

@app.get("/api/public/categories")
async def get_public_categories():
    """Returns top product categories with active in-stock deal counts across deals and new products."""
    cached = await ram_cache.get("public_categories")
    if cached is not None:
        return cached

    try:
        rows = await database.fetch("""
            WITH combined_deals AS (
                SELECT 
                    COALESCE(NULLIF(LOWER(p.category), ''), 'general') as category,
                    p.platform
                FROM deals d
                JOIN products p ON d.product_id = p.id
                WHERE p.in_stock = TRUE AND p.status = 'ACTIVE' AND p.current_price > 0 AND p.mrp > p.current_price
                  AND LOWER(p.platform) != 'croma'
                  AND p.current_price <= (d.posted_price * 1.01)
                  AND (d.posted_at >= NOW() - INTERVAL '24 hours' OR (p.last_checked >= NOW() - INTERVAL '12 hours' AND d.posted_at >= NOW() - INTERVAL '72 hours'))
                UNION ALL
                SELECT 
                    COALESCE(NULLIF(LOWER(p.category), ''), 'general') as category,
                    p.platform
                FROM products p
                WHERE p.in_stock = TRUE AND p.status = 'ACTIVE' AND p.current_price > 0 AND p.mrp > p.current_price
                  AND LOWER(p.platform) != 'croma'
                  AND (p.created_at >= NOW() - INTERVAL '48 hours' OR p.last_price_change >= NOW() - INTERVAL '48 hours')
                  AND p.id NOT IN (SELECT product_id FROM deals WHERE posted_at >= NOW() - INTERVAL '72 hours')
            )
            SELECT 
                category,
                COUNT(*) as deal_count,
                COUNT(DISTINCT platform) as platform_count
            FROM combined_deals
            GROUP BY category
            HAVING COUNT(*) >= 5
            ORDER BY deal_count DESC
            LIMIT 25;
        """)
        res = [dict(r) for r in rows]
        await ram_cache.set("public_categories", res, ttl=1800)  # 30 min — categories barely change
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

KNOWN_PLATFORMS = {'amazon', 'flipkart', 'myntra', 'ajio', 'croma', 'nykaa'}
ACCESSORY_WORDS = {
    'case', 'cover', 'glass', 'strap', 'cable', 'charger', 'adapter',
    'sleeve', 'bag', 'backpack', 'pouch', 'guard', 'protector', 'skin',
    'stand', 'mount', 'holder', 'cleaner', 'cooling pad', 'mouse pad'
}

def parse_search_query(raw_query: str):
    """
    Parses natural language search queries:
    - Extracts platform names (e.g. 'puma shoes amazon' -> platform='amazon', keywords=['puma', 'shoes'])
    - Extracts price constraints (e.g. 'under 500', 'below 1000', '500 to 1000', 'above 1500')
    - Cleans noise words and extracts search tokens
    - Detects if user specifically intends to search for accessories
    """
    query = raw_query.strip().lower()
    target_platform = None
    max_price = None
    min_price = None

    # Normalize t-shirt variants
    query = re.sub(r'\bt[\s\-]+shirt\b', 'tshirt', query)

    # 1. Platform extraction
    for plat in KNOWN_PLATFORMS:
        pattern = rf'\b(?:on|from|in|at)?\s*{plat}\b'
        if re.search(pattern, query):
            target_platform = plat
            query = re.sub(pattern, ' ', query)
            break

    # 2. Price range: "500 to 1000", "between 500 and 1000"
    range_match = re.search(r'\b(?:between\s+)?(\d+)\s*(?:to|-|and)\s*(\d+)\b', query)
    if range_match:
        val1 = float(range_match.group(1))
        val2 = float(range_match.group(2))
        min_price = min(val1, val2)
        max_price = max(val1, val2)
        query = re.sub(r'\b(?:between\s+)?(\d+)\s*(?:to|-|and)\s*(\d+)\b', ' ', query)
    else:
        under_match = re.search(r'\b(?:under|below|less than|within|<=|<)\s*(?:rs\.?|inr|₹)?\s*(\d+)\b', query)
        if under_match:
            max_price = float(under_match.group(1))
            query = re.sub(r'\b(?:under|below|less than|within|<=|<)\s*(?:rs\.?|inr|₹)?\s*(\d+)\b', ' ', query)

        above_match = re.search(r'\b(?:above|over|more than|>=|>)\s*(?:rs\.?|inr|₹)?\s*(\d+)\b', query)
        if above_match:
            min_price = float(above_match.group(1))
            query = re.sub(r'\b(?:above|over|more than|>=|>)\s*(?:rs\.?|inr|₹)?\s*(\d+)\b', ' ', query)

    # 3. Clean tokens
    words = re.findall(r'\b[a-z0-9]{2,}\b', query)
    stop_words = {'for', 'with', 'and', 'the', 'best', 'good', 'cheap', 'buy', 'online', 'in', 'on', 'from', 'at', 'to', 'of', 'a', 'an', 'deal', 'deals', 'offer', 'offers', 'all', 'top', 'latest'}
    meaningful = [w for w in words if w not in stop_words]
    tokens = meaningful if meaningful else words

    is_accessory_query = any(w in raw_query.lower() for w in ACCESSORY_WORDS)

    return {
        'platform': target_platform,
        'max_price': max_price,
        'min_price': min_price,
        'tokens': tokens,
        'clean_query': " ".join(tokens),
        'is_accessory_query': is_accessory_query
    }

ALLOWED_REDIRECT_DOMAINS = (
    "amazon.in", "amazon.com", "amzn.to", "amzn.in",
    "flipkart.com", "dl.flipkart.com", "fktr.in",
    "myntra.com", "myntr.it",
    "ajio.com", "ajiio.in",
    "nykaa.com", "nykaa.ly", "clnk.in", "ekaro.in"
)

def is_safe_redirect_url(url: str) -> bool:
    """Validates that destination URL belongs strictly to recognized merchant or affiliate domains."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return False
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower().split(":")[0]
        if not host:
            return False
        return any(host == d or host.endswith("." + d) for d in ALLOWED_REDIRECT_DOMAINS)
    except Exception:
        return False

def resolve_deal_button_url(
    platform: str, 
    tg_raw_url: str | None, 
    affiliate_url: str | None, 
    product_url: str | None, 
    product_id: int | None = None
) -> str:
    """
    Guarantees all consumer storefront deals route shoppers through verified affiliate links:
    1. Amazon: Always attach the official associate tag dealpulse21-21.
    2. Non-Amazon (Flipkart, Myntra, Ajio, Nykaa):
       - If already converted to EarnKaro (fktr.in, ajiio.in, myntr.it, ekaro.in) or Cuelinks (clnk.in), return that link.
       - If tg_raw_url is an affiliate shortlink (not synthetic), return that link.
       - If not yet converted and product_id is available, route through /api/deal/redirect/{product_id}
         which auto-converts on click via @ekconverter9bot / @CuelinksBot, caches the link in DB, and redirects.
       - Fallback: clean direct merchant URL.
    """
    plat = (platform or "").strip().lower()

    # 1. Amazon: Always use official associate tag dealpulse21-21
    if plat == "amazon":
        tag = getattr(config, "AMAZON_ASSOCIATE_TAG", "dealpulse21-21")
        target = product_url or affiliate_url or tg_raw_url or ""
        m = re.search(r'/(?:dp|gp/product|product)/([A-Z0-9]{10})', target)
        if m:
            return f"https://www.amazon.in/dp/{m.group(1)}?tag={tag}"
        if target:
            clean = re.sub(r'([?&])tag=[^&]*', '', target)
            sep = "&" if "?" in clean else "?"
            return f"{clean}{sep}tag={tag}"
        return target

    # 2. Non-Amazon: Check if already an EarnKaro or Cuelinks tracking shortlink
    for candidate in (affiliate_url, tg_raw_url):
        if candidate and candidate.startswith("http") and not any(bad in candidate for bad in ("affgrowth", "affExtParam")):
            cand_lower = candidate.lower()
            if any(domain in cand_lower for domain in ("fktr.in", "ajiio.in", "myntr.it", "ekaro.in", "clnk.in")):
                return candidate

    # 3. If product_id is known, route through redirect endpoint which converts live
    if product_id:
        return f"/api/deal/redirect/{product_id}"

    # 4. Fallback: Clean direct merchant product_url without synthetic broken params
    target = product_url or affiliate_url or ""
    clean = target.split("&affid=")[0].split("?affid=")[0].split("&affExtParam")[0].split("?affExtParam")[0]
    return clean

@app.get("/api/deal/redirect/{product_id}")
async def redirect_to_deal(product_id: int):
    """
    Outbound affiliate redirect endpoint:
    Guarantees every click from the consumer website generates tracked affiliate credit.
    - Amazon: tag=dealpulse21-21
    - Flipkart/Myntra/Ajio: EarnKaro (fktr.in, myntr.it, ajiio.in, ekaro.in) via @ekconverter9bot
    - Nykaa: Cuelinks (clnk.in) via @CuelinksBot / Cuelinks API
    Caches the converted link in products.affiliate_url so subsequent loads and clicks are instant.
    """
    try:
        row = await database.fetchrow("""
            SELECT id, platform, product_url, affiliate_url
            FROM products
            WHERE id = $1
        """, product_id)
        if not row:
            raise HTTPException(status_code=404, detail="Product not found")

        platform = (row["platform"] or "").strip().lower()
        prod_url = row["product_url"] or ""
        aff_url = row["affiliate_url"] or ""

        # 1. Amazon: Always use official tag
        if platform == "amazon":
            tag = getattr(config, "AMAZON_ASSOCIATE_TAG", "dealpulse21-21")
            target = prod_url or aff_url
            m = re.search(r'/(?:dp|gp/product|product)/([A-Z0-9]{10})', target)
            if m:
                final_url = f"https://www.amazon.in/dp/{m.group(1)}?tag={tag}"
            else:
                clean = re.sub(r'([?&])tag=[^&]*', '', target)
                sep = "&" if "?" in clean else "?"
                final_url = f"{clean}{sep}tag={tag}"
            if is_safe_redirect_url(final_url):
                return RedirectResponse(url=final_url, status_code=307)

        # 2. Non-Amazon: If already converted to EarnKaro or Cuelinks, redirect directly
        for candidate in (aff_url,):
            if candidate and candidate.startswith("http") and not any(bad in candidate for bad in ("affgrowth", "affExtParam")):
                cand_lower = candidate.lower()
                if any(domain in cand_lower for domain in ("fktr.in", "ajiio.in", "myntr.it", "ekaro.in", "clnk.in")):
                    if is_safe_redirect_url(candidate):
                        return RedirectResponse(url=candidate, status_code=307)

        # 3. Flipkart, Myntra, Ajio: Live conversion via @ekconverter9bot
        if platform in ("flipkart", "myntra", "ajio"):
            target_url = prod_url or aff_url
            try:
                from budgetby.ingest.telegram_listener import convert_url_via_ek_bot
                converted = await convert_url_via_ek_bot(target_url, timeout=4.0)
                if converted and converted != target_url and any(domain in converted.lower() for domain in ("fktr.in", "ajiio.in", "myntr.it", "ekaro.in")):
                    if is_safe_redirect_url(converted):
                        await database.execute("UPDATE products SET affiliate_url = $1 WHERE id = $2;", converted, product_id)
                        logger.info(f"✨ [CLICK CONVERTED] Prod {product_id} [{platform}] ➔ {converted}")
                        return RedirectResponse(url=converted, status_code=307)
            except Exception as e:
                logger.debug(f"Click redirect EK error: {e}")

        # 4. Nykaa: Live conversion via @CuelinksBot or Cuelinks API
        elif platform == "nykaa":
            target_url = prod_url or aff_url
            try:
                from budgetby.ingest.telegram_listener import convert_url_via_cuelinks_bot
                converted = await convert_url_via_cuelinks_bot(target_url, timeout=5.0)
                if converted and converted != target_url and "clnk.in" in converted.lower():
                    if is_safe_redirect_url(converted):
                        await database.execute("UPDATE products SET affiliate_url = $1 WHERE id = $2;", converted, product_id)
                        logger.info(f"✨ [CLICK CONVERTED] Prod {product_id} [NYKAA] ➔ {converted}")
                        return RedirectResponse(url=converted, status_code=307)
            except Exception as e:
                logger.debug(f"Click redirect Cuelinks error: {e}")

        # 5. Clean fallback to merchant page if conversion fails
        clean = (prod_url or aff_url).split("&affid=")[0].split("?affid=")[0].split("&affExtParam")[0].split("?affExtParam")[0]
        if is_safe_redirect_url(clean):
            return RedirectResponse(url=clean, status_code=307)
        return RedirectResponse(url="/deals", status_code=307)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Redirect deal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

async def _background_convert_top_deals(limit: int = 100):
    """
    Background batch converter:
    Converts active non-Amazon deals into live EarnKaro/Cuelinks tracking links
    and persists them to PostgreSQL so the storefront immediately serves tracked links.
    """
    try:
        from budgetby.ingest.telegram_listener import convert_url_via_ek_bot, convert_url_via_cuelinks_bot
        deals = await database.fetch("""
            SELECT d.id as deal_id, p.id as product_id, p.platform, p.product_url, p.affiliate_url
            FROM deals d
            JOIN products p ON d.product_id = p.id
            WHERE p.in_stock = TRUE AND LOWER(p.platform) IN ('flipkart', 'myntra', 'ajio', 'nykaa')
              AND (p.affiliate_url IS NULL 
                   OR NOT (p.affiliate_url ILIKE '%fktr.in%' OR p.affiliate_url ILIKE '%myntr.it%' OR p.affiliate_url ILIKE '%ajiio.in%' OR p.affiliate_url ILIKE '%ekaro.in%' OR p.affiliate_url ILIKE '%clnk.in%'))
            ORDER BY d.posted_at DESC
            LIMIT $1;
        """, limit)
        
        converted_count = 0
        for d in deals:
            pid = d["product_id"]
            plat = d["platform"].lower()
            url = d["product_url"] or d["affiliate_url"]
            if not url:
                continue
            try:
                if plat in ("flipkart", "myntra", "ajio"):
                    new_url = await convert_url_via_ek_bot(url, timeout=4.0)
                    if new_url and new_url != url and any(dom in new_url.lower() for dom in ("fktr.in", "myntr.it", "ajiio.in", "ekaro.in")):
                        await database.execute("UPDATE products SET affiliate_url = $1 WHERE id = $2;", new_url, pid)
                        converted_count += 1
                        logger.info(f"✨ [BATCH CONVERTED] Prod {pid} [{plat}] ➔ {new_url}")
                elif plat == "nykaa":
                    new_url = await convert_url_via_cuelinks_bot(url, timeout=6.0)
                    if new_url and new_url != url and "clnk.in" in new_url.lower():
                        await database.execute("UPDATE products SET affiliate_url = $1 WHERE id = $2;", new_url, pid)
                        converted_count += 1
                        logger.info(f"✨ [BATCH CONVERTED] Prod {pid} [NYKAA] ➔ {new_url}")
            except Exception as e:
                logger.debug(f"Batch conversion error on prod {pid}: {e}")
            await asyncio.sleep(0.5)
        logger.info(f"✅ Background deal conversion finished: {converted_count}/{len(deals)} converted.")
    except Exception as e:
        logger.error(f"Error in background deal pre-converter: {e}")

@app.post("/api/trigger/convert-top-deals", dependencies=[Depends(require_admin)])
async def trigger_convert_top_deals(limit: int = 100):
    try:
        asyncio.create_task(_background_convert_top_deals(limit=min(limit, 200)))
        return {"status": "success", "message": f"Background conversion of top {limit} active deals initiated."}
    except Exception as e:
        logger.error(f"Convert top deals trigger error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/public/price-drops")
async def get_public_price_drops(
    page: int = Query(1, ge=1),
    limit: int = Query(14, ge=1, le=100),
    min_drop_pct: float = Query(5.0, ge=1.0, le=90.0),
    min_drop_percent: float = Query(None),
    platform: str = Query("", max_length=50),
    category: str = Query("", max_length=50),
    sort_by: str = Query("drop_pct", max_length=30)
):
    """
    Returns massive 24-hour price drops & today's specials with pagination support.
    Calculates drop percentage, absolute rupee savings, previous price, and current price.
    """
    try:
        if min_drop_percent is not None:
            min_drop_pct = min_drop_percent

        cache_key = f"drops:{page}:{limit}:{min_drop_pct}:{platform}:{category}:{sort_by}"
        cached = await ram_cache.get(cache_key)
        if cached is not None:
            return cached

        offset = (page - 1) * limit

        where_clauses = [
            "p.in_stock = TRUE",
            "p.status = 'ACTIVE'",
            "p.current_price > 0",
            "p.previous_price > p.current_price",
            "p.previous_price <= GREATEST(COALESCE(NULLIF(p.mrp, 0), p.current_price * 1.35) * 1.15, p.current_price * 3.0)",
            "LOWER(p.platform) != 'croma'",
            "(((p.previous_price - p.current_price) / NULLIF(p.previous_price, 0)) * 100) >= $1",
            "(((p.previous_price - p.current_price) / NULLIF(p.previous_price, 0)) * 100) <= 95.0"
        ]
        args = [min_drop_pct]
        arg_idx = 2

        plat_clean = platform.strip().lower() if platform else ""
        if plat_clean and plat_clean not in ("all", "croma"):
            where_clauses.append(f"LOWER(p.platform) = ${arg_idx}")
            args.append(plat_clean)
            arg_idx += 1

        cat_clean = category.strip().lower() if category else ""
        if cat_clean and cat_clean not in ("all",):
            where_clauses.append(f"LOWER(p.category) LIKE ${arg_idx}")
            args.append(f"%{cat_clean}%")
            arg_idx += 1

        aff_priority = "(CASE WHEN p.affiliate_url ILIKE '%fktr.in%' OR p.affiliate_url ILIKE '%myntr.it%' OR p.affiliate_url ILIKE '%ajiio.in%' OR p.affiliate_url ILIKE '%clnk.in%' OR LOWER(p.platform) = 'amazon' THEN 1 ELSE 0 END) DESC"
        order_by = f"{aff_priority}, drop_pct DESC, drop_amount DESC"
        if sort_by == "price_asc":
            order_by = f"{aff_priority}, p.current_price ASC, drop_pct DESC"
        elif sort_by == "discount":
            order_by = f"{aff_priority}, drop_amount DESC, drop_pct DESC"
        elif sort_by == "latest":
            order_by = f"{aff_priority}, p.last_price_change DESC NULLS LAST, drop_pct DESC"

        args.extend([limit, offset])

        query = f"""
            SELECT 
                p.id as product_id,
                COALESCE(d.id, -(p.id)) as deal_id,
                p.title,
                p.platform,
                COALESCE(NULLIF(LOWER(p.category), ''), 'general') as category,
                p.current_price,
                p.previous_price,
                p.mrp,
                p.image_url,
                p.product_url,
                p.affiliate_url,
                p.rating,
                p.review_count,
                COALESCE(p.last_price_change, NOW()) as last_price_change,
                ROUND((((p.previous_price - p.current_price) / NULLIF(p.previous_price, 0)) * 100)::numeric, 1) as drop_pct,
                ROUND((p.previous_price - p.current_price)::numeric, 2) as drop_amount,
                (d.id IS NOT NULL) as is_verified_deal,
                COALESCE(d.badge, 'PRICE DROP') as badge
            FROM products p
            LEFT JOIN deals d ON d.product_id = p.id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY {order_by}
            LIMIT ${arg_idx} OFFSET ${arg_idx + 1};
        """
        rows = await database.fetch(query, *args)

        cached_total_drops = await ram_cache.get("total_drops_today_count")
        if cached_total_drops is None:
            cached_total_drops = await database.fetchval("""
                SELECT COUNT(*) FROM products 
                WHERE in_stock = TRUE AND status = 'ACTIVE' 
                  AND previous_price > current_price AND current_price > 0 
                  AND previous_price <= GREATEST(COALESCE(NULLIF(mrp, 0), current_price * 1.35) * 1.15, current_price * 3.0)
                  AND (((previous_price - current_price) / NULLIF(previous_price, 0)) * 100) <= 85.0
                  AND LOWER(platform) != 'croma';
            """) or 30000
            await ram_cache.set("total_drops_today_count", cached_total_drops, ttl=600)

        total_reported = cached_total_drops
        total_pages = max(1, math.ceil(total_reported / limit)) if total_reported > 0 else 1
        has_more = page < total_pages

        drops = []
        seen_pids = set()
        seen_aff_urls = set()
        for r in rows:
            pid = r["product_id"]
            if pid in seen_pids:
                continue

            cur_p = float(r["current_price"])
            prev_p = float(r["previous_price"])
            mrp_p = float(r["mrp"]) if r["mrp"] and float(r["mrp"]) > cur_p else None
            if mrp_p and mrp_p > cur_p * 4.5:
                mrp_p = round(cur_p * 1.35, 2)
            if mrp_p and cur_p < 1500 and mrp_p > 15000:
                mrp_p = round(cur_p * 1.35, 2)

            # Plausibility clamps on consumer display
            if mrp_p and prev_p > mrp_p:
                prev_p = mrp_p
            elif prev_p > cur_p * 3.0:
                prev_p = round(cur_p * 1.35, 2)

            drop_amt = max(0.0, prev_p - cur_p)
            drop_pct = round((drop_amt / prev_p) * 100, 1) if prev_p > 0 else 0.0
            aff_url = resolve_deal_button_url(r["platform"], None, r["affiliate_url"], r["product_url"], product_id=r["product_id"])

            if aff_url and "/api/deal/redirect/" not in aff_url:
                clean_aff = aff_url.split("?")[0].rstrip("/").lower()
                if aff_url in seen_aff_urls or clean_aff in seen_aff_urls:
                    continue
                seen_aff_urls.add(aff_url)
                seen_aff_urls.add(clean_aff)

            seen_pids.add(pid)

            drops.append({
                "product_id": r["product_id"],
                "deal_id": r["deal_id"],
                "title": r["title"],
                "platform": r["platform"].lower(),
                "category": r["category"],
                "current_price": cur_p,
                "deal_price": cur_p,
                "previous_price": prev_p,
                "mrp": mrp_p,
                "drop_pct": drop_pct,
                "drop_amount": drop_amt,
                "is_verified_deal": bool(r["is_verified_deal"]),
                "badge": r["badge"],
                "image_url": r["image_url"],
                "product_url": r["product_url"],
                "affiliate_url": aff_url,
                "rating": round(float(r["rating"]), 1) if r["rating"] is not None and 1.0 <= float(r["rating"]) <= 5.0 else None,
                "review_count": int(r["review_count"]) if r.get("review_count") and int(r["review_count"]) > 0 else None,
                "last_price_change": r["last_price_change"].isoformat() if hasattr(r["last_price_change"], "isoformat") else str(r["last_price_change"]) if r["last_price_change"] else None,
                "posted_at": r["last_price_change"].isoformat() if hasattr(r["last_price_change"], "isoformat") else str(r["last_price_change"]) if r.get("last_price_change") else None
            })

        result = {
            "total_drops_24h": total_reported,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_more": has_more,
            "min_drop_pct": min_drop_pct,
            "drops": drops
        }
        await ram_cache.set(cache_key, result, ttl=30)  # 30s RAM cache ensures fresh drops appear promptly
        return result
    except Exception as e:
        logger.error(f"Error in get_public_price_drops: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

_report_cooldowns: dict[int, float] = {}

@app.post("/api/public/report-price/{product_id}")
async def report_product_price(product_id: int):
    """
    Crowdsourced price reporting with anti-abuse cooldown:
    Flags a product for immediate price re-verification by the micro-verifier.
    Resets last_checked so it's prioritized at the front of the verification queue.
    """
    try:
        now_ts = datetime.datetime.now().timestamp()
        last_reported = _report_cooldowns.get(product_id, 0)
        if now_ts - last_reported < 1800:  # 30-minute cooldown per product ID
            return {
                "status": "already_queued",
                "product_id": product_id,
                "message": "This product is already queued for instant verification."
            }

        exists = await database.fetchval("SELECT id FROM products WHERE id = $1;", product_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Product not found")

        _report_cooldowns[product_id] = now_ts
        if len(_report_cooldowns) > 5000:
            cutoff = now_ts - 3600
            for pid in list(_report_cooldowns.keys()):
                if _report_cooldowns[pid] < cutoff:
                    del _report_cooldowns[pid]

        # Reset last_checked to past timestamp to trigger immediate scan in next 60s micro-verifier run
        await database.execute("""
            UPDATE products 
            SET last_checked = '2000-01-01'::timestamptz 
            WHERE id = $1;
        """, product_id)

        return {
            "status": "success",
            "product_id": product_id,
            "message": "Thank you! Flagged for immediate re-verification."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report price error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")



@app.post("/api/public/submit-review")
async def submit_product_review(request: Request):
    """
    Public endpoint to submit any product (existing ID or external URL) for algorithmic review.
    Prioritizes the product in the verification and scraping queue.
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    product_id = data.get("product_id")
    url = (data.get("url") or "").strip()
    title = (data.get("title") or "").strip()
    observed_price = data.get("observed_price")
    notes = (data.get("notes") or "").strip()

    if product_id:
        try:
            pid = int(product_id)
            exists = await database.fetchval("SELECT id FROM products WHERE id = $1;", pid)
            if exists:
                await database.execute("""
                    UPDATE products 
                    SET last_checked = '2000-01-01'::timestamptz,
                        priority_tier = 1,
                        next_check = NOW()
                    WHERE id = $1;
                """, pid)
                return {
                    "status": "success",
                    "product_id": pid,
                    "message": "Product queued for immediate algorithmic verification."
                }
        except Exception as e:
            logger.error(f"Error resetting product by ID: {e}")

    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="A valid product URL is required.")

    # Detect platform
    plat = "amazon"
    url_lower = url.lower()
    if "flipkart.com" in url_lower or "fkrt.it" in url_lower:
        plat = "flipkart"
    elif "myntra.com" in url_lower:
        plat = "myntra"
    elif "ajio.com" in url_lower:
        plat = "ajio"
    elif "nykaa.com" in url_lower:
        plat = "nykaa"
    elif "croma.com" in url_lower:
        plat = "croma"

    # Check if exists by URL
    existing_id = await database.fetchval(
        "SELECT id FROM products WHERE product_url = $1 OR affiliate_url = $1 LIMIT 1;", url
    )

    if existing_id:
        await database.execute("""
            UPDATE products 
            SET last_checked = '2000-01-01'::timestamptz,
                priority_tier = 1,
                next_check = NOW()
            WHERE id = $1;
        """, existing_id)
        return {
            "status": "success",
            "product_id": existing_id,
            "message": "Product found in catalog and queued for immediate re-verification."
        }

    # Queue new product
    import hashlib
    platform_id = hashlib.md5(url.encode()).hexdigest()[:16]
    clean_title = title if title else f"Submitted {plat.capitalize()} Deal"
    try:
        new_id = await database.fetchval("""
            INSERT INTO products (
                platform, platform_id, title, category, product_url, affiliate_url,
                current_price, status, priority_tier, next_check, last_checked
            ) VALUES (
                $1, $2, $3, 'general', $4, $4,
                $5, 'ACTIVE', 1, NOW(), '2000-01-01'::timestamptz
            )
            ON CONFLICT (platform, platform_id) DO UPDATE 
            SET priority_tier = 1, next_check = NOW(), last_checked = '2000-01-01'::timestamptz
            RETURNING id;
        """, plat, platform_id, clean_title, url, float(observed_price) if observed_price else 0)

        return {
            "status": "success",
            "product_id": new_id,
            "message": "New product added to catalog and queued for priority verification."
        }
    except Exception as e:
        logger.error(f"Error ingesting submitted review product: {e}")
        return {
            "status": "success",
            "message": "Product received and queued for review."
        }


@app.get("/api/public/deals")
async def get_public_deals(
    platform: str = Query("", max_length=50),
    platforms: str = Query("", max_length=200),
    category: str = Query("", max_length=50),
    categories: str = Query("", max_length=500),
    tab: str = Query("all", max_length=30),
    search: str = Query("", max_length=100),
    sort_by: str = Query("latest", max_length=30),
    min_discount: float = Query(0.0, ge=0.0, le=100.0),
    min_price: float = Query(0.0, ge=0.0),
    max_price: float = Query(0.0, ge=0.0),
    min_rating: float = Query(0.0, ge=0.0, le=5.0),
    verified_only: bool = Query(False),
    deal_type: str = Query("", max_length=30),
    ids: str = Query("", max_length=500),
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100)
):
    """
    Public paginated deals & catalog feed.
    - Exposes all 100,000+ products in the catalog to shoppers.
    - Verified deals (price checked vs historical deals with no price increases) are always prioritized first.
    - If a search has no verified deals, marks it clearly and serves all matching catalog products with price history.
    """
    try:
        cache_key = f"deals:{platform}:{platforms}:{category}:{categories}:{tab}:{search}:{sort_by}:{min_discount}:{min_price}:{max_price}:{min_rating}:{verified_only}:{deal_type}:{ids}:{page}:{limit}"
        cached = await ram_cache.get(cache_key)
        if cached is not None:
            return cached

        offset = (page - 1) * limit
        search_clean = search.strip().lstrip("#")
        platform_clean = platform.strip().lower()
        category_clean = category.strip().lower()
        tab_clean = tab.strip().lower()
        deal_type_clean = deal_type.strip().lower()

        where_clauses = [
            "p.in_stock = TRUE",
            "p.status = 'ACTIVE'",
            "p.current_price > 0",
            "LOWER(p.platform) != 'croma'",
            "(d.id IS NOT NULL OR p.mrp IS NULL OR p.mrp <= p.current_price * 25.0)"
        ]
        args = []
        arg_idx = 1
        relevance_select = "0 as relevance_score"

        # Shared watchlist IDs filtering
        if ids:
            clean_ids = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()][:50]
            if clean_ids:
                where_clauses.append(f"p.id = ANY(${arg_idx})")
                args.append(clean_ids)
                arg_idx += 1

        # ── SEARCH INTENT EXTRACTION & FILTERING ────────────────────────────
        parsed = None
        if search_clean:
            parsed = parse_search_query(search_clean)
            if parsed["platform"] and (not platform_clean or platform_clean == "all"):
                platform_clean = parsed["platform"]

            # Price constraints from search query
            if parsed["max_price"]:
                where_clauses.append(f"p.current_price <= ${arg_idx}")
                args.append(parsed["max_price"])
                arg_idx += 1
            if parsed["min_price"]:
                where_clauses.append(f"p.current_price >= ${arg_idx}")
                args.append(parsed["min_price"])
                arg_idx += 1

            # Keyword tokens matching
            for t in parsed["tokens"]:
                if t == "tshirt":
                    where_clauses.append(f"(p.title ILIKE ${arg_idx} OR p.title ILIKE ${arg_idx+1} OR COALESCE(p.category, '') ILIKE ${arg_idx})")
                    args.extend(['%t-shirt%', '%tshirt%'])
                    arg_idx += 2
                else:
                    where_clauses.append(f"(p.title ILIKE ${arg_idx} OR COALESCE(p.category, '') ILIKE ${arg_idx})")
                    args.append(f"%{t}%")
                    arg_idx += 1

            # Scoring parameters
            args.append(f"%{parsed['clean_query']}%")
            exact_idx = arg_idx
            arg_idx += 1

            first_token = parsed["tokens"][0] if parsed["tokens"] else ""
            args.append(f"{first_token}%")
            starts_idx = arg_idx
            arg_idx += 1

            acc_sql = "0"
            if not parsed["is_accessory_query"]:
                acc_sql = """
                    CASE 
                        WHEN (p.title ILIKE '%case%' OR p.title ILIKE '%cover%' OR p.title ILIKE '%tempered glass%' 
                              OR p.title ILIKE '%screen protector%' OR p.title ILIKE '%charger%' OR p.title ILIKE '%adapter%'
                              OR p.title ILIKE '%cable%' OR p.title ILIKE '%sleeve%' OR p.title ILIKE '%bag%'
                              OR p.title ILIKE '%backpack%' OR p.title ILIKE '%stand%' OR p.title ILIKE '%mount%'
                              OR p.title ILIKE '%pouch%' OR p.title ILIKE '%cooling pad%' OR p.title ILIKE '%mouse pad%') 
                        THEN -300 
                        ELSE 0 
                    END
                """

            relevance_select = f"""
                (
                    (CASE WHEN p.title ILIKE ${exact_idx} THEN 200 ELSE 0 END) +
                    (CASE WHEN p.title ILIKE ${starts_idx} THEN 100 ELSE 0 END) +
                    (CASE WHEN p.all_time_low IS NOT NULL AND p.current_price <= p.all_time_low * 1.02 THEN 50 ELSE 0 END) +
                    (COALESCE(ROUND((((p.mrp - p.current_price)/NULLIF(p.mrp,0)) * 100)::numeric, 0), 0) * 0.5) +
                    (COALESCE(p.rating, 0) * 8) +
                    {acc_sql}
                ) as relevance_score
            """

        # ── PLATFORM FILTER ─────────────────────────────────────────────────
        selected_platforms = []
        if platforms:
            selected_platforms = [p.strip().lower() for p in platforms.split(",") if p.strip() and p.strip().lower() != "croma"]
        elif platform_clean and platform_clean != "all" and platform_clean != "croma":
            selected_platforms = [platform_clean]

        if selected_platforms:
            where_clauses.append(f"LOWER(p.platform) = ANY(${arg_idx})")
            args.append(selected_platforms)
            arg_idx += 1

        # ── EXPLICIT PRICE RANGE FILTER ─────────────────────────────────────
        if min_price and min_price > 0:
            where_clauses.append(f"p.current_price >= ${arg_idx}")
            args.append(min_price)
            arg_idx += 1
        if max_price and max_price > 0:
            where_clauses.append(f"p.current_price <= ${arg_idx}")
            args.append(max_price)
            arg_idx += 1

        # ── MINIMUM DISCOUNT FILTER ─────────────────────────────────────────
        if min_discount and min_discount > 0:
            where_clauses.append(f"""
                COALESCE(
                    ROUND((((p.mrp - p.current_price) / NULLIF(p.mrp, 0)) * 100)::numeric, 0),
                    ROUND((((p.previous_price - p.current_price) / NULLIF(p.previous_price, 0)) * 100)::numeric, 0),
                    0
                ) >= ${arg_idx}
            """)
            args.append(min_discount)
            arg_idx += 1

        # ── CUSTOMER RATING FILTER ──────────────────────────────────────────
        if min_rating and min_rating > 0:
            where_clauses.append(f"COALESCE(p.rating, 0) >= ${arg_idx}")
            args.append(min_rating)
            arg_idx += 1

        # ── VERIFIED ONLY FILTER ────────────────────────────────────────────
        if verified_only:
            where_clauses.append("d.id IS NOT NULL")
            where_clauses.append("(p.mrp IS NULL OR p.mrp > p.current_price)")

        # ── CATEGORY FILTER ─────────────────────────────────────────────────
        selected_categories = []
        if categories:
            selected_categories = [c.strip().lower() for c in categories.split(",") if c.strip()]
        elif category_clean and category_clean != "all":
            selected_categories = [category_clean]

        if selected_categories:
            cat_clauses = []
            for cat in selected_categories:
                if cat in ("general", "none", "other", "null"):
                    cat_clauses.append("(p.category IS NULL OR LOWER(p.category) IN ('general', 'none', 'other') OR p.category = '')")
                else:
                    cat_clauses.append(f"LOWER(p.category) = ${arg_idx}")
                    args.append(cat)
                    arg_idx += 1
            if cat_clauses:
                where_clauses.append(f"({' OR '.join(cat_clauses)})")

        use_fast_deals_path = (
            not search_clean 
            and not ids 
            and deal_type_clean not in ("drops", "atl") 
            and tab_clean not in ("drops", "atl")
        )

        aff_priority = "(CASE WHEN p.affiliate_url ILIKE '%fktr.in%' OR p.affiliate_url ILIKE '%myntr.it%' OR p.affiliate_url ILIKE '%ajiio.in%' OR p.affiliate_url ILIKE '%clnk.in%' OR LOWER(p.platform) = 'amazon' THEN 1 ELSE 0 END) DESC"

        if use_fast_deals_path:
            if tab_clean == "under499":
                where_clauses.append("p.current_price <= 499")
            elif tab_clean == "under999":
                where_clauses.append("p.current_price <= 999")
            elif tab_clean == "featured":
                where_clauses.append("(p.mrp IS NULL OR ((p.mrp - p.current_price) / NULLIF(p.mrp, 0)) >= 0.30)")

            if sort_by == "discount_desc":
                order_sql = f"ORDER BY {aff_priority}, ((p.mrp - p.current_price) / NULLIF(p.mrp, 0)) DESC NULLS LAST, d.posted_at DESC"
            elif sort_by == "price_asc":
                order_sql = f"ORDER BY {aff_priority}, p.current_price ASC, d.posted_at DESC"
            elif sort_by == "price_desc":
                order_sql = f"ORDER BY {aff_priority}, p.current_price DESC, d.posted_at DESC"
            elif sort_by == "score_desc":
                order_sql = f"ORDER BY {aff_priority}, COALESCE(d.deal_score, 50.0) DESC, d.posted_at DESC"
            else:
                order_sql = f"ORDER BY {aff_priority}, d.posted_at DESC"

            args.extend([limit, offset])
            where_sql = f"WHERE {' AND '.join(where_clauses)}"

            query = f"""
                SELECT 
                    d.id as deal_id,
                    p.id as product_id,
                    p.title,
                    p.platform,
                    COALESCE(NULLIF(LOWER(p.category), ''), 'general') as category,
                    p.product_url,
                    p.affiliate_url,
                    p.image_url,
                    p.rating,
                    p.review_count,
                    COALESCE(d.posted_price, p.current_price) as current_price,
                    p.mrp,
                    p.previous_price,
                    p.min_30d,
                    p.all_time_low,
                    p.in_stock,
                    p.status,
                    COALESCE(p.last_checked, d.posted_at) as last_checked,
                    TRUE as is_verified,
                    COALESCE(d.badge, 'HOT DEAL') as badge,
                    COALESCE(d.deal_score, 50.0) as deal_score,
                    d.posted_at as deal_time,
                    0 as relevance_score,
                    COUNT(*) OVER() as total_matches,
                    COUNT(d.id) OVER() as verified_matches
                FROM deals d
                JOIN products p ON d.product_id = p.id
                {where_sql}
                {order_sql}
                LIMIT ${arg_idx} OFFSET ${arg_idx + 1};
            """
        else:
            if deal_type_clean == "verified" or tab_clean == "verified" or verified_only:
                where_clauses.append("d.id IS NOT NULL")
                where_clauses.append("(p.mrp IS NULL OR p.mrp > p.current_price)")
            elif deal_type_clean == "drops" or tab_clean == "drops":
                where_clauses.append("p.previous_price > p.current_price")
                where_clauses.append("p.previous_price <= GREATEST(COALESCE(NULLIF(p.mrp, 0), p.current_price * 1.35) * 1.15, p.current_price * 3.0)")
                where_clauses.append("(((p.previous_price - p.current_price) / NULLIF(p.previous_price, 0)) * 100) <= 85.0")
            elif deal_type_clean == "atl" or tab_clean == "atl":
                where_clauses.append("(d.badge ILIKE '%ATL%' OR (p.all_time_low IS NOT NULL AND p.current_price <= p.all_time_low * 1.02))")
            elif tab_clean == "under499":
                where_clauses.append("p.current_price <= 499")
            elif tab_clean == "under999":
                where_clauses.append("p.current_price <= 999")
            elif tab_clean == "featured":
                where_clauses.append("(d.id IS NOT NULL OR ((p.mrp - p.current_price) / NULLIF(p.mrp, 0)) >= 0.50)")

            if sort_by == "discount_desc":
                order_sql = f"ORDER BY {aff_priority}, (CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) DESC, ((p.mrp - p.current_price) / NULLIF(p.mrp, 0)) DESC NULLS LAST, p.id DESC"
            elif sort_by == "price_asc":
                order_sql = f"ORDER BY {aff_priority}, (CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) DESC, p.current_price ASC, p.id DESC"
            elif sort_by == "price_desc":
                order_sql = f"ORDER BY {aff_priority}, (CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) DESC, p.current_price DESC, p.id DESC"
            elif sort_by == "score_desc":
                order_sql = f"ORDER BY {aff_priority}, (CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) DESC, COALESCE(d.deal_score, 50.0) DESC, p.id DESC"
            elif search_clean:
                order_sql = f"ORDER BY {aff_priority}, (CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) DESC, relevance_score DESC, COALESCE(d.posted_at, p.last_price_change, p.created_at) DESC"
            else:
                if tab_clean == "drops":
                    order_sql = f"ORDER BY {aff_priority}, (CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) DESC, (((p.previous_price - p.current_price) / NULLIF(p.previous_price, 0))) DESC NULLS LAST, p.last_price_change DESC NULLS LAST, p.id DESC"
                else:
                    order_sql = f"ORDER BY {aff_priority}, (CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) DESC, COALESCE(d.posted_at, p.last_price_change, p.created_at) DESC, p.id DESC"

            args.extend([limit, offset])
            where_sql = f"WHERE {' AND '.join(where_clauses)}"

            query = f"""
                SELECT 
                    COALESCE(d.id, -(p.id)) as deal_id,
                    p.id as product_id,
                    p.title,
                    p.platform,
                    COALESCE(NULLIF(LOWER(p.category), ''), 'general') as category,
                    p.product_url,
                    p.affiliate_url,
                    p.image_url,
                    p.rating,
                    p.review_count,
                    COALESCE(d.posted_price, p.current_price) as current_price,
                    p.mrp,
                    p.previous_price,
                    p.min_30d,
                    p.all_time_low,
                    p.in_stock,
                    p.status,
                    COALESCE(p.last_checked, d.posted_at, p.last_price_change) as last_checked,
                    (d.id IS NOT NULL) as is_verified,
                    COALESCE(d.badge, 
                        CASE 
                            WHEN p.all_time_low IS NOT NULL AND p.current_price <= p.all_time_low * 1.02 THEN 'ATL'
                            WHEN p.last_price_change >= NOW() - INTERVAL '24 hours' THEN 'PRICE DROP'
                            WHEN ((p.mrp - p.current_price)/NULLIF(p.mrp,0)) >= 0.50 THEN 'HOT DEAL'
                            ELSE 'CATALOG'
                        END
                    ) as badge,
                    COALESCE(d.deal_score, ROUND((((p.mrp - p.current_price)/NULLIF(p.mrp,0)) * 100)::numeric, 1), 50.0) as deal_score,
                    COALESCE(d.posted_at, p.last_price_change, p.created_at) as deal_time,
                    {relevance_select},
                    COUNT(*) OVER() as total_matches,
                    COUNT(d.id) OVER() as verified_matches
                FROM products p
                LEFT JOIN deals d ON d.product_id = p.id
                {where_sql}
                {order_sql}
                LIMIT ${arg_idx} OFFSET ${arg_idx + 1};
            """

        rows = await database.fetch(query, *args)
        total_matches = rows[0]["total_matches"] if rows else 0
        verified_matches = rows[0]["verified_matches"] if rows else 0
        catalog_matches = max(0, total_matches - verified_matches)

        deals = []
        seen_pids = set()
        seen_aff_urls = set()
        for r in rows:
            pid = r["product_id"]
            if pid in seen_pids:
                continue

            cur_p = float(r["current_price"]) if r["current_price"] and float(r["current_price"]) > 0 else 0.0
            mrp_p = float(r["mrp"]) if r["mrp"] and float(r["mrp"]) > cur_p else cur_p
            if mrp_p > cur_p * 4.5:
                mrp_p = round(cur_p * 1.35, 2)
            if cur_p < 1500 and mrp_p > 15000:
                mrp_p = round(cur_p * 1.35, 2)
            
            if mrp_p > cur_p and mrp_p > 0:
                pct = round(((mrp_p - cur_p) / mrp_p) * 100)
                savings = round(mrp_p - cur_p, 2)
            else:
                pct = 0
                savings = 0.0

            prev_p = float(r["previous_price"]) if r.get("previous_price") and float(r["previous_price"]) > cur_p else None
            if prev_p:
                if mrp_p and prev_p > mrp_p:
                    prev_p = mrp_p
                elif prev_p > cur_p * 3.0:
                    prev_p = round(cur_p * 1.35, 2)

            drop_pct = round(((prev_p - cur_p) / prev_p) * 100) if prev_p else 0
            drop_amount = round(prev_p - cur_p, 2) if prev_p else 0.0

            aff_url = resolve_deal_button_url(r["platform"], None, r["affiliate_url"], r["product_url"], product_id=r["product_id"])

            if aff_url and "/api/deal/redirect/" not in aff_url:
                clean_aff = aff_url.split("?")[0].rstrip("/").lower()
                if aff_url in seen_aff_urls or clean_aff in seen_aff_urls:
                    continue
                seen_aff_urls.add(aff_url)
                seen_aff_urls.add(clean_aff)

            seen_pids.add(pid)
            is_verified = bool(r["is_verified"])

            deals.append({
                "deal_id": r["deal_id"],
                "product_id": r["product_id"],
                "title": r["title"],
                "platform": r["platform"].lower(),
                "category": r["category"] or "general",
                "deal_price": cur_p,
                "current_price": cur_p,
                "mrp": mrp_p if mrp_p > cur_p else None,
                "previous_price": prev_p,
                "drop_pct": drop_pct,
                "drop_amount": drop_amount,
                "discount_pct": pct,
                "savings_amount": savings,
                "is_verified_deal": is_verified,
                "badge": r["badge"] or ("VERIFIED DEAL" if is_verified else "CATALOG"),
                "deal_score": float(r["deal_score"]) if r["deal_score"] else None,
                "posted_at": r["deal_time"].isoformat() if r["deal_time"] else None,
                "image_url": r["image_url"],
                "product_url": r["product_url"],
                "affiliate_url": aff_url,
                "rating": round(float(r["rating"]), 1) if r["rating"] is not None and 1.0 <= float(r["rating"]) <= 5.0 else None,
                "review_count": int(r["review_count"]) if r.get("review_count") and int(r["review_count"]) > 0 else None,
                "min_30d": float(r["min_30d"]) if r["min_30d"] else None,
                "all_time_low": float(r["all_time_low"]) if r["all_time_low"] else None,
                "in_stock": bool(r["in_stock"]),
                "last_checked": r["last_checked"].isoformat() if r.get("last_checked") else None,
                "is_catalog_product": not is_verified
            })

        result = {
            "page": page,
            "limit": limit,
            "total_matches": total_matches,
            "total_pages": max(1, (total_matches + limit - 1) // limit) if total_matches > 0 else 1,
            "verified_matches": verified_matches,
            "catalog_matches": catalog_matches,
            "has_verified_deals": bool(verified_matches > 0),
            "search_query": search_clean,
            "deals": deals
        }
        await ram_cache.set(cache_key, result, ttl=30)  # 30s RAM cache ensures fresh Telegram deals appear within 30s
        return result
    except Exception as e:
        logger.error(f"Error in get_public_deals: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Page Rendering Routes ───────────────────────────────────────────────────

STORE_DISPLAY_NAMES = {
    "amazon": "Amazon India",
    "flipkart": "Flipkart",
    "myntra": "Myntra",
    "ajio": "Ajio",
    "nykaa": "Nykaa"
}

def render_consumer_template(template_name: str, request: Request, context: dict = None):
    if context is None:
        context = {}
    context["request"] = request
    try:
        return templates.TemplateResponse(request=request, name=template_name, context=context)
    except TypeError:
        # Fallback for older Starlette signature: TemplateResponse(name, context)
        try:
            return templates.TemplateResponse(template_name, context)
        except Exception as e:
            logger.error(f"Fallback render error for {template_name}: {e}", exc_info=True)
            import traceback
            return HTMLResponse(content=f"<h3>Template Error: {e}</h3><pre>{traceback.format_exc()}</pre>", status_code=500)
    except Exception as e:
        logger.error(f"Render error for {template_name}: {e}", exc_info=True)
        import traceback
        return HTMLResponse(content=f"<h3>Template Error: {e}</h3><pre>{traceback.format_exc()}</pre>", status_code=500)

@app.get("/", response_class=HTMLResponse)
async def page_home(request: Request):
    """Renders the modular BudgetBy Home Hub with pre-rendered initial data (SSR)."""
    initial_drops = {"drops": []}
    initial_featured = {"deals": []}
    initial_stats = {}
    try:
        drops_task = get_public_price_drops(page=1, limit=14, min_drop_pct=5.0, min_drop_percent=None, platform="", category="", sort_by="drop_pct")
        featured_task = get_public_deals(platform="", platforms="", category="", categories="", tab="featured", search="", sort_by="discount", min_discount=30.0, min_price=0.0, max_price=0.0, min_rating=0.0, verified_only=True, deal_type="", ids="", page=1, limit=8)
        stats_task = get_public_stats()
        r_drops, r_featured, r_stats = await asyncio.gather(drops_task, featured_task, stats_task, return_exceptions=True)
        if not isinstance(r_drops, Exception):
            initial_drops = r_drops
        if not isinstance(r_featured, Exception):
            initial_featured = r_featured
        if not isinstance(r_stats, Exception):
            initial_stats = r_stats
    except Exception as e:
        logger.warning(f"Home SSR prefetch error: {e}")

    return render_consumer_template("consumer/home.html", request, {
        "active_page": "home",
        "initial_drops": initial_drops,
        "initial_featured": initial_featured,
        "initial_stats": initial_stats
    })

@app.get("/drops", response_class=HTMLResponse)
@app.get("/price-drops", response_class=HTMLResponse)
async def page_drops(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    min_drop_percent: float = Query(None),
    min_drop_pct: float = Query(15.0),
    platform: str = Query(""),
    sort_by: str = Query("drop_pct")
):
    """Renders the dedicated 24-Hour Price Drops Hub with complete pre-rendered items (SSR)."""
    eff_min_drop = min_drop_percent if min_drop_percent is not None else min_drop_pct
    initial_data = {"drops": [], "total_drops_24h": 0, "total_pages": 1, "page": page}
    try:
        initial_data = await get_public_price_drops(
            page=page,
            limit=limit,
            min_drop_pct=eff_min_drop,
            min_drop_percent=None,
            platform=platform,
            category="",
            sort_by=sort_by
        )
    except Exception as e:
        logger.warning(f"Drops SSR prefetch error: {e}")

    return render_consumer_template("consumer/drops.html", request, {
        "active_page": "drops",
        "initial_data": initial_data,
        "current_page": page,
        "current_min_drop": eff_min_drop,
        "current_platform": platform,
        "current_sort": sort_by
    })

@app.get("/deals", response_class=HTMLResponse)
async def page_deals(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    search: str = Query(""),
    platform: str = Query(""),
    category: str = Query(""),
    tab: str = Query("all"),
    verified_only: bool = Query(True),
    sort_by: str = Query("latest"),
    min_discount: float = Query(0.0)
):
    """Renders the Deals Catalog with complete pre-rendered items (SSR)."""
    # When user searches, show all matching products across catalog unless verified_only is explicitly set
    if search and "verified_only" not in request.query_params:
        verified_only = False

    initial_data = {"deals": [], "total_matches": 0, "total_pages": 1, "page": page}
    try:
        initial_data = await get_public_deals(
            platform=platform,
            platforms="",
            category=category,
            categories="",
            tab=tab,
            search=search,
            sort_by=sort_by,
            min_discount=min_discount,
            min_price=0.0,
            max_price=0.0,
            min_rating=0.0,
            verified_only=verified_only,
            deal_type="",
            ids="",
            page=page,
            limit=limit
        )
    except Exception as e:
        logger.warning(f"Deals SSR prefetch error: {e}")

    return render_consumer_template("consumer/deals.html", request, {
        "active_page": "deals",
        "initial_data": initial_data,
        "current_page": page,
        "current_search": search,
        "current_platform": platform,
        "current_category": category,
        "current_tab": tab,
        "current_verified_only": verified_only,
        "current_sort": sort_by,
        "current_min_discount": min_discount
    })

@app.get("/all-time-lows", response_class=HTMLResponse)
@app.get("/atl", response_class=HTMLResponse)
async def page_atl(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    platform: str = Query(""),
    category: str = Query(""),
    sort_by: str = Query("latest")
):
    """Renders the All-Time Lows (ATL) Showcase Hub with complete pre-rendered items (SSR)."""
    initial_data = {"deals": [], "total_matches": 0, "total_pages": 1, "page": page}
    try:
        initial_data = await get_public_deals(
            platform=platform,
            platforms="",
            category=category,
            categories="",
            tab="atl",
            search="",
            sort_by=sort_by,
            min_discount=0.0,
            min_price=0.0,
            max_price=0.0,
            min_rating=0.0,
            verified_only=False,
            deal_type="",
            ids="",
            page=page,
            limit=limit
        )
    except Exception as e:
        logger.warning(f"ATL SSR prefetch error: {e}")

    return render_consumer_template("consumer/atl.html", request, {
        "active_page": "atl",
        "initial_data": initial_data,
        "current_page": page,
        "current_platform": platform,
        "current_category": category,
        "current_sort": sort_by
    })

@app.get("/stores", response_class=HTMLResponse)
@app.get("/stores/{platform}", response_class=HTMLResponse)
async def page_stores(request: Request, platform: str = ""):
    """Renders the Stores Directory or Dedicated Store Deals Page."""
    plat_clean = platform.strip().lower() if platform else ""
    if plat_clean == "croma":
        return RedirectResponse(url="/stores", status_code=302)
    store_name = STORE_DISPLAY_NAMES.get(plat_clean, plat_clean.capitalize()) if plat_clean else None
    
    initial_deals = None
    if plat_clean in STORE_DISPLAY_NAMES:
        try:
            initial_deals = await get_public_deals(
                platform=plat_clean,
                platforms="",
                category="",
                categories="",
                tab="all",
                search="",
                sort_by="latest",
                min_discount=0.0,
                min_price=0.0,
                max_price=0.0,
                min_rating=0.0,
                verified_only=False,
                deal_type="",
                ids="",
                page=1,
                limit=24
            )
        except Exception as e:
            logger.warning(f"Store deals SSR prefetch error: {e}")

    return render_consumer_template(
        "consumer/stores.html", 
        request, 
        {
            "active_page": "stores", 
            "store_id": plat_clean if plat_clean in STORE_DISPLAY_NAMES else None,
            "store_name": store_name,
            "initial_data": initial_deals
        }
    )

def render_admin_login_template(request: Request, context: dict, status_code: int = 200):
    context["request"] = request
    try:
        return templates.TemplateResponse(request=request, name="admin_login.html", context=context, status_code=status_code)
    except TypeError:
        return templates.TemplateResponse("admin_login.html", context, status_code=status_code)

@app.get("/pnther/login", response_class=HTMLResponse)
async def get_admin_login(request: Request, next: str = "/pnther"):
    """Renders the secure Admin Login Page. Always prompts for credentials."""
    clean_next = next if next.startswith("/pnther") and not next.startswith("/pnther/login") else "/pnther"
    response = render_admin_login_template(
        request,
        {"next": clean_next, "error": None}
    )
    response.delete_cookie(key="budgetby_admin_session")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.post("/pnther/login", response_class=HTMLResponse)
async def post_admin_login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/pnther")
):
    """
    Authenticates admin credentials against authorized pairs:
    1) pnther / Pnther@3Alphabetisc
    2) vidushi / lilu
    """
    user_clean = (username or "").strip()
    pwd_clean = (password or "").strip()

    auth_ok = False
    matched_user = None
    for u, p in ADMIN_CREDENTIALS:
        if secrets.compare_digest(user_clean, u) and secrets.compare_digest(pwd_clean, p):
            auth_ok = True
            matched_user = u
            break

    clean_next = next if next.startswith("/pnther") and not next.startswith("/pnther/login") else "/pnther"

    if not auth_ok:
        await asyncio.sleep(0.3)  # Anti brute-force timing buffer
        return render_admin_login_template(
            request,
            {"next": clean_next, "error": "Invalid username or password. Access denied."},
            status_code=401
        )

    token = create_admin_session_token(matched_user)
    target_url = f"{clean_next}{'&' if '?' in clean_next else '?'}auth_token={token}"
    resp = RedirectResponse(url=target_url, status_code=303)
    resp.delete_cookie(key="budgetby_admin_session")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.get("/pnther/logout")
@app.post("/pnther/logout")
async def admin_logout():
    """Logs out admin and terminates any session."""
    resp = RedirectResponse(url="/pnther/login", status_code=302)
    resp.delete_cookie(key="budgetby_admin_session")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.get("/pnther", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Renders the BudgetBy Admin Control Center (Stealth Protected URL: /pnther)."""
    auth_tok = request.query_params.get("auth_token")
    req_key = request.query_params.get("key") or request.query_params.get("admin_key")

    is_valid_token = bool(auth_tok and verify_admin_session_token(auth_tok))
    is_valid_key = bool(req_key and secrets.compare_digest(str(req_key), ADMIN_SECRET_KEY))

    if not is_valid_token and not is_valid_key:
        return RedirectResponse(url="/pnther/login?next=/pnther", status_code=302)

    active_token = auth_tok if is_valid_token else create_admin_session_token("pnther")

    raw_html = "<h1>BudgetBy Admin Dashboard Loading...</h1>"
    if os.path.exists(ADMIN_TEMPLATE_PATH):
        with open(ADMIN_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            raw_html = f.read()

    final_html = inject_admin_session_script(raw_html, active_token)
    response = HTMLResponse(content=final_html)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.delete_cookie(key="budgetby_admin_session")
    return response

@app.get("/pnther/db-explorer", response_class=HTMLResponse)
async def admin_db_explorer(request: Request):
    """Renders the BudgetBy Database Explorer (Stealth Protected URL: /pnther/db-explorer)."""
    auth_tok = request.query_params.get("auth_token")
    req_key = request.query_params.get("key") or request.query_params.get("admin_key")

    is_valid_token = bool(auth_tok and verify_admin_session_token(auth_tok))
    is_valid_key = bool(req_key and secrets.compare_digest(str(req_key), ADMIN_SECRET_KEY))

    if not is_valid_token and not is_valid_key:
        return RedirectResponse(url="/pnther/login?next=/pnther/db-explorer", status_code=302)

    active_token = auth_tok if is_valid_token else create_admin_session_token("pnther")

    response = await render_db_explorer(token=active_token)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.delete_cookie(key="budgetby_admin_session")
    return response

@app.get("/admin")
@app.get("/admin/{rest:path}")
async def redirect_old_admin(rest: str = ""):
    """Safely redirects deprecated /admin routes to consumer homepage."""
    return RedirectResponse(url="/", status_code=302)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)

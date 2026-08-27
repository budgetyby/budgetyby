import asyncio
import sys
import os
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from budgetby import database, config

app = FastAPI(title="BudgetBy Control Center", version="2.0")

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")

@app.on_event("startup")
async def startup():
    if not database._pool:
        await database.init_pool()

@app.get("/api/stats")
async def get_stats():
    try:
        # Total catalog products
        total_prods = await database.fetchval("SELECT COUNT(*) FROM products;")
        by_plat = await database.fetch("SELECT platform, COUNT(*) as count FROM products GROUP BY platform ORDER BY count DESC;")
        
        # Time-based deals counts (IST Timezone)
        deals_today = await database.fetchval("""
            SELECT COUNT(*) FROM deals 
            WHERE posted_at >= (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE;
        """)
        
        deals_1h = await database.fetchval("""
            SELECT COUNT(*) FROM deals 
            WHERE posted_at >= NOW() - INTERVAL '1 hour';
        """)
        
        deals_this_month = await database.fetchval("""
            SELECT COUNT(*) FROM deals 
            WHERE posted_at >= date_trunc('month', NOW() AT TIME ZONE 'Asia/Kolkata');
        """)
        
        deals_last_month = await database.fetchval("""
            SELECT COUNT(*) FROM deals 
            WHERE posted_at >= date_trunc('month', (NOW() AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 month')
              AND posted_at < date_trunc('month', NOW() AT TIME ZONE 'Asia/Kolkata');
        """)
        
        deals_lifetime = await database.fetchval("SELECT COUNT(*) FROM deals;")
        
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
        
        all_plats = ["amazon", "flipkart", "myntra", "ajio", "croma", "nykaa"]
        for p in all_plats:
            posted_today_by_plat.setdefault(p, 0)
            posted_month_by_plat.setdefault(p, 0)
            posted_life_by_plat.setdefault(p, 0)
                
        cooldowns = await database.fetchval("SELECT COUNT(*) FROM post_cooldowns WHERE expires_at > NOW();")
        daily_prices = await database.fetchval("SELECT COUNT(*) FROM daily_prices;")
        
        # Channel Ingestion Stats
        total_ingested = await database.fetchval("SELECT COUNT(*) FROM ingested_channel_deals;")
        ingested_today = await database.fetchval("SELECT COUNT(*) FROM ingested_channel_deals WHERE created_at >= (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE;")
        products_added_today = await database.fetchval("""
            SELECT COUNT(*) FROM products 
            WHERE (created_at AT TIME ZONE 'Asia/Kolkata')::DATE = (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE;
        """)
        
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
                COUNT(CASE WHEN p.platform = 'croma' THEN 1 END) as croma_deals,
                COUNT(CASE WHEN p.platform = 'nykaa' THEN 1 END) as nykaa_deals
            FROM deals d
            LEFT JOIN products p ON d.product_id = p.id
            GROUP BY date_trunc('month', d.posted_at AT TIME ZONE 'Asia/Kolkata')
            ORDER BY date_trunc('month', d.posted_at AT TIME ZONE 'Asia/Kolkata') DESC;
        """)
        
        return {
            "status": "online",
            "db_host": f"{config.DB_HOST}:{config.DB_PORT}",
            "db_name": config.DB_NAME,
            "total_products": total_prods or 0,
            "products_added_today": products_added_today or 0,
            "by_platform": {r["platform"]: r["count"] for r in by_plat},
            "deals_today": deals_today or 0,
            "deals_last_hour": deals_1h or 0,
            "deals_this_month": deals_this_month or 0,
            "deals_last_month": deals_last_month or 0,
            "deals_lifetime": deals_lifetime or 0,
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
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/channel_stats")
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
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/posting_queue")
async def get_posting_queue_endpoint():
    """Returns real-time deals in the posting queue waiting to be broadcasted."""
    try:
        from budgetby.engine.posting_queue import get_posting_queue
        pq = get_posting_queue()
        return pq.get_queue_snapshot()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/category_platform_stats")
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


@app.get("/api/price_changes_24h")
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

        # Global stats across entire 24h window
        global_stats = await database.fetchrow("""
            SELECT 
                COUNT(*) as global_total,
                COUNT(CASE WHEN dp_today.close_price < dp_yest.close_price THEN 1 END) as global_drops,
                COUNT(CASE WHEN dp_today.close_price > dp_yest.close_price THEN 1 END) as global_hikes
            FROM products p
            JOIN daily_prices dp_today ON p.id = dp_today.product_id AND dp_today.date = (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE
            JOIN daily_prices dp_yest ON p.id = dp_yest.product_id AND dp_yest.date = ((NOW() AT TIME ZONE 'Asia/Kolkata')::DATE - 1)
            WHERE dp_today.close_price != dp_yest.close_price;
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
                "drops": global_stats["global_drops"] if global_stats else 0,
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

@app.get("/db-explorer", response_class=HTMLResponse)
async def db_explorer_page():
    """Renders the Full Database Explorer Web Interface."""
    explorer_html_path = os.path.join(os.path.dirname(__file__), "templates", "explorer.html")
    if os.path.exists(explorer_html_path):
        with open(explorer_html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Database Explorer Loading...</h1>")

@app.get("/api/db/overview")
async def get_db_overview():
    """Returns database size, table summaries, and column schemas for all tables."""
    try:
        total_db_size = await database.fetchval("SELECT pg_size_pretty(pg_database_size('budgetby'));")
        
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
            "tables": [dict(t) for t in tables_stats],
            "schemas": table_schemas
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/db/product_history/{product_id}")
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/db/table_data")
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
                    where_clauses.append(f"(id = ${arg_idx} OR id::text LIKE ${arg_idx+1} OR title ILIKE ${arg_idx+2} OR platform_id ILIKE ${arg_idx+2})")
                    args.extend([exact_id, f"{clean_search}%", f"%{clean_search}%"])
                    arg_idx += 3
                    order_override = f"ORDER BY CASE WHEN id = {exact_id} THEN 0 WHEN id::text LIKE '{clean_search}%' THEN 1 ELSE 2 END, id ASC"
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
            order_col = sort_by if sort_by else ("id" if table != "channel_monitors" else "channel_name")
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/deals")
async def get_deals(limit: int = 36, platform: str = ""):
    try:
        where_clause = ""
        args = []
        if platform and platform.lower() != "all":
            where_clause = "WHERE LOWER(p.platform) = $1"
            args.append(platform.lower())
            
        limit_val = min(max(1, limit), 200)
        query = f"""
            SELECT d.id, d.posted_price, d.posted_mrp, d.savings_pct, d.badge, d.deal_score, d.posted_at, d.source_channel,
                   p.title, p.platform, p.category, p.product_url, p.affiliate_url, p.image_url, p.rating
            FROM deals d
            JOIN products p ON d.product_id = p.id
            {where_clause}
            ORDER BY d.posted_at DESC
            LIMIT {limit_val};
        """
        rows = await database.fetch(query, *args) if args else await database.fetch(query)
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/search")
async def search_products(q: str = Query(..., min_length=2), limit: int = 20):
    try:
        rows = await database.fetch("""
            SELECT id, platform, title, current_price, mrp, rating, review_count, in_stock, affiliate_url, product_url, image_url, min_30d, all_time_low
            FROM products
            WHERE title ILIKE $1 OR platform_id ILIKE $1
            ORDER BY current_price ASC NULLS LAST
            LIMIT $2;
        """, f"%{q}%", limit)
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trigger/backup")
async def trigger_backup():
    try:
        from budgetby.scheduler.cleanup import run_backup
        asyncio.create_task(run_backup())
        return {"status": "success", "message": "Database backup triggered successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trigger/backfill")
async def trigger_backfill():
    try:
        from budgetby.scheduler.scheduler import hourly_backfill
        asyncio.create_task(hourly_backfill())
        return {"status": "success", "message": "Hourly backfill post triggered successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trigger/channel_scan")
async def trigger_channel_scan():
    try:
        from budgetby.ingest.channel_monitor import run_channel_monitor
        asyncio.create_task(run_channel_monitor())
        return {"status": "success", "message": "Channel spy monitor scan triggered in background!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def dashboard_home():
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>BudgetBy Dashboard</h1><p>Template loading...</p>")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)

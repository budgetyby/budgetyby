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
        
        # Deals posted today & last hour
        deals_today = await database.fetchval("SELECT COUNT(*) FROM deals WHERE posted_at >= CURRENT_DATE;")
        deals_1h = await database.fetchval("SELECT COUNT(*) FROM deals WHERE posted_at >= NOW() - INTERVAL '1 hour';")
        
        # Deals posted TODAY grouped by platform
        posted_today_rows = await database.fetch("""
            SELECT p.platform, COUNT(*) as count 
            FROM deals d 
            JOIN products p ON d.product_id = p.id 
            WHERE d.posted_at >= CURRENT_DATE 
            GROUP BY p.platform;
        """)
        posted_today_by_plat = {r["platform"].lower(): r["count"] for r in posted_today_rows}
        
        # Deals posted LIFETIME grouped by platform
        posted_life_rows = await database.fetch("""
            SELECT p.platform, COUNT(*) as count 
            FROM deals d 
            JOIN products p ON d.product_id = p.id 
            GROUP BY p.platform;
        """)
        posted_life_by_plat = {r["platform"].lower(): r["count"] for r in posted_life_rows}
        
        # Ensure all 5 platforms exist in dicts
        all_plats = ["amazon", "flipkart", "myntra", "ajio", "nykaa"]
        for p in all_plats:
            if p not in posted_today_by_plat:
                posted_today_by_plat[p] = 0
            if p not in posted_life_by_plat:
                posted_life_by_plat[p] = 0
                
        cooldowns = await database.fetchval("SELECT COUNT(*) FROM post_cooldowns WHERE expires_at > NOW();")
        daily_prices = await database.fetchval("SELECT COUNT(*) FROM daily_prices;")
        latest_deals = await database.fetchval("SELECT COUNT(*) FROM deals;")
        
        return {
            "status": "online",
            "db_host": f"{config.DB_HOST}:{config.DB_PORT}",
            "db_name": config.DB_NAME,
            "total_products": total_prods or 0,
            "by_platform": {r["platform"]: r["count"] for r in by_plat},
            "deals_today": deals_today or 0,
            "deals_last_hour": deals_1h or 0,
            "posted_today_by_platform": posted_today_by_plat,
            "posted_lifetime_by_platform": posted_life_by_plat,
            "hourly_targets": config.PLATFORM_MIN_HOURLY_POSTS,
            "active_cooldowns": cooldowns or 0,
            "daily_prices_recorded": daily_prices or 0,
            "total_deals_lifetime": latest_deals or 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/deals")
async def get_deals(limit: int = 25):
    try:
        rows = await database.fetch(f"""
            SELECT d.id, d.posted_price, d.posted_mrp, d.savings_pct, d.badge, d.deal_score, d.posted_at,
                   p.title, p.platform, p.category, p.product_url, p.affiliate_url, p.image_url, p.rating
            FROM deals d
            JOIN products p ON d.product_id = p.id
            ORDER BY d.posted_at DESC
            LIMIT {limit};
        """)
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

@app.get("/", response_class=HTMLResponse)
async def dashboard_home():
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>BudgetBy Dashboard</h1><p>Template loading...</p>")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)

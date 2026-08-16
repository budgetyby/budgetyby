"""
BudgetBy — Database Table Inspector
Usage: python -m scripts.check_tables
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from budgetby import database


async def main():
    print("\n" + "=" * 60)
    print("BUDGETBY - DATABASE TABLE OVERVIEW")
    print("=" * 60)

    await database.init_pool()

    try:
        tables = [
            "products",
            "daily_prices",
            "deals",
            "deal_tracking",
            "post_cooldowns",
            "scraper_retry_queue",
        ]

        print("\nTable Row Counts:")
        for t in tables:
            count = await database.fetchval(f"SELECT COUNT(*) FROM {t}")
            print(f"  - {t:<22}: {count:>6} rows")

        # Check latest products
        products = await database.fetch("""
            SELECT id, platform, title, current_price, mrp, in_stock, status, priority_tier
            FROM products
            ORDER BY id DESC
            LIMIT 5
        """)

        if products:
            print("\nLatest 5 Tracked Products:")
            for p in products:
                print(f"  [{p['id']}] ({p['platform'].upper()}) {p['title'][:45]}... | Price: Rs.{p['current_price']} | Status: {p['status']}")
        else:
            print("\nProducts Table: Empty (Run 'python -m scripts.initial_seed' to add products)")

        # Check latest deals
        deals = await database.fetch("""
            SELECT id, product_id, deal_type, badge, posted_price, savings_pct, posted_at
            FROM deals
            ORDER BY id DESC
            LIMIT 5
        """)

        if deals:
            print("\nLatest 5 Posted Deals:")
            for d in deals:
                print(f"  [Deal #{d['id']}] Product #{d['product_id']} | {d['badge']} | Rs.{d['posted_price']} ({d['savings_pct']}% OFF)")
        else:
            print("\nDeals Table: No deals posted yet")

        print("\n" + "=" * 60 + "\n")

    finally:
        await database.close_pool()


if __name__ == "__main__":
    asyncio.run(main())

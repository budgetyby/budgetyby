"""
Inspect database catalog breakdown
"""
import asyncio
import asyncpg
import ssl
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from budgetby import config, database

async def main():
    await database.init_pool()

    total = await database.fetchval("SELECT COUNT(*) FROM products")
    print(f"Total products in DB: {total}")

    platforms = await database.fetch("SELECT platform, COUNT(*) FROM products GROUP BY platform")
    print("\nPlatform breakdown:")
    for p in platforms:
        print(f"  - {p['platform']}: {p['count']} products")

    categories = await database.fetch("SELECT category, COUNT(*) FROM products GROUP BY category ORDER BY count DESC LIMIT 15")
    print("\nTop 15 Categories:")
    for c in categories:
        print(f"  - {c['category']}: {c['count']} products")

    price_counts = await database.fetchval("SELECT COUNT(*) FROM daily_prices")
    print(f"\nTotal price records in daily_prices: {price_counts}")

    deals_count = await database.fetchval("SELECT COUNT(*) FROM deals")
    print(f"Total deals posted: {deals_count}")

    recent = await database.fetchval("SELECT MAX(created_at) FROM products")
    print(f"\nLatest product added at: {recent}")

    await database.close_pool()

if __name__ == "__main__":
    asyncio.run(main())

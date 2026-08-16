"""
BudgetBy — Initial Seed Script
Runs the seeder once to populate initial products across Amazon, Flipkart, and Myntra.
Usage: python -m scripts.initial_seed
"""

import asyncio
import logging
import os
import sys

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from budgetby import database
from budgetby.discovery.seeder import ProductSeeder

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("scripts.initial_seed")


async def main():
    logger.info("🚀 Starting initial product discovery and seeding...")
    await database.init_pool()
    try:
        seeder = ProductSeeder()
        stats = await seeder.run_full_discovery()
        logger.info(f"✅ Initial seeding completed successfully! Stats: {stats}")
    except Exception as e:
        logger.error(f"❌ Error during initial seed: {e}", exc_info=True)
    finally:
        await database.close_pool()
        logger.info("Database pool closed.")


if __name__ == "__main__":
    asyncio.run(main())

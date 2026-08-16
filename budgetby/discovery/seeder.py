"""
ProductSeeder orchestrator for populating the database with discovered products.
"""
import logging
import asyncio
from budgetby import config
from budgetby import database
from budgetby.discovery import amazon_discover, flipkart_discover, myntra_discover
from budgetby.affiliate import earnkaro_links, amazon_links

logger = logging.getLogger("budgetby.discovery.seeder")

class ProductSeeder:
    def __init__(self):
        self.stats = {
            "new_products_added": 0,
            "existing_updated": 0,
            "errors": 0
        }

    async def seed_amazon(self):
        logger.info("Starting Amazon discovery...")
        for category, info in config.AMAZON_DISCOVERY_TARGETS.items():
            try:
                slug = info.get("slug", category)
                products = await amazon_discover.discover_bestsellers(slug, pages=config.NORMAL_PAGES_PER_CATEGORY)
                for p in products:
                    p["category"] = info.get("category", category)
                    await self._upsert(p)
            except Exception as e:
                logger.error(f"Error seeding Amazon {category}: {e}")
                self.stats["errors"] += 1

    async def seed_flipkart(self):
        logger.info("Starting Flipkart discovery...")
        for category, info in config.FLIPKART_DISCOVERY_TARGETS.items():
            try:
                sid = info.get("sid", "")
                pages = min(info.get("pages", 2), config.NORMAL_PAGES_PER_CATEGORY)
                products = await flipkart_discover.discover_category(category, sid, pages=pages)
                for p in products:
                    p["category"] = info.get("category", category)
                    p["affiliate_url"] = await earnkaro_links.build_earnkaro_url(p["product_url"])
                    await self._upsert(p)
            except Exception as e:
                logger.error(f"Error seeding Flipkart {category}: {e}")
                self.stats["errors"] += 1

    async def seed_myntra(self):
        logger.info("Starting Myntra discovery...")
        for category, info in config.MYNTRA_DISCOVERY_TARGETS.items():
            try:
                pages = min(info.get("pages", 2), config.NORMAL_PAGES_PER_CATEGORY)
                products = await myntra_discover.discover_category(category, pages=pages)
                for p in products:
                    p["category"] = info.get("category", category)
                    p["affiliate_url"] = await earnkaro_links.build_earnkaro_url(p["product_url"])
                    await self._upsert(p)
            except Exception as e:
                logger.error(f"Error seeding Myntra {category}: {e}")
                self.stats["errors"] += 1

    async def _upsert(self, p_dict: dict):
        try:
            await database.upsert_product(p_dict)
            self.stats["new_products_added"] += 1
        except Exception as e:
            logger.error(f"Failed to upsert product {p_dict.get('platform_id')}: {e}")
            self.stats["errors"] += 1

    async def run_full_discovery(self):
        logger.info("Running full discovery...")
        await self.seed_amazon()
        await self.seed_flipkart()
        await self.seed_myntra()
        
        logger.info(f"Discovery completed. Stats: {self.stats}")

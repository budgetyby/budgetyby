"""
ProductSeeder orchestrator for populating the database with discovered products.
Supports Amazon, Flipkart, Myntra, Ajio, and Nykaa with EarnKaro & Amazon monetization.
"""
import logging
import asyncio
from budgetby import config
from budgetby import database
from budgetby.discovery import amazon_discover, flipkart_discover, myntra_discover, ajio_discover, nykaa_discover

logger = logging.getLogger("budgetby.discovery.seeder")

class ProductSeeder:
    def __init__(self):
        self.stats = {
            "new_products_added": 0,
            "existing_updated": 0,
            "errors": 0
        }

    async def get_target_pages(self, category_commission: float = 0.045) -> int:
        """Dynamically compute pages to crawl based on database size & commission potential."""
        try:
            total_prods = await database.fetchval("SELECT COUNT(*) FROM products") or 0
        except Exception:
            total_prods = 0

        if total_prods < 15000:
            if category_commission >= 0.08:
                return 6  # High commission (Fashion, Beauty, Watches, Shoes) -> 6 pages
            elif category_commission >= 0.04:
                return 4  # Core categories (Electronics, Laptops, Home, Sports, Toys) -> 4 pages
            else:
                return 3  # Low commission -> 3 pages
        else:
            return config.NORMAL_PAGES_PER_CATEGORY

    async def seed_amazon(self):
        logger.info("Starting Amazon full discovery across all categories & keywords...")
        try:
            total_prods = await database.fetchval("SELECT COUNT(*) FROM products") or 0
        except Exception:
            total_prods = 0

        for category, info in config.AMAZON_DISCOVERY_TARGETS.items():
            try:
                slug = info.get("slug", category)
                comm_rate = info.get("commission", 0.045)
                pages = await self.get_target_pages(comm_rate)
                
                # 1. Bestsellers
                products = await amazon_discover.discover_bestsellers(slug, pages=pages)
                for p in products:
                    p["category"] = info.get("category", category)
                    await self._upsert(p)

                # 2. In bootstrap mode (< 15,000 items), crawl New Releases, Most Wished & Keyword Searches
                if total_prods < 15000:
                    new_rel = await amazon_discover.discover_new_releases(slug, pages=2)
                    for p in new_rel:
                        p["category"] = info.get("category", category)
                        await self._upsert(p)

                    wished = await amazon_discover.discover_most_wished_for(slug)
                    for p in wished:
                        p["category"] = info.get("category", category)
                        await self._upsert(p)

                    keywords = amazon_discover.AMAZON_CATEGORY_KEYWORDS.get(category, [])
                    for kw in keywords:
                        kw_prods = await amazon_discover.discover_search_keywords(kw, pages=3)
                        for p in kw_prods:
                            p["category"] = info.get("category", category)
                            await self._upsert(p)
                        await asyncio.sleep(config.SCRAPER_DELAY_MIN)

                logger.info(f"Amazon {category}: Completed discovery pass")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Amazon {category}: {e}")
                self.stats["errors"] += 1

    async def seed_flipkart(self):
        logger.info("Starting Flipkart discovery...")
        for category, info in config.FLIPKART_DISCOVERY_TARGETS.items():
            try:
                sid = info.get("sid", "")
                cat_type = info.get("category", "fashion")
                comm_rate = config.EARNKARO_COMMISSION_RATES["flipkart"].get(cat_type, 0.03)
                pages = await self.get_target_pages(comm_rate)
                pages = min(pages, info.get("pages", 5))

                products = await flipkart_discover.discover_category(category, sid, pages=pages)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Flipkart {category}: {e}")
                self.stats["errors"] += 1

    async def seed_myntra(self):
        logger.info("Starting Myntra discovery...")
        for category, info in config.MYNTRA_DISCOVERY_TARGETS.items():
            try:
                cat_type = info.get("category", "fashion")
                comm_rate = 0.0875 if "fashion" in cat_type else 0.05
                pages = await self.get_target_pages(comm_rate)
                pages = min(pages, info.get("pages", 5))

                products = await myntra_discover.discover_category(category, pages=pages)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Myntra {category}: {e}")
                self.stats["errors"] += 1

    async def seed_ajio(self):
        logger.info("Starting Ajio discovery...")
        for category, info in getattr(config, "AJIO_DISCOVERY_TARGETS", {}).items():
            try:
                code = info.get("code", "")
                cat_type = info.get("category", "fashion")
                products = await ajio_discover.discover_category(code, pages=2)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Ajio {category}: Discovered {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Ajio {category}: {e}")
                self.stats["errors"] += 1

    async def seed_nykaa(self):
        logger.info("Starting Nykaa discovery...")
        for category, info in getattr(config, "NYKAA_DISCOVERY_TARGETS", {}).items():
            try:
                path = info.get("path", "")
                cat_type = info.get("category", "beauty")
                products = await nykaa_discover.discover_category(path, pages=2)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Nykaa {category}: Discovered {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Nykaa {category}: {e}")
                self.stats["errors"] += 1

    async def _upsert(self, product_data: dict):
        try:
            if not product_data.get("product_url"):
                return
            await database.upsert_product(product_data)
            self.stats["new_products_added"] += 1
        except Exception as e:
            logger.error(f"Error upserting product {product_data.get('platform_id')}: {e}")
            self.stats["errors"] += 1

    async def run_bootstrap_until_target(self, target_count: int = 15000):
        """Continuously runs discovery until target catalog size is reached."""
        logger.info(f"Starting continuous bootstrap loop until {target_count} products...")
        while True:
            try:
                total_prods = await database.fetchval("SELECT COUNT(*) FROM products") or 0
            except Exception:
                total_prods = 0

            if total_prods >= target_count:
                logger.info(f"Target catalog reached ({total_prods} >= {target_count}). Switching to 6h routine maintenance.")
                break

            logger.info(f"Bootstrap Progress: {total_prods}/{target_count} products. Starting full wave...")
            await self.seed_amazon()
            await self.seed_ajio()
            await self.seed_nykaa()
            
            try:
                total_prods = await database.fetchval("SELECT COUNT(*) FROM products") or 0
            except Exception:
                pass

            if total_prods >= target_count:
                logger.info(f"Target reached: {total_prods} products! Switching to routine maintenance mode.")
                break

            logger.info(f"Wave finished. Current count: {total_prods}/{target_count}. Pausing 15s before next wave...")
            await asyncio.sleep(15)

    async def run_full_discovery(self) -> dict:
        """Run standard multi-platform discovery pass."""
        logger.info("Running routine multi-platform discovery pass across Amazon, Flipkart, Myntra, Ajio, Nykaa...")
        await self.seed_amazon()
        await self.seed_flipkart()
        await self.seed_myntra()
        await self.seed_ajio()
        await self.seed_nykaa()
        logger.info(f"Discovery pass complete. Stats: {self.stats}")
        return self.stats

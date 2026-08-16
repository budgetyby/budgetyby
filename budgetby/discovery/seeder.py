"""
ProductSeeder orchestrator for populating the database with discovered products.
Implements intelligent dynamic scaling:
- Bootstrap Mode (< 15,000 products): Crawls 4-8 pages across all 200+ categories based on commission priority.
- Maintenance Mode (>= 15,000 products): Crawls 2 pages every 6 hours to capture new trending items.
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

    async def get_target_pages(self, category_commission: float = 0.045) -> int:
        """Dynamically compute pages to crawl based on database size & commission potential."""
        try:
            total_prods = await database.fetchval("SELECT COUNT(*) FROM products") or 0
        except Exception:
            total_prods = 0

        # If database is small (< 15,000 products), scale up crawl depth
        if total_prods < 15000:
            if category_commission >= 0.08:
                return 6  # High commission (Fashion, Beauty, Watches, Shoes) -> 6 pages
            elif category_commission >= 0.04:
                return 4  # Core categories (Electronics, Laptops, Home, Sports, Toys) -> 4 pages
            else:
                return 3  # Smartphones, low commission -> 3 pages
        else:
            return config.NORMAL_PAGES_PER_CATEGORY  # Standard 2 pages in maintenance mode

    async def seed_amazon(self):
        logger.info("Starting Amazon full discovery across all categories...")
        for category, info in config.AMAZON_DISCOVERY_TARGETS.items():
            try:
                slug = info.get("slug", category)
                comm_rate = info.get("commission", 0.045)
                pages = await self.get_target_pages(comm_rate)
                
                products = await amazon_discover.discover_bestsellers(slug, pages=pages)
                for p in products:
                    p["category"] = info.get("category", category)
                    await self._upsert(p)
                logger.info(f"Amazon {category}: Discovered {len(products)} products ({pages} pages)")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Amazon {category}: {e}")
                self.stats["errors"] += 1

    async def seed_flipkart(self):
        logger.info("Starting Flipkart full discovery across 80+ categories...")
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
                    p["affiliate_url"] = await earnkaro_links.build_earnkaro_url(p["product_url"])
                    await self._upsert(p)
                logger.info(f"Flipkart {category}: Discovered {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Flipkart {category}: {e}")
                self.stats["errors"] += 1

    async def seed_myntra(self):
        logger.info("Starting Myntra full discovery across 115+ categories...")
        for category, info in config.MYNTRA_DISCOVERY_TARGETS.items():
            try:
                cat_type = info.get("category", "fashion")
                comm_rate = 0.0875 if "fashion" in cat_type else 0.05
                pages = await self.get_target_pages(comm_rate)
                pages = min(pages, info.get("pages", 5))

                products = await myntra_discover.discover_category(category, pages=pages)
                for p in products:
                    p["category"] = cat_type
                    p["affiliate_url"] = await earnkaro_links.build_earnkaro_url(p["product_url"])
                    await self._upsert(p)
                logger.info(f"Myntra {category}: Discovered {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Myntra {category}: {e}")
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

    async def run_full_discovery(self) -> dict:
        """Run discovery across all platforms with auto-scaling."""
        logger.info("🚀 Running autonomous multi-platform full discovery...")
        await self.seed_amazon()
        await self.seed_flipkart()
        await self.seed_myntra()
        logger.info(f"✅ Full discovery complete. Stats: {self.stats}")
        return self.stats

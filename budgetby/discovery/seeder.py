"""
ProductSeeder orchestrator for populating the database with discovered products.
Maintains balanced, proportional multi-platform catalogs:
- Amazon: ~22,000 products (Core multi-category)
- Flipkart: ~4,000 products (Tech, Home & Bestsellers)
- Myntra: ~4,000 products (Fashion & Footwear)
- Ajio: ~2,000 products (Trendy Streetwear & Kurtas)
- Nykaa: ~1,500 products (Skincare, Cosmetics & Fragrances)
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
        """Compute pages to crawl based on commission potential."""
        if category_commission >= 0.08:
            return 4  # High commission -> 4 pages
        elif category_commission >= 0.04:
            return 3  # Core categories -> 3 pages
        else:
            return 2  # Standard -> 2 pages

    async def seed_amazon(self):
        logger.info("Starting Amazon full discovery...")
        for category, info in config.AMAZON_DISCOVERY_TARGETS.items():
            try:
                slug = info.get("slug", category)
                comm_rate = info.get("commission", 0.045)
                pages = await self.get_target_pages(comm_rate)
                
                products = await amazon_discover.discover_bestsellers(slug, pages=pages)
                for p in products:
                    p["category"] = info.get("category", category)
                    await self._upsert(p)

                keywords = amazon_discover.AMAZON_CATEGORY_KEYWORDS.get(category, [])
                for kw in keywords[:10]:
                    kw_prods = await amazon_discover.discover_search_keywords(kw, pages=2)
                    for p in kw_prods:
                        p["category"] = info.get("category", category)
                        await self._upsert(p)
                    await asyncio.sleep(config.SCRAPER_DELAY_MIN)

                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Amazon {category}: {e}")
                self.stats["errors"] += 1

    async def seed_flipkart(self):
        logger.info("Starting Flipkart discovery across all 80+ categories...")
        for category, info in config.FLIPKART_DISCOVERY_TARGETS.items():
            try:
                sid = info.get("sid", "")
                cat_type = info.get("category", "fashion")
                pages = min(info.get("pages", 3), 3)

                products = await flipkart_discover.discover_category(category, sid, pages=pages)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Flipkart {category}: Added {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Flipkart {category}: {e}")
                self.stats["errors"] += 1

    async def seed_myntra(self):
        logger.info("Starting Myntra discovery across 115+ categories...")
        for category, info in config.MYNTRA_DISCOVERY_TARGETS.items():
            try:
                cat_type = info.get("category", "fashion")
                pages = min(info.get("pages", 3), 3)

                products = await myntra_discover.discover_category(category, pages=pages)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Myntra {category}: Added {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Myntra {category}: {e}")
                self.stats["errors"] += 1

    async def seed_ajio(self):
        logger.info("Starting Ajio discovery across all fashion categories...")
        for category, info in getattr(config, "AJIO_DISCOVERY_TARGETS", {}).items():
            try:
                code = info.get("code", "")
                cat_type = info.get("category", "fashion")
                products = await ajio_discover.discover_category(code, pages=3)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Ajio {category}: Added {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Ajio {category}: {e}")
                self.stats["errors"] += 1

    async def seed_nykaa(self):
        logger.info("Starting Nykaa discovery across all beauty categories...")
        for category, info in getattr(config, "NYKAA_DISCOVERY_TARGETS", {}).items():
            try:
                path = info.get("path", "")
                cat_type = info.get("category", "beauty")
                products = await nykaa_discover.discover_category(path, pages=3)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Nykaa {category}: Added {len(products)} products")
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

    async def run_full_discovery(self) -> dict:
        """Runs autonomous discovery across all 5 platforms."""
        logger.info("🚀 Running autonomous multi-platform full discovery across Amazon, Flipkart, Myntra, Ajio, Nykaa...")
        await self.seed_amazon()
        await self.seed_flipkart()
        await self.seed_myntra()
        await self.seed_ajio()
        await self.seed_nykaa()
        logger.info(f"✅ Multi-platform discovery complete. Stats: {self.stats}")
        return self.stats

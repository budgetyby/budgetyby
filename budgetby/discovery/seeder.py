"""
ProductSeeder orchestrator with customized high-profit proportions (~75,000 products):
- Amazon (31%): ~23,250 products (Official Tag: dealpulse21-21)
- Flipkart (25%): ~18,750 products (EarnKaro: r=5549565)
- Myntra (20%): ~15,000 products (EarnKaro: r=5549565)
- Ajio (15%): ~11,250 products (EarnKaro: r=5549565)
- Nykaa (9%): ~6,750 products (EarnKaro: r=5549565)
"""
import logging
import asyncio
from budgetby import config
from budgetby import database
from budgetby.discovery import amazon_discover, flipkart_discover, myntra_discover, ajio_discover, nykaa_discover

logger = logging.getLogger("budgetby.discovery.seeder")

TARGET_PROPORTIONS = {
    "amazon": 23250,
    "flipkart": 18750,
    "myntra": 15000,
    "ajio": 11250,
    "nykaa": 6750,
}

class ProductSeeder:
    def __init__(self):
        self.stats = {
            "new_products_added": 0,
            "existing_updated": 0,
            "errors": 0
        }

    async def get_platform_count(self, platform: str) -> int:
        try:
            return await database.fetchval("SELECT COUNT(*) FROM products WHERE platform = $1", platform) or 0
        except Exception:
            return 0

    async def seed_amazon(self):
        current_count = await self.get_platform_count("amazon")
        target = TARGET_PROPORTIONS["amazon"]
        if current_count >= target:
            logger.info(f"Amazon target reached ({current_count}/{target}). Skipping deep wave.")
            return

        logger.info(f"Starting Amazon discovery ({current_count}/{target} target)...")
        for category, info in config.AMAZON_DISCOVERY_TARGETS.items():
            try:
                slug = info.get("slug", category)
                
                # Bestsellers
                products = await amazon_discover.discover_bestsellers(slug, pages=3)
                for p in products:
                    p["category"] = info.get("category", category)
                    await self._upsert(p)

                # New Releases & Most Wished
                new_rel = await amazon_discover.discover_new_releases(slug, pages=2)
                for p in new_rel:
                    p["category"] = info.get("category", category)
                    await self._upsert(p)

                wished = await amazon_discover.discover_most_wished_for(slug)
                for p in wished:
                    p["category"] = info.get("category", category)
                    await self._upsert(p)

                # Search Keywords
                keywords = amazon_discover.AMAZON_CATEGORY_KEYWORDS.get(category, [])
                for kw in keywords[:8]:
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
        current_count = await self.get_platform_count("flipkart")
        target = TARGET_PROPORTIONS["flipkart"]
        if current_count >= target:
            logger.info(f"Flipkart target reached ({current_count}/{target}). Skipping deep wave.")
            return

        logger.info(f"Starting Flipkart discovery ({current_count}/{target} target)...")
        for category, info in config.FLIPKART_DISCOVERY_TARGETS.items():
            try:
                sid = info.get("sid", "")
                cat_type = info.get("category", "fashion")

                products = await flipkart_discover.discover_category(category, sid, pages=10)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Flipkart {category}: Added {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Flipkart {category}: {e}")
                self.stats["errors"] += 1

    async def seed_myntra(self):
        current_count = await self.get_platform_count("myntra")
        target = TARGET_PROPORTIONS["myntra"]
        if current_count >= target:
            logger.info(f"Myntra target reached ({current_count}/{target}). Skipping deep wave.")
            return

        logger.info(f"Starting Myntra discovery ({current_count}/{target} target)...")
        for category, info in config.MYNTRA_DISCOVERY_TARGETS.items():
            try:
                cat_type = info.get("category", "fashion")

                products = await myntra_discover.discover_category(category, pages=5)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Myntra {category}: Added {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Myntra {category}: {e}")
                self.stats["errors"] += 1

    async def seed_ajio(self):
        current_count = await self.get_platform_count("ajio")
        target = TARGET_PROPORTIONS["ajio"]
        if current_count >= target:
            logger.info(f"Ajio target reached ({current_count}/{target}). Skipping deep wave.")
            return

        logger.info(f"Starting Ajio discovery ({current_count}/{target} target)...")
        for category, info in getattr(config, "AJIO_DISCOVERY_TARGETS", {}).items():
            try:
                code = info.get("code", "")
                cat_type = info.get("category", "fashion")
                products = await ajio_discover.discover_category(code, pages=18)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Ajio {category}: Added {len(products)} products")
                await asyncio.sleep(config.SCRAPER_DELAY_MIN)
            except Exception as e:
                logger.error(f"Error seeding Ajio {category}: {e}")
                self.stats["errors"] += 1

    async def seed_nykaa(self):
        current_count = await self.get_platform_count("nykaa")
        target = TARGET_PROPORTIONS["nykaa"]
        if current_count >= target:
            logger.info(f"Nykaa target reached ({current_count}/{target}). Skipping deep wave.")
            return

        logger.info(f"Starting Nykaa discovery ({current_count}/{target} target)...")
        for category, info in getattr(config, "NYKAA_DISCOVERY_TARGETS", {}).items():
            try:
                path = info.get("path", "")
                cat_type = info.get("category", "beauty")
                products = await nykaa_discover.discover_category(path, pages=15)
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

    async def run_bootstrap_until_target(self, target_count: int = 75000):
        """Continuously runs discovery until custom multi-platform proportional targets are reached."""
        logger.info(f"Starting continuous multi-platform bootstrap loop until {target_count} products...")
        while True:
            try:
                total_prods = await database.fetchval("SELECT COUNT(*) FROM products") or 0
            except Exception:
                total_prods = 0

            if total_prods >= target_count:
                logger.info(f"Target catalog reached ({total_prods} >= {target_count}). Switching to routine 6h maintenance.")
                break

            logger.info(f"Bootstrap progress: {total_prods}/{target_count} products. Running concurrent discovery across all 5 platforms...")
            await asyncio.gather(
                self.seed_flipkart(),
                self.seed_myntra(),
                self.seed_ajio(),
                self.seed_nykaa(),
                self.seed_amazon(),
                return_exceptions=True
            )
            
            try:
                total_prods = await database.fetchval("SELECT COUNT(*) FROM products") or 0
            except Exception:
                pass

            if total_prods >= target_count:
                logger.info(f"Target reached: {total_prods} products! Switching to routine maintenance mode.")
                break

            logger.info(f"Wave finished. Current count: {total_prods}/{target_count}. Pausing 10s before next wave...")
            await asyncio.sleep(10)

    async def run_full_discovery(self) -> dict:
        """Runs standard multi-platform discovery pass."""
        logger.info("Running routine multi-platform discovery pass across Amazon, Flipkart, Myntra, Ajio, Nykaa...")
        await asyncio.gather(
            self.seed_flipkart(),
            self.seed_myntra(),
            self.seed_ajio(),
            self.seed_nykaa(),
            self.seed_amazon(),
            return_exceptions=True
        )
        logger.info(f"Discovery pass complete. Stats: {self.stats}")
        return self.stats

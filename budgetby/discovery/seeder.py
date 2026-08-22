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
            logger.info(f"Amazon target reached ({current_count}/{target}). Skipping discovery.")
            return

        logger.info(f"Starting throttled Amazon discovery ({current_count}/{target} target)...")
        for category, info in config.AMAZON_DISCOVERY_TARGETS.items():
            current_count = await self.get_platform_count("amazon")
            if current_count >= target:
                break
            try:
                slug = info.get("slug", category)
                
                # Bestsellers (single page, slowed down)
                products = await amazon_discover.discover_bestsellers(slug, pages=1)
                for p in products:
                    p["category"] = info.get("category", category)
                    await self._upsert(p)
                await asyncio.sleep(3.0)

                # New Releases (single page, slowed down)
                new_rel = await amazon_discover.discover_new_releases(slug, pages=1)
                for p in new_rel:
                    p["category"] = info.get("category", category)
                    await self._upsert(p)
                await asyncio.sleep(3.0)

                # Search Keywords (throttled to max 2 keywords with 4s pause)
                keywords = amazon_discover.AMAZON_CATEGORY_KEYWORDS.get(category, [])
                for kw in keywords[:2]:
                    kw_prods = await amazon_discover.discover_search_keywords(kw, pages=1)
                    for p in kw_prods:
                        p["category"] = info.get("category", category)
                        await self._upsert(p)
                    await asyncio.sleep(4.0)

                await asyncio.sleep(5.0)
            except Exception as e:
                logger.error(f"Error seeding Amazon {category}: {e}")
                self.stats["errors"] += 1

    async def seed_flipkart(self, sort_mode: str = "popularity"):
        current_count = await self.get_platform_count("flipkart")
        target = TARGET_PROPORTIONS["flipkart"]
        if current_count >= target:
            logger.info(f"Flipkart target reached ({current_count}/{target}). Skipping deep wave.")
            return

        logger.info(f"Starting Flipkart discovery [sort={sort_mode}] ({current_count}/{target} target)...")
        for category, info in config.FLIPKART_DISCOVERY_TARGETS.items():
            current_count = await self.get_platform_count("flipkart")
            if current_count >= target:
                break
            try:
                sid = info.get("sid", "")
                cat_type = info.get("category", "fashion")

                products = await flipkart_discover.discover_category(category, sid, pages=25, sort=sort_mode)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Flipkart {category} ({sort_mode}): Added {len(products)} products")
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error seeding Flipkart {category}: {e}")
                self.stats["errors"] += 1

    async def seed_myntra(self, sort_mode: str = "popularity"):
        current_count = await self.get_platform_count("myntra")
        target = TARGET_PROPORTIONS["myntra"]
        if current_count >= target:
            logger.info(f"Myntra target reached ({current_count}/{target}). Skipping deep wave.")
            return

        logger.info(f"Starting concurrent Myntra discovery [sort={sort_mode}] ({current_count}/{target} target)...")
        sem = asyncio.Semaphore(3)

        async def process_category(category, info):
            cnt = await self.get_platform_count("myntra")
            if cnt >= target:
                return
            async with sem:
                try:
                    cat_type = info.get("category", "fashion")
                    products = await myntra_discover.discover_category(category, pages=15, sort=sort_mode)
                    for p in products:
                        p["category"] = cat_type
                        await self._upsert(p)
                    logger.info(f"Myntra {category} ({sort_mode}): Added {len(products)} products")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error seeding Myntra {category}: {e}")
                    self.stats["errors"] += 1

        tasks = [process_category(cat, info) for cat, info in config.MYNTRA_DISCOVERY_TARGETS.items()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def seed_ajio(self):
        current_count = await self.get_platform_count("ajio")
        target = TARGET_PROPORTIONS["ajio"]
        if current_count >= target:
            logger.info(f"Ajio target reached ({current_count}/{target}). Skipping deep wave.")
            return

        logger.info(f"Starting Ajio discovery ({current_count}/{target} target)...")
        for category, info in getattr(config, "AJIO_DISCOVERY_TARGETS", {}).items():
            current_count = await self.get_platform_count("ajio")
            if current_count >= target:
                break
            try:
                code = info.get("code", "")
                cat_type = info.get("category", "fashion")
                products = await ajio_discover.discover_category(code, pages=30)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Ajio {category}: Added {len(products)} products")
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error seeding Ajio {category}: {e}")
                self.stats["errors"] += 1

    async def seed_nykaa(self, sort_mode: str = "popularity"):
        current_count = await self.get_platform_count("nykaa")
        target = TARGET_PROPORTIONS["nykaa"]
        if current_count >= target:
            logger.info(f"Nykaa target reached ({current_count}/{target}). Skipping deep wave.")
            return

        logger.info(f"Starting Nykaa discovery [sort={sort_mode}] ({current_count}/{target} target)...")
        for category, info in getattr(config, "NYKAA_DISCOVERY_TARGETS", {}).items():
            current_count = await self.get_platform_count("nykaa")
            if current_count >= target:
                break
            try:
                path = info.get("path", "")
                cat_type = info.get("category", "beauty")
                products = await nykaa_discover.discover_category(path, pages=25, sort=sort_mode)
                for p in products:
                    p["category"] = cat_type
                    await self._upsert(p)
                logger.info(f"Nykaa {category} ({sort_mode}): Added {len(products)} products")
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

    async def _platform_worker(self, platform: str, seed_func, sort_modes: list = None):
        """Runs continuous multi-sort discovery for a single platform until its target is reached."""
        target = TARGET_PROPORTIONS.get(platform, 15000)
        sort_modes = sort_modes or ["popularity"]
        mode_idx = 0

        while True:
            try:
                current_count = await self.get_platform_count(platform)
                if current_count >= target:
                    logger.info(f"[{platform.upper()}] Target reached ({current_count}/{target}). Worker sleeping for 1 hour.")
                    await asyncio.sleep(3600)
                    continue

                active_sort = sort_modes[mode_idx % len(sort_modes)]
                mode_idx += 1

                logger.info(f"[{platform.upper()}] Starting discovery pass [sort={active_sort}] ({current_count}/{target} target)...")
                if platform in ("myntra", "nykaa", "flipkart"):
                    await seed_func(sort_mode=active_sort)
                else:
                    await seed_func()
                logger.info(f"[{platform.upper()}] Discovery pass ({active_sort}) completed. Brief pause before next cycle.")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"[{platform.upper()}] Worker error: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def run_bootstrap_until_target(self, target_count: int = 75000):
        """Runs continuous independent multi-platform workers until custom targets are reached."""
        logger.info(f"Starting independent multi-platform workers until {target_count} total products...")

        async def guarded_worker(platform, seed_func, sort_modes):
            """Wraps _platform_worker with outer crash recovery so the worker NEVER permanently dies."""
            while True:
                try:
                    await self._platform_worker(platform, seed_func, sort_modes)
                    break  # Worker exited cleanly (target reached)
                except Exception as e:
                    logger.error(f"[{platform.upper()}] Worker crashed unexpectedly: {e}. Restarting in 30s...", exc_info=True)
                    await asyncio.sleep(30)

        tasks = [
            asyncio.create_task(guarded_worker("myntra", self.seed_myntra, ["popularity", "discount", "new"])),
            asyncio.create_task(guarded_worker("nykaa", self.seed_nykaa, ["popularity", "discount", "new_arrival", "customer_top_rated"])),
            asyncio.create_task(guarded_worker("flipkart", self.seed_flipkart, ["popularity", "discount", "recency_desc", "relevance"])),
            asyncio.create_task(guarded_worker("ajio", self.seed_ajio, None)),
            asyncio.create_task(guarded_worker("amazon", self.seed_amazon, None)),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)


    async def run_full_discovery(self) -> dict:
        """Runs standard multi-platform discovery pass."""
        logger.info("Running routine multi-platform discovery pass across Amazon, Flipkart, Myntra, Ajio, Nykaa...")
        results = await asyncio.gather(
            self.seed_flipkart(),
            self.seed_myntra(),
            self.seed_ajio(),
            self.seed_nykaa(),
            self.seed_amazon(),
            return_exceptions=True
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Discovery task failed: {r}", exc_info=r)
        logger.info(f"Discovery pass complete. Stats: {self.stats}")
        return self.stats

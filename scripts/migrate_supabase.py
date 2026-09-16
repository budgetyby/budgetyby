import asyncio
from budgetby import database

async def migrate():
    await database.init_pool()
    print('Adding current_deal_score column...')
    await database.execute('ALTER TABLE products ADD COLUMN IF NOT EXISTS current_deal_score INTEGER DEFAULT 0;')
    print('Creating index...')
    await database.execute('CREATE INDEX IF NOT EXISTS idx_products_feed ON products (current_deal_score DESC, in_stock DESC, id ASC);')
    await database.close_pool()

asyncio.run(migrate())

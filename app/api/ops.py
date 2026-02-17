from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis_client import get_redis
from app.db.session import get_db_session

router = APIRouter()


@router.get('/health')
async def health(db: AsyncSession = Depends(get_db_session), redis: Redis = Depends(get_redis)):
    await db.execute(text('SELECT 1'))
    pong = await redis.ping()
    return {'status': 'ok', 'db': 'ok', 'redis': bool(pong)}


@router.get('/metrics')
async def metrics(db: AsyncSession = Depends(get_db_session)):
    # simple placeholder metrics in plaintext format
    result = await db.execute(text('SELECT COUNT(*) FROM giveaways'))
    giveaways = result.scalar() or 0
    return {'giveaways_total': giveaways}

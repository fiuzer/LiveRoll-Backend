from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from app.db.redis_client import get_redis


class RateLimiter:
    def __init__(self, bucket: str, max_requests: int, window_seconds: int) -> None:
        self.bucket = bucket
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def __call__(self, request: Request, redis: Redis = Depends(get_redis)) -> None:
        ip = request.client.host if request.client else 'unknown'
        user_id = request.session.get('user_id', 'anon')
        key = f'ratelimit:{self.bucket}:{user_id}:{ip}'
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, self.window_seconds)
        if count > self.max_requests:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail='Too many requests')

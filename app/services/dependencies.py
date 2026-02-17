from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models import Giveaway, User


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db_session)) -> User:
    user_id = request.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid user session')
    return user


async def get_owned_giveaway(giveaway_id: int, user: User, db: AsyncSession) -> Giveaway:
    result = await db.execute(
        select(Giveaway).where(Giveaway.id == giveaway_id, Giveaway.user_id == user.id)
    )
    giveaway = result.scalar_one_or_none()
    if not giveaway:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Giveaway not found')
    return giveaway

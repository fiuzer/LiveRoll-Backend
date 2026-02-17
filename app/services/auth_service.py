from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models import AuthIdentity, User


async def create_user(db: AsyncSession, email: str, password: str) -> User:
    user = User(email=email.lower().strip(), password_hash=hash_password(password))
    db.add(user)
    await db.flush()
    return user


async def create_social_user(db: AsyncSession, email: str) -> User:
    user = User(email=email.lower().strip(), password_hash=None)
    db.add(user)
    await db.flush()
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower().strip()))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def user_exists(db: AsyncSession, email: str) -> bool:
    result = await db.execute(select(User.id).where(User.email == email.lower().strip()))
    return result.scalar_one_or_none() is not None


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower().strip()))
    return result.scalar_one_or_none()


async def get_user_by_identity(db: AsyncSession, provider: str, provider_user_id: str) -> User | None:
    result = await db.execute(
        select(User)
        .join(AuthIdentity, AuthIdentity.user_id == User.id)
        .where(AuthIdentity.provider == provider, AuthIdentity.provider_user_id == provider_user_id)
    )
    return result.scalar_one_or_none()


async def link_identity(
    db: AsyncSession,
    user_id: int,
    provider: str,
    provider_user_id: str,
    email: str | None,
) -> AuthIdentity:
    result = await db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == provider,
            AuthIdentity.provider_user_id == provider_user_id,
        )
    )
    identity = result.scalar_one_or_none()
    if identity is None:
        identity = AuthIdentity(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email.lower().strip() if email else None,
        )
        db.add(identity)
    else:
        identity.user_id = user_id
        identity.email = email.lower().strip() if email else identity.email
    await db.flush()
    return identity

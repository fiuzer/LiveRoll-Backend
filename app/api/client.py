from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models import Giveaway, OAuthAccount, OAuthProvider, User
from app.services.dependencies import get_current_user

router = APIRouter(prefix='/api/v1', tags=['client'])


async def _session_user(request: Request, db: AsyncSession) -> User | None:
    raw_user_id = request.session.get('user_id')
    if not raw_user_id:
        return None
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


@router.get('/public/links')
async def public_links(request: Request):
    base_url = str(request.base_url).rstrip('/')
    return {
        'base_url': base_url,
        'login_url': f'{base_url}/login',
        'register_url': f'{base_url}/register',
        'dashboard_url': f'{base_url}/dashboard',
        'google_login_url': f'{base_url}/auth/google/start',
        'github_login_url': f'{base_url}/auth/github/start',
    }


@router.get('/session')
async def session_status(request: Request, db: AsyncSession = Depends(get_db_session)):
    user = await _session_user(request, db)
    if user is None:
        return {
            'authenticated': False,
            'user': None,
            'connected': {'twitch': False, 'google': False},
            'csrf_token': request.session.get('csrf_token'),
        }

    accounts = (
        await db.execute(select(OAuthAccount).where(OAuthAccount.user_id == user.id))
    ).scalars()
    providers = {account.provider for account in accounts}

    return {
        'authenticated': True,
        'user': {'id': user.id, 'email': user.email},
        'connected': {
            'twitch': OAuthProvider.TWITCH in providers,
            'google': OAuthProvider.GOOGLE in providers,
        },
        'csrf_token': request.session.get('csrf_token'),
    }


@router.get('/giveaways')
async def giveaways_list(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    items = (
        await db.execute(
            select(Giveaway)
            .where(Giveaway.user_id == user.id)
            .order_by(Giveaway.id.desc())
        )
    ).scalars().all()
    return {
        'items': [
            {
                'id': giveaway.id,
                'name': giveaway.name,
                'command': giveaway.command,
                'is_open': giveaway.is_open,
                'created_at': giveaway.created_at,
            }
            for giveaway in items
        ],
        'count': len(items),
    }

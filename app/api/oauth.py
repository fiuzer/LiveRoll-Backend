import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_csrf
from app.db.session import get_db_session
from app.models import OAuthAccount, OAuthProvider
from app.services.audit import add_audit_log
from app.services.dependencies import get_current_user
from app.services.oauth_service import (
    OAuthServiceError,
    google_authorize_url,
    google_exchange_code,
    save_oauth_account,
    twitch_authorize_url,
    twitch_exchange_code,
)

router = APIRouter(prefix='/oauth')


@router.get('/twitch/connect')
async def twitch_connect(request: Request, user=Depends(get_current_user)):
    state = secrets.token_urlsafe(24)
    request.session['oauth_state_twitch'] = state
    return RedirectResponse(twitch_authorize_url(state), status_code=status.HTTP_302_FOUND)


@router.get('/twitch/callback')
async def twitch_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    if request.session.get('oauth_state_twitch') != state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='OAuth state inválido')
    data = await twitch_exchange_code(code)
    await save_oauth_account(
        db=db,
        user_id=user.id,
        provider=OAuthProvider.TWITCH,
        access_token=data['access_token'],
        refresh_token=data.get('refresh_token'),
        expires_in=data.get('expires_in'),
        provider_user_id=data['provider_user_id'],
        scopes=data.get('scopes', ''),
    )
    await add_audit_log(db, user_id=user.id, action='oauth_connected', payload={'provider': 'twitch'})
    await db.commit()
    return RedirectResponse('/dashboard?connected=twitch', status_code=status.HTTP_302_FOUND)


@router.get('/google/connect')
async def google_connect(request: Request, user=Depends(get_current_user)):
    state = secrets.token_urlsafe(24)
    request.session['oauth_state_google'] = state
    return RedirectResponse(google_authorize_url(state), status_code=status.HTTP_302_FOUND)


@router.get('/google/callback')
async def google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    if request.session.get('oauth_state_google') != state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='OAuth state inválido')
    try:
        data = await google_exchange_code(code)
    except OAuthServiceError as exc:
        return RedirectResponse(
            f'/dashboard?oauth_error={quote(exc.user_message)}',
            status_code=status.HTTP_302_FOUND,
        )
    await save_oauth_account(
        db=db,
        user_id=user.id,
        provider=OAuthProvider.GOOGLE,
        access_token=data['access_token'],
        refresh_token=data.get('refresh_token'),
        expires_in=data.get('expires_in'),
        provider_user_id=data['provider_user_id'],
        scopes=data.get('scopes', ''),
    )
    await add_audit_log(db, user_id=user.id, action='oauth_connected', payload={'provider': 'google'})
    await db.commit()
    return RedirectResponse('/dashboard?connected=google', status_code=status.HTTP_302_FOUND)


@router.post('/twitch/disconnect')
async def twitch_disconnect(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    await require_csrf(request)
    account = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.user_id == user.id,
                OAuthAccount.provider == OAuthProvider.TWITCH,
            )
        )
    ).scalar_one_or_none()
    if account:
        await db.delete(account)
        await add_audit_log(db, user_id=user.id, action='oauth_disconnected', payload={'provider': 'twitch'})
        await db.commit()
    return RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)


@router.post('/google/disconnect')
async def google_disconnect(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    await require_csrf(request)
    account = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.user_id == user.id,
                OAuthAccount.provider == OAuthProvider.GOOGLE,
            )
        )
    ).scalar_one_or_none()
    if account:
        await db.delete(account)
        await add_audit_log(db, user_id=user.id, action='oauth_disconnected', payload={'provider': 'google'})
        await db.commit()
    return RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)

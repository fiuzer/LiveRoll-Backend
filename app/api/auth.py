import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_csrf_token, require_csrf
from app.db.session import get_db_session
from app.services.auth_service import (
    authenticate_user,
    create_social_user,
    create_user,
    get_user_by_email,
    get_user_by_identity,
    link_identity,
    user_exists,
)
from app.services.social_auth_service import (
    SocialAuthError,
    github_auth_authorize_url,
    github_auth_exchange_code,
    google_auth_authorize_url,
    google_auth_exchange_code,
)

router = APIRouter()


@router.get('/register')
async def register_page(request: Request):
    if request.session.get('user_id'):
        return RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)
    csrf = request.session.get('csrf_token') or generate_csrf_token()
    request.session['csrf_token'] = csrf
    response = request.app.state.templates.TemplateResponse(
        'auth/register.html',
        {'request': request, 'csrf_token': csrf},
    )
    response.set_cookie('csrf_token', csrf, secure=False, httponly=False, samesite='lax')
    return response


@router.post('/register')
async def register_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db_session),
):
    await require_csrf(request)
    if await user_exists(db, email):
        return request.app.state.templates.TemplateResponse(
            'auth/register.html',
            {'request': request, 'error': 'Email já cadastrado', 'csrf_token': request.session.get('csrf_token')},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = await create_user(db, email, password)
    await db.commit()
    request.session['user_id'] = user.id
    request.session['csrf_token'] = generate_csrf_token()
    response = RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)
    response.set_cookie('csrf_token', request.session['csrf_token'], secure=False, httponly=False, samesite='lax')
    return response


@router.get('/login')
async def login_page(request: Request):
    if request.session.get('user_id'):
        return RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)
    csrf = request.session.get('csrf_token') or generate_csrf_token()
    request.session['csrf_token'] = csrf
    oauth_error = request.query_params.get('oauth_error')
    response = request.app.state.templates.TemplateResponse(
        'auth/login.html',
        {'request': request, 'csrf_token': csrf, 'error': oauth_error},
    )
    response.set_cookie('csrf_token', csrf, secure=False, httponly=False, samesite='lax')
    return response


@router.post('/login')
async def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db_session),
):
    await require_csrf(request)
    user = await authenticate_user(db, email, password)
    if not user:
        return request.app.state.templates.TemplateResponse(
            'auth/login.html',
            {'request': request, 'error': 'Credenciais inválidas', 'csrf_token': request.session.get('csrf_token')},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    request.session['user_id'] = user.id
    request.session['csrf_token'] = generate_csrf_token()
    response = RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)
    response.set_cookie('csrf_token', request.session['csrf_token'], secure=False, httponly=False, samesite='lax')
    return response


@router.get('/auth/google/start')
async def google_auth_start(request: Request):
    state = secrets.token_urlsafe(24)
    request.session['oauth_state_google_auth'] = state
    return RedirectResponse(google_auth_authorize_url(state), status_code=status.HTTP_302_FOUND)


@router.get('/auth/google/callback')
async def google_auth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
):
    if request.session.get('oauth_state_google_auth') != state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='OAuth state inválido')

    try:
        data = await google_auth_exchange_code(code)
    except SocialAuthError as exc:
        return RedirectResponse(
            f'/login?oauth_error={quote(exc.user_message)}',
            status_code=status.HTTP_302_FOUND,
        )
    email = data.get('email')
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Conta Google sem e-mail')

    user = await get_user_by_identity(db, data['provider'], data['provider_user_id'])
    if user is None:
        user = await get_user_by_email(db, email)
        if user is None:
            user = await create_social_user(db, email)
        await link_identity(db, user.id, data['provider'], data['provider_user_id'], email)

    await db.commit()
    request.session['user_id'] = user.id
    request.session['csrf_token'] = generate_csrf_token()
    response = RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)
    response.set_cookie('csrf_token', request.session['csrf_token'], secure=False, httponly=False, samesite='lax')
    return response


@router.get('/auth/github/start')
async def github_auth_start(request: Request):
    state = secrets.token_urlsafe(24)
    request.session['oauth_state_github_auth'] = state
    return RedirectResponse(github_auth_authorize_url(state), status_code=status.HTTP_302_FOUND)


@router.get('/auth/github/callback')
async def github_auth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
):
    if request.session.get('oauth_state_github_auth') != state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='OAuth state inválido')

    try:
        data = await github_auth_exchange_code(code)
    except SocialAuthError as exc:
        return RedirectResponse(
            f'/login?oauth_error={quote(exc.user_message)}',
            status_code=status.HTTP_302_FOUND,
        )
    email = data.get('email')
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Conta GitHub sem e-mail verificado público',
        )

    user = await get_user_by_identity(db, data['provider'], data['provider_user_id'])
    if user is None:
        user = await get_user_by_email(db, email)
        if user is None:
            user = await create_social_user(db, email)
        await link_identity(db, user.id, data['provider'], data['provider_user_id'], email)

    await db.commit()
    request.session['user_id'] = user.id
    request.session['csrf_token'] = generate_csrf_token()
    response = RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)
    response.set_cookie('csrf_token', request.session['csrf_token'], secure=False, httponly=False, samesite='lax')
    return response


@router.post('/logout')
async def logout_action(request: Request):
    await require_csrf(request)
    request.session.clear()
    response = RedirectResponse('/login', status_code=status.HTTP_302_FOUND)
    response.delete_cookie('csrf_token')
    return response

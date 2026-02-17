import logging
import csv
import asyncio
import secrets
from io import StringIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import RateLimiter
from app.core.security import generate_csrf_token, require_csrf, sign_overlay_token
from app.db.redis_client import get_redis
from app.db.session import get_db_session
from app.models import Giveaway, OAuthAccount, OAuthProvider, Participant, Winner
from app.services.audit import add_audit_log
from app.services.dependencies import get_current_user, get_owned_giveaway
from app.services.giveaway_service import clear_participants, draw_winner, normalize_command
from app.services.oauth_service import decrypt_access_token, get_google_live_chat_id, validate_twitch_access_token
from app.services.realtime import build_giveaway_state, publish_control, publish_draw_started, publish_state
from app.services.youtube_utils import parse_youtube_video_id

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)


@router.get('/')
async def home(request: Request):
    if request.session.get('user_id'):
        return RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)
    return RedirectResponse('/login', status_code=status.HTTP_302_FOUND)


@router.get('/dashboard')
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    giveaways = (await db.execute(select(Giveaway).where(Giveaway.user_id == user.id).order_by(Giveaway.id.desc()))).scalars().all()
    oauth_accounts = (
        await db.execute(select(OAuthAccount).where(OAuthAccount.user_id == user.id))
    ).scalars().all()
    removed_invalid_twitch = False
    for acc in list(oauth_accounts):
        if acc.provider != OAuthProvider.TWITCH:
            continue
        token = decrypt_access_token(acc)
        is_valid = await validate_twitch_access_token(token)
        if is_valid is False:
            await db.delete(acc)
            removed_invalid_twitch = True

    if removed_invalid_twitch:
        await db.commit()
        oauth_accounts = (
            await db.execute(select(OAuthAccount).where(OAuthAccount.user_id == user.id))
        ).scalars().all()

    connected = {acc.provider.value for acc in oauth_accounts}
    oauth_error = request.query_params.get('oauth_error')
    create_error = request.query_params.get('create_error')
    csrf = request.session.get('csrf_token') or generate_csrf_token()
    request.session['csrf_token'] = csrf
    response = request.app.state.templates.TemplateResponse(
        'dashboard/index.html',
        {
            'request': request,
            'giveaways': giveaways,
            'connected': connected,
            'oauth_error': oauth_error,
            'create_error': create_error,
            'csrf_token': csrf,
            'default_command': settings.default_command,
        },
    )
    response.set_cookie('csrf_token', csrf, secure=False, httponly=False, samesite='lax')
    return response


@router.post('/giveaways/create', dependencies=[Depends(RateLimiter('giveaway_create', 20, 60))])
async def create_giveaway(
    request: Request,
    name: str = Form(...),
    command: str = Form(default='!participar'),
    youtube_video_id: str = Form(default=''),
    ticker_message: str = Form(default=''),
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    await require_csrf(request)
    parsed_video_id = parse_youtube_video_id(youtube_video_id)
    if youtube_video_id.strip() and not parsed_video_id:
        return RedirectResponse(
            f'/dashboard?create_error={quote("URL/ID do YouTube invalido. Cole a URL da live ou o ID do video.")}',
            status_code=status.HTTP_302_FOUND,
        )
    giveaway = Giveaway(
        user_id=user.id,
        name=name.strip(),
        command=normalize_command(command),
        youtube_video_id=parsed_video_id,
        ticker_message=ticker_message.strip() or None,
    )
    db.add(giveaway)
    await add_audit_log(db, user_id=user.id, giveaway_id=None, action='giveaway_created', payload={'name': giveaway.name})
    await db.commit()
    return RedirectResponse(f'/giveaways/{giveaway.id}', status_code=status.HTTP_302_FOUND)


@router.get('/giveaways/{giveaway_id}')
async def giveaway_detail(
    giveaway_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    giveaway = await get_owned_giveaway(giveaway_id, user, db)
    participants = (
        await db.execute(select(Participant).where(Participant.giveaway_id == giveaway_id).order_by(Participant.first_seen.desc()).limit(100))
    ).scalars().all()
    winners = (
        await db.execute(select(Winner).where(Winner.giveaway_id == giveaway_id).order_by(Winner.drawn_at.desc()).limit(10))
    ).scalars().all()
    winners_total = await db.scalar(select(func.count(Winner.id)).where(Winner.giveaway_id == giveaway_id))
    participants_count = await db.scalar(select(func.count(Participant.id)).where(Participant.giveaway_id == giveaway_id))
    overlay_token = sign_overlay_token(giveaway_id)
    warning = request.query_params.get('warning')
    ticker_default = giveaway.ticker_message or f'Sorteio {giveaway.name} rolando agora. Digite {giveaway.command}'
    csrf = request.session.get('csrf_token') or generate_csrf_token()
    request.session['csrf_token'] = csrf
    response = request.app.state.templates.TemplateResponse(
        'giveaways/detail.html',
        {
            'request': request,
            'giveaway': giveaway,
            'participants': participants,
            'participants_count': participants_count or 0,
            'winners': winners,
            'winners_total': winners_total or 0,
            'csrf_token': csrf,
            'overlay_token': overlay_token,
            'warning': warning,
            'ticker_default': ticker_default,
        },
    )
    response.set_cookie('csrf_token', csrf, secure=False, httponly=False, samesite='lax')
    return response


@router.post('/giveaways/{giveaway_id}/start', dependencies=[Depends(RateLimiter('giveaway_control', 60, 60))])
async def start_giveaway(
    giveaway_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user=Depends(get_current_user),
):
    await require_csrf(request)
    giveaway = await get_owned_giveaway(giveaway_id, user, db)
    giveaway.is_open = True
    warning = None

    google_acc = (
        await db.execute(
            select(OAuthAccount).where(OAuthAccount.user_id == user.id, OAuthAccount.provider == OAuthProvider.GOOGLE)
        )
    ).scalar_one_or_none()
    if google_acc and not giveaway.youtube_live_chat_id:
        try:
            token = decrypt_access_token(google_acc)
            discovered = await get_google_live_chat_id(token, giveaway.youtube_video_id)
            if discovered:
                giveaway.youtube_live_chat_id = discovered[0]
            else:
                warning = 'YouTube sem live ativa detectada. Sorteio abriu mesmo assim.'
        except Exception:
            logger.exception('youtube_live_detect_failed giveaway=%s user=%s', giveaway_id, user.id)
            warning = 'Falha ao consultar YouTube. Sorteio abriu mesmo assim.'

    await add_audit_log(db, user_id=user.id, giveaway_id=giveaway_id, action='giveaway_start')
    await db.commit()
    await publish_control(redis, 'start', giveaway_id, user.id)
    state = await build_giveaway_state(db, giveaway_id)
    await publish_state(redis, state)
    if warning:
        return RedirectResponse(f'/giveaways/{giveaway_id}?warning={warning}', status_code=status.HTTP_302_FOUND)
    return RedirectResponse(f'/giveaways/{giveaway_id}', status_code=status.HTTP_302_FOUND)


@router.post('/giveaways/{giveaway_id}/stop', dependencies=[Depends(RateLimiter('giveaway_control', 60, 60))])
async def stop_giveaway(
    giveaway_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user=Depends(get_current_user),
):
    await require_csrf(request)
    giveaway = await get_owned_giveaway(giveaway_id, user, db)
    giveaway.is_open = False
    await add_audit_log(db, user_id=user.id, giveaway_id=giveaway_id, action='giveaway_stop')
    await db.commit()
    await publish_control(redis, 'stop', giveaway_id, user.id)
    state = await build_giveaway_state(db, giveaway_id)
    await publish_state(redis, state)
    return RedirectResponse(f'/giveaways/{giveaway_id}', status_code=status.HTTP_302_FOUND)


@router.post('/giveaways/{giveaway_id}/clear', dependencies=[Depends(RateLimiter('giveaway_control', 60, 60))])
async def clear_giveaway(
    giveaway_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user=Depends(get_current_user),
):
    await require_csrf(request)
    await get_owned_giveaway(giveaway_id, user, db)
    removed = await clear_participants(db, giveaway_id)
    await add_audit_log(db, user_id=user.id, giveaway_id=giveaway_id, action='participants_clear', payload={'removed': removed})
    await db.commit()
    state = await build_giveaway_state(db, giveaway_id)
    await publish_state(redis, state)
    return RedirectResponse(f'/giveaways/{giveaway_id}', status_code=status.HTTP_302_FOUND)


@router.post('/giveaways/{giveaway_id}/draw', dependencies=[Depends(RateLimiter('giveaway_control', 60, 60))])
async def draw_giveaway(
    giveaway_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user=Depends(get_current_user),
):
    await require_csrf(request)
    giveaway = await get_owned_giveaway(giveaway_id, user, db)
    winner = await draw_winner(db, giveaway)
    if winner is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Sem participantes')
    draw_duration_ms = 3000 + secrets.randbelow(2001)
    await publish_draw_started(redis, giveaway_id, winner.display_name, draw_duration_ms)
    await asyncio.sleep(draw_duration_ms / 1000)
    await add_audit_log(
        db,
        user_id=user.id,
        giveaway_id=giveaway_id,
        action='winner_drawn',
        payload={'platform': winner.platform.value, 'display_name': winner.display_name},
    )
    await db.commit()
    state = await build_giveaway_state(db, giveaway_id)
    await publish_state(redis, state)
    return RedirectResponse(f'/giveaways/{giveaway_id}', status_code=status.HTTP_302_FOUND)


@router.post('/giveaways/{giveaway_id}/ticker-message', dependencies=[Depends(RateLimiter('giveaway_control', 60, 60))])
async def update_ticker_message(
    giveaway_id: int,
    request: Request,
    ticker_message: str = Form(default=''),
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    await require_csrf(request)
    giveaway = await get_owned_giveaway(giveaway_id, user, db)
    giveaway.ticker_message = ticker_message.strip() or None
    await add_audit_log(
        db,
        user_id=user.id,
        giveaway_id=giveaway_id,
        action='ticker_message_updated',
        payload={'ticker_message': giveaway.ticker_message},
    )
    await db.commit()
    return RedirectResponse(f'/giveaways/{giveaway_id}', status_code=status.HTTP_302_FOUND)


@router.post('/giveaways/{giveaway_id}/delete', dependencies=[Depends(RateLimiter('giveaway_control', 60, 60))])
async def delete_giveaway(
    giveaway_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user=Depends(get_current_user),
):
    await require_csrf(request)
    giveaway = await get_owned_giveaway(giveaway_id, user, db)
    await publish_control(redis, 'stop', giveaway_id, user.id)
    await add_audit_log(
        db,
        user_id=user.id,
        giveaway_id=giveaway_id,
        action='giveaway_deleted',
        payload={'name': giveaway.name},
    )
    await db.delete(giveaway)
    await db.commit()
    return RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)


@router.get('/giveaways/{giveaway_id}/participants')
async def list_participants(
    giveaway_id: int,
    format: str = 'json',
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    await get_owned_giveaway(giveaway_id, user, db)
    items = (
        await db.execute(select(Participant).where(Participant.giveaway_id == giveaway_id).order_by(Participant.display_name.asc()))
    ).scalars().all()

    if format.lower() == 'csv':
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['platform', 'platform_user_id', 'display_name'])
        for p in items:
            writer.writerow([p.platform.value, p.platform_user_id, p.display_name])
        csv_body = output.getvalue()
        headers = {'Content-Disposition': f'attachment; filename="participantes_giveaway_{giveaway_id}.csv"'}
        return Response(content=csv_body, media_type='text/csv; charset=utf-8', headers=headers)

    return [{'platform': p.platform.value, 'platform_user_id': p.platform_user_id, 'display_name': p.display_name} for p in items]


@router.get('/giveaways/{giveaway_id}/participants/latest')
async def latest_participant(
    giveaway_id: int,
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    await get_owned_giveaway(giveaway_id, user, db)
    participant = (
        await db.execute(
            select(Participant)
            .where(Participant.giveaway_id == giveaway_id)
            .order_by(Participant.last_seen.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not participant:
        return {'display_name': None, 'platform': None}
    return {'display_name': participant.display_name, 'platform': participant.platform.value}


@router.get('/demo')
async def demo_page(request: Request):
    return request.app.state.templates.TemplateResponse('overlay/demo.html', {'request': request})


@router.get('/giveaways/{giveaway_id}/winners')
async def winners_history(
    giveaway_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    giveaway = await get_owned_giveaway(giveaway_id, user, db)
    winners = (
        await db.execute(select(Winner).where(Winner.giveaway_id == giveaway_id).order_by(Winner.drawn_at.desc()))
    ).scalars().all()
    return request.app.state.templates.TemplateResponse(
        'giveaways/winners.html',
        {
            'request': request,
            'giveaway': giveaway,
            'winners': winners,
            'csrf_token': request.session.get('csrf_token'),
        },
    )





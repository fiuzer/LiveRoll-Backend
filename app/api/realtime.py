import json

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select

from app.db.redis_client import get_redis
from app.db.session import AsyncSessionLocal
from app.models import Giveaway
from app.services.realtime import EVENT_CHANNEL, build_giveaway_state

router = APIRouter()


@router.websocket('/ws/giveaways/{giveaway_id}')
async def giveaway_ws(
    websocket: WebSocket,
    giveaway_id: int,
    redis: Redis = Depends(get_redis),
):
    await websocket.accept()
    session = websocket.scope.get('session', {})
    user_id = session.get('user_id')
    if not user_id:
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        owned = await db.execute(select(Giveaway).where(Giveaway.id == giveaway_id, Giveaway.user_id == int(user_id)))
        if owned.scalar_one_or_none() is None:
            await websocket.close(code=4404)
            return
        state = await build_giveaway_state(db, giveaway_id)
    if state:
        await websocket.send_json({'type': 'state', 'state': state})

    pubsub = redis.pubsub()
    await pubsub.subscribe(EVENT_CHANNEL)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not msg:
                continue
            payload = json.loads(msg['data'])
            event_type = payload.get('type')
            if event_type == 'state':
                event_state = payload.get('state', {})
                if int(event_state.get('giveaway_id', 0)) != giveaway_id:
                    continue
                await websocket.send_json({'type': 'state', 'state': event_state})
            elif event_type == 'draw_started':
                if int(payload.get('giveaway_id', 0)) != giveaway_id:
                    continue
                await websocket.send_json(
                    {
                        'type': 'draw_started',
                        'giveaway_id': giveaway_id,
                        'winner_name': payload.get('winner_name'),
                        'duration_ms': int(payload.get('duration_ms', 4000)),
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(EVENT_CHANNEL)
        await pubsub.close()


@router.get('/overlay/{giveaway_id}')
async def overlay_default(giveaway_id: int, token: str):
    return RedirectResponse(f'/overlay/{giveaway_id}/banner?token={token}', status_code=302)


@router.get('/overlay/{giveaway_id}/banner')
async def overlay_banner_page(giveaway_id: int, token: str, request: Request):
    giveaway = await request.app.state.overlay_loader(giveaway_id, token)
    if not giveaway:
        return HTMLResponse('Invalid overlay token', status_code=401)
    return request.app.state.templates.TemplateResponse(
        'overlay/banner.html', {'request': request, 'giveaway_id': giveaway_id, 'token': token}
    )


@router.get('/overlay/{giveaway_id}/roulette')
async def overlay_roulette_page(giveaway_id: int, token: str, request: Request):
    giveaway = await request.app.state.overlay_loader(giveaway_id, token)
    if not giveaway:
        return HTMLResponse('Invalid overlay token', status_code=401)
    return request.app.state.templates.TemplateResponse(
        'overlay/roulette.html', {'request': request, 'giveaway_id': giveaway_id, 'token': token}
    )


async def _overlay_ws_stream(
    websocket: WebSocket,
    giveaway_id: int,
    token: str,
    redis: Redis,
):
    giveaway = await websocket.app.state.overlay_loader(giveaway_id, token)
    if not giveaway:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    async with AsyncSessionLocal() as db:
        state = await build_giveaway_state(db, giveaway_id)
    if state:
        await websocket.send_json({'type': 'state', 'state': state})

    pubsub = redis.pubsub()
    await pubsub.subscribe(EVENT_CHANNEL)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not msg:
                continue
            payload = json.loads(msg['data'])
            event_type = payload.get('type')
            if event_type == 'state':
                event_state = payload.get('state', {})
                if int(event_state.get('giveaway_id', 0)) != giveaway_id:
                    continue
                await websocket.send_json({'type': 'state', 'state': event_state})
            elif event_type == 'draw_started':
                if int(payload.get('giveaway_id', 0)) != giveaway_id:
                    continue
                await websocket.send_json(
                    {
                        'type': 'draw_started',
                        'giveaway_id': giveaway_id,
                        'winner_name': payload.get('winner_name'),
                        'duration_ms': int(payload.get('duration_ms', 4000)),
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(EVENT_CHANNEL)
        await pubsub.close()


@router.websocket('/ws/overlay/{giveaway_id}')
async def overlay_ws_legacy(
    websocket: WebSocket,
    giveaway_id: int,
    token: str,
    redis: Redis = Depends(get_redis),
):
    await _overlay_ws_stream(websocket, giveaway_id, token, redis)


@router.websocket('/ws/overlay/banner/{giveaway_id}')
async def overlay_ws_banner(
    websocket: WebSocket,
    giveaway_id: int,
    token: str,
    redis: Redis = Depends(get_redis),
):
    await _overlay_ws_stream(websocket, giveaway_id, token, redis)


@router.websocket('/ws/overlay/roulette/{giveaway_id}')
async def overlay_ws_roulette(
    websocket: WebSocket,
    giveaway_id: int,
    token: str,
    redis: Redis = Depends(get_redis),
):
    await _overlay_ws_stream(websocket, giveaway_id, token, redis)

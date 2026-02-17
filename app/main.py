import asyncio
from contextlib import suppress
from datetime import timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.api import auth, client, dashboard, oauth, ops, realtime
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import parse_overlay_token
from app.db.session import AsyncSessionLocal
from app.models import Giveaway
from app.workers.chat_worker import worker_loop

BRAZIL_TZ = ZoneInfo('America/Sao_Paulo')


def format_brt_datetime(value) -> str:
    if value is None:
        return '-'
    dt = value
    if getattr(dt, 'tzinfo', None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(BRAZIL_TZ)
    return local_dt.strftime('%d/%m/%Y %H:%M')


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_wrapper(message):
            if message['type'] == 'http.response.start':
                headers = message.setdefault('headers', [])
                headers.extend(
                    [
                        (b'x-frame-options', b'SAMEORIGIN'),
                        (b'x-content-type-options', b'nosniff'),
                        (b'referrer-policy', b'strict-origin-when-cross-origin'),
                    ]
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(title=settings.app_name)
    app.mount('/static', StaticFiles(directory='app/static'), name='static')

    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=settings.session_max_age_seconds)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(',') if origin.strip()],
        allow_credentials=True,
        allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        allow_headers=['*'],
    )
    app.add_middleware(SecurityHeadersMiddleware)

    templates = Jinja2Templates(directory='app/templates')
    templates.env.filters['br_datetime'] = format_brt_datetime
    templates.env.globals['public_frontend_url'] = settings.public_frontend_url
    app.state.templates = templates
    app.state.embedded_worker_task = None

    async def overlay_loader(giveaway_id: int, token: str):
        parsed = parse_overlay_token(token)
        if parsed != giveaway_id:
            return None
        async with AsyncSessionLocal() as db:
            giveaway = await db.get(Giveaway, giveaway_id)
            return giveaway

    app.state.overlay_loader = overlay_loader

    @app.on_event('startup')
    async def startup_embedded_worker():
        if settings.run_embedded_worker:
            app.state.embedded_worker_task = asyncio.create_task(worker_loop())

    @app.on_event('shutdown')
    async def shutdown_embedded_worker():
        task = app.state.embedded_worker_task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app.include_router(auth.router)
    app.include_router(client.router)
    app.include_router(oauth.router)
    app.include_router(dashboard.router)
    app.include_router(realtime.router)
    app.include_router(ops.router)

    @app.get('/ping')
    async def ping():
        return {'pong': True}

    @app.get('/app')
    async def app_redirect(request: Request):
        return RedirectResponse('/dashboard')

    return app


app = create_app()

import asyncio
import json
import logging
from contextlib import suppress

import httpx
import websockets
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import get_settings
from app.db.redis_client import redis_client
from app.db.session import AsyncSessionLocal
from app.models import Giveaway, OAuthProvider, Platform
from app.services.audit import add_audit_log
from app.services.giveaway_service import add_or_refresh_participant, normalize_command
from app.services.oauth_service import decrypt_access_token, get_google_live_chat_id, get_oauth_account
from app.services.realtime import build_giveaway_state, publish_state

logger = logging.getLogger(__name__)
settings = get_settings()


class GiveawayRunner:
    def __init__(self, giveaway_id: int):
        self.giveaway_id = giveaway_id
        self.tasks: list[asyncio.Task] = []
        self.stop_event = asyncio.Event()

    async def start(self) -> None:
        if self.tasks:
            return
        self.stop_event.clear()
        self.tasks = [
            asyncio.create_task(self._run_twitch(), name=f'twitch-{self.giveaway_id}'),
            asyncio.create_task(self._run_youtube(), name=f'youtube-{self.giveaway_id}'),
        ]
        logger.info('Runner started for giveaway=%s', self.giveaway_id)

    async def stop(self) -> None:
        if not self.tasks:
            return
        self.stop_event.set()
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError):
                await task
        self.tasks = []
        logger.info('Runner stopped for giveaway=%s', self.giveaway_id)

    async def _get_runtime_data(self) -> dict | None:
        async with AsyncSessionLocal() as db:
            giveaway_result = await db.execute(select(Giveaway).where(Giveaway.id == self.giveaway_id))
            giveaway = giveaway_result.scalar_one_or_none()
            if not giveaway:
                return None
            twitch = await get_oauth_account(db, giveaway.user_id, OAuthProvider.TWITCH)
            google = await get_oauth_account(db, giveaway.user_id, OAuthProvider.GOOGLE)
            return {'giveaway': giveaway, 'twitch': twitch, 'google': google}

    async def _run_twitch(self) -> None:
        backoff = 1
        while not self.stop_event.is_set():
            try:
                data = await self._get_runtime_data()
                if not data or not data['twitch']:
                    await asyncio.sleep(5)
                    continue
                giveaway = data['giveaway']
                token = decrypt_access_token(data['twitch'])
                channel_login = await self._fetch_twitch_login(token)
                if not channel_login:
                    await asyncio.sleep(10)
                    continue

                cmd = normalize_command(giveaway.command)
                await self._consume_twitch_ws(token, channel_login, cmd)
                backoff = 1
            except Exception as exc:
                logger.warning('Twitch runner error giveaway=%s error=%s', self.giveaway_id, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _consume_twitch_ws(self, token: str, channel_login: str, cmd: str) -> None:
        ws_url = 'wss://irc-ws.chat.twitch.tv:443'
        async with websockets.connect(ws_url, open_timeout=20, ping_interval=30, ping_timeout=30) as ws:
            await ws.send('CAP REQ :twitch.tv/tags twitch.tv/commands')
            await ws.send(f'PASS oauth:{token}')
            await ws.send(f'NICK {channel_login}')
            await ws.send(f'JOIN #{channel_login}')

            while not self.stop_event.is_set():
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
                message = raw.decode(errors='ignore').strip() if isinstance(raw, bytes) else str(raw).strip()
                if message.startswith('PING'):
                    await ws.send(message.replace('PING', 'PONG', 1))
                    continue
                parsed = self._parse_twitch_privmsg(message)
                if not parsed:
                    continue
                if parsed['text'].strip().lower() == cmd:
                    await self._register_participant(
                        platform=Platform.TWITCH,
                        platform_user_id=parsed['user_id'],
                        display_name=parsed['display_name'],
                    )

    async def _fetch_twitch_login(self, token: str) -> str | None:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                'https://api.twitch.tv/helix/users',
                headers={
                    'Authorization': f'Bearer {token}',
                    'Client-Id': settings.twitch_client_id,
                },
            )
            if resp.status_code >= 400:
                return None
            items = resp.json().get('data', [])
            if not items:
                return None
            return items[0].get('login')

    def _parse_twitch_privmsg(self, raw: str) -> dict | None:
        if 'PRIVMSG' not in raw:
            return None
        try:
            tags, remainder = raw.split(' ', 1)
            user_id = ''
            display_name = ''
            if tags.startswith('@'):
                tag_dict = dict(part.split('=', 1) if '=' in part else (part, '') for part in tags[1:].split(';'))
                user_id = tag_dict.get('user-id', '')
                display_name = tag_dict.get('display-name', '')
            if not display_name and '!' in remainder and remainder.startswith(':'):
                display_name = remainder[1:].split('!', 1)[0]
            parts = remainder.split(' :', 1)
            if len(parts) != 2:
                return None
            text = parts[1]
            return {
                'user_id': user_id or display_name or 'unknown',
                'display_name': display_name or 'twitch-user',
                'text': text,
            }
        except Exception:
            return None

    async def _run_youtube(self) -> None:
        backoff = settings.youtube_polling_floor_seconds
        page_token = None
        while not self.stop_event.is_set():
            try:
                data = await self._get_runtime_data()
                if not data or not data['google']:
                    await asyncio.sleep(5)
                    continue
                giveaway = data['giveaway']
                token = decrypt_access_token(data['google'])
                chat_id = giveaway.youtube_live_chat_id
                if not chat_id:
                    discovered = await get_google_live_chat_id(token, giveaway.youtube_video_id)
                    if discovered:
                        chat_id, _ = discovered
                        async with AsyncSessionLocal() as db:
                            db_giveaway = await db.get(Giveaway, self.giveaway_id)
                            if db_giveaway:
                                db_giveaway.youtube_live_chat_id = chat_id
                                await db.commit()
                    else:
                        await asyncio.sleep(10)
                        continue

                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        'https://www.googleapis.com/youtube/v3/liveChat/messages',
                        params={
                            'part': 'snippet,authorDetails',
                            'liveChatId': chat_id,
                            'maxResults': 200,
                            'pageToken': page_token,
                        },
                        headers={'Authorization': f'Bearer {token}'},
                    )
                    if resp.status_code in {403, 429, 500, 503}:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, settings.youtube_backoff_cap_seconds)
                        continue
                    resp.raise_for_status()
                    data_json = resp.json()
                    page_token = data_json.get('nextPageToken')
                    interval_ms = data_json.get('pollingIntervalMillis', 3000)
                    cmd = normalize_command(giveaway.command)
                    for item in data_json.get('items', []):
                        text = item.get('snippet', {}).get('displayMessage', '').strip().lower()
                        if text != cmd:
                            continue
                        author = item.get('authorDetails', {})
                        channel_id = author.get('channelId', '')
                        display_name = author.get('displayName', 'youtube-user')
                        if not channel_id:
                            continue
                        await self._register_participant(
                            platform=Platform.YOUTUBE,
                            platform_user_id=channel_id,
                            display_name=display_name,
                        )
                    backoff = settings.youtube_polling_floor_seconds
                    await asyncio.sleep(max(interval_ms / 1000.0, settings.youtube_polling_floor_seconds))
            except Exception as exc:
                logger.warning('YouTube runner error giveaway=%s error=%s', self.giveaway_id, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, settings.youtube_backoff_cap_seconds)

    async def _register_participant(self, platform: Platform, platform_user_id: str, display_name: str) -> None:
        async with AsyncSessionLocal() as db:
            giveaway = await db.get(Giveaway, self.giveaway_id)
            if not giveaway or not giveaway.is_open:
                return
            _, created = await add_or_refresh_participant(
                db,
                giveaway_id=self.giveaway_id,
                platform=platform,
                platform_user_id=platform_user_id,
                display_name=display_name,
            )
            await add_audit_log(
                db,
                user_id=giveaway.user_id,
                giveaway_id=self.giveaway_id,
                action='participant_seen',
                payload={'platform': platform.value, 'platform_user_id': platform_user_id, 'created': created},
            )
            await db.commit()
            state = await build_giveaway_state(db, self.giveaway_id)
            await publish_state(redis_client, state)


class RunnerManager:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.runners: dict[int, GiveawayRunner] = {}

    async def start_giveaway(self, giveaway_id: int) -> None:
        runner = self.runners.get(giveaway_id)
        if runner is None:
            runner = GiveawayRunner(giveaway_id)
            self.runners[giveaway_id] = runner
        await runner.start()

    async def stop_giveaway(self, giveaway_id: int) -> None:
        runner = self.runners.get(giveaway_id)
        if not runner:
            return
        await runner.stop()
        self.runners.pop(giveaway_id, None)

    async def shutdown(self) -> None:
        ids = list(self.runners.keys())
        for giveaway_id in ids:
            await self.stop_giveaway(giveaway_id)


async def worker_loop() -> None:
    manager = RunnerManager(redis_client)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe('giveaway:control')
    logger.info('Worker subscribed to giveaway:control')
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message:
                await asyncio.sleep(0.1)
                continue
            payload = json.loads(message['data'])
            action = payload.get('type')
            giveaway_id = int(payload['giveaway_id'])
            if action == 'start':
                await manager.start_giveaway(giveaway_id)
            elif action in {'stop', 'clear'}:
                await manager.stop_giveaway(giveaway_id)
    finally:
        await manager.shutdown()
        await pubsub.unsubscribe('giveaway:control')
        await pubsub.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        pass

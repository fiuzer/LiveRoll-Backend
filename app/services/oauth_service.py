from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_value, encrypt_value
from app.models import OAuthAccount, OAuthProvider

settings = get_settings()


class OAuthServiceError(Exception):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


def twitch_authorize_url(state: str) -> str:
    query = urlencode(
        {
            'client_id': settings.twitch_client_id,
            'redirect_uri': settings.twitch_redirect_uri,
            'response_type': 'code',
            'scope': 'chat:read',
            'state': state,
        }
    )
    return f'https://id.twitch.tv/oauth2/authorize?{query}'


def google_authorize_url(state: str) -> str:
    query = urlencode(
        {
            'client_id': settings.google_client_id,
            'redirect_uri': settings.google_redirect_uri,
            'response_type': 'code',
            'scope': 'https://www.googleapis.com/auth/youtube.readonly',
            'access_type': 'offline',
            'include_granted_scopes': 'true',
            'prompt': 'consent',
            'state': state,
        }
    )
    return f'https://accounts.google.com/o/oauth2/v2/auth?{query}'


async def save_oauth_account(
    db: AsyncSession,
    user_id: int,
    provider: OAuthProvider,
    access_token: str,
    refresh_token: str | None,
    provider_user_id: str,
    expires_in: int | None,
    scopes: str,
) -> OAuthAccount:
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user_id,
            OAuthAccount.provider == provider,
        )
    )
    account = result.scalar_one_or_none()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in else None
    )
    if account is None:
        account = OAuthAccount(
            user_id=user_id,
            provider=provider,
            access_token_enc=encrypt_value(access_token),
            refresh_token_enc=encrypt_value(refresh_token) if refresh_token else None,
            provider_user_id=provider_user_id,
            expires_at=expires_at,
            scopes=scopes,
        )
        db.add(account)
    else:
        account.access_token_enc = encrypt_value(access_token)
        if refresh_token:
            account.refresh_token_enc = encrypt_value(refresh_token)
        account.provider_user_id = provider_user_id
        account.expires_at = expires_at
        account.scopes = scopes
    await db.flush()
    return account


async def get_oauth_account(db: AsyncSession, user_id: int, provider: OAuthProvider) -> OAuthAccount | None:
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user_id,
            OAuthAccount.provider == provider,
        )
    )
    return result.scalar_one_or_none()


async def twitch_exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            'https://id.twitch.tv/oauth2/token',
            params={
                'client_id': settings.twitch_client_id,
                'client_secret': settings.twitch_client_secret,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': settings.twitch_redirect_uri,
            },
        )
        response.raise_for_status()
        token_data = response.json()

        user_resp = await client.get(
            'https://api.twitch.tv/helix/users',
            headers={
                'Authorization': f"Bearer {token_data['access_token']}",
                'Client-Id': settings.twitch_client_id,
            },
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()['data'][0]

    return {
        'access_token': token_data['access_token'],
        'refresh_token': token_data.get('refresh_token'),
        'expires_in': token_data.get('expires_in'),
        'provider_user_id': user_data['id'],
        'scopes': ' '.join(token_data.get('scope', [])),
    }


async def google_exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            'https://oauth2.googleapis.com/token',
            data={
                'code': code,
                'client_id': settings.google_client_id,
                'client_secret': settings.google_client_secret,
                'redirect_uri': settings.google_redirect_uri,
                'grant_type': 'authorization_code',
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        response.raise_for_status()
        token_data = response.json()

        me_resp = await client.get(
            'https://www.googleapis.com/youtube/v3/channels',
            params={'part': 'id', 'mine': 'true'},
            headers={'Authorization': f"Bearer {token_data['access_token']}"},
        )
        if me_resp.status_code >= 400:
            message = 'Falha ao acessar YouTube API. Verifique API habilitada e usuário de teste no Google.'
            try:
                payload = me_resp.json()
                reason = payload.get('error', {}).get('errors', [{}])[0].get('reason', '')
                if reason == 'accessNotConfigured':
                    message = 'YouTube Data API v3 não está habilitada no projeto Google.'
                elif reason == 'youtubeSignupRequired':
                    message = 'Esta conta Google não possui canal do YouTube ativo.'
                elif reason == 'insufficientPermissions':
                    message = 'Permissões insuficientes. Reconecte com escopo do YouTube.'
            except Exception:
                pass
            raise OAuthServiceError(message)

        items = me_resp.json().get('items', [])
        if not items:
            raise OAuthServiceError('Nenhum canal YouTube encontrado para esta conta.')
        channel_id = items[0]['id']

    return {
        'access_token': token_data['access_token'],
        'refresh_token': token_data.get('refresh_token'),
        'expires_in': token_data.get('expires_in'),
        'provider_user_id': channel_id,
        'scopes': token_data.get('scope', ''),
    }


async def get_google_live_chat_id(access_token: str, video_id: str | None = None) -> tuple[str, str] | None:
    async with httpx.AsyncClient(timeout=20) as client:
        if video_id:
            resp = await client.get(
                'https://www.googleapis.com/youtube/v3/videos',
                params={'part': 'liveStreamingDetails,snippet', 'id': video_id},
                headers={'Authorization': f'Bearer {access_token}'},
            )
            if resp.status_code >= 400:
                return None
            items = resp.json().get('items', [])
            if not items:
                return None
            live_chat_id = items[0].get('liveStreamingDetails', {}).get('activeLiveChatId')
            title = items[0].get('snippet', {}).get('title', video_id)
            if not live_chat_id:
                return None
            return live_chat_id, title

        me_resp = await client.get(
            'https://www.googleapis.com/youtube/v3/channels',
            params={'part': 'id', 'mine': 'true'},
            headers={'Authorization': f'Bearer {access_token}'},
        )
        if me_resp.status_code >= 400:
            return None
        me_items = me_resp.json().get('items', [])
        if not me_items:
            return None
        channel_id = me_items[0].get('id')
        if not channel_id:
            return None

        search_resp = await client.get(
            'https://www.googleapis.com/youtube/v3/search',
            params={
                'part': 'id,snippet',
                'channelId': channel_id,
                'eventType': 'live',
                'type': 'video',
                'maxResults': 1,
            },
            headers={'Authorization': f'Bearer {access_token}'},
        )
        if search_resp.status_code >= 400:
            return None
        items = search_resp.json().get('items', [])
        if not items:
            return None
        vid = items[0]['id']['videoId']

        video_resp = await client.get(
            'https://www.googleapis.com/youtube/v3/videos',
            params={'part': 'liveStreamingDetails,snippet', 'id': vid},
            headers={'Authorization': f'Bearer {access_token}'},
        )
        if video_resp.status_code >= 400:
            return None
        video_items = video_resp.json().get('items', [])
        if not video_items:
            return None
        live_chat_id = video_items[0].get('liveStreamingDetails', {}).get('activeLiveChatId')
        title = video_items[0].get('snippet', {}).get('title', vid)
        if not live_chat_id:
            return None
        return live_chat_id, title


def decrypt_access_token(account: OAuthAccount) -> str:
    return decrypt_value(account.access_token_enc)


async def validate_twitch_access_token(access_token: str) -> bool | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                'https://id.twitch.tv/oauth2/validate',
                headers={'Authorization': f'OAuth {access_token}'},
            )
        if response.status_code == 200:
            return True
        if response.status_code in (400, 401):
            return False
        return None
    except Exception:
        return None

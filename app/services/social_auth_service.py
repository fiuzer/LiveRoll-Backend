from urllib.parse import urlencode

import httpx

from app.core.config import get_settings

settings = get_settings()


def google_auth_authorize_url(state: str) -> str:
    query = urlencode(
        {
            'client_id': settings.google_auth_client_id,
            'redirect_uri': settings.google_auth_redirect_uri,
            'response_type': 'code',
            'scope': 'openid email profile',
            'access_type': 'offline',
            'prompt': 'consent',
            'state': state,
        }
    )
    return f'https://accounts.google.com/o/oauth2/v2/auth?{query}'


def github_auth_authorize_url(state: str) -> str:
    query = urlencode(
        {
            'client_id': settings.github_auth_client_id,
            'redirect_uri': settings.github_auth_redirect_uri,
            'scope': 'read:user user:email',
            'state': state,
        }
    )
    return f'https://github.com/login/oauth/authorize?{query}'


async def google_auth_exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(
            'https://oauth2.googleapis.com/token',
            data={
                'code': code,
                'client_id': settings.google_auth_client_id,
                'client_secret': settings.google_auth_client_secret,
                'redirect_uri': settings.google_auth_redirect_uri,
                'grant_type': 'authorization_code',
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()['access_token']

        user_resp = await client.get(
            'https://openidconnect.googleapis.com/v1/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()

    return {
        'provider': 'google_auth',
        'provider_user_id': user_data['sub'],
        'email': user_data.get('email'),
    }


async def github_auth_exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(
            'https://github.com/login/oauth/access_token',
            data={
                'client_id': settings.github_auth_client_id,
                'client_secret': settings.github_auth_client_secret,
                'code': code,
                'redirect_uri': settings.github_auth_redirect_uri,
            },
            headers={'Accept': 'application/json'},
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()['access_token']

        user_resp = await client.get(
            'https://api.github.com/user',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/vnd.github+json',
            },
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()

        email_resp = await client.get(
            'https://api.github.com/user/emails',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/vnd.github+json',
            },
        )
        email_resp.raise_for_status()
        emails = email_resp.json()

    primary_verified = next(
        (e for e in emails if e.get('primary') and e.get('verified')),
        None,
    )
    fallback_verified = next((e for e in emails if e.get('verified')), None)
    chosen_email = (primary_verified or fallback_verified or {}).get('email')

    return {
        'provider': 'github_auth',
        'provider_user_id': str(user_data['id']),
        'email': chosen_email,
    }

from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, status
from itsdangerous import URLSafeTimedSerializer
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=['pbkdf2_sha256'], deprecated='auto')


def hash_password(raw_password: str) -> str:
    return pwd_context.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    return pwd_context.verify(raw_password, password_hash)


def get_serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.secret_key, salt='roleta-session')


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def require_csrf(request: Request) -> None:
    settings = get_settings()
    if request.method in {'GET', 'HEAD', 'OPTIONS'}:
        return
    session_token = request.session.get('csrf_token')
    provided = request.headers.get(settings.csrf_header_name) or request.cookies.get('csrf_token')
    if not provided and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        form = await request.form()
        provided = form.get('csrf_token')
    if not session_token or not provided or not hmac.compare_digest(session_token, provided):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='CSRF validation failed')


def get_fernet() -> Fernet:
    settings = get_settings()
    digest = hashlib.sha256(settings.token_encryption_key.encode('utf-8')).digest()
    return Fernet(urlsafe_b64encode(digest))


def encrypt_value(value: str) -> str:
    return get_fernet().encrypt(value.encode('utf-8')).decode('utf-8')


def decrypt_value(value: str) -> str:
    return get_fernet().decrypt(value.encode('utf-8')).decode('utf-8')


def sign_overlay_token(giveaway_id: int) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.overlay_token_ttl_seconds)
    payload = {'giveaway_id': giveaway_id, 'exp': int(expires.timestamp())}
    return get_serializer().dumps(payload, salt='overlay-token')


def parse_overlay_token(token: str) -> int | None:
    settings = get_settings()
    try:
        data = get_serializer().loads(token, max_age=settings.overlay_token_ttl_seconds, salt='overlay-token')
    except Exception:
        return None
    if datetime.now(timezone.utc).timestamp() > int(data.get('exp', 0)):
        return None
    return int(data['giveaway_id'])

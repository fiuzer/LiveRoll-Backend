from urllib.parse import parse_qs, urlparse


def parse_youtube_video_id(raw: str | None) -> str | None:
    if raw is None:
        return None

    value = raw.strip()
    if not value:
        return None

    # fallback: already a probable video id
    if '://' not in value and '/' not in value and len(value) >= 6:
        return value

    try:
        parsed = urlparse(value)
    except Exception:
        return None

    host = (parsed.netloc or '').lower()
    path = (parsed.path or '').strip('/')

    if 'youtu.be' in host:
        first = path.split('/')[0] if path else ''
        return first or None

    if 'youtube.com' in host:
        if path == 'watch':
            query = parse_qs(parsed.query)
            return (query.get('v') or [None])[0]

        if path.startswith('live/'):
            return path.split('/', 1)[1] or None

        if path.startswith('shorts/'):
            return path.split('/', 1)[1] or None

        if path.startswith('embed/'):
            return path.split('/', 1)[1] or None

    return None

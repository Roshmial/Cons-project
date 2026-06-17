import json
import os
import sys

from telegram_web_auth import DEFAULT_TTL_MINUTES, MAX_TTL_MINUTES, _base_url, _iso, _normalize_profile, _now_utc, store, _public_view
from datetime import timedelta
import secrets


def main() -> int:
    profile = _normalize_profile(sys.argv[1] if len(sys.argv) > 1 else 'profile_private')
    ttl_minutes = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TTL_MINUTES
    ttl_minutes = max(1, min(ttl_minutes, MAX_TTL_MINUTES))
    token = secrets.token_urlsafe(24)
    now = _now_utc()
    payload = {
        'profile': profile,
        'status': 'ready',
        'created_at': _iso(now),
        'updated_at': _iso(now),
        'expires_at': _iso(now + timedelta(minutes=ttl_minutes)),
    }
    store.put(token, payload)
    print(json.dumps(_public_view(token, payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

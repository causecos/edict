"""三省六部 · 簡易 JWT 認證模塊（零外部依賴）。

使用 Python stdlib 實現：
- 密碼哈希: hashlib.pbkdf2_hmac (SHA-256, 100k iterations)
- Token: HMAC-SHA256 籤名的 Base64 JSON
- 配置存儲: data/auth.json

用法:
  首次運行時通過 /api/auth/setup 設置密碼
  後續通過 /api/auth/login 獲取 token
  API 請求通過 Cookie 或 Authorization header 攜帶 token
"""

import base64
import hashlib
import hmac
import json
import pathlib
import secrets
import time

# Token 有效期 24 小時
TOKEN_TTL = 24 * 60 * 60

# auth.json 存儲路徑（由外部在 server.py 初始化時設置）
_auth_file: pathlib.Path | None = None
_secret_key: bytes | None = None


def init(data_dir: pathlib.Path):
    """初始化認證模塊。"""
    global _auth_file, _secret_key
    _auth_file = data_dir / 'auth.json'
    # 每次啓動生成新的籤名密鑰（重啓後舊 token 失效，這是安全特性）
    _secret_key = secrets.token_bytes(32)


def is_configured() -> bool:
    """是否已設置密碼。"""
    if not _auth_file or not _auth_file.exists():
        return False
    try:
        cfg = json.loads(_auth_file.read_text(encoding='utf-8'))
        return bool(cfg.get('password_hash'))
    except Exception:
        return False


def is_enabled() -> bool:
    """認證是否啓用。僅當 auth.json 存在且配置了密碼時啓用。"""
    return is_configured()


def setup_password(password: str) -> dict:
    """首次設置密碼。如已設置則拒絕。"""
    if not _auth_file:
        return {'ok': False, 'error': '認證模塊未初始化'}
    if is_configured():
        return {'ok': False, 'error': '密碼已設置，如需重置請刪除 data/auth.json'}
    if len(password) < 4:
        return {'ok': False, 'error': '密碼至少 4 個字符'}

    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt.encode('utf-8'), 100_000
    ).hex()

    cfg = {'password_hash': pw_hash, 'salt': salt}
    _auth_file.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    return {'ok': True, 'message': '密碼已設置'}


def verify_password(password: str) -> bool:
    """校驗密碼。"""
    if not _auth_file or not _auth_file.exists():
        return False
    try:
        cfg = json.loads(_auth_file.read_text(encoding='utf-8'))
    except Exception:
        return False
    salt = cfg.get('salt', '')
    stored_hash = cfg.get('password_hash', '')
    if not salt or not stored_hash:
        return False
    computed = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt.encode('utf-8'), 100_000
    ).hex()
    return hmac.compare_digest(computed, stored_hash)


def create_token() -> str:
    """創建 JWT-like token。"""
    if not _secret_key:
        raise RuntimeError('Auth not initialized')
    payload = {
        'iat': int(time.time()),
        'exp': int(time.time()) + TOKEN_TTL,
        'jti': secrets.token_hex(8),
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip('=')
    sig = hmac.new(_secret_key, payload_b64.encode(), hashlib.sha256).hexdigest()
    return f'{payload_b64}.{sig}'


def verify_token(token: str) -> bool:
    """驗證 token 籤名和有效期。"""
    if not _secret_key or not token:
        return False
    parts = token.split('.')
    if len(parts) != 2:
        return False
    payload_b64, sig = parts
    expected_sig = hmac.new(_secret_key, payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False
    # 解碼 payload 檢查過期
    try:
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return False
    if payload.get('exp', 0) < time.time():
        return False
    return True


def extract_token(headers) -> str | None:
    """從請求頭中提取 token (Authorization header 或 Cookie)。"""
    # Authorization: Bearer <token>
    auth_header = headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:].strip()
    # Cookie: edict_token=<token>
    cookie = headers.get('Cookie', '')
    for part in cookie.split(';'):
        part = part.strip()
        if part.startswith('edict_token='):
            return part[len('edict_token='):]
    return None


# 不需要認證的路徑白名單
_PUBLIC_PATHS = frozenset({
    '/healthz',
    '/api/auth/login',
    '/api/auth/setup',
    '/api/auth/status',
})

# 公開的路徑前綴（靜態資源）
_PUBLIC_PREFIXES = ('/_assets/', '/assets/')


def requires_auth(path: str) -> bool:
    """判斷該路徑是否需要認證。"""
    if not is_enabled():
        return False
    # 靜態頁面和資源不攔截
    if path in _PUBLIC_PATHS:
        return False
    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return False
    # dashboard 首頁不攔截（前端自己處理重定向到登錄）
    if path in ('', '/', '/dashboard', '/dashboard.html'):
        return False
    return True

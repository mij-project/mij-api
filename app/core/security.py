# app/core/security.py
from passlib.context import CryptContext
from app.core.config import settings
import secrets, jwt, httpx, os, datetime as dt, time

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12

REGION = os.getenv('AWS_DEFAULT_REGION')
USER_POOL_ID = os.getenv('USER_POOL_ID')
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
AUD = os.getenv('AUD')
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
_cache = {"jwks": None, "exp": 0}

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    """
    パスワードをハッシュ化する

    Args:
        plain: 平文のパスワード
    """
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    """
    パスワードを検証する

    Args:
        plain: 平文のパスワード
        hashed: ハッシュ化されたパスワード
    """
    return pwd_context.verify(plain, hashed)

def now_utc() -> dt.datetime:
    """
    現在のUTC時刻を取得する
    """
    return dt.datetime.now(dt.timezone.utc)

def create_access_token(sub: str) -> str:
    """
    アクセストークンを作成する

    Args:
        sub (str): ユーザーID

    Returns:
        str: アクセストークン
    """
    iat = now_utc()
    exp = iat + dt.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MIN)
    payload = {"sub": sub, "iat": iat, "exp": exp, "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(sub: str) -> str:
    """
    リフレッシュトークンを作成する

    Args:
        sub (str): ユーザーID

    Returns:
        str: リフレッシュトークン
    """
    iat = now_utc()
    exp = iat + dt.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": sub, "iat": iat, "exp": exp, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    """
    トークンをデコードする

    Args:
        token (str): トークン

    Returns:
        dict: デコードされたトークン
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])

def new_csrf_token() -> str:
    """
    新しいCSRFトークンを生成する

    Returns:
        str: 新しいCSRFトークン
    """
    return secrets.token_urlsafe(16)

def _get_jwks():
    """
    JWKSを取得する
    """
    now = time.time()
    if _cache["jwks"] and now < _cache["exp"]:
        return _cache["jwks"]
    _cache["jwks"] = httpx.get(JWKS_URL, timeout=5).json()
    _cache["exp"] = now + 3600
    return _cache["jwks"]

def verify_id_token(id_token: str):
    """
    IDトークンを検証する

    Args:
        id_token (str): IDトークン

    Returns:
        dict: デコードされたトークン
    """
    header = jwt.get_unverified_header(id_token)
    jwks = _get_jwks()
    key = next(k for k in jwks["keys"] if k["kid"] == header["kid"])
    claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=AUD, issuer=ISSUER)
    return claims  # email, sub などを取り出して使う

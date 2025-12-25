import random
import string
import secrets
import base64
import hashlib 
import bcrypt
from typing import Dict, Any, Optional
from os import getenv
from app.constants.enums import MediaAssetKind, MediaAssetStatus
from uuid import UUID
import os
from app.services.s3.presign import presign_get


CDN_URL = getenv("CDN_BASE_URL")
MEDIA_CDN_URL = getenv("MEDIA_CDN_URL")
INGEST_CDN_URL = getenv("INGEST_CDN_URL")

APPROVED_MEDIA_CDN_KINDS = {
    MediaAssetKind.MAIN_VIDEO,
    MediaAssetKind.SAMPLE_VIDEO,
}
CDN_MEDIA_KINDS = {
    MediaAssetKind.OGP,
    MediaAssetKind.THUMBNAIL,
}
PENDING_MEDIA_ASSET_STATUSES = {
    MediaAssetStatus.PENDING,
    MediaAssetStatus.RESUBMIT,
    MediaAssetStatus.CONVERTING,
    MediaAssetStatus.REJECTED,
}
PRESIGN_MEDIA_KINDS = APPROVED_MEDIA_CDN_KINDS | {MediaAssetKind.IMAGES}


def generate_code(length: int = 5) -> str:
    """
    ランダムなコードを生成

    Args:
        length (int): コードの長さ

    Returns:
        str: ランダムなコード
    """
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

def generate_sms_code(length: int = 5) -> int:
    """
    5桁の数値のSMSコードを生成

    Args:
        length (int): コードの長さ

    Returns:
        str: SMSコード
    """
    code = f"{random.randint(0, 999999):06d}"
    return int(code)

def generate_sendid(length: int = 20) -> str:
    """
    CREDIX決済用のランダムなカードID（sendid）を生成

    Args:
        length (int): 生成する文字列の長さ（デフォルト20文字、最大25文字）

    Returns:
        str: ランダム文字列（半角英数字）

    Raises:
        ValueError: lengthが25を超える場合
    """
    if length > 25:
        raise ValueError("sendid length must be 25 or less")

    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))

def get_video_duration(duration_sec: float) -> str:
    """
    動画の再生時間をmm:ss形式に変換

    Args:
        duration_sec (float): 動画の再生時間（秒）

    Returns:
        str: mm:ss形式の動画の再生時間
    """
    # 四捨五入して整数秒に変換
    rounded_sec = round(duration_sec)
    minutes = rounded_sec // 60
    seconds = rounded_sec % 60
    return f"{minutes:02d}:{seconds:02d}"

def generate_email_verification_token() -> tuple[str, str]:
    raw = base64.urlsafe_b64encode(random.randbytes(32)).decode().rstrip("=")
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, token_hash

def check_sms_verify(code: str, code_hash: str) -> bool:
    """
    SMSコードを検証する

    Returns:
        bool: 検証結果
    """
    return bcrypt.checkpw(code.encode('utf-8'), code_hash.encode('utf-8'))

def generete_hash(code: str) -> str:
    """
    コードをハッシュ化する

    Returns:
        str: ハッシュ化されたコード
    """
    return bcrypt.hashpw(code.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def resolve_media_asset_storage_key(media_asset: Dict[str, Any]) -> str:
    """メディアアセットの状態に応じて表示用の storage_key を返す。"""
    kind = media_asset.get("kind")
    status = media_asset.get("status")
    storage_key = media_asset.get("storage_key")

    if not storage_key:
        return ""

    if status == MediaAssetStatus.APPROVED:
        if kind == MediaAssetKind.IMAGES:
            return f"{MEDIA_CDN_URL}/{storage_key}_1080w.webp"
        if kind in APPROVED_MEDIA_CDN_KINDS:
            return f"{MEDIA_CDN_URL}/{storage_key}"
        if kind in CDN_MEDIA_KINDS:
            return f"{CDN_URL}/{storage_key}"
        return storage_key

    if status in PENDING_MEDIA_ASSET_STATUSES:
        if kind in PRESIGN_MEDIA_KINDS:
            # presign_url = presign_get("ingest", storage_key)
            # return presign_url["download_url"]
            return f"{INGEST_CDN_URL}/{storage_key}"
        if kind in CDN_MEDIA_KINDS:
            return f"{CDN_URL}/{storage_key}"

    return storage_key


def generate_email_verification_url(token: str, code: Optional[UUID] = None) -> str:
    """
    メールアドレスの認証URLを生成
    """
    if code:
        return f"{os.getenv('FRONTEND_URL')}/auth/verify-email?token={token}&code={code}"
    else:
        return f"{os.getenv('FRONTEND_URL')}/auth/verify-email?token={token}"

def generate_advertising_agency_code() -> str:
    """
    広告会社コードを生成ランダムな10桁の数字とアルファベット

    Returns:
        str: 広告会社コード
    """
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
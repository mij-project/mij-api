import random
import string
import base64
import hashlib, bcrypt
import os


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
    raw = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
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
# app/services/s3/keygen.py
import uuid
from datetime import datetime, timezone

def video_key(creator_id: str, filename: str) -> str:
    """
    ビデオキー生成

    Args:
        creator_id (str): クリエイターID
        filename (str): ファイル名

    Returns:
        str: ビデオキー
    """
    uid = uuid.uuid4()
    d = datetime.now(timezone.utc)
    return f"{creator_id}/videos/{d.year}/{d.month:02d}/{d.day:02d}/{uid}/raw/{filename}"

def identity_key(creator_id: str, submission_id: str, kind: str, ext: str) -> str:
    """
    身分証明書キー生成

    Args:
        creator_id (str): クリエイターID
        submission_id (str): 提出ID
        kind (str): 種類
        ext (str): 拡張子

    Returns:
        str: 身分証明書キー
    """
    return f"{creator_id}/identity/{submission_id}/{kind}.{ext}"


def account_asset_key(creator_id: str, kind: str, ext: str) -> str:
    """
    アバターキー生成

    Args:
        creator_id (str): クリエイターID
        filename (str): ファイル名
    Returns:
        str: アバターキー
    """
    return f"profiles/{creator_id}/{kind}/{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4()}.{ext}"

def post_media_image_key(kind: str, creator_id: str, post_id: str, ext: str) -> str:
    """
    投稿メディア画像キー生成

    Args:
        kind: str 種類
        creator_id: str クリエイターID
        post_id: str 投稿ID
        ext: str 拡張子

    Returns:
        str: 投稿メディア画像キー
    """
    return f"post-media/{creator_id}/{kind}/{post_id}/{uuid.uuid4()}.{ext}"


def post_media_video_key(creator_id: str, post_id: str, ext: str, kind: str) -> str:
    """
    投稿メディアビデオキー生成

    Args:
        creator_id: str クリエイターID
        post_id: str 投稿ID
        ext: str 拡張子
        kind: str 種類

    Returns:
        str: 投稿メディアビデオキー
    """
    return f"post-media/{creator_id}/{kind}/{post_id}/{uuid.uuid4()}.{ext}"

def transcode_mc_key(creator_id: str, post_id: str, asset_id: str) -> str:
    """
    メディアコンバートキー生成

    Args:
        creator_id: str クリエイターID
        post_id: str 投稿ID
        ext: str 拡張子
        kind: str 種類

    Returns:
        str: メディアコンバートキー
    """
    return f"transcode-mc/{creator_id}/{post_id}/{asset_id}/preview/"


def transcode_mc_hls_prefix(creator_id: str, post_id: str, asset_id: str) -> str:
    """
    HLS 出力のプレフィックスを生成

    Args:
        creator_id: str クリエイターID
        post_id: str 投稿ID
        asset_id: str アセットID

    Returns:
        str: HLS 出力のプレフィックス
    """
    return f"transcode-mc/{creator_id}/{post_id}/{asset_id}/hls/"


def transcode_mc_ffmpeg_key(creator_id: str, post_id: str, ext: str) -> str:
    """
    メディアコンバートキー生成

    Args:
        creator_id: str クリエイターID
        post_id: str 投稿ID
        asset_id: str アセットID
        ext: str 拡張子

    Returns:
        str: メディアコンバートキー
    """
    return f"transcode-mc/{creator_id}/{post_id}/ffmpeg/{uuid.uuid4()}.{ext}"

def temp_video_key(creator_id: str, filename: str, ext: str) -> str:
    """
    一時保存ビデオキー生成

    Args:
        creator_id: str クリエイターID
        filename: str ファイル名

    Returns:
        str: 一時保存ビデオキー
    """
    return f"temp-videos/{creator_id}/{uuid.uuid4()}.{ext}"

def message_asset_key(conversation_id: str, message_id: str, asset_type: str, ext: str) -> str:
    """
    メッセージアセットキー生成

    Args:
        conversation_id: str 会話ID
        message_id: str メッセージID
        asset_type: str アセットタイプ（"image" or "video"）
        ext: str 拡張子

    Returns:
        str: メッセージアセットキー
    """
    uid = uuid.uuid4()
    return f"conversations/{conversation_id}/messages/{message_id}/{asset_type}/{uid}.{ext}"


def bulk_message_asset_key(user_id: str, bulk_message_id: str, asset_type: str, ext: str) -> str:
    """
    一斉送信メッセージアセットキー生成

    Args:
        user_id: str ユーザーID（クリエイター）
        bulk_message_id: str 一斉送信ID
        asset_type: str アセットタイプ（"image" or "video"）
        ext: str 拡張子

    Returns:
        str: 一斉送信メッセージアセットキー
    """
    uid = uuid.uuid4()
    d = datetime.now(timezone.utc)
    return f"bulk-messages/{user_id}/{d.year}/{d.month:02d}/{d.day:02d}/{bulk_message_id}/{asset_type}/{uid}.{ext}"
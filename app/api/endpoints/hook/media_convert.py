from fastapi import APIRouter, Header, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional, Tuple
import boto3
import os
import subprocess
import tempfile
from decimal import Decimal

from app.crud.media_rendition_jobs_crud import update_media_rendition_job, get_media_rendition_job_by_id
from app.crud.media_assets_crud import get_media_asset_by_id, update_media_asset
from app.crud.media_rendition_crud import create_media_rendition
from app.crud.post_crud import add_notification_for_post, update_post_status
from app.constants.enums import MediaRenditionJobStatus, MediaRenditionKind, PostStatus, MediaAssetStatus
from app.db.base import get_db
from app.constants.enums import AuthenticatedFlag
from app.services.s3.client import MEDIA_BUCKET_NAME, AWS_REGION

# Constants
HLS_VARIANT_SUFFIXES = (
    "_360p.m3u8", "_480p.m3u8", "_720p.m3u8", "_1080p.m3u8", "_audio.m3u8"
)

MP4_VARIANT_SUFFIXES = (
    "_360p.mp4", "_480p.mp4", "_720p.mp4", "_1080p.mp4", "_preview.mp4", "_audio.mp4"
)

SUPPORTED_EXTENSIONS = (".m3u8", ".mp4")

MIME_TYPE_MAP = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".mp4": "video/mp4"
}

HOOK_SECRET = os.getenv("WEB_HOOK_SECRET")

# Initialize S3 client
s3_client = boto3.client("s3", region_name=AWS_REGION)

router = APIRouter()


@router.post("/mediaconvert")
async def mediaconvert_webhook(
    payload: dict, 
    x_hook_secret: Optional[str] = Header(None), 
    db: Session = Depends(get_db)
) -> dict:
    """
    MediaConvertのWebhookを受け取って処理する
    """
    _validate_webhook_secret(x_hook_secret)
    
    webhook_data = _extract_webhook_data(payload)
    
    try:
        if webhook_data["type"] == "preview":
            _handle_preview_completion(db, webhook_data)
        elif webhook_data["type"] == "final-hls":
            _handle_final_hls_completion(db, webhook_data)
        else:
            raise HTTPException(400, f"Unsupported job type: {webhook_data['type']}")
            
        db.commit()
        return {"ok": True}
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Webhook processing error: {e}")
        raise HTTPException(500, "Internal server error")


def _validate_webhook_secret(x_hook_secret: Optional[str]) -> None:
    """Webhookの認証を検証する"""
    if not HOOK_SECRET:
        raise HTTPException(500, "Server misconfigured: HOOK_SECRET not set")
    if x_hook_secret != HOOK_SECRET:
        raise HTTPException(401, "Unauthorized")


def _extract_webhook_data(payload: dict) -> dict:
    """Webhookペイロードから必要なデータを抽出する"""
    try:
        detail = payload["detail"]
        user_metadata = detail["userMetadata"]
        
        # ステータスの変換
        status_map = {
            "COMPLETE": MediaRenditionJobStatus.COMPLETE,
            "ERROR": MediaRenditionJobStatus.FAILED
        }
        
        status = status_map.get(detail["status"])
        if not status:
            raise HTTPException(400, f"Invalid status: {detail['status']}")
        
        return {
            "type": user_metadata["type"],
            "rendition_job_id": user_metadata["renditionJobId"],
            "asset_id": user_metadata.get("assetId"),
            "status": status,
            "detail": detail
        }
    except KeyError as e:
        raise HTTPException(400, f"Missing required field: {e}")


def _handle_preview_completion(db: Session, webhook_data: dict) -> None:
    """プレビュー完了の処理"""
    rendition_job = get_media_rendition_job_by_id(db, webhook_data["rendition_job_id"])
    if not rendition_job:
        raise HTTPException(404, "Rendition job not found")
    
    # マスターファイルを検索
    storage_key, size_bytes = _find_master_file(webhook_data["detail"], rendition_job.output_prefix)
    
    if not storage_key:
        raise HTTPException(500, "Master file not found under output prefix")
    
    # レンディションジョブを更新
    update_data = {
        "status": webhook_data["status"],
        "output_key": storage_key
    }
    
    update_media_rendition_job(db, webhook_data["rendition_job_id"], update_data)


def _handle_final_hls_completion(db: Session, webhook_data: dict) -> None:
    """HLS完了の処理"""
    if not webhook_data["asset_id"]:
        raise HTTPException(400, "Asset ID is required for final-hls processing")
    
    # アセットの取得
    asset = get_media_asset_by_id(db, webhook_data["asset_id"])
    if not asset:
        raise HTTPException(404, "Asset not found")
    
    # レンディションジョブの取得
    rendition_job = get_media_rendition_job_by_id(db, webhook_data["rendition_job_id"])
    if not rendition_job:
        raise HTTPException(404, "Rendition job not found")
    
    # マスターファイルを検索
    storage_key, size_bytes = _find_master_file(webhook_data["detail"], rendition_job.output_prefix)
    
    if not storage_key:
        raise HTTPException(500, "Master file not found under output prefix")
    
    # ファイル拡張子からMIMEタイプとMediaRenditionKindを決定
    file_extension = _get_file_extension(storage_key)
    mime_type = MIME_TYPE_MAP.get(file_extension, "application/octet-stream")
    kind = _get_media_rendition_kind(file_extension)
    
    # 動画の再生時間を取得
    duration_sec = _get_video_duration(webhook_data["detail"], storage_key)
    
    # レンディションジョブを更新
    update_data = {
        "status": webhook_data["status"],
        "output_key": storage_key,
        "mime_type": mime_type,
        "kind": kind,
    }    
    update_media_rendition_job(db, webhook_data["rendition_job_id"], update_data)

    # media_asset 更新
    media_asset_update_data = {
        "bytes": size_bytes or 0,
        "storage_key": storage_key,
        "duration_sec": duration_sec,
        "status": MediaAssetStatus.APPROVED,
    }
    update_media_asset(db, asset.id, media_asset_update_data)
    
    # 投稿のステータスを承認に更新
    post = update_post_status(db, asset.post_id, PostStatus.APPROVED, AuthenticatedFlag.AUTHENTICATED)
    if not post:
        raise HTTPException(404, "Post not found")
    
    # 投稿に対する通知を追加
    add_notification_for_post(db, post, post.creator_user_id, type="approved")

def _find_master_file(detail: dict, output_prefix: str) -> Tuple[Optional[str], Optional[int]]:
    """マスターファイルを検索する"""
    # 1. イベントから直接取得を試行
    storage_key = _extract_master_from_event(detail)
    
    if storage_key:
        # イベントから取得できた場合はサイズを補完
        try:
            head = s3_client.head_object(Bucket=MEDIA_BUCKET_NAME, Key=storage_key)
            size_bytes = head.get("ContentLength", 0)
            return storage_key, size_bytes
        except Exception:
            # S3アクセスに失敗した場合はS3リストで再試行
            pass
    
    # 2. S3を走査して検索
    return _find_master_by_listing(MEDIA_BUCKET_NAME, output_prefix)


def _extract_master_from_event(detail: dict) -> Optional[str]:
    """
    MediaConvertのイベントからマスターファイルのS3キーを抽出する
    """
    output_groups = detail.get("outputGroupDetails", [])
    file_keys = []
    
    for output_group in output_groups:
        for output_detail in output_group.get("outputDetails", []):
            # HLS用のプレイリストファイル
            for playlist_path in output_detail.get("playlistFilePaths", []):
                key = _extract_s3_key_from_path(playlist_path)
                if key:
                    file_keys.append(key)
            
            # MP4用の出力ファイル
            for output_path in output_detail.get("outputFilePaths", []):
                key = _extract_s3_key_from_path(output_path)
                if key:
                    file_keys.append(key)
    
    # バリアントでないマスターファイルを検索
    master_files = [key for key in file_keys if _is_master_file(key)]
    
    return master_files[0] if master_files else None


def _extract_s3_key_from_path(s3_path: str) -> Optional[str]:
    """S3パスからキーを抽出する"""
    try:
        if not s3_path.startswith("s3://"):
            return None
        
        # s3://bucket/key の形式から key を抽出
        _, _, rest = s3_path.partition("s3://")
        bucket, _, key = rest.partition("/")
        
        return key if bucket and key else None
    except Exception:
        return None


def _find_master_by_listing(bucket: str, prefix: str) -> Tuple[Optional[str], Optional[int]]:
    """
    S3を走査してマスターファイルを検索する
    """
    try:
        search_prefix = prefix.strip("/") + "/"
        paginator = s3_client.get_paginator("list_objects_v2")
        
        candidates = []
        for page in paginator.paginate(Bucket=bucket, Prefix=search_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if _is_master_file(key):
                    candidates.append(key)
        
        if not candidates:
            return None, None
        
        # 最短のキーを選択（通常はマスターファイルが最短）
        master_key = sorted(candidates, key=len)[0]
        
        # ファイルサイズを取得
        head = s3_client.head_object(Bucket=bucket, Key=master_key)
        size_bytes = head.get("ContentLength")
        
        return master_key, size_bytes
        
    except Exception as e:
        print(f"Error listing S3 objects: {e}")
        return None, None


def _is_master_file(key: str) -> bool:
    """キーがマスターファイルかどうかを判定する"""
    key_lower = key.lower()
    
    # サポートする拡張子かチェック
    if not any(key_lower.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        return False
    
    # バリアントファイルでないかチェック
    if key_lower.endswith('.m3u8'):
        return not key_lower.endswith(HLS_VARIANT_SUFFIXES)
    elif key_lower.endswith('.mp4'):
        return not key_lower.endswith(MP4_VARIANT_SUFFIXES)
    
    return False


def _get_file_extension(filename: str) -> str:
    """ファイル名から拡張子を取得する"""
    return filename.lower().split('.')[-1] if '.' in filename else ''


def _get_media_rendition_kind(file_extension: str) -> MediaRenditionKind:
    """ファイル拡張子からMediaRenditionKindを決定する"""
    if file_extension == ".m3u8":
        return MediaRenditionKind.HLS_MASTER
    elif file_extension == ".mp4":
        return MediaRenditionKind.MP4
    else:
        return MediaRenditionKind.HLS_MASTER  # デフォルト


def _get_video_duration(detail: dict, storage_key: str) -> Optional[Decimal]:
    """
    動画の再生時間を取得する
    1. MediaConvertのイベントから取得を試行
    2. 失敗した場合はFFmpegを使用してS3ファイルから取得
    """
    # 1. MediaConvertのイベントから取得を試行
    duration_ms = _extract_duration_from_event(detail)
    if duration_ms is not None:
        return Decimal(str(duration_ms / 1000.0))  # ミリ秒を秒に変換
    
    # 2. FFmpegを使用してS3ファイルから取得
    try:
        return _get_duration_with_ffmpeg(storage_key)
    except Exception as e:
        print(f"Failed to get video duration: {e}")
        return None


def _extract_duration_from_event(detail: dict) -> Optional[int]:
    """
    MediaConvertのイベントから動画の再生時間を抽出する
    """
    try:
        # MediaConvertの完了イベントからdurationInMsを取得
        output_groups = detail.get("outputGroupDetails", [])
        
        for output_group in output_groups:
            for output_detail in output_group.get("outputDetails", []):
                # durationInMsフィールドを確認
                duration_ms = output_detail.get("durationInMs")
                if duration_ms is not None:
                    return duration_ms
        
        # フォールバック: ジョブ全体のduration
        job_duration = detail.get("durationInMs")
        if job_duration is not None:
            return job_duration
            
        return None
    except Exception:
        return None


def _get_duration_with_ffmpeg(storage_key: str) -> Optional[Decimal]:
    """
    FFmpegを使用してS3ファイルから動画の再生時間を取得する
    """
    try:
        # S3から一時ファイルにダウンロード
        with tempfile.NamedTemporaryFile(suffix=_get_file_extension(storage_key)) as temp_file:
            # S3からファイルをダウンロード
            s3_client.download_file(MEDIA_BUCKET_NAME, storage_key, temp_file.name)
            
            # FFmpegでメタデータを取得
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                temp_file.name
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # JSONを解析してdurationを取得
            import json
            metadata = json.loads(result.stdout)
            duration_str = metadata["format"].get("duration")
            
            if duration_str:
                return Decimal(duration_str)
            
            return None
            
    except subprocess.CalledProcessError as e:
        print(f"FFprobe error: {e}")
        return None
    except Exception as e:
        print(f"Error getting duration with FFmpeg: {e}")
        return None
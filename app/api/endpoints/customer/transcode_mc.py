from math import fabs
from fastapi import APIRouter, HTTPException, Depends, Path
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.services.s3.media_covert import build_media_rendition_job_settings, build_hls_abr4_settings
from app.crud.media_assets_crud import get_media_asset_by_post_id, update_media_asset, get_media_assets_by_ids
from app.schemas.post_media import PoseMediaCovertRequest
from app.services.s3.keygen import (
    transcode_mc_hls_prefix, 
    transcode_mc_ffmpeg_key
)
from app.services.s3.image_screening import (
    _s3_download_bytes, 
    _s3_put_bytes,
    _is_supported_magic,
    _sanitize_and_variants,
    _moderation_check,
    _make_variant_keys,
)
from app.services.s3.client import s3_client_for_mc, ENV, MEDIA_BUCKET_NAME, INGEST_BUCKET
from app.constants.enums import (
    MediaRenditionJobKind, 
    MediaRenditionJobBackend, 
    MediaRenditionJobStatus,
    MediaRenditionKind,
    PostStatus,
    PostType,
    MediaAssetStatus,
    AuthenticatedFlag,
)
from app.crud.media_rendition_jobs_crud import create_media_rendition_job, update_media_rendition_job
from app.crud.media_rendition_crud import create_media_rendition
from app.crud.media_assets_crud import update_media_asset, update_sub_media_assets_status, update_media_asset_rejected_comments 
from app.crud.post_crud import add_mail_notification_for_post, add_notification_for_post, update_post_status
from app.crud.media_assets_crud import get_media_asset_by_id
from app.schemas.transcode_mc import TranscodeMCUpdateRequest
from app.crud.post_crud import get_post_by_id
from app.constants.enums import MediaAssetKind
import boto3
from typing import Dict, Any, Optional
from app.core.logger import Logger
logger = Logger.get_logger()
S3 = boto3.client("s3", region_name="ap-northeast-1")

router = APIRouter()

def _create_media_convert_job(
    db: Session,
    asset_row: Any,
    post_id: str,
    job_kind: MediaRenditionJobKind,
    output_prefix: str,
    usermeta_type: str,
    build_settings_func
) -> Any:
    """
    メディアコンバートジョブを作成する共通処理
    
    Args:
        db: データベースセッション
        asset_row: メディアアセット行
        post_id: 投稿ID
        job_kind: ジョブの種類
        output_prefix: 出力プレフィックス
        usermeta_type: ユーザーメタタイプ
        build_settings_func: 設定ビルド関数
    
    Returns:
        作成されたメディアレンディションジョブ
    """
    # ジョブ作成
    media_rendition_job_data = {
        "asset_id": asset_row.id,
        "kind": job_kind,
        "input_key": asset_row.storage_key,
        "output_prefix": output_prefix,
        "backend": MediaRenditionJobBackend.MEDIACONVERT,
        "status": MediaRenditionJobStatus.PENDING,
    }
    media_rendition_job = create_media_rendition_job(db, media_rendition_job_data)

    # ジョブ設定作成
    usermeta = {
        "postId": str(post_id), 
        "assetId": str(asset_row.id), 
        "renditionJobId": str(media_rendition_job.id),
        "type": usermeta_type,
        "env": ENV,
    } 
    settings = build_settings_func(
        input_key=asset_row.storage_key,
        output_prefix=output_prefix,
        usermeta=usermeta,
    )

    # MediaConvertにジョブを送信
    try:
        mediaconvert_client = s3_client_for_mc()
        response = mediaconvert_client.create_job(**settings)
        
        # ジョブIDを保存
        update_data = {
            "id": media_rendition_job.id,
            "status": MediaRenditionJobStatus.PROGRESSING,
            "job_id": response['Job']['Id']
        }
    except Exception as e:
        logger.error(f"Error creating MediaConvert job: {e}")
        # エラーが発生した場合はステータスを更新
        update_data = {
            "id": media_rendition_job.id,
            "status": MediaRenditionJobStatus.FAILED,
        }

    # ジョブ設定更新
    update_media_rendition_job(db, media_rendition_job.id, update_data)
    db.commit()
    return True


def _process_image_asset(
    db: Session,
    asset_row: Any,
    post_id: str
) -> Optional[Any]:
    """
    画像アセットを処理する共通処理
    
    Args:
        db: データベースセッション
        asset_row: メディアアセット行
        post_id: 投稿ID
    
    Returns:
        作成されたメディアレンディション（最後のもの）
    """
    # 1) 取り込み元の取得
    src_key = asset_row.storage_key
    img_bytes = _s3_download_bytes(INGEST_BUCKET, src_key)

    # 2) マジックナンバー/整合性チェック
    if not _is_supported_magic(img_bytes):
        raise HTTPException(400, "Unsupported image format")

    # 3) 任意: モデレーション
    mod = _moderation_check(img_bytes, min_conf=80.0)
    if mod["flagged"]:
        # ここでDBをREJECTにする等の処理を行っても良い
        raise HTTPException(status_code=400, detail=f"Image rejected by moderation: {mod['labels']}")

    # 4) 正規化＋派生生成
    variants = _sanitize_and_variants(img_bytes)

    # 出力先key
    base_output_key = transcode_mc_ffmpeg_key(
        creator_id=asset_row.creator_user_id,
        post_id=asset_row.post_id,
        ext="jpg", 
    )

    # ベースキーから派生ファイルの最終保存キーを決定
    variant_keys = _make_variant_keys(base_output_key)

    # 5) DB: media_asset 更新
    stem, _ext = base_output_key.rsplit(".", 1)

    # 6) アップロード（SSE-KMS, CacheControl 付き）
    for filename, (bytes_data, ctype) in variants.items():
        dst_key = variant_keys[filename]
        _s3_put_bytes(MEDIA_BUCKET_NAME, dst_key, bytes_data, ctype)

        # 元画像の場合は、storage_keyを更新
        if filename == "original.jpg":
            media_asset_update_data = {
                "storage_key": stem,
                "bytes": len(bytes_data),
                "status": MediaAssetStatus.APPROVED,
            }
            update_media_asset(db, asset_row.id, media_asset_update_data)

    return True


@router.post("/transcode_mc/{post_id}/{post_type}")
def transcode_mc_unified(
    post_id: str = Path(..., description="Post ID"),
    post_type: int = Path(..., description="Post Type"),
    db: Session = Depends(get_db)
):
    """
    投稿メディアコンバート統合処理（HLS ABR4 + FFmpeg）
    
    Args:
        post_id: str
        post_type: str
        db: Session
    
    Returns:
        dict: メディアコンバート結果
    """
    try:
        # post_typeから処理タイプを決定
        type_mapping = {
            PostType.VIDEO: "video",  # 動画投稿
            PostType.IMAGE: "image",  # 画像投稿
        }
        type = type_mapping.get(post_type, "video")  # デフォルトはvideo

        # サブメディアアセットを更新
        update_sub_media_asset(db, post_id)

        # 投稿ステータスを変換中に更新
        post = _update_post_status_for_convert(db, post_id, PostStatus.CONVERTING)
        if not post:
            raise HTTPException(status_code=404, detail="Post status not updated")

        # メディアアセットの取得
        assets = get_media_asset_by_post_id(db, post_id, post_type)
        if not assets:
            raise HTTPException(status_code=404, detail="Media asset not found")


        image_processing_result = False
        for row in assets:
            # HLS ABR4処理（ビデオの場合のみ）
            if type == "video":
                output_prefix = transcode_mc_hls_prefix(
                    creator_id=row.creator_user_id,
                    post_id=row.post_id,
                    asset_id=row.id,
                )

                _create_media_convert_job(
                    db=db,
                    asset_row=row,
                    post_id=post_id,
                    job_kind=MediaRenditionJobKind.HLS_ABR4,
                    output_prefix=output_prefix,
                    usermeta_type="final-hls",
                    build_settings_func=build_hls_abr4_settings
                )

            # FFmpeg処理（画像の場合のみ）
            if type == "image":
                image_processing_result = _process_image_asset(db, row, post_id)
                if not image_processing_result:
                    raise HTTPException(status_code=500, detail="Image processing failed")

        # 画像処理の場合のみ、最後のループ処理でステータス更新と通知を送信
        if type == "image" and image_processing_result:
            # 投稿ステータスの更新
            post = update_post_status(db, post_id, PostStatus.APPROVED, AuthenticatedFlag.AUTHENTICATED)
            
            db.commit()
            db.refresh(post)

            # Email通知を追加（メール通知設定をチェック）
            add_mail_notification_for_post(db, post_id=post_id, type="approved")
            # 投稿に対する通知を追加
            add_notification_for_post(db, post, post.creator_user_id, type="approved")

        return {"status": True, "message": f"Media conversion completed for {type}"}

    except HTTPException as httpexception:
        db.rollback()
        logger.exception(f"HTTPException: {httpexception}")
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"メディアコンバート処理にてエラーが発生しました。: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/transcode_mc")
def transcode_mc_update(
    update_request: TranscodeMCUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    再申請メディアアセットのコンバート処理

    Args:
        update_request: TranscodeMCUpdateRequest
        db: Session

    Returns:
        dict: メディアコンバート結果
    """
    try:
        post_id = update_request.post_id
        media_asset_ids = update_request.media_assets
        post_type = update_request.post_type

        post = _update_post_status_for_convert(db, post_id, PostStatus.CONVERTING)

        logger.info(f"MediaConvert処理対象アセット更新処理: post_id={post_id}, media_asset_ids={media_asset_ids}")

        result = _update_media_asset_rejected_comments(db, post_id)
        if not result:
            raise HTTPException(status_code=404, detail="Media asset not found")

        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        type_mapping = {
            PostType.VIDEO: "video",  # 動画投稿
            PostType.IMAGE: "image",  # 画像投稿
        }
        type = type_mapping.get(post_type, "video")  # デフォルトはvideo

        update_sub_media_asset(db, post_id)

        assets = get_media_assets_by_ids(db, media_asset_ids, type)
        if not assets:
            raise HTTPException(status_code=404, detail="Media asset not found")

        logger.info(f"MediaConvert処理対象アセット: post_id={post_id}, asset_ids={[a.id for a in assets]}, kinds={[a.kind for a in assets]}")

        # 動画投稿の場合、メイン・サンプル動画のステータスをRESUBMITに更新
        # （どちらかが再提出された場合、両方を再変換するため）
        if type == "video":
            for asset in assets:
                if asset.kind in [MediaAssetKind.MAIN_VIDEO, MediaAssetKind.SAMPLE_VIDEO]:
                    video_update_data = {
                        "status": MediaAssetStatus.RESUBMIT
                    }
                    update_media_asset(db, asset.id, video_update_data)
                    kind_label = "メイン動画" if asset.kind == MediaAssetKind.MAIN_VIDEO else "サンプル動画"
                    logger.info(f"{kind_label}のステータスをRESUBMITに更新: asset_id={asset.id}")

        for asset in assets:
            if type == "video":
                output_prefix = transcode_mc_hls_prefix(
                    creator_id=asset.creator_user_id,
                    post_id=asset.post_id,
                    asset_id=asset.id,
                )
                _create_media_convert_job(db, asset, post_id, MediaRenditionJobKind.HLS_ABR4, output_prefix, "final-hls", build_hls_abr4_settings)
            if type == "image":
                result = _process_image_asset(db, asset, post_id)
                if not result:
                    raise HTTPException(status_code=500, detail="Image processing failed")
                else:
                    # 投稿ステータスの更新
                    post = update_post_status(db, post_id, PostStatus.APPROVED, AuthenticatedFlag.AUTHENTICATED)
                    db.commit()
                    db.refresh(post)

                    # Email通知を追加
                    add_mail_notification_for_post(db, post_id=post_id, type="approved")
                    # 投稿に対する通知を追加
                    add_notification_for_post(db, post, asset.creator_user_id, type="approved")

        return {"status": True, "message": f"Media conversion completed for {type}"}


    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"メディアコンバート更新処理にてエラーが発生しました。: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

def update_sub_media_asset(db: Session, post_id: str) -> Optional[Any]:
    """
    サブメディアアセットを更新する
    """
    kind_list = [MediaAssetKind.THUMBNAIL, MediaAssetKind.OGP]
    media_assets = update_sub_media_assets_status(db, post_id, kind_list, MediaAssetStatus.APPROVED)
    return True

def _update_post_status_for_convert(db: Session, post_id: str, status: int) -> Optional[Any]:
    """
    投稿ステータスを変換中に更新する
    """
    post = update_post_status(db, post_id, status)
    db.commit()
    db.refresh(post)
    return post

def _update_media_asset_rejected_comments(db: Session, post_id: str) -> bool:
    """
    メディアアセットを拒否して拒否理由を更新する
    """
    result = update_media_asset_rejected_comments(db, post_id)
    return True
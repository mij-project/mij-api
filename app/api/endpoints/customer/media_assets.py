from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.services.s3.presign import presign_put_public, presign_put, get_bucket_name, Resource
from app.schemas.post_media import (
    PostMediaImagePresignRequest,
    PostMediaVideoPresignRequest,
    ImageKind,
    PostMediaImagePresignResponse,
    PostMediaVideoPresignResponse,
    VideoKind,
    UpdateMediaImagePresignRequest,
    UpdateMediaVideoPresignRequest,
    UpdateImagesPresignRequest,
    UpdateImagesPresignResponse,
    TriggerBatchProcessRequest,
    TriggerBatchProcessResponse,
)
from app.deps.auth import get_current_user
from app.db.base import get_db
from app.services.s3.keygen import post_media_image_key, post_media_video_key
from app.schemas.commons import PresignResponseItem
from typing import Dict, List, Union, Tuple, Set, Any
from app.services.s3.client import delete_ffmpeg_directory, delete_hls_directory_full
from app.services.s3.presign import delete_object
from app.crud.media_assets_crud import (
    create_media_asset,
    get_media_assets_by_post_id_and_kind,
    delete_media_asset,
    get_media_asset_by_id,
)
from app.crud.media_rendition_jobs_crud import delete_media_rendition_job
from app.crud.post_crud import get_post_by_id
from app.models.posts import Posts
from app.models.user import Users
from app.constants.enums import MediaAssetKind, MediaAssetOrientation, MediaAssetStatus, PostStatus
from app.constants.enums import AuthenticatedFlag
from app.core.logger import Logger
import subprocess
import os
import boto3
from app.core.config import settings

logger = Logger.get_logger()
router = APIRouter()

# 文字列kindから整数kindへのマッピング
KIND_MAPPING = {
    "ogp": MediaAssetKind.OGP,
    "thumbnail": MediaAssetKind.THUMBNAIL,
    "images": MediaAssetKind.IMAGES,
    "main": MediaAssetKind.MAIN_VIDEO,
    "sample": MediaAssetKind.SAMPLE_VIDEO,
}

# 文字列orientationから整数orientationへのマッピング
ORIENTATION_MAPPING = {
    "portrait": MediaAssetOrientation.PORTRAIT,
    "landscape": MediaAssetOrientation.LANDSCAPE,
    "square": MediaAssetOrientation.SQUARE,
}

# 許可されたkind
ALLOWED_IMAGE_KINDS = {"ogp", "thumbnail", "images"}
ALLOWED_VIDEO_KINDS = {"main", "sample"}

# S3
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
INGEST_BUCKET_NAME = os.getenv("INGEST_BUCKET_NAME")
KMS_ALIAS_INGEST = os.getenv("KMS_ALIAS_INGEST")
TMP_VIDEO_BUCKET_NAME = os.getenv("TMP_VIDEO_BUCKET")
KMS_ALIAS_INGEST = os.getenv("KMS_ALIAS_INGEST")


# ==================== ヘルパー関数 ====================

def validate_kinds(files: List, allowed_kinds: Set[str]) -> None:
    """
    ファイルのkindをバリデート
    
    Args:
        files: ファイルリスト
        allowed_kinds: 許可されたkindのセット
        
    Raises:
        HTTPException: バリデーションエラー
    """
    seen = set()
    for f in files:
        if f.kind not in allowed_kinds:
            raise HTTPException(400, f"unsupported kind: {f.kind}")
        if f.kind != "images" and f.kind in seen:
            raise HTTPException(400, f"duplicated kind: {f.kind}")
        seen.add(f.kind)


def create_presign_response_item(response: dict) -> PresignResponseItem:
    """PresignResponseItemを作成"""
    return PresignResponseItem(
        key=response["key"],
        upload_url=response["upload_url"],
        expires_in=response["expires_in"],
        required_headers=response["required_headers"]
    )


def create_media_asset_data(
    post_id: str,
    kind: ImageKind | VideoKind,
    storage_key: str,
    orientation: str,
    content_type: str,
    status: MediaAssetStatus = MediaAssetStatus.PENDING,
    sample_type: str | None = None,
    sample_start_time: float | None = None,
    sample_end_time: float | None = None,
) -> dict:
    """メディアアセットデータを作成"""
    data = {
        "post_id": post_id,
        "kind": KIND_MAPPING[kind],
        "storage_key": storage_key,
        "orientation": ORIENTATION_MAPPING[orientation],
        "mime_type": content_type,
        "status": status,
        "bytes": 0,
    }

    # サンプル動画のメタデータを追加（kind=sampleの場合のみ）
    if kind == "sample" and sample_type:
        data["sample_type"] = sample_type
        if sample_type == "cut_out":
            data["sample_start_time"] = sample_start_time
            data["sample_end_time"] = sample_end_time

    return data


def generate_image_presign(
    kind: ImageKind,
    user_id: str,
    post_id: str,
    ext: str,
    content_type: str
) -> dict:
    """
    画像のpresigned URLを生成
    
    Returns:
        dict: presigned URL情報
    """
    key = post_media_image_key(kind, user_id, post_id, ext)
    if kind == "images":
        return presign_put("ingest", key, content_type)
    else:
        return presign_put_public("public", key, content_type)


def generate_video_presign(
    user_id: str,
    post_id: str,
    ext: str,
    kind: VideoKind,
    content_type: str
) -> dict:
    """
    動画のpresigned URLを生成
    
    Returns:
        dict: presigned URL情報
    """
    key = post_media_video_key(user_id, post_id, ext, kind)
    return presign_put("ingest", key, content_type)


def get_image_resource_and_approved_flag(kind: str, authenticated_flg: AuthenticatedFlag) -> Resource:
    """
    画像のkindとpostステータスからリソース名とapproved_flagを取得
    
    Args:
        kind (str): 画像の種類（"images", "thumbnail", "ogp"）
        post_status (PostStatus): 投稿のステータス

    Returns:
        Tuple[Resource, bool]: (リソース名, approved_flag)
    """
    if kind == "images":
        if authenticated_flg == AuthenticatedFlag.AUTHENTICATED:
            return "media"
        else:
            return "ingest"
    elif kind in ("thumbnail", "ogp"):
        return "public"
    else:
        raise ValueError(f"Unknown image kind: {kind}")


def get_video_resource_and_approved_flag(uploaded_flag: int) -> Resource:
    """
    動画のアップロードフラグからリソース名とapproved_flagを取得
    
    Args:
        uploaded_flag (int): アップロードフラグ
        
    Returns:
        Tuple[Resource, bool]: (リソース名, approved_flag)
    """
    if uploaded_flag == AuthenticatedFlag.AUTHENTICATED:
        return "media"
    else:
        return "ingest"


def delete_existing_media_file(
    storage_key: str,
    resource: Resource,
    authenticated_flg: int,
    is_video: bool = False
) -> None:
    """
    既存のメディアファイルをS3から削除

    Args:
        storage_key (str): ストレージキー
        resource (Resource): リソース名
        authenticated_flg (int): 認証フラグ
        is_video (bool): 動画かどうか
    """
    if not storage_key:
        return

    bucket = get_bucket_name(resource)  

    try:
        if authenticated_flg == AuthenticatedFlag.AUTHENTICATED:
            if is_video:
                # 動画の場合、hlsディレクトリを削除
                if '/hls/' in storage_key:
                    delete_hls_directory_full(bucket, storage_key)
                else:
                    delete_object(resource, storage_key)
            else:
                # 画像の場合、ffmpegディレクトリを削除
                if '/ffmpeg/' in storage_key:
                    delete_ffmpeg_directory(bucket, storage_key)
                else:
                    delete_object(resource, storage_key)
        else:
            # 承認されていない場合は通常削除
            delete_object(resource, storage_key)
    except Exception as e:
        logger.error(f"Failed to delete old file from S3: {e}")


def _determine_resource_for_asset(
    asset_kind: MediaAssetKind,
    authenticated_flg: AuthenticatedFlag
) -> Resource:
    """
    メディアアセットの種類と認証フラグからリソースを決定

    Args:
        asset_kind (MediaAssetKind): メディアアセットの種類
        authenticated_flg (AuthenticatedFlag): 認証フラグ

    Returns:
        Resource: リソース名
    """
    if asset_kind in [MediaAssetKind.OGP, MediaAssetKind.THUMBNAIL]:
        return "public"
    elif asset_kind == MediaAssetKind.IMAGES:
        return get_image_resource_and_approved_flag("images", authenticated_flg)
    elif asset_kind in [MediaAssetKind.MAIN_VIDEO, MediaAssetKind.SAMPLE_VIDEO]:
        return get_video_resource_and_approved_flag(authenticated_flg)
    else:
        return "ingest"


def _verify_post_ownership(
    post: Dict[str, Any],
    user: Users
) -> None:
    """
    投稿の所有権を確認

    Args:
        post (Dict[str, Any]): 投稿情報（辞書形式）
        user (Users): 現在のユーザー

    Raises:
        HTTPException: 所有権がない場合
    """
    if str(post['user_id']) != str(user.id):
        raise HTTPException(
            status_code=403,
            detail="Unauthorized: you are not the owner of this post"
        )


# ==================== エンドポイント ====================

@router.post("/presign-image-upload")
async def presign_post_media_image(
    request: PostMediaImagePresignRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """画像のアップロードURLを生成

    Args:
        request (PostMediaImagePresignRequest): リクエストデータ
        user (Users): ユーザー
        db (Session): データベースセッション

    Raises:
        HTTPException: エラー

    Returns:
        PostMediaImagePresignResponse: アップロードURL
    """
    try:
        validate_kinds(request.files, ALLOWED_IMAGE_KINDS)

        uploads: Dict[ImageKind, Union[PresignResponseItem, List[PresignResponseItem]]] = {}
        updated_posts: Set[str] = set()

        for f in request.files:
            response = generate_image_presign(
                f.kind, str(user.id), str(f.post_id), f.ext, f.content_type
            )
            key = response["key"]

            if f.kind == "images":
                if f.kind not in uploads:
                    uploads[f.kind] = []
                uploads[f.kind].append(create_presign_response_item(response))
            else:
                uploads[f.kind] = create_presign_response_item(response)
            
            # メディアアセット作成
            media_asset_data = create_media_asset_data(
                str(f.post_id), f.kind, key, f.orientation, f.content_type
            )
            create_media_asset(db, media_asset_data)
            updated_posts.add(str(f.post_id))

        db.commit()
        
        # 更新された投稿をrefresh
        for post_id in updated_posts:
            post = db.query(Posts).filter(Posts.id == post_id).first()
            if post:
                db.refresh(post)

        return PostMediaImagePresignResponse(uploads=uploads)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"アップロードURL生成エラーが発生しました: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/presign-video-upload")
async def presign_post_media_video(
    request: PostMediaVideoPresignRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """動画のアップロードURLを生成（sample動画のuploadモード専用）

    Args:
        request (PostMediaVideoPresignRequest): リクエストデータ
        user (Users): ユーザー
        db (Session): データベースセッション

    Raises:
        HTTPException: エラー

    Returns:
        PostMediaVideoPresignResponse: アップロードURL
    """
    try:
        validate_kinds(request.files, ALLOWED_VIDEO_KINDS)

        uploads: Dict[VideoKind, PresignResponseItem] = {}

        for f in request.files:
            # sample動画のuploadモードのみ許可
            # main動画はuploadTempMainVideo → triggerBatchProcessを使用
            if f.kind == "main":
                raise HTTPException(
                    400,
                    "main動画のアップロードはuploadTempMainVideo → triggerBatchProcessを使用してください"
                )

            # sample動画でuploadモード以外は拒否
            if f.kind == "sample" and f.sample_type != "upload":
                raise HTTPException(
                    400,
                    "このエンドポイントはsample動画のuploadモードのみ対応しています。cut_outモードはtriggerBatchProcessを使用してください"
                )

            response = generate_video_presign(
                str(user.id), str(f.post_id), f.ext, f.kind, f.content_type
            )
            key = response["key"]

            uploads[f.kind] = create_presign_response_item(response)

            media_asset_data = create_media_asset_data(
                str(f.post_id), f.kind, key, f.orientation, f.content_type,
                sample_type=f.sample_type,
                sample_start_time=f.sample_start_time,
                sample_end_time=f.sample_end_time
            )
            create_media_asset(db, media_asset_data)

        db.commit()

        return PostMediaVideoPresignResponse(uploads=uploads)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"アップロードURL生成エラーが発生しました: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/presign-image-upload")
async def presign_update_image_upload(
    request: UpdateMediaImagePresignRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """画像のアップロードURLを更新

    Args:
        request (UpdateMediaImagePresignRequest): リクエストデータ
        user (Users): ユーザー
        db (Session): データベースセッション

    Raises:
        HTTPException: エラー

    Returns:
        PostMediaImagePresignResponse: アップロードURL
    """
    try:
        post = get_post_by_id(db, request.post_id)
        if not post:
            raise HTTPException(404, f"post not found: {request.post_id}")

        validate_kinds(request.files, ALLOWED_IMAGE_KINDS)

        uploads: Dict[ImageKind, Union[PresignResponseItem, List[PresignResponseItem]]] = {}
        
        for f in request.files:
            # 既存メディアアセットを取得
            existing_assets = get_media_assets_by_post_id_and_kind(
                db, str(request.post_id), KIND_MAPPING[f.kind]
            )

            # 新しいstorage_keyとpresigned URLを生成
            response = generate_image_presign(
                f.kind, str(user.id), str(request.post_id), f.ext, f.content_type
            )
            new_key = response["key"]

            # リソースと承認フラグを決定
            resource = get_image_resource_and_approved_flag(
                f.kind, post['authenticated_flg']
            )

            # 既存のメディアアセットがある場合は削除
            if existing_assets:
                # 既存ファイルをS3から削除
                delete_existing_media_file(
                    existing_assets.storage_key, resource, post['authenticated_flg'], is_video=False
                )

                # 古いメディアアセットをDBから削除
                delete_media_asset(db, existing_assets.id)

            # レスポンスに追加
            uploads[f.kind] = create_presign_response_item(response)

            # 新しいメディアアセットを作成
            media_asset_data = create_media_asset_data(
                str(request.post_id), f.kind, new_key, f.orientation,
                f.content_type, MediaAssetStatus.RESUBMIT
            )
            create_media_asset(db, media_asset_data)
            db.commit()

        return PostMediaImagePresignResponse(uploads=uploads)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"アップロードURL更新エラーが発生しました: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/presign-video-upload")
async def presign_update_video_upload(
    request: UpdateMediaVideoPresignRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """動画のアップロードURLを更新

    Args:
        request (UpdateMediaVideoPresignRequest): リクエストデータ
        user (Users): ユーザー
        db (Session): データベースセッション

    Raises:
        HTTPException: エラー

    Returns:
        PostMediaVideoPresignResponse: アップロードURL
    """
    try:
        post = get_post_by_id(db, request.post_id)
        if not post:
            raise HTTPException(404, f"post not found: {request.post_id}")

        validate_kinds(request.files, ALLOWED_VIDEO_KINDS)

        uploads: Dict[VideoKind, PresignResponseItem] = {}
        
        for f in request.files:
            # 既存メディアアセットを取得
            existing_assets = get_media_assets_by_post_id_and_kind(
                db, str(request.post_id), KIND_MAPPING[f.kind]
            )

            if not existing_assets:
                raise HTTPException(
                    404, f"media assets not found: {request.post_id}, {f.kind}"
                )

            # 新しいstorage_keyとpresigned URLを生成
            response = generate_video_presign(
                str(user.id), str(request.post_id), f.ext, f.kind, f.content_type
            )
            new_key = response["key"]

            # リソースと承認フラグを決定
            resource = get_video_resource_and_approved_flag(post['authenticated_flg'])

            # 既存ファイルをS3から削除
            delete_existing_media_file(
                existing_assets.storage_key, resource, post['authenticated_flg'], is_video=True
            )

            # 古いメディアアセットをDBから削除
            if post['authenticated_flg'] == AuthenticatedFlag.AUTHENTICATED:
                delete_media_rendition_job(db, existing_assets.id)
                
            delete_media_asset(db, existing_assets.id)

            # レスポンスに追加
            uploads[f.kind] = create_presign_response_item(response)

            # 新しいメディアアセットを作成
            media_asset_data = create_media_asset_data(
                str(request.post_id), f.kind, new_key, f.orientation,
                f.content_type, MediaAssetStatus.RESUBMIT,
                sample_type=f.sample_type,
                sample_start_time=f.sample_start_time,
                sample_end_time=f.sample_end_time
            )
            create_media_asset(db, media_asset_data)
            db.commit()

        return PostMediaVideoPresignResponse(uploads=uploads)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"アップロードURL更新エラーが発生しました: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/media-asset/{media_asset_id}")
async def delete_media_asset_by_id(
    media_asset_id: str,
    user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """メディアアセットを削除

    Args:
        media_asset_id (str): メディアアセットID
        user (Users): 現在のユーザー
        db (Session): データベースセッション

    Returns:
        Dict[str, str]: 削除結果

    Raises:
        HTTPException: メディアアセットが見つからない場合、投稿が見つからない場合、
                       所有権がない場合、削除処理でエラーが発生した場合
    """
    try:
        # メディアアセットを取得
        asset = get_media_asset_by_id(db, media_asset_id)
        if not asset:
            raise HTTPException(
                status_code=404,
                detail=f"Media asset not found: {media_asset_id}"
            )

        # 投稿を取得
        post = get_post_by_id(db, str(asset.post_id))
        if not post:
            raise HTTPException(
                status_code=404,
                detail=f"Post not found: {asset.post_id}"
            )

        # 投稿の所有権を確認
        _verify_post_ownership(post, user)

        # リソースを決定
        resource = _determine_resource_for_asset(
            asset.kind,
            post['authenticated_flg']
        )

        # S3から削除
        is_video = asset.kind in [
            MediaAssetKind.MAIN_VIDEO,
            MediaAssetKind.SAMPLE_VIDEO
        ]
        delete_existing_media_file(
            asset.storage_key,
            resource,
            post['authenticated_flg'],
            is_video=is_video
        )

        # DBから削除
        delete_media_asset(db, asset.id)
        db.commit()

        return {
            "status": "success",
            "message": "Media asset deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"メディアアセット削除エラー: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to delete media asset"
        )

@router.put("/update-images")
async def update_images(
    request: UpdateImagesPresignRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """画像投稿の更新（複数画像の追加/削除対応）

    Args:
        request (UpdateImagesPresignRequest): リクエストデータ
        user: ユーザー
        db (Session): データベースセッション

    Returns:
        UpdateImagesPresignResponse: アップロードURL一覧
    """
    try:
        # 投稿の存在確認
        post = get_post_by_id(db, request.post_id)
        if not post:
            raise HTTPException(404, f"post not found: {request.post_id}")

        # 指定されたIDの画像を削除
        if request.delete_image_ids:
            resource = get_image_resource_and_approved_flag(
                "images", post['authenticated_flg']
            )

            for image_id in request.delete_image_ids:
                asset = get_media_asset_by_id(db, image_id)

                if not asset:
                    logger.error(f"Warning: media asset not found: {image_id}")
                    continue

                # 投稿IDが一致するか確認
                if str(asset.post_id) != str(request.post_id):
                    raise HTTPException(
                        403, 
                        f"Unauthorized: asset {image_id} does not belong to post {request.post_id}"
                    )

                # kindがIMAGESであることを確認
                if asset.kind != MediaAssetKind.IMAGES:
                    logger.error(f"Warning: asset {image_id} is not an image (kind={asset.kind})")
                    continue

                # S3から削除
                if asset.storage_key:
                    delete_existing_media_file(
                        asset.storage_key, resource, post['authenticated_flg'], is_video=False
                    )

                # DBから削除
                delete_media_asset(db, asset.id)

        # 新しい画像を追加
        uploads = []
        for img in request.add_images:
            response = generate_image_presign(
                "images", str(user.id), str(request.post_id), img.ext, img.content_type
            )
            new_key = response["key"]

            uploads.append(create_presign_response_item(response))

            # 新しいメディアアセットをDBに作成
            media_asset_data = create_media_asset_data(
                str(request.post_id), "images", new_key, img.orientation,
                img.content_type, MediaAssetStatus.RESUBMIT
            )
            create_media_asset(db, media_asset_data)

        db.commit()

        return UpdateImagesPresignResponse(uploads=uploads)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"画像更新エラー: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/trigger-batch-process", response_model=TriggerBatchProcessResponse)
async def trigger_batch_process(
    request: TriggerBatchProcessRequest,
    background_tasks: BackgroundTasks,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    バッチ処理をトリガーする（バックグラウンド実行）
    - tmpバケットの動画をmainバケットへ移動
    - need_trim=Trueの場合、FFmpegでサンプル動画を切り取り

    Args:
        request: バッチ処理リクエスト
        background_tasks: FastAPIバックグラウンドタスク
        user: 現在のユーザー
        db: データベースセッション

    Returns:
        TriggerBatchProcessResponse: 処理状態
    """
    try:
        # バリデーション
        if request.need_trim:
            if request.start_time is None or request.end_time is None:
                raise HTTPException(
                    400,
                    "need_trim=Trueの場合、start_timeとend_timeは必須です"
                )
            if request.start_time >= request.end_time:
                raise HTTPException(
                    400,
                    "start_timeはend_timeより小さい値である必要があります"
                )

        logger.info(f"バッチ処理トリガー: user_id={user.id}, post_id={request.post_id}, tmp_key={request.tmp_storage_key}")

        # バックグラウンドタスクとしてバッチ処理を登録
        background_tasks.add_task(
            execute_batch_process,
            post_id=str(request.post_id),
            user_id=str(user.id),
            tmp_storage_key=request.tmp_storage_key,
            need_trim=request.need_trim,
            start_time=request.start_time,
            end_time=request.end_time
        )

        return TriggerBatchProcessResponse(
            status="processing",
            message="バッチ処理を開始しました",
            tmp_storage_key=request.tmp_storage_key
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"バッチ処理トリガーエラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def execute_batch_process(
    post_id: str,
    user_id: str,
    tmp_storage_key: str,
    need_trim: bool,
    start_time: float = None,
    end_time: float = None,
):
    """
    バッチ処理を実行（バックグラウンド）
    - tmpバケットから動画をダウンロード
    - 必要に応じてFFmpegでトリミング
    - mainバケットとsampleバケットにアップロード

    Args:
        post_id: 投稿ID
        user_id: ユーザーID
        tmp_storage_key: tmpバケットのストレージキー
        need_trim: トリミングが必要か
        start_time: トリミング開始時間（秒）
        end_time: トリミング終了時間（秒）
    """
    try:
        logger.info(f"バッチ処理開始: post_id={post_id}, tmp_key={tmp_storage_key}")

        # keygen関数でoutput_keyを生成
        main_output_key = post_media_video_key(user_id, post_id, "mp4", "main")
        sample_output_key = post_media_video_key(user_id, post_id, "mp4", "sample")

        logger.info(f"生成されたキー: main={main_output_key}, sample={sample_output_key}")

        # 環境変数を設定してバッチスクリプトを実行
        env = os.environ.copy()
        env["TEMP_VIDEO_BUCKET"] = INGEST_BUCKET_NAME  # tmpバケット
        env["TEMP_VIDEO_DESTINATION"] = tmp_storage_key
        env["MAIN_VIDEO_BUCKET"] = INGEST_BUCKET_NAME  # 審査用バケット
        env["MAIN_VIDEO_DESTINATION"] = main_output_key
        env["SAMPLE_VIDEO_BUCKET"] = INGEST_BUCKET_NAME  # 審査用バケット
        env["SAMPLE_VIDEO_DESTINATION"] = sample_output_key
        env["NEED_TRIM"] = "1" if need_trim else "0"
        env["START_TIME"] = str(start_time) if start_time is not None else "0.0"
        env["END_TIME"] = str(end_time) if end_time is not None else "0.0"
        env["AWS_REGION"] = AWS_REGION
        env["AWS_ACCESS"] = AWS_ACCESS_KEY_ID
        env["AWS_SECRET"] = AWS_SECRET_ACCESS_KEY
        env["KMS_ARN"] = KMS_ALIAS_INGEST if hasattr(settings, 'KMS_ALIAS_INGEST') else ""

        # バッチスクリプトのディレクトリとファイルパスを取得
        # app/api/endpoints/customer/ から mij-api/batchs へ移動
        batch_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__),
            "../../../../batchs/batch-main-sample-video"
        ))
        batch_script = "main.py"

        logger.info(f"バッチディレクトリ: {batch_dir}")

        # ディレクトリの存在確認
        if not os.path.exists(batch_dir):
            raise FileNotFoundError(f"バッチディレクトリが見つかりません: {batch_dir}")

        # バッチスクリプトのディレクトリから実行（相対インポート対応）
        result = subprocess.run(
            ["python", batch_script],
            env=env,
            cwd=batch_dir,  # 作業ディレクトリを変更
            capture_output=True,
            text=True,
            check=True
        )

        logger.info(f"バッチ処理完了: {result.stdout}")

    except subprocess.CalledProcessError as e:
        logger.error(f"バッチ処理エラー: {e.stderr}")
        raise
    except Exception as e:
        logger.error(f"バッチ処理予期しないエラー: {e}")
        raise
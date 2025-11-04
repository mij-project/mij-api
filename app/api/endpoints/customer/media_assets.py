from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from app.services.s3.presign import presign_put_public, presign_put
from app.schemas.post_media import (
    PostMediaImagePresignRequest,
    PostMediaVideoPresignRequest,
    ImageKind,
    PostMediaImagePresignResponse,
    PostMediaVideoPresignResponse,
    VideoKind
)
from app.deps.auth import get_current_user
from app.db.base import get_db
from app.services.s3.keygen import post_media_image_key, post_media_video_key
from app.schemas.commons import PresignResponseItem, UploadItem
from typing import Dict, List, Union
from app.services.s3.client import delete_object, delete_hls_directory
from app.crud.media_assets_crud import create_media_asset, get_media_assets_by_post_id, update_media_asset
from app.models.posts import Posts
from app.models.media_assets import MediaAssets
from app.constants.enums import MediaAssetKind, MediaAssetOrientation, MediaAssetStatus, PostStatus
from app.services.s3.client import MEDIA_BUCKET_NAME

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
        allowed_kinds =  {"ogp","thumbnail","images"}

        seen = set()
        for f in request.files:
            if f.kind not in allowed_kinds:
                raise HTTPException(400, f"unsupported kind: {f.kind}")
            if f.kind != "images" and f.kind in seen:
                raise HTTPException(400, f"duplicated kind: {f.kind}")
            seen.add(f.kind)

        uploads: Dict[ImageKind, Union[PresignResponseItem, List[PresignResponseItem]]] = {}
        updated_posts = set()  # 更新された投稿IDを保存

        for f in request.files:
            key = post_media_image_key(f.kind, str(user.id), str(f.post_id), f.ext)

            if f.kind == "images":
                response = presign_put("ingest", key, f.content_type)
            else:
                response = presign_put_public("public", key, f.content_type)

            if f.kind == "images":
                if f.kind not in uploads:
                    uploads[f.kind] = []
                uploads[f.kind].append(PresignResponseItem(
                    key=response["key"],
                    upload_url=response["upload_url"],
                    expires_in=response["expires_in"],
                    required_headers=response["required_headers"]
                ))
            else:
                uploads[f.kind] = PresignResponseItem(
                    key=response["key"],
                    upload_url=response["upload_url"],
                    expires_in=response["expires_in"],
                    required_headers=response["required_headers"]
                )
            
            # メディアアセット作成
            media_asset_data = {
                "post_id": f.post_id,
                "kind": KIND_MAPPING[f.kind],
                "storage_key": key,
                "orientation": ORIENTATION_MAPPING[f.orientation],
                "mime_type": f.content_type,
                "status": MediaAssetStatus.PENDING,
                "bytes": 0,
            }
            media_asset = create_media_asset(db, media_asset_data)
            updated_posts.add(f.post_id)

        db.commit()
        
        # 更新された投稿をrefresh
        for post_id in updated_posts:
            post = db.query(Posts).filter(Posts.id == post_id).first()
            if post:
                db.refresh(post)
                db.refresh(media_asset)

        return PostMediaImagePresignResponse(uploads=uploads)
    except Exception as e:
        print("アップロードURL生成エラーが発生しました", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/presign-video-upload")
async def presign_post_media_video(
    request: PostMediaVideoPresignRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """動画のアップロードURLを生成

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
        allowed_kinds = {"main","sample"}

        seen = set()
        for f in request.files:
            if f.kind not in allowed_kinds:
                raise HTTPException(400, f"unsupported kind: {f.kind}")
            if f.kind != "images" and f.kind in seen:
                raise HTTPException(400, f"duplicated kind: {f.kind}")
            seen.add(f.kind)

        uploads: Dict[VideoKind, UploadItem] = {}

        for f in request.files:
            key = post_media_video_key(str(user.id), str(f.post_id), f.ext, f.kind)

            response = presign_put("ingest", key, f.content_type)

            uploads[f.kind] = PresignResponseItem(
                key=response["key"],
                upload_url=response["upload_url"],
                expires_in=response["expires_in"],
                required_headers=response["required_headers"]
            )
            media_asset_data = {
                "post_id": f.post_id,
                "kind": KIND_MAPPING[f.kind],
                "orientation": ORIENTATION_MAPPING[f.orientation],
                "storage_key": key,
                "mime_type": f.content_type,
                "bytes": 0,
                "status": MediaAssetStatus.PENDING,
            }
            media_asset = create_media_asset(db, media_asset_data)

        db.commit()
        db.refresh(media_asset)

        return PostMediaVideoPresignResponse(uploads=uploads)
    except Exception as e:
        print("アップロードURL生成エラーが発生しました", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/presign-image-upload")
async def presign_post_media_image(
    request: PostMediaImagePresignRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """画像のアップロードURLを更新

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
        allowed_kinds = {"ogp","thumbnail","images"}

        seen = set()
        uploads: Dict[ImageKind, Union[PresignResponseItem, List[PresignResponseItem]]] = {}
        for f in request.files:
            if f.kind not in allowed_kinds:
                raise HTTPException(400, f"unsupported kind: {f.kind}")
            if f.kind != "images" and f.kind in seen:
                raise HTTPException(400, f"duplicated kind: {f.kind}")
            seen.add(f.kind)

            # postsテーブルからステータスを取得してバケットを判断
            post = db.query(Posts).filter(Posts.id == f.post_id).first()
            if not post:
                raise HTTPException(404, f"post not found: {f.post_id}")

            #　post_idと同じkindの既存メディアアセットをすべて取得
            existing_assets = db.query(MediaAssets).filter(
                MediaAssets.post_id == f.post_id,
                MediaAssets.kind == KIND_MAPPING[f.kind]
            ).all()

            if not existing_assets:
                raise HTTPException(404, f"media assets not found: {f.post_id}, {f.kind}")

            # 新しいstorage_keyを生成
            new_key = post_media_image_key(f.kind, str(user.id), str(f.post_id), f.ext)

            #　既存のすべてのファイルをs3から削除
            # imagesは常にingestバケット、その他はpostsのstatusで判断
            if f.kind == "images":
                bucket = "ingest"
            else:
                # 承認済みの場合はMEDIA_BUCKET_NAME、それ以外はpublic
                bucket = MEDIA_BUCKET_NAME if post.status == PostStatus.APPROVED else "public"

            for old_asset in existing_assets:
                if old_asset.storage_key:
                    try:
                        # 変換済みファイル（.m3u8）の場合、関連ファイルも削除
                        if old_asset.storage_key.endswith('.m3u8'):
                            # HLSの関連ファイル（.tsセグメント、プレイリストなど）をディレクトリごと削除
                            delete_hls_directory(bucket, old_asset.storage_key)
                        else:
                            # 通常のファイル（.mp4など）を削除
                            delete_object(bucket, old_asset.storage_key)
                        print(f"Deleted old file: {old_asset.storage_key}")
                    except Exception as e:
                        print(f"Failed to delete old file from S3: {e}")
                        # 削除に失敗しても処理を継続

                # 古いメディアアセットをDBから削除
                db.delete(old_asset)

            # 新しいファイル用のpresigned URLを生成
            if f.kind == "images":
                response = presign_put("ingest", new_key, f.content_type)
            else:
                response = presign_put_public("public", new_key, f.content_type)

            if f.kind == "images":
                uploads[f.kind] = PresignResponseItem(
                    key=response["key"],
                    upload_url=response["upload_url"],
                    expires_in=response["expires_in"],
                    required_headers=response["required_headers"]
                )
            else:
                uploads[f.kind] = PresignResponseItem(
                    key=response["key"],
                    upload_url=response["upload_url"],
                    expires_in=response["expires_in"],
                    required_headers=response["required_headers"]
                )

            # 新しいメディアアセットを作成（古いものは削除済み）
            media_asset_data = {
                "post_id": f.post_id,
                "kind": KIND_MAPPING[f.kind],
                "storage_key": new_key,
                "orientation": ORIENTATION_MAPPING[f.orientation],
                "mime_type": f.content_type,
                "status": MediaAssetStatus.RESUBMIT,
                "bytes": 0,
            }
            media_asset = create_media_asset(db, media_asset_data)
            db.flush()

        return PostMediaImagePresignResponse(uploads=uploads)
    except Exception as e:
        print("アップロードURL更新エラーが発生しました", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/presign-video-upload")
async def presign_post_media_video(
    request: PostMediaVideoPresignRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """動画のアップロードURLを更新

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
        allowed_kinds = {"main","sample"}

        seen = set()
        uploads: Dict[VideoKind, UploadItem] = {}
        for f in request.files:
            if f.kind not in allowed_kinds:
                raise HTTPException(400, f"unsupported kind: {f.kind}")
            if f.kind != "images" and f.kind in seen:
                raise HTTPException(400, f"duplicated kind: {f.kind}")
            seen.add(f.kind)

            # postsテーブルからステータスを取得してバケットを判断
            post = db.query(Posts).filter(Posts.id == f.post_id).first()
            if not post:
                raise HTTPException(404, f"post not found: {f.post_id}")

            #　post_idと同じkindの既存メディアアセットをすべて取得
            existing_assets = db.query(MediaAssets).filter(
                MediaAssets.post_id == f.post_id,
                MediaAssets.kind == KIND_MAPPING[f.kind]
            ).all()

            if not existing_assets:
                raise HTTPException(404, f"media assets not found: {f.post_id}, {f.kind}")

            # 新しいstorage_keyを生成
            new_key = post_media_video_key(str(user.id), str(f.post_id), f.ext, f.kind)

            #　既存のすべてのファイルをs3から削除
            # 承認済みの場合はMEDIA_BUCKET_NAME、それ以外はingest
            bucket = MEDIA_BUCKET_NAME if post.status == PostStatus.APPROVED else "ingest"

            for old_asset in existing_assets:
                if old_asset.storage_key:
                    try:
                        # 変換済みファイル（.m3u8）の場合、関連ファイルも削除
                        if old_asset.storage_key.endswith('.m3u8'):
                            # HLSの関連ファイル（.tsセグメント、プレイリストなど）をディレクトリごと削除
                            delete_hls_directory(bucket, old_asset.storage_key)
                        else:
                            # 通常のファイル（.mp4など）を削除
                            delete_object(bucket, old_asset.storage_key)
                        print(f"Deleted old video file: {old_asset.storage_key}")
                    except Exception as e:
                        print(f"Failed to delete old video file from S3: {e}")
                        # 削除に失敗しても処理を継続

                # 古いメディアアセットをDBから削除
                db.delete(old_asset)

            #　新しいファイル用のpresigned URLを生成
            response = presign_put("ingest", new_key, f.content_type)
            uploads[f.kind] = PresignResponseItem(
                key=response["key"],
                upload_url=response["upload_url"],
                expires_in=response["expires_in"],
                required_headers=response["required_headers"]
            )

            # 新しいメディアアセットを作成（古いものは削除済み）
            media_asset_data = {
                "post_id": f.post_id,
                "kind": KIND_MAPPING[f.kind],
                "storage_key": new_key,
                "orientation": ORIENTATION_MAPPING[f.orientation],
                "mime_type": f.content_type,
                "bytes": 0,
                "status": MediaAssetStatus.RESUBMIT,
            }
            media_asset = create_media_asset(db, media_asset_data)
            db.flush()

        return PostMediaVideoPresignResponse(uploads=uploads)
    except Exception as e:
        print("アップロードURL更新エラーが発生しました", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

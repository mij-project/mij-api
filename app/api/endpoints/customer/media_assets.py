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
from app.crud.media_assets_crud import create_media_asset
from app.models.posts import Posts
from app.constants.enums import MediaAssetKind, MediaAssetOrientation, MediaAssetStatus

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

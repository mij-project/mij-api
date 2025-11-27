from fastapi import APIRouter
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.constants.enums import GenerationMediaKind
from app.crud.generation_media_crud import get_generation_media_by_post_id, create_generation_media
from app.crud.post_crud import get_post_detail_by_id
from app.constants.enums import MediaAssetKind
from app.services.s3.image_screening import generate_ogp_image
from app.services.s3.client import upload_ogp_image_to_s3
from app.services.s3.keygen import post_media_image_key
from fastapi import APIRouter, Depends, HTTPException
from os import getenv
CDN_BASE_URL = getenv("CDN_BASE_URL")

router = APIRouter()

@router.post("/create/{post_id}")
async def create_generation_media_endpoint(
    post_id: str,
    db: Session = Depends(get_db)
):
    """生成メディアを作成する"""
    try:
        # 3. OGP画像が存在しない場合は動的に生成
        post_data = get_post_detail_by_id(db, post_id, user_id=None)
        if not post_data:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        # 投稿情報を取得
        creator = post_data["creator"]
        creator_profile = post_data["creator_profile"]
        media_assets = post_data["media_assets"]

        # サムネイル画像を取得
        thumbnail_key = None
        for media_asset in media_assets:
            if media_asset.kind == MediaAssetKind.THUMBNAIL:
                thumbnail_key = media_asset.storage_key
                break

        if not thumbnail_key:
            raise HTTPException(status_code=404, detail="サムネイル画像が見つかりません")

        thumbnail_url = f"{CDN_BASE_URL}/{thumbnail_key}"

        # アバター画像を取得
        avatar_url = None
        if creator_profile and creator_profile.avatar_url:
            avatar_url = f"{CDN_BASE_URL}/{creator_profile.avatar_url}"

        # プロフィール名とユーザー名
        profile_name = creator.profile_name if creator else creator.email
        username = creator_profile.username if creator_profile else creator.email

        # 4. OGP画像を生成
        ogp_image_data = generate_ogp_image(
            thumbnail_url=thumbnail_url,
            avatar_url=avatar_url,
            profile_name=profile_name,
            username=username
        )

        # 5. S3キーを生成
        s3_key = post_media_image_key(
            kind="generation-ogp",
            creator_id=str(creator.id),
            post_id=post_id,
            ext="png"
        )

        # 6. S3にアップロード
        upload_ogp_image_to_s3(s3_key, ogp_image_data)

        # 7. generation_mediaテーブルに保存
        generation_data = {
            "kind": GenerationMediaKind.POST_IMAGE,
            "user_id": None,
            "post_id": post_id,
            "storage_key": s3_key
        }
        create_generation_media(db, generation_data)
        db.commit()

        return
    except Exception as e:
        print(f"生成メディア作成エラーが発生しました: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
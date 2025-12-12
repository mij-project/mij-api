from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.schemas.creator import (
    CreatorCreate,
    CreatorUpdate,
    CreatorOut,
    IdentityVerificationOut,
)
from app.db.base import get_db
from app.crud.creator_crud import (
    create_creator,
    update_creator,
    get_creator_by_user_id,
    get_identity_verification_by_user_id,
)
from app.deps.auth import get_current_user
from app.crud.gender_crud import get_gender_by_slug
from app.crud.followes_crud import get_follower_count
from app.models.creator_type import CreatorType
from app.crud.post_crud import get_total_likes_by_user_id, get_posts_count_by_user_id
from app.crud.creator_crud import get_creators
from typing import List
from os import getenv
from app.core.logger import Logger

logger = Logger.get_logger()
BASE_URL = getenv("CDN_BASE_URL")

router = APIRouter()


@router.post("/register", response_model=CreatorOut)
def register_creator(
    creator_create: CreatorCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    クリエイター登録

    Args:
        creator_create (CreatorCreate): クリエイター登録情報
        user_id (UUID): ユーザーID
        db (Session): データベースセッション

    Returns:
        CreatorOut: クリエイター情報
    """
    try:
        existing_creator = get_creator_by_user_id(db, user.id)
        if existing_creator:
            raise HTTPException(status_code=400, detail="Creator already registered")

        creater = create_creator(db, creator_create, user.id)

        # 性別を取得
        genders = get_gender_by_slug(db, creator_create.gender_slug)
        insert_data = [
            {
                "user_id": user.id,
                "gender_id": gender_obj.id,
            }
            for gender_obj in genders
        ]
        db.bulk_insert_mappings(CreatorType, insert_data)

        # 変更をコミット
        db.commit()

        # コミット後にリフレッシュ
        db.refresh(creater)
        return creater
    except Exception as e:
        logger.error("クリエイター登録エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/profile", response_model=CreatorOut)
def update_creator_profile(
    creator_update: CreatorUpdate, user_id: UUID, db: Session = Depends(get_db)
):
    """
    クリエイタープロフィール更新

    Args:
        creator_update (CreatorUpdate): クリエイター更新情報
        user_id (UUID): ユーザーID
        db (Session): データベースセッション

    Returns:
        CreatorOut: 更新されたクリエイター情報
    """
    try:
        return update_creator(db, user_id, creator_update)
    except Exception as e:
        logger.error("クリエイタープロフィール更新エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/verification-status", response_model=IdentityVerificationOut)
def get_verification_status(user_id: UUID, db: Session = Depends(get_db)):
    """
    本人確認ステータス取得

    Args:
        user_id (UUID): ユーザーID
        db (Session): データベースセッション

    Returns:
        IdentityVerificationOut: 本人確認情報
    """
    try:
        verification = get_identity_verification_by_user_id(db, user_id)
        if not verification:
            raise HTTPException(
                status_code=404, detail="Identity verification not found"
            )
        return verification
    except Exception as e:
        logger.error("本人確認ステータス取得エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile", response_model=CreatorOut)
def get_creator_profile(user_id: UUID, db: Session = Depends(get_db)):
    """
    クリエイタープロフィール取得

    Args:
        user_id (UUID): ユーザーID
        db (Session): データベースセッション

    Returns:
        CreatorOut: クリエイター情報
    """
    try:
        # クリエイターを取得
        creator = get_creator_by_user_id(db, user_id)

        if not creator:
            raise HTTPException(status_code=404, detail="Creator not found")

        # フォロワー数を取得
        follower_count = get_follower_count(db, user_id)

        # いいね数を取得
        likes_count = get_total_likes_by_user_id(db, user_id)

        # 各種投稿数を取得
        posts_count = get_posts_count_by_user_id(db, user_id)

        return {
            "creator": creator,
            "follower_count": follower_count,
            "likes_count": likes_count,
            "posts_count": posts_count,
        }
    except Exception as e:
        logger.error("クリエイタープロフィール取得エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=List)
def get_creator_list(db: Session = Depends(get_db)):
    try:
        creators = get_creators(db, limit=50)
        return [
            {
                "id": str(creator.id),
                "name": creator.profile_name,
                "username": creator.username,
                "followers_count": creator.followers_count,
                "avatar_url": f"{BASE_URL}/{creator.avatar_url}"
                if creator.avatar_url
                else None,
            }
            for creator in creators
        ]
    except Exception as e:
        logger.error("クリエイター一覧取得エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))

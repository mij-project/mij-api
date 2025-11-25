import re
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_user_optional
from app.constants.enums import PostStatus
from app.models.user import Users
from app.schemas.post import PostCreateRequest, PostResponse, NewArrivalsResponse, PostUpdateRequest, PostOGPResponse
from app.constants.enums import PostVisibility, PostType, PlanStatus, PriceType, MediaAssetKind
from app.crud.post_crud import create_post, get_post_detail_by_id, update_post, get_post_ogp_image_url, get_post_ogp_data
from app.crud.plan_crud import create_plan
from app.crud.price_crud import create_price, delete_price_by_post_id
from app.crud.post_plans_crud import create_post_plan, delete_plan_by_post_id
from app.crud.tags_crud import exit_tag, create_tag
from app.crud.post_tags_crud import create_post_tag, delete_post_tags_by_post_id
from app.crud.post_categories_crud import create_post_category, delete_post_categories_by_post_id
from app.crud.post_crud import get_recent_posts
from app.crud.entitlements_crud import check_entitlement
from app.crud.generation_media_crud import get_generation_media_by_post_id, create_generation_media
from app.models.tags import Tags
from app.services.s3.image_screening import generate_ogp_image
from app.services.s3.client import upload_ogp_image_to_s3
from app.services.s3.keygen import post_media_image_key
from typing import List
from app.constants.enums import GenerationMediaKind
import os
from os import getenv
from datetime import datetime, timezone
from app.api.commons.utils import get_video_duration
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()

# PostTypeの文字列からenumへのマッピングを定義
POST_TYPE_MAPPING = {
    "video": PostType.VIDEO,
    "image": PostType.IMAGE,
}


BASE_URL = getenv("CDN_BASE_URL")
MEDIA_CDN_URL = os.getenv("MEDIA_CDN_URL")
CDN_BASE_URL = os.getenv("CDN_BASE_URL")

@router.post("/create", response_model=PostResponse)
async def create_post_endpoint(
    post_create: PostCreateRequest,
    user = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """投稿を作成する"""
    try:
        # 可視性を判定
        visibility = _determine_visibility(post_create.single, post_create.plan)
        
        # 関連オブジェクトを初期化
        price = None
        plan_posts = []
        category_posts = []
        tag_posts = []
        
        # 投稿を作成
        post = _create_post(db, post_create, user.id, visibility)
        
        # 単品販売の場合、価格を登録
        if post_create.single:
            price = _create_price(db, post.id, post_create.price)

        # プランの場合、プランを登録
        if post_create.plan:
            plan_posts = _create_plan(db, post.id, post_create.plan_ids)
        
        # カテゴリを投稿に紐づけ
        if post_create.category_ids:
            category_posts = _create_post_categories(db, post.id, post_create.category_ids)
        
        # タグを投稿に紐づけ
        if post_create.tags:
            tag_posts = _create_post_tag(db, post.id, post_create.tags)
        
        # データベースをコミット
        db.commit()
        
        # オブジェクトをリフレッシュ
        _refresh_related_objects(
            db, post, price, plan_posts, category_posts, tag_posts
        )
        
        return post
        
    except Exception as e:
        db.rollback()
        logger.error("投稿作成エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/update")
async def update_post_endpoint(
    request_data: PostUpdateRequest,
    current_user: Users = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """投稿を更新する"""
    try:
        # 投稿を更新
        # 可視性を判定
        visibility = _determine_visibility(request_data.single, request_data.plan)
        
        # 関連オブジェクトを初期化
        price = None
        plan_posts = []
        category_posts = []
        tag_posts = []
        
        # 投稿を更新
        post = _update_post(db, request_data, current_user.id, visibility)
        
        # 単品販売の場合、価格をデリートインサート
        if request_data.single:
            delete_price_by_post_id(db, request_data.post_id)
            price = _create_price(db, request_data.post_id, request_data.price)

        # プランの場合、プランをデリートインサート
        if request_data.plan:
            delete_plan_by_post_id(db, request_data.post_id)
            plan_posts = _create_plan(db, request_data.post_id, request_data.plan_ids)

        
        # カテゴリをデリートインサート
        if request_data.category_ids:
            delete_post_categories_by_post_id(db, request_data.post_id)
            category_posts = _create_post_categories(db, request_data.post_id, request_data.category_ids)

        
        # タグをデリートインサート
        if request_data.tags:
            delete_post_tags_by_post_id(db, request_data.post_id)
            tag_posts = _create_post_tag(db, request_data.post_id, request_data.tags)

        
        # データベースをコミット
        db.commit()
        
        # オブジェクトをリフレッシュ
        _refresh_related_objects(
            db, post, price, plan_posts, category_posts, tag_posts
        )
        
        return post
    except Exception as e:
        logger.error("投稿更新エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/detail")
async def get_post_detail(
    post_id: str = Query(..., description="投稿ID"),
    user = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    try:
        # CRUD関数を使用して投稿詳細を取得
        user_id = user.id if user else None

        post_data = get_post_detail_by_id(db, post_id, user_id)

        if not post_data:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        # クリエイター情報を整形
        creator_info = _format_creator_info(post_data["creator"], post_data["creator_profile"])

        # メディア情報を整形
        media_info, thumbnail_key = _format_media_info(post_data["media_assets"], post_data["is_entitlement"])

        # カテゴリ情報を整形
        categories_data = _format_categories_info(post_data["categories"])

        # 販売情報を整形
        sale_info = _format_sale_info(post_data["price"], post_data["plans"])

        # 投稿詳細を整形
        post_detail = {
            "id": str(post_data["post"].id),
            "post_type": post_data["post"].post_type,
            "description": post_data["post"].description,
            "thumbnail_key": thumbnail_key,
            "creator": creator_info,
            "categories": categories_data,
            "media_info": media_info,
            "sale_info": sale_info,
        }
        
        return post_detail
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("投稿詳細取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/new-arrivals" , response_model=List[NewArrivalsResponse])
async def get_new_arrivals(
    db: Session = Depends(get_db)
):
    try:
        recent_posts = get_recent_posts(db, limit=50)
        return [NewArrivalsResponse(
            id=str(post.Posts.id),
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            creator_name=post.profile_name,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            duration=get_video_duration(post.duration_sec) if post.duration_sec else None,
            likes_count=post.likes_count or 0
        ) for post in recent_posts]
    except Exception as e:
        logger.error("新着投稿取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{post_id}/ogp-image", response_model=PostOGPResponse)
async def get_post_ogp_image(
    post_id: str,
    db: Session = Depends(get_db)
):
    """投稿のOGP情報を取得する（Lambda@Edge用）"""
    try:
        # OGP情報を取得（投稿詳細 + クリエイター情報 + OGP画像）
        ogp_data = get_post_ogp_data(db, post_id)

        if not ogp_data:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        return ogp_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("OGP画像URL取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

# utils
def _determine_visibility(single: bool, plan: bool) -> int:
    """投稿の可視性を判定する"""
    if single and plan:
        return PostVisibility.BOTH
    elif single:
        return PostVisibility.SINGLE
    elif plan:
        return PostVisibility.PLAN
    else:
        return PostVisibility.SINGLE  # デフォルト

def _create_post(db: Session, post_data: dict, user_id: str, visibility: int):
    """投稿を作成する"""
    post_data = {
        "creator_user_id": user_id,
        "description": post_data.description,
        "scheduled_at": post_data.formattedScheduledDateTime if post_data.scheduled else None,
        "expiration_at": post_data.expirationDate if post_data.expiration else None,
        "visibility": visibility,
        "post_type": POST_TYPE_MAPPING.get(post_data.post_type),
    }
    return create_post(db, post_data)

def _create_post_categories(db: Session, post_id: str, category_ids: list):
    """投稿にカテゴリを紐づける"""
    category_posts = []
    for category_id in category_ids:
        category_data = {
            "post_id": post_id,
            "category_id": category_id,
        }
        category_post = create_post_category(db, category_data)
        category_posts.append(category_post)
    return category_posts

def _create_post_tag(db: Session, post_id: str, tag_name: str):
    """投稿にタグを紐づける"""
    # タグが存在するか確認
    existing_tag = exit_tag(db, tag_name)
    
    if not existing_tag:
        tag_data = {
            "slug": tag_name,
            "name": tag_name,
        }
        tag = create_tag(db, tag_data)
    else:
        tag = db.query(Tags).filter(Tags.name == tag_name).first()
    
    # タグと投稿の中間テーブルに登録
    post_tag_data = {
        "post_id": post_id,
        "tag_id": tag.id,
    }
    return create_post_tag(db, post_tag_data)

def _update_post(db: Session, request_data: PostUpdateRequest, user_id: str, visibility: int):
    """投稿を更新する"""
    post_data = {
        "id": request_data.post_id,
        "creator_user_id": user_id,
        "description": request_data.description,
        "scheduled_at": request_data.formattedScheduledDateTime if request_data.scheduled else None,
        "expiration_at": request_data.expirationDate if request_data.expiration else None,
        "visibility": visibility,
        "status": PostStatus.RESUBMIT,
        "reject_comments": "",
    }
    return update_post(db, post_data)


# def _delete_post_categories(db: Session, post_id: str):
#     """投稿に紐づくカテゴリを削除する"""
#     delete_post_category(db, post_id)
#     return True

# def _delete_post_tags(db: Session, post_id: str):
#     """投稿に紐づくタグを削除する"""
#     delete_post_tag(db, post_id)
#     return True

# def _delete_post_plans(db: Session, post_id: str):
#     """投稿に紐づくプランを削除する"""
#     delete_post_plans(db, post_id)
#     return True

# def _delete_post_price(db: Session, post_id: str):
#     """投稿に紐づく価格を削除する"""
#     delete_price(db, post_id)
#     return True

def _refresh_related_objects(
    db: Session, 
    post, 
    price=None, 
    plan_posts=None, 
    category_posts=None, 
    tag_posts=None
):
    """関連オブジェクトをリフレッシュする"""
    db.refresh(post)
    
    if price:
        db.refresh(price)
    
    if plan_posts:
        for plan_post in plan_posts:
            db.refresh(plan_post)
    
    if category_posts:
        for category_post in category_posts:
            db.refresh(category_post)
    
    if tag_posts:
        for tag_post in tag_posts:
            db.refresh(tag_post)

def _create_price(db: Session, post_id: str, price: int):
    """投稿に価格を紐づける"""
    
    price_data = {
        "post_id": post_id,
        "type": PriceType.SINGLE,
        "currency": "JPY",
        "is_active": True,
        "price": price,
        "starts_at": datetime.now(timezone.utc),
    }
    return create_price(db, price_data)

def _create_plan(db: Session, post_id: str, plan_ids: list):
    """投稿にプランを紐づける"""
    plan_post = []
    for plan_id in plan_ids:
        plan_post_data = {
            "post_id": post_id,
            "plan_id": plan_id,
        }
        plan_post.append(create_post_plan(db, plan_post_data))
    return plan_post

def _format_media_info(media_assets: list, is_entitlement: bool):
    """メディア情報を整形する"""
    set_media_kind = MediaAssetKind.MAIN_VIDEO if is_entitlement else MediaAssetKind.SAMPLE_VIDEO
    set_file_name = "_1080w.webp" if is_entitlement else "_blurred.webp"
    
    media_info = []
    for media_asset in media_assets:
        if media_asset.kind == MediaAssetKind.THUMBNAIL:
            thumbnail_key = f"{CDN_BASE_URL}/{media_asset.storage_key}"
        elif media_asset.kind == MediaAssetKind.IMAGES:
            media_info.append({
                "kind": media_asset.kind,
                "duration": media_asset.duration_sec,
                "media_assets_id": media_asset.id,
                "orientation": media_asset.orientation,
                "post_id": media_asset.post_id,
                "storage_key": f"{MEDIA_CDN_URL}/{media_asset.storage_key}{set_file_name}"
            })
        elif media_asset.kind == set_media_kind:
            media_info.append({
                "kind": media_asset.kind,
                "duration": media_asset.duration_sec,
                "media_assets_id": media_asset.id,
                "orientation": media_asset.orientation,
                "post_id": media_asset.post_id,
                "storage_key": f"{MEDIA_CDN_URL}/{media_asset.storage_key}"
            })

    return media_info, thumbnail_key

def _format_creator_info(creator: dict, creator_profile: dict):
    """クリエイター情報を整形する"""
    return {
        "username": creator_profile.username if creator_profile else creator.email,
        "profile_name": creator.profile_name if creator_profile else creator.email,
        "avatar": f"{BASE_URL}/{creator_profile.avatar_url}" if creator_profile.avatar_url else None,
    }

def _format_categories_info(categories: list):
    """カテゴリ情報を整形する"""
    return [
        {
            "id": str(category.id),
            "name": category.name,
            "slug": category.slug
        }
        for category in categories
    ]

def _format_sale_info(price: dict, plans: list):
    """販売情報を整形する"""
    return {
        "price": price.price if price else None,
        "plans": [
            {
                "id": str(plan.id),
                "name": plan.name,
                "description": plan.description,
                "price": plan.price
            }
            for plan in plans
        ]
    }
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from app.schemas.user import UserCreate, UserOut, UserProfileResponse
from app.db.base import get_db
from sqlalchemy.orm import Session
from app.crud.user_crud import (
    create_user,
    check_email_exists,
    check_profile_name_exists,
    get_user_profile_by_username
)
from app.api.commons.utils import generate_code
from app.deps.auth import get_current_user
from app.crud.profile_crud import create_profile
from app.schemas.user import ProfilePostResponse, ProfilePlanResponse, ProfilePurchaseResponse, ProfileGachaResponse
from app.models.posts import Posts
import os
from app.crud.email_verification_crud import issue_verification_token
from app.services.email.send_email import send_email_verification
from app.core.config import settings
router = APIRouter()

BASE_URL = os.getenv("CDN_BASE_URL")

@router.post("/register", response_model=UserOut)
def register_user(
    user_create: UserCreate, 
    db: Session = Depends(get_db),
    background: BackgroundTasks = BackgroundTasks()
):
    """
    ユーザー登録

    Args:
        user_create (UserCreate): ユーザー登録情報
        db (Session, optional): データベースセッション. Defaults to Depends(get_db).

    Raises:
        HTTPException: メールアドレスが既に登録されている場合

    Returns:
        UserOut: ユーザー情報
    """
    try:
        is_email_exists = check_email_exists(db, user_create.email)
        if is_email_exists:
            raise HTTPException(status_code=400, detail="存在しているメールアドレスです")
        is_profile_name_exists = check_profile_name_exists(db, user_create.name)
        if is_profile_name_exists:
            raise HTTPException(status_code=400, detail="存在しているユーザー名です")

        for _ in range(10):  # 最大10回リトライ
            username_code = generate_code(5)
            is_profile_name_exists = check_profile_name_exists(db, username_code)
            if not is_profile_name_exists:
                break
            raise HTTPException(status_code=500, detail="ユーザー名の生成に失敗しました")

        db_user = create_user(db, user_create)
        db_profile = create_profile(db, db_user.id, username_code)


        # メールアドレスの認証トークンを発行
        raw, expires_at = issue_verification_token(db, db_user.id)
        verify_url = f"{os.getenv('FRONTEND_URL')}/auth/verify-email?token={raw}"
        background.add_task(send_email_verification, db_user.email, verify_url, db_user.display_name if hasattr(db_user, "display_name") else None)

        db.commit()
        db.refresh(db_user)
        db.refresh(db_profile)

        return db_user
    except Exception as e:
        print("ユーザー登録エラー: ", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/profile", response_model=UserProfileResponse)
def get_user_profile_by_username_endpoint(
    username: str = Query(..., description="ユーザー名"),
    db: Session = Depends(get_db)
):
    """
    ユーザー名によるユーザープロフィール取得
    """
    try:
        profile_data = get_user_profile_by_username(db, username)
        if not profile_data:
            raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
        
        user = profile_data["user"]
        profile = profile_data["profile"]
        
        website_url = None
        if profile and profile.links and isinstance(profile.links, dict):
            website_url = profile.links.get("website")
        
        # モデルオブジェクトをスキーマオブジェクトに変換
        profile_posts = []
        for post_data in profile_data["posts"]:
            if hasattr(post_data, 'Posts'):
                post = post_data.Posts
                likes_count = post_data.likes_count
                thumbnail_key = post_data.thumbnail_key
            else:
                post = post_data
                likes_count = None
                thumbnail_key = None
            
            profile_posts.append(ProfilePostResponse(
                id=post.id,
                likes_count=likes_count,
                created_at=post.created_at,
                description=post.description,
                thumbnail_url=f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None
            ))
        
        profile_plans = []
        for plan in profile_data["plans"]:
            profile_plans.append(ProfilePlanResponse(
                id=plan.id,
                name=plan.name,
                description=plan.description,
                price=plan.price,
            ))
        
        profile_purchases = []
        for purchase in profile_data["individual_purchases"]:
            if hasattr(purchase, 'Posts'):
                post = purchase.Posts
                likes_count = purchase.likes_count
                thumbnail_key = purchase.thumbnail_key
            else:
                post = purchase
                likes_count = None
                thumbnail_key = None

            profile_purchases.append(ProfilePurchaseResponse(
                id=post.id,
                likes_count=likes_count,
                created_at=post.created_at,
                description=post.description,
                thumbnail_url=f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None
            ))
        
        profile_gacha_items = [] 
        for gacha_item in profile_data["gacha_items"]:
            profile_gacha_items.append(ProfileGachaResponse(
                id=gacha_item.id,
                amount=gacha_item.amount,
                created_at=gacha_item.order.created_at  # Ordersテーブルのcreated_atを使用
            ))
        
        return UserProfileResponse(
            id=user.id,
            profile_name=user.profile_name,
            username=profile.username if profile else None,
            avatar_url=f"{BASE_URL}/{profile.avatar_url}" if profile and profile.avatar_url else None,
            cover_url=f"{BASE_URL}/{profile.cover_url}" if profile and profile.cover_url else None,
            bio=profile.bio if profile else None,
            website_url=website_url,
            post_count=len(profile_data["posts"]),
            follower_count=profile_data["follower_count"],
            posts=profile_posts,
            plans=profile_plans,
            individual_purchases=profile_purchases,
            gacha_items=profile_gacha_items
        )
    except Exception as e:
        print("ユーザープロフィール取得エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))
    
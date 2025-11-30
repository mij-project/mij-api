from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Response
from app.schemas.user import (
    UserCreate,
    UserOut,
    UserProfileResponse,
    UserRegisterCompany,
    UserOGPResponse,
)
from app.db.base import get_db
from sqlalchemy.orm import Session
from app.crud.user_crud import (
    create_user,
    check_email_exists,
    check_profile_name_exists,
    get_user_profile_by_username,
    get_plan_details,
)
from app.crud.companies_crud import get_company_by_code
from app.models.profiles import Profiles
from app.models.user import Users
from app.api.commons.utils import generate_code
from app.crud.profile_crud import create_profile, get_profile_ogp_data
from app.schemas.user import (
    ProfilePostResponse,
    ProfilePlanResponse,
    ProfilePurchaseResponse,
    ProfileGachaResponse,
)
from app.api.commons.utils import generate_email_verification_url
import os
from app.crud.email_verification_crud import issue_verification_token
from app.services.email.send_email import send_email_verification
from typing import Tuple, Optional
from uuid import UUID
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()

BASE_URL = os.getenv("CDN_BASE_URL")


@router.post("/register", response_model=UserOut)
def register_user(
    user_create: UserCreate,
    db: Session = Depends(get_db),
    background: BackgroundTasks = BackgroundTasks(),
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
        result = _insert_user(
            db, user_create.email, user_create.password, user_create.name
        )

        # エラーレスポンスの場合はそのまま返す
        if isinstance(result, Response):
            return result

        db_user, db_profile = result

        # メールアドレスの認証トークンを発行
        _send_email_verification(db, db_user, background)

        db.commit()
        db.refresh(db_user)
        db.refresh(db_profile)

        return db_user
    except Exception as e:
        logger.error("ユーザー登録エラー: ", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/register/company", response_model=UserOut)
def get_user_profile_by_company_code(
    user_register_company: UserRegisterCompany,
    db: Session = Depends(get_db),
    background: BackgroundTasks = BackgroundTasks(),
):
    """
    企業コードによるユーザープロフィール取得
    """
    try:
        result = _insert_user(
            db,
            user_register_company.email,
            user_register_company.password,
            user_register_company.name,
        )

        # エラーレスポンスの場合はそのまま返す
        if isinstance(result, Response):
            return result

        db_user, db_profile = result
        _send_email_verification(
            db, db_user, background, user_register_company.company_code
        )

        company = get_company_by_code(db, user_register_company.company_code)
        if not company:
            raise HTTPException(status_code=404, detail="企業が見つかりません")

        db.commit()
        db.refresh(db_user)
        db.refresh(db_profile)
        return db_user
    except Exception as e:
        logger.error("ユーザー登録エラー: ", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile", response_model=UserProfileResponse)
def get_user_profile_by_username_endpoint(
    username: str = Query(..., description="ユーザー名"), db: Session = Depends(get_db)
):
    """
    ユーザー名によるユーザープロフィール取得
    """
    try:
        now = datetime.now(timezone.utc)
        profile_data = get_user_profile_by_username(db, username)
        if not profile_data:
            raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

        user = profile_data["user"]
        profile = profile_data["profile"]

        # モデルオブジェクトをスキーマオブジェクトに変換
        profile_posts = []
        for post_data in profile_data["posts"]:
            if hasattr(post_data, "Posts"):
                post = post_data.Posts
                likes_count = post_data.likes_count
                thumbnail_key = post_data.thumbnail_key
                duration_sec = post_data.duration_sec
                price = post_data.price
                currency = post_data.currency
            else:
                # タプル形式の場合
                post = post_data[0]
                likes_count = post_data[1] if len(post_data) > 1 else None
                thumbnail_key = post_data[2] if len(post_data) > 2 else None
                duration_sec = post_data[3] if len(post_data) > 3 else None
                price = post_data[4] if len(post_data) > 4 else None
                currency = post_data[5] if len(post_data) > 5 else "JPY"

            # duration_secを整数秒に変換（Decimal型の場合があるため）
            video_duration_int = None
            if duration_sec is not None:
                video_duration_int = int(round(float(duration_sec)))

            if post.scheduled_at and post.scheduled_at.replace(tzinfo=timezone.utc) > now:
                is_reserved = True
            else:
                is_reserved = False

            profile_posts.append(
                ProfilePostResponse(
                    id=post.id,
                    post_type=post.post_type,
                    likes_count=likes_count,
                    created_at=post.created_at,
                    description=post.description,
                    thumbnail_url=f"{BASE_URL}/{thumbnail_key}"
                    if thumbnail_key
                    else None,
                    video_duration=video_duration_int,
                    price=price,
                    currency=currency,
                    is_reserved=is_reserved
                )
            )

        profile_plans = []
        for plan in profile_data["plans"]:
            # プランの詳細情報を取得
            plan_details = get_plan_details(db, plan.id)

            profile_plans.append(
                ProfilePlanResponse(
                    id=plan.id,
                    name=plan.name,
                    description=plan.description,
                    price=plan.price,
                    currency="JPY",  # 通貨は固定（必要に応じてDBから取得）
                    type=plan.type,
                    post_count=plan_details["post_count"],
                    thumbnails=plan_details["thumbnails"],
                )
            )

        profile_purchases = []
        for purchase_data in profile_data["individual_purchases"]:
            # 修正：purchase_dataはタプル形式 (Posts, likes_count, thumbnail_key, price, currency, duration_sec)
            if hasattr(purchase_data, "Posts"):
                post = purchase_data.Posts
                likes_count = purchase_data.likes_count
                thumbnail_key = purchase_data.thumbnail_key
                price = purchase_data.price
                currency = purchase_data.currency
                duration_sec = purchase_data.duration_sec
            else:
                post = purchase_data[0]
                likes_count = purchase_data[1]
                thumbnail_key = purchase_data[2]
                price = purchase_data[3] if len(purchase_data) > 3 else None
                currency = purchase_data[4] if len(purchase_data) > 4 else "JPY"
                duration_sec = purchase_data[5] if len(purchase_data) > 5 else None

            # duration_secを整数秒に変換
            video_duration_int = None
            if duration_sec is not None:
                video_duration_int = int(round(float(duration_sec)))
            if post.scheduled_at and post.scheduled_at.replace(tzinfo=timezone.utc) > now:
                is_reserved = True
            else:
                is_reserved = False
            profile_purchases.append(
                ProfilePurchaseResponse(
                    id=post.id,
                    likes_count=likes_count,
                    created_at=post.created_at,
                    description=post.description,
                    thumbnail_url=f"{BASE_URL}/{thumbnail_key}"
                    if thumbnail_key
                    else None,
                    video_duration=video_duration_int,
                    price=price,
                    currency=currency,
                    is_reserved=is_reserved,
                )
            )

        profile_gacha_items = []
        for gacha_item in profile_data["gacha_items"]:
            profile_gacha_items.append(
                ProfileGachaResponse(
                    id=gacha_item.id,
                    amount=gacha_item.amount,
                    created_at=gacha_item.order.created_at,  # Ordersテーブルのcreated_atを使用
                )
            )

        return UserProfileResponse(
            id=user.id,
            profile_name=user.profile_name,
            offical_flg=user.offical_flg,
            username=profile.username if profile else None,
            avatar_url=f"{BASE_URL}/{profile.avatar_url}"
            if profile and profile.avatar_url
            else None,
            cover_url=f"{BASE_URL}/{profile.cover_url}"
            if profile and profile.cover_url
            else None,
            bio=profile.bio if profile else None,
            links=profile.links if profile else None,
            post_count=len(profile_data["posts"]),
            follower_count=profile_data["follower_count"],
            posts=profile_posts,
            plans=profile_plans,
            individual_purchases=profile_purchases,
            gacha_items=profile_gacha_items,
        )
    except Exception as e:
        logger.error("ユーザープロフィール取得エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}/ogp-image", response_model=UserOGPResponse)
async def get_user_ogp_image(user_id: str, db: Session = Depends(get_db)):
    """ユーザーのOGP情報を取得する（Lambda@Edge用）"""
    try:
        # OGP情報を取得（プロフィール詳細 + 統計情報 + OGP画像）
        ogp_data = get_profile_ogp_data(db, user_id)

        if not ogp_data:
            raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

        return ogp_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("OGP画像URL取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


def _insert_user(
    db: Session,
    email: str,
    password: str,
    name: str,
    company_code: Optional[UUID] = None,
) -> Tuple[Users, Profiles]:
    """
    ユーザーを登録
    """
    is_email_exists = check_email_exists(db, email)
    if is_email_exists:
        return Response(
            content="このメールアドレスは既に登録されています。", status_code=400
        )
    is_profile_name_exists = check_profile_name_exists(db, name)
    if is_profile_name_exists:
        return Response(content="この名前は既に登録されています。", status_code=400)

    for _ in range(10):  # 最大10回リトライ
        username_code = generate_code(5)
        is_profile_name_exists = check_profile_name_exists(db, username_code)
        if not is_profile_name_exists:
            break
        return Response(
            content="ユーザー名の生成に失敗しました。再度お試しください。",
            status_code=500,
        )

    db_user = create_user(db, UserCreate(email=email, password=password, name=name))
    db_profile = create_profile(db, db_user.id, username_code)

    return db_user, db_profile


def _send_email_verification(
    db: Session,
    user: Users,
    background: BackgroundTasks,
    company_code: Optional[UUID] = None,
) -> None:
    """
    メールアドレスの認証トークンを発行
    """
    raw, expires_at = issue_verification_token(db, user.id)
    if company_code:
        verify_url = generate_email_verification_url(raw, company_code)
    else:
        verify_url = generate_email_verification_url(raw)
    background.add_task(
        send_email_verification,
        user.email,
        verify_url,
        user.profile_name if hasattr(user, "profile_name") else None,
    )

import calendar
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Response
from app.crud.sales_crud import get_payments_by_user_id
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
    get_user_by_id,
)
from app.deps.auth import get_current_user, get_current_user_optional
from app.crud.companies_crud import get_company_by_code
from app.models.profiles import Profiles
from app.models.user import Users
from app.api.commons.utils import generate_code
from app.crud.profile_crud import create_profile, get_profile_ogp_data, get_profile_by_user_id
from app.schemas.user import (
    ProfilePostResponse,
    ProfilePlanResponse,
    ProfilePurchaseResponse,
    ProfileGachaResponse,
    TopBuyerResponse,
)
from app.crud.payments_crud import get_top_buyers_by_user_id
from app.models.subscriptions import Subscriptions
from app.models.payments import Payments
from app.constants.enums import ItemType, SubscriptionStatus, PaymentStatus, PaymentType
from app.models.plans import Plans
from sqlalchemy import func, select, cast, String
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
    username: str = Query(..., description="ユーザー名"),
    db: Session = Depends(get_db),
    current_user: Optional[Users] = Depends(get_current_user_optional),
):
    """
    ユーザー名によるユーザープロフィール取得（未ログインでもアクセス可能）
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
        post_count = 0
        for post_data in profile_data["posts"]:
            post_count += 1
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

            if (
                post.scheduled_at
                and post.scheduled_at.replace(tzinfo=timezone.utc) > now
            ):
                post_count -= 1
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
                    is_reserved=is_reserved,
                    is_time_sale=post.is_time_sale,
                    sale_percentage=post.price_sale_percentage,
                    end_date=post.price_sale_end_date,
                )
            )

        profile_plans = []
        for plan in profile_data["plans"]:
            # プランの詳細情報を取得
            plan_details = get_plan_details(db, plan.id)

            # 現在のユーザーが加入済みかどうかをチェック
            is_subscribed = False
            if current_user:
                is_subscribed = (
                    db.query(Subscriptions)
                    .filter(
                        Subscriptions.user_id == current_user.id,
                        Subscriptions.order_id == str(plan.id),
                        Subscriptions.order_type == ItemType.PLAN,  # 2=ItemType.PLAN
                        Subscriptions.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED]),  # 1=ACTIVE
                    )
                    .first()
                    is not None
                )
            
            profile_plans.append(
                ProfilePlanResponse(
                    id=plan.id,
                    name=plan.name,
                    description=plan.description,
                    open_dm_flg=plan.open_dm_flg,
                    price=plan.price,
                    currency="JPY",  # 通貨は固定（必要に応じてDBから取得）
                    type=plan.type,
                    post_count=plan_details["post_count"],
                    plan_post=[
                        {
                            "description": post["description"],
                            "thumbnail_url": f"{BASE_URL}/{post['storage_key']}",
                        }
                        for post in plan_details.get("plan_post", [])
                    ],
                    is_subscribed=is_subscribed,
                    is_time_sale=plan.is_time_sale,
                    time_sale_info=plan.time_sale_info,
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
            if (
                post.scheduled_at
                and post.scheduled_at.replace(tzinfo=timezone.utc) > now
            ):
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
                    is_time_sale=post.is_time_sale,
                    sale_percentage=post.price_sale_percentage,
                    end_date=post.price_sale_end_date,
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

        # 購入金額上位3名を取得
        top_buyers = []
        # seller_user_idが現在のユーザーで、statusがSUCCEEDEDのレコードを集計
        top_buyers_results = get_top_buyers_by_user_id(db, user.id)

        for buyer_result in top_buyers_results:
            buyer_user_id = buyer_result.buyer_user_id
            # 購入者情報を取得
            buyer_user = get_user_by_id(db, str(buyer_user_id))
            if buyer_user:
                buyer_profile = get_profile_by_user_id(db, buyer_user_id)
                top_buyers.append(
                    TopBuyerResponse(
                        profile_name=buyer_user.profile_name if buyer_user else "",
                        username=buyer_profile.username if buyer_profile else None,
                        avatar_url=f"{BASE_URL}/{buyer_profile.avatar_url}" if buyer_profile and buyer_profile.avatar_url else None,
                    )
                )

        # チップ購入済みかどうかをチェック
        has_sent_chip = False
        if current_user:
            has_sent_chip = (
                db.query(Payments)
                .filter(
                    Payments.payment_type == PaymentType.CHIP,
                    Payments.seller_user_id == user.id,
                    Payments.buyer_user_id == current_user.id,
                    Payments.status == PaymentStatus.SUCCEEDED,
                )
                .first()
                is not None
            )

        # DM解放プランに加入済みかどうかをチェック
        has_dm_release_plan = False
        if current_user:
            has_dm_release_plan = (
                db.query(Subscriptions)
                .join(Plans, Subscriptions.order_id == cast(Plans.id, String))
                .filter(
                    Subscriptions.user_id == current_user.id,
                    Subscriptions.order_type == ItemType.PLAN,
                    Subscriptions.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED]),
                    Plans.creator_user_id == user.id,
                    Plans.open_dm_flg == True,
                )
                .first()
                is not None
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
            post_count=post_count,
            follower_count=profile_data["follower_count"],
            is_creator=(user.role == 2),  # AccountType.CREATOR
            posts=profile_posts,
            plans=profile_plans,
            individual_purchases=profile_purchases,
            gacha_items=profile_gacha_items,
            top_buyers=top_buyers,
            has_sent_chip=has_sent_chip,
            has_dm_release_plan=has_dm_release_plan,
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


@router.get("/payment-histories")
async def get_payment_histories(
    period: str = Query("today"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    logger.info(f"Payment histories period: {period}")
    if period in ["today", "yesterday", "day_before_yesterday"]:
        return _get_payment_histories_period_date_range(
            db, period, current_user, page, limit
        )
    return _get_payment_histories_period_month_range(
        db, period, current_user, page, limit
    )


def _get_payment_histories_period_date_range(
    db: Session, period: str, current_user: Users, page: int, limit: int
):
    now = datetime.now(timezone.utc)
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            hours=9
        )
        end_date = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(hours=9)
    elif period == "yesterday":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=1, hours=9
        )
        end_date = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(days=1, hours=9)
    elif period == "day_before_yesterday":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=2, hours=9
        )
        end_date = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(days=2, hours=9)
    else:
        raise HTTPException(status_code=400, detail="Invalid period")
    payment_histories = get_payments_by_user_id(
        db, current_user.id, start_date, end_date, page, limit
    )
    if payment_histories is None:
        raise HTTPException(status_code=500, detail="Payment histories not found")
    return payment_histories


def _get_payment_histories_period_month_range(
    db: Session, period: str, current_user: Users, page: int, limit: int
):
    start_date, end_date, none_use_start_date, none_use_end_date = __get_month_ranges(
        period
    )
    payment_histories = get_payments_by_user_id(
        db, current_user.id, start_date, end_date, page, limit
    )
    if payment_histories is None:
        raise HTTPException(status_code=500, detail="Payment histories not found")
    return payment_histories


def __get_month_ranges(ym: str):
    year, month = map(int, ym.split("-"))

    start_date = datetime(year, month, 1, 0, 0, 0) - timedelta(hours=9)

    last_day = calendar.monthrange(year, month)[1]
    end_date = datetime(year, month, last_day, 23, 59, 59, 999_999) - timedelta(hours=9)

    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1

    prev_start_date = datetime(prev_year, prev_month, 1, 0, 0, 0) - timedelta(hours=9)
    prev_last_day = calendar.monthrange(prev_year, prev_month)[1]
    prev_end_date = datetime(
        prev_year, prev_month, prev_last_day, 23, 59, 59, 999_999
    ) - timedelta(hours=9)

    return (start_date, end_date, prev_start_date, prev_end_date)

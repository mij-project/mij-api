from sqlalchemy.orm import Session
from app.crud.time_sale_crud import (
    get_active_plan_timesale_map,
    get_active_price_timesale_pairs,
)
from app.models.user import Users
from app.schemas.user import UserCreate
from app.core.security import hash_password
from sqlalchemy import select, desc, func, update, asc, case
from sqlalchemy.orm import joinedload
from datetime import datetime, timezone
from uuid import UUID
from app.constants.enums import AccountType, AccountStatus, PostStatus, MediaAssetKind
from app.crud.profile_crud import get_profile_by_username
from app.models.posts import Posts
from app.models.plans import Plans, PostPlans
from app.models.media_assets import MediaAssets
from app.models.social import Likes, Follows
from app.models.prices import Prices
# from app.constants.enums import MediaAssetKind
from app.api.commons.function import CommonFunction
import os

BASE_URL = os.getenv("CDN_BASE_URL")


def check_email_exists(db: Session, email: str) -> bool:
    """
    メールアドレスの重複チェック

    Args:
        db (Session): データベースセッション
        email (str): メールアドレス

    Returns:
        bool: 重複している場合はTrue、重複していない場合はFalse
    """
    result = db.query(Users).filter(Users.email == email).first()
    return result is not None


def check_profile_name_exists(db: Session, profile_name: str) -> bool:
    """
    プロファイル名の重複チェック

    Args:
        db (Session): データベースセッション
        profile_name (str): プロファイル名

    Returns:
        bool: 重複している場合はTrue、重複していない場合はFalse
    """
    result = db.query(Users).filter(Users.profile_name == profile_name).first()
    return result is not None


def get_user_by_email(db: Session, email: str) -> Users:
    """
    メールアドレスによるユーザー取得

    Args:
        db (Session): データベースセッション
        email (str): メールアドレス

    Returns:
        Users: ユーザー情報
    """
    return db.scalar(
        select(Users).where(Users.email == email, Users.is_email_verified.is_(True))
    )


def get_plan_details(db: Session, plan_id: UUID) -> dict:
    """
    プランの詳細情報を取得（投稿数、サムネイル）
    """
    active_post_cond = CommonFunction.get_active_post_cond()

    # プランに紐づく投稿のサムネイルを取得（最大3枚）
    plan_posts_query = (
        db.query(Posts.description, MediaAssets.storage_key)
        .join(Posts, MediaAssets.post_id == Posts.id)
        .join(PostPlans, Posts.id == PostPlans.post_id)
        .filter(PostPlans.plan_id == plan_id)
        .filter(MediaAssets.kind == MediaAssetKind.THUMBNAIL)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .limit(3)
        .all()
    )

    # plan_postを辞書形式で返す
    plan_post = [
        {
            "description": post.description
            if hasattr(post, "description")
            else post[0],
            "storage_key": post.storage_key
            if hasattr(post, "storage_key")
            else post[1],
        }
        for post in plan_posts_query
    ]

    # プランに紐づく投稿数を取得
    post_count = (
        db.query(func.count(Posts.id))
        .join(PostPlans, Posts.id == PostPlans.post_id)
        .filter(PostPlans.plan_id == plan_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .scalar()
    )

    return {"plan_post": plan_post, "post_count": post_count or 0}


def get_user_profile_by_username(db: Session, username: str) -> dict:
    """
    ユーザー名によるユーザープロフィール取得（関連データ含む）
    """
    profile = get_profile_by_username(db, username)

    if not profile:
        return None

    user = get_user_by_id(db, profile.user_id)

    # サムネイルのMediaAssetsを取得するサブクエリ
    thumbnail_subq = (
        db.query(MediaAssets.post_id, MediaAssets.storage_key.label("thumbnail_key"))
        .filter(MediaAssets.kind == MediaAssetKind.THUMBNAIL)
        .subquery()
    )

    # メインビデオのduration_secを取得するサブクエリ
    video_duration_subq = (
        db.query(MediaAssets.post_id, MediaAssets.duration_sec.label("duration_sec"))
        .filter(MediaAssets.kind == MediaAssetKind.MAIN_VIDEO)
        .subquery()
    )

    active_post_cond = CommonFunction.get_active_post_cond()
    likes_count_subq = (
        db.query(
            Likes.post_id.label("post_id"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .group_by(Likes.post_id)
        .subquery()
    )

    posts = (
        db.query(
            Posts,
            func.coalesce(likes_count_subq.c.likes_count, 0).label("likes_count"),
            thumbnail_subq.c.thumbnail_key,
            video_duration_subq.c.duration_sec,
            Prices.id.label("price_id"),
            Prices.price.label("price"),
            Prices.currency.label("currency"),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .outerjoin(likes_count_subq, Posts.id == likes_count_subq.c.post_id)
        .outerjoin(thumbnail_subq, Posts.id == thumbnail_subq.c.post_id)
        .outerjoin(video_duration_subq, Posts.id == video_duration_subq.c.post_id)
        .outerjoin(Prices, (Posts.id == Prices.post_id) & (Prices.is_active.is_(True)))
        .filter(Posts.creator_user_id == user.id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .group_by(
            Posts.id,
            thumbnail_subq.c.thumbnail_key,
            video_duration_subq.c.duration_sec,
            likes_count_subq.c.likes_count,
            Prices.id,
            Prices.price,
            Prices.currency,
        )
        .order_by(desc(Posts.created_at))
        .all()
    )

    post_ids = [row[0].id for row in posts]
    post_plan_rows = (
        db.query(PostPlans.post_id, PostPlans.plan_id)
        .filter(PostPlans.post_id.in_(post_ids))
        .all()
    )
    post_to_plan_ids: dict[str, list[str]] = {}
    all_plan_ids = set()
    for post_id, plan_id in post_plan_rows:
        post_to_plan_ids.setdefault(str(post_id), []).append(str(plan_id))
        all_plan_ids.add(plan_id)
    plan_ts_map = get_active_plan_timesale_map(db, all_plan_ids)

    price_pairs = []
    for row in posts:
        post_obj = row[0]
        price_id = row.price_id
        price = row.price
        if price_id and price and int(price) > 0:
            price_pairs.append((post_obj.id, price_id))

    active_price_pairs = get_active_price_timesale_pairs(db, price_pairs)
    post_sale_map: dict[str, bool] = {}

    for row in posts:
        post_obj = row[0]
        pid = str(post_obj.id)

        # price sale
        has_price_sale = False
        if row.price_id and row.price and int(row.price) > 0:
            found = [x for x in active_price_pairs if x[0] == pid]
            has_price_sale = True if found else False

        # plan sale
        has_plan_sale = False
        plan_ids = post_to_plan_ids.get(pid, [])
        for plan_id in plan_ids:
            if (
                (plan_id in plan_ts_map)
                and (plan_ts_map[plan_id]["is_active"])
                and (not plan_ts_map[plan_id]["is_expired"])
            ):
                has_plan_sale = True
                break

        post_sale_map[pid] = has_price_sale or has_plan_sale

    for row in posts:
        id = str(row[0].id)
        if id in post_sale_map and post_sale_map[id]:
            is_time_sale = True
        else:
            is_time_sale = False
        sale_percentage = None
        end_date = None
        price_ts = [x for x in active_price_pairs if x[0] == id]
        if price_ts:
            sale_percentage = price_ts[0][2]
            end_date = price_ts[0][3]
        row[0].is_time_sale = is_time_sale
        row[0].price_sale_percentage = sale_percentage
        row[0].price_sale_end_date = end_date
    # プラン一覧を取得（typeはプランの種類：1=通常、2=おすすめ）
    plans = (
        db.query(Plans)
        .filter(Plans.creator_user_id == user.id)
        .filter(Plans.deleted_at.is_(None))
        .order_by(
            case((Plans.type == 2, 0), else_=1),  # typeが2のものを優先
            asc(Plans.display_order),
            asc(Plans.created_at),
        )
        .all()
    )
    for plan in plans:
        plan_id = str(plan.id)
        if (
            (plan_id in plan_ts_map)
            and (plan_ts_map[plan_id]["is_active"])
            and (not plan_ts_map[plan_id]["is_expired"])
        ):
            plan.is_time_sale = True
            plan.time_sale_info = plan_ts_map[plan_id]
        else:
            plan.is_time_sale = False
            plan.time_sale_info = None

    # 単品購入の投稿を取得（Pricesテーブルに紐づく投稿）
    # サムネイル用サブクエリ（再利用）
    thumbnail_subq_purchase = (
        db.query(MediaAssets.post_id, MediaAssets.storage_key.label("thumbnail_key"))
        .filter(MediaAssets.kind == MediaAssetKind.THUMBNAIL)
        .subquery()
    )

    # ビデオduration用サブクエリ（再利用）
    video_duration_subq_purchase = (
        db.query(MediaAssets.post_id, MediaAssets.duration_sec.label("duration_sec"))
        .filter(MediaAssets.kind == MediaAssetKind.MAIN_VIDEO)
        .subquery()
    )

    individual_purchases = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            thumbnail_subq_purchase.c.thumbnail_key,
            Prices.price.label("price"),
            Prices.currency.label("currency"),
            video_duration_subq_purchase.c.duration_sec,
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Prices, Posts.id == Prices.post_id)  # Pricesテーブルと結合
        .outerjoin(
            thumbnail_subq_purchase, Posts.id == thumbnail_subq_purchase.c.post_id
        )
        .outerjoin(
            video_duration_subq_purchase,
            Posts.id == video_duration_subq_purchase.c.post_id,
        )
        .filter(Posts.creator_user_id == user.id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Prices.is_active.is_(True))  # 有効な価格設定のみ
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .group_by(
            Posts.id,
            thumbnail_subq_purchase.c.thumbnail_key,
            Prices.price,
            Prices.currency,
            video_duration_subq_purchase.c.duration_sec,
        )
        .order_by(desc(Posts.created_at))
        .all()
    )
    

    gacha_items = []

    # フォロワー数とフォロー数を取得
    follower_count = get_follower_count(db, user.id)
    following_count = get_following_count(db, user.id)
    
    return {
        "user": user,
        "profile": profile,
        "posts": posts,
        "plans": plans,
        "individual_purchases": individual_purchases,
        "gacha_items": gacha_items,
        "follower_count": follower_count,
        "following_count": following_count,
    }


def get_user_by_id(db: Session, user_id: str) -> Users:
    """
    ユーザーIDによるユーザー取得（Profileテーブルと結合）

    Args:
        db (Session): データベースセッション
        user_id (str): ユーザーID

    Returns:
        Users: ユーザー情報（Profile情報も含む）
    """
    return (
        db.query(Users)
        .options(joinedload(Users.profile))
        .filter(Users.id == user_id)
        .first()
    )


def get_follower_count(db: Session, user_id: UUID) -> int:
    """
    ユーザーのフォロワー数を取得

    Args:
        db (Session): データベースセッション
        user_id (UUID): ユーザーID

    Returns:
        int: フォロワー数
    """
    return db.query(Follows).filter(Follows.creator_user_id == user_id).count()


def get_following_count(db: Session, user_id: UUID) -> int:
    """
    ユーザーのフォロー数を取得

    Args:
        db (Session): データベースセッション
        user_id (UUID): ユーザーID

    Returns:
        int: フォロー数
    """
    return db.query(Follows).filter(Follows.follower_user_id == user_id).count()


def check_super_user(db: Session, user_id: UUID) -> bool:
    """
    スーパーユーザーかどうかをチェック
    """
    return (
        db.query(Users)
        .filter(Users.id == user_id, Users.role == AccountType.SUPER_USER)
        .first()
        is not None
    )


def resend_email_verification(db: Session, email: str) -> Users:
    """
    メールアドレスによるユーザー取得
    """
    stmt = select(Users).where(Users.email == email)
    user = (db.execute(stmt)).scalar_one_or_none()
    return user


def update_user(db: Session, user_id: str, profile_name: str) -> Users:
    """
    ユーザーを更新
    """
    user = get_user_by_id(db, user_id)
    user.profile_name = profile_name
    db.add(user)
    db.flush()
    return user


def update_user_phone_verified_at(db: Session, user_id: str) -> Users:
    """
    ユーザーの電話番号を検証済みに更新
    """
    # まず更新を実行
    db.query(Users).filter(Users.id == user_id).update(
        {"is_phone_verified": True, "phone_verified_at": datetime.now(timezone.utc)}
    )

    # 更新されたオブジェクトを取得して返す
    return db.query(Users).filter(Users.id == user_id).first()


def update_user_identity_verified_at(
    db: Session,
    user_id: str,
    is_identity_verified: bool,
    identity_verified_at: datetime,
) -> Users:
    """
    ユーザーの身分証明を検証済みに更新
    """
    db.query(Users).filter(Users.id == user_id).update(
        {
            "is_identity_verified": is_identity_verified,
            "identity_verified_at": identity_verified_at,
        }
    )
    db.commit()
    return db.query(Users).filter(Users.id == user_id).first()


def update_user_email_verified_at(
    db: Session, user_id: str, offical_flg: bool
) -> Users:
    """
    ユーザーのメールアドレスを検証済みに更新
    """
    db.execute(
        update(Users)
        .where(Users.id == user_id)
        .values(
            is_email_verified=True,
            email_verified_at=datetime.now(timezone.utc),
            offical_flg=offical_flg,
        )
    )


def create_user_by_x(db: Session, user: Users) -> Users:
    """
    Xユーザーを作成
    """
    db.add(user)
    db.flush()
    return user


def create_user(db: Session, user_create: UserCreate) -> Users:
    """
    ユーザーを作成する

    Args:
        db: データベースセッション
        user_create: ユーザー作成情報
    """
    # ランダム文字列5文字作成
    db_user = Users(
        profile_name=user_create.name,
        email=user_create.email,
        password_hash=hash_password(user_create.password),
        role=AccountType.GENERAL_USER,
        status=AccountStatus.ACTIVE,
    )
    db.add(db_user)
    db.flush()
    return db_user


def create_super_user(db: Session, email: str, password: str, name: str) -> Users:
    """
    スーパーユーザーを作成
    """
    user = Users(
        profile_name=name,
        email=email,
        password_hash=hash_password(password),
        role=AccountType.SUPER_USER,
        status=AccountStatus.ACTIVE,
        is_email_verified=True,
    )
    db.add(user)
    db.flush()
    return user

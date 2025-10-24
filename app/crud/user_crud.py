from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.user import Users
from app.models.profiles import Profiles
from app.schemas.user import UserCreate
from app.core.security import hash_password
from sqlalchemy import select, desc, func, update
from sqlalchemy.orm import joinedload
from datetime import datetime, timezone
from uuid import UUID
from app.constants.enums import (
    AccountType, 
    AccountStatus
)
from app.crud.profile_crud import get_profile_by_username
from app.models.posts import Posts
from app.models.plans import Plans, PostPlans
from app.models.orders import Orders, OrderItems
from app.models.media_assets import MediaAssets
from app.models.social import Likes, Follows
from app.models.prices import Prices
from app.constants.enums import PostStatus, MediaAssetKind, PlanStatus

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
    return (
        db.scalar(
            select(Users)
            .where(Users.email == email, Users.is_email_verified == True))
        )

def get_user_profile_by_username(db: Session, username: str) -> dict:
    """
    ユーザー名によるユーザープロフィール取得（関連データ含む）
    """
    profile = get_profile_by_username(db, username)

    if not profile:
        return None
    
    user = get_user_by_id(db, profile.user_id)
    
    posts = (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .filter(Posts.creator_user_id == user.id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .group_by(Posts.id, MediaAssets.storage_key)  # GROUP BY句を追加
        .order_by(desc(Posts.created_at))
        .all()
    )
    
    plans = (
        db.query(
            Plans.id.label('id'),
            Plans.name.label('name'),
            Plans.description.label('description'),
            Plans.price.label('price')
        )
        .filter(Plans.creator_user_id == user.id)
        .filter(Plans.type == PlanStatus.PLAN)
        .filter(Plans.deleted_at.is_(None))
        .group_by(Plans.id, Plans.price)
        .all()
    )
    
    individual_purchases = (
        db.query(
            Posts, 
            func.count(Likes.post_id).label('likes_count'),
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(PostPlans, Posts.id == PostPlans.post_id)  # PostPlansテーブルを通じて結合
        .join(Plans, PostPlans.plan_id == Plans.id)  # Plansテーブルと結合
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .filter(Posts.creator_user_id == user.id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Plans.type == PlanStatus.SINGLE)  # typeが1（SINGLE）のもののみ
        .filter(Plans.deleted_at.is_(None))  # 削除されていないプランのみ
        .filter(Posts.status == PostStatus.APPROVED)
        .group_by(Posts.id, MediaAssets.storage_key)
        .order_by(desc(Posts.created_at))
        .all()
    )
    
    gacha_items = db.query(OrderItems).join(Orders).filter(Orders.user_id == user.id).filter(OrderItems.item_type == 2).all()
    
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
        "following_count": following_count
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
    return (
        db.query(Follows)
        .filter(Follows.creator_user_id == user_id)
        .count()
    )

def get_following_count(db: Session, user_id: UUID) -> int:
    """
    ユーザーのフォロー数を取得

    Args:
        db (Session): データベースセッション
        user_id (UUID): ユーザーID

    Returns:
        int: フォロー数
    """
    return (
        db.query(Follows)
        .filter(Follows.follower_user_id == user_id)
        .count()
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
    db.query(Users).filter(Users.id==user_id).update({
        "is_phone_verified": True, 
        "phone_verified_at": datetime.now()
    })
    
    # 更新されたオブジェクトを取得して返す
    return db.query(Users).filter(Users.id==user_id).first()

def update_user_identity_verified_at(db: Session, user_id: str, is_identity_verified: bool, identity_verified_at: datetime) -> Users:
    """
    ユーザーの身分証明を検証済みに更新
    """
    db.query(Users).filter(Users.id==user_id).update({
        "is_identity_verified": is_identity_verified,
        "identity_verified_at": identity_verified_at
    })
    db.commit()
    return db.query(Users).filter(Users.id==user_id).first()

def update_user_email_verified_at(db: Session, user_id: str) -> Users:
    """
    ユーザーのメールアドレスを検証済みに更新
    """
    db.execute(update(Users).where(Users.id==user_id).values(
        is_email_verified=True, email_verified_at=datetime.utcnow()
    ))

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
        status=AccountStatus.ACTIVE
    )
    db.add(db_user)
    db.flush()
    return db_user

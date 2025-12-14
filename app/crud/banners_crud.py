from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from datetime import datetime, timezone
from uuid import UUID

from app.models.banners import Banners
from app.models.user import Users
from app.models.profiles import Profiles
from app.models.events import Events, UserEvents
from app.constants.enums import BannerImageSource, BannerStatus, BannerType
from app.constants.event_code import EventCode
from sqlalchemy import func
import os

BANNER_IMAGE_URL = os.getenv("BANNER_IMAGE_URL", "")
CDN_URL = os.getenv("CDN_BASE_URL", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "")

def create_banner(
    db: Session,
    form_data: dict[str, Any]
) -> Banners:
    """
    新しいバナーを作成

    Args:
        db: データベースセッション
        form_data: バナー作成データ

    Returns:
        Banners: 作成されたバナー
    """
    banner = Banners(**form_data)
    db.add(banner)
    db.flush()
    return banner


def get_banner_by_id(
    db: Session,
    banner_id: UUID
) -> Optional[Banners]:
    """
    IDでバナーを取得

    Args:
        db: データベースセッション
        banner_id: バナーID

    Returns:
        Optional[Banners]: バナー
    """
    return db.query(Banners).filter(
        Banners.id == banner_id
    ).first()


def get_active_banners(
    db: Session
) -> List[Dict[str, Any]]:
    """
    現在有効なバナー一覧を取得（表示期間内 & status=1）

    Args:
        db: データベースセッション

    Returns:
        List[Dict]: バナーリスト
    """
    now = datetime.now(timezone.utc)

    results = (
        db.query(Banners, Profiles.username, Profiles.cover_url, Profiles.avatar_url, Users.profile_name)
        .outerjoin(Users, Banners.creator_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .filter(
            Banners.status == BannerStatus.ACTIVE,
            Banners.start_at <= now,
            Banners.end_at >= now
        )
        .order_by(asc(Banners.display_order))
        .all()
    )

    banners = []
    for row in results:
        banner = row[0]
        username = row[1]
        cover_url = row[2]
        avatar_url = row[3]
        profile_name = row[4]

        avatar_image_url = None
        banner_image_url = None
        # image_source に応じて画像URLを決定
        if banner.image_source == BannerImageSource.USER_PROFILE:  # USER_PROFILE
            # プロフィールのカバー画像を使用
            banner_image_url = f"{CDN_URL}/{cover_url}" if cover_url else None
            avatar_image_url = f"{CDN_URL}/{avatar_url}" if avatar_url else None
        elif banner.image_source == BannerImageSource.ADMIN_POST:  # ADMIN_POST
            # 管理者がアップロードした画像を使用
            banner_image_url = f"{BANNER_IMAGE_URL}/{banner.image_key}" if banner.image_key else None

        banners.append({
            "id": str(banner.id),
            "type": banner.type,
            "title": banner.title,
            "image_url": banner_image_url,
            "avatar_url": avatar_image_url,
            "image_source": banner.image_source,
            "alt_text": banner.alt_text,
            "creator_id": str(banner.creator_id) if banner.creator_id else None,
            "creator_username": username,
            "creator_profile_name": profile_name,
            "external_url": banner.external_url if banner.external_url else None,
            "display_order": banner.display_order
        })

    return banners


def get_banners_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    status: Optional[int] = None,
    search: Optional[str] = None,
    sort: str = "display_order_asc"
) -> Tuple[List[Dict[str, Any]], int]:
    """
    ページネーション付きバナー一覧を取得（管理画面用）

    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        status: ステータスフィルタ
        search: 検索クエリ
        sort: ソート順

    Returns:
        Tuple[List[Dict], int]: (バナーリスト, 総件数)
    """
    skip = (page - 1) * limit

    query = (
        db.query(Banners, Profiles.username, Users.profile_name, Profiles.avatar_url)
        .outerjoin(Users, Banners.creator_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
    )

    # ステータスフィルタ
    if status is not None:
        query = query.filter(Banners.status == status)

    # 検索フィルタ
    if search:
        query = query.filter(
            Banners.title.ilike(f"%{search}%")
        )

    # ソート
    if sort == "display_order_asc":
        query = query.order_by(asc(Banners.display_order))
    elif sort == "display_order_desc":
        query = query.order_by(desc(Banners.display_order))
    elif sort == "created_at_desc":
        query = query.order_by(desc(Banners.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(Banners.created_at))
    elif sort == "start_at_desc":
        query = query.order_by(desc(Banners.start_at))
    elif sort == "start_at_asc":
        query = query.order_by(asc(Banners.start_at))
    else:
        query = query.order_by(asc(Banners.display_order))

    total = query.count()
    results = query.offset(skip).limit(limit).all()

    # データ変換
    type_labels = {1: "クリエイター", 2: "バナー広告(外部URL)", 3: "バナー広告(画像のみ)"}
    status_labels = {0: "無効", 1: "有効", 2: "下書き"}

    banners = []
    for row in results:
        banner = row[0]
        username = row[1]
        profile_name = row[2]
        avatar_url = row[3]

        banners.append({
            "id": str(banner.id),
            "type": banner.type,
            "type_label": type_labels.get(banner.type, "不明"),
            "title": banner.title,
            "image_key": banner.image_key,
            "image_url": f"{BANNER_IMAGE_URL}/{banner.image_key}",
            "alt_text": banner.alt_text,
            "cta_label": banner.cta_label,
            "creator_id": str(banner.creator_id) if banner.creator_id else None,
            "creator_username": username,
            "creator_profile_name": profile_name,
            "creator_avatar_url": f"{CDN_URL}/{avatar_url}" if avatar_url else None,
            "external_url": banner.external_url if banner.external_url else None,
            "status": banner.status,
            "status_label": status_labels.get(banner.status, "不明"),
            "start_at": banner.start_at,
            "end_at": banner.end_at,
            "display_order": banner.display_order,
            "priority": banner.priority,
            "image_source": banner.image_source,
            "created_at": banner.created_at,
            "updated_at": banner.updated_at
        })

    return banners, total


def update_banner(
    db: Session,
    banner_id: UUID,
    type: Optional[int] = None,
    title: Optional[str] = None,
    image_key: Optional[str] = None,
    alt_text: Optional[str] = None,
    cta_label: Optional[str] = None,
    creator_id: Optional[UUID] = None,
    external_url: Optional[str] = None,
    status: Optional[int] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    display_order: Optional[int] = None,
    priority: Optional[int] = None
) -> Optional[Banners]:
    """
    バナーを更新

    Args:
        db: データベースセッション
        banner_id: バナーID
        その他: 更新するフィールド

    Returns:
        Optional[Banners]: 更新されたバナー
    """
    banner = get_banner_by_id(db, banner_id)
    if not banner:
        return None

    if type is not None:
        banner.type = type
    if title is not None:
        banner.title = title
    if image_key is not None:
        banner.image_key = image_key
    if alt_text is not None:
        banner.alt_text = alt_text
    if cta_label is not None:
        banner.cta_label = cta_label
    if creator_id is not None:
        banner.creator_id = creator_id
    if external_url is not None:
        banner.external_url = external_url
    if status is not None:
        banner.status = status
    if start_at is not None:
        banner.start_at = start_at
    if end_at is not None:
        banner.end_at = end_at
    if display_order is not None:
        banner.display_order = display_order
    if priority is not None:
        banner.priority = priority

    banner.updated_at = datetime.now(timezone.utc)
    db.flush()
    return banner


def update_banner_image(
    db: Session,
    banner_id: UUID,
    image_key: str,
    image_source: BannerImageSource
) -> Optional[Banners]:
    """
    バナー画像を更新
    """
    banner = get_banner_by_id(db, banner_id)
    if not banner:
        return None

    banner.image_key = image_key
    banner.updated_at = datetime.now(timezone.utc)
    banner.image_source = image_source
    db.flush()
    return banner

def delete_banner(
    db: Session,
    banner_id: UUID
) -> bool:
    """
    バナーを削除（物理削除）

    Args:
        db: データベースセッション
        banner_id: バナーID

    Returns:
        bool: 成功フラグ
    """
    banner = get_banner_by_id(db, banner_id)
    if not banner:
        return False

    db.delete(banner)
    db.flush()
    return True


def reorder_banners(
    db: Session,
    banner_ids: List[UUID]
) -> bool:
    """
    バナーの表示順序を一括更新

    Args:
        db: データベースセッション
        banner_ids: バナーIDリスト（並び順）

    Returns:
        bool: 成功フラグ
    """
    for index, banner_ids in enumerate(banner_ids):
        banner = get_banner_by_id(db, banner_ids)
        if banner:
            banner.display_order = index
            banner.updated_at = datetime.now(timezone.utc)

    db.flush()
    return True


def get_banner_detail(
    db: Session,
    banner_id: UUID
) -> Optional[Dict[str, Any]]:
    """
    バナー詳細を取得（管理画面用）

    Args:
        db: データベースセッション
        banner_id: バナーID

    Returns:
        Optional[Dict]: バナー詳細
    """
    result = (
        db.query(Banners, Profiles.username, Users.profile_name)
        .outerjoin(Users, Banners.creator_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .filter(Banners.id == banner_id)
        .first()
    )

    if not result:
        return None

    banner = result[0]
    username = result[1]
    profile_name = result[2]

    type_labels = {BannerType.CREATOR: "クリエイター", BannerType.SPECIAL_EVENT: "バナー広告(外部URL)", BannerType.INTERNAL_EVENT: "バナー広告(画像のみ)"}
    status_labels = {BannerStatus.INACTIVE: "無効", BannerStatus.ACTIVE: "有効", BannerStatus.DRAFT: "下書き"}

    return {
        "id": str(banner.id),
        "type": banner.type,
        "type_label": type_labels.get(banner.type, "不明"),
        "title": banner.title,
        "image_key": banner.image_key,
        "image_url": f"{BANNER_IMAGE_URL}/{banner.image_key}",
        "alt_text": banner.alt_text,
        "cta_label": banner.cta_label,
        "creator_id": str(banner.creator_id) if banner.creator_id else None,
        "creator_username": username,
        "creator_profile_name": profile_name,
        "external_url": banner.external_url if banner.external_url else None,
        "status": banner.status,
        "status_label": status_labels.get(banner.status, "不明"),
        "start_at": banner.start_at,
        "end_at": banner.end_at,
        "display_order": banner.display_order,
        "priority": banner.priority,
        "image_source": banner.image_source,
        "created_at": banner.created_at,
        "updated_at": banner.updated_at
    }


def get_pre_register_users_random(
    db: Session,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    イベント"pre-register"に参加しているユーザーをランダムで取得

    Args:
        db: データベースセッション
        limit: 取得件数（デフォルト: 5）

    Returns:
        List[Dict]: ユーザーリスト
    """
    # イベント"pre-register"を取得
    event = db.query(Events).filter(Events.code == EventCode.PRE_REGISTRATION).first()

    if not event:
        return []

    # イベントに参加しているユーザーをランダムで取得
    results = (
        db.query(Users, Profiles.username, Profiles.avatar_url, Profiles.cover_url)
        .join(UserEvents, UserEvents.user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(UserEvents.event_id == event.id)
        .order_by(func.random())
        .limit(limit)
        .all()
    )

    users = []
    for row in results:
        user = row[0]
        username = row[1]
        avatar_url = row[2]
        cover_url = row[3]

        users.append({
            "id": str(user.id),
            "profile_name": user.profile_name,
            "username": username,
            "avatar_url": f"{CDN_URL}/{avatar_url}" if avatar_url else f"{FRONTEND_URL}/assets/no-image.svg ",
            "cover_url": f"{CDN_URL}/{cover_url}" if cover_url else f"{FRONTEND_URL}/assets/mijfans.png",
        })

    return users

# -*- coding: utf-8 -*-
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, func
from app.models.profiles import Profiles
from datetime import datetime, timezone
from uuid import UUID

from app.models.advertising_agencies import AdvertisingAgencies, UserReferrals, AgencyAccessLogs
from app.models.user import Users


def create_advertising_agency(
    db: Session,
    name: str,
    code: str,
    status: int = 1
) -> AdvertisingAgencies:
    """
    新しい広告会社を作成

    Args:
        db: データベースセッション
        name: 会社名
        code: 紹介コード（カスタム）
        status: ステータス（1=有効, 2=停止）

    Returns:
        AdvertisingAgencies: 作成された広告会社
    """
    # コードの重複チェック
    existing = db.query(AdvertisingAgencies).filter(
        AdvertisingAgencies.code == code,
        AdvertisingAgencies.deleted_at.is_(None)
    ).first()

    if existing:
        raise ValueError(f"コード '{code}' は既に使用されています")

    agency = AdvertisingAgencies(
        name=name,
        code=code,
        status=status
    )
    db.add(agency)
    db.flush()
    return agency


def get_advertising_agency_by_id(
    db: Session,
    agency_id: UUID
) -> Optional[AdvertisingAgencies]:
    """
    IDで広告会社を取得

    Args:
        db: データベースセッション
        agency_id: 広告会社ID

    Returns:
        Optional[AdvertisingAgencies]: 広告会社
    """
    return db.query(AdvertisingAgencies).filter(
        AdvertisingAgencies.id == agency_id,
        AdvertisingAgencies.deleted_at.is_(None)
    ).first()


def get_advertising_agency_by_code(
    db: Session,
    code: str
) -> Optional[AdvertisingAgencies]:
    """
    コードで広告会社を取得

    Args:
        db: データベースセッション
        code: 広告会社コード

    Returns:
        Optional[AdvertisingAgencies]: 広告会社
    """
    return db.query(AdvertisingAgencies).filter(
        AdvertisingAgencies.code == code,
        AdvertisingAgencies.deleted_at.is_(None)
    ).first()


def get_advertising_agencies_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    status: Optional[int] = None,
    sort: str = "created_at_desc"
) -> Tuple[List[Dict[str, Any]], int]:
    """
    ページネーション付き広告会社一覧を取得

    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索クエリ（会社名・コード）
        status: ステータスフィルタ（1=有効, 2=停止）
        sort: ソート順

    Returns:
        Tuple[List[Dict], int]: (広告会社リスト, 総件数)
    """
    skip = (page - 1) * limit

    # サブクエリ: 広告会社ごとのユーザー数をカウント
    user_count_subquery = (
        db.query(
            UserReferrals.agency_id,
            func.count(func.distinct(UserReferrals.user_id)).label("user_count")
        )
        .group_by(UserReferrals.agency_id)
        .subquery()
    )

    # サブクエリ: 広告会社ごとのアクセス数をカウント（ユニークセッションのみ）
    access_count_subquery = (
        db.query(
            AgencyAccessLogs.agency_id,
            func.count(func.distinct(AgencyAccessLogs.session_id)).label("access_count")
        )
        .group_by(AgencyAccessLogs.agency_id)
        .subquery()
    )

    # メインクエリ
    query = (
        db.query(
            AdvertisingAgencies,
            user_count_subquery.c.user_count,
            access_count_subquery.c.access_count
        )
        .outerjoin(user_count_subquery, AdvertisingAgencies.id == user_count_subquery.c.agency_id)
        .outerjoin(access_count_subquery, AdvertisingAgencies.id == access_count_subquery.c.agency_id)
        .filter(AdvertisingAgencies.deleted_at.is_(None))
    )

    # ステータスフィルタ
    if status is not None:
        query = query.filter(AdvertisingAgencies.status == status)

    # 検索フィルタ
    if search:
        query = query.filter(
            (AdvertisingAgencies.name.ilike(f"%{search}%")) |
            (AdvertisingAgencies.code.ilike(f"%{search}%"))
        )

    # ソート
    if sort == "name_asc":
        query = query.order_by(asc(AdvertisingAgencies.name))
    elif sort == "name_desc":
        query = query.order_by(desc(AdvertisingAgencies.name))
    elif sort == "created_at_desc":
        query = query.order_by(desc(AdvertisingAgencies.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(AdvertisingAgencies.created_at))
    elif sort == "user_count_desc":
        query = query.order_by(desc(user_count_subquery.c.user_count))
    elif sort == "user_count_asc":
        query = query.order_by(asc(user_count_subquery.c.user_count))
    else:
        query = query.order_by(desc(AdvertisingAgencies.created_at))

    total = query.count()
    results = query.offset(skip).limit(limit).all()

    # データ変換
    agencies = []
    for row in results:
        agency = row[0]
        user_count = row[1] or 0
        access_count = row[2] or 0

        # ステータスラベル
        status_label = "有効" if agency.status == 1 else "停止"

        agencies.append({
            "id": str(agency.id),
            "name": agency.name,
            "code": agency.code,
            "referral_url": None,  # フロントエンドで生成
            "status": agency.status,
            "status_label": status_label,
            "user_count": user_count,
            "access_count": access_count,
            "created_at": agency.created_at,
            "updated_at": agency.updated_at
        })

    return agencies, total


def get_advertising_agency_detail(
    db: Session,
    agency_id: UUID
) -> Optional[Dict[str, Any]]:
    """
    広告会社詳細を取得

    Args:
        db: データベースセッション
        agency_id: 広告会社ID

    Returns:
        Optional[Dict]: 広告会社詳細
    """
    agency = get_advertising_agency_by_id(db, agency_id)
    if not agency:
        return None

    # ユーザー数をカウント
    user_count = db.query(func.count(func.distinct(UserReferrals.user_id))).filter(
        UserReferrals.agency_id == agency_id
    ).scalar() or 0

    # アクセス数をカウント（ユニークセッションのみ）
    access_count = db.query(func.count(func.distinct(AgencyAccessLogs.session_id))).filter(
        AgencyAccessLogs.agency_id == agency_id
    ).scalar() or 0

    # ステータスラベル
    status_label = "有効" if agency.status == 1 else "停止"

    return {
        "id": str(agency.id),
        "name": agency.name,
        "code": agency.code,
        "referral_url": None,  # フロントエンドで生成
        "status": agency.status,
        "status_label": status_label,
        "user_count": user_count,
        "access_count": access_count,
        "created_at": agency.created_at,
        "updated_at": agency.updated_at
    }


def update_advertising_agency(
    db: Session,
    agency_id: UUID,
    name: Optional[str] = None,
    code: Optional[str] = None,
    status: Optional[int] = None
) -> Optional[AdvertisingAgencies]:
    """
    広告会社を更新

    Args:
        db: データベースセッション
        agency_id: 広告会社ID
        name: 会社名
        code: コード
        status: ステータス

    Returns:
        Optional[AdvertisingAgencies]: 更新された広告会社
    """
    agency = get_advertising_agency_by_id(db, agency_id)
    if not agency:
        return None

    if name is not None:
        agency.name = name

    if code is not None and code != agency.code:
        # コードの重複チェック
        existing = db.query(AdvertisingAgencies).filter(
            AdvertisingAgencies.code == code,
            AdvertisingAgencies.id != agency_id,
            AdvertisingAgencies.deleted_at.is_(None)
        ).first()

        if existing:
            raise ValueError(f"コード '{code}' は既に使用されています")

        agency.code = code

    if status is not None:
        agency.status = status

    agency.updated_at = datetime.now(timezone.utc)
    db.flush()
    return agency


def delete_advertising_agency(
    db: Session,
    agency_id: UUID
) -> bool:
    """
    広告会社を削除（論理削除）

    Args:
        db: データベースセッション
        agency_id: 広告会社ID

    Returns:
        bool: 成功フラグ
    """
    agency = get_advertising_agency_by_id(db, agency_id)
    if not agency:
        return False

    agency.deleted_at = datetime.now(timezone.utc)
    db.flush()
    return True


# ====================
# UserReferrals CRUD
# ====================

def get_referred_users(
    db: Session,
    agency_id: UUID,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], int]:
    """
    広告会社に紐づく紹介ユーザー一覧を取得

    Args:
        db: データベースセッション
        agency_id: 広告会社ID
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索クエリ（ユーザー名・メール）

    Returns:
        Tuple[List[Dict], int]: (ユーザーリスト, 総件数)
    """
    skip = (page - 1) * limit

    query = (
        db.query(UserReferrals, Users, Profiles)
        .join(Users, UserReferrals.user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .filter(UserReferrals.agency_id == agency_id)
        .order_by(desc(UserReferrals.created_at))
    )

    # 検索フィルタ
    if search:
        query = query.filter(
            (Profiles.username.ilike(f"%{search}%")) |
            (Users.profile_name.ilike(f"%{search}%")) |
            (Users.email.ilike(f"%{search}%"))
        )

    total = query.count()
    results = query.offset(skip).limit(limit).all()

    users = []
    for row in results:
        referral = row[0]
        user = row[1]
        profile = row[2]

        users.append({
            "user_id": str(user.id),
            "username": profile.username if profile else None,
            "profile_name": user.profile_name,
            "avatar_url": profile.avatar_url if profile else None,
            "email": user.email,
            "referral_code": referral.referral_code,
            "registration_source": referral.registration_source,
            "referred_at": referral.created_at
        })

    return users, total


def create_user_referral(
    db: Session,
    user_id: UUID,
    agency_id: UUID,
    referral_code: str,
    registration_source: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    landing_page: Optional[str] = None
) -> UserReferrals:
    """
    ユーザーリファラルを作成

    Args:
        db: データベースセッション
        user_id: ユーザーID
        agency_id: 広告会社ID
        referral_code: 使用されたリファラルコード
        registration_source: 登録元
        ip_address: IPアドレス
        user_agent: ユーザーエージェント
        landing_page: 最初にアクセスしたページURL

    Returns:
        UserReferrals: 作成されたリファラル
    """
    # 既存のリファラルがあるか確認
    existing = db.query(UserReferrals).filter(
        UserReferrals.user_id == user_id
    ).first()

    if existing:
        # 既に存在する場合は何もしない
        return existing

    referral = UserReferrals(
        user_id=user_id,
        agency_id=agency_id,
        referral_code=referral_code,
        registration_source=registration_source,
        ip_address=ip_address,
        user_agent=user_agent,
        landing_page=landing_page
    )
    db.add(referral)
    db.flush()
    return referral


def create_agency_access_log(
    db: Session,
    agency_id: UUID,
    referral_code: str,
    session_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    landing_page: Optional[str] = None
) -> AgencyAccessLogs:
    """
    広告会社アクセスログを作成

    Args:
        db: データベースセッション
        agency_id: 広告会社ID
        referral_code: リファラルコード
        session_id: セッションID
        ip_address: IPアドレス
        user_agent: ユーザーエージェント
        landing_page: アクセスしたページURL

    Returns:
        AgencyAccessLogs: 作成されたアクセスログ
    """
    # 同じセッションIDで既にログがあるか確認（重複防止）
    existing = db.query(AgencyAccessLogs).filter(
        AgencyAccessLogs.session_id == session_id,
        AgencyAccessLogs.agency_id == agency_id
    ).first()

    if existing:
        # 既に存在する場合は何もしない
        return existing

    access_log = AgencyAccessLogs(
        agency_id=agency_id,
        referral_code=referral_code,
        session_id=session_id,
        ip_address=ip_address,
        user_agent=user_agent,
        landing_page=landing_page
    )
    db.add(access_log)
    db.flush()
    return access_log

# -*- coding: utf-8 -*-
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, func
from datetime import datetime
from uuid import UUID

from app.models.companies import Companies, CompanyUsers
from app.models.user import Users


def create_company(
    db: Session,
    name: str,
    parent_company_id: Optional[UUID] = None
) -> Companies:
    """
    新しい企業を作成

    Args:
        db: データベースセッション
        name: 企業名
        parent_company_id: 親企業ID（2次代理店の場合）

    Returns:
        Companies: 作成された企業
    """
    company = Companies(
        name=name,
        parent_company_id=parent_company_id
    )
    db.add(company)
    db.flush()
    return company


def get_company_by_id(
    db: Session,
    company_id: UUID
) -> Optional[Companies]:
    """
    IDで企業を取得

    Args:
        db: データベースセッション
        company_id: 企業ID

    Returns:
        Optional[Companies]: 企業
    """
    return db.query(Companies).filter(
        Companies.id == company_id,
        Companies.deleted_at.is_(None)
    ).first()

def get_company_by_code(    
    db: Session,
    code: UUID
) -> Optional[Companies]:
    """
    コードで企業を取得（企業コードから企業を取得）

    Args:
        db: データベースセッション
        code: 企業コード

    Returns:
        Optional[Companies]: 企業
    """
    return (
        db.query(Companies)
        .filter(
            Companies.code == code,
            Companies.deleted_at.is_(None)
        )
        .first()
    )

def get_companies_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    type: Optional[str] = None,
    sort: str = "created_at_desc"
) -> Tuple[List[Dict[str, Any]], int]:
    """
    ページネーション付き企業一覧を取得（管理画面用）

    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索クエリ（企業名・企業コード）
        type: タイプフィルタ（primary=1次代理店, secondary=2次代理店, all=すべて）
        sort: ソート順

    Returns:
        Tuple[List[Dict], int]: (企業リスト, 総件数)
    """
    skip = (page - 1) * limit

    # サブクエリ: 企業ごとのユーザー数をカウント
    user_count_subquery = (
        db.query(
            CompanyUsers.company_id,
            func.count(CompanyUsers.id).label("user_count")
        )
        .filter(CompanyUsers.deleted_at.is_(None))
        .group_by(CompanyUsers.company_id)
        .subquery()
    )

    # サブクエリ: 企業ごとの子企業数をカウント
    child_count_subquery = (
        db.query(
            Companies.parent_company_id,
            func.count(Companies.id).label("child_count")
        )
        .filter(Companies.deleted_at.is_(None))
        .group_by(Companies.parent_company_id)
        .subquery()
    )

    # メインクエリ
    query = (
        db.query(
            Companies,
            user_count_subquery.c.user_count,
            child_count_subquery.c.child_count
        )
        .outerjoin(user_count_subquery, Companies.id == user_count_subquery.c.company_id)
        .outerjoin(child_count_subquery, Companies.id == child_count_subquery.c.parent_company_id)
        .filter(Companies.deleted_at.is_(None))
    )

    # タイプフィルタ
    if type == "primary":
        query = query.filter(Companies.parent_company_id.is_(None))
    elif type == "secondary":
        query = query.filter(Companies.parent_company_id.isnot(None))

    # 検索フィルタ
    if search:
        query = query.filter(
            Companies.name.ilike(f"%{search}%")
        )

    # ソート
    if sort == "name_asc":
        query = query.order_by(asc(Companies.name))
    elif sort == "name_desc":
        query = query.order_by(desc(Companies.name))
    elif sort == "created_at_desc":
        query = query.order_by(desc(Companies.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(Companies.created_at))
    elif sort == "user_count_desc":
        query = query.order_by(desc(user_count_subquery.c.user_count))
    elif sort == "user_count_asc":
        query = query.order_by(asc(user_count_subquery.c.user_count))
    else:
        query = query.order_by(desc(Companies.created_at))

    total = query.count()
    results = query.offset(skip).limit(limit).all()

    # データ変換
    companies = []
    for row in results:
        company = row[0]
        user_count = row[1] or 0
        child_count = row[2] or 0

        # 親企業名を取得
        parent_company_name = None
        if company.parent_company_id:
            parent = db.query(Companies).filter(
                Companies.id == company.parent_company_id
            ).first()
            parent_company_name = parent.name if parent else None

        companies.append({
            "id": str(company.id),
            "name": company.name,
            "parent_company_id": str(company.parent_company_id) if company.parent_company_id else None,
            "parent_company_name": parent_company_name,
            "code": str(company.code),
            "type": "secondary" if company.parent_company_id else "primary",
            "user_count": user_count,
            "child_count": child_count,
            "created_at": company.created_at,
            "updated_at": company.updated_at
        })

    return companies, total


def get_company_detail(
    db: Session,
    company_id: UUID
) -> Optional[Dict[str, Any]]:
    """
    企業詳細を取得（管理画面用）

    Args:
        db: データベースセッション
        company_id: 企業ID

    Returns:
        Optional[Dict]: 企業詳細
    """
    company = get_company_by_id(db, company_id)
    if not company:
        return None

    # ユーザー数をカウント
    user_count = db.query(func.count(CompanyUsers.id)).filter(
        CompanyUsers.company_id == company_id,
        CompanyUsers.deleted_at.is_(None)
    ).scalar() or 0

    # 子企業数をカウント
    child_count = db.query(func.count(Companies.id)).filter(
        Companies.parent_company_id == company_id,
        Companies.deleted_at.is_(None)
    ).scalar() or 0

    # 親企業名を取得
    parent_company_name = None
    if company.parent_company_id:
        parent = db.query(Companies).filter(
            Companies.id == company.parent_company_id
        ).first()
        parent_company_name = parent.name if parent else None

    return {
        "id": str(company.id),
        "name": company.name,
        "parent_company_id": str(company.parent_company_id) if company.parent_company_id else None,
        "parent_company_name": parent_company_name,
        "code": str(company.code),
        "type": "secondary" if company.parent_company_id else "primary",
        "user_count": user_count,
        "child_count": child_count,
        "created_at": company.created_at,
        "updated_at": company.updated_at
    }


def update_company(
    db: Session,
    company_id: UUID,
    name: Optional[str] = None,
    parent_company_id: Optional[UUID] = None
) -> Optional[Companies]:
    """
    企業を更新

    Args:
        db: データベースセッション
        company_id: 企業ID
        name: 企業名
        parent_company_id: 親企業ID

    Returns:
        Optional[Companies]: 更新された企業
    """
    company = get_company_by_id(db, company_id)
    if not company:
        return None

    if name is not None:
        company.name = name
    if parent_company_id is not None:
        company.parent_company_id = parent_company_id

    company.updated_at = datetime.utcnow()
    db.flush()
    return company


def delete_company(
    db: Session,
    company_id: UUID
) -> bool:
    """
    企業を削除（論理削除）

    Args:
        db: データベースセッション
        company_id: 企業ID

    Returns:
        bool: 成功フラグ
    """
    company = get_company_by_id(db, company_id)
    if not company:
        return False

    # 紹介クリエイターが存在するか確認
    user_count = db.query(func.count(CompanyUsers.id)).filter(
        CompanyUsers.company_id == company_id,
        CompanyUsers.deleted_at.is_(None)
    ).scalar() or 0

    if user_count > 0:
        return False

    # 子企業が存在するか確認
    child_count = db.query(func.count(Companies.id)).filter(
        Companies.parent_company_id == company_id,
        Companies.deleted_at.is_(None)
    ).scalar() or 0

    if child_count > 0:
        return False

    company.deleted_at = datetime.utcnow()
    db.flush()
    return True


# ====================
# CompanyUsers CRUD
# ====================

def get_company_users(
    db: Session,
    company_id: UUID,
    page: int = 1,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    企業に紐づくユーザー（クリエイター）一覧を取得

    Args:
        db: データベースセッション
        company_id: 企業ID
        page: ページ番号
        limit: 1ページあたりの件数

    Returns:
        Tuple[List[Dict], int]: (ユーザーリスト, 総件数)
    """
    skip = (page - 1) * limit

    query = (
        db.query(CompanyUsers, Users)
        .join(Users, CompanyUsers.user_id == Users.id)
        .filter(
            CompanyUsers.company_id == company_id,
            CompanyUsers.deleted_at.is_(None)
        )
        .order_by(desc(CompanyUsers.created_at))
    )

    total = query.count()
    results = query.offset(skip).limit(limit).all()

    users = []
    for row in results:
        company_user = row[0]
        user = row[1]

        users.append({
            "id": str(company_user.id),
            "company_id": str(company_user.company_id),
            "user_id": str(company_user.user_id),
            "user": {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "profile_name": user.profile_name,
                "role": user.role
            },
            "company_fee_percent": company_user.company_fee_percent,
            "created_at": company_user.created_at,
            "updated_at": company_user.updated_at
        })

    return users, total


def add_company_user(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    company_fee_percent: int = 3
) -> CompanyUsers:
    """
    企業にユーザー（クリエイター）を追加

    Args:
        db: データベースセッション
        company_id: 企業ID
        user_id: ユーザーID
        company_fee_percent: 企業への支払い率（デフォルト3%）

    Returns:
        CompanyUsers: 作成されたCompanyUser
    """
    # 既存の紐付けがあるか確認
    existing = db.query(CompanyUsers).filter(
        CompanyUsers.company_id == company_id,
        CompanyUsers.user_id == user_id,
        CompanyUsers.deleted_at.is_(None)
    ).first()

    if existing:
        # 既に存在する場合はエラー
        raise ValueError("このユーザーは既に企業に紐付けられています")

    company_user = CompanyUsers(
        company_id=company_id,
        user_id=user_id,
        company_fee_percent=company_fee_percent
    )
    db.add(company_user)
    db.flush()
    return company_user


def update_company_user_fee(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    company_fee_percent: int
) -> Optional[CompanyUsers]:
    """
    企業ユーザーの支払い率を更新

    Args:
        db: データベースセッション
        company_id: 企業ID
        user_id: ユーザーID
        company_fee_percent: 新しい支払い率

    Returns:
        Optional[CompanyUsers]: 更新されたCompanyUser
    """
    company_user = db.query(CompanyUsers).filter(
        CompanyUsers.company_id == company_id,
        CompanyUsers.user_id == user_id,
        CompanyUsers.deleted_at.is_(None)
    ).first()

    if not company_user:
        return None

    company_user.company_fee_percent = company_fee_percent
    company_user.updated_at = datetime.utcnow()
    db.flush()
    return company_user


def remove_company_user(
    db: Session,
    company_id: UUID,
    user_id: UUID
) -> bool:
    """
    企業からユーザーを削除（論理削除）

    Args:
        db: データベースセッション
        company_id: 企業ID
        user_id: ユーザーID

    Returns:
        bool: 成功フラグ
    """
    company_user = db.query(CompanyUsers).filter(
        CompanyUsers.company_id == company_id,
        CompanyUsers.user_id == user_id,
        CompanyUsers.deleted_at.is_(None)
    ).first()

    if not company_user:
        return False

    company_user.deleted_at = datetime.utcnow()
    db.flush()
    return True


def get_all_primary_companies(
    db: Session
) -> List[Dict[str, Any]]:
    """
    全ての1次代理店を取得（親企業選択用）

    Args:
        db: データベースセッション

    Returns:
        List[Dict]: 1次代理店リスト
    """
    companies = db.query(Companies).filter(
        Companies.parent_company_id.is_(None),
        Companies.deleted_at.is_(None)
    ).order_by(asc(Companies.name)).all()

    return [
        {
            "id": str(company.id),
            "name": company.name,
            "code": str(company.code)
        }
        for company in companies
    ]

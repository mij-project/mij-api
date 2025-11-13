# -*- coding: utf-8 -*-
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, asc, func
from app.models.profiles import Profiles
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

    # サブクエリ: 企業ごとのユーザー数をカウント（is_referrer=Trueのみ）
    user_count_subquery = (
        db.query(
            CompanyUsers.company_id,
            func.count(CompanyUsers.id).label("user_count")
        )
        .filter(
            CompanyUsers.deleted_at.is_(None),
            CompanyUsers.is_referrer.is_(True)
        )
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

    # ユーザー数をカウント（is_referrer=Trueのみ）
    user_count = db.query(func.count(CompanyUsers.id)).filter(
        CompanyUsers.company_id == company_id,
        CompanyUsers.deleted_at.is_(None),
        CompanyUsers.is_referrer.is_(True)
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
        db.query(CompanyUsers, Users, Profiles)
        .join(Users, CompanyUsers.user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
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
        profile = row[2]

        # 関連企業の情報を取得
        # - is_referrer = False の場合: 2次代理店からの紹介なので、2次代理店の情報を取得
        # - is_referrer = True の場合: 1次代理店の情報を取得（2次代理店の画面で必要）
        referrer_company_id = None
        referrer_company = None
        parent_company_id = None
        parent_company = None

        # 同じuser_idで別の企業との紐付けを検索
        other_records = db.query(CompanyUsers).filter(
            CompanyUsers.user_id == company_user.user_id,
            CompanyUsers.company_id != company_user.company_id,
            CompanyUsers.deleted_at.is_(None)
        ).all()

        for other_record in other_records:
            other_company = db.query(Companies).filter(
                Companies.id == other_record.company_id
            ).first()

            if not other_company:
                continue

            company_info = {
                "id": str(other_company.id),
                "name": other_company.name,
                "code": str(other_company.code),
                "fee_percent": other_record.company_fee_percent
            }

            # is_referrer = True のレコードは紹介元（2次代理店）
            if other_record.is_referrer is True:
                referrer_company_id = str(other_record.company_id)
                referrer_company = company_info
            # is_referrer = False のレコードは親企業（1次代理店）
            elif other_record.is_referrer is False:
                parent_company_id = str(other_record.company_id)
                parent_company = company_info

        # 現在の企業情報を取得（キャッシュのために一度だけ取得）
        if not hasattr(get_company_users, '_current_company_cache'):
            get_company_users._current_company_cache = {}

        if company_id not in get_company_users._current_company_cache:
            current_company = db.query(Companies).filter(
                Companies.id == company_id
            ).first()
            get_company_users._current_company_cache[company_id] = current_company
        else:
            current_company = get_company_users._current_company_cache[company_id]

        # 2次企業の場合、親企業情報が必要
        # - 自社紹介クリエイター（is_referrer=True）: parent_companyに1次企業の情報を設定
        # - 1次企業からの2次代理店紹介（is_referrer=False）: 既にreferrer_companyに2次企業情報がある
        if current_company and current_company.parent_company_id:
            if company_user.is_referrer and not parent_company_id:
                # 2次企業の自社紹介: 親企業（1次企業）の情報を取得
                parent_comp = db.query(Companies).filter(
                    Companies.id == current_company.parent_company_id
                ).first()
                if parent_comp:
                    # 親企業とのcompany_usersレコードを検索して支払い率を取得
                    parent_cu = db.query(CompanyUsers).filter(
                        CompanyUsers.user_id == company_user.user_id,
                        CompanyUsers.company_id == parent_comp.id,
                        CompanyUsers.deleted_at.is_(None)
                    ).first()

                    # parent_cuが存在しない場合、このクリエイターは1次企業に登録されていない
                    # デフォルト値として0を使用し、フロントエンドで新規作成を促す
                    parent_company_id = str(parent_comp.id)
                    parent_company = {
                        "id": str(parent_comp.id),
                        "name": parent_comp.name,
                        "code": str(parent_comp.code),
                        "fee_percent": parent_cu.company_fee_percent if parent_cu else 0,
                        "exists": parent_cu is not None  # レコードが存在するかのフラグ
                    }

        # 1次企業の場合で、is_referrer=Falseのクリエイター（2次代理店からの紹介）
        # referrer_companyには既に2次企業の情報が入っているはず
        user_data = {
            "id": str(company_user.id),
            "company_id": str(company_user.company_id),
            "user_id": str(company_user.user_id),
            "user": {
                "id": str(user.id),
                "email": user.email,
                "username": profile.username if profile else None,
                "profile_name": user.profile_name,
                "avatar_url": profile.avatar_url if profile else None,
                "role": user.role
            },
            "company_fee_percent": company_user.company_fee_percent,
            "is_referrer": company_user.is_referrer if company_user.is_referrer is not None else False,
            "referrer_company_id": referrer_company_id,
            "referrer_company": referrer_company,
            "parent_company_id": parent_company_id,
            "parent_company": parent_company,
            "created_at": company_user.created_at,
            "updated_at": company_user.updated_at
        }

        users.append(user_data)

    return users, total


def add_company_user(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    company_fee_percent: int = 3,
    is_referrer: bool = False
) -> CompanyUsers:
    """
    企業にユーザー（クリエイター）を追加

    Args:
        db: データベースセッション
        company_id: 企業ID
        user_id: ユーザーID
        company_fee_percent: 企業への支払い率（デフォルト3%）
        is_referrer: 紹介者フラグ（デフォルトFalse）

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
        company_fee_percent=company_fee_percent,
        is_referrer=is_referrer
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

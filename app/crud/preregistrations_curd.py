from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from app.models.preregistrations import Preregistrations
from uuid import UUID
from typing import List, Optional, Tuple

def is_preregistration_exists(db: Session, email: str) -> bool:
    """
    登録済みのアドレスかを確認する
    """
    return db.query(Preregistrations).filter(Preregistrations.email == email).first() is not None

def create_preregistration(db: Session, preregistration_data: Preregistrations) -> Preregistrations:
    """
    事前登録データを作成する
    Args:
        db: データベースセッション
        preregistration_data: 事前登録データ
    Returns:
        Preregistrations: 事前登録データ
    """
    db.add(preregistration_data)
    db.commit()
    db.refresh(preregistration_data)
    return preregistration_data

def get_preregistrations_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    sort: str = "created_at_desc"
) -> Tuple[List[Preregistrations], int]:
    """
    ページネーション付き事前登録一覧を取得

    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索クエリ（name, email, x_nameで検索）
        sort: ソート順

    Returns:
        Tuple[List[Preregistrations], int]: (事前登録リスト, 総件数)
    """
    skip = (page - 1) * limit

    query = db.query(Preregistrations).filter(Preregistrations.deleted_at.is_(None))

    # 検索フィルタ
    if search:
        query = query.filter(
            (Preregistrations.name.ilike(f"%{search}%")) |
            (Preregistrations.email.ilike(f"%{search}%")) |
            (Preregistrations.x_name.ilike(f"%{search}%"))
        )

    # ソート処理
    if sort == "created_at_desc":
        query = query.order_by(desc(Preregistrations.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(Preregistrations.created_at))
    elif sort == "name_asc":
        query = query.order_by(asc(Preregistrations.name))
    elif sort == "name_desc":
        query = query.order_by(desc(Preregistrations.name))
    elif sort == "email_asc":
        query = query.order_by(asc(Preregistrations.email))
    else:
        query = query.order_by(desc(Preregistrations.created_at))

    total = query.count()
    preregistrations = query.offset(skip).limit(limit).all()

    return preregistrations, total

def get_preregistration_by_email(db: Session, email: str) -> bool:
    """
    事前登録データが存在するかを確認
    """
    return db.query(Preregistrations).filter(Preregistrations.email == email).first() is not None
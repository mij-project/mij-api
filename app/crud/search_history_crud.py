from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.models.search_history import SearchHistory


def create_or_update_search_history(
    db: Session,
    user_id: UUID,
    query: str,
    search_type: Optional[str] = None,
    filters: Optional[dict] = None
) -> SearchHistory:
    """
    検索履歴を作成または更新
    同一ユーザー・同一クエリの場合は created_at を更新
    """
    existing = (
        db.query(SearchHistory)
        .filter(
            SearchHistory.user_id == user_id,
            SearchHistory.query == query
        )
        .first()
    )

    if existing:
        existing.created_at = datetime.now(timezone.utc)
        existing.search_type = search_type
        existing.filters = filters
        db.commit()
        db.refresh(existing)
        return existing

    # 新規作成
    history = SearchHistory(
        user_id=user_id,
        query=query,
        search_type=search_type,
        filters=filters
    )
    db.add(history)

    # 50件を超える場合は古いものを削除
    _cleanup_old_histories(db, user_id, max_count=50)

    db.commit()
    db.refresh(history)
    return history


def get_search_histories(
    db: Session,
    user_id: UUID,
    limit: int = 10
) -> List[SearchHistory]:
    """
    検索履歴を取得 (最新順)
    """
    return (
        db.query(SearchHistory)
        .filter(SearchHistory.user_id == user_id)
        .order_by(desc(SearchHistory.created_at))
        .limit(limit)
        .all()
    )


def delete_search_history(
    db: Session,
    history_id: UUID,
    user_id: UUID
) -> bool:
    """
    検索履歴を削除 (個別)
    """
    history = (
        db.query(SearchHistory)
        .filter(
            SearchHistory.id == history_id,
            SearchHistory.user_id == user_id
        )
        .first()
    )

    if history:
        db.delete(history)
        db.commit()
        return True
    return False


def delete_all_search_histories(
    db: Session,
    user_id: UUID
) -> int:
    """
    検索履歴を全削除
    """
    count = (
        db.query(SearchHistory)
        .filter(SearchHistory.user_id == user_id)
        .delete()
    )
    db.commit()
    return count


def cleanup_expired_histories(db: Session, days: int = 90) -> int:
    """
    期限切れの検索履歴を削除 (バッチ処理用)
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    count = (
        db.query(SearchHistory)
        .filter(SearchHistory.created_at < cutoff_date)
        .delete()
    )
    db.commit()
    return count


def _cleanup_old_histories(db: Session, user_id: UUID, max_count: int = 50):
    """
    ユーザーの検索履歴が上限を超える場合、古いものを削除
    """
    histories = (
        db.query(SearchHistory)
        .filter(SearchHistory.user_id == user_id)
        .order_by(desc(SearchHistory.created_at))
        .all()
    )

    if len(histories) >= max_count:
        to_delete = histories[max_count - 1:]
        for history in to_delete:
            db.delete(history)


def get_all_search_histories_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    user_search: Optional[str] = None,
    search_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    sort: str = "created_at_desc"
) -> tuple[List[SearchHistory], int]:
    """
    全ユーザーの検索履歴を取得（ページネーション対応、フィルタリング対応）
    
    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索クエリでの検索
        user_search: ユーザー名/プロフィール名での検索
        search_type: 検索タイプでのフィルタ
        start_date: 開始日時
        end_date: 終了日時
        sort: ソート順（created_at_desc, created_at_asc, query_asc, query_desc）
    
    Returns:
        (検索履歴リスト, 総件数)
    """
    from app.models.user import Users
    from app.models.profiles import Profiles
    from sqlalchemy import or_, func, asc
    
    # UsersとProfilesをjoin（左外部結合でProfilesがない場合も取得可能に）
    query = (
        db.query(SearchHistory)
        .join(Users, SearchHistory.user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
    )
    
    # 検索クエリでのフィルタ
    if search:
        query = query.filter(SearchHistory.query.ilike(f"%{search}%"))
    
    # ユーザー名/プロフィール名でのフィルタ
    if user_search:
        query = query.filter(
            or_(
                Users.profile_name.ilike(f"%{user_search}%"),
                Profiles.username.ilike(f"%{user_search}%")
            )
        )
    
    # 検索タイプでのフィルタ
    if search_type:
        query = query.filter(SearchHistory.search_type == search_type)
    
    # 日付範囲でのフィルタ
    if start_date:
        query = query.filter(SearchHistory.created_at >= start_date)
    if end_date:
        query = query.filter(SearchHistory.created_at <= end_date)
    
    # ソート
    if sort == "created_at_desc":
        query = query.order_by(desc(SearchHistory.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(SearchHistory.created_at))
    elif sort == "query_asc":
        query = query.order_by(asc(SearchHistory.query))
    elif sort == "query_desc":
        query = query.order_by(desc(SearchHistory.query))
    else:
        query = query.order_by(desc(SearchHistory.created_at))
    
    # 総件数を取得
    total = query.count()
    
    # ページネーション
    offset = (page - 1) * limit
    histories = query.offset(offset).limit(limit).all()
    
    return histories, total

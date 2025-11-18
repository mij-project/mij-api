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

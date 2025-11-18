from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, func, and_
from datetime import datetime, timezone
from uuid import UUID

from app.models.events import Events, UserEvents
from app.models.user import Users
from app.models.profiles import Profiles


def create_event(
    db: Session,
    event_data: dict[str, Any]
) -> Events:
    """
    新しいイベントを作成

    Args:
        db: データベースセッション
        event_data: イベント作成データ

    Returns:
        Events: 作成されたイベント
    """
    event = Events(**event_data)
    db.add(event)
    db.flush()
    return event


def get_event_by_id(
    db: Session,
    event_id: UUID
) -> Optional[Events]:
    """
    IDでイベントを取得

    Args:
        db: データベースセッション
        event_id: イベントID

    Returns:
        Optional[Events]: イベント
    """
    return db.query(Events).filter(
        Events.id == event_id,
        Events.deleted_at.is_(None)
    ).first()


def get_event_by_code(
    db: Session,
    code: str
) -> Optional[Events]:
    """
    コードでイベントを取得

    Args:
        db: データベースセッション
        code: イベントコード

    Returns:
        Optional[Events]: イベント
    """
    return db.query(Events).filter(
        Events.code == code,
        Events.deleted_at.is_(None)
    ).first()


def get_events_list(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    status: Optional[int] = None,
    sort: str = "created_at_desc"
) -> Tuple[List[Dict[str, Any]], int]:
    """
    イベント一覧を取得

    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索文字列（名前・コード）
        status: ステータスフィルタ
        sort: ソート順

    Returns:
        Tuple[List[Dict], int]: イベントリストと総件数
    """
    # 参加者数のサブクエリ
    participant_count_subquery = (
        db.query(
            UserEvents.event_id,
            func.count(UserEvents.user_id).label('participant_count')
        )
        .group_by(UserEvents.event_id)
        .subquery()
    )

    # ベースクエリ
    query = (
        db.query(
            Events,
            func.coalesce(participant_count_subquery.c.participant_count, 0).label('participant_count')
        )
        .outerjoin(participant_count_subquery, Events.id == participant_count_subquery.c.event_id)
        .filter(Events.deleted_at.is_(None))
    )

    # 検索フィルタ
    if search:
        query = query.filter(
            (Events.name.ilike(f"%{search}%")) |
            (Events.code.ilike(f"%{search}%"))
        )

    # ステータスフィルタ
    if status is not None:
        query = query.filter(Events.status == status)

    # 総件数取得
    total = query.count()

    # ソート
    if sort == "created_at_desc":
        query = query.order_by(desc(Events.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(Events.created_at))
    elif sort == "start_date_desc":
        query = query.order_by(desc(Events.start_date))
    elif sort == "start_date_asc":
        query = query.order_by(asc(Events.start_date))
    elif sort == "name_asc":
        query = query.order_by(asc(Events.name))
    elif sort == "name_desc":
        query = query.order_by(desc(Events.name))
    else:
        query = query.order_by(desc(Events.created_at))

    # ページネーション
    offset = (page - 1) * limit
    results = query.offset(offset).limit(limit).all()

    # レスポンス整形
    events = []
    for row in results:
        event = row[0]
        participant_count = row[1]
        events.append({
            'id': str(event.id),
            'code': event.code,
            'name': event.name,
            'description': event.description,
            'status': event.status,
            'start_date': event.start_date,
            'end_date': event.end_date,
            'participant_count': participant_count,
            'created_at': event.created_at,
            'updated_at': event.updated_at,
        })

    return events, total


def update_event(
    db: Session,
    event: Events,
    update_data: dict[str, Any]
) -> Events:
    """
    イベント情報を更新

    Args:
        db: データベースセッション
        event: 更新対象のイベント
        update_data: 更新データ

    Returns:
        Events: 更新されたイベント
    """
    for key, value in update_data.items():
        if value is not None:
            setattr(event, key, value)

    event.updated_at = datetime.now(timezone.utc)
    db.flush()
    return event


def delete_event(
    db: Session,
    event: Events
) -> None:
    """
    イベントを物理削除

    Args:
        db: データベースセッション
        event: 削除対象のイベント
    """
    db.delete(event)
    db.flush()


def get_event_participants(
    db: Session,
    event_id: UUID,
    page: int = 1,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    イベント参加者一覧を取得

    Args:
        db: データベースセッション
        event_id: イベントID
        page: ページ番号
        limit: 1ページあたりの件数

    Returns:
        Tuple[List[Dict], int]: 参加者リストと総件数
    """
    # ベースクエリ
    query = (
        db.query(UserEvents, Users, Profiles)
        .join(Users, UserEvents.user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .filter(UserEvents.event_id == event_id)
    )

    # 総件数取得
    total = query.count()

    # ページネーション
    offset = (page - 1) * limit
    results = query.order_by(desc(UserEvents.created_at)).offset(offset).limit(limit).all()

    # レスポンス整形
    participants = []
    for row in results:
        user_event = row[0]
        user = row[1]
        profile = row[2]

        participants.append({
            'user_id': str(user.id),
            'username': profile.username if profile else None,
            'profile_name': user.profile_name,
            'avatar_url': profile.avatar_url if profile else None,
            'participated_at': user_event.created_at,
        })

    return participants, total


def add_event_participant(
    db: Session,
    event_id: UUID,
    user_id: UUID
) -> UserEvents:
    """
    イベント参加者を追加

    Args:
        db: データベースセッション
        event_id: イベントID
        user_id: ユーザーID

    Returns:
        UserEvents: 作成された参加記録
    """
    user_event = UserEvents(
        event_id=event_id,
        user_id=user_id
    )
    db.add(user_event)
    db.flush()
    return user_event


def remove_event_participant(
    db: Session,
    event_id: UUID,
    user_id: UUID
) -> None:
    """
    イベント参加者を削除

    Args:
        db: データベースセッション
        event_id: イベントID
        user_id: ユーザーID
    """
    db.query(UserEvents).filter(
        UserEvents.event_id == event_id,
        UserEvents.user_id == user_id
    ).delete()
    db.flush()


def check_participant_exists(
    db: Session,
    event_id: UUID,
    user_id: UUID
) -> bool:
    """
    ユーザーがイベントに参加済みかチェック

    Args:
        db: データベースセッション
        event_id: イベントID
        user_id: ユーザーID

    Returns:
        bool: 参加済みの場合True
    """
    return db.query(UserEvents).filter(
        UserEvents.event_id == event_id,
        UserEvents.user_id == user_id
    ).first() is not None

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
import math

from app.deps.auth import get_current_admin_user
from app.db.base import get_db
from app.models.admins import Admins
from app.crud import events_crud
from app.schemas.events import (
    EventCreateRequest,
    EventUpdateRequest,
    EventDetail,
    EventListResponse,
    EventParticipantListResponse
)

router = APIRouter()


@router.get("", response_model=EventListResponse)
def get_events(
    page: int = Query(1, ge=1, description="ページ番号"),
    limit: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    status: Optional[int] = Query(None, description="0=無効, 1=有効, 2=下書き"),
    search: Optional[str] = Query(None, description="検索クエリ（名前・コード）"),
    sort: str = Query("created_at_desc", description="created_at_desc/created_at_asc/start_date_desc/start_date_asc/name_asc/name_desc"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    イベント一覧を取得（管理者用）

    - **page**: ページ番号（1から開始）
    - **limit**: 1ページあたりの件数（1-100）
    - **status**: ステータスフィルタ（0=無効, 1=有効, 2=下書き）
    - **search**: 検索クエリ（名前・コード）
    - **sort**: ソート順
    """
    events, total = events_crud.get_events_list(
        db=db,
        page=page,
        limit=limit,
        status=status,
        search=search,
        sort=sort
    )

    total_pages = math.ceil(total / limit) if total > 0 else 0

    # status_labelを追加
    status_labels = {0: "無効", 1: "有効", 2: "下書き"}
    for event in events:
        event['status_label'] = status_labels.get(event['status'], "不明")

    return EventListResponse(
        items=[EventDetail(**event) for event in events],
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )


@router.get("/{event_id}", response_model=EventDetail)
def get_event(
    event_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    イベント詳細を取得（管理者用）

    - **event_id**: イベントID
    """
    event = events_crud.get_event_by_id(db, event_id)

    if not event:
        raise HTTPException(status_code=404, detail="イベントが見つかりません")

    # 参加者数を取得
    _, participant_count = events_crud.get_event_participants(db, event_id, page=1, limit=1)

    status_labels = {0: "無効", 1: "有効", 2: "下書き"}

    return EventDetail(
        id=str(event.id),
        code=event.code,
        name=event.name,
        description=event.description,
        status=event.status,
        status_label=status_labels.get(event.status, "不明"),
        start_date=event.start_date,
        end_date=event.end_date,
        participant_count=participant_count,
        created_at=event.created_at,
        updated_at=event.updated_at
    )


@router.post("", response_model=EventDetail)
def create_event(
    request: EventCreateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    イベントを作成（管理者用）

    イベント情報を登録します。codeは一意である必要があります。
    """
    # コードの重複チェック
    existing = events_crud.get_event_by_code(db, request.code)
    if existing:
        raise HTTPException(status_code=400, detail="このコードは既に使用されています")

    try:
        event_data = request.model_dump()
        event = events_crud.create_event(db, event_data)
        db.commit()
        db.refresh(event)

        status_labels = {0: "無効", 1: "有効", 2: "下書き"}

        return EventDetail(
            id=str(event.id),
            code=event.code,
            name=event.name,
            description=event.description,
            status=event.status,
            status_label=status_labels.get(event.status, "不明"),
            start_date=event.start_date,
            end_date=event.end_date,
            participant_count=0,
            created_at=event.created_at,
            updated_at=event.updated_at
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"イベントの作成に失敗しました: {str(e)}")


@router.put("/{event_id}", response_model=EventDetail)
def update_event(
    event_id: UUID,
    request: EventUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    イベント情報を更新（管理者用）

    - **event_id**: イベントID
    """
    event = events_crud.get_event_by_id(db, event_id)

    if not event:
        raise HTTPException(status_code=404, detail="イベントが見つかりません")

    # コードの重複チェック（変更がある場合）
    if request.code and request.code != event.code:
        existing = events_crud.get_event_by_code(db, request.code)
        if existing:
            raise HTTPException(status_code=400, detail="このコードは既に使用されています")

    try:
        update_data = request.model_dump(exclude_unset=True)
        event = events_crud.update_event(db, event, update_data)
        db.commit()
        db.refresh(event)

        # 参加者数を取得
        _, participant_count = events_crud.get_event_participants(db, event_id, page=1, limit=1)

        status_labels = {0: "無効", 1: "有効", 2: "下書き"}

        return EventDetail(
            id=str(event.id),
            code=event.code,
            name=event.name,
            description=event.description,
            status=event.status,
            status_label=status_labels.get(event.status, "不明"),
            start_date=event.start_date,
            end_date=event.end_date,
            participant_count=participant_count,
            created_at=event.created_at,
            updated_at=event.updated_at
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"イベントの更新に失敗しました: {str(e)}")


@router.delete("/{event_id}")
def delete_event(
    event_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    イベントを削除（管理者用）

    論理削除されます。

    - **event_id**: イベントID
    """
    event = events_crud.get_event_by_id(db, event_id)

    if not event:
        raise HTTPException(status_code=404, detail="イベントが見つかりません")

    try:
        events_crud.delete_event(db, event)
        db.commit()

        return {"message": "イベントを削除しました"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"イベントの削除に失敗しました: {str(e)}")


@router.get("/{event_id}/participants", response_model=EventParticipantListResponse)
def get_event_participants(
    event_id: UUID,
    page: int = Query(1, ge=1, description="ページ番号"),
    limit: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    イベント参加者一覧を取得（管理者用）

    - **event_id**: イベントID
    - **page**: ページ番号（1から開始）
    - **limit**: 1ページあたりの件数（1-100）
    """
    # イベント存在チェック
    event = events_crud.get_event_by_id(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="イベントが見つかりません")

    participants, total = events_crud.get_event_participants(
        db=db,
        event_id=event_id,
        page=page,
        limit=limit
    )

    total_pages = math.ceil(total / limit) if total > 0 else 0

    from app.schemas.events import EventParticipantDetail

    return EventParticipantListResponse(
        items=[EventParticipantDetail(**p) for p in participants],
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )
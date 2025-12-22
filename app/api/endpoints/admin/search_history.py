from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.models.admins import Admins
from app.crud import search_history_crud
from app.schemas.search import (
    AdminSearchHistoryItem,
    AdminSearchHistoryListResponse,
    SearchHistoryUserInfo,
)
from os import getenv

BASE_URL = getenv("CDN_BASE_URL", "")

router = APIRouter()


@router.get("/", response_model=AdminSearchHistoryListResponse)
def get_search_histories(
    page: int = Query(1, ge=1, description="ページ番号"),
    limit: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    search: Optional[str] = Query(None, description="検索クエリでの検索"),
    user_search: Optional[str] = Query(None, description="ユーザー名/プロフィール名での検索"),
    search_type: Optional[str] = Query(
        None,
        regex="^(all|users|posts|hashtags|creators|paid_posts)$",
        description="検索タイプでのフィルタ"
    ),
    start_date: Optional[str] = Query(None, description="開始日時 (ISO形式)"),
    end_date: Optional[str] = Query(None, description="終了日時 (ISO形式)"),
    sort: str = Query(
        "created_at_desc",
        regex="^(created_at_desc|created_at_asc|query_asc|query_desc)$",
        description="ソート順"
    ),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    全ユーザーの検索履歴を取得（ページネーション対応、フィルタリング対応）
    """
    try:
        # 日付文字列をdatetimeに変換
        start_datetime = None
        end_datetime = None
        if start_date:
            try:
                start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")
        if end_date:
            try:
                end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")

        # 検索履歴を取得
        histories, total = search_history_crud.get_all_search_histories_paginated(
            db=db,
            page=page,
            limit=limit,
            search=search,
            user_search=user_search,
            search_type=search_type,
            start_date=start_datetime,
            end_date=end_datetime,
            sort=sort
        )

        # レスポンス用のアイテムリストを作成
        items = []
        for history in histories:
            # ユーザー情報を取得
            user = history.user
            profile = user.profile if hasattr(user, 'profile') else None
            user_info = SearchHistoryUserInfo(
                id=user.id,
                username=profile.username if profile else None,
                profile_name=user.profile_name,
                avatar_url=f"{BASE_URL}/{profile.avatar_url}" if profile and profile.avatar_url else None,
                email=user.email
            )

            item = AdminSearchHistoryItem(
                id=history.id,
                query=history.query,
                search_type=history.search_type,
                filters=history.filters,
                created_at=history.created_at.isoformat(),
                user=user_info
            )
            items.append(item)

        total_pages = (total + limit - 1) // limit if total > 0 else 1

        return AdminSearchHistoryListResponse(
            items=items,
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch search histories: {str(e)}")


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
import math

from app.deps.auth import get_current_admin_user
from app.db.base import get_db
from app.models.admins import Admins
from app.crud import advertising_agencies_crud
from app.schemas.advertising_agencies import (
    AdvertisingAgencyCreateRequest,
    AdvertisingAgencyUpdateRequest,
    AdvertisingAgencyDetail,
    AdvertisingAgencyListResponse,
    ReferredUserDetail,
    ReferredUserListResponse
)
from app.api.commons.utils import generate_advertising_agency_code

router = APIRouter()


@router.get("", response_model=AdvertisingAgencyListResponse)
def get_advertising_agencies(
    page: int = Query(1, ge=1, description="ページ番号"),
    limit: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    search: Optional[str] = Query(None, description="検索クエリ（会社名・コード）"),
    status: Optional[int] = Query(None, description="ステータスフィルタ（1=有効, 2=停止）"),
    sort: str = Query("created_at_desc", description="name_asc/name_desc/created_at_desc/created_at_asc/user_count_desc/user_count_asc"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    広告会社一覧を取得（管理者用）

    - **page**: ページ番号（1から開始）
    - **limit**: 1ページあたりの件数（1-100）
    - **search**: 検索クエリ（会社名・コード）
    - **status**: ステータスフィルタ（1=有効, 2=停止）
    - **sort**: ソート順
    """
    agencies, total = advertising_agencies_crud.get_advertising_agencies_paginated(
        db=db,
        page=page,
        limit=limit,
        search=search,
        status=status,
        sort=sort
    )

    total_pages = math.ceil(total / limit) if total > 0 else 0

    return AdvertisingAgencyListResponse(
        items=[AdvertisingAgencyDetail(**agency) for agency in agencies],
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )


@router.get("/{agency_id}", response_model=AdvertisingAgencyDetail)
def get_advertising_agency(
    agency_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    広告会社詳細を取得（管理者用）

    - **agency_id**: 広告会社ID
    """
    detail = advertising_agencies_crud.get_advertising_agency_detail(db, agency_id)

    if not detail:
        raise HTTPException(status_code=404, detail="広告会社が見つかりません")

    return AdvertisingAgencyDetail(**detail)


@router.post("", response_model=AdvertisingAgencyDetail)
def create_advertising_agency(
    request: AdvertisingAgencyCreateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    広告会社を作成（管理者用）

    - **name**: 会社名（必須）
    - **status**: ステータス（デフォルト: 1=有効）
    """
    # コードを自動生成（会社名の先頭3文字 + ランダムな6桁の数字）
    import random
    import string
  # 3文字に満たない場合はXで埋める

    # ランダムな6桁のコードを生成（重複チェック付き）
    max_attempts = 100
    for _ in range(max_attempts):
        code = generate_advertising_agency_code()

        # 重複チェック
        existing = advertising_agencies_crud.get_advertising_agency_by_code(db, code)
        if not existing:
            break
    else:
        raise HTTPException(
            status_code=500,
            detail="一意なコードの生成に失敗しました。もう一度お試しください。"
        )

    try:
        agency = advertising_agencies_crud.create_advertising_agency(
            db=db,
            name=request.name,
            code=code,
            status=request.status
        )
        db.commit()
        db.refresh(agency)

        # 詳細を取得して返却
        detail = advertising_agencies_crud.get_advertising_agency_detail(db, agency.id)
        return AdvertisingAgencyDetail(**detail)

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"広告会社作成に失敗しました: {str(e)}"
        )


@router.put("/{agency_id}", response_model=AdvertisingAgencyDetail)
def update_advertising_agency(
    agency_id: UUID,
    request: AdvertisingAgencyUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    広告会社を更新（管理者用）

    - **agency_id**: 広告会社ID
    """
    try:
        agency = advertising_agencies_crud.update_advertising_agency(
            db=db,
            agency_id=agency_id,
            name=request.name,
            status=request.status
        )

        if not agency:
            raise HTTPException(status_code=404, detail="広告会社が見つかりません")

        db.commit()

        # 詳細を取得して返却
        detail = advertising_agencies_crud.get_advertising_agency_detail(db, agency_id)
        return AdvertisingAgencyDetail(**detail)

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"広告会社更新に失敗しました: {str(e)}"
        )


@router.delete("/{agency_id}")
def delete_advertising_agency(
    agency_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    広告会社を削除（管理者用・論理削除）

    - **agency_id**: 広告会社ID
    """
    success = advertising_agencies_crud.delete_advertising_agency(db, agency_id)

    if not success:
        raise HTTPException(status_code=404, detail="広告会社が見つかりません")

    db.commit()

    return {"message": "広告会社を削除しました"}


@router.get("/{agency_id}/users", response_model=ReferredUserListResponse)
def get_referred_users(
    agency_id: UUID,
    page: int = Query(1, ge=1, description="ページ番号"),
    limit: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    search: Optional[str] = Query(None, description="検索クエリ（ユーザー名・メール）"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    広告会社に紐づく紹介ユーザー一覧を取得（管理者用）

    - **agency_id**: 広告会社ID
    - **page**: ページ番号（1から開始）
    - **limit**: 1ページあたりの件数（1-100）
    - **search**: 検索クエリ（ユーザー名・メール）
    """
    # 広告会社の存在確認
    agency = advertising_agencies_crud.get_advertising_agency_by_id(db, agency_id)
    if not agency:
        raise HTTPException(status_code=404, detail="広告会社が見つかりません")

    users, total = advertising_agencies_crud.get_referred_users(
        db=db,
        agency_id=agency_id,
        page=page,
        limit=limit,
        search=search
    )

    total_pages = math.ceil(total / limit) if total > 0 else 0

    return ReferredUserListResponse(
        items=[ReferredUserDetail(**user) for user in users],
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )

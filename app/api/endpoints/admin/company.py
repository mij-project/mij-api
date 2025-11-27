from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
import math

from app.deps.auth import get_current_admin_user
from app.db.base import get_db
from app.models.admins import Admins
from app.crud import companies_crud
from app.schemas.companies import (
    CompanyCreateRequest,
    CompanyUpdateRequest,
    CompanyDetail,
    CompanyListResponse,
    CompanyBasicInfo,
    CompanyUserCreateRequest,
    CompanyUserUpdateRequest,
    CompanyUserDetail,
    CompanyUserListResponse
)

router = APIRouter()


@router.get("", response_model=CompanyListResponse)
def get_companies(
    page: int = Query(1, ge=1, description="ページ番号"),
    limit: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    search: Optional[str] = Query(None, description="検索クエリ（企業名・企業コード）"),
    type: Optional[str] = Query("all", description="primary=1次代理店のみ, secondary=2次代理店のみ, all=すべて"),
    sort: str = Query("created_at_desc", description="name_asc/name_desc/created_at_desc/created_at_asc/user_count_desc/user_count_asc"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    企業一覧を取得（管理者用）

    - **page**: ページ番号（1から開始）
    - **limit**: 1ページあたりの件数（1-100）
    - **search**: 検索クエリ（企業名・企業コード）
    - **type**: フィルター（primary=1次代理店, secondary=2次代理店, all=すべて）
    - **sort**: ソート順
    """
    companies, total = companies_crud.get_companies_paginated(
        db=db,
        page=page,
        limit=limit,
        search=search,
        type=type if type != "all" else None,
        sort=sort
    )

    total_pages = math.ceil(total / limit) if total > 0 else 0

    return CompanyListResponse(
        items=[CompanyDetail(**company) for company in companies],
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )


@router.get("/primary", response_model=list[CompanyBasicInfo])
def get_primary_companies(
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    全ての1次代理店を取得（親企業選択用）

    2次代理店作成時の親企業選択で使用します。
    """
    companies = companies_crud.get_all_primary_companies(db)
    return [CompanyBasicInfo(**company) for company in companies]


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    企業詳細を取得（管理者用）

    - **company_id**: 企業ID
    """
    detail = companies_crud.get_company_detail(db, company_id)

    if not detail:
        raise HTTPException(status_code=404, detail="企業が見つかりません")

    return CompanyDetail(**detail)


@router.post("", response_model=CompanyDetail)
def create_company(
    request: CompanyCreateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    企業を作成（管理者用）

    1次代理店または2次代理店を作成します。
    - 1次代理店の場合: parent_company_id は None
    - 2次代理店の場合: parent_company_id に1次代理店のIDを指定
    """
    # 親企業が存在するか確認（2次代理店の場合）
    if request.parent_company_id:
        parent_company = companies_crud.get_company_by_id(db, request.parent_company_id)
        if not parent_company:
            raise HTTPException(status_code=404, detail="親企業が見つかりません")

        # 親企業が1次代理店であることを確認
        if parent_company.parent_company_id:
            raise HTTPException(
                status_code=400,
                detail="親企業として指定できるのは1次代理店のみです"
            )

    try:
        company = companies_crud.create_company(
            db=db,
            name=request.name,
            parent_company_id=request.parent_company_id
        )
        db.commit()
        db.refresh(company)

        # 詳細を取得して返却
        detail = companies_crud.get_company_detail(db, company.id)
        return CompanyDetail(**detail)

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"企業作成に失敗しました: {str(e)}"
        )


@router.put("/{company_id}", response_model=CompanyDetail)
def update_company(
    company_id: UUID,
    request: CompanyUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    企業を更新（管理者用）

    - **company_id**: 企業ID
    """
    # 親企業が変更される場合、循環参照をチェック
    if request.parent_company_id:
        if request.parent_company_id == company_id:
            raise HTTPException(status_code=400, detail="親企業に自分自身を指定することはできません")

        parent_company = companies_crud.get_company_by_id(db, request.parent_company_id)
        if not parent_company:
            raise HTTPException(status_code=404, detail="親企業が見つかりません")

        # 親企業が1次代理店であることを確認
        if parent_company.parent_company_id:
            raise HTTPException(
                status_code=400,
                detail="親企業として指定できるのは1次代理店のみです"
            )

    company = companies_crud.update_company(
        db=db,
        company_id=company_id,
        name=request.name,
        parent_company_id=request.parent_company_id
    )

    if not company:
        raise HTTPException(status_code=404, detail="企業が見つかりません")

    db.commit()

    # 詳細を取得して返却
    detail = companies_crud.get_company_detail(db, company_id)
    return CompanyDetail(**detail)


@router.delete("/{company_id}")
def delete_company(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    企業を削除（管理者用・論理削除）

    - **company_id**: 企業ID

    注意:
    - 紹介クリエイターが存在する企業は削除できません
    - 子企業が存在する1次代理店は削除できません
    """
    success = companies_crud.delete_company(db, company_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="削除に失敗しました。紹介クリエイターまたは子企業が存在する可能性があります。"
        )

    db.commit()

    return {
        "success": True,
        "message": "企業を削除しました"
    }


# ====================
# CompanyUsers エンドポイント
# ====================

@router.get("/{company_id}/users", response_model=CompanyUserListResponse)
def get_company_users(
    company_id: UUID,
    page: int = Query(1, ge=1, description="ページ番号"),
    limit: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    企業に紐づくクリエイター一覧を取得（管理者用）

    - **company_id**: 企業ID
    - **page**: ページ番号
    - **limit**: 1ページあたりの件数
    """
    try:
        # 企業が存在するか確認
        company = companies_crud.get_company_by_id(db, company_id)
        if not company:
            raise HTTPException(status_code=404, detail="企業が見つかりません")

        users, total = companies_crud.get_company_users(
            db=db,
            company_id=company_id,
            page=page,
            limit=limit
        )

        total_pages = math.ceil(total / limit) if total > 0 else 0


        return CompanyUserListResponse(
            items=[CompanyUserDetail(**user) for user in users],
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"クリエイター追加に失敗しました: {str(e)}")



@router.post("/{company_id}/users", response_model=CompanyUserDetail)
def add_company_user(
    company_id: UUID,
    request: CompanyUserCreateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    企業にクリエイターを追加（管理者用）

    - **company_id**: 企業ID
    - **user_id**: ユーザー（クリエイター）ID
    - **company_fee_percent**: 企業への支払い率（デフォルト3%）
    """
    # 企業が存在するか確認
    company = companies_crud.get_company_by_id(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="企業が見つかりません")

    try:
        company_user = companies_crud.add_company_user(
            db=db,
            company_id=company_id,
            user_id=request.user_id,
            company_fee_percent=request.company_fee_percent,
            is_referrer=request.is_referrer
        )
        db.commit()
        db.refresh(company_user)

        # 詳細を取得して返却
        users, _ = companies_crud.get_company_users(db, company_id, page=1, limit=1000)
        user_detail = next((u for u in users if u["user_id"] == str(request.user_id)), None)

        if not user_detail:
            raise HTTPException(status_code=404, detail="追加したユーザーが見つかりません")

        return CompanyUserDetail(**user_detail)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"クリエイター追加に失敗しました: {str(e)}"
        )


@router.put("/{company_id}/users/{user_id}", response_model=CompanyUserDetail)
def update_company_user_fee(
    company_id: UUID,
    user_id: UUID,
    request: CompanyUserUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    企業クリエイターの支払い率を更新（管理者用）

    - **company_id**: 企業ID
    - **user_id**: ユーザーID
    - **company_fee_percent**: 新しい支払い率（0-100%）
    """
    company_user = companies_crud.update_company_user_fee(
        db=db,
        company_id=company_id,
        user_id=user_id,
        company_fee_percent=request.company_fee_percent
    )

    if not company_user:
        raise HTTPException(status_code=404, detail="企業ユーザーが見つかりません")

    db.commit()

    # 詳細を取得して返却
    users, _ = companies_crud.get_company_users(db, company_id, page=1, limit=1000)
    user_detail = next((u for u in users if u["user_id"] == str(user_id)), None)

    if not user_detail:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    return CompanyUserDetail(**user_detail)


@router.delete("/{company_id}/users/{user_id}")
def remove_company_user(
    company_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    企業からクリエイターを削除（管理者用・論理削除）

    - **company_id**: 企業ID
    - **user_id**: ユーザーID
    """
    success = companies_crud.remove_company_user(
        db=db,
        company_id=company_id,
        user_id=user_id
    )

    if not success:
        raise HTTPException(
            status_code=404,
            detail="企業ユーザーが見つかりません"
        )

    db.commit()

    return {
        "success": True,
        "message": "クリエイターを削除しました"
    }

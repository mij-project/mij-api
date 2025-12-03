from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
import math

from app.deps.auth import get_current_admin_user
from app.db.base import get_db
from app.models.admins import Admins
from app.crud import banners_crud
from app.schemas.banners import (
    BannerCreateRequest,
    BannerUpdateRequest,
    BannerReorderRequest,
    BannerDetail,
    BannerListResponse
)
from app.constants.enums import BannerType, BannerStatus, BannerImageSource
from app.services.s3.banner_upload import upload_banner_image, delete_banner_image
from datetime import datetime

router = APIRouter()


@router.get("", response_model=BannerListResponse)
def get_banners(
    page: int = Query(1, ge=1, description="ページ番号"),
    limit: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    status: Optional[int] = Query(None, description="0=無効, 1=有効, 2=下書き"),
    search: Optional[str] = Query(None, description="検索クエリ（タイトル）"),
    sort: str = Query("display_order_asc", description="display_order_asc/display_order_desc/created_at_desc/created_at_asc/start_at_desc/start_at_asc"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    バナー一覧を取得（管理者用）

    - **page**: ページ番号（1から開始）
    - **limit**: 1ページあたりの件数（1-100）
    - **status**: ステータスフィルタ（0=無効, 1=有効, 2=下書き）
    - **search**: 検索クエリ（タイトル）
    - **sort**: ソート順
    """
    banners, total = banners_crud.get_banners_paginated(
        db=db,
        page=page,
        limit=limit,
        status=status,
        search=search,
        sort=sort
    )

    total_pages = math.ceil(total / limit) if total > 0 else 0

    return BannerListResponse(
        items=[BannerDetail(**banner) for banner in banners],
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )


@router.get("/{banner_id}", response_model=BannerDetail)
def get_banner(
    banner_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    バナー詳細を取得（管理者用）

    - **banner_id**: バナーID
    """
    detail = banners_crud.get_banner_detail(db, banner_id)

    if not detail:
        raise HTTPException(status_code=404, detail="バナーが見つかりません")

    return BannerDetail(**detail)


@router.post("", response_model=BannerDetail)
async def create_banner(
    type: int = Form(..., description="1=クリエイター, 2=イベント"),
    title: str = Form(..., description="バナータイトル"),
    alt_text: str = Form(..., description="画像の代替テキスト"),
    cta_label: str = Form("", description="CTAラベル"),
    creator_id: Optional[str] = Form(None, description="クリエイターID"),
    external_url: Optional[str] = Form(None, description="外部URL"),
    status: int = Form(2, description="0=無効, 1=有効, 2=下書き"),
    start_at: Optional[str] = Form(None, description="表示開始日時"),
    end_at: Optional[str] = Form(None, description="表示終了日時"),
    display_order: int = Form(100, description="表示順序"),
    priority: int = Form(0, description="優先度"),
    image: Optional[UploadFile] = File(None, description="バナー画像"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    バナーを作成（管理者用）

    画像ファイルと共に、バナー情報をアップロードします。
    """
    # バリデーション
    if type == BannerType.CREATOR and not creator_id:
        raise HTTPException(status_code=400, detail="type=1の場合、creator_idは必須です")
    if type == BannerType.SPECIAL_EVENT and not external_url:
        raise HTTPException(status_code=400, detail="type=2の場合、external_urlは必須です")

    # 画像をS3にアップロード
    image_key = None
    if image:
        image_key, image_url = await upload_banner_image(image)
        image_source = BannerImageSource.ADMIN_POST
    else:
        image_source = BannerImageSource.USER_PROFILE

    # 日時文字列をdatetimeに変換
    parsed_start_at = None
    parsed_end_at = None

    if start_at:
        try:
            # ISO 8601形式の日時文字列をパース（例: "2025-12-03T10:00"）
            parsed_start_at = datetime.fromisoformat(start_at.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="start_atの日時フォーマットが不正です")

    if end_at:
        try:
            parsed_end_at = datetime.fromisoformat(end_at.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="end_atの日時フォーマットが不正です")

    # デフォルト値を設定（日時が指定されていない場合）
    # start_atがNoneの場合は現在時刻、end_atがNoneの場合は30日後
    if not parsed_start_at:
        parsed_start_at = datetime.now()
    if not parsed_end_at:
        from datetime import timedelta
        parsed_end_at = datetime.now() + timedelta(days=30)

    try:
        insert_form_data = {
            "type": type,
            "title": title,
            "image_key": image_key,
            "alt_text": alt_text,
            "cta_label": cta_label,
            "creator_id": UUID(creator_id) if creator_id else None,
            "external_url": external_url or "",
            "status": status,
            "start_at": parsed_start_at,
            "end_at": parsed_end_at,
            "display_order": display_order,
            "priority": priority,
            "image_source": image_source
        }

        banner = banners_crud.create_banner(db, insert_form_data)
        db.commit()
        db.refresh(banner)

        # 詳細を取得して返却
        detail = banners_crud.get_banner_detail(db, banner.id)
        return BannerDetail(**detail)

    except Exception as e:
        db.rollback()
        # エラー時は画像を削除
        if image_key:
            delete_banner_image(image_key)
        raise HTTPException(
            status_code=500,
            detail=f"バナー作成に失敗しました: {str(e)}"
        )


@router.put("/{banner_id}", response_model=BannerDetail)
def update_banner(
    banner_id: UUID,
    request: BannerUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    バナーを更新（管理者用）

    - **banner_id**: バナーID
    """
    # バリデーション
    if request.type == BannerType.CREATOR and not request.creator_id:
        raise HTTPException(status_code=400, detail="type=1の場合、creator_idは必須です")
    if request.type == BannerType.SPECIAL_EVENT and not request.external_url:
        raise HTTPException(status_code=400, detail="type=2の場合、external_urlは必須です")

    banner = banners_crud.update_banner(
        db=db,
        banner_id=banner_id,
        type=request.type,
        title=request.title,
        alt_text=request.alt_text,
        cta_label=request.cta_label,
        creator_id=request.creator_id,
        external_url=request.external_url,
        status=request.status,
        start_at=request.start_at,
        end_at=request.end_at,
        display_order=request.display_order,
        priority=request.priority
    )

    if not banner:
        raise HTTPException(status_code=404, detail="バナーが見つかりません")

    db.commit()

    # 詳細を取得して返却
    detail = banners_crud.get_banner_detail(db, banner_id)
    return BannerDetail(**detail)


@router.put("/{banner_id}/image", response_model=BannerDetail)
async def update_banner_image(
    banner_id: UUID,
    image: UploadFile = File(..., description="新しいバナー画像"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    バナー画像を更新（管理者用）

    - **banner_id**: バナーID
    - **image**: 新しい画像ファイル
    """
    # 既存バナーを取得
    existing_banner = banners_crud.get_banner_by_id(db, banner_id)
    if not existing_banner:
        raise HTTPException(status_code=404, detail="バナーが見つかりません")

    old_image_key = existing_banner.image_key

    # 新しい画像をS3にアップロード
    new_image_key, new_image_url = await upload_banner_image(image)

    try:
        # バナー画像を更新
        banner = banners_crud.update_banner_image(
            db=db,
            banner_id=banner_id,
            image_key=new_image_key,
            image_source=BannerImageSource.ADMIN_POST
        )

        if not banner:
            raise HTTPException(status_code=404, detail="バナーが見つかりません")

        db.commit()

        # 古い画像を削除
        delete_banner_image(old_image_key)

        # 詳細を取得して返却
        detail = banners_crud.get_banner_detail(db, banner_id)
        return BannerDetail(**detail)

    except Exception as e:
        db.rollback()
        # エラー時は新しい画像を削除
        delete_banner_image(new_image_key)
        raise HTTPException(
            status_code=500,
            detail=f"画像更新に失敗しました: {str(e)}"
        )


@router.delete("/{banner_id}")
def delete_banner(
    banner_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    バナーを削除（管理者用）

    - **banner_id**: バナーID
    """
    # 既存バナーを取得
    existing_banner = banners_crud.get_banner_by_id(db, banner_id)
    if not existing_banner:
        raise HTTPException(status_code=404, detail="バナーが見つかりません")

    image_key = existing_banner.image_key

    success = banners_crud.delete_banner(db, banner_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="削除に失敗しました"
        )

    db.commit()

    # S3から画像を削除
    delete_banner_image(image_key)

    return {
        "success": True,
        "message": "バナーを削除しました"
    }


@router.patch("/reorder")
def reorder_banners(
    request: BannerReorderRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    バナーの表示順序を一括更新（管理者用）

    - **banner_ids**: バナーIDリスト（並び順）
    """
    success = banners_crud.reorder_banners(db, request.banner_ids)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="並び替えに失敗しました"
        )

    db.commit()

    return {
        "success": True,
        "message": "バナーの表示順序を更新しました"
    }

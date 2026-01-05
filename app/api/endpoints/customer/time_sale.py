import math
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Any

from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.crud.time_sale_crud import (
    get_price_time_sale_by_id,
    update_price_time_sale_by_id,
)
from app.crud.post_crud import get_post_by_id
from app.schemas.post_plan_timesale import PlanTimeSaleResponse, UpdateRequest
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()


@router.get("/timesale-edit/{time_sale_id}")
async def get_post_price_timesale_edit_by_id(
    time_sale_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    タイムセールIDから投稿の価格タイムセール編集ページ初期化用のデータを取得
    """
    try:
        # タイムセール情報を取得
        row = get_price_time_sale_by_id(db, time_sale_id)
        if not row:
            raise HTTPException(
                status_code=404, detail="タイムセール情報が見つかりません"
            )

        time_sale_data = row
        post_id = time_sale_data.TimeSale.post_id

        # 投稿を取得
        post = get_post_by_id(db, post_id)
        if not post:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        # 投稿の所有者確認（get_post_by_idは辞書を返すため、キーでアクセス）
        if str(post.get("user_id")) != str(current_user.id):
            raise HTTPException(
                status_code=403, detail="この投稿を編集する権限がありません"
            )

        # 投稿情報を辞書形式で返す（get_post_by_idは辞書を返すため、キーでアクセス）
        post_detail = {
            "id": post.get("id", ""),
            "title": post.get(
                "description", ""
            ),  # get_post_by_idはtitleではなくdescriptionを返す
            "price": post.get("single_price", 0)
            or 0,  # single_priceは既に価格の値（整数）を返す
        }

        # タイムセール情報をResponse形式に変換
        time_sale = PlanTimeSaleResponse(
            id=str(time_sale_data.TimeSale.id),
            post_id=str(time_sale_data.TimeSale.post_id)
            if time_sale_data.TimeSale.post_id
            else None,
            plan_id=str(time_sale_data.TimeSale.plan_id)
            if time_sale_data.TimeSale.plan_id
            else None,
            price_id=str(time_sale_data.TimeSale.price_id)
            if time_sale_data.TimeSale.price_id
            else None,
            start_date=time_sale_data.TimeSale.start_date
            if time_sale_data.TimeSale.start_date
            else None,
            end_date=time_sale_data.TimeSale.end_date
            if time_sale_data.TimeSale.end_date
            else None,
            sale_percentage=time_sale_data.TimeSale.sale_percentage,
            max_purchase_count=time_sale_data.TimeSale.max_purchase_count
            if time_sale_data.TimeSale.max_purchase_count
            else None,
            purchase_count=time_sale_data.purchase_count,
            is_active=time_sale_data.is_active,
            is_expired=time_sale_data.is_expired,
            created_at=time_sale_data.TimeSale.created_at
            if time_sale_data.TimeSale.created_at
            else None,
        )

        # 投稿情報とタイムセール情報を返す
        return {
            "plan": post_detail,  # "plan"キーを使用して統一（フロントエンドで異なる用途のため）
            "time_sale": time_sale,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("タイムセール編集データ取得エラーが発生しました")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update-time-sale/{time_sale_id}")
async def update_price_time_sale(
    time_sale_id: str,
    payload: UpdateRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """価格時間販売情報を更新する"""
    time_sale = update_price_time_sale_by_id(db, time_sale_id, payload, current_user.id)
    if not time_sale:
        raise HTTPException(status_code=500, detail="Can not update price time sale")
    return {"message": "ok"}

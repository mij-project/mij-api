from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.schemas.order import OrderCreateRequest
from app.constants.enums import ItemType
from uuid import UUID
from app.crud.price_crud import get_price_by_id
from app.crud.plan_crud import get_plan_by_id
from app.crud.orders import insert_order
from app.crud.order_items import insert_order_item
from app.constants.enums import OrderStatus
import os
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()

@router.post("/create")
def create_order(
    order_request: OrderCreateRequest,
    # user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    注文を作成
    """
    try:
        # TODO: ユーザーIDを取得
        user_id = "276081e3-6647-48b2-a257-170c9c4a6b0e"
        # 金額を取得
        result, amount = _get_item_info(db, order_request.item_type, order_request.price_id, order_request.plan_id)
        
        # 注文を作成
        order_create = {
            "user_id": user_id,
            "total_amount": amount,
            "currency": "JPY",
            "status": OrderStatus.PENDING,
        }
        order = insert_order(db, order_create)
        
        # アイテムを作成
        order_item_create = {
            "order_id": order.id,
            "item_type": order_request.item_type,
            "post_id": result.post_id if order_request.item_type == ItemType.POST else None,
            "plan_id": result.id if order_request.item_type == ItemType.PLAN else None,
            "amount": amount,
            "creator_user_id": user_id,
        }
        order_item = insert_order_item(db, order_item_create)


        db.commit()
        db.refresh(order)
        db.refresh(order_item)

        return {
            "order_id": order.id,
            "order_item_id": order_item.id,
            "amount": amount,
        }
    except Exception as e:
        db.rollback()
        logger.error("注作成エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

def _get_item_info(db: Session, item_type: int, price_id: UUID | None, plan_id: UUID | None) -> int:
    """
    金額を取得
    """
    amount = 0
    if item_type == ItemType.POST:
        price = get_price_by_id(db, price_id)
        amount = price.price
        if not price:
            raise HTTPException(status_code=404, detail="Price not found")
        return price, amount
    elif item_type == ItemType.PLAN:
        plan = get_plan_by_id(db, plan_id)
        amount = plan.price
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        return plan, plan.price
    else:
        raise HTTPException(status_code=400, detail="Invalid item type")

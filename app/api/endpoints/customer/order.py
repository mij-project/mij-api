from fastapi import APIRouter, Depends, HTTPException
from pydantic.types import T
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.schemas.order import OrderCreateRequest
from app.constants.enums import ItemType
from uuid import UUID
from app.crud.price_crud import get_price_by_id
from app.crud.plan_crud import get_plan_by_id
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
       return True
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

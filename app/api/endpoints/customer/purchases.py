from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.schemas.purchases import (
    PurchaseCreateRequest,
    SalesDataResponse,
    SalesTransactionsListResponse
)
from app.crud.purchases_crud import (
    create_purchase,
    get_sales_data_by_creator_id,
    get_sales_transactions_by_creator_id
)
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()

@router.post("/create")
async def create_purchase_endpoint(
    purchase_create: PurchaseCreateRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    購入情報を作成

    Args:
        purchase_create (PurchaseCreateRequest): 購入情報
        user (User): ユーザー
        db (Session): データベースセッション

    Raises:
        HTTPException: エラーが発生した場合

    Returns:
        dict: 購入情報を作成しました
    """
    try:
        purchase_data = {
            "user_id": user.id,
            "plan_id": purchase_create.plan_id,
        }
        # post_idが指定されている場合のみ追加
        if purchase_create.post_id:
            purchase_data["post_id"] = purchase_create.post_id

        purchase = create_purchase(db, purchase_data)
        db.commit()
        db.refresh(purchase)

        return {
            "message": "購入情報を作成しました",
            "purchase_id": purchase.id
        }
    except Exception as e:
        db.rollback()
        logger.error("購入情報処理に失敗しました", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sales", response_model=SalesDataResponse)
async def get_sales_data(
    period: str = "today",
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    クリエイターの売上データを取得

    Args:
        period: 期間（"today", "monthly", "last_5_days"）デフォルトは"today"

    Returns:
        SalesDataResponse: 売上サマリーデータ
    """
    try:
        sales_data = get_sales_data_by_creator_id(db, user.id, period)
        return SalesDataResponse(**sales_data)
    except Exception as e:
        logger.error("売上データ取得に失敗しました", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/transactions", response_model=SalesTransactionsListResponse)
async def get_sales_transactions(
    limit: int = 50,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    クリエイターの売上履歴を取得

    Args:
        limit: 取得件数（デフォルト50件）

    Returns:
        SalesTransactionsListResponse: 売上履歴リスト
    """
    try:
        transactions = get_sales_transactions_by_creator_id(db, user.id, limit)
        return SalesTransactionsListResponse(transactions=transactions)
    except Exception as e:
        logger.error("売上履歴取得に失敗しました", e)
        raise HTTPException(status_code=500, detail=str(e))

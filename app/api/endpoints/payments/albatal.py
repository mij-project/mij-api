from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.schemas.albatal import AlbatalSessionRequest, AlbatalSessionResponse, PurchaseType
from app.deps.auth import get_current_user_optional
from app.models.user import Users
from app.core.logger import Logger
from app.crud import providers_crud, payment_transactions_crud, user_providers_crud
from app.constants.number import AlbatalRecurringInterval
from app.constants.limits import AlbatalRecurringMaxCount
from app.api.commons.utils import generate_sendid
from app.constants.enums import PaymentTransactionType, TransactionType
from app.constants.number import PaymentPlanPlatformFeePercent
from app.crud.time_sale_crud import get_active_plan_timesale, get_active_price_timesale
from app.crud.plan_crud import get_active_plan_timesale
from app.models.user_providers import UserProviders
from app.models.prices import Prices
from app.models.plans import Plans
from app.models.payment_transactions import PaymentTransactions
from uuid import UUID
import math
import os
import httpx
import json

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://mijfans.jp")
ENV = os.getenv("ENV", "dev")
ALBATAL_API_KEY = os.getenv("ALBATAL_PAY_API_KEY", "")
ALBATAL_API_WPF_URL = os.getenv("ALBATAL_API_WPF_URL", "https://staging.console.albatal.ltd/api/wpf/create")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", os.getenv("API_BASE_URL", "https://api.mijfans.jp"))
logger = Logger.get_logger()

router = APIRouter()

@router.post("/session", response_model=AlbatalSessionResponse)
async def create_albatal_session(
    request: AlbatalSessionRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user_optional)
):
    """
    Albatalセッション発行（WPF決済）

    単発決済（sale3d）のWPF URLを取得してフロントエンドに返す
    """
    try:
        # Albatalプロバイダー取得
        albatal_provider = providers_crud.get_provider_by_code(db, "albatal")
        if not albatal_provider:
            raise HTTPException(status_code=500, detail="Albatal provider not found in database")

        # user_providersテーブル確認
        user_provider = user_providers_crud.get_user_provider(
            db=db,
            user_id=current_user.id,
            provider_id=albatal_provider.id
        )

        is_first_payment = user_provider is None or user_provider.sendid is None

        # 決済金額計算
        money, order_id, transaction_type = _set_money(request, db)
        transaction_id = generate_sendid()

        # 決済トランザクション作成
        transaction = _create_transaction(
            db=db,
            current_user=current_user,
            provider_id=albatal_provider.id,
            transaction_type=transaction_type,
            session_id=transaction_id,
            order_id=order_id,
        )

        notification_url = f"{WEBHOOK_BASE_URL}/webhook/albatal/payment"
        request_url = ALBATAL_API_WPF_URL

        wpf_payload = {
            "transaction_id": str(transaction.id),
            "usage": "決済",
            "amount": int(money),
            "currency": "JPY",
            "description": "決済画面になります。",
            "consumer_id": str(current_user.id),
            "consumer_email": request.provider_email,
            "notification_url": notification_url,
            "remember_card": True,
            "return_success_url": f"{FRONTEND_URL}{request.return_url}",
            "return_failure_url": f"{FRONTEND_URL}{request.return_url}",
            "return_cancel_url": f"{FRONTEND_URL}{request.return_url}",
            "return_pending_url": f"{FRONTEND_URL}{request.return_url}",
            "transaction_type_name": "sale3d",
        }

        if request.purchase_type == PurchaseType.SUBSCRIPTION:
            wpf_payload["transaction_type_name"] = "recurring_sale3d"
            wpf_payload["recurring_type"] = "managed"
            wpf_payload["managed_recurring"] = {
                "mode": "automatic",
                "interval": "days",
                "period": AlbatalRecurringInterval.PERIOD_DAYS,
                "amount": int(money),
                "max_count": AlbatalRecurringMaxCount.MAX_COUNT,
            }

        # Albatal APIへリクエスト
        async with httpx.AsyncClient() as client:
            response = await client.post(
                request_url,
                json=wpf_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {ALBATAL_API_KEY}",
                },
                timeout=30.0,
            )

        if response.status_code not in [200, 201]:
            logger.error(f"Albatal API error: {response.status_code} {response.text}")
            raise HTTPException(status_code=500, detail=f"Albatal API request failed: {response.status_code}")

        albatal_response = response.json()
        payment_url = albatal_response.get("redirect_url") or albatal_response.get("url") or albatal_response.get("payment_url") or albatal_response.get("wpf_url")

        if not payment_url:
            logger.error(f"No payment URL in Albatal response: {albatal_response}")
            raise HTTPException(status_code=500, detail="Failed to get payment URL from Albatal")

        if is_first_payment:
            user_providers_crud.create_albatal_user_provider(
                db=db,
                user_id=current_user.id,
                provider_id=albatal_provider.id,
                provider_email=request.provider_email,
                is_valid=False,
            )

        transaction.session_id = albatal_response.get("unique_id")
        db.commit()
        db.refresh(transaction)

        return AlbatalSessionResponse(
            transaction_id=transaction.id,
            success_url=f"{FRONTEND_URL}{request.return_url}",
            failure_url=f"{FRONTEND_URL}{request.return_url}",
            payment_url=payment_url,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Albatal session creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _set_money(request: AlbatalSessionRequest, db: Session) -> tuple[int, str, int]:
    """決済金額設定"""
    try:
         # 決済金額計算
        if request.purchase_type == PurchaseType.SINGLE:
            if not request.price_id:
                raise HTTPException(status_code=400, detail="Price ID is required for single purchase")
            # 対象のレコードに対してロックをかける（select_for_update）
            price = db.query(Prices).filter(Prices.id == request.price_id).with_for_update().first()
            if not price:
                raise HTTPException(status_code=404, detail="Price not found")
            original_price = price.price
            # Check TimeSale Information
            if request.is_time_sale:
                price_time_sale_info = get_active_price_timesale(db, price.post_id, price.id)
                if price_time_sale_info and price_time_sale_info["is_active"] and (not price_time_sale_info["is_expired"]):
                    original_price = math.ceil(original_price - original_price * price_time_sale_info["sale_percentage"] / 100)
                elif price_time_sale_info and price_time_sale_info["is_active"] and price_time_sale_info["is_expired"]:
                    raise HTTPException(status_code=400, detail="タイムセール期限過ぎました、または限定人数を超えました。申し訳ございませんが、再度リロードして、購入してください。")
                else:
                    raise HTTPException(status_code=400, detail="タイムセール期限過ぎました、または限定人数を超えました。申し訳ございませんが、再度リロードして、購入してください。")

            money = math.floor(original_price * (1 + PaymentPlanPlatformFeePercent.DEFAULT / 100))
            order_id = request.price_id
            transaction_type = PaymentTransactionType.SINGLE
        else:  # subscription
            if not request.plan_id:
                raise HTTPException(status_code=400, detail="Plan ID is required for subscription")

            # 対象のレコードに対してロックをかける（select_for_update）
            plan = db.query(Plans).filter(Plans.id == request.plan_id).with_for_update().first()
            if not plan:
                raise HTTPException(status_code=404, detail="Plan not found")
            # 元の価格を保持し、手数料込みの金額を計算（DBの値は更新しない）
            original_price = plan.price
            # Check TimeSale Information
            if request.is_time_sale:
                plan_time_sale_info = get_active_plan_timesale(db, plan.id)
                if plan_time_sale_info and plan_time_sale_info["is_active"] and (not plan_time_sale_info["is_expired"]):
                    original_price = math.ceil(original_price - original_price * plan_time_sale_info["sale_percentage"] / 100)
                elif plan_time_sale_info and plan_time_sale_info["is_active"] and plan_time_sale_info["is_expired"]:
                    raise HTTPException(status_code=400, detail="タイムセール期限過ぎました、または限定人数を超えました。申し訳ございませんが、再度リロードして、購入してください。")
                else:
                    raise HTTPException(status_code=400, detail="タイムセール期限過ぎました、または限定人数を超えました。申し訳ございませんが、再度リロードして、購入してください。")
            money = math.floor(original_price * (1 + PaymentPlanPlatformFeePercent.DEFAULT / 100))
            order_id = request.plan_id
            transaction_type = PaymentTransactionType.SUBSCRIPTION

        return money, order_id, transaction_type
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CREDIX set money failed: {e}")
        raise HTTPException(status_code=500, detail=f"CREDIX set money failed: {str(e)}")


def _create_transaction(
    db: Session,
    current_user: Users,
    provider_id: UUID,
    transaction_type: int,
    session_id: str,
    order_id: str,
):
    """決済トランザクション作成"""
    try:
        return payment_transactions_crud.create_payment_transaction(
            db=db,
            user_id=current_user.id,
            provider_id=provider_id,
            transaction_type=transaction_type,
            session_id=session_id,
            order_id=order_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Albatal create transaction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Albatal create transaction failed: {str(e)}")

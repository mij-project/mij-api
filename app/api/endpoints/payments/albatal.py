from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.schemas.albatal import AlbatalSessionRequest, AlbatalSessionResponse, AlbatalChipPaymentRequest, PurchaseType
from app.deps.auth import get_current_user_optional
from app.models.user import Users
from app.core.logger import Logger
from app.crud import (
    providers_crud, 
    payment_transactions_crud, 
    user_providers_crud, 
    user_crud, 
    profile_crud,
    conversations_crud
)
from app.constants.number import (
    AlbatalRecurringInterval,
    PaymentPlanPlatformFeePercent,
    ChipPaymentFeePercent,
)
from app.constants.limits import AlbatalRecurringMaxCount
from app.api.commons.utils import generate_sendid
from app.constants.enums import PaymentTransactionType
from app.crud.time_sale_crud import get_active_plan_timesale, get_active_price_timesale
from app.models.prices import Prices
from app.models.plans import Plans
from app.constants.enums import ConversationMessageStatus
from uuid import UUID
from typing import Any
import math
import os
import httpx

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://mijfans.jp")
ENV = os.getenv("ENV", "dev")
ALBATAL_API_KEY = os.getenv("ALBATAL_PAY_API_KEY", "")
ALBATAL_API_WPF_URL = os.getenv("ALBATAL_API_WPF_URL", "https://staging.console.albatal.ltd/api/wpf/create")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", os.getenv("API_BASE_URL", "https://api.mijfans.jp"))
_TIMESALE_EXPIRED_MESSAGE = (
    "タイムセール期限過ぎました、または限定人数を超えました。"
    "申し訳ございませんが、再度リロードして、購入してください。"
)
logger = Logger.get_logger()

router = APIRouter()


def _get_albatal_provider(db: Session):
    """Albatalプロバイダーを取得"""
    albatal_provider = providers_crud.get_provider_by_code(db, "albatal")
    if not albatal_provider:
        raise HTTPException(status_code=500, detail="Albatal provider not found in database")
    return albatal_provider


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
        albatal_provider = _get_albatal_provider(db)

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
        
        # WPFペイロード作成
        wpf_payload = _build_wpf_payload(
            transaction_id=transaction.id,
            amount=money,
            consumer_id=current_user.id,
            consumer_email=request.provider_email,
            notification_url=notification_url,
            return_url=request.return_url,
            purchase_type=request.purchase_type,
        )

        # Albatal APIへリクエスト
        albatal_response = await _call_albatal_api(wpf_payload)
        payment_url = _extract_payment_url(albatal_response)

        transaction.session_id = albatal_response.get("unique_id")
        db.commit()
        db.refresh(transaction)

        return _build_session_response(
            transaction_id=transaction.id,
            return_url=request.return_url,
            payment_url=payment_url,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Albatal session creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/session/chip", response_model=AlbatalSessionResponse)
async def create_albatal_chip_session(
    request: AlbatalChipPaymentRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user_optional)
):
    """
    Albatal投げ銭セッション発行（WPF決済）
    """
    try:
        # Albatalプロバイダー取得
        albatal_provider = _get_albatal_provider(db)

        # クリエイター情報を取得
        creator_user = user_crud.get_user_by_id(db, request.recipient_user_id)
        if not creator_user:
            raise HTTPException(status_code=404, detail="Creator user not found")

        # Profileテーブルからusernameを取得
        creator_profile = profile_crud.get_profile_by_user_id(db, UUID(request.recipient_user_id))
        if not creator_profile or not creator_profile.username:
            raise HTTPException(status_code=404, detail="Creator profile or username not found")

        # 決済金額計算（手数料込み）
        money = math.floor(request.amount * (1 + ChipPaymentFeePercent.DEFAULT / 100))

        # メッセージが指定されている場合、先に会話を作成してメッセージを追加
        chip_message_id = None

        try:
            # DM会話を取得または作成
            conversation = conversations_crud.get_or_create_dm_conversation(
                db=db,
                user_id_1=current_user.id,
                user_id_2=UUID(request.recipient_user_id),
            )
            
            # チップメッセージを作成（タイムスタンプは決済完了時に設定）
            if request.message and request.message.strip():
                chip_monner_message = f"{current_user.profile_name}さんが{request.amount}円のチップを送りました！\n\n【メッセージ】\n{request.message}"
            else:
                chip_monner_message = f"{current_user.profile_name}さんが{request.amount}円のチップを送りました！"

            chip_message = conversations_crud.create_chip_message(
                db=db,
                conversation_id=conversation.id,
                sender_user_id=current_user.id,
                body_text=chip_monner_message,
                status=ConversationMessageStatus.INACTIVE,
            )
            chip_message_id = str(chip_message.id)
            logger.info(f"Chip payment message created: {chip_message_id}")

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create chip payment message: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"メッセージの作成に失敗しました: {str(e)}"
            )

        notification_url = f"{WEBHOOK_BASE_URL}/webhook/albatal/payment/chip"

        # order_idを決定（ recipient_user_id + "_" + chip_message_id）
        order_id = f"{request.recipient_user_id}_{chip_message_id}"

        # 決済トランザクション作成（仮のセッションID生成）
        temp_session_id = generate_sendid(length=20)
        transaction = _create_transaction(
            db=db,
            current_user=current_user,
            provider_id=albatal_provider.id,
            transaction_type=PaymentTransactionType.CHIP,
            session_id=temp_session_id,
            order_id=order_id,
        )

        # WPFペイロード作成
        wpf_payload = _build_wpf_payload(
            transaction_id=transaction.id,
            amount=money,
            consumer_id=current_user.id,
            consumer_email=request.provider_email,
            notification_url=notification_url,
            return_url=request.return_url,
            purchase_type=None,  # チップ決済は単発決済
        )

        # Albatal APIへリクエスト
        albatal_response = await _call_albatal_api(wpf_payload)
        payment_url = _extract_payment_url(albatal_response)

        transaction.session_id = albatal_response.get("unique_id")
        db.commit()
        db.refresh(transaction)

        return _build_session_response(
            transaction_id=transaction.id,
            return_url=request.return_url,
            payment_url=payment_url,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Albatal chip session creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _build_wpf_payload(
    transaction_id: UUID,
    amount: int,
    consumer_id: UUID,
    consumer_email: str | None,
    notification_url: str,
    return_url: str | None,
    purchase_type: PurchaseType | None = None,
) -> dict:
    """
    Albatal WPFペイロードを作成
    
    Args:
        transaction_id: トランザクションID
        amount: 決済金額
        consumer_id: コンシューマーID
        consumer_email: コンシューマーメールアドレス
        notification_url: 通知URL
        return_url: リターンURL
        purchase_type: 購入タイプ（サブスクリプションの場合のみ設定）
    
    Returns:
        WPFペイロード辞書
    """
    base_url = _build_return_url(return_url, transaction_id)
    return_cancel_url = f"{FRONTEND_URL}{return_url}" if return_url else FRONTEND_URL
    
    payload = {
        "transaction_id": str(transaction_id),
        "usage": "決済",
        "amount": int(amount),
        "currency": "JPY",
        "description": "決済画面になります。",
        "consumer_id": str(consumer_id),
        "consumer_email": consumer_email,
        "notification_url": notification_url,
        "remember_card": True,
        "return_success_url": base_url,
        "return_failure_url": base_url,
        "return_cancel_url": return_cancel_url,
        "return_pending_url": base_url,
        "transaction_type_name": "sale3d",
    }
    
    # サブスクリプションの場合は定期決済設定を追加
    if purchase_type == PurchaseType.SUBSCRIPTION:
        payload["transaction_type_name"] = "recurring_sale3d"
        payload["recurring_type"] = "managed"
        payload["managed_recurring"] = {
            "mode": "automatic",
            "interval": "days",
            "period": AlbatalRecurringInterval.PERIOD_DAYS,
            "amount": int(amount),
            "max_count": AlbatalRecurringMaxCount.MAX_COUNT,
        }
    
    return payload


async def _call_albatal_api(wpf_payload: dict) -> dict:
    """
    Albatal APIを呼び出し
    
    Args:
        wpf_payload: WPFペイロード
    
    Returns:
        Albatal APIレスポンス
    
    Raises:
        HTTPException: API呼び出しが失敗した場合
    """
    request_url = f"{ALBATAL_API_WPF_URL}/api/wpf/create"
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
        raise HTTPException(
            status_code=500,
            detail=f"Albatal API request failed: {response.status_code}"
        )
    
    return response.json()


def _build_session_response(
    transaction_id: UUID,
    return_url: str | None,
    payment_url: str,
) -> AlbatalSessionResponse:
    """
    セッションレスポンスを作成
    
    Args:
        transaction_id: トランザクションID
        return_url: リターンURL
        payment_url: 決済URL
    
    Returns:
        セッションレスポンス
    """
    base_url = f"{FRONTEND_URL}{return_url}" if return_url else FRONTEND_URL
    return AlbatalSessionResponse(
        transaction_id=transaction_id,
        success_url=base_url,
        failure_url=base_url,
        payment_url=payment_url,
    )


def _extract_payment_url(albatal_response: dict) -> str:
    """
    Albatalレスポンスから決済URLを抽出
    
    Args:
        albatal_response: Albatal APIレスポンス
    
    Returns:
        決済URL
    
    Raises:
        HTTPException: 決済URLが見つからない場合
    """
    payment_url = (
        albatal_response.get("redirect_url")
        or albatal_response.get("url")
        or albatal_response.get("payment_url")
        or albatal_response.get("wpf_url")
    )
    
    if not payment_url:
        logger.error(f"No payment URL in Albatal response: {albatal_response}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get payment URL from Albatal"
        )
    
    return payment_url


def _apply_timesale_discount(
    original_price: int,
    timesale_info: dict | None,
    is_time_sale: bool,
) -> int:
    """
    タイムセール情報を適用して価格を計算
    
    Args:
        original_price: 元の価格
        timesale_info: タイムセール情報
        is_time_sale: タイムセールフラグ
    
    Returns:
        タイムセール適用後の価格
    
    Raises:
        HTTPException: タイムセールが期限切れまたは無効な場合
    """
    if not is_time_sale:
        return original_price
    
    if not timesale_info:
        raise HTTPException(status_code=400, detail=_TIMESALE_EXPIRED_MESSAGE)
    
    if timesale_info.get("is_active") and not timesale_info.get("is_expired"):
        sale_percentage = timesale_info.get("sale_percentage", 0)
        discounted_price = math.ceil(
            original_price - original_price * sale_percentage / 100
        )
        return discounted_price
    else:
        raise HTTPException(status_code=400, detail=_TIMESALE_EXPIRED_MESSAGE)


def _set_money(request: AlbatalSessionRequest, db: Session) -> tuple[int, str, int]:
    """
    決済金額設定
    
    Args:
        request: セッションリクエスト
        db: データベースセッション
    
    Returns:
        (決済金額, order_id, トランザクションタイプ) のタプル
    
    Raises:
        HTTPException: バリデーションエラーまたは計算エラー
    """
    try:
        if request.purchase_type == PurchaseType.SINGLE:
            if not request.price_id:
                raise HTTPException(
                    status_code=400,
                    detail="Price ID is required for single purchase"
                )
            
            # 対象のレコードに対してロックをかける（select_for_update）
            price = db.query(Prices).filter(
                Prices.id == request.price_id
            ).with_for_update().first()
            
            if not price:
                raise HTTPException(status_code=404, detail="Price not found")
            
            original_price = price.price
            
            # タイムセール情報を適用
            if request.is_time_sale:
                price_timesale_info = get_active_price_timesale(
                    db, price.post_id, price.id
                )
                original_price = _apply_timesale_discount(
                    original_price,
                    price_timesale_info,
                    request.is_time_sale,
                )
            
            money = math.floor(
                original_price * (1 + PaymentPlanPlatformFeePercent.DEFAULT / 100)
            )
            order_id = request.price_id
            transaction_type = PaymentTransactionType.SINGLE
            
        else:  # subscription
            if not request.plan_id:
                raise HTTPException(
                    status_code=400,
                    detail="Plan ID is required for subscription"
                )
            
            # 対象のレコードに対してロックをかける（select_for_update）
            plan = db.query(Plans).filter(
                Plans.id == request.plan_id
            ).with_for_update().first()
            
            if not plan:
                raise HTTPException(status_code=404, detail="Plan not found")
            
            original_price = plan.price
            
            # タイムセール情報を適用
            if request.is_time_sale:
                plan_timesale_info = get_active_plan_timesale(db, plan.id)
                original_price = _apply_timesale_discount(
                    original_price,
                    plan_timesale_info,
                    request.is_time_sale,
                )
            
            money = math.floor(
                original_price * (1 + PaymentPlanPlatformFeePercent.DEFAULT / 100)
            )
            order_id = request.plan_id
            transaction_type = PaymentTransactionType.SUBSCRIPTION
        
        return money, order_id, transaction_type
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Albatal set money failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Albatal set money failed: {str(e)}"
        )

def _build_return_url(return_url: str | None, transaction_id: UUID) -> str:
    """
    リターンURLを作成
    
    Args:
        return_url: リターンURL
        transaction_id: トランザクションID

    Returns:
        リターンURL
    """
    # return_urlにplanが含まれている場合は?transaction_id={transaction_id}を追加
    if "plan" in return_url:
        return f"{FRONTEND_URL}{return_url}?transaction_id={transaction_id}"
    else:
        return f"{FRONTEND_URL}{return_url}&transaction_id={transaction_id}"


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

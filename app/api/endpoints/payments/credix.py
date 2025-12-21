"""
CREDIX決済APIエンドポイント
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.base import get_db
from app.schemas.credix import (
    CredixSessionRequest,
    CredixSessionResponse,
    CredixPaymentResultResponse,
    PurchaseType
)
from app.services.credix import credix_client
from app.api.commons.utils import generate_sendid
from app.crud import payment_transactions_crud, user_providers_crud, providers_crud, price_crud, plan_crud
from app.deps.auth import get_current_user_optional
from app.models.user import Users
from app.models.providers import Providers
from app.models.plans import Plans
from app.models.prices import Prices
from app.constants.number import PaymentPlanPlatformFeePercent
from app.constants.enums import PaymentTransactionType, TransactionType
from app.constants.messages import CredixMessage    
from app.core.logger import Logger
import os
import math
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://mijfans.jp")

logger = Logger.get_logger()
router = APIRouter(prefix="/credix", tags=["CREDIX決済"])

FREE_ORDER_ID = "FREE_ORDER"

@router.post("/session", response_model=CredixSessionResponse)
async def create_credix_session(
    request: CredixSessionRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user_optional)
):
    """
    CREDIXセッション発行（初回決済・リピーター決済）

    - user_providersテーブルを確認し、sendidの有無で初回/リピーター決済を判定
    - セッションIDを発行し、payment_transactionsテーブルにレコード作成
    - 初回決済: カード情報を毎回入力し、決済完了したカード情報をCREDIXサーバに保存
    - リピーター決済: CREDIXサーバに保存されたカード情報を利用して決済処理を実行
    """
    try:
        # CREDIXプロバイダーID取得
        credix_provider = providers_crud.get_provider_by_code(db, "credix")
        if not credix_provider:
            raise HTTPException(status_code=500, detail="CREDIX provider not found in database")

        # user_providersテーブル確認
        user_provider = user_providers_crud.get_user_provider(
            db=db,
            user_id=current_user.id,
            provider_id=credix_provider.id
        )

        # TODO: user_providerが複数の場合は、画面に戻してどのカードを使うかを選択させる

        # sendid生成または取得
        is_first_payment = user_provider is None or user_provider.sendid is None

        # 決済完了後のリダイレクトURL
        if request.purchase_type == PurchaseType.SINGLE:
            success_url = f"{FRONTEND_URL}/post/detail?post_id={request.order_id}"
            failure_url = f"{FRONTEND_URL}/post/detail?post_id={request.order_id}"
        else:
            success_url = f"{FRONTEND_URL}/plan/{request.order_id}"
            failure_url = f"{FRONTEND_URL}/plan/{request.order_id}"


        if is_first_payment:
            sendid = generate_sendid(length=20)
        else:
            sendid = user_provider.sendid

        # 決済金額計算
        money, order_id, transaction_type = _set_money(request, db)

        # 決済トランザクション作成（仮のセッションID生成）
        temp_session_id = generate_sendid(length=20)
        transaction = _create_transaction(
            db=db,
            current_user=current_user,
            provider_id=credix_provider.id,
            transaction_type=transaction_type,
            session_id=temp_session_id,
            order_id=order_id,
        )

        # sendpointにtransaction_idを含める
        sendpoint = TransactionType.PAYMENT_ORIGIN_FRONT + "_" + str(transaction.id)

        # CREDIXセッション発行API呼び出し（初回決済・リピーター決済共通）
        try:
            session_data = await credix_client.create_session(
                sendid=sendid,
                money=money,
                email=current_user.email if current_user else None,
                sendpoint=sendpoint,
                success_url=success_url,
                failure_url=failure_url,
                is_repeater=(not is_first_payment),  # リピーター決済かどうか
                search_type=2,  # clientip + sendid で会員を検索（デフォルト）
                use_seccode=True,  # セキュリティコード入力を表示
                send_email=True,  # 決済完了メール送信
            )
        except Exception as e:
            logger.error(f"CREDIX API error: {e}")
            raise HTTPException(status_code=500, detail=f"CREDIX API error: {str(e)}")

        # セッション発行失敗チェック
        if session_data["result"] != "ok":
            error_msg = session_data.get("error_message", "Unknown error")
            logger.error(f"CREDIX session creation failed: {error_msg}")

            # リピーター決済失敗の場合は初回決済を案内
            if not is_first_payment:
                if "Member data not found" in error_msg or "Card has expired" in error_msg:
                    raise HTTPException(
                        status_code=400,
                        detail=f"リピーター決済が利用できません。初回決済をご利用ください。理由: {error_msg}"
                    )

            raise HTTPException(status_code=400, detail=f"CREDIX session creation failed: {error_msg}")

        session_id = session_data["sid"]

        # transaction の session_id を更新
        transaction.session_id = session_id
        db.commit()
        db.refresh(transaction)

        # 決済画面URL生成（初回決済・リピーター決済共通）
        payment_url = credix_client.get_payment_url()

        return CredixSessionResponse(
            session_id=session_id,
            payment_url=payment_url,
            transaction_id=str(transaction.id),
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"CREDIX session creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"CREDIX session creation failed: {str(e)}")

@router.post("/free/payment", response_model=CredixSessionResponse)
async def create_credix_free_payment(
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user_optional)
):
    """
    CREDIXセッション発行（カード登録）

    - user_providersテーブルを確認し、sendidの有無で初回/リピーター決済を判定
    - セッションIDを発行し、payment_transactionsテーブルにレコード作成
    - 初回決済: カード情報を毎回入力し、決済完了したカード情報をCREDIXサーバに保存
    - リピーター決済: CREDIXサーバに保存されたカード情報を利用して決済処理を実行
    """
    try:
        # CREDIXプロバイダーID取得
        credix_provider = providers_crud.get_provider_by_code(db, "credix")

        # 決済完了後のリダイレクトURL
        success_url = f"{FRONTEND_URL}/account/payment"
        failure_url = f"{FRONTEND_URL}/account/payment"

        # sendid生成
        sendid = generate_sendid(length=20)

        # 決済金額計算
        money = 0
        order_id = FREE_ORDER_ID
        transaction_type = PaymentTransactionType.FREE

        # 決済トランザクション作成（仮のセッションID生成）
        temp_session_id = generate_sendid(length=20)

        transaction = _create_transaction(
            db=db,
            current_user=current_user,
            provider_id=credix_provider.id,
            transaction_type=transaction_type,
            session_id=temp_session_id,
            order_id=order_id,
        )

        # sendpointにtransaction_idを含める
        sendpoint = TransactionType.PAYMENT_ORIGIN_FREE + "_" + str(transaction.id)

        # CREDIXセッジン発行API呼び出し
        try:
            session_data = await credix_client.create_session(
                sendid=sendid,
                money=money,
                email=current_user.email if current_user else None,
                sendpoint=sendpoint,
                success_url=success_url,
                failure_url=failure_url,
                is_repeater=False,  # リピーター決済ではない
                search_type=2,  # clientip + sendid で会員を検索（デフォルト）
                use_seccode=False,  # セキュリティコード入力を非表示
                send_email=False,  # 決済完了メール送信を非表示
            )
        except Exception as e:
            logger.error(f"CREDIX API error: {e}")
            raise HTTPException(status_code=500, detail=f"CREDIX API error: {str(e)}")

        if session_data["result"] != "ok":
            error_msg = session_data.get("error_message", "Unknown error")
            logger.error(f"CREDIX session creation failed: {error_msg}")
            raise HTTPException(status_code=400, detail=f"CREDIX session creation failed: {error_msg}")

        session_id = session_data["sid"]

        # transaction の session_id を更新
        transaction.session_id = session_id
        db.commit()
        db.refresh(transaction)

        # 決済画面URL生成（初回決済・リピーター決済共通）
        payment_url = credix_client.get_payment_url()

        return CredixSessionResponse(
            session_id=session_id,
            payment_url=payment_url,
            transaction_id=str(transaction.id),
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"CREDIX free session creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"CREDIX free session creation failed: {str(e)}")

def _set_money(request: CredixSessionRequest, db: Session) -> tuple[int, str, int]:
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
            # 元の価格を保持し、手数料込みの金額を計算（DBの値は更新しない）
            original_price = price.price
            money = math.ceil(original_price * (1 + PaymentPlanPlatformFeePercent.DEFAULT / 100))
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
            money = math.ceil(original_price * (1 + PaymentPlanPlatformFeePercent.DEFAULT / 100))
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
        logger.error(f"CREDIX create transaction failed: {e}")
        raise HTTPException(status_code=500, detail=f"CREDIX create transaction failed: {str(e)}")
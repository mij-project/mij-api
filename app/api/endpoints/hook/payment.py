from fastapi import APIRouter, Query, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta

from app.core.logger import Logger
from app.db.base import get_db
from app.crud import payment_transactions_crud, user_providers_crud, payments_crud, subscriptions_crud
from app.models.providers import Providers
from app.models.posts import Posts
from sqlalchemy import select

logger = Logger.get_logger()
router = APIRouter()

@router.get("/payment")
async def payment_webhook(
    clientip: Optional[str] = Query(None, alias="clientip"),
    telno: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    sendid: Optional[str] = Query(None),
    sendpoint: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    money: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    """
    CREDIX決済結果Webhook

    URL形式: /payment?clientip=***&telno=***&email=***&sendid=***&sendpoint=***&result=***&money=***

    Args:
        clientip: クライアントIP
        telno: 電話番号
        email: メールアドレス
        sendid: カードID
        sendpoint: フリーパラメータ（transaction_idを含む想定）
        result: 決済結果（OK/NG）
        money: 決済金額
    """
    logger.info("=== CREDIX Webhook受信 ===")
    logger.info(f"clientip: {clientip}")
    logger.info(f"telno: {telno}")
    logger.info(f"email: {email}")
    logger.info(f"sendid: {sendid}")
    logger.info(f"sendpoint: {sendpoint}")
    logger.info(f"result: {result}")
    logger.info(f"money: {money}")

    # sendpointからtransaction_idを抽出
    # 想定フォーマット: "post_{post_id}_{transaction_id}"
    if not sendpoint:
        logger.error("sendpoint is required")
        return PlainTextResponse(content="successok", status_code=200)  # CREDIXには成功を返す

    sendpoint_parts = sendpoint.split("_")
    if len(sendpoint_parts) < 3:
        logger.error(f"Invalid sendpoint format: {sendpoint}")
        return PlainTextResponse(content="successok", status_code=200)

    try:
        post_id_str = sendpoint_parts[1]
        transaction_id_str = sendpoint_parts[2]
        transaction_id = UUID(transaction_id_str)
    except (IndexError, ValueError) as e:
        logger.error(f"Failed to parse sendpoint: {e}")
        return PlainTextResponse(content="successok", status_code=200)

    # トランザクション取得
    transaction = await payment_transactions_crud.get_transaction_by_id(db, transaction_id)
    if not transaction:
        logger.error(f"Transaction not found: {transaction_id}")
        return PlainTextResponse(content="successok", status_code=200)

    # 決済結果判定
    is_success = result == "OK"

    if is_success:
        logger.info(f"決済成功: transaction_id={transaction_id}")

        # トランザクションステータス更新: completed
        await payment_transactions_crud.update_transaction_status(
            db=db,
            transaction_id=transaction.id,
            status=2  # completed
        )

        # 投稿取得（クリエイター情報取得）
        post_result = await db.execute(
            select(Posts).where(Posts.id == UUID(post_id_str))
        )
        post = post_result.scalar_one_or_none()
        if not post:
            logger.error(f"Post not found: {post_id_str}")
            return PlainTextResponse(content="successok", status_code=200)

        # paymentsテーブルにレコード作成
        payment = await payments_crud.create_payment(
            db=db,
            transaction_id=transaction.id,
            payment_type=transaction.type,
            order_id=transaction.order_id,
            order_type=transaction.type,
            provider_id=transaction.provider_id,
            provider_payment_id=transaction.session_id,
            buyer_user_id=transaction.user_id,
            seller_user_id=post.user_id,
            payment_amount=money if money else 0,
            payment_price=money if money else 0,
            status=2  # succeeded
        )

        # subscriptionsテーブルにレコード作成
        access_type = 1 if transaction.type == 2 else 2  # 1=plan, 2=one_time
        access_start = datetime.utcnow()

        # サブスクの場合は1ヶ月後、単発の場合はNULL
        access_end = access_start + timedelta(days=30) if transaction.type == 2 else None
        next_billing_date = access_end if transaction.type == 2 else None

        subscription = await subscriptions_crud.create_subscription(
            db=db,
            access_type=access_type,
            user_id=transaction.user_id,
            creator_id=post.user_id,
            order_id=transaction.order_id,
            order_type=transaction.type,
            access_start=access_start,
            access_end=access_end,
            next_billing_date=next_billing_date,
            provider_id=transaction.provider_id,
            payment_id=payment.id,
            status=1  # active
        )

        # user_providersテーブル作成または更新
        credix_result = await db.execute(
            select(Providers).where(Providers.code == "credix")
        )
        credix_provider = credix_result.scalar_one_or_none()

        if credix_provider:
            existing_user_provider = await user_providers_crud.get_user_provider(
                db=db,
                user_id=transaction.user_id,
                provider_id=credix_provider.id
            )

            if not existing_user_provider:
                # 初回決済: user_providers作成
                await user_providers_crud.create_user_provider(
                    db=db,
                    user_id=transaction.user_id,
                    provider_id=credix_provider.id,
                    sendid=sendid
                )
                logger.info(f"Created user_provider: user_id={transaction.user_id}, sendid={sendid}")
            else:
                # リピーター決済: 最終利用日時更新
                await user_providers_crud.update_last_used_at(
                    db=db,
                    user_provider_id=existing_user_provider.id
                )
                logger.info(f"Updated user_provider last_used_at: {existing_user_provider.id}")

        logger.info(f"Payment created: {payment.id}")
        logger.info(f"Subscription created: {subscription.id}")

    else:
        logger.info(f"決済失敗: transaction_id={transaction_id}")

        # トランザクションステータス更新: failed
        await payment_transactions_crud.update_transaction_status(
            db=db,
            transaction_id=transaction.id,
            status=3  # failed
        )

    # CREDIXに成功レスポンス返却
    return PlainTextResponse(content="successok", status_code=200)
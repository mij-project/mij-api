from fastapi import APIRouter, Query
from typing import Optional
from app.core.logger import Logger
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
) -> dict:
    """
    PaymentのWebhookを受け取って処理する
    URL形式: /payment?clientip=***&telno=***&email=***&sendid=***&sendpoint=***&result=***
    Args:
        clientip: クライアントIP
        telno: 電話番号
        email: メールアドレス
        sendid: ユーザーID
        sendpoint: 送信ポイント
        result: 結果
    """
    logger.info(f"clientip: {clientip}")
    logger.info(f"telno: {telno}")
    logger.info(f"email: {email}")
    logger.info(f"sendid: {sendid}")
    logger.info(f"sendpoint: {sendpoint}")
    logger.info(f"result: {result}")
    return {"ok": True}
from fastapi import APIRouter, Query
from typing import Optional

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
    print(f"clientip: {clientip}")
    print(f"telno: {telno}")
    print(f"email: {email}")
    print(f"sendid: {sendid}")
    print(f"sendpoint: {sendpoint}")
    print(f"result: {result}")
    return {"ok": True}
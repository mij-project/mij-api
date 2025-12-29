from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

router = APIRouter()

@router.post("/payment")
async def univa_payment_webhook(request: Request):
    return PlainTextResponse(content="success", status_code=200)
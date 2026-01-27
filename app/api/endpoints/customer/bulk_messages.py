# app/api/endpoints/customer/bulk_messages.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
import logging
import os
import json
from typing import List
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.models.profiles import Profiles
from app.crud import bulk_message_crud
from app.crud import notifications_crud
from app.schemas.bulk_message import (
    BulkMessageRecipientsResponse,
    PresignedUrlRequest,
    PresignedUrlResponse,
    BulkMessageSendRequest,
    BulkMessageSendResponse,
)
from app.services.s3 import presign, keygen
from app.constants.enums import MessageAssetType
from app.services.s3.client import scheduler_client
from datetime import datetime, timezone, timedelta
from app.crud.reservation_message_crud import ReservationMessageCrud
from app.models.reservation_message import ReservationMessage
from app.api.commons.function import CommonFunction
from app.services.email.send_email import send_message_notification_email
from app.domain.bulk_message.bulk_message import BulkMessageDomain
from app.deps.initial_domain import initial_bulk_message_domain

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/recipients", response_model=BulkMessageRecipientsResponse)
def get_bulk_message_recipients(
    current_user: Users = Depends(get_current_user),
    initial_bulk_message_domain: BulkMessageDomain = Depends(initial_bulk_message_domain),
    db: Session = Depends(get_db),
):
    """
    一斉送信の送信先リスト情報を取得
    - クリエイターのみアクセス可能
    - チップ送信者数、単品購入者数、プラン別加入者数を返す
    """

    recipients = initial_bulk_message_domain.get_bulk_message_recipients(current_user.id)

    return BulkMessageRecipientsResponse(
        chip_senders_count=recipients['chip_senders_count'],
        single_purchasers_count=recipients['single_purchasers_count'],
        plan_subscribers=recipients['plan_subscribers'],
        follower_users_count=recipients['follower_users_count']
    )


@router.post("/upload-url", response_model=PresignedUrlResponse)
def get_bulk_message_upload_url(
    request: PresignedUrlRequest,
    current_user: Users = Depends(get_current_user),
    initial_bulk_message_domain: BulkMessageDomain = Depends(initial_bulk_message_domain),
):
    """
    一斉送信用メッセージアセットのPresigned URL取得
    - クリエイターのみアクセス可能
    - 画像または動画のアップロード用URL生成
    """
    
    result = initial_bulk_message_domain.get_presigned_url_for_bulk_message(request, current_user)
    return PresignedUrlResponse(
        storage_key=result["key"],
        upload_url=result["upload_url"],
        expires_in=result["expires_in"],
        required_headers=result["required_headers"],
    )



@router.post("/", response_model=BulkMessageSendResponse)
async def send_bulk_message(
    request: BulkMessageSendRequest,
    current_user: Users = Depends(get_current_user),
    initial_bulk_message_domain: BulkMessageDomain = Depends(initial_bulk_message_domain),
    db: Session = Depends(get_db),
):
    """
    一斉メッセージ送信
    - クリエイターのみアクセス可能
    - 選択された送信先に対してメッセージを一斉送信
    - 予約送信にも対応
    """
    try:
        result = await initial_bulk_message_domain.send_bulk_message(request, current_user)
        return BulkMessageSendResponse(
            message=result["message"],
            sent_count=result["sent_count"],
            scheduled=result["scheduled"],
            scheduled_at=result["scheduled_at"]
        )
    except Exception as e:
        db.rollback()
        logger.error(f"一斉送信エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))
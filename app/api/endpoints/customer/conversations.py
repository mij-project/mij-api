from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from typing import List
from uuid import UUID
import uuid
from app.services.email.send_email import send_message_notification_email
from app.models.profiles import Profiles
from app.schemas.conversation import MessageAssetInfo
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.crud import conversations_crud, user_crud, profile_crud, payments_crud, subscriptions_crud, message_assets_crud, notifications_crud
from app.models.conversation_participants import ConversationParticipants
from app.models.payments import Payments
from app.models.subscriptions import Subscriptions
from app.models.plans import Plans
from app.constants.enums import PaymentType, PaymentStatus, SubscriptionStatus, MessageAssetStatus, AccountType
from app.schemas.conversation import (
    MessageCreate,
    MessageResponse,
    ConversationResponse,
    ConversationMessagesResponse,
)
from app.schemas.message_asset import (
    PresignedUrlRequest,
    PresignedUrlResponse,
)
from app.api.commons.function import CommonFunction
from app.services.s3 import presign, keygen
from app.constants.enums import MessageAssetType
import logging
import os

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_URL = os.getenv("CDN_BASE_URL")
MESSAGE_ASSETS_CDN_URL = os.getenv("MESSAGE_ASSETS_CDN_URL", "")

# ========== 一般ユーザー用エンドポイント ==========


@router.get("/delusion", response_model=ConversationResponse)
def get_or_create_delusion_conversation(
    current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    妄想メッセージ会話を取得または作成
    - 1ユーザーにつき1つの管理人トークルーム
    - 自動で作成される
    """
    conversation = conversations_crud.get_or_create_delusion_conversation(
        db, current_user.id
    )

    return ConversationResponse(
        id=conversation.id,
        type=conversation.type,
        is_active=conversation.is_active,
        last_message_id=conversation.last_message_id,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        unread_count=0,
    )


@router.get("/delusion/messages", response_model=List[MessageResponse])
def get_delusion_messages(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    妄想メッセージの一覧を取得
    - 古い順にソート
    - 送信者情報（名前、アバター）を含む
    """
    # ユーザーの妄想メッセージ会話を取得
    conversation = conversations_crud.get_or_create_delusion_conversation(
        db, current_user.id
    )

    # メッセージ一覧を取得
    messages = conversations_crud.get_messages_by_conversation(
        db, conversation.id, skip, limit
    )

    # レスポンスを構築
    response = []
    for message, sender, profile, admin in messages:
        # 送信者情報の判定
        sender_username = None
        sender_avatar = None
        sender_profile_name = None

        if sender and profile:
            # ユーザーメッセージの場合
            sender_username = sender.profile_name
            sender_avatar = (
                f"{BASE_URL}/{profile.avatar_url}" if profile.avatar_url else None
            )
            sender_profile_name = sender.profile_name
        elif admin:
            # 管理者メッセージの場合
            sender_username = "運営"
            sender_avatar = None
            sender_profile_name = "運営"

        response.append(
            MessageResponse(
                id=message.id,
                conversation_id=message.conversation_id,
                sender_user_id=message.sender_user_id,
                sender_admin_id=message.sender_admin_id,
                type=message.type,
                body_text=message.body_text,
                created_at=message.created_at,
                updated_at=message.updated_at,
                sender_username=sender_username,
                sender_avatar=sender_avatar,
                sender_profile_name=sender_profile_name,
            )
        )

    return response


@router.post("/delusion/messages", response_model=MessageResponse)
def send_delusion_message(
    message_data: MessageCreate,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    妄想メッセージを送信
    - テキストのみ対応
    """
    # ユーザーの妄想メッセージ会話を取得
    conversation = conversations_crud.get_or_create_delusion_conversation(
        db, current_user.id
    )

    # メッセージを作成
    message = conversations_crud.create_message(
        db=db,
        conversation_id=conversation.id,
        sender_user_id=current_user.id,
        body_text=message_data.body_text,
    )

    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_user_id=message.sender_user_id,
        type=message.type,
        body_text=message.body_text,
        created_at=message.created_at,
        updated_at=message.updated_at,
        sender_username=current_user.username,
        sender_avatar=current_user.avatar_storage_key,
        sender_profile_name=current_user.profile_name,
    )


@router.get("/unread")
async def get_new_conversations_unread(
    current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    新着メッセージ数を取得
    """
    is_unread = conversations_crud.get_new_conversations_unread(db, current_user.id)
    return {"is_unread": is_unread}



@router.get("/list")
def get_user_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=1000),
    search: str = Query(None),
    sort: str = Query("last_message_desc"),
    unread_only: bool = Query(False),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    ログインユーザーが参加しているtype=2の会話リストを取得

    Args:
        skip: スキップ件数（無限スクロール用）
        limit: 取得件数
        search: 検索キーワード（相手の名前で検索）
        sort: ソート順（last_message_desc, last_message_asc）
        unread_only: 未読のみフィルター

    Returns:
        会話リスト
    """
    conversations, total = conversations_crud.get_user_conversations(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        search=search,
        sort=sort,
        unread_only=unread_only,
    )

    return {
        "data": conversations,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


# ========== 個別会話のメッセージAPI ==========
@router.get("/{conversation_id}/messages", response_model=ConversationMessagesResponse)
def get_conversation_messages(
    conversation_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    個別会話のメッセージ一覧を取得
    - ユーザーが参加している会話のみ取得可能
    - 古い順にソート
    - 相手のプロフィール情報も含む
    """
    # ユーザーがこの会話に参加しているか確認
    if not conversations_crud.is_user_in_conversation(db, conversation_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied to this conversation")

    # メッセージ一覧を取得
    messages = conversations_crud.get_messages_by_conversation(
        db, conversation_id, skip, limit
    )

    # 会話の参加者から相手のユーザー情報を取得
    partner_user_id = None
    partner_username = None
    partner_profile_name = None
    partner_avatar = None

    # conversation_participantsから相手のuser_idを取得
    participants = db.query(ConversationParticipants).filter(
        ConversationParticipants.conversation_id == conversation_id,
        ConversationParticipants.user_id != current_user.id
    ).first()


    if participants:
        partner_user_id = participants.user_id
        # 相手のユーザー情報とプロフィールを取得
        partner_user = user_crud.get_user_by_id(db, partner_user_id)
        partner_profile_username = None
        if partner_user:
            partner_username = partner_user.profile_name
            partner_profile_name = partner_user.profile_name
            # プロフィールから相手のusernameとアバターを取得
            partner_profile = profile_crud.get_profile_by_user_id(db, partner_user_id)
            if partner_profile:
                partner_profile_username = partner_profile.username
                if partner_profile.avatar_url:
                    partner_avatar = f"{BASE_URL}/{partner_profile.avatar_url}"

    # メッセージレスポンスを構築
    message_responses = []
    for message, sender, profile, admin in messages:
        # 送信者情報の判定
        sender_username = None
        sender_avatar = None
        sender_profile_name = None

        if sender and profile:
            # ユーザーメッセージの場合
            sender_username = sender.profile_name
            sender_avatar = (
                f"{BASE_URL}/{profile.avatar_url}" if profile.avatar_url else None
            )
            sender_profile_name = sender.profile_name
        elif admin:
            # 管理者メッセージの場合
            sender_username = "運営"
            sender_avatar = None
            sender_profile_name = "運営"

        # メッセージアセット情報を取得
        asset_response = None
        message_assets = message_assets_crud.get_message_assets_by_message_id(db, message.id)
        if message_assets:
            # 最初のアセットのみ取得（1メッセージにつき1アセット）
            asset = message_assets[0]

            # 承認済みの場合のみCDN URLを設定
            cdn_url = None
            if asset.status == MessageAssetStatus.APPROVED:
                cdn_url = f"{MESSAGE_ASSETS_CDN_URL}/{asset.storage_key}"

            asset_response = MessageAssetInfo(
                id=asset.id,
                status=asset.status,
                asset_type=asset.asset_type,
                cdn_url=cdn_url,
                storage_key=asset.storage_key,
            )

        # body_textが空かつassetもない場合は除外
        if not message.body_text and asset_response is None:
            continue

        message_responses.append(
            MessageResponse(
                id=message.id,
                conversation_id=message.conversation_id,
                sender_user_id=message.sender_user_id,
                sender_admin_id=message.sender_admin_id,
                type=message.type,
                body_text=message.body_text,
                created_at=message.created_at,
                updated_at=message.updated_at,
                sender_username=sender_username,
                sender_avatar=sender_avatar,
                sender_profile_name=sender_profile_name,
                asset=asset_response,
            )
        )

    # メッセージ送信権限の判定
    can_send_message = False
    has_dm_plan_to_partner = False
    has_dm_plan_from_partner = False
    has_chip_history_to_partner = False
    has_chip_history_from_partner = False

    if partner_user_id:
        # チップ送信履歴の確認（双方向）
        has_chip_history_to_partner = bool(payments_crud.get_payment_by_user_id(db, current_user.id, partner_user_id, PaymentType.CHIP))
        has_chip_history_from_partner = bool(payments_crud.get_payment_by_user_id(db, partner_user_id, current_user.id, PaymentType.CHIP))

        # DM解放プラン加入の確認（双方向）
        # current_userがpartner_userのDM解放プランに加入している（open_dm_flg=true）
        has_dm_plan_to_partner = bool(subscriptions_crud.get_dm_release_plan_subscription(db, current_user.id, partner_user_id))
        # partner_userがcurrent_userのDM解放プランに加入している（open_dm_flg=true）
        has_dm_plan_from_partner = bool(subscriptions_crud.get_dm_release_plan_subscription(db, partner_user_id, current_user.id))

        # どちらか一方を満たせばメッセージ送信可能
        can_send_message = has_chip_history_to_partner or has_dm_plan_to_partner or has_dm_plan_from_partner or has_chip_history_from_partner

    # ユーザーの役割情報を取得
    current_user_is_creator = current_user.role == AccountType.CREATOR
    partner_user_is_creator = False
    if partner_user_id and partner_user:
        partner_user_is_creator = partner_user.role == AccountType.CREATOR

    # クリエイター ⇔ クリエイター 用フラグ
    # 購入されている側：相手がプラン加入（任意のプラン） OR チップ送信
    is_current_user_seller = bool(subscriptions_crud.get_subscription_by_user_id(db, partner_user_id, current_user.id)) or has_chip_history_from_partner
    # 購入者側：自分がDM解放プラン購入（open_dm_flg=true） OR チップ送信
    is_current_user_buyer = has_dm_plan_to_partner or has_chip_history_to_partner

    return ConversationMessagesResponse(
        messages=message_responses,
        partner_user_id=partner_user_id,
        partner_username=partner_username,
        partner_profile_name=partner_profile_name,
        partner_profile_username=partner_profile_username,
        partner_avatar=partner_avatar,
        can_send_message=can_send_message,
        current_user_is_creator=current_user_is_creator,
        partner_user_is_creator=partner_user_is_creator,
        has_dm_plan_to_partner=has_dm_plan_to_partner,
        has_dm_plan_from_partner=has_dm_plan_from_partner,
        has_chip_history_to_partner=has_chip_history_to_partner,
        has_chip_history_from_partner=has_chip_history_from_partner,
        is_current_user_seller=is_current_user_seller,
        is_current_user_buyer=is_current_user_buyer,
    )


@router.post("/{conversation_id}/messages", response_model=MessageResponse)
def send_conversation_message(
    conversation_id: UUID,
    message_data: MessageCreate,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    個別会話にメッセージを送信
    - ユーザーが参加している会話のみ送信可能
    - テキストのみ、または画像/動画を含むメッセージを送信可能
    """
    # ユーザーがこの会話に参加しているか確認
    if not conversations_crud.is_user_in_conversation(db, conversation_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied to this conversation")

    # テキストとアセットの両方がない場合はエラー
    if not message_data.body_text and not message_data.asset_storage_key:
        raise HTTPException(status_code=400, detail="Either body_text or asset is required")

    # アセットがある場合はasset_typeも必要
    if message_data.asset_storage_key and not message_data.asset_type:
        raise HTTPException(status_code=400, detail="asset_type is required when asset_storage_key is provided")

    # メッセージを作成
    group_by = str(uuid.uuid4())
    message = conversations_crud.create_message(
        db=db,
        conversation_id=conversation_id,
        sender_user_id=current_user.id,
        body_text=message_data.body_text,
        group_by=group_by,
    )

    # アセットがある場合はmessage_assetレコードを作成
    message_asset = None
    if message_data.asset_storage_key and message_data.asset_type:
        message_asset = message_assets_crud.create_message_asset(
            db=db,
            message_id=message.id,
            asset_type=message_data.asset_type,
            storage_key=message_data.asset_storage_key,
            status=MessageAssetStatus.PENDING,  # 審査待ち
        )

    # レスポンス構築
    asset_response = None
    if message_asset:
        asset_response = MessageAssetInfo(
            id=message_asset.id,
            status=message_asset.status,
            asset_type=message_asset.asset_type,
            cdn_url=None,  # 審査待ちの場合はnull
            storage_key=message_asset.storage_key,
        )

    

    # 通知処理（ベストエフォート - エラーでもメッセージ送信は成功とする）
    try:
        # 受信者を取得（送信者以外の参加者）
        recipients = db.query(ConversationParticipants).filter(
            ConversationParticipants.conversation_id == conversation_id,
            ConversationParticipants.user_id != current_user.id
        ).all()

        # 送信者のプロフィール情報を取得
        sender_profile = db.query(Profiles).filter(Profiles.user_id == current_user.id).first()
        sender_avatar_url = f"{os.getenv('CDN_BASE_URL')}/{sender_profile.avatar_url}" if sender_profile and sender_profile.avatar_url else None

        # メッセージプレビューを生成
        if message_data.body_text:
            message_preview = message_data.body_text[:50] if len(message_data.body_text) > 50 else message_data.body_text
        else:
            # アセットのみの場合
            if message_asset:
                if message_asset.asset_type == MessageAssetType.IMAGE:
                    message_preview = "画像を送信しました"
                elif message_asset.asset_type == MessageAssetType.VIDEO:
                    message_preview = "動画を送信しました"
                else:
                    message_preview = "メディアファイルを送信しました"
            else:
                message_preview = ""

        # 各受信者に通知とメールを送信
        for recipient in recipients:
            need_to_send_notification = CommonFunction.get_user_need_to_send_notification(db, recipient.user_id, "userMessages")
            if not need_to_send_notification:
                continue

            recipient_user = db.query(Users).filter(Users.id == recipient.user_id).first()
            if not recipient_user:
                continue

            notifications_crud.add_notification_for_new_message(
                db=db,
                recipient_user_id=recipient_user.id,
                sender_profile_name=current_user.profile_name or "Unknown User",
                sender_avatar_url=sender_avatar_url,
                message_preview=message_preview,
                conversation_id=conversation_id,
            )

            # メール通知を送信（通知可否情報を取得してから送信）
            need_to_send_email_notification = CommonFunction.get_user_need_to_send_notification(db, recipient_user.id, "message")
            if need_to_send_email_notification and recipient_user.email:
                logger.info(f"Attempting to send email notification to {recipient_user.email} for message {message.id}")
                conversation_url = f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/message/conversation/{conversation_id}"

                recipient_profile = db.query(Profiles).filter(Profiles.user_id == recipient_user.id).first()
                recipient_name = recipient_profile.username if recipient_profile and recipient_profile.username else recipient_user.profile_name

                send_message_notification_email(
                    to=recipient_user.email,
                    sender_name=current_user.profile_name or "Unknown User",
                    recipient_name=recipient_name or "User",
                    message_preview=message_preview,
                    conversation_url=conversation_url,
                )
                logger.info(f"Email notification call completed for {recipient_user.email}")
            else:
                if not need_to_send_email_notification:
                    logger.info(f"Email notification disabled for user {recipient_user.id}, skipping email notification")
                else:
                    logger.info(f"Recipient user {recipient_user.id} has no email address, skipping email notification")
    except Exception as e:
        # 通知エラーはログに記録するが、メッセージ送信は成功とする
        logger.error(f"Failed to send notification for message {message.id}: {e}")

    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_user_id=message.sender_user_id,
        sender_admin_id=message.sender_admin_id,
        type=message.type,
        body_text=message.body_text,
        created_at=message.created_at,
        updated_at=message.updated_at,
        sender_username=current_user.profile_name,
        sender_avatar=None,  # TODO: プロフィールから取得
        sender_profile_name=current_user.profile_name,
        asset=asset_response,
    )


@router.post("/{conversation_id}/messages/{message_id}/read")
def mark_conversation_message_as_read(
    conversation_id: UUID,
    message_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    メッセージを既読にする
    - ユーザーが参加している会話のみ既読可能
    """
    from app.core.logger import Logger
    logger = Logger.get_logger()

    logger.info(f"Mark as read request: conversation_id={conversation_id}, message_id={message_id}, user_id={current_user.id}")

    # ユーザーがこの会話に参加しているか確認
    if not conversations_crud.is_user_in_conversation(db, conversation_id, current_user.id):
        logger.warning(f"User {current_user.id} is not a participant in conversation {conversation_id}")
        raise HTTPException(status_code=403, detail="Access denied to this conversation")

    # 既読にする
    conversations_crud.mark_as_read(db, conversation_id, current_user.id, message_id)

    logger.info(f"Message {message_id} marked as read successfully")
    return {"status": "ok", "message": "Message marked as read"}


@router.get("/get-or-create/{partner_user_id}")
def get_or_create_conversation_with_user(
    partner_user_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    指定したユーザーとの会話を取得または作成
    - 既存の会話があればそれを返す
    - なければ新規作成して返す
    - 自分自身との会話は禁止
    """
    # 自分自身との会話は禁止
    if current_user.id == partner_user_id:
        raise HTTPException(status_code=400, detail="Cannot create conversation with yourself")

    # 既存の会話を取得または新規作成
    conversation = conversations_crud.get_or_create_dm_conversation(
        db=db,
        user_id_1=current_user.id,
        user_id_2=partner_user_id,
    )

    return {
        "conversation_id": str(conversation.id),
        "partner_user_id": str(partner_user_id),
    }


@router.get("/unread-count")
def get_unread_conversation_count(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    未読メッセージがある会話の数を取得
    - 自分以外が送った最新メッセージがある会話をカウント
    """
    unread_count = conversations_crud.get_unread_conversation_count(db, current_user.id)
    return {"unread_count": unread_count}


# ========== メッセージアセット用エンドポイント ==========

@router.post("/{conversation_id}/messages/upload-url", response_model=PresignedUrlResponse)
def get_message_asset_upload_url(
    conversation_id: UUID,
    request: PresignedUrlRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセット用のPresigned URL取得
    - ユーザーが参加している会話のみ取得可能
    - 画像または動画のアップロード用URL生成
    """
    try:
        # ユーザーがこの会話に参加しているか確認
        if not conversations_crud.is_user_in_conversation(db, conversation_id, current_user.id):
            raise HTTPException(status_code=403, detail="Access denied to this conversation")

        # ファイルタイプの検証
        allowed_image_types = ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"]
        allowed_video_types = ["video/mp4", "video/quicktime"]  # mp4, mov

        if request.asset_type == MessageAssetType.IMAGE:
            if request.content_type not in allowed_image_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid image content type. Allowed: {', '.join(allowed_image_types)}"
                )
        elif request.asset_type == MessageAssetType.VIDEO:
            if request.content_type not in allowed_video_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid video content type. Allowed: {', '.join(allowed_video_types)}"
                )
        else:
            raise HTTPException(status_code=400, detail="Invalid asset type")

        # 拡張子の検証
        allowed_extensions = {
            MessageAssetType.IMAGE: ["jpg", "jpeg", "png", "gif", "webp"],
            MessageAssetType.VIDEO: ["mp4", "mov"],
        }

        if request.file_extension.lower() not in allowed_extensions[request.asset_type]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file extension for asset type. Allowed: {', '.join(allowed_extensions[request.asset_type])}"
            )

        # ストレージキー生成（まだメッセージIDがないので仮のUUIDを使用）
        import uuid
        temp_message_id = str(uuid.uuid4())
        asset_type_str = "image" if request.asset_type == MessageAssetType.IMAGE else "video"
        
        storage_key = keygen.message_asset_key(
            conversation_id=str(conversation_id),
            message_id=temp_message_id,
            asset_type=asset_type_str,
            ext=request.file_extension.lower(),
        )

        # Presigned URL生成
        result = presign.presign_put(
            resource="message-assets",
            key=storage_key,
            content_type=request.content_type,
            expires_in=3600,  # 1時間
        )

        return PresignedUrlResponse(
            storage_key=result["key"],
            upload_url=result["upload_url"],
            expires_in=result["expires_in"],
            required_headers=result["required_headers"],
        )
    except Exception as e:
        logger.error(f"メッセージアセット用のPresigned URL取得エラーが発生しました: {e}")
        raise HTTPException(status_code=500, detail=str(e))
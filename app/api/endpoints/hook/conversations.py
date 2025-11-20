from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Cookie
from sqlalchemy.orm import Session
from typing import Dict, Set, Optional
from uuid import UUID
import json
import os

from app.db.base import get_db
from app.core.security import decode_token
from app.core.cookies import ACCESS_COOKIE
from app.models.user import Users
from app.models.admins import Admins
from app.crud.user_crud import get_user_by_id
from app.crud.admin_crud import get_admin_by_id
from app.crud import conversations_crud
from app.core.logger import Logger

logger = Logger.get_logger()
BASE_URL = os.getenv("CDN_BASE_URL")

router = APIRouter()

# アクティブなWebSocket接続を管理
# Key: conversation_id, Value: Set of WebSocket connections
active_connections: Dict[str, Set[WebSocket]] = {}

class ConnectionManager:
    """WebSocket接続を管理するクラス"""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, conversation_id: str):
        """WebSocket接続を追加"""
        await websocket.accept()
        if conversation_id not in self.active_connections:
            self.active_connections[conversation_id] = set()
        self.active_connections[conversation_id].add(websocket)

    def disconnect(self, websocket: WebSocket, conversation_id: str):
        """WebSocket接続を削除"""
        if conversation_id in self.active_connections:
            self.active_connections[conversation_id].discard(websocket)
            if not self.active_connections[conversation_id]:
                del self.active_connections[conversation_id]

    async def broadcast_to_conversation(self, conversation_id: str, message: dict):
        """特定の会話に接続している全員にメッセージを配信"""
        if conversation_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[conversation_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.add(connection)

            # 切断されたコネクションを削除
            for conn in disconnected:
                self.active_connections[conversation_id].discard(conn)


manager = ConnectionManager()


async def get_user_from_cookie(websocket: WebSocket, db: Session) -> Optional[Users]:
    """CookieからユーザーIDを取得"""
    try:
        # WebSocketのCookieヘッダーから access_token を取得
        cookies = websocket.cookies
        access_token = cookies.get(ACCESS_COOKIE)

        if not access_token:
            logger.error("❌ No access token found in cookies")
            return None

        payload = decode_token(access_token)

        if payload.get("type") != "access":
            logger.error("❌ Invalid token type")
            return None

        user_id = payload.get("sub")
        user = get_user_by_id(db, user_id)
        return user
    except Exception as e:
        logger.error(f"❌ Authentication error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def get_admin_from_cookie(websocket: WebSocket, db: Session) -> Optional[Admins]:
    """Cookieから管理者IDを取得"""
    try:
        # WebSocketのCookieヘッダーから access_token を取得
        cookies = websocket.cookies
        access_token = cookies.get(ACCESS_COOKIE)

        if not access_token:
            logger.error("❌ No access token found in cookies")
            return None

        payload = decode_token(access_token)

        if payload.get("type") != "access":
            logger.error("❌ Invalid token type")
            return None

        admin_id = payload.get("sub")
        admin = get_admin_by_id(db, admin_id)
        return admin
    except Exception as e:
        logger.error(f"❌ Admin authentication error: {e}")
        import traceback
        traceback.print_exc()
        return None


@router.websocket("/conversations/delusion")
async def websocket_delusion_endpoint(
    websocket: WebSocket,
    db: Session = Depends(get_db)
):
    """
    妄想メッセージ用WebSocketエンドポイント
    - Cookieからトークンを取得
    - ユーザーの妄想メッセージ会話に自動接続
    - リアルタイムでメッセージを送受信
    """

    # トークン検証
    user = await get_user_from_cookie(websocket, db)
    if not user:
        logger.error("❌ Authentication failed, closing connection")
        await websocket.close(code=4001, reason="Invalid token")
        return


    # ユーザーの妄想メッセージ会話を取得または作成
    conversation = conversations_crud.get_or_create_delusion_conversation(db, user.id)
    conversation_id = str(conversation.id)

    # WebSocket接続を確立
    await manager.connect(websocket, conversation_id)

    try:
        # 接続成功メッセージを送信
        connection_message = {
            "type": "connected",
            "conversation_id": conversation_id,
            "message": "Connected to delusion messages"
        }
        await websocket.send_json(connection_message)

        # メッセージの受信ループ
        while True:
            # クライアントからのメッセージを受信
            data = await websocket.receive_json()

            message_type = data.get("type")

            if message_type == "message":
                # テキストメッセージの送信
                body_text = data.get("body_text")

                if not body_text:
                    error_msg = {"type": "error", "message": "body_text is required"}
                    logger.error(f"❌ Sending error: {error_msg}")
                    await websocket.send_json(error_msg)
                    continue

                # メッセージをDBに保存
                logger.info(f"💾 Saving message to DB...")
                message = conversations_crud.create_message(
                    db=db,
                    conversation_id=UUID(conversation_id),
                    sender_user_id=user.id,
                    body_text=body_text
                )
                logger.info(f"✅ Message saved with ID: {message.id}")

                # 会話に接続している全員に配信
                broadcast_data = {
                    "type": "new_message",
                    "message": {
                        "id": str(message.id),
                        "conversation_id": str(message.conversation_id),
                        "sender_user_id": str(message.sender_user_id) if message.sender_user_id else None,
                        "sender_admin_id": None,
                        "body_text": message.body_text,
                        "created_at": message.created_at.isoformat(),
                        "sender_username": user.profile_name if hasattr(user, 'profile_name') else None,
                        "sender_avatar": f"{BASE_URL}/{user.profile.avatar_url}" if user.profile and user.profile.avatar_url else None,
                        "sender_profile_name": user.profile_name if hasattr(user, 'profile_name') else None
                    }
                }
                await manager.broadcast_to_conversation(conversation_id, broadcast_data)

            elif message_type == "ping":
                # Ping/Pongでコネクション維持
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket, conversation_id)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        import traceback
        traceback.print_exc()
        manager.disconnect(websocket, conversation_id)


@router.websocket("/admin/conversations/delusion/{conversation_id}")
async def websocket_admin_delusion_endpoint(
    websocket: WebSocket,
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """
    管理人用WebSocketエンドポイント
    - 特定の会話に接続
    - リアルタイムでメッセージを送受信
    """
    # トークン検証（管理者テーブルから取得）
    admin = await get_admin_from_cookie(websocket, db)
    if not admin:  # 管理者認証チェック
        await websocket.close(code=4003, reason="Admin access required")
        return

    # 会話の存在確認
    conversation = conversations_crud.get_conversation_by_id(db, UUID(conversation_id))
    if not conversation:
        await websocket.close(code=4004, reason="Conversation not found")
        return

    # WebSocket接続を確立
    await manager.connect(websocket, conversation_id)

    try:
        # 接続成功メッセージを送信
        await websocket.send_json({
            "type": "connected",
            "conversation_id": conversation_id,
            "message": "Connected to conversation as admin"
        })

        # メッセージの受信ループ
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "message":
                body_text = data.get("body_text")
                if not body_text:
                    await websocket.send_json({
                        "type": "error",
                        "message": "body_text is required"
                    })
                    continue

                # メッセージをDBに保存（管理者メッセージとして保存）
                message = conversations_crud.create_message(
                    db=db,
                    conversation_id=UUID(conversation_id),
                    sender_admin_id=admin.id,
                    body_text=body_text
                )

                # 会話に接続している全員に配信
                await manager.broadcast_to_conversation(conversation_id, {
                    "type": "new_message",
                    "message": {
                        "id": str(message.id),
                        "conversation_id": str(message.conversation_id),
                        "sender_user_id": None,
                        "sender_admin_id": str(message.sender_admin_id),
                        "body_text": message.body_text,
                        "created_at": message.created_at.isoformat(),
                        "sender_username": "運営",
                        "sender_avatar": None,
                        "sender_profile_name": "運営"
                    }
                })

            elif message_type == "mark_read":
                # 既読マーク
                message_id = data.get("message_id")
                if message_id:
                    conversations_crud.mark_as_read(
                        db=db,
                        conversation_id=UUID(conversation_id),
                        user_id=admin.id,
                        message_id=UUID(message_id)
                    )
                    await websocket.send_json({
                        "type": "read_confirmed",
                        "message_id": message_id
                    })

            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket, conversation_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket, conversation_id)

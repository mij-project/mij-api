from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.schemas.preregistrations import PreregistrationCreateRequest
from app.crud.preregistrations_curd import create_preregistration, is_preregistration_exists
from app.models.preregistrations import Preregistrations
from app.services.email.send_email import send_thanks_email
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()

@router.post("/")
def create_preregistration_endpoint(
    preregistration: PreregistrationCreateRequest, 
    db: Session = Depends(get_db),
    bg: BackgroundTasks = BackgroundTasks()
):
    """
    事前登録を行う

    Args:
        preregistration (PreregistrationCreateRequest): 事前登録データ
        db (Session, optional): データベースセッション
        bg (BackgroundTasks, optional): バックグラウンドタスク

    Raises:
        HTTPException: 事前登録データの作成に失敗した場合
        HTTPException: メール送信に失敗した場合

    Returns:
        dict: 事前登録データ、メール送信結果
    """
    try:
        if is_preregistration_exists(db, preregistration.email):
            return {
                "result": None,
                "email_queued": False,
                "email_error": "すでに事前登録されています"
            }

        preregistration_data = Preregistrations(
            name=preregistration.name,
            email=preregistration.email,
            x_name=preregistration.x_name
        )
        preregistration_data = create_preregistration(db, preregistration_data)

        if not preregistration_data:
            raise HTTPException(status_code=500, detail="Failed to create preregistration")
        
        email_error = None
        email_queued = False

        try:
            if bg is not None:
                bg.add_task(send_thanks_email, preregistration.email, preregistration.name or None)
                email_queued = True
            else:
                # もしBackgroundTasksを使えない構成なら同期送信
                send_thanks_email(preregistration.email, preregistration.name or None)
                email_queued = True
        except Exception as e:
            # 送信失敗は登録結果に影響させない
            email_error = str(e)
            logger.error("Error sending email", e)

        return {
            "result": preregistration_data,
            "email_queued": email_queued,
            "email_error": email_error
        }
    except Exception as e:
        logger.error("Error creating preregistration", e)
        raise HTTPException(status_code=500, detail=str(e)) 
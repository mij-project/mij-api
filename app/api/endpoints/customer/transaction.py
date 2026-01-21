from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.crud import payments_crud
from app.core.logger import Logger
from uuid import UUID
import asyncio
logger = Logger.get_logger()
router = APIRouter()

@router.get("/settlement-status/{transaction_id}")
async def get_settlement_status(
    transaction_id: str,
    db: Session = Depends(get_db),
):
    try:
        transaction_uuid = UUID(transaction_id)
        max_attempts = 30  # 30秒間
        attempt_interval = 1  # 1秒間隔
        
        for attempt in range(max_attempts):
            transaction = payments_crud.check_payment_status_by_transaction_id(db, transaction_uuid)
            
            if transaction:
                return True
            
            # 最後の試行でなければ1秒待機
            if attempt < max_attempts - 1:
                await asyncio.sleep(attempt_interval)
        
        return False
    except ValueError as e:
        logger.error(f"Invalid transaction_id format: {e}")
        raise HTTPException(status_code=400, detail="Invalid transaction_id format")
    except Exception as e:
        logger.error(f"Error getting transaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, asc
from datetime import datetime, timezone
from uuid import UUID
from app.models.providers import Providers
from app.core.logger import Logger
logger = Logger.get_logger()

def get_provider_by_code(db: Session, code: str) -> Optional[Providers]:
    """
    コードでプロバイダーを取得
    """
    try:
        provider = db.query(Providers).filter(Providers.code == code).first()
        return provider
    except Exception as e:
        logger.error(f"Get provider by id error: {e}")
        return None
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.api.commons.utils import generate_code
from app.crud.user_crud import check_profile_name_exists, create_super_user
from app.crud.profile_crud import create_profile
from app.db.base import get_db
from app.schemas.user import UserCreate

from app.core.logger import Logger

logger = Logger.get_logger()

router = APIRouter()

@router.post("/create-super-user")
def create_super_user_endpoint(
    user_create: UserCreate,
    db: Session = Depends(get_db),
):
    try:
        new_user = create_super_user(db, user_create.email, user_create.password, user_create.name)

        username_code = None
        for _ in range(10):  # 最大10回リトライ
            username_code = generate_code(5)
            is_profile_name_exists = check_profile_name_exists(db, username_code)
            if not is_profile_name_exists:
                break
        

        if not username_code:
            return Response(content="ユーザー名の生成に失敗しました。再度お試しください。", status_code=500)

        db_profile = create_profile(db, new_user.id, username_code)
        db.commit()
        db.refresh(new_user)
        db.refresh(db_profile)
        return Response(content="スーパーユーザー作成に成功しました", status_code=200)

    except Exception as e:
        db.rollback()
        logger.error(f"スーパーユーザー作成エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=f"スーパーユーザー作成に失敗しました: {str(e)}")

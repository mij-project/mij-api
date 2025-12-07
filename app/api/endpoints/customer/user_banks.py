import os
import requests as REQUESTS_UTILS
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.crud.user_banks_curd import (
    check_bank_request_history,
    check_branch_request_history,
    check_existing_bank_master,
    check_user_bank_existing,
    create_bank_master,
    create_bank_request_history,
    create_branch_request_history,
    create_user_bank,
    get_default_bank_information_by_user_id,
)
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.core.logger import Logger
from app.schemas.user_banks import (
    UserDefaultBank,
    UserDefaultBankResponse,
    UserDefaultBankSettingRequest,
)
from app.api.commons.base64helper import encode_b64, decode_b64

BANKCODE_JP_API_URL = "https://apis.bankcode-jp.com/v3"
BANKCODE_JP_API_KEY = os.environ.get("BANKCODE_JP_API_KEY", "rF4LJWVUtbK9QD5DbS67W8DIA6YgOn")

logger = Logger.get_logger()
router = APIRouter()


@router.get("/default")
async def get_default_bank(
    db: Session = Depends(get_db), current_user: Users = Depends(get_current_user)
):
    bank = get_default_bank_information_by_user_id(db, current_user.id)
    if bank is None:
        return UserDefaultBankResponse(user_bank=None)

    return UserDefaultBankResponse(
        user_bank=UserDefaultBank(
            id=str(bank.UserBanks.id),
            account_number=decode_b64(bank.UserBanks.account_number),
            account_holder_name=decode_b64(bank.UserBanks.account_holder_name),
            account_holder_name_kana=bank.UserBanks.account_holder_name_kana,
            account_type=int(bank.UserBanks.account_type),
            bank_code=bank.bank_code,
            bank_name=bank.bank_name,
            bank_name_kana=bank.bank_name_kana,
            branch_code=bank.branch_code,
            branch_name=bank.branch_name,
            branch_name_kana=bank.branch_name_kana,
            created_at=bank.UserBanks.created_at,
            updated_at=bank.UserBanks.updated_at,
        )
    )


@router.get("/banks-external")
async def get_banks_external(
    search: Optional[str] = Query(None, description="検索クエリ"),
    bank_code: Optional[str] = Query(
        None, description="銀行コード(未指定の場合は空文字列)"
    ),
    branch_code: Optional[str] = Query(
        None, description="支店コード(未指定の場合は空文字列)"
    ),
    type: int = Query(
        1,
        description="1=bank_search(銀行検索), 2=branch_search(支店検索), 3=account_verify(口座確認)",
    ),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    if type == 1:
        banks = _get_banks_by_search(db, current_user, search)
        return {"banks": banks}
    elif type == 2:
        branches = _get_branches_by_search(
            db, current_user, bank_code, search, branch_code
        )
        return {"branches": branches}


def _get_banks_by_search(db: Session, user: Users, search: str):
    history = check_bank_request_history(db, user.id, 1, search)
    if history is None:
        external_banks = __get_external_bankcode_api(search)
        if external_banks is None:
            return []
        bank_code = search if search else None
        create_bank_request_history(db, user.id, 1, bank_code, external_banks)
        return external_banks
    else:
        return history.response_data or []


def _get_branches_by_search(
    db: Session, user: Users, bank_code: str, search: str, branch_code: str
):
    if branch_code:
        history = check_branch_request_history(db, user.id, 2, branch_code, bank_code)
        if history is None:
            external_branches = __get_external_branchcode_api_with_code(
                bank_code, branch_code
            )
            if external_branches is None:
                return []
            create_branch_request_history(
                db, user.id, 2, bank_code, branch_code, external_branches
            )
            return external_branches
        else:
            return history.response_data or []
    else:
        history = check_branch_request_history(db, user.id, 2, search, bank_code)
        if history is None:
            external_branches = __get_external_branchcode_api_with_search(
                bank_code, search
            )
            if external_branches is None:
                return []
            search = search if search else None
            create_branch_request_history(
                db, user.id, 2, bank_code, search, external_branches
            )
            return external_branches
        else:
            return history.response_data or []


def __get_external_bankcode_api(search: str):
    try:
        logger.info(f"Call BankCode JP API for Bank ->{search}")
        if search:
            url = f"{BANKCODE_JP_API_URL}/banks?filter=name=re={search},hiragana=re={search},code=={search}&limit=100"
        else:
            url = f"{BANKCODE_JP_API_URL}/banks?limit=100"
        response = REQUESTS_UTILS.get(url, headers={"apiKey": BANKCODE_JP_API_KEY})
        if response.status_code != 200:
            logger.error(
                f"Failed to get banks from external API: {response.status_code}"
            )
            return None
        res = response.json()
        banks = res["banks"]
        return banks
    except Exception as e:
        logger.exception(f"Failed to get banks from external API: {e}")
        return None


def __get_external_branchcode_api_with_search(bank_code: str, search: str):
    try:
        logger.info(
            f"Call BankCode JP API for Branch -> bankcode: {bank_code}, search: {search}"
        )
        if search:
            url = f"{BANKCODE_JP_API_URL}/banks/{bank_code}/branches?filter=name=re={search},hiragana=re={search}&limit=100"
        else:
            url = f"{BANKCODE_JP_API_URL}/banks/{bank_code}/branches?limit=100"
        response = REQUESTS_UTILS.get(url, headers={"apiKey": BANKCODE_JP_API_KEY})
        if response.status_code != 200:
            logger.error(
                f"Failed to get branches from external API: {response.status_code}"
            )
            return None
        res = response.json()
        branches = res["branches"]
        return branches
    except Exception as e:
        logger.exception(f"Failed to get branches from external API: {e}")
        return None


def __get_external_branchcode_api_with_code(bank_code: str, code: str):
    try:
        logger.info(
            f"Call BankCode JP API for Branch -> bankcode: {bank_code}, code: {code}"
        )
        url = f"{BANKCODE_JP_API_URL}/banks/{bank_code}/branches?filter=code=={code}&limit=100"
        response = REQUESTS_UTILS.get(url, headers={"apiKey": BANKCODE_JP_API_KEY})
        if response.status_code != 200:
            logger.error(
                f"Failed to get branches from external API: {response.status_code}"
            )
            return None
        res = response.json()
        branches = res["branches"]
        return branches
    except Exception as e:
        logger.exception(f"Failed to get branches from external API: {e}")
        return None


@router.post("/setting-default")
async def set_default_bank(
    payload: UserDefaultBankSettingRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    logger.info(f"Set default bank: {payload} for user: {current_user.id}")
    # Check if exsiting bank or not
    existing_bank = check_existing_bank_master(
        db, payload.bank.code, payload.branch.code
    )
    if existing_bank is None:
        existing_bank = create_bank_master(db, payload.bank, payload.branch)
        if existing_bank is None:
            raise HTTPException(status_code=500, detail="Failed to create bank master")
    # Check if exsiting user bank or not
    existing_user_bank = check_user_bank_existing(
        db,
        current_user.id,
        existing_bank.id,
        encode_b64(payload.account_number),
        encode_b64(payload.account_holder),
    )
    if existing_user_bank is not None:
        return {"message": "Ok"}
    # Create user bank
    user_bank = create_user_bank(
        db,
        current_user.id,
        existing_bank.id,
        payload.account_type,
        encode_b64(payload.account_number),
        encode_b64(payload.account_holder),
    )
    if user_bank is None:
        raise HTTPException(status_code=500, detail="Failed to create user bank")

    return {"message": "Ok"}
